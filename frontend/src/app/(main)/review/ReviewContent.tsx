"use client";

import { useState } from "react";
import {
  Table,
  Button,
  Tag,
  Modal,
  Space,
  App,
  Select,
  Input,
  Checkbox,
  Divider,
  Descriptions,
  Alert,
} from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  SafetyCertificateOutlined,
  RobotOutlined,
  DownloadOutlined,
  ZoomInOutlined,
} from "@ant-design/icons";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import QualityRadar from "@/components/QualityRadar";
import PageHeader from "@/components/PageHeader";
import { useReviewQueue, useAutoReview } from "@/hooks";
import { api } from "@/lib/api";
import type { ReviewQueueItem, QualityScores, ReviewRequest } from "@/types";
import { L1_DIM_LABELS, L2_DIM_OPTIONS, L3_LABELS, MARKET_OPTIONS } from "@/constants";

export default function ReviewContent() {
  const [selectedImage, setSelectedImage] = useState<ReviewQueueItem | null>(null);
  const [marketFilter, setMarketFilter] = useState<string | undefined>();
  const [rejectReason, setRejectReason] = useState("");
  const [problemDims, setProblemDims] = useState<string[]>([]);
  const [reviewerNotes, setReviewerNotes] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data, isPending, error } = useReviewQueue(page, pageSize, marketFilter);

  const resetForm = () => {
    setRejectReason("");
    setProblemDims([]);
    setReviewerNotes("");
  };

  const columns = [
    {
      title: "图片",
      dataIndex: "image_url",
      key: "image",
      width: 80,
      render: (url: string) => (
        <div
          className="w-12 h-12 rounded bg-gray-100 bg-cover bg-center cursor-pointer"
          style={{ backgroundImage: `url(${url})` }}
        />
      ),
    },
    {
      title: "综合分",
      dataIndex: "overall_score",
      key: "score",
      width: 100,
      sorter: (a: ReviewQueueItem, b: ReviewQueueItem) =>
        (a.overall_score || 0) - (b.overall_score || 0),
      render: (score: number | undefined) => {
        if (score === undefined || score === null) return <Tag>—</Tag>;
        return (
          <Tag color={score >= 75 ? "green" : score >= 60 ? "orange" : "red"}>
            {score.toFixed(0)}
          </Tag>
        );
      },
    },
    {
      title: "市场",
      dataIndex: "market_variant",
      key: "market",
      width: 80,
      render: (m: string | undefined) => (
        <Tag>{m?.toUpperCase() || "—"}</Tag>
      ),
    },
    {
      title: "L1 合规",
      key: "l1",
      width: 90,
      render: (_: unknown, record: ReviewQueueItem) => {
        const l1 = record.quality_scores?.l1;
        if (!l1) return <Tag>—</Tag>;
        return (
          <Tag color={l1.passed ? "green" : "red"} icon={
            l1.passed ? <CheckCircleOutlined /> : <CloseCircleOutlined />
          }>
            {l1.passed ? "通过" : "未通过"}
          </Tag>
        );
      },
    },
    {
      title: "L2 质量",
      key: "l2",
      width: 90,
      render: (_: unknown, record: ReviewQueueItem) => {
        const l2 = record.quality_scores?.l2;
        if (!l2) return <Tag>—</Tag>;
        return (
          <Tag color={l2.verdict === "pass" ? "green" : "red"}>
            {l2.overall_score.toFixed(0)}
          </Tag>
        );
      },
    },
    {
      title: "状态",
      dataIndex: "review_status",
      key: "status",
      width: 100,
      render: (s: string) => {
        const statusMap: Record<string, { color: string; text: string }> = {
          auto_approved: { color: "green", text: "已通过" },
          manual_pending: { color: "orange", text: "待审核" },
          rejected: { color: "red", text: "已驳回" },
        };
        const info = statusMap[s] || { color: "default", text: s };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "time",
      width: 120,
      render: (t: string | undefined) =>
        t?.split("T")[0] || "—",
    },
    {
      title: "操作",
      key: "action",
      width: 150,
      render: (_: unknown, record: ReviewQueueItem) => (
        <ReviewRowActions
          record={record}
          onSelect={(r) => {
            setSelectedImage(r);
            resetForm();
          }}
        />
      ),
    },
  ];

  return (
      <div className="space-y-6" style={{ maxWidth: 1280, margin: "0 auto" }}>
        <PageHeader
          title="审核工作台"
          subtitle={`待审核 ${data?.total || 0} 张图片 · 按分数从低到高排列`}
          extra={
            <>
              <AIBatchReviewButton items={data?.items || []} />
              <Select
                allowClear
                placeholder="市场筛选"
                value={marketFilter}
                onChange={(v) => { setMarketFilter(v); setPage(1); }}
                style={{ width: 160 }}
                options={MARKET_OPTIONS.map((m) => ({ ...m, label: `${m.label} (${m.value.toUpperCase()})` }))}
              />
            </>
          }
        />

        {/* 审核列表 */}
        {error && (
          <Alert
            type="error"
            showIcon
            title="审核队列加载失败"
            description={error instanceof Error ? error.message : "请检查网络连接后重试"}
          />
        )}
        <div className="bg-white rounded-lg">
          <Table
            columns={columns}
            dataSource={data?.items || []}
            rowKey="id"
            loading={isPending}
            pagination={{
              current: page,
              pageSize: pageSize,
              total: data?.total || 0,
              showTotal: (total) => `共 ${total} 张`,
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
              },
            }}
            size="middle"
            locale={{ emptyText: "暂无待审核图片" }}
          />
        </div>

        {/* 详情弹窗 */}
        <Modal
          open={!!selectedImage}
          onCancel={() => {
            setSelectedImage(null);
            resetForm();
          }}
          footer={null}
          width={1100}
          title="图片质量详情"
          centered
          styles={{ body: { padding: 20 } }}
        >
          {selectedImage && (
            <QualityDetailContent
              image={selectedImage}
              rejectReason={rejectReason}
              setRejectReason={setRejectReason}
              problemDims={problemDims}
              setProblemDims={setProblemDims}
              reviewerNotes={reviewerNotes}
              setReviewerNotes={setReviewerNotes}
              onClose={() => {
                setSelectedImage(null);
                resetForm();
              }}
            />
          )}
        </Modal>
      </div>
  );
}

// ====== 行级审核操作组件（每行独立 mutation，避免共享 loading） ======

function ReviewRowActions({
  record,
  onSelect,
}: {
  record: ReviewQueueItem;
  onSelect: (r: ReviewQueueItem) => void;
}) {
  const queryClient = useQueryClient();
  const { message } = App.useApp();

  const decideMutation = useMutation({
    mutationFn: ({ imageId, body }: { imageId: number; body: ReviewRequest }) =>
      api.decideReview(imageId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    },
  });

  return (
    <Space>
      <Button
        type="link"
        size="small"
        onClick={() => onSelect(record)}
      >
        详情
      </Button>
      <Button
        type="link"
        size="small"
        className="text-green-500"
        loading={decideMutation.isPending}
        onClick={() => {
          decideMutation.mutate(
            {
              imageId: record.id,
              body: { action: "approved", notes: "人工审核通过" },
            },
            {
              onSuccess: () => message.success("已通过"),
              onError: () => message.error("操作失败"),
            }
          );
        }}
      >
        通过
      </Button>
      <Button
        type="link"
        size="small"
        danger
        loading={decideMutation.isPending}
        onClick={() => {
          decideMutation.mutate(
            {
              imageId: record.id,
              body: { action: "rejected", reason: "质量不达标" },
            },
            {
              onSuccess: () => message.warning("已驳回"),
              onError: () => message.error("操作失败"),
            }
          );
        }}
      >
        驳回
      </Button>
    </Space>
  );
}

// ====== 质检详情内容组件 ======

interface QualityDetailContentProps {
  image: ReviewQueueItem;
  rejectReason: string;
  setRejectReason: (v: string) => void;
  problemDims: string[];
  setProblemDims: (v: string[]) => void;
  reviewerNotes: string;
  setReviewerNotes: (v: string) => void;
  onClose: () => void;
}

function QualityDetailContent({
  image,
  rejectReason,
  setRejectReason,
  problemDims,
  setProblemDims,
  reviewerNotes,
  setReviewerNotes,
  onClose,
}: QualityDetailContentProps) {
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const [previewVisible, setPreviewVisible] = useState(false);

  const decideMutation = useMutation({
    mutationFn: ({ imageId, body }: { imageId: number; body: ReviewRequest }) =>
      api.decideReview(imageId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["review-queue"] });
    },
  });

  const handleApprove = () => {
    decideMutation.mutate(
      {
        imageId: image.id,
        body: {
          action: "approved",
          notes: reviewerNotes || "人工审核通过",
        },
      },
      {
        onSuccess: () => {
          message.success("已通过");
          onClose();
        },
        onError: () => message.error("操作失败"),
      }
    );
  };

  const handleReject = () => {
    decideMutation.mutate(
      {
        imageId: image.id,
        body: {
          action: "rejected",
          reason: rejectReason || "质量不达标",
          problem_dimensions: problemDims.length > 0
            ? Object.fromEntries(problemDims.map((d) => [d, true]))
            : undefined,
          notes: reviewerNotes || undefined,
        },
      },
      {
        onSuccess: () => {
          message.warning("已驳回");
          onClose();
        },
        onError: () => message.error("操作失败"),
      }
    );
  };

  const handleDownload = async () => {
    try {
      message.loading({ content: "下载中...", key: "download" });
      const response = await fetch(image.image_url);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `image-${image.id}.jpg`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      message.success({ content: "下载完成", key: "download", duration: 1 });
    } catch {
      message.error({ content: "下载失败，请稍后重试", key: "download" });
    }
  };

  const pending = decideMutation.isPending;
  const qs: QualityScores | undefined = image.quality_scores;
  const l1 = qs?.l1;
  const l2 = qs?.l2;
  const l3 = qs?.l3;
  const genParams = image.generation_params;

  const scoreColor =
    image.overall_score == null
      ? "#64748B"
      : image.overall_score >= 75
        ? "#059669"
        : image.overall_score >= 60
          ? "#D97706"
          : "#DC2626";

  const statusInfo =
    image.review_status === "auto_approved"
      ? { color: "green", text: "已通过" }
      : image.review_status === "rejected"
        ? { color: "red", text: "已驳回" }
        : { color: "orange", text: "待审核" };

  return (
    <div className="flex flex-col gap-4">
      {/* 主体：图片预览 + 质量评估 横向布局 */}
      <div className="flex gap-5">
        {/* 左侧：图片预览区 */}
        <div className="w-[400px] flex-shrink-0 space-y-3">
          <div
            className="rounded-lg overflow-hidden border border-gray-200 bg-gray-100 cursor-zoom-in relative group"
            onClick={() => setPreviewVisible(true)}
            style={{
              backgroundImage: `url(${image.image_url})`,
              backgroundSize: "contain",
              backgroundPosition: "center",
              backgroundRepeat: "no-repeat",
              height: 320,
            }}
          >
            {/* 悬停提示层 */}
            <div className="absolute inset-0 flex items-center justify-center bg-black/0 group-hover:bg-black/30 transition-colors">
              <div className="opacity-0 group-hover:opacity-100 transition-opacity bg-white/95 rounded-full px-3 py-1.5 text-xs flex items-center gap-1.5 text-gray-700 shadow-sm">
                <ZoomInOutlined />
                <span>点击放大</span>
              </div>
            </div>
          </div>
          {/* 图片元信息卡 */}
          <div className="bg-gray-50 rounded-lg p-3 space-y-2 text-xs">
            <div className="flex justify-between items-center">
              <span className="text-gray-500">图片 ID</span>
              <span className="font-mono">{image.id}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-500">市场</span>
              <Tag>{image.market_variant?.toUpperCase() || "—"}</Tag>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-500">审核状态</span>
              <Tag color={statusInfo.color}>{statusInfo.text}</Tag>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-gray-500">创建时间</span>
              <span>{image.created_at?.split("T")[0] || "—"}</span>
            </div>
          </div>
          <Button
            block
            icon={<DownloadOutlined />}
            onClick={handleDownload}
          >
            下载原图
          </Button>
        </div>

        {/* 右侧：质量评估 */}
        <div className="flex-1 min-w-0 space-y-3">
          {/* 综合分 + L2 质检横幅 */}
          <div
            className="rounded-lg p-4 flex items-center justify-between"
            style={{
              background: "linear-gradient(135deg, #EEF2FF 0%, #FFFFFF 100%)",
              border: "1px solid #E0E7FF",
            }}
          >
            <div>
              <div className="text-xs text-gray-500 mb-1">综合质量评分</div>
              <div className="flex items-baseline gap-1">
                <span
                  className="text-4xl font-bold"
                  style={{ color: scoreColor }}
                >
                  {image.overall_score ?? "—"}
                </span>
                <span className="text-sm text-gray-400">分</span>
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs text-gray-500 mb-1">L2 质检</div>
              {l2 ? (
                <Tag
                  color={l2.verdict === "pass" ? "green" : "red"}
                  style={{ fontSize: 13, padding: "2px 12px" }}
                >
                  {l2.verdict === "pass" ? "通过" : "未通过"} · {l2.overall_score.toFixed(0)}
                </Tag>
              ) : (
                <Tag>—</Tag>
              )}
            </div>
          </div>

          {/* L1 合规 + L3 审美 横向 */}
          <div className="grid grid-cols-2 gap-3">
            {/* L1 合规 */}
            <div className="border rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <SafetyCertificateOutlined style={{ color: "#2563EB" }} />
                <span className="font-semibold text-sm">L1 合规</span>
                {l1 && (
                  <Tag
                    color={l1.passed ? "green" : "red"}
                    className="ml-auto"
                  >
                    {l1.passed ? "通过" : "未通过"}
                  </Tag>
                )}
              </div>
              {l1 ? (
                <div className="text-xs space-y-1">
                  {l1.checks.map((c, idx) => (
                    <div
                      key={idx}
                      className="flex items-center gap-1"
                      title={`${c.actual}${c.passed ? "" : `（要求：${c.requirement}）`}`}
                    >
                      {c.passed ? (
                        <CheckCircleOutlined className="text-green-500" />
                      ) : (
                        <CloseCircleOutlined className="text-red-500" />
                      )}
                      <span className="text-gray-600 truncate">
                        {L1_DIM_LABELS[c.dimension] || c.dimension}
                      </span>
                    </div>
                  ))}
                  {image.c2pa_manifest && (
                    <div className="flex items-center gap-1 pt-1 border-t border-gray-100 mt-1">
                      <CheckCircleOutlined className="text-green-500" />
                      <span className="text-gray-600">C2PA 内容溯源</span>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-xs text-gray-400">无合规数据</p>
              )}
            </div>

            {/* L3 审美 */}
            <div className="border rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="font-semibold text-sm">L3 审美</span>
              </div>
              {l3 ? (
                <div className="space-y-1">
                  {Object.entries(l3).map(([key, val]) => (
                    <div key={key} className="flex items-center justify-between text-xs">
                      <span className="text-gray-500">{L3_LABELS[key] || key}</span>
                      <span
                        className="font-semibold"
                        style={{
                          color:
                            val >= 75 ? "#059669" : val >= 60 ? "#D97706" : "#DC2626",
                        }}
                      >
                        {val.toFixed(1)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-gray-400">无审美数据</p>
              )}
            </div>
          </div>

          {/* 质量雷达图 */}
          <QualityRadar
            overallScore={image.overall_score}
            reviewStatus={image.review_status}
            dimensions={l2?.dimensions}
            failedDimensions={
              l2?.verdict === "fail"
                ? Object.entries(l2.dimensions)
                    .filter(([, score]) => typeof score === "number" && score < 60)
                    .map(([key]) => key)
                : []
            }
          />
        </div>
      </div>

      {/* 生成参数 */}
      {genParams && (
        <>
          <Divider className="my-1" />
          <Descriptions title="生成参数" size="small" column={2} bordered>
            {Boolean(genParams.model) && (
              <Descriptions.Item label="模型">{String(genParams.model)}</Descriptions.Item>
            )}
            {Boolean(genParams.prompt) && (
              <Descriptions.Item label="Prompt" span={2}>
                <span className="text-xs text-gray-600">{String(genParams.prompt)}</span>
              </Descriptions.Item>
            )}
            {Boolean(genParams.steps) && (
              <Descriptions.Item label="步数">{String(genParams.steps)}</Descriptions.Item>
            )}
            {Boolean(genParams.guidance_scale) && (
              <Descriptions.Item label="引导系数">{String(genParams.guidance_scale)}</Descriptions.Item>
            )}
          </Descriptions>
        </>
      )}

      {/* 审核操作区 */}
      <Divider className="my-1" />
      <div className="space-y-3">
        {/* 问题维度标注 */}
        <div>
          <p className="text-sm font-medium mb-2">问题维度标注（驳回时填写）</p>
          <Checkbox.Group
            options={[...L2_DIM_OPTIONS]}
            value={problemDims}
            onChange={(vals) => setProblemDims(vals as string[])}
          />
        </div>

        {/* 驳回原因 + 审核备注 横向 */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <p className="text-sm font-medium mb-1">驳回原因</p>
            <Input
              placeholder="如：清晰度不足、色彩偏暗、构图失衡"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
            />
          </div>
          <div>
            <p className="text-sm font-medium mb-1">审核备注（可选）</p>
            <Input
              placeholder="补充说明..."
              value={reviewerNotes}
              onChange={(e) => setReviewerNotes(e.target.value)}
            />
          </div>
        </div>

        {/* 操作按钮 */}
        <div className="flex items-center gap-3 pt-3 border-t">
          <AutoReviewButton imageId={image.id} />
          <div className="flex-1" />
          <Button onClick={onClose}>关闭</Button>
          <Button danger onClick={handleReject} loading={pending}>
            驳回
          </Button>
          <Button type="primary" onClick={handleApprove} loading={pending}>
            通过
          </Button>
        </div>
      </div>

      {/* 图片放大预览 Modal */}
      <Modal
        open={previewVisible}
        onCancel={() => setPreviewVisible(false)}
        footer={null}
        width="90%"
        style={{ top: 20, maxWidth: 1400 }}
        title={`图片预览 · ID ${image.id}`}
        destroyOnHidden
      >
        <div
          className="bg-contain bg-no-repeat bg-center bg-gray-100 rounded-lg"
          style={{
            backgroundImage: `url(${image.image_url})`,
            width: "100%",
            height: "72vh",
          }}
        />
        <div className="flex justify-center mt-4">
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            onClick={handleDownload}
          >
            下载原图
          </Button>
        </div>
      </Modal>
    </div>
  );
}

// ====== AI 自动审核按钮（单图） ======
function AutoReviewButton({ imageId }: { imageId: number }) {
  const autoReview = useAutoReview();
  const { message } = App.useApp();

  const handleAutoReview = () => {
    autoReview.mutate(imageId, {
      onSuccess: (data) => {
        if (data.passed) {
          message.success(`AI 审核通过 · 综合分 ${data.overall_score}`);
        } else {
          message.warning(`AI 诊断完成 · 综合分 ${data.overall_score} · 建议人工复审`);
        }
      },
      onError: () => message.error("AI 自动审核失败"),
    });
  };

  return (
    <Button
      icon={<RobotOutlined />}
      onClick={handleAutoReview}
      loading={autoReview.isPending}
      size="small"
      type="dashed"
    >
      AI 诊断
    </Button>
  );
}

// ====== AI 批量审核按钮 ======
function AIBatchReviewButton({ items }: { items: ReviewQueueItem[] }) {
  const autoReview = useAutoReview();
  const { message } = App.useApp();
  const [reviewing, setReviewing] = useState(false);

  const handleBatchReview = async () => {
    if (items.length === 0) {
      message.info("暂无可审核的图片");
      return;
    }
    setReviewing(true);
    message.loading({ content: `正在 AI 批量诊断 ${items.length} 张图片...`, key: "batch-ai", duration: 0 });
    let passCount = 0;
    let failCount = 0;
    for (const item of items) {
      try {
        const res = await autoReview.mutateAsync(item.id);
        if (res.passed) passCount++;
        else failCount++;
      } catch {
        failCount++;
        console.warn(`AI 诊断失败 · 图片 ${item.id}`);
      }
    }
    setReviewing(false);
    message.success({
      content: `AI 诊断完成：${passCount} 张通过，${failCount} 张待复审`,
      key: "batch-ai",
    });
  };

  return (
    <Button
      icon={<RobotOutlined />}
      onClick={handleBatchReview}
      loading={reviewing}
      type="dashed"
    >
      全部 AI 诊断
    </Button>
  );
}
