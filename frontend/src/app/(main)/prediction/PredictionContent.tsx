"use client";

import { useState } from "react";
import { Alert, App, Button, Card, Empty, InputNumber, Progress, Select, Spin, Statistic, Table, Tag } from "antd";
import { BarChartOutlined, RiseOutlined, SafetyCertificateOutlined } from "@ant-design/icons";
import { usePrediction, useProducts } from "@/hooks";
import PageHeader from "@/components/PageHeader";
import { api } from "@/lib/api";
import type { PredictionResponse } from "@/types";

type BatchPrediction = { scheme_id: number; scheme_name: string; prediction: PredictionResponse | null; error?: string };

export default function PredictionContent() {
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [selectedSchemeIds, setSelectedSchemeIds] = useState<number[]>([]);
  const [predicting, setPredicting] = useState(false);
  const [predictionResults, setPredictionResults] = useState<BatchPrediction[]>([]);
  const { data: productsData, isPending: productsLoading } = useProducts(1, 50);
  const { message } = App.useApp();
  const products = productsData?.items || [];
  const selectedProduct = products.find((product) => product.id === selectedProductId);

  const handleProductSelect = (id: number) => {
    setSelectedProductId(id);
    setSelectedSchemeIds([]);
    setPredictionResults([]);
  };

  const handleBatchPredict = async () => {
    if (selectedSchemeIds.length === 0) {
      message.warning("请至少选择一张方案图片进行预测");
      return;
    }
    setPredicting(true);
    setPredictionResults([]);
    const schemes = selectedProduct?.schemes.filter((scheme) => selectedSchemeIds.includes(scheme.id)) || [];
    const results = await Promise.all(schemes.map(async (scheme) => {
      try {
        return { scheme_id: scheme.id, scheme_name: scheme.scheme_name, prediction: await api.predictByScheme(scheme.id) };
      } catch (error) {
        return { scheme_id: scheme.id, scheme_name: scheme.scheme_name, prediction: null, error: error instanceof Error ? error.message : "预测失败" };
      }
    }));
    setPredictionResults(results);
    setPredicting(false);
    message.success(`预测完成：${results.filter((result) => result.prediction).length}/${results.length} 个方案成功`);
  };

  return (
    <main className="office-workspace">
      <PageHeader title="预测决策面板" subtitle="出图前预估 CTR、爆款概率和退货风险，以数据辅助方案选择。" />

      <Card title="1. 选择商品">
        <div className="office-form-grid">
          <div className="office-form-field office-form-field--wide">
            <label>商品</label>
            <Select showSearch allowClear placeholder="按 SKU、标题或类目搜索商品" value={selectedProductId} onChange={handleProductSelect} loading={productsLoading} filterOption={(input, option) => (option?.label as string)?.toLowerCase().includes(input.toLowerCase())} options={products.map((product) => ({ value: product.id, label: `[${product.sku_code}] ${product.title} · ${product.category}` }))} />
          </div>
          {selectedProduct && <div className="office-selection-summary office-form-field--wide"><span className="text-xs text-slate-500">已选商品</span><strong className="text-sm text-slate-700">{selectedProduct.title}</strong><Tag>{selectedProduct.category}</Tag><Tag>{(selectedProduct.target_markets || []).join(", ").toUpperCase()}</Tag><Tag>{selectedProduct.status}</Tag></div>}
        </div>
      </Card>

      {selectedProduct && selectedProduct.schemes.length > 0 && (
        <Card title="2. 选择方案并预测" extra={<span className="text-xs text-slate-400">已选 {selectedSchemeIds.length} 项</span>}>
          <div className="office-table-toolbar"><span className="office-table-toolbar__meta">选择待比较的视觉方案；系统会并行计算每张图片的预估表现。</span><Button type="primary" icon={<BarChartOutlined />} onClick={handleBatchPredict} loading={predicting}>{predicting ? "正在预测…" : `预测已选方案（${selectedSchemeIds.length}）`}</Button></div>
          <Table
            rowSelection={{ selectedRowKeys: selectedSchemeIds, onChange: (keys) => setSelectedSchemeIds(keys as number[]) }}
            dataSource={selectedProduct.schemes.map((scheme) => ({ key: scheme.id, scheme_id: scheme.id, scheme_name: scheme.scheme_name, style_tags: scheme.style_tags, score: scheme.recommendation_score }))}
            columns={[
              { title: "方案名称", dataIndex: "scheme_name", key: "name", ellipsis: true },
              { title: "风格标签", dataIndex: "style_tags", key: "tags", render: (tags: Record<string, unknown> | undefined) => tags ? Object.values(tags).slice(0, 3).map((tag) => <Tag key={String(tag)}>{String(tag)}</Tag>) : "—" },
              { title: "推荐分", dataIndex: "score", key: "score", align: "right" as const, width: 112, render: (value: number | undefined) => value == null ? "—" : <span className="font-semibold tabular-nums text-slate-700">{value.toFixed(1)}</span> },
            ]}
            pagination={false}
            scroll={{ x: 560 }}
            locale={{ emptyText: "该商品暂无关联方案" }}
          />
        </Card>
      )}

      {predictionResults.length > 0 && (
        <Card title="预测结果" extra={<span className="text-xs text-slate-400">{predictionResults.length} 个方案</span>}>
          <Table
            dataSource={predictionResults}
            rowKey="scheme_id"
            scroll={{ x: 660 }}
            pagination={false}
            columns={[
              { title: "方案名称", dataIndex: "scheme_name", key: "name", width: 180, ellipsis: true },
              { title: "预估 CTR", key: "ctr", align: "right" as const, width: 120, render: (_: unknown, row: BatchPrediction) => row.prediction?.predicted_ctr != null ? <strong className="tabular-nums text-blue-700">{(row.prediction.predicted_ctr * 100).toFixed(2)}%</strong> : "—" },
              { title: "爆款概率", key: "hit", align: "right" as const, width: 120, render: (_: unknown, row: BatchPrediction) => row.prediction?.predicted_hit_probability != null ? <span className="tabular-nums">{(row.prediction.predicted_hit_probability * 100).toFixed(0)}%</span> : "—" },
              { title: "退货风险", key: "risk", width: 120, render: (_: unknown, row: BatchPrediction) => <RiskLabel level={row.prediction?.return_risk_level} /> },
              { title: "状态", key: "status", width: 180, render: (_: unknown, row: BatchPrediction) => row.error ? <span className="text-xs text-red-600">{row.error}</span> : <span className="text-xs text-emerald-700">预测完成</span> },
            ]}
          />
        </Card>
      )}

      {selectedProduct && !selectedProduct.schemes.length && <Alert type="warning" showIcon title="该商品暂无关联的视觉方案" description="请先在发品工作台创建方案，再回到此处进行效果预测。" />}
      {!selectedProduct && <Card><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一个商品后开始方案预测" /></Card>}

      <Card title="快速单图预测" extra={<span className="text-xs text-slate-400">输入已生成图片的 ID</span>}><SingleImagePredictor /></Card>
    </main>
  );
}

function RiskLabel({ level }: { level?: string }) {
  if (level === "low") return <span className="text-emerald-700">低风险</span>;
  if (level === "medium") return <span className="text-amber-700">中风险</span>;
  if (level === "high") return <span className="text-red-700">高风险</span>;
  return <span className="text-slate-400">—</span>;
}

function SingleImagePredictor() {
  const [imageId, setImageId] = useState<number | null>(null);
  const { data: prediction, isPending, error } = usePrediction(imageId ?? 0);
  return <div className="office-workspace" style={{ gap: 18 }}>
    <div className="office-form-grid"><div className="office-form-field"><label>图片 ID</label><InputNumber placeholder="例如 1024" value={imageId} onChange={setImageId} min={1} style={{ width: "100%" }} /></div><div className="office-form-field"><label>说明</label><span className="text-sm text-slate-500">输入任意已生成图片的 ID，立即查看效果预测。</span></div></div>
    {error && <Alert type="error" showIcon title={error instanceof Error ? error.message : "预测失败"} />}
    {isPending && imageId && <Spin description="正在计算预测…" />}
    {prediction && <section className="office-metric-grid">
      <Card className="office-metric-card"><Statistic title="预估 CTR" value={prediction.predicted_ctr != null ? `${(prediction.predicted_ctr * 100).toFixed(2)}%` : "—"} prefix={<RiseOutlined style={{ color: "#2563EB" }} />} styles={{ content: { color: "#2563EB" } }} />{prediction.ctr_confidence_interval && <div className="text-xs text-slate-400">置信区间：{(prediction.ctr_confidence_interval.lower * 100).toFixed(2)}% – {(prediction.ctr_confidence_interval.upper * 100).toFixed(2)}%</div>}</Card>
      <Card className="office-metric-card"><Statistic title="爆款概率" value={prediction.predicted_hit_probability != null ? `${(prediction.predicted_hit_probability * 100).toFixed(0)}%` : "—"} styles={{ content: { color: (prediction.predicted_hit_probability || 0) > 0.5 ? "#087B5A" : "#A56A00" } }} /><Progress percent={prediction.predicted_hit_probability != null ? Math.round(prediction.predicted_hit_probability * 100) : 0} showInfo={false} strokeColor={(prediction.predicted_hit_probability || 0) > 0.5 ? "#087B5A" : "#A56A00"} /></Card>
      <Card className="office-metric-card"><Statistic title="退货风险" value={prediction.return_risk_level === "low" ? "低风险" : prediction.return_risk_level === "medium" ? "中风险" : prediction.return_risk_level === "high" ? "高风险" : "—"} prefix={<SafetyCertificateOutlined />} styles={{ content: { color: prediction.return_risk_level === "low" ? "#087B5A" : prediction.return_risk_level === "medium" ? "#A56A00" : "#C2413A" } }} /></Card>
      <Card className="office-metric-card"><Statistic title="预测时间" value={prediction.predicted_at?.split("T")[0] || "—"} styles={{ content: { fontSize: 17 } }} /></Card>
    </section>}
  </div>;
}
