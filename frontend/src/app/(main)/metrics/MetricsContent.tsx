"use client";

import { useState } from "react";
import { Alert, App, Button, Card, DatePicker, Descriptions, Input, Select, Statistic, Table, Tag, Typography } from "antd";
import { CalendarOutlined, CheckCircleOutlined, CloudSyncOutlined, DatabaseOutlined, FileTextOutlined, SyncOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import PageHeader from "@/components/PageHeader";
import { useBatchUpsertMetrics, useMetricsStats, useSyncPlatformMetrics } from "@/hooks";
import type { MetricsBatchItem, MetricsSyncResponse } from "@/types";

const { RangePicker } = DatePicker;
const { Text } = Typography;

const PLATFORMS = [
  { value: "shopee", label: "Shopee" },
  { value: "lazada", label: "Lazada（请使用批量导入）", disabled: true },
  { value: "amazon", label: "Amazon" },
];

export default function MetricsContent() {
  const { data: stats, isPending: statsLoading } = useMetricsStats();
  const syncMutation = useSyncPlatformMetrics();
  const batchMutation = useBatchUpsertMetrics();
  const { message } = App.useApp();
  const [platform, setPlatform] = useState("shopee");
  const [apiKey, setApiKey] = useState("");
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [syncResult, setSyncResult] = useState<MetricsSyncResponse | null>(null);
  const [batchJson, setBatchJson] = useState(() => JSON.stringify([{ image_id: 1, date: dayjs().format("YYYY-MM-DD"), source_platform: "manual", impressions: 5000, clicks: 150, ctr: 0.03, cvr: 0.05, revenue: 1250.5 }], null, 2));

  const handleSync = async () => {
    setSyncResult(null);
    message.loading({ content: `正在同步 ${platform} 数据…`, key: "sync" });
    try {
      const res = await syncMutation.mutateAsync({ platform, apiKey: apiKey || undefined, dateFrom: dateRange?.[0]?.format("YYYY-MM-DD"), dateTo: dateRange?.[1]?.format("YYYY-MM-DD") });
      setSyncResult(res);
      if (res.status === "success") message.success({ content: `同步完成，写入 ${res.records_upserted} 条`, key: "sync" });
      else if (res.status === "partial") message.warning({ content: `部分成功：写入 ${res.records_upserted} 条，${res.errors.length} 个错误`, key: "sync" });
      else message.error({ content: "同步失败", key: "sync" });
    } catch (error) {
      message.error({ content: error instanceof Error ? error.message : "同步失败", key: "sync" });
    }
  };

  const handleBatchImport = async () => {
    try {
      const parsed: unknown = JSON.parse(batchJson);
      if (!Array.isArray(parsed) || parsed.length === 0) throw new Error("请输入至少一条指标记录的 JSON 数组");
      const items = parsed as MetricsBatchItem[];
      message.loading({ content: `正在校验并写入 ${items.length} 条数据…`, key: "batch" });
      const res = await batchMutation.mutateAsync({ body: { items }, apiKey: apiKey || undefined });
      message.success({ content: `写入完成：${res.upserted}/${res.total}`, key: "batch" });
    } catch (error) {
      message.error({ content: error instanceof Error ? error.message : "JSON 解析或写入失败", key: "batch" });
    }
  };

  const errorColumns: ColumnsType<{ error: string; index: number }> = [
    { title: "序号", dataIndex: "index", key: "index", width: 72 },
    { title: "错误信息", dataIndex: "error", key: "error" },
  ];

  return (
    <main className="office-workspace">
      <PageHeader title="指标数据管理" subtitle="集中同步、导入与核验商品图片的经营指标。" />

      <section className="office-metric-grid" aria-label="数据概况">
        <Card className="office-metric-card" loading={statsLoading}><Statistic title="指标记录" value={stats?.total_records ?? 0} prefix={<FileTextOutlined style={{ color: "#2563EB" }} />} /></Card>
        <Card className="office-metric-card" loading={statsLoading}><Statistic title="涉及图片" value={stats?.total_images ?? 0} prefix={<DatabaseOutlined style={{ color: "#087B5A" }} />} /></Card>
        <Card className="office-metric-card" loading={statsLoading}><Statistic title="数据起始日期" value={stats?.earliest_date ?? "—"} prefix={<CalendarOutlined style={{ color: "#A56A00" }} />} /></Card>
        <Card className="office-metric-card" loading={statsLoading}><Statistic title="最近导入" value={stats?.last_import_at ? dayjs(stats.last_import_at).format("YYYY-MM-DD HH:mm") : "—"} prefix={<SyncOutlined style={{ color: "#0F766E" }} />} /></Card>
      </section>

      <section className="office-two-column">
        <Card title={<><CloudSyncOutlined style={{ color: "#2563EB", marginRight: 8 }} />平台数据同步</>}>
          <p className="office-panel-note">Shopee 可同步曝光、点击和 CTR；Amazon 同步销售与流量报告中的 CVR、营收。Lazada 请使用右侧批量导入。</p>
          <Alert type="info" showIcon title="按日期范围增量同步，重复记录会安全更新。" style={{ marginBottom: 18 }} />
          <div className="office-form-grid">
            <div className="office-form-field"><label>平台</label><Select value={platform} onChange={setPlatform} options={PLATFORMS} /></div>
            <div className="office-form-field"><label>数据日期</label><RangePicker value={dateRange} onChange={(dates) => setDateRange(dates as [dayjs.Dayjs, dayjs.Dayjs] | null)} format="YYYY-MM-DD" style={{ width: "100%" }} /></div>
            <div className="office-form-field office-form-field--wide"><label>Metrics API Key（开发环境可留空）</label><Input.Password value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="输入平台数据授权密钥" /></div>
            <div className="office-form-actions office-form-field--wide"><Button type="primary" icon={<SyncOutlined />} onClick={handleSync} loading={syncMutation.isPending} size="large">开始同步</Button></div>
          </div>
          {syncResult && <SyncResult result={syncResult} errorColumns={errorColumns} />}
        </Card>

        <Card title={<><DatabaseOutlined style={{ color: "#087B5A", marginRight: 8 }} />批量数据导入</>}>
          <p className="office-panel-note">直接提交指标 JSON 数组；服务端会验证字段并使用幂等写入。单次最多支持 1000 条。</p>
          <Alert type="warning" showIcon title="写入端点需要 X-API-Key 鉴权；开发环境未配置时可留空。" style={{ marginBottom: 18 }} />
          <div className="office-form-grid">
            <div className="office-form-field office-form-field--wide"><label>指标 JSON 数组</label><Input.TextArea rows={13} value={batchJson} onChange={(event) => setBatchJson(event.target.value)} spellCheck={false} aria-label="指标数据 JSON 数组" /></div>
            <div className="office-form-actions office-form-field--wide"><Button type="primary" icon={<CheckCircleOutlined />} onClick={handleBatchImport} loading={batchMutation.isPending} size="large" style={{ background: "#087B5A", borderColor: "#087B5A" }}>校验并写入</Button></div>
          </div>
          <Text type="secondary" style={{ display: "block", marginTop: 14, fontSize: 12, lineHeight: 1.7 }}>支持 manual、shopee、lazada、amazon 作为 source_platform；服务端会校验字段并限制单次写入量。</Text>
        </Card>
      </section>
    </main>
  );
}

function SyncResult({ result, errorColumns }: { result: MetricsSyncResponse; errorColumns: ColumnsType<{ error: string; index: number }> }) {
  const statusColor = result.status === "success" ? "green" : result.status === "partial" ? "orange" : "red";
  const statusText = result.status === "success" ? "成功" : result.status === "partial" ? "部分成功" : "失败";
  return <div className="office-result-block"><Descriptions column={2} size="small">
    <Descriptions.Item label="状态"><Tag color={statusColor}>{statusText}</Tag></Descriptions.Item>
    <Descriptions.Item label="写入条数">{result.records_upserted}</Descriptions.Item>
    <Descriptions.Item label="拉取记录">{result.records_fetched}</Descriptions.Item>
    {result.date_range && <Descriptions.Item label="日期范围">{result.date_range}</Descriptions.Item>}
    {result.message && <Descriptions.Item label="消息" span={2}>{result.message}</Descriptions.Item>}
  </Descriptions>{result.errors.length > 0 && <Table size="small" style={{ marginTop: 14 }} columns={errorColumns} dataSource={result.errors.map((error, index) => ({ error, index: index + 1 }))} rowKey="index" pagination={false} />}</div>;
}
