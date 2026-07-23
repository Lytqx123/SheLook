"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Alert,
  App,
  Badge,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  List,
  Modal,
  Progress,
  Segmented,
  Select,
  Skeleton,
  Space,
  Spin,
  Steps,
  Tag,
  Timeline,
  Tooltip,
} from "antd";
import {
  ArrowRightOutlined,
  BarChartOutlined,
  CheckCircleOutlined,
  ExperimentOutlined,
  FileSearchOutlined,
  PlusOutlined,
  RocketOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import PageHeader from "@/components/PageHeader";
import {
  useCampaign,
  useCampaigns,
  useCreateCampaign,
  useCurrentUser,
  useUpdateCampaign,
} from "@/hooks";
import type { Campaign, CampaignCreateRequest, CampaignStage, CampaignStatus } from "@/types";
import { MARKET_OPTIONS_SELECT } from "@/constants";
import { hasAnyPermission } from "@/lib/access";

const STAGES: Array<{ key: CampaignStage; title: string; description: string }> = [
  { key: "brief", title: "经营简报", description: "确定市场、商品与目标" },
  { key: "strategy", title: "视觉策略", description: "选择方案与依据" },
  { key: "production", title: "素材生产", description: "生成并准备素材" },
  { key: "review", title: "质量门禁", description: "审核风险与合规" },
  { key: "prediction", title: "效果决策", description: "评估潜力与风险" },
  { key: "experiment", title: "投放验证", description: "A/B 实验验证" },
  { key: "learning", title: "复盘学习", description: "沉淀策略并反馈" },
];

const STATUS_META: Record<string, { label: string; color: string }> = {
  draft: { label: "待启动", color: "default" },
  in_progress: { label: "进行中", color: "blue" },
  waiting_review: { label: "待审核", color: "orange" },
  experimenting: { label: "实验中", color: "purple" },
  learning: { label: "复盘中", color: "cyan" },
  completed: { label: "已完成", color: "green" },
  archived: { label: "已归档", color: "default" },
};

const STAGE_ROUTE: Record<CampaignStage, { href: string; label: string; icon: React.ReactNode }> = {
  brief: { href: "/publish", label: "补全经营简报", icon: <RocketOutlined /> },
  strategy: { href: "/publish", label: "进入方案工作台", icon: <RocketOutlined /> },
  production: { href: "/publish", label: "继续生成素材", icon: <RocketOutlined /> },
  planning: { href: "/publish", label: "补全经营简报", icon: <RocketOutlined /> },
  generation: { href: "/publish", label: "进入方案工作台", icon: <RocketOutlined /> },
  review: { href: "/review", label: "处理审核队列", icon: <CheckCircleOutlined /> },
  prediction: { href: "/prediction", label: "查看预测决策", icon: <BarChartOutlined /> },
  experiment: { href: "/experiments", label: "进入实验中心", icon: <ExperimentOutlined /> },
  learning: { href: "/flywheel", label: "查看复盘沉淀", icon: <SyncOutlined /> },
  retrospective: { href: "/flywheel", label: "查看复盘沉淀", icon: <SyncOutlined /> },
  completed: { href: "/flywheel", label: "查看归档复盘", icon: <FileSearchOutlined /> },
};

function stageIndex(stage?: string) {
  const index = STAGES.findIndex((item) => item.key === stage);
  return index < 0 ? 0 : index;
}

function percent(value: unknown, digits = 1) {
  return typeof value === "number" ? `${(value * 100).toFixed(digits)}%` : "—";
}

function formatTime(value?: string) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}

function campaignAction(campaign: Campaign) {
  const configured = campaign.recommended_action;
  const label = typeof configured?.label === "string" ? configured.label : undefined;
  const description = typeof configured?.description === "string" ? configured.description : undefined;
  const stage = campaign.current_stage || "brief";
  const fallback = STAGE_ROUTE[stage] ?? STAGE_ROUTE.brief;
  return {
    ...fallback,
    label: label || fallback.label,
    description: description || campaign.next_step || "按当前阶段推进活动，系统会持续保留决策与结果。",
  };
}

export default function CampaignsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { message } = App.useApp();
  const [status, setStatus] = useState<string | undefined>();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm<CampaignCreateRequest>();
  const { data: user, isLoading: userLoading } = useCurrentUser();
  const canOperate = !userLoading && hasAnyPermission(user, ["product:write", "generation:run"]);
  const canManageModel = !userLoading && hasAnyPermission(user, ["model:manage"]);
  const campaignsQuery = useCampaigns({ status, page: 1, pageSize: 50 });
  const createCampaign = useCreateCampaign();
  const updateCampaign = useUpdateCampaign();
  const campaigns = campaignsQuery.data?.items ?? [];

  useEffect(() => {
    if (searchParams.get("new") === "1") setCreateOpen(true);
  }, [searchParams]);

  useEffect(() => {
    const requestedCampaignId = searchParams.get("selected");
    if (requestedCampaignId && campaigns.some((campaign) => campaign.id === requestedCampaignId)) {
      setSelectedId(requestedCampaignId);
    }
  }, [campaigns, searchParams]);

  useEffect(() => {
    if (!selectedId && campaigns[0]) setSelectedId(campaigns[0].id);
    if (selectedId && !campaigns.some((campaign) => campaign.id === selectedId)) {
      setSelectedId(campaigns[0]?.id ?? null);
    }
  }, [campaigns, selectedId]);

  const detailQuery = useCampaign(selectedId ?? "");
  const campaign = detailQuery.data?.campaign ?? campaigns.find((item) => item.id === selectedId);
  const detail = detailQuery.data;
  const currentAction = campaign ? campaignAction(campaign) : null;
  const statusOptions = useMemo(() => [
    { label: "全部活动", value: "all" },
    { label: "进行中", value: "in_progress" },
    { label: "待审核", value: "waiting_review" },
    { label: "实验中", value: "experimenting" },
    { label: "复盘中", value: "learning" },
  ], []);

  const handleCreate = async (values: CampaignCreateRequest) => {
    if (!canOperate) {
      message.warning("当前账号仅可查看活动，请联系运营负责人创建或推进活动。");
      return;
    }
    try {
      const created = await createCampaign.mutateAsync({
        ...values,
        objective_metric: values.objective_metric || "CTR",
      });
      setSelectedId(created.id);
      setCreateOpen(false);
      form.resetFields();
      message.success("视觉运营活动已创建，可从经营简报开始推进。");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "创建活动失败，请稍后重试");
    }
  };

  const openAction = async () => {
    if (!campaign || !currentAction) return;
    if (!canOperate) {
      message.warning("当前账号没有推进活动的操作权限。");
      return;
    }
    const route = `${currentAction.href}?campaignId=${encodeURIComponent(campaign.id)}`;
    router.push(route);
  };

  const markLearning = async () => {
    if (!campaign) return;
    if (!canOperate) {
      message.warning("当前账号没有更新活动状态的操作权限。");
      return;
    }
    try {
      await updateCampaign.mutateAsync({
        campaignId: campaign.id,
        body: { current_stage: "learning", status: "learning" },
      });
      message.success("活动已进入复盘学习阶段。");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "更新活动失败");
    }
  };

  return (
    <main className="office-workspace">
      <PageHeader
        title="视觉运营活动"
        subtitle="以一项经营目标串起视觉策略、内容生产、质量门禁、效果验证与策略沉淀。"
        extra={canOperate ? <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建运营活动</Button> : undefined}
      />

      <section className="office-activity-intro">
        <div>
          <span className="office-activity-intro__eyebrow">经营主线</span>
          <strong>不要从模块开始，从“这次活动要达成什么”开始。</strong>
          <p>每一步都会保留选择依据、风险判断和真实结果，便于团队协同与后续复用。</p>
        </div>
        <div className="office-activity-intro__steps" aria-label="视觉运营活动流程">
          {STAGES.slice(0, 4).map((stage, index) => (
            <span key={stage.key}>{index > 0 && <i>→</i>}{stage.title}</span>
          ))}
          <span><i>→</i>投放验证</span>
          <span><i>→</i>复盘学习</span>
        </div>
      </section>

      <div className="office-activity-layout">
        <Card className="office-activity-list" title="活动列表" extra={<span className="text-xs text-slate-400">{campaignsQuery.data?.total ?? campaigns.length} 项</span>}>
          <Segmented
            block
            value={status ?? "all"}
            options={statusOptions}
            onChange={(value) => setStatus(value === "all" ? undefined : String(value))}
            className="mb-3"
          />
          {campaignsQuery.isPending ? <Skeleton active paragraph={{ rows: 8 }} /> : (
            <List
              dataSource={campaigns}
              locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有运营活动" /> }}
              renderItem={(item) => {
                const meta = STATUS_META[item.status] ?? { label: item.status, color: "default" };
                const isSelected = item.id === selectedId;
                return (
                  <List.Item
                    className={`office-activity-list__item${isSelected ? " office-activity-list__item--active" : ""}`}
                    onClick={() => setSelectedId(item.id)}
                  >
                    <div className="office-activity-list__item-title">
                      <strong>{item.name}</strong>
                      <Tag color={meta.color}>{meta.label}</Tag>
                    </div>
                    <div className="office-activity-list__item-meta">
                      <span>{item.market?.toUpperCase() || "未设市场"}</span>
                      <span>{item.objective || "未设目标"}</span>
                    </div>
                    <div className="office-activity-list__item-footer">
                      <span>{STAGES[stageIndex(item.current_stage)]?.title}</span>
                      <span>{formatTime(item.updated_at || item.created_at)}</span>
                    </div>
                  </List.Item>
                );
              }}
            />
          )}
        </Card>

        <section className="office-activity-detail">
          {!selectedId && !campaignsQuery.isPending && (
            <Card><Empty description="选择一个活动，或新建一项经营目标" /></Card>
          )}
          {selectedId && detailQuery.isPending && <Card><Spin size="large" tip="正在加载活动链路…" /></Card>}
          {selectedId && detailQuery.error && (
            <Alert
              type="error"
              showIcon
              title="活动详情加载失败"
              description={detailQuery.error instanceof Error ? detailQuery.error.message : "请刷新后重试"}
            />
          )}
          {campaign && !detailQuery.isPending && (
            <>
              <Card className="office-activity-hero">
                <div className="office-activity-hero__top">
                  <div>
                    <Space size={8} wrap>
                      <Tag color={(STATUS_META[campaign.status] ?? { color: "default" }).color}>{(STATUS_META[campaign.status] ?? { label: campaign.status }).label}</Tag>
                      <Tag>{campaign.market?.toUpperCase()}</Tag>
                      {campaign.objective_metric && <Tag color="blue">目标：{campaign.objective_metric}{campaign.target_value != null ? ` ${campaign.target_value}` : ""}</Tag>}
                    </Space>
                    <h2>{campaign.name}</h2>
                    <p>{campaign.description || campaign.objective || "尚未补充经营目标说明"}</p>
                  </div>
                  <div className="office-activity-hero__actions">
                    {canOperate && <Button type="primary" icon={currentAction?.icon} onClick={openAction}>{currentAction?.label}</Button>}
                    {canOperate && campaign.current_stage !== "learning" && campaign.current_stage !== "brief" && (
                      <Tooltip title="当素材或实验已具备结果时，进入复盘并沉淀可复用策略">
                        <Button icon={<FileSearchOutlined />} loading={updateCampaign.isPending} onClick={markLearning}>进入复盘</Button>
                      </Tooltip>
                    )}
                  </div>
                </div>
                <div className="office-next-action">
                  <Badge status="processing" />
                  <div><strong>现在最该做什么</strong><span>{currentAction?.description}</span></div>
                  <ArrowRightOutlined />
                </div>
              </Card>

              <Card className="office-activity-stage-card" title="活动推进">
                <Steps
                  current={stageIndex(campaign.current_stage)}
                  size="small"
                  items={STAGES.map((stage) => ({ title: stage.title, description: stage.description }))}
                />
              </Card>

              <section className="office-metric-grid office-activity-metrics">
                <Metric label="已生成素材" value={detail?.summary?.total_images ?? 0} />
                <Metric label="待人工审核" value={detail?.summary?.pending_reviews ?? 0} danger={Number(detail?.summary?.pending_reviews ?? 0) > 0} />
                <Metric label="平均预估 CTR" value={percent(detail?.summary?.avg_predicted_ctr, 2)} />
                <Metric label="进行中实验" value={detail?.summary?.experiments_running ?? 0} />
              </section>

              <div className="office-two-column office-activity-lower">
                <Card title="决策时间线" extra={<span className="text-xs text-slate-400">每一次选择都有据可查</span>}>
                  {detail?.timeline?.length ? (
                    <Timeline
                      items={detail.timeline.slice(0, 8).map((item) => ({
                        color: item.status === "failed" ? "red" : item.status === "waiting" ? "orange" : "blue",
                        children: <div className="office-activity-timeline"><strong>{item.title}</strong><p>{item.description}</p><span>{formatTime(item.occurred_at)}</span></div>,
                      }))}
                    />
                  ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="活动推进后，这里会自动沉淀关键决策" />}
                </Card>

                <Card title="本次活动沉淀" extra={canManageModel ? <Button type="link" onClick={() => router.push(`/flywheel?campaignId=${campaign.id}`)}>查看飞轮复盘</Button> : undefined}>
                  {detail?.insights?.length ? (
                    <div className="office-activity-insights">
                      {detail.insights.slice(0, 4).map((insight) => (
                        <article key={insight.id} className="office-activity-insight">
                          <Tag color={insight.insight_type === "strategy_rejected" ? "red" : "green"}>{insight.insight_type === "strategy_rejected" ? "待规避" : "已验证"}</Tag>
                          <strong>{insight.title}</strong>
                          <p>{insight.summary}</p>
                          {insight.confidence != null && <Progress percent={Math.round(insight.confidence * 100)} size="small" showInfo={false} />}
                        </article>
                      ))}
                    </div>
                  ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚无足够结果；完成实验或回流后将自动形成策略洞察" />}
                </Card>
              </div>
            </>
          )}
        </section>
      </div>

      <Modal
        title="新建视觉运营活动"
        open={createOpen}
        okText="创建并开始"
        cancelText="取消"
        confirmLoading={createCampaign.isPending}
        onCancel={() => setCreateOpen(false)}
        onOk={() => form.submit()}
        destroyOnClose
      >
        <p className="text-sm text-slate-500 mb-5">先定义业务目标，再让系统推荐、生成、审核和验证围绕同一目标协作。</p>
        <Form form={form} layout="vertical" onFinish={handleCreate} initialValues={{ market: "us", objective_metric: "CTR" }}>
          <Form.Item name="name" label="活动名称" rules={[{ required: true, message: "请输入活动名称" }]}>
            <Input placeholder="例如：美国站夏季连衣裙视觉增长活动" maxLength={120} />
          </Form.Item>
          <div className="office-form-grid">
            <Form.Item name="market" label="目标市场" rules={[{ required: true, message: "请选择目标市场" }]}>
              <Select options={MARKET_OPTIONS_SELECT} />
            </Form.Item>
            <Form.Item name="objective_metric" label="核心指标">
              <Select options={[{ value: "CTR", label: "点击率（CTR）" }, { value: "CVR", label: "转化率（CVR）" }, { value: "return_rate", label: "退货率" }, { value: "revenue", label: "营收" }]} />
            </Form.Item>
          </div>
          <div className="office-form-grid">
            <Form.Item name="objective" label="经营目标" rules={[{ required: true, message: "请输入希望达成的结果" }]}>
              <Input placeholder="例如：验证轻度生活化场景是否能提升首图点击" maxLength={200} />
            </Form.Item>
            <Form.Item name="target_value" label="目标值（可选）">
              <InputNumber min={0} style={{ width: "100%" }} placeholder="例如：0.05" />
            </Form.Item>
          </div>
          <Form.Item name="description" label="活动背景（可选）">
            <Input.TextArea rows={3} placeholder="补充人群、商品、季节或渠道等上下文，方便团队理解本次决策边界。" maxLength={500} showCount />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}

function Metric({ label, value, danger = false }: { label: string; value: React.ReactNode; danger?: boolean }) {
  return <Card className="office-metric-card"><span className="office-kpi-strip__label">{label}</span><strong className={danger ? "office-kpi-strip__value office-kpi-strip__value--danger" : "office-kpi-strip__value"}>{value}</strong></Card>;
}
