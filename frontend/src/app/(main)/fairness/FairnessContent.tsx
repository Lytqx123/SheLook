"use client";

import { useState } from "react";
import { Alert, App, Button, Card, Descriptions, Empty, InputNumber, Progress, Select, Space, Table, Tag, Typography } from "antd";
import { AuditOutlined, SearchOutlined } from "@ant-design/icons";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip as ChartTooltip, XAxis, YAxis } from "recharts";
import { useCheckSchemeFairness, useFairnessMarketReport, useSkinToneDistribution } from "@/hooks";
import { CATEGORY_OPTIONS_SELECT, MARKET_OPTIONS_SELECT, SKIN_TONE_LABELS } from "@/constants";
import type { SchemeFairnessItem } from "@/types";
import PageHeader from "@/components/PageHeader";

const PIE_COLORS = ["#F0C9A0", "#D59A67", "#A76D47", "#6E4635"];

export default function FairnessContent() {
  const [marketFilter, setMarketFilter] = useState<string | undefined>();
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>();
  const [schemeId, setSchemeId] = useState<number | null>(null);
  const [schemeResult, setSchemeResult] = useState<SchemeFairnessItem | null>(null);
  const { data: skinToneData, isPending: skinToneLoading, error: skinToneError } = useSkinToneDistribution({ market: marketFilter, category: categoryFilter });
  const reportMarket = marketFilter || "us";
  const { data: marketReport, isPending: reportLoading, error: reportError } = useFairnessMarketReport(reportMarket);
  const checkScheme = useCheckSchemeFairness();
  const { message } = App.useApp();
  const skinTones = skinToneData || [];
  const markets = marketReport?.markets || [];
  const totalImages = skinTones.reduce((sum, item) => sum + item.count, 0);
  const pieData = skinTones.map((item) => ({ name: SKIN_TONE_LABELS[item.label] || item.label, value: item.percentage, count: item.count }));
  const barData = markets.map((market) => ({
    market: market.market.toUpperCase(),
    "浅色·预期": market.expected.light * 100,
    "浅色·实际": market.actual.light * 100,
    "中等·预期": market.expected.medium * 100,
    "中等·实际": market.actual.medium * 100,
    "深色·预期": market.expected.dark * 100,
    "深色·实际": market.actual.dark * 100,
  }));

  const handleCheckScheme = async () => {
    if (schemeId == null) return message.warning("请先输入方案 ID");
    try {
      const result = await checkScheme.mutateAsync(schemeId);
      setSchemeResult(result);
      result.is_biased ? message.warning("检测到方案存在肤色分布偏差，建议调整素材配比") : message.success("方案肤色分布处于正常范围");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "方案公平性检查失败");
    }
  };

  return (
    <main className="office-workspace">
      <PageHeader title="公平性分析" subtitle="查看生成素材的肤色多样性，并对照目标市场的人口统计分布。" extra={<><Select allowClear placeholder="全部市场" value={marketFilter} onChange={setMarketFilter} style={{ width: 140 }} options={MARKET_OPTIONS_SELECT} /><Select allowClear placeholder="全部类目" value={categoryFilter} onChange={setCategoryFilter} style={{ width: 140 }} options={CATEGORY_OPTIONS_SELECT} /></>} />

      {skinToneError && <Alert type="error" showIcon title="肤色分布数据加载失败" description={skinToneError instanceof Error ? skinToneError.message : "请检查网络连接后重试"} />}
      <section className="office-equal-columns">
        <Card title="肤色分布" extra={<span className="text-xs text-slate-400">当前筛选范围</span>} loading={skinToneLoading}>
          {skinTones.length > 0 ? <div className="office-donut">
            <div className="office-chart"><ResponsiveContainer width="100%" height={270}><PieChart><Pie data={pieData} cx="50%" cy="50%" innerRadius={72} outerRadius={102} paddingAngle={2} dataKey="value" stroke="none">{pieData.map((_, index) => <Cell key={index} fill={PIE_COLORS[index % PIE_COLORS.length]} />)}</Pie><ChartTooltip formatter={(value) => `${Number(value).toFixed(1)}%`} /></PieChart></ResponsiveContainer></div>
            <div className="office-donut__total"><strong>{totalImages.toLocaleString()}</strong><span>已分析图片</span></div>
          </div> : <Empty description="暂无肤色分布数据" />}
          {pieData.length > 0 && <div className="office-chart-legend">{pieData.map((item, index) => <div className="office-chart-legend__item" key={item.name}><span className="office-chart-legend__label"><i className="office-chart-legend__dot" style={{ background: PIE_COLORS[index % PIE_COLORS.length] }} />{item.name}</span><span className="office-chart-legend__value">{item.value.toFixed(1)}%</span></div>)}</div>}
        </Card>

        <Card title="肤色统计明细" extra={<span className="text-xs text-slate-400">{totalImages.toLocaleString()} 张图片</span>} loading={skinToneLoading}>
          <Table dataSource={skinTones} rowKey="label" pagination={false} scroll={{ x: 480 }} columns={[
            { title: "肤色", dataIndex: "label", key: "label", render: (value: string) => SKIN_TONE_LABELS[value] || value },
            { title: "数量", dataIndex: "count", key: "count", align: "right" as const },
            { title: "占比", dataIndex: "percentage", key: "percentage", align: "right" as const, render: (value: number) => `${value.toFixed(1)}%` },
            { title: "分布", key: "progress", width: 170, render: (_: unknown, row: { percentage: number }) => <Progress percent={Math.round(row.percentage)} showInfo={false} strokeColor={row.percentage > 60 ? "#A56A00" : "#2563EB"} /> },
          ]} />
        </Card>
      </section>

      {reportError && <Alert type="error" showIcon title="市场人口统计数据加载失败" description={reportError instanceof Error ? reportError.message : "请检查网络连接后重试"} />}
      <Card title="市场人口统计对比" extra={<span className="text-xs text-slate-400">预期与实际分布</span>} loading={reportLoading}>
        {markets.length > 0 ? <div className="office-workspace" style={{ gap: 18 }}>
          <div className="office-chart"><ResponsiveContainer width="100%" height={340}><BarChart data={barData} margin={{ top: 10, right: 14, left: -12, bottom: 2 }} barGap={2}><CartesianGrid vertical={false} /><XAxis dataKey="market" tickLine={false} axisLine={false} /><YAxis tickLine={false} axisLine={false} width={42} tickFormatter={(value) => `${value}%`} /><ChartTooltip formatter={(value) => `${Number(value).toFixed(1)}%`} /><Legend iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 11 }} /><Bar dataKey="浅色·预期" fill="#F0C9A0" opacity={0.42} radius={[2, 2, 0, 0]} maxBarSize={12} /><Bar dataKey="浅色·实际" fill="#F0C9A0" radius={[2, 2, 0, 0]} maxBarSize={12} /><Bar dataKey="中等·预期" fill="#D59A67" opacity={0.42} radius={[2, 2, 0, 0]} maxBarSize={12} /><Bar dataKey="中等·实际" fill="#D59A67" radius={[2, 2, 0, 0]} maxBarSize={12} /><Bar dataKey="深色·预期" fill="#A76D47" opacity={0.42} radius={[2, 2, 0, 0]} maxBarSize={12} /><Bar dataKey="深色·实际" fill="#A76D47" radius={[2, 2, 0, 0]} maxBarSize={12} /></BarChart></ResponsiveContainer></div>
          <Table dataSource={markets} rowKey="market" pagination={false} scroll={{ x: 560 }} columns={[
            { title: "市场", dataIndex: "market", key: "market", render: (value: string) => value.toUpperCase() },
            { title: "浅色偏差", key: "light", align: "right" as const, render: (_: unknown, row: { deviation: Record<string, number> }) => <Deviation value={(row.deviation?.light || 0) * 100} /> },
            { title: "中等肤色偏差", key: "medium", align: "right" as const, render: (_: unknown, row: { deviation: Record<string, number> }) => <Deviation value={(row.deviation?.medium || 0) * 100} /> },
            { title: "深色偏差", key: "dark", align: "right" as const, render: (_: unknown, row: { deviation: Record<string, number> }) => <Deviation value={(row.deviation?.dark || 0) * 100} /> },
          ]} />
        </div> : <Empty description="暂无市场人口统计数据" />}
      </Card>

      <Card title={<><AuditOutlined style={{ color: "#2563EB", marginRight: 8 }} />方案级公平性检查</>}>
        <p className="office-panel-note">输入方案 ID 后，系统会根据已关联图片的肤色分布给出偏差判断和素材配比建议。</p>
        <div className="office-form-grid"><div className="office-form-field"><label>方案 ID</label><InputNumber value={schemeId} onChange={(value) => setSchemeId(value)} min={1} precision={0} placeholder="输入方案 ID" style={{ width: "100%" }} /></div><div className="office-form-actions"><Button type="primary" icon={<SearchOutlined />} loading={checkScheme.isPending} onClick={handleCheckScheme}>开始检查</Button></div></div>
        {schemeResult && <SchemeResult result={schemeResult} />}
      </Card>
    </main>
  );
}

function Deviation({ value }: { value: number }) {
  const color = value > 30 ? "#C2413A" : value > 15 ? "#A56A00" : "#087B5A";
  return <span className="tabular-nums" style={{ color }}>{value.toFixed(1)}%</span>;
}

function SchemeResult({ result }: { result: SchemeFairnessItem }) {
  return <div className="office-result-block"><div className="office-workspace" style={{ gap: 16 }}>
    {result.is_biased && <Alert type="warning" showIcon title="检测到肤色分布偏差" description="建议调整方案素材配比，确保不同肤色群体得到公平覆盖。" />}
    <Descriptions size="small" column={2} items={[{ key: "id", label: "方案 ID", children: result.scheme_id }, { key: "name", label: "方案名称", children: result.scheme_name }, { key: "status", label: "检查结果", children: result.is_biased ? <Tag color="red">存在偏差</Tag> : <Tag color="green">正常</Tag> }]} />
    <Typography.Text strong>肤色分布</Typography.Text>
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>{result.skin_tone_distribution.map((item) => <div key={item.label}><div className="flex items-center justify-between mb-1"><span>{SKIN_TONE_LABELS[item.label] || item.label}</span><span className="text-xs text-slate-500">{item.count} 张 · {item.percentage.toFixed(1)}%</span></div><Progress percent={Math.round(item.percentage)} showInfo={false} strokeColor="#2563EB" /></div>)}</Space>
  </div></div>;
}
