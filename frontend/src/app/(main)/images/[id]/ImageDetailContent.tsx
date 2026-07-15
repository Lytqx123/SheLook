"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Card, Button, Tag, Descriptions, Result, Skeleton, Statistic,
  Row, Col, Image, Select, Input, Space, App, Table, Progress, Empty,
} from "antd";
import {
  ArrowLeftOutlined, PictureOutlined, FileProtectOutlined,
  ExportOutlined, CheckCircleOutlined, EyeOutlined, HistoryOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import QualityRadar from "@/components/QualityRadar";
import {
  useGenerationStatus, usePrediction, usePredictionHistory,
  useExportPlatforms, useExportImage,
  useCheckTextMatch, useEvaluateAesthetic,
  useGenerationWebSocket,
} from "@/hooks";
import { REVIEW_STATUS_MAP } from "@/constants";
import type { TextMatchResponse, VisionRewardResponse, PredictionHistoryItem } from "@/types";

export default function ImageDetailContent() {
  const params = useParams();
  const router = useRouter();
  const imageId = Number(params.id);

  const { data: genStatus, isPending, error } = useGenerationStatus(imageId, 5000);
  // WebSocket 实时进度：收到消息自动触发轮询刷新，降低完成感知延迟；失败时静默降级为轮询
  const { connectionState: wsState } = useGenerationWebSocket(imageId);
  const { data: prediction } = usePrediction(imageId, genStatus?.status === "completed");
  const { data: predHistory } = usePredictionHistory(imageId);
  const { data: platforms } = useExportPlatforms();

  const exportMutation = useExportImage();
  const textMatchMutation = useCheckTextMatch();
  const aestheticMutation = useEvaluateAesthetic();

  // 导出
  const [exportPlatform, setExportPlatform] = useState<string>("");
  // 图文匹配
  const [matchTitle, setMatchTitle] = useState("");
  const [matchDesc, setMatchDesc] = useState("");
  const [matchTags, setMatchTags] = useState("");
  const [matchResult, setMatchResult] = useState<TextMatchResponse | null>(null);
  // 美学评估
  const [aestheticResult, setAestheticResult] = useState<VisionRewardResponse | null>(null);
  const { message } = App.useApp();

  if (isNaN(imageId)) {
    return (
        <Result
          status="error"
          title="无效的图片 ID"
          extra={<Button onClick={() => router.push("/publish")}>返回发品工作台</Button>}
        />
    );
  }

  if (isPending) {
    return (
        <div className="space-y-6" style={{ maxWidth: 1280, margin: "0 auto" }}>
          <Skeleton active paragraph={{ rows: 1 }} />
          <Skeleton active paragraph={{ rows: 8 }} />
        </div>
    );
  }

  if (error || !genStatus) {
    return (
        <Result
          status="error"
          title="无法加载图片详情"
          subTitle={error instanceof Error ? error.message : "图片不存在或已被删除"}
          extra={<Button onClick={() => router.push("/publish")}>返回发品工作台</Button>}
        />
    );
  }

  if (genStatus.status === "failed") {
    return (
      <Result
        status="error"
        title="图片生成失败"
        subTitle={genStatus.error_message || "生成任务未能完成，请重新提交"}
        extra={<Button onClick={() => router.push("/publish")}>返回发品工作台</Button>}
      />
    );
  }

  const reviewInfo = REVIEW_STATUS_MAP[genStatus.review_status || ""] || {
    color: "default", label: genStatus.review_status || "未知",
  };

  const imageUrl = genStatus.image_url;

  // 导出
  const handleExport = async () => {
    if (!exportPlatform) { message.warning("请选择目标平台"); return; }
    message.loading({ content: "正在导出...", key: "export" });
    try {
      const blob = await exportMutation.mutateAsync({ imageId, platform: exportPlatform });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `image_${imageId}_${exportPlatform}.jpg`;
      a.click();
      URL.revokeObjectURL(url);
      message.success({ content: "导出成功", key: "export" });
    } catch (e: unknown) {
      message.error({ content: e instanceof Error ? e.message : "导出失败", key: "export" });
    }
  };

  // 图文匹配
  const handleTextMatch = async () => {
    if (!imageUrl || !matchTitle.trim()) { message.warning("需要图片 URL 和商品标题"); return; }
    setMatchResult(null);
    try {
      const res = await textMatchMutation.mutateAsync({
        image_path: imageUrl,
        product_title: matchTitle,
        product_description: matchDesc || undefined,
        tags: matchTags ? matchTags.split(",").map((t) => t.trim()).filter(Boolean) : undefined,
      });
      setMatchResult(res);
      message.success(res.match ? "图文匹配通过" : "图文匹配度较低");
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "验证失败");
    }
  };

  // 美学评估
  const handleAesthetic = async () => {
    if (!imageUrl) { message.warning("图片尚未生成"); return; }
    setAestheticResult(null);
    try {
      const res = await aestheticMutation.mutateAsync({ image_path: imageUrl });
      setAestheticResult(res);
      message.success("美学评估完成");
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "评估失败");
    }
  };

  // 预测历史列
  const historyColumns: ColumnsType<PredictionHistoryItem> = [
    { title: "记录 ID", dataIndex: "id", key: "id", width: 80 },
    {
      title: "预估 CTR", dataIndex: "predicted_ctr", key: "ctr", width: 120,
      render: (v?: number) => v != null ? `${(v * 100).toFixed(2)}%` : "—",
    },
    {
      title: "置信区间", key: "ci", width: 180,
      render: (_, r) => {
        const lower = r.ctr_confidence_interval?.lower;
        const upper = r.ctr_confidence_interval?.upper;
        return typeof lower === "number" && Number.isFinite(lower)
          && typeof upper === "number" && Number.isFinite(upper)
          ? `${(lower * 100).toFixed(2)}% ~ ${(upper * 100).toFixed(2)}%`
          : "—";
      },
    },
    {
      title: "爆款概率", dataIndex: "predicted_hit_probability", key: "hit", width: 100,
      render: (v?: number) => v != null ? `${(v * 100).toFixed(0)}%` : "—",
    },
    {
      title: "退货风险", dataIndex: "return_risk_level", key: "risk", width: 100,
      render: (v?: string) => {
        const map: Record<string, { color: string; label: string }> = {
          low: { color: "green", label: "低" },
          medium: { color: "orange", label: "中" },
          high: { color: "red", label: "高" },
        };
        const m = map[v || ""] || { color: "default", label: v || "—" };
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
    {
      title: "预测时间", dataIndex: "predicted_at", key: "time",
      render: (v?: string) => v ? new Date(v).toLocaleString("zh-CN") : "—",
    },
  ];

  return (
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.back()} style={{ marginBottom: 20 }}>
          返回
        </Button>

        {/* 图片预览 + 基本信息 */}
        <Row gutter={24} style={{ marginBottom: 20 }}>
          <Col xs={24} md={12}>
            <Card>
              <div className="aspect-square bg-gray-100 rounded-lg overflow-hidden flex items-center justify-center">
                {imageUrl ? (
                  <Image
                    src={imageUrl}
                    alt={`Generated image ${imageId}`}
                    className="w-full h-full object-contain"
                    fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Crect fill='%23f5f5f5' width='200' height='200'/%3E%3Ctext x='100' y='95' text-anchor='middle' fill='%23999' font-size='16' font-family='sans-serif'%3E图片%3C/text%3E%3Ctext x='100' y='118' text-anchor='middle' fill='%23999' font-size='16' font-family='sans-serif'%3E加载失败%3C/text%3E%3C/svg%3E"
                  />
                ) : (
                  <div className="text-gray-400 text-center">
                    <PictureOutlined style={{ fontSize: 48 }} />
                    <p className="mt-2">图片生成中...</p>
                  </div>
                )}
              </div>
            </Card>
          </Col>

          <Col xs={24} md={12}>
            <Card title="基本信息">
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="图片 ID">{genStatus.image_id}</Descriptions.Item>
                <Descriptions.Item label="生成状态">
                  <Tag color={genStatus.status === "completed" ? "green" : genStatus.status === "processing" ? "processing" : "default"}>
                    {genStatus.status === "completed" ? "已完成" : genStatus.status === "processing" ? "生成中" : genStatus.status}
                  </Tag>
                  {genStatus.status !== "completed" && (
                    <Tag color={
                      wsState === "open" ? "green"
                        : wsState === "connecting" ? "blue"
                        : "default"
                    } className="ml-2">
                      {wsState === "open" ? "实时同步"
                        : wsState === "connecting" ? "连接中"
                        : "轮询模式"}
                    </Tag>
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="综合评分">
                  {genStatus.overall_score != null ? (
                    <Tag color={genStatus.overall_score >= 75 ? "green" : genStatus.overall_score >= 60 ? "orange" : "red"}>
                      {genStatus.overall_score} 分
                    </Tag>
                  ) : "—"}
                </Descriptions.Item>
                <Descriptions.Item label="审核状态">
                  <Tag color={reviewInfo.color}>{reviewInfo.label}</Tag>
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
        </Row>

        {/* 质量雷达图 */}
        {genStatus.overall_score != null && (
          <Card title="质量评分" style={{ marginBottom: 20 }}>
            <QualityRadar overallScore={genStatus.overall_score} reviewStatus={genStatus.review_status || "manual_pending"} />
          </Card>
        )}

        {/* 效果预估 */}
        {prediction && (
          <Card title="效果预估" style={{ marginBottom: 20 }}>
            <Row gutter={[20, 20]}>
              <Col xs={12} lg={6}>
                <Statistic title="预估 CTR" value={prediction.predicted_ctr != null ? `${(prediction.predicted_ctr * 100).toFixed(2)}%` : "—"} styles={{ content: { color: "#2563EB" } }} />
              </Col>
              <Col xs={12} lg={6}>
                <Statistic title="置信区间" value={prediction.ctr_confidence_interval ? `${(prediction.ctr_confidence_interval.lower * 100).toFixed(2)}% ~ ${(prediction.ctr_confidence_interval.upper * 100).toFixed(2)}%` : "—"} styles={{ content: { fontSize: 14 } }} />
              </Col>
              <Col xs={12} lg={6}>
                <Statistic title="爆款概率" value={prediction.predicted_hit_probability != null ? `${(prediction.predicted_hit_probability * 100).toFixed(0)}%` : "—"} styles={{ content: { color: (prediction.predicted_hit_probability || 0) > 0.5 ? "#059669" : "#D97706" } }} />
              </Col>
              <Col xs={12} lg={6}>
                <Statistic title="退货风险" value={prediction.return_risk_level === "low" ? "低风险" : prediction.return_risk_level === "medium" ? "中风险" : prediction.return_risk_level === "high" ? "高风险" : "—"} styles={{ content: { color: prediction.return_risk_level === "low" ? "#059669" : prediction.return_risk_level === "medium" ? "#D97706" : prediction.return_risk_level === "high" ? "#DC2626" : undefined } }} />
              </Col>
            </Row>
          </Card>
        )}

        {/* C2PA 内容溯源 */}
        {genStatus.c2pa_manifest && (
          <Card title={<Space><FileProtectOutlined /><span>C2PA 内容溯源</span></Space>} style={{ marginBottom: 20 }}>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="Manifest">
                <span className="text-xs font-mono break-all">
                  {typeof genStatus.c2pa_manifest === "string" ? genStatus.c2pa_manifest : JSON.stringify(genStatus.c2pa_manifest)}
                </span>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        )}

        <Row gutter={[20, 20]}>
          {/* 平台导出 */}
          <Col xs={24} lg={12}>
            <Card title={<Space><ExportOutlined style={{ color: "#2563EB" }} /><span>平台导出</span></Space>} style={{ marginBottom: 20 }}>
              <Space orientation="vertical" style={{ width: "100%" }} size="middle">
                <Select
                  style={{ width: "100%" }}
                  placeholder="选择目标平台"
                  value={exportPlatform || undefined}
                  onChange={setExportPlatform}
                  options={platforms?.platforms?.map((p) => ({ value: p.key, label: `${p.label} (${p.size})` }))}
                />
                <Button type="primary" icon={<ExportOutlined />} onClick={handleExport} loading={exportMutation.isPending} block disabled={!imageUrl}>
                  导出图片
                </Button>
              </Space>
            </Card>
          </Col>

          {/* 图文匹配验证 */}
          <Col xs={24} lg={12}>
            <Card title={<Space><CheckCircleOutlined style={{ color: "#059669" }} /><span>图文匹配验证</span></Space>} style={{ marginBottom: 20 }}>
              <Space orientation="vertical" style={{ width: "100%" }} size="middle">
                <Input placeholder="商品标题" value={matchTitle} onChange={(e) => setMatchTitle(e.target.value)} />
                <Input.TextArea placeholder="商品描述（可选）" rows={2} value={matchDesc} onChange={(e) => setMatchDesc(e.target.value)} />
                <Input placeholder="标签（逗号分隔，可选）" value={matchTags} onChange={(e) => setMatchTags(e.target.value)} />
                <Button type="primary" icon={<CheckCircleOutlined />} onClick={handleTextMatch} loading={textMatchMutation.isPending} block disabled={!imageUrl} style={{ background: "#059669", borderColor: "#059669" }}>
                  验证图文一致性
                </Button>
                {matchResult && (
                  <div className="p-3 bg-gray-50 rounded">
                    <Descriptions column={1} size="small">
                      <Descriptions.Item label="匹配结果">
                        <Tag color={matchResult.match ? "green" : "red"}>{matchResult.match ? "通过" : "不通过"}</Tag>
                      </Descriptions.Item>
                      <Descriptions.Item label="相似度得分">
                        <Progress percent={Math.round(matchResult.similarity_score * 100)} size="small" format={(v) => `${v}%`} />
                      </Descriptions.Item>
                      <Descriptions.Item label="阈值">{(matchResult.threshold * 100).toFixed(0)}%</Descriptions.Item>
                      {matchResult.details.title_similarity != null && (
                        <Descriptions.Item label="标题相似度">{(matchResult.details.title_similarity * 100).toFixed(1)}%</Descriptions.Item>
                      )}
                    </Descriptions>
                  </div>
                )}
              </Space>
            </Card>
          </Col>
        </Row>

        {/* 九维审美启发式评估 */}
        <Card title={<Space><EyeOutlined style={{ color: "#0F766E" }} /><span>九维审美启发式评估</span></Space>} style={{ marginBottom: 20 }}>
          <Space orientation="vertical" style={{ width: "100%" }} size="middle">
            <Button type="primary" icon={<EyeOutlined />} onClick={handleAesthetic} loading={aestheticMutation.isPending} disabled={!imageUrl} style={{ background: "#0F766E", borderColor: "#0F766E" }}>
              执行 9 维度美学评估
            </Button>
            {aestheticResult && (
              <div>
                <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                  <Col span={6}>
                    <Statistic title="综合评分" value={aestheticResult.overall_score.toFixed(1)} suffix="/ 100" styles={{ content: { color: "#0F766E" } }} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="模型版本" value={aestheticResult.model_version} styles={{ content: { fontSize: 14 } }} />
                  </Col>
                </Row>
                <Row gutter={[12, 12]}>
                  {Object.entries(aestheticResult.dimension_scores).map(([dim, score]) => (
                    <Col xs={12} md={8} key={dim}>
                      <div style={{ marginBottom: 4, display: "flex", justifyContent: "space-between" }}>
                        <span style={{ fontSize: 13 }}>{dim}</span>
                        <span style={{ fontWeight: 600, color: score >= 70 ? "#059669" : score >= 50 ? "#D97706" : "#DC2626" }}>{score.toFixed(1)}</span>
                      </div>
                      <Progress percent={Math.round(score)} size="small" showInfo={false} strokeColor={score >= 70 ? "#059669" : score >= 50 ? "#D97706" : "#DC2626"} />
                    </Col>
                  ))}
                </Row>
              </div>
            )}
          </Space>
        </Card>

        {/* 预测历史 */}
        <Card title={<Space><HistoryOutlined style={{ color: "#2563EB" }} /><span>预测历史</span></Space>} style={{ marginBottom: 20 }}>
          {predHistory && predHistory.items?.length > 0 ? (
            <Table
              columns={historyColumns}
              dataSource={predHistory.items}
              rowKey="id"
              size="small"
              pagination={{ pageSize: 5, showTotal: (t) => `共 ${t} 条` }}
            />
          ) : (
            <Empty description="暂无历史预测记录" />
          )}
        </Card>
      </div>
  );
}
