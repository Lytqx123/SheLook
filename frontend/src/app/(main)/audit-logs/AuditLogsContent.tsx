"use client";

import { useState } from "react";
import {
  Card, Table, Tag, Input, Select, Button, Modal, Descriptions,
  Alert, DatePicker, Spin, Image, Typography,
} from "antd";
import { SearchOutlined, LinkOutlined, EyeOutlined } from "@ant-design/icons";
import { useAuditLogs, useAuditTrace, useAuditLogDetail } from "@/hooks";
import { AUDIT_OPERATION_OPTIONS } from "@/constants";
import type { AuditLogItem, AuditTraceItem, AuditLogDetail } from "@/types";
import dayjs from "dayjs";
import PageHeader from "@/components/PageHeader";

const { Text } = Typography;

const { RangePicker } = DatePicker;

export default function AuditLogsContent() {
  const [filters, setFilters] = useState<{
    request_id?: string; image_id?: number; operation?: string;
    status?: string; start_date?: string; end_date?: string;
    limit?: number; offset?: number;
  }>({ limit: 50, offset: 0 });

  const [traceModal, setTraceModal] = useState<{ open: boolean; requestId: string }>({
    open: false, requestId: "",
  });

  const [detailId, setDetailId] = useState<number | null>(null);

  const { data, isPending, error } = useAuditLogs(filters);

  const columns = [
    { title: "ID", dataIndex: "id", key: "id", width: 70 },
    {
      title: "Request ID", dataIndex: "request_id", key: "rid", width: 200,
      render: (v: string) => (
        <Button
          type="link" size="small" icon={<LinkOutlined />}
          onClick={() => setTraceModal({ open: true, requestId: v })}
        >
          {v.substring(0, 16)}...
        </Button>
      ),
    },
    {
      title: "操作", dataIndex: "operation", key: "op", width: 100,
      render: (v: string) => {
        const labels: Record<string, string> = {
          generate: "图片生成",
          video_generate: "视频生成",
          auto_review: "AI 审核",
          evaluate: "质量评估",
          review: "人工审核",
          export: "导出",
        };
        return <Tag>{labels[v] || v}</Tag>;
      },
    },
    {
      title: "图片 ID", dataIndex: "image_id", key: "img", width: 80,
      render: (v: number | null) => v ?? "—",
    },
    {
      title: "模型", dataIndex: "model_name", key: "model", width: 120,
      render: (v: string | null) => v ? <Tag color="purple">{v}</Tag> : "—",
    },
    {
      title: "C2PA", dataIndex: "c2pa_manifest_present", key: "c2pa", width: 70,
      render: (v: boolean | null) =>
        v === true ? <Tag color="green">是</Tag> :
        v === false ? <Tag color="red">否</Tag> : "—",
    },
    {
      title: "合规", dataIndex: "compliance_checks_passed", key: "comp", width: 70,
      render: (v: boolean | null) =>
        v === true ? <Tag color="green">通过</Tag> :
        v === false ? <Tag color="red">未通过</Tag> : "—",
    },
    {
      title: "状态", dataIndex: "status", key: "status", width: 80,
      render: (v: string) => (
        <Tag color={v === "success" ? "green" : v === "failed" ? "red" : "default"}>
          {v === "success" ? "成功" : v === "failed" ? "失败" : v}
        </Tag>
      ),
    },
    {
      title: "时间", dataIndex: "created_at", key: "time", width: 160,
      render: (v: string | null) => v ? dayjs(v).format("YYYY-MM-DD HH:mm:ss") : "—",
    },
    {
      title: "操作", key: "action", width: 80, fixed: "right" as const,
      render: (_: unknown, record: AuditLogItem) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => setDetailId(record.id)}
        >
          详情
        </Button>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto" }}>
      <PageHeader
        title="审计日志"
        subtitle="全量 AI 操作日志 · 合规保留 ≥180 天 · 符合 EU AI Act & 深度合成监管细则"
      />

      {/* 筛选 */}
      <Card style={{ marginBottom: 20 }}>
        <div className="flex flex-wrap items-center gap-3">
          <Input
            placeholder="Request ID"
            allowClear
            style={{ width: 200 }}
            prefix={<SearchOutlined />}
            value={filters.request_id}
            onChange={(e) => setFilters((f) => ({ ...f, request_id: e.target.value || undefined }))}
          />
          <Select
            allowClear
            placeholder="操作类型"
            style={{ width: 140 }}
            value={filters.operation}
            onChange={(v) => setFilters((f) => ({ ...f, operation: v }))}
            options={[...AUDIT_OPERATION_OPTIONS]}
          />
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 120 }}
            value={filters.status}
            onChange={(v) => setFilters((f) => ({ ...f, status: v }))}
            options={[
              { value: "success", label: "成功" },
              { value: "failed", label: "失败" },
            ]}
          />
          <RangePicker
            onChange={(dates) => {
              setFilters((f) => ({
                ...f,
                start_date: dates?.[0]?.format("YYYY-MM-DD"),
                end_date: dates?.[1]?.format("YYYY-MM-DD"),
              }));
            }}
          />
        </div>
      </Card>

      {/* 日志表格 */}
      {error && (
        <Alert
          type="error"
          showIcon
          title="审计日志加载失败"
          description={error instanceof Error ? error.message : "请检查网络"}
          style={{ marginBottom: 20 }}
        />
      )}
      <Card>
        <Table
          columns={columns}
          dataSource={data?.items || []}
          rowKey="id"
          loading={isPending}
          pagination={{
            total: data?.total || 0,
            pageSize: filters.limit || 50,
            current: ((filters.offset || 0) / (filters.limit || 50)) + 1,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (page, pageSize) => {
              setFilters((f) => ({
                ...f,
                limit: pageSize,
                offset: (page - 1) * pageSize,
              }));
            },
          }}
          size="small"
          scroll={{ x: 1000 }}
          locale={{ emptyText: "暂无审计日志" }}
        />
      </Card>

      {/* 链路追踪弹窗 */}
      <TraceModal
        open={traceModal.open}
        requestId={traceModal.requestId}
        onClose={() => setTraceModal({ open: false, requestId: "" })}
      />

      {/* 单条审计日志详情弹窗 */}
      <AuditLogDetailModal
        open={detailId !== null}
        logId={detailId}
        onClose={() => setDetailId(null)}
      />
    </div>
  );
}

function TraceModal({
  open, requestId, onClose,
}: {
  open: boolean; requestId: string; onClose: () => void;
}) {
  const { data, isPending } = useAuditTrace(requestId);

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={700}
      title={`全链路追踪 · ${requestId}`}
    >
      {isPending ? (
        <div className="text-center py-8 text-gray-400">加载中...</div>
      ) : data ? (
        <>
          <Descriptions column={2} size="small" bordered className="mb-4">
            <Descriptions.Item label="Request ID">{data.request_id}</Descriptions.Item>
            <Descriptions.Item label="步骤总数">{data.total}</Descriptions.Item>
          </Descriptions>
          <Table
            dataSource={data.items}
            rowKey="id"
            size="small"
            pagination={false}
            columns={[
              { title: "步骤", dataIndex: "id", width: 60 },
              { title: "操作", dataIndex: "operation", width: 100,
                render: (v: string) => {
                  const labels: Record<string, string> = {
                    generate: "图片生成",
                    video_generate: "视频生成",
                    auto_review: "AI 审核",
                    evaluate: "质量评估",
                    review: "人工审核",
                    export: "导出",
                  };
                  return <Tag>{labels[v] || v}</Tag>;
                } },
              { title: "图片 ID", dataIndex: "image_id", width: 80,
                render: (v: number | null) => v ?? "—" },
              { title: "模型", dataIndex: "model_name", width: 120,
                render: (v: string | null) => v || "—" },
              { title: "状态", dataIndex: "status", width: 80,
                render: (v: string) => (
                  <Tag color={v === "success" ? "green" : "red"}>
                    {v === "success" ? "成功" : "失败"}
                  </Tag>
                ) },
              { title: "时间", dataIndex: "created_at",
                render: (v: string | null) => v ? dayjs(v).format("MM-DD HH:mm:ss") : "—" },
            ]}
          />
        </>
      ) : (
        <div className="text-center py-8 text-gray-400">未找到追踪数据</div>
      )}
    </Modal>
  );
}

function AuditLogDetailModal({
  open, logId, onClose,
}: {
  open: boolean; logId: number | null; onClose: () => void;
}) {
  const { data, isPending } = useAuditLogDetail(logId);

  const detail: AuditLogDetail | undefined = data;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={780}
      title={logId != null ? `审计日志详情 #${logId}` : "审计日志详情"}
      destroyOnHidden
    >
      {isPending ? (
        <div className="text-center py-12">
          <Spin description="加载中..." />
        </div>
      ) : detail ? (
        <>
          {/* 基础信息 */}
          <Descriptions
            title="基础信息"
            column={2}
            size="small"
            bordered
            className="mb-4"
          >
            <Descriptions.Item label="ID">{detail.id}</Descriptions.Item>
            <Descriptions.Item label="Request ID">
              {detail.request_id || "—"}
            </Descriptions.Item>
            <Descriptions.Item label="操作">{detail.operation || "—"}</Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={detail.status === "success" ? "green" : detail.status === "failed" ? "red" : "default"}>
                {detail.status === "success" ? "成功" : detail.status === "failed" ? "失败" : detail.status}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="创建时间" span={2}>
              {detail.created_at ? dayjs(detail.created_at).format("YYYY-MM-DD HH:mm:ss") : "—"}
            </Descriptions.Item>
          </Descriptions>

          {/* 关联资源 */}
          <Descriptions
            title="关联资源"
            column={2}
            size="small"
            bordered
            className="mb-4"
          >
            <Descriptions.Item label="Product ID">{detail.product_id ?? "—"}</Descriptions.Item>
            <Descriptions.Item label="Scheme ID">{detail.scheme_id ?? "—"}</Descriptions.Item>
            <Descriptions.Item label="Image ID">{detail.image_id ?? "—"}</Descriptions.Item>
            <Descriptions.Item label="模型">
              {detail.model_name ? <Tag color="purple">{detail.model_name}</Tag> : "—"}
            </Descriptions.Item>
          </Descriptions>

          {/* 合规信息 */}
          <Descriptions
            title="合规信息"
            column={2}
            size="small"
            bordered
            className="mb-4"
          >
            <Descriptions.Item label="C2PA Manifest">
              {detail.c2pa_manifest_present === true ? <Tag color="green">是</Tag> :
               detail.c2pa_manifest_present === false ? <Tag color="red">否</Tag> : "—"}
            </Descriptions.Item>
            <Descriptions.Item label="合规检查">
              {detail.compliance_checks_passed === true ? <Tag color="green">是</Tag> :
               detail.compliance_checks_passed === false ? <Tag color="red">否</Tag> : "—"}
            </Descriptions.Item>
            <Descriptions.Item label="管辖区" span={2}>
              {detail.jurisdiction || "—"}
            </Descriptions.Item>
          </Descriptions>

          {/* 技术信息 */}
          <Descriptions
            title="技术信息"
            column={2}
            size="small"
            bordered
            className="mb-4"
          >
            <Descriptions.Item label="Prompt Hash">
              {detail.prompt_hash || "—"}
            </Descriptions.Item>
            <Descriptions.Item label="IP 地址">{detail.ip_address || "—"}</Descriptions.Item>
            <Descriptions.Item label="User Agent" span={2}>
              {detail.user_agent || "—"}
            </Descriptions.Item>
            <Descriptions.Item label="耗时 (ms)" span={2}>
              {detail.duration_ms != null ? `${detail.duration_ms} ms` : "—"}
            </Descriptions.Item>
          </Descriptions>

          {/* 生成参数 */}
          <Descriptions
            title="生成参数"
            column={1}
            size="small"
            bordered
            className="mb-4"
          >
            <Descriptions.Item label="generation_params">
              {detail.generation_params ? (
                <pre
                  style={{
                    margin: 0, maxHeight: 240, overflow: "auto",
                    background: "#f6f8fa", padding: 12, borderRadius: 6,
                    fontSize: 12,
                  }}
                >
                  {JSON.stringify(detail.generation_params, null, 2)}
                </pre>
              ) : "—"}
            </Descriptions.Item>
          </Descriptions>

          {/* 错误信息 */}
          {detail.error_message ? (
            <Descriptions
              title="错误信息"
              column={1}
              size="small"
              bordered
              className="mb-4"
            >
              <Descriptions.Item label="error_message">
                <Text type="danger" style={{ wordBreak: "break-word" }}>
                  {detail.error_message}
                </Text>
              </Descriptions.Item>
            </Descriptions>
          ) : null}

          {/* 图片 */}
          {detail.image_url ? (
            <Descriptions
              title="生成图片"
              column={1}
              size="small"
              bordered
            >
              <Descriptions.Item label="image_url">
                <Image
                  src={detail.image_url}
                  alt="audit"
                  width={160}
                  style={{ borderRadius: 6 }}
                />
              </Descriptions.Item>
            </Descriptions>
          ) : null}
        </>
      ) : (
        <div className="text-center py-12 text-gray-400">未找到审计日志详情</div>
      )}
    </Modal>
  );
}
