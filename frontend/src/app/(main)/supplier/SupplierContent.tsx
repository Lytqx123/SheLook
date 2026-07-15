"use client";

import { useState, useCallback } from "react";
import {
  Card, Upload, Button, Select, Input, App, Spin, Descriptions,
  Tag, Table, Progress, Empty, Space, Typography, Row, Col,
} from "antd";
import {
  UploadOutlined, ThunderboltOutlined, TrophyOutlined,
  BulbOutlined, RiseOutlined, HistoryOutlined,
} from "@ant-design/icons";
import type { UploadFile } from "antd";
import type { ColumnsType } from "antd/es/table";
import { api } from "@/lib/api";
import { useSupplierReports } from "@/hooks";
import type { SupplierReport, SupplierReportHistoryItem } from "@/types";
import PageHeader from "@/components/PageHeader";

const { Text, Paragraph } = Typography;
const { Option } = Select;

// ---- 常量 ----

const DIM_LABELS: Record<string, string> = {
  sharpness: "清晰度",
  lighting_uniformity: "光照均匀度",
  color_harmony: "色彩和谐度",
  composition_balance: "构图均衡度",
  information_density: "信息密度",
};

const VERDICT_COLORS: Record<string, string> = {
  auto_approved: "#52C41A",
  manual_pending: "#FAAD14",
  rejected: "#FF4D4F",
};

const VERDICT_LABELS: Record<string, string> = {
  auto_approved: "自动通过",
  manual_pending: "待人工审核",
  rejected: "不合格",
};

const MARKETS = ["SG", "MY", "TH", "ID", "VN", "PH", "TW", "BR", "MX", "CO"];

const CATEGORIES = [
  "dress", "shoes", "tops", "bottoms", "outerwear",
  "accessories", "bags", "lingerie", "sportswear", "kids",
];

export default function SupplierContent() {
  const [imageUrl, setImageUrl] = useState("");
  const [category, setCategory] = useState("dress");
  const [market, setMarket] = useState("SG");
  const [loading, setLoading] = useState(false);
  const [report, setReport] = useState<SupplierReport | null>(null);

  // 历史报告：通过 useSupplierReports hook 拉取，点击"查询历史"按钮触发
  const [historyInputId, setHistoryInputId] = useState("");
  const [historyQueryId, setHistoryQueryId] = useState("");
  const { data: historyData, isLoading: historyLoading } = useSupplierReports(historyQueryId);
  const { message } = App.useApp();
  const history: SupplierReportHistoryItem[] = historyData?.reports ?? [];

  const handleAnalyze = useCallback(async () => {
    if (!imageUrl.trim()) {
      message.warning("请输入图片 URL");
      return;
    }
    setLoading(true);
    try {
      const data = await api.analyzeSupplierImage({ image_url: imageUrl, category, market });
      setReport(data);
      message.success("分析完成");
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "分析失败");
    } finally {
      setLoading(false);
    }
  }, [imageUrl, category, market]);

  const handleQueryHistory = useCallback(() => {
    if (!historyInputId.trim()) {
      message.warning("请输入供应商 ID");
      return;
    }
    setHistoryQueryId(historyInputId.trim());
  }, [historyInputId]);

  const scoreColor = (score: number) => {
    if (score >= 75) return "#52C41A";
    if (score >= 60) return "#FAAD14";
    return "#FF4D4F";
  };

  const historyColumns: ColumnsType<SupplierReportHistoryItem> = [
    {
      title: "图片",
      dataIndex: "image_url",
      key: "image_url",
      width: 80,
      render: (url: string) => (
        // 外部供应商 URL，使用 <img> 避免 next/image remotePatterns 配置
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={url}
          alt="商品图"
          style={{ width: 56, height: 56, objectFit: "cover", borderRadius: 6 }}
          onError={(e) => {
            (e.target as HTMLImageElement).src =
              "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='56' height='56'><rect fill='%23f0f0f0' width='56' height='56'/><text x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='%23999' font-size='9'>N/A</text></svg>";
          }}
        />
      ),
    },
    {
      title: "品类",
      dataIndex: "category",
      key: "category",
      width: 100,
    },
    {
      title: "市场",
      dataIndex: "market",
      key: "market",
      width: 80,
    },
    {
      title: "得分",
      dataIndex: "overall_score",
      key: "overall_score",
      width: 90,
      render: (score: number) => (
        <Text strong style={{ color: scoreColor(score) }}>
          {score}
        </Text>
      ),
    },
    {
      title: "判定",
      dataIndex: "quality_verdict",
      key: "quality_verdict",
      width: 110,
      render: (verdict: string) => (
        <Tag color={VERDICT_COLORS[verdict] || "#999"}>
          {VERDICT_LABELS[verdict] || verdict}
        </Tag>
      ),
    },
    {
      title: "分析时间",
      dataIndex: "analyzed_at",
      key: "analyzed_at",
      render: (ts: string) => (ts ? new Date(ts).toLocaleString("zh-CN") : "-"),
    },
  ];

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <PageHeader
        title="供应商分析"
        subtitle="上传商品图片，获取质量评分、品类标杆对比与可执行的视觉改进建议"
      />

      {/* ---- 输入区 ---- */}
      <Card style={{ marginBottom: 24 }}>
        <Space orientation="vertical" style={{ width: "100%" }} size="middle">
          <Space.Compact style={{ width: "100%" }}>
            <Input
              size="large"
              placeholder="输入图片 URL（如 https://minio.example.com/product-images/xxx.jpg）"
              value={imageUrl}
              onChange={(e) => setImageUrl(e.target.value)}
              onPressEnter={handleAnalyze}
            />
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={loading}
              onClick={handleAnalyze}
            >
              开始分析
            </Button>
          </Space.Compact>
          <Space wrap>
            <Select value={category} onChange={setCategory} style={{ width: 140 }}>
              {CATEGORIES.map((c) => (
                <Option key={c} value={c}>{c}</Option>
              ))}
            </Select>
            <Select value={market} onChange={setMarket} style={{ width: 100 }}>
              {MARKETS.map((m) => (
                <Option key={m} value={m}>{m}</Option>
              ))}
            </Select>
          </Space>
        </Space>
      </Card>

      {/* ---- 分析结果 ---- */}
      {loading && (
        <Card>
          <div style={{ textAlign: "center", padding: 60 }}>
            <Spin size="large" />
            <Paragraph style={{ marginTop: 16 }}>正在分析图片质量...</Paragraph>
          </div>
        </Card>
      )}

      {report && !loading && (
        <>
          {/* 概览 */}
          <Card style={{ marginBottom: 24 }}>
            <Row gutter={24} align="middle">
              <Col flex="200px">
                {/* 外部供应商 URL，使用 <img> 避免 next/image remotePatterns 配置 */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={report.image_url}
                  alt="商品图"
                  style={{ width: 200, height: 200, objectFit: "cover", borderRadius: 8 }}
                  onError={(e) => {
                    (e.target as HTMLImageElement).src = "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><rect fill='%23f0f0f0' width='200' height='200'/><text x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' fill='%23999'>图片加载失败</text></svg>";
                  }}
                />
              </Col>
              <Col flex="auto">
                <Descriptions column={2} size="small">
                  <Descriptions.Item label="综合得分">
                    <Text strong style={{ fontSize: 24, color: scoreColor(report.overall_score) }}>
                      {report.overall_score}
                    </Text>
                    <Text type="secondary"> / 100</Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="质量判定">
                    <Tag color={VERDICT_COLORS[report.quality_verdict] || "#999"}>
                      {VERDICT_LABELS[report.quality_verdict] || report.quality_verdict}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="L1 合规">
                    <Tag color={report.l1_passed ? "green" : "red"}>
                      {report.l1_passed ? "通过" : "未通过"}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="品类">
                    {report.category} / {report.market}
                  </Descriptions.Item>
                  {report.predicted_ctr != null && (
                    <Descriptions.Item label="预测 CTR">
                      {(report.predicted_ctr * 100).toFixed(2)}%
                      {report.normalized_ctr != null && (
                        <Text type="secondary"> (归一化: {report.normalized_ctr.toFixed(2)})</Text>
                      )}
                    </Descriptions.Item>
                  )}
                  {report.return_risk_probability != null && (
                    <Descriptions.Item label="退货风险">
                      <Text style={{ color: report.return_risk_probability > 0.1 ? "#FF4D4F" : "#52C41A" }}>
                        {(report.return_risk_probability * 100).toFixed(1)}%
                      </Text>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </Col>
            </Row>
          </Card>

          {/* 维度对比 */}
          <Card title={<><TrophyOutlined /> 维度得分与标杆对比</>} style={{ marginBottom: 24 }}>
            {report.benchmark && (
              <Paragraph type="secondary" style={{ marginBottom: 16 }}>
                品类「{report.category}」Top 20% CTR 标杆，共 {report.benchmark.sample_count} 个样本
              </Paragraph>
            )}
            <Space orientation="vertical" style={{ width: "100%" }} size="middle">
              {report.dimensions.map((dim) => (
                <div key={dim.name}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                    <Text strong>{dim.display_name}</Text>
                    <Space size="small">
                      <Text style={{ color: scoreColor(dim.score) }}>{dim.score.toFixed(1)}</Text>
                      <Text type="secondary">/ 标杆 {dim.benchmark.toFixed(1)}</Text>
                      <Tag color={dim.gap >= 0 ? "green" : "orange"} style={{ margin: 0 }}>
                        {dim.gap >= 0 ? `+${dim.gap.toFixed(1)}` : dim.gap.toFixed(1)}
                      </Tag>
                    </Space>
                  </div>
                  <Progress
                    percent={Math.min(100, dim.score)}
                    strokeColor={scoreColor(dim.score)}
                    showInfo={false}
                    size="small"
                  />
                  <div style={{ position: "relative", height: 4 }}>
                    <div
                      style={{
                        position: "absolute",
                        left: `${Math.min(100, dim.benchmark)}%`,
                        top: -2,
                        width: 2,
                        height: 8,
                        background: "#FF4D4F",
                        borderRadius: 1,
                      }}
                    />
                  </div>
                </div>
              ))}
            </Space>
          </Card>

          {/* 改进建议 */}
          <Card
            title={<><BulbOutlined /> 改进建议</>}
            style={{ marginBottom: 24 }}
          >
            {report.suggestions.map((s, i) => (
              <Card
                key={`${s.dimension}-${i}`}
                size="small"
                style={{ marginBottom: 12 }}
                title={
                  <Space>
                    <Tag color="blue">#{s.priority}</Tag>
                    <Text strong>{s.title}</Text>
                    <Tag>{DIM_LABELS[s.dimension] || s.dimension}</Tag>
                  </Space>
                }
              >
                <Paragraph>{s.description}</Paragraph>
                <Paragraph type="secondary">
                  <RiseOutlined /> {s.expected_improvement}
                </Paragraph>
              </Card>
            ))}
          </Card>
        </>
      )}

      {!report && !loading && (
        <Empty
          description="输入图片 URL 开始分析"
          style={{ padding: 60 }}
        />
      )}

      {/* ---- 历史分析报告 ---- */}
      <Card
        title={<><HistoryOutlined /> 历史分析报告</>}
        style={{ marginTop: 24 }}
      >
        <Space style={{ marginBottom: 16 }} wrap>
          <Input
            placeholder="输入供应商 ID，查询其历史分析报告"
            value={historyInputId}
            onChange={(e) => setHistoryInputId(e.target.value)}
            onPressEnter={handleQueryHistory}
            style={{ width: 320 }}
            allowClear
          />
          <Button
            type="primary"
            icon={<HistoryOutlined />}
            loading={historyLoading}
            onClick={handleQueryHistory}
          >
            查询历史
          </Button>
        </Space>
        <Table
          rowKey="report_id"
          columns={historyColumns}
          dataSource={history}
          loading={historyLoading}
          pagination={{ pageSize: 10, showSizeChanger: false }}
          size="middle"
          scroll={{ x: 600 }}
          locale={{
            emptyText: historyQueryId
              ? "该供应商暂无历史报告"
              : "输入供应商 ID 后点击“查询历史”",
          }}
        />
      </Card>
    </div>
  );
}
