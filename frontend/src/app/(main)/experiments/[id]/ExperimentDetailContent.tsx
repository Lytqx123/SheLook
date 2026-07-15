"use client";

import { useParams, useRouter } from "next/navigation";
import dayjs from "dayjs";
import {
  Card,
  Descriptions,
  Tag,
  Button,
  Row,
  Col,
  Statistic,
  Result,
  Skeleton,
} from "antd";
import {
  ArrowLeftOutlined,
  TrophyOutlined,
} from "@ant-design/icons";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useExperiment, useExperimentBreakdown } from "@/hooks";

export default function ExperimentDetailContent() {
  const params = useParams();
  const router = useRouter();
  const experimentId = Number(params.id);

  const { data: report, isPending, error } = useExperiment(experimentId);
  // 按 date 维度拉取真实 CTR 时序数据，替代 Math.random() 假数据
  const { data: breakdown } = useExperimentBreakdown(experimentId, "date");

  if (isNaN(experimentId)) {
    return (
        <Result
          status="error"
          title="无效的实验 ID"
          extra={
            <Button onClick={() => router.push("/experiments")}>
              返回实验列表
            </Button>
          }
        />
    );
  }

  if (isPending) {
    return (
        <div className="space-y-6" style={{ maxWidth: 1280, margin: "0 auto" }}>
          <Skeleton active paragraph={{ rows: 1 }} />
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
    );
  }

  if (error || !report) {
    return (
        <Result
          status="error"
          title="无法加载实验详情"
          subTitle={error instanceof Error ? error.message : "请检查实验ID是否正确"}
          extra={
            <Button onClick={() => router.push("/experiments")}>
              返回实验列表
            </Button>
          }
        />
    );
  }

  const isSignificant =
    report.p_value != null && report.p_value < 0.05;
  const ctrA = report.result_ctr_a ?? 0;
  const ctrB = report.result_ctr_b ?? 0;
  const lift: number | null = ctrA > 0 ? ((ctrB - ctrA) / ctrA) * 100 : null;

  // 从 breakdown API 拉取真实 CTR 时序，无数据时降级为单点汇总
  const trendData = (breakdown?.breakdown ?? []).map((slice) => ({
    day: slice.dimension_value,
    variantA: Number((((slice.variant_a?.ctr) ?? 0) * 100).toFixed(2)),
    variantB: Number((((slice.variant_b?.ctr) ?? 0) * 100).toFixed(2)),
  }));
  // 无时序数据时用实验汇总 CTR 展示单点，避免图表空白
  const chartData = trendData.length > 0
    ? trendData
    : ctrA > 0 || ctrB > 0
      ? [{ day: "汇总", variantA: Number((ctrA * 100).toFixed(2)), variantB: Number((ctrB * 100).toFixed(2)) }]
      : [];

  return (
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        {/* 返回按钮 + 标题 */}
        <div className="flex items-center gap-4" style={{ marginBottom: 20 }}>
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => router.push("/experiments")}
          >
            返回
          </Button>
          <div>
            <h2 className="text-xl font-bold">实验详情</h2>
            <p className="text-sm text-gray-400">实验 #{experimentId}</p>
          </div>
        </div>

        {/* 基本信息 */}
        <Card title="实验信息" style={{ marginBottom: 20 }}>
          <Descriptions column={2} size="middle" bordered>
            <Descriptions.Item label="实验 ID">{report.id}</Descriptions.Item>
            <Descriptions.Item label="关联商品">{report.product_id}</Descriptions.Item>
            <Descriptions.Item label="版本A图片">{report.variant_a_image_id}</Descriptions.Item>
            <Descriptions.Item label="版本B图片">{report.variant_b_image_id}</Descriptions.Item>
            <Descriptions.Item label="流量比例">
              {report.traffic_ratio != null
                ? `${(report.traffic_ratio * 100).toFixed(0)}:${((1 - report.traffic_ratio) * 100).toFixed(0)}`
                : "—"}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag
                color={
                  report.status === "running"
                    ? "processing"
                    : report.status === "completed"
                      ? "success"
                      : "default"
                }
              >
                {report.status === "running"
                  ? "运行中"
                  : report.status === "completed"
                    ? "已完成"
                    : report.status === "stopped"
                      ? "已停止"
                      : report.status}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="开始时间">
              {report.start_date
                ? dayjs(report.start_date).format("YYYY-MM-DD")
                : "—"}
            </Descriptions.Item>
            <Descriptions.Item label="结束时间">
              {report.end_date
                ? dayjs(report.end_date).format("YYYY-MM-DD")
                : "—"}
            </Descriptions.Item>
          </Descriptions>
        </Card>

        {/* CTR 对比 */}
        <Row gutter={[20, 20]} style={{ marginBottom: 20 }}>
          <Col xs={12} lg={6}>
            <Card>
              <Statistic
                title="版本A CTR"
                value={`${(ctrA * 100).toFixed(2)}%`}
                styles={{ content: { color: "#2563EB" } }}
              />
            </Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card>
              <Statistic
                title="版本B CTR"
                value={`${(ctrB * 100).toFixed(2)}%`}
                styles={{ content: { color: "#059669" } }}
              />
            </Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card>
              <Statistic
                title="CTR Lift"
                value={lift !== null ? `${lift.toFixed(1)}%` : "—"}
                styles={{
                  content: {
                    color: lift !== null && lift > 0 ? "#059669" : "#DC2626",
                  },
                }}
              />
            </Card>
          </Col>
          <Col xs={12} lg={6}>
            <Card>
              <Statistic
                title="显著性"
                value={report.p_value != null ? report.p_value.toFixed(4) : "—"}
                suffix={
                  isSignificant ? (
                    <Tag color="green" style={{ marginLeft: 8 }}>显著</Tag>
                  ) : report.p_value != null ? (
                    <Tag color="default" style={{ marginLeft: 8 }}>不显著</Tag>
                  ) : null
                }
              />
            </Card>
          </Col>
        </Row>

        {/* 胜出方 */}
        {report.winner_image_id && (
          <Card className="border-green-300 bg-green-50" style={{ marginBottom: 20 }}>
            <div className="flex items-center gap-3">
              <TrophyOutlined style={{ fontSize: 28, color: "#D97706" }} />
              <div>
                <h3 className="text-lg font-bold text-green-700">
                  胜出方：图片 #{report.winner_image_id}
                </h3>
                <p className="text-sm text-green-600">
                  {report.winner_image_id === report.variant_a_image_id
                    ? "版本A"
                    : "版本B"}
                  {" "}在本次实验中表现更优
                </p>
              </div>
            </div>
          </Card>
        )}

        {/* CTR 趋势对比图（真实 breakdown 数据） */}
        <Card title="CTR 趋势对比" style={{ marginBottom: 20 }}>
          <div className="office-chart">
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={chartData} margin={{ top: 12, right: 12, left: -12, bottom: 0 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="day" tickLine={false} axisLine={false} minTickGap={24} />
              <YAxis tickFormatter={(v) => `${v}%`} tickLine={false} axisLine={false} width={42} />
              <Tooltip formatter={(v) => `${Number(v).toFixed(2)}%`} labelFormatter={(label) => `日期：${label}`} />
              <Legend iconType="circle" iconSize={7} />
              <Line
                type="monotone"
                dataKey="variantA"
                name="版本A CTR"
                stroke="#2563EB"
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0 }}
              />
              <Line
                type="monotone"
                dataKey="variantB"
                name="版本B CTR"
                stroke="#087B5A"
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0 }}
              />
            </LineChart>
          </ResponsiveContainer>
          </div>
        </Card>

        {/* 统计结论 */}
        {isSignificant && (
          <Card className="border-blue-200 bg-blue-50">
            <h3 className="font-bold text-blue-700 mb-2">实验结论</h3>
            <p className="text-sm text-blue-600">
              在置信度 95% 的水平下，两个版本之间存在统计学显著差异（p ={" "}
              {report.p_value?.toFixed(4)}）。
              {lift != null
                ? (ctrB > ctrA
                  ? `版本B 的 CTR 比 版本A 高 ${lift.toFixed(1)}%，建议采用版本B作为主推方案。`
                  : `版本A 的 CTR 比 版本B 高 ${Math.abs(lift).toFixed(1)}%，建议继续使用版本A。`)
                : `统计结论已生成，但 CTR 数据尚在收集中，请稍后再查看详细对比。`}
            </p>
          </Card>
        )}
      </div>
  );
}
