"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Alert, App, Button, Card, Descriptions, Empty, InputNumber, Progress, Select, Spin, Statistic, Table, Tag } from "antd";
import { BarChartOutlined, CheckCircleOutlined, ExperimentOutlined, RiseOutlined, SafetyCertificateOutlined, SendOutlined } from "@ant-design/icons";
import { useCreateExperiment, usePrediction, useProducts, useUpdateCampaign } from "@/hooks";
import PageHeader from "@/components/PageHeader";
import { api } from "@/lib/api";
import type { PredictionResponse } from "@/types";

type BatchPrediction = { scheme_id: number; scheme_name: string; prediction: PredictionResponse | null; error?: string };

export default function PredictionContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const campaignId = searchParams.get("campaignId");
  const [selectedProductId, setSelectedProductId] = useState<number | null>(null);
  const [selectedSchemeIds, setSelectedSchemeIds] = useState<number[]>([]);
  const [predicting, setPredicting] = useState(false);
  const [predictionResults, setPredictionResults] = useState<BatchPrediction[]>([]);
  const [experimentCandidates, setExperimentCandidates] = useState<number[]>([]);
  const { data: productsData, isPending: productsLoading } = useProducts(1, 50);
  const { message } = App.useApp();
  const createExperiment = useCreateExperiment();
  const updateCampaign = useUpdateCampaign();
  const products = productsData?.items || [];
  const selectedProduct = products.find((product) => product.id === selectedProductId);

  const handleProductSelect = (id: number) => {
    setSelectedProductId(id);
    setSelectedSchemeIds([]);
    setPredictionResults([]);
    setExperimentCandidates([]);
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
    setExperimentCandidates([]);
    setPredicting(false);
    if (campaignId) {
      const generatedImageIds = results.flatMap((result) => result.prediction?.image_id ? [result.prediction.image_id] : []);
      try {
        await updateCampaign.mutateAsync({
          campaignId,
          body: {
            image_ids: generatedImageIds,
            current_stage: "experiment",
            status: "in_progress",
            next_step: "从可信且低风险的方案中选择两项，进入 A/B 实验验证。",
          },
        });
      } catch {
        message.warning("预测完成，活动状态将在后台同步。");
      }
    }
    message.success(`预测完成：${results.filter((result) => result.prediction).length}/${results.length} 个方案成功`);
  };

  const decisionSummary = useMemo(() => buildDecisionSummary(predictionResults), [predictionResults]);

  const toggleExperimentCandidate = (imageId: number) => {
    setExperimentCandidates((previous) => {
      if (previous.includes(imageId)) return previous.filter((item) => item !== imageId);
      if (previous.length >= 2) {
        message.warning("一次实验仅选择两个方案；请先取消其中一个候选。 ");
        return previous;
      }
      return [...previous, imageId];
    });
  };

  const createExperimentFromCandidates = async () => {
    if (!selectedProductId || experimentCandidates.length !== 2) {
      message.warning("请选择同一商品下的两个方案后再创建实验。");
      return;
    }
    try {
      const experiment = await createExperiment.mutateAsync({
        product_id: selectedProductId,
        variant_a_image_id: experimentCandidates[0],
        variant_b_image_id: experimentCandidates[1],
        traffic_ratio: 0.5,
      });
      if (campaignId) {
        try {
          await updateCampaign.mutateAsync({
            campaignId,
            body: {
              experiment_ids: [experiment.id],
              current_stage: "experiment",
              status: "experimenting",
              next_step: "观察实验结果，确认胜出策略后进入复盘。",
            },
          });
        } catch {
          message.warning("实验已创建，活动关联将在后台同步。");
        }
      }
      message.success("A/B 实验已创建，正在按 50/50 流量分配验证。");
      router.push(`/experiments/${experiment.id}${campaignId ? `?campaignId=${encodeURIComponent(campaignId)}` : ""}`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建实验失败，请稍后重试");
    }
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
        <Card
          title="经营决策建议"
          extra={
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">已完成 {predictionResults.length} 个方案评估</span>
              <Button
                type="primary"
                icon={<ExperimentOutlined />}
                disabled={experimentCandidates.length !== 2}
                loading={createExperiment.isPending}
                onClick={createExperimentFromCandidates}
              >
                用已选 {experimentCandidates.length}/2 创建 A/B 实验
              </Button>
            </div>
          }
        >
          <Alert
            type="info"
            showIcon
            className="mb-4"
            message="建议不是自动执行"
            description="系统展示预测、置信度与风险依据；运营人员选择进入审核、实验或保留观察，所有决策仍由团队确认。"
          />
          <div className="office-decision-grid">
            {predictionResults.map((row) => {
              const decision = getDecision(row, decisionSummary);
              const imageId = row.prediction?.image_id;
              const selected = imageId != null && experimentCandidates.includes(imageId);
              return (
                <article key={row.scheme_id} className={`office-decision-card office-decision-card--${decision.tone}`}>
                  <header>
                    <div><span className="office-decision-card__eyebrow">适用市场：{(selectedProduct?.target_markets || []).join("、").toUpperCase() || "当前商品市场"}</span><h3>{row.scheme_name}</h3></div>
                    <Tag color={decision.color}>{decision.label}</Tag>
                  </header>
                  {row.error ? <Alert type="error" showIcon message={row.error} /> : (
                    <>
                      <p className="office-decision-card__summary">{decision.summary}</p>
                      <div className="office-decision-card__metrics">
                        <div><span>预估 CTR</span><strong>{formatPercent(row.prediction?.predicted_ctr, 2)}</strong></div>
                        <div><span>爆款概率</span><strong>{formatPercent(row.prediction?.predicted_hit_probability, 0)}</strong></div>
                        <div><span>退货风险</span><strong><RiskLabel level={row.prediction?.return_risk_level} /></strong></div>
                      </div>
                      <div className="office-decision-card__evidence">
                        <strong>依据</strong>
                        <span>{confidenceText(row.prediction)}；{riskText(row.prediction)}。预测结果来自该方案对应素材的视觉特征与当前模型版本，不替代真实实验。</span>
                      </div>
                      <div className="office-decision-card__actions">
                        {decision.action === "review" && imageId != null && <Button icon={<SendOutlined />} onClick={() => router.push(`/review?imageId=${imageId}${campaignId ? `&campaignId=${encodeURIComponent(campaignId)}` : ""}`)}>送人工审核</Button>}
                        {decision.action === "experiment" && imageId != null && <Button type={selected ? "primary" : "default"} icon={<ExperimentOutlined />} onClick={() => toggleExperimentCandidate(imageId)}>{selected ? "已加入实验候选" : "加入实验候选"}</Button>}
                        {imageId != null && <Button type="link" onClick={() => router.push(`/images/${imageId}`)}>查看素材</Button>}
                      </div>
                    </>
                  )}
                </article>
              );
            })}
          </div>
        </Card>
      )}

      {selectedProduct && !selectedProduct.schemes.length && <Alert type="warning" showIcon title="该商品暂无关联的视觉方案" description="请先在发品工作台创建方案，再回到此处进行效果预测。" />}
      {!selectedProduct && <Card><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一个商品后开始方案预测" /></Card>}

      <Card title="快速单图预测" extra={<span className="text-xs text-slate-400">输入已生成图片的 ID</span>}><SingleImagePredictor /></Card>
    </main>
  );
}

function buildDecisionSummary(rows: BatchPrediction[]) {
  const ctrs = rows
    .map((item) => item.prediction?.predicted_ctr)
    .filter((value): value is number => typeof value === "number");
  return {
    avgCtr: ctrs.length ? ctrs.reduce((sum, value) => sum + value, 0) / ctrs.length : null,
    topCtr: ctrs.length ? Math.max(...ctrs) : null,
  };
}

function getDecision(row: BatchPrediction, benchmark: ReturnType<typeof buildDecisionSummary>) {
  const prediction = row.prediction;
  if (!prediction || row.error) {
    return { tone: "neutral", color: "default", label: "需重试", action: "none", summary: "本次预测没有返回有效结果，请检查素材状态后重新计算。" };
  }
  const ctr = prediction.predicted_ctr ?? 0;
  const confidence = prediction.ctr_confidence_interval;
  const range = confidence ? confidence.upper - confidence.lower : undefined;
  const uplift = benchmark.avgCtr && benchmark.avgCtr > 0 ? (ctr - benchmark.avgCtr) / benchmark.avgCtr : 0;
  if (prediction.return_risk_level === "high") {
    return { tone: "risk", color: "red", label: "先控制风险", action: "review", summary: "退货风险处于高位。建议先由人工核查素材表达、尺码信息与市场合规，不直接进入投放。" };
  }
  if (prediction.return_risk_level === "medium" || (range != null && range > 0.035)) {
    return { tone: "caution", color: "orange", label: "小流量验证", action: "review", summary: "结果存在不确定性或中等退货风险。建议先补充审核，再以小流量验证，不宜直接放量。" };
  }
  if (benchmark.topCtr != null && ctr >= benchmark.topCtr * 0.94 && (prediction.predicted_hit_probability ?? 0) >= 0.45) {
    const upliftText = uplift > 0.01 ? `，相对已选方案均值高约 ${(uplift * 100).toFixed(0)}%` : "";
    return { tone: "opportunity", color: "green", label: "建议进入 A/B", action: "experiment", summary: `该方案具备较高点击潜力且当前退货风险可控${upliftText}。建议与另一候选方案进入 A/B 实验确认真实增益。` };
  }
  return { tone: "neutral", color: "blue", label: "保留观察", action: "experiment", summary: "预测表现处于候选方案中段。可作为备选进入小范围实验，优先与高潜力方案做对照。" };
}

function formatPercent(value?: number, digits = 1) {
  return typeof value === "number" ? `${(value * 100).toFixed(digits)}%` : "—";
}

function confidenceText(prediction?: PredictionResponse | null) {
  const interval = prediction?.ctr_confidence_interval;
  if (!interval) return "暂未返回置信区间";
  return `CTR 置信区间 ${formatPercent(interval.lower, 2)}–${formatPercent(interval.upper, 2)}`;
}

function riskText(prediction?: PredictionResponse | null) {
  const probability = prediction?.return_risk_probability;
  const source = prediction?.return_risk_source === "model" ? "模型判断" : prediction?.return_risk_source === "heuristic" ? "规则辅助判断" : "风险评估";
  return `${source}${probability != null ? `，风险概率 ${formatPercent(probability, 0)}` : ""}`;
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
    {prediction && <><section className="office-metric-grid">
      <Card className="office-metric-card"><Statistic title="预估 CTR" value={prediction.predicted_ctr != null ? `${(prediction.predicted_ctr * 100).toFixed(2)}%` : "—"} prefix={<RiseOutlined style={{ color: "#2563EB" }} />} styles={{ content: { color: "#2563EB" } }} />{prediction.ctr_confidence_interval && <div className="text-xs text-slate-400">置信区间：{(prediction.ctr_confidence_interval.lower * 100).toFixed(2)}% – {(prediction.ctr_confidence_interval.upper * 100).toFixed(2)}%</div>}</Card>
      <Card className="office-metric-card"><Statistic title="爆款概率" value={prediction.predicted_hit_probability != null ? `${(prediction.predicted_hit_probability * 100).toFixed(0)}%` : "—"} styles={{ content: { color: (prediction.predicted_hit_probability || 0) > 0.5 ? "#087B5A" : "#A56A00" } }} /><Progress percent={prediction.predicted_hit_probability != null ? Math.round(prediction.predicted_hit_probability * 100) : 0} showInfo={false} strokeColor={(prediction.predicted_hit_probability || 0) > 0.5 ? "#087B5A" : "#A56A00"} /></Card>
      <Card className="office-metric-card"><Statistic title="退货风险" value={prediction.return_risk_level === "low" ? "低风险" : prediction.return_risk_level === "medium" ? "中风险" : prediction.return_risk_level === "high" ? "高风险" : "—"} prefix={<SafetyCertificateOutlined />} styles={{ content: { color: prediction.return_risk_level === "low" ? "#087B5A" : prediction.return_risk_level === "medium" ? "#A56A00" : "#C2413A" } }} /></Card>
      <Card className="office-metric-card"><Statistic title="预测时间" value={prediction.predicted_at?.split("T")[0] || "—"} styles={{ content: { fontSize: 17 } }} /></Card>
    </section>
    <Card size="small" title="预测依据与边界">
      <Descriptions size="small" column={1}>
        <Descriptions.Item label="不确定性">{confidenceText(prediction)}</Descriptions.Item>
        <Descriptions.Item label="风险来源">{riskText(prediction)}</Descriptions.Item>
        <Descriptions.Item label="归因说明">{summarizeRecord(prediction.return_risk, "当前风险未触发细分归因；建议结合真实退货与审核结果复盘。")}</Descriptions.Item>
        <Descriptions.Item label="合规检查">{summarizeRecord(prediction.compliance, "尚未返回合规检查细节。")}</Descriptions.Item>
      </Descriptions>
    </Card></>}
  </div>;
}

function summarizeRecord(value: Record<string, unknown> | undefined, fallback: string) {
  if (!value || Object.keys(value).length === 0) return fallback;
  const values = Object.entries(value)
    .filter(([, item]) => typeof item === "string" || typeof item === "number" || typeof item === "boolean")
    .slice(0, 3)
    .map(([key, item]) => `${key}: ${String(item)}`);
  return values.length ? values.join("；") : "已返回结构化结果，请结合审核与真实经营数据判断。";
}
