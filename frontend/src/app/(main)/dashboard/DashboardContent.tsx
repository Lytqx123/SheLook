"use client";

import { useState } from "react";
import { Alert, Card, Select, Spin, Statistic, Tooltip as AntTooltip } from "antd";
import {
  CheckCircleOutlined,
  DollarOutlined,
  PictureOutlined,
  QuestionCircleOutlined,
} from "@ant-design/icons";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  useCTRTrend,
  useDashboardSummary,
  useMarketComparison,
  useStyleInsight,
} from "@/hooks";
import { CATEGORY_OPTIONS_SELECT, MARKET_OPTIONS_SELECT } from "@/constants";
import PageHeader from "@/components/PageHeader";

const percent = (value: number | null | undefined, digits = 1) =>
  value == null ? "—" : `${(value * 100).toFixed(digits)}%`;

export default function DashboardContent() {
  const [marketFilter, setMarketFilter] = useState<string | undefined>();
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>();
  const { data: summary, isPending, error } = useDashboardSummary({
    market: marketFilter,
    category: categoryFilter,
  });
  const { data: ctrTrend } = useCTRTrend(30);
  const { data: marketCompare } = useMarketComparison();
  const { data: styleInsight } = useStyleInsight();

  const trendData = ctrTrend?.data || [];
  const marketData = marketCompare?.markets || [];
  const insights = styleInsight?.insights || [];

  if (isPending) {
    return <div className="flex items-center justify-center" style={{ padding: "120px 0" }}><Spin size="large" description="正在加载经营数据…" /></div>;
  }

  if (error) {
    return <Alert type="error" showIcon title="数据加载失败" description={error instanceof Error ? error.message : "请检查网络连接后重试"} />;
  }

  return (
    <main className="office-workspace">
      <PageHeader
        title="数据看板"
        subtitle="聚焦商品视觉运营的核心结果、转化表现与模型质量。"
        extra={
          <>
            <Select allowClear placeholder="全部市场" value={marketFilter} onChange={setMarketFilter} style={{ width: 140 }} options={MARKET_OPTIONS_SELECT} />
            <Select allowClear placeholder="全部类目" value={categoryFilter} onChange={setCategoryFilter} style={{ width: 130 }} options={CATEGORY_OPTIONS_SELECT} />
          </>
        }
      />

      <section className="office-metric-grid" aria-label="核心经营指标">
        <Card className="office-metric-card"><Statistic title="累计生成" value={summary?.total_generated || 0} prefix={<PictureOutlined style={{ color: "#2563EB" }} />} /></Card>
        <Card className="office-metric-card"><Statistic title="审核通过率" value={percent(summary?.approval_rate)} prefix={<CheckCircleOutlined style={{ color: "#087B5A" }} />} styles={{ content: { color: "#087B5A" } }} /></Card>
        <Card className="office-metric-card"><Statistic title="平均 CTR" value={percent(summary?.avg_ctr, 2)} styles={{ content: { color: "#2563EB" } }} /></Card>
        <Card className="office-metric-card"><Statistic title="累计营收" value={summary?.total_revenue || 0} prefix={<DollarOutlined style={{ color: "#087B5A" }} />} styles={{ content: { color: "#087B5A" } }} /></Card>
      </section>

      <Card title="运营概览" extra={<span className="text-xs text-slate-400">当前筛选范围</span>}>
        <div className="office-kpi-strip">
          <Kpi label="曝光量" value={summary?.total_impressions || 0} />
          <Kpi label="点击量" value={summary?.total_clicks || 0} />
          <Kpi label="已通过" value={summary?.total_approved || 0} positive />
          <Kpi label="平均 CVR" value={percent(summary?.avg_cvr, 2)} />
          <Kpi label="退货率" value={percent(summary?.avg_return_rate)} danger={(summary?.avg_return_rate || 0) > 0.1} />
          <Kpi label="转化订单" value={Math.round((summary?.total_clicks || 0) * (summary?.avg_cvr || 0))} />
        </div>
      </Card>

      <Card title="模型健康度" extra={<span className="text-xs text-slate-400">离线评估与人工复核</span>}>
        <div className="office-kpi-strip">
          <Kpi label="相对基线 CTR" value={summary?.ctr_vs_baseline_percent == null ? "—" : `${summary.ctr_vs_baseline_percent.toFixed(2)}%`} positive={(summary?.ctr_vs_baseline_percent || 0) >= 0} danger={(summary?.ctr_vs_baseline_percent || 0) < 0} />
          <Kpi label={<span>CTR 预估 AUC <AntTooltip title="反映模型对高低 CTR 样本的区分能力"><QuestionCircleOutlined /></AntTooltip></span>} value={summary?.ctr_auc?.toFixed(4) || "离线评估中"} />
          <Kpi label={<span>高 CTR 预测占比 <AntTooltip title="预测记录中，预测 CTR 大于 5% 的比例"><QuestionCircleOutlined /></AntTooltip></span>} value={percent(summary?.high_ctr_prediction_share, 2)} />
          <Kpi label="人工复核占比" value={percent(summary?.manual_review_rate, 2)} />
        </div>
      </Card>

      <section className="office-two-column">
        <Card title="CTR 趋势" extra={<span className="text-xs text-slate-400">近 30 天</span>}>
          <div className="office-chart">
            <ResponsiveContainer width="100%" height={318}>
              <AreaChart data={trendData} margin={{ top: 12, right: 12, left: -12, bottom: 0 }}>
                <defs><linearGradient id="dashboardCtrFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2563EB" stopOpacity={0.22} /><stop offset="100%" stopColor="#2563EB" stopOpacity={0.01} /></linearGradient></defs>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={28} />
                <YAxis tickLine={false} axisLine={false} width={46} tickFormatter={(v) => `${(v * 100).toFixed(1)}%`} />
                <ChartTooltip formatter={(v) => `${(Number(v) * 100).toFixed(2)}%`} labelFormatter={(label) => `日期：${label}`} />
                <Area type="monotone" dataKey="avg_ctr" name="平均 CTR" stroke="#2563EB" fill="url(#dashboardCtrFill)" strokeWidth={2.5} activeDot={{ r: 4, strokeWidth: 0 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <div className="office-workspace" style={{ gap: 20 }}>
          <Card title="各市场表现" extra={<span className="text-xs text-slate-400">转化与图量</span>}>
            <div className="office-chart">
              <ResponsiveContainer width="100%" height={226}>
                <BarChart data={marketData} margin={{ top: 8, right: 6, left: -12, bottom: 0 }} barGap={3}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="market" tickLine={false} axisLine={false} />
                  <YAxis yAxisId="rate" tickLine={false} axisLine={false} width={42} tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
                  <YAxis yAxisId="count" orientation="right" tickLine={false} axisLine={false} width={36} />
                  <ChartTooltip formatter={(v, name) => name === "图片数" ? Number(v).toLocaleString() : `${(Number(v) * 100).toFixed(2)}%`} />
                  <Legend iconType="circle" iconSize={7} />
                  <Bar yAxisId="rate" dataKey="avg_ctr" name="平均 CTR" fill="#2563EB" radius={[3, 3, 0, 0]} maxBarSize={18} />
                  <Bar yAxisId="rate" dataKey="avg_cvr" name="平均 CVR" fill="#45A3E8" radius={[3, 3, 0, 0]} maxBarSize={18} />
                  <Bar yAxisId="count" dataKey="total_images" name="图片数" fill="#95A4B8" radius={[3, 3, 0, 0]} maxBarSize={18} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <Card title="风格标签分布" extra={<span className="text-xs text-slate-400">使用频次</span>}>
            <div className="office-chart">
              <ResponsiveContainer width="100%" height={226}>
                <BarChart data={insights} layout="vertical" margin={{ top: 4, right: 18, left: 2, bottom: 0 }}>
                  <CartesianGrid horizontal={false} />
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="tag" tickLine={false} axisLine={false} width={76} />
                  <ChartTooltip formatter={(v) => `${Number(v).toLocaleString()} 次`} />
                  <Bar dataKey="count" name="使用次数" fill="#2563EB" radius={[0, 3, 3, 0]} maxBarSize={14} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>
      </section>
    </main>
  );
}

function Kpi({ label, value, positive, danger }: { label: React.ReactNode; value: string | number; positive?: boolean; danger?: boolean }) {
  return <div className="office-kpi-strip__item"><span className="office-kpi-strip__label">{label}</span><strong className={`office-kpi-strip__value${positive ? " office-kpi-strip__value--positive" : danger ? " office-kpi-strip__value--danger" : ""}`}>{value}</strong></div>;
}
