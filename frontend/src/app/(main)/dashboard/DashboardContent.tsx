"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Card, Collapse, Empty, Select, Skeleton, Statistic, Tag, Tooltip as AntTooltip } from "antd";
import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExperimentOutlined,
  FlagOutlined,
  FundOutlined,
  PictureOutlined,
  PlusOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  WarningOutlined,
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
  useCurrentUser,
  useDashboardSummary,
  useExperiments,
  useMarketComparison,
  useReviewQueue,
  useStyleInsight,
  useWorkflowTasks,
} from "@/hooks";
import { getRoleExperience, hasAnyPermission, hasPermission } from "@/lib/access";
import { CATEGORY_OPTIONS_SELECT, MARKET_OPTIONS_SELECT } from "@/constants";
import PageHeader from "@/components/PageHeader";

const percent = (value: number | null | undefined, digits = 1) =>
  value == null ? "—" : `${(value * 100).toFixed(digits)}%`;

type Priority = "urgent" | "high" | "medium";

type DecisionAction = {
  id: string;
  priority: Priority;
  title: string;
  description: string;
  href: string;
  cta: string;
  icon: React.ReactNode;
  count?: number;
};

const priorityMeta: Record<Priority, { label: string; color: string; order: number }> = {
  urgent: { label: "需立即处理", color: "red", order: 0 },
  high: { label: "优先处理", color: "orange", order: 1 },
  medium: { label: "建议关注", color: "blue", order: 2 },
};

export default function DashboardContent() {
  const router = useRouter();
  const [marketFilter, setMarketFilter] = useState<string | undefined>();
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>();
  const { data: user, isLoading: userLoading } = useCurrentUser();
  const identityReady = !userLoading;
  const roleExperience = getRoleExperience(user);
  const canReadAnalytics = identityReady && hasPermission(user, "analytics:read");
  const canReadReviews = identityReady && hasPermission(user, "review:read");
  const canReadExperiments = identityReady && hasPermission(user, "experiment:read");
  const canManageWorkflows = identityReady && hasAnyPermission(user, ["generation:run", "workflow:manage"]);
  const canCreateCampaign = identityReady && hasAnyPermission(user, ["product:write", "generation:run"]);

  const summaryQuery = useDashboardSummary({ market: marketFilter, category: categoryFilter }, canReadAnalytics);
  const ctrTrendQuery = useCTRTrend(30, canReadAnalytics);
  const marketCompareQuery = useMarketComparison(canReadAnalytics);
  const styleInsightQuery = useStyleInsight(canReadAnalytics);
  const reviewQueueQuery = useReviewQueue(1, 5, undefined, canReadReviews);
  const workflowTasksQuery = useWorkflowTasks({ page: 1, pageSize: 25 }, canManageWorkflows);
  const experimentsQuery = useExperiments(1, 10, "running", canReadExperiments);

  const summary = summaryQuery.data;
  const trendData = ctrTrendQuery.data?.data ?? [];
  const marketData = marketCompareQuery.data?.markets ?? [];
  const insights = styleInsightQuery.data?.insights ?? [];
  const failedTasks = workflowTasksQuery.data?.items.filter((task) => task.status === "failed").length ?? 0;
  const waitingForHumanTasks = workflowTasksQuery.data?.items.filter((task) => task.status === "waiting_human").length ?? 0;

  const decisionActions = useMemo<DecisionAction[]>(() => {
    const actions: DecisionAction[] = [];

    if (waitingForHumanTasks > 0) {
      actions.push({
        id: "waiting-human",
        priority: "urgent",
        title: `${waitingForHumanTasks} 项任务等待人工确认`,
        description: "这些任务无法自动继续，确认后才能恢复后续生成、审核或投放流程。",
        href: "/tasks",
        cta: "处理任务",
        icon: <ClockCircleOutlined />,
        count: waitingForHumanTasks,
      });
    }

    if (failedTasks > 0) {
      actions.push({
        id: "failed-tasks",
        priority: "urgent",
        title: `${failedTasks} 项任务执行异常`,
        description: "查看失败原因并决定是否重试，避免活动链路在异常状态下停滞。",
        href: "/tasks",
        cta: "查看异常",
        icon: <WarningOutlined />,
        count: failedTasks,
      });
    }

    if ((reviewQueueQuery.data?.total ?? 0) > 0) {
      actions.push({
        id: "pending-reviews",
        priority: "high",
        title: `${reviewQueueQuery.data?.total} 张素材待审核`,
        description: "完成质量与合规确认后，素材才能进入预测、实验或后续投放。",
        href: "/review",
        cta: "进入审核",
        icon: <CheckCircleOutlined />,
        count: reviewQueueQuery.data?.total,
      });
    }

    if (summary && summary.avg_return_rate >= 0.1) {
      actions.push({
        id: "return-risk",
        priority: "high",
        title: `平均退货率为 ${percent(summary.avg_return_rate)}`,
        description: "退货风险高于建议关注线，请复查当前视觉承诺与商品实际体验是否一致。",
        href: "/prediction",
        cta: "查看风险",
        icon: <SafetyCertificateOutlined />,
      });
    }

    if ((experimentsQuery.data?.total ?? 0) > 0) {
      actions.push({
        id: "running-experiments",
        priority: "medium",
        title: `${experimentsQuery.data?.total} 个实验正在运行`,
        description: "关注样本量、显著性和胜出方案，避免长期保留没有决策价值的实验。",
        href: "/experiments",
        cta: "查看实验",
        icon: <ExperimentOutlined />,
        count: experimentsQuery.data?.total,
      });
    }

    if (summary && summary.approval_rate < 0.8 && summary.total_generated > 0) {
      actions.push({
        id: "approval-rate",
        priority: "medium",
        title: `审核通过率为 ${percent(summary.approval_rate)}`,
        description: "通过率低于 80%，建议优先复盘高频驳回原因和当前视觉方案。",
        href: "/review",
        cta: "复查质量",
        icon: <CheckCircleOutlined />,
      });
    }

    if (summary && (summary.ctr_vs_baseline_percent ?? 0) < 0) {
      actions.push({
        id: "ctr-baseline",
        priority: "medium",
        title: "CTR 低于当前基线",
        description: "当前素材组合尚未达到基线表现，建议先对候选方案进行预测或新建对照实验。",
        href: "/prediction",
        cta: "分析方案",
        icon: <FundOutlined />,
      });
    }

    return actions.sort((a, b) => priorityMeta[a.priority].order - priorityMeta[b.priority].order);
  }, [experimentsQuery.data?.total, failedTasks, reviewQueueQuery.data?.total, summary, waitingForHumanTasks]);

  const isLoadingActions =
    userLoading ||
    (canReadReviews && reviewQueueQuery.isPending) ||
    (canManageWorkflows && workflowTasksQuery.isPending) ||
    (canReadExperiments && experimentsQuery.isPending) ||
    (canReadAnalytics && summaryQuery.isPending);

  const primaryAction = canCreateCampaign
    ? { label: "新建视觉运营活动", href: "/campaigns?new=1", icon: <PlusOutlined /> }
    : canReadReviews
      ? { label: "查看审核队列", href: "/review", icon: <CheckCircleOutlined /> }
      : { label: "查看运营活动", href: "/campaigns", icon: <FlagOutlined /> };

  const hasAnalyticsError = canReadAnalytics && summaryQuery.isError;

  return (
    <main className="office-workspace">
      <PageHeader
        title={roleExperience.title}
        subtitle={roleExperience.subtitle}
        extra={
          <>
            {canReadAnalytics && (
              <>
                <Select
                  allowClear
                  placeholder="全部市场"
                  value={marketFilter}
                  onChange={setMarketFilter}
                  style={{ width: 140 }}
                  options={MARKET_OPTIONS_SELECT}
                />
                <Select
                  allowClear
                  placeholder="全部类目"
                  value={categoryFilter}
                  onChange={setCategoryFilter}
                  style={{ width: 130 }}
                  options={CATEGORY_OPTIONS_SELECT}
                />
              </>
            )}
            <Button type="primary" icon={primaryAction.icon} onClick={() => router.push(primaryAction.href)}>
              {primaryAction.label}
            </Button>
          </>
        }
      />

      <section className="office-decision-hero" aria-label="今日决策概览">
        <div>
          <span className="office-decision-hero__eyebrow">{user ? `${user.username} 的工作台` : "运营工作台"}</span>
          <h2>先处理影响结果的事项，再查看数据。</h2>
          <p>待办按业务风险和阻塞程度排序；处理动作会回到对应的可追溯工作流中完成。</p>
        </div>
        <div className="office-decision-hero__summary">
          <strong>{decisionActions.length}</strong>
          <span>项待决策事项</span>
        </div>
      </section>

      <Card
        className="office-decision-card"
        title="待决策事项"
        extra={<span className="office-card-meta">来自审核、任务、实验与经营信号</span>}
      >
        {isLoadingActions && decisionActions.length === 0 ? (
          <Skeleton active title={false} paragraph={{ rows: 3 }} />
        ) : decisionActions.length > 0 ? (
          <div className="office-decision-list">
            {decisionActions.map((action) => (
              <div key={action.id} className={`office-decision-item office-decision-item--${action.priority}`}>
                <span className="office-decision-item__icon">{action.icon}</span>
                <div className="office-decision-item__content">
                  <div className="office-decision-item__heading">
                    <span>{action.title}</span>
                    <Tag color={priorityMeta[action.priority].color}>{priorityMeta[action.priority].label}</Tag>
                  </div>
                  <p>{action.description}</p>
                </div>
                <Button type="link" icon={<ArrowRightOutlined />} iconPosition="end" onClick={() => router.push(action.href)}>
                  {action.cta}
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <div className="office-decision-empty">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={roleExperience.emptyHint} />
            <Button type="primary" icon={primaryAction.icon} onClick={() => router.push(primaryAction.href)}>
              {primaryAction.label}
            </Button>
          </div>
        )}
      </Card>

      {hasAnalyticsError && (
        <Alert
          type="warning"
          showIcon
          title="部分经营数据暂不可用"
          description="待决策事项仍可继续处理；请稍后刷新经营信号和趋势分析。"
        />
      )}

      {canReadAnalytics && (
        <>
          <Card title="经营信号" extra={<span className="office-card-meta">用于解释行动优先级</span>}>
            <div className="office-kpi-strip">
              <Kpi label="累计生成" value={summary?.total_generated ?? 0} />
              <Kpi label="审核通过率" value={percent(summary?.approval_rate)} positive={(summary?.approval_rate ?? 0) >= 0.8} danger={(summary?.approval_rate ?? 0) < 0.8} />
              <Kpi label="平均 CTR" value={percent(summary?.avg_ctr, 2)} />
              <Kpi label="平均 CVR" value={percent(summary?.avg_cvr, 2)} />
              <Kpi label="退货率" value={percent(summary?.avg_return_rate)} danger={(summary?.avg_return_rate ?? 0) >= 0.1} />
              <Kpi label="累计营收" value={summary?.total_revenue ?? 0} positive />
            </div>
          </Card>

          <Collapse
            className="office-insights-collapse"
            items={[
              {
                key: "analytics",
                label: "查看经营趋势与模型健康",
                children: (
                  <div className="office-workspace" style={{ gap: 20 }}>
                    <section className="office-metric-grid" aria-label="核心经营指标">
                      <Card className="office-metric-card"><Statistic title="累计生成" value={summary?.total_generated ?? 0} prefix={<PictureOutlined style={{ color: "#2563EB" }} />} /></Card>
                      <Card className="office-metric-card"><Statistic title="审核通过率" value={percent(summary?.approval_rate)} prefix={<CheckCircleOutlined style={{ color: "#087B5A" }} />} styles={{ content: { color: "#087B5A" } }} /></Card>
                      <Card className="office-metric-card"><Statistic title="平均 CTR" value={percent(summary?.avg_ctr, 2)} styles={{ content: { color: "#2563EB" } }} /></Card>
                      <Card className="office-metric-card"><Statistic title="累计营收" value={summary?.total_revenue ?? 0} prefix={<FundOutlined style={{ color: "#087B5A" }} />} styles={{ content: { color: "#087B5A" } }} /></Card>
                    </section>

                    <Card title="模型健康" extra={<span className="office-card-meta">离线评估与人工复核</span>}>
                      <div className="office-kpi-strip">
                        <Kpi label="相对基线 CTR" value={summary?.ctr_vs_baseline_percent == null ? "—" : `${summary.ctr_vs_baseline_percent.toFixed(2)}%`} positive={(summary?.ctr_vs_baseline_percent ?? 0) >= 0} danger={(summary?.ctr_vs_baseline_percent ?? 0) < 0} />
                        <Kpi label={<span>CTR 预估 AUC <AntTooltip title="反映模型对高、低 CTR 样本的区分能力。"><ThunderboltOutlined /></AntTooltip></span>} value={summary?.ctr_auc?.toFixed(4) || "离线评估中"} />
                        <Kpi label="高 CTR 预测占比" value={percent(summary?.high_ctr_prediction_share, 2)} />
                        <Kpi label="人工复核占比" value={percent(summary?.manual_review_rate, 2)} />
                      </div>
                    </Card>

                    <section className="office-two-column">
                      <Card title="CTR 趋势" extra={<span className="office-card-meta">近 30 天</span>}>
                        <div className="office-chart">
                          <ResponsiveContainer width="100%" height={318}>
                            <AreaChart data={trendData} margin={{ top: 12, right: 12, left: -12, bottom: 0 }}>
                              <defs><linearGradient id="dashboardCtrFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2563EB" stopOpacity={0.22} /><stop offset="100%" stopColor="#2563EB" stopOpacity={0.01} /></linearGradient></defs>
                              <CartesianGrid vertical={false} />
                              <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={28} />
                              <YAxis tickLine={false} axisLine={false} width={46} tickFormatter={(value) => `${(value * 100).toFixed(1)}%`} />
                              <ChartTooltip formatter={(value) => `${(Number(value) * 100).toFixed(2)}%`} labelFormatter={(label) => `日期：${label}`} />
                              <Area type="monotone" dataKey="avg_ctr" name="平均 CTR" stroke="#2563EB" fill="url(#dashboardCtrFill)" strokeWidth={2.5} activeDot={{ r: 4, strokeWidth: 0 }} />
                            </AreaChart>
                          </ResponsiveContainer>
                        </div>
                      </Card>

                      <div className="office-workspace" style={{ gap: 20 }}>
                        <Card title="各市场表现" extra={<span className="office-card-meta">转化与图片量</span>}>
                          <div className="office-chart">
                            <ResponsiveContainer width="100%" height={226}>
                              <BarChart data={marketData} margin={{ top: 8, right: 6, left: -12, bottom: 0 }} barGap={3}>
                                <CartesianGrid vertical={false} />
                                <XAxis dataKey="market" tickLine={false} axisLine={false} />
                                <YAxis yAxisId="rate" tickLine={false} axisLine={false} width={42} tickFormatter={(value) => `${(value * 100).toFixed(0)}%`} />
                                <YAxis yAxisId="count" orientation="right" tickLine={false} axisLine={false} width={36} />
                                <ChartTooltip formatter={(value, name) => name === "图片数" ? Number(value).toLocaleString() : `${(Number(value) * 100).toFixed(2)}%`} />
                                <Legend iconType="circle" iconSize={7} />
                                <Bar yAxisId="rate" dataKey="avg_ctr" name="平均 CTR" fill="#2563EB" radius={[3, 3, 0, 0]} maxBarSize={18} />
                                <Bar yAxisId="rate" dataKey="avg_cvr" name="平均 CVR" fill="#45A3E8" radius={[3, 3, 0, 0]} maxBarSize={18} />
                                <Bar yAxisId="count" dataKey="total_images" name="图片数" fill="#95A4B8" radius={[3, 3, 0, 0]} maxBarSize={18} />
                              </BarChart>
                            </ResponsiveContainer>
                          </div>
                        </Card>

                        <Card title="风格标签分布" extra={<span className="office-card-meta">使用频次</span>}>
                          <div className="office-chart">
                            <ResponsiveContainer width="100%" height={226}>
                              <BarChart data={insights} layout="vertical" margin={{ top: 4, right: 18, left: 2, bottom: 0 }}>
                                <CartesianGrid horizontal={false} />
                                <XAxis type="number" hide />
                                <YAxis type="category" dataKey="tag" tickLine={false} axisLine={false} width={76} />
                                <ChartTooltip formatter={(value) => `${Number(value).toLocaleString()} 次`} />
                                <Bar dataKey="count" name="使用次数" fill="#2563EB" radius={[0, 3, 3, 0]} maxBarSize={14} />
                              </BarChart>
                            </ResponsiveContainer>
                          </div>
                        </Card>
                      </div>
                    </section>
                  </div>
                ),
              },
            ]}
          />
        </>
      )}
    </main>
  );
}

function Kpi({ label, value, positive, danger }: { label: React.ReactNode; value: string | number; positive?: boolean; danger?: boolean }) {
  return <div className="office-kpi-strip__item"><span className="office-kpi-strip__label">{label}</span><strong className={`office-kpi-strip__value${positive ? " office-kpi-strip__value--positive" : danger ? " office-kpi-strip__value--danger" : ""}`}>{value}</strong></div>;
}
