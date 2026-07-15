"use client";

import { useState } from "react";
import {
  Card, Button, Row, Col, Tag,
  Descriptions, App, Spin,
  Table, Popconfirm,
} from "antd";
import {
  SyncOutlined, RocketOutlined, DatabaseOutlined,
  TrophyOutlined, ClockCircleOutlined, HistoryOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import {
  useTriggerFlywheelSync, useTriggerFlywheelRetrain,
  useModelVersions, useRollbackModel,
} from "@/hooks";
import PageHeader from "@/components/PageHeader";
import type {
  FlywheelSyncResponse, FlywheelRetrainResponse,
  ModelVersionInfo,
} from "@/types";

export default function FlywheelContent() {
  const [syncResult, setSyncResult] = useState<FlywheelSyncResponse | null>(null);
  const [retrainResult, setRetrainResult] = useState<FlywheelRetrainResponse | null>(null);

  const syncMutation = useTriggerFlywheelSync();
  const retrainMutation = useTriggerFlywheelRetrain();
  const modelVersionsQuery = useModelVersions();
  const rollbackMutation = useRollbackModel();
  const { message } = App.useApp();

  const handleRollback = async (targetDate: string) => {
    message.loading({ content: "正在回滚模型版本...", key: "rollback" });
    try {
      const res = await rollbackMutation.mutateAsync({ target_date: targetDate });
      if (res.success) {
        message.success({
          content: res.message || `已回滚到 ${res.target_version ?? targetDate}`,
          key: "rollback",
        });
      } else {
        message.error({
          content: res.message || "回滚失败",
          key: "rollback",
        });
      }
    } catch {
      message.error({ content: "回滚失败", key: "rollback" });
    }
  };

  const versionColumns: ColumnsType<ModelVersionInfo> = [
    {
      title: "版本号",
      dataIndex: "version",
      key: "version",
      render: (text, record) => (
        <span className="font-mono">
          {text}
          {record.is_current && (
            <Tag color="#2563EB" className="ml-2">当前</Tag>
          )}
        </span>
      ),
    },
    {
      title: "日期",
      dataIndex: "date",
      key: "date",
    },
    {
      title: "状态",
      key: "status",
      render: (_, record) =>
        record.is_current ? (
          <Tag color="green">当前版本</Tag>
        ) : (
          <Tag color="default">历史版本</Tag>
        ),
    },
    {
      title: "操作",
      key: "action",
      render: (_, record) => (
        <Popconfirm
          title="确认回滚到此版本？"
          description={`将回滚到 ${record.date} 的版本 ${record.version}`}
          okText="确认回滚"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          onConfirm={() => handleRollback(record.date)}
          disabled={record.is_current || rollbackMutation.isPending}
        >
          <Button
            size="small"
            type="default"
            danger
            disabled={record.is_current}
            loading={rollbackMutation.isPending}
          >
            回滚到此版本
          </Button>
        </Popconfirm>
      ),
    },
  ];

  const handleSync = async () => {
    message.loading({ content: "正在执行数据回流与自动标注...", key: "sync" });
    try {
      const res = await syncMutation.mutateAsync();
      setSyncResult(res);
      message.success({ content: "数据回流完成", key: "sync" });
    } catch {
      message.error({ content: "数据回流失败", key: "sync" });
    }
  };

  const handleRetrain = async () => {
    message.loading({ content: "正在训练模型...", key: "retrain" });
    try {
      const res = await retrainMutation.mutateAsync();
      setRetrainResult(res);
      message.success({ content: "模型重训练完成", key: "retrain" });
    } catch {
      message.error({ content: "模型训练失败", key: "retrain" });
    }
  };

  return (
    <div className="space-y-6" style={{ maxWidth: 1280, margin: "0 auto" }}>
      <PageHeader
        title="数据飞轮"
        subtitle="数据回流 → 自动标注 → 模型迭代，驱动效果持续进化"
      />

      {/* 飞轮流程图 */}
      <Card>
        <div className="flex items-center justify-center gap-3 py-6 flex-wrap">
          {[
            { icon: <DatabaseOutlined />, label: "数据回流", desc: "每日 2:00", color: "#2563EB" },
            { icon: <TrophyOutlined />, label: "自动标注", desc: "正/负样本", color: "#059669" },
            { icon: <RocketOutlined />, label: "模型迭代", desc: "每周日 3:00", color: "#722ed1" },
            { icon: <SyncOutlined />, label: "效果提升", desc: "持续进化", color: "#fa8c16" },
          ].map((step, idx, arr) => (
            <div key={step.label} className="flex items-center gap-3">
              <Card size="small" className="text-center min-w-[140px] hover:shadow-md transition-shadow">
                <div style={{ color: step.color, fontSize: 28 }}>{step.icon}</div>
                <div className="font-semibold mt-2 text-sm">{step.label}</div>
                <div className="text-xs text-gray-400 mt-1">{step.desc}</div>
              </Card>
              {idx < arr.length - 1 && (
                <span className="text-gray-300 text-2xl hidden sm:inline">→</span>
              )}
            </div>
          ))}
        </div>
      </Card>

      {/* 调度说明 */}
      <Card className="border-blue-100 bg-blue-50">
        <div className="flex items-start gap-2">
          <ClockCircleOutlined className="text-blue-500 mt-0.5" />
          <div>
            <p className="font-semibold text-blue-700 mb-1">自动化调度</p>
            <p className="text-sm text-blue-600">
              数据回流与自动标注每日凌晨 2:00 自动执行 · 模型重训练每周日凌晨 3:00 自动执行
            </p>
            <p className="text-xs text-blue-500 mt-1">
              下方按钮用于手动触发，适用于数据异常后补跑或紧急迭代场景
            </p>
          </div>
        </div>
      </Card>

      <Row gutter={[20, 20]}>
        {/* 数据回流 */}
        <Col span={12}>
          <Card
            title={
              <div className="flex items-center gap-2">
                <DatabaseOutlined className="text-blue-500" />
                <span>数据回流与标注</span>
              </div>
            }
          >
            <p className="text-sm text-gray-500 mb-4">
              聚合近 30 天图片效果数据，按 CTR 分位数自动标注正/负样本
            </p>
            <Button
              type="primary"
              icon={<SyncOutlined />}
              onClick={handleSync}
              loading={syncMutation.isPending}
              size="large"
              block
            >
              手动触发数据回流
            </Button>

            {syncMutation.isPending && (
              <div className="text-center mt-4">
                <Spin description="执行中...">
                  <div className="py-4" />
                </Spin>
              </div>
            )}

            {syncResult && (
              <div className="mt-4 p-3 bg-gray-50 rounded">
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="状态">
                    <Tag color={syncResult.status === "success" ? "green" : "red"}>
                      {syncResult.status === "success" ? "成功" : syncResult.status}
                    </Tag>
                  </Descriptions.Item>
                  {syncResult.total_samples != null && (
                    <Descriptions.Item label="处理图片数">
                      {syncResult.total_samples}
                    </Descriptions.Item>
                  )}
                  {syncResult.positive_samples != null && (
                    <Descriptions.Item label="正样本（CTR ≥ P75）">
                      <Tag color="green">{syncResult.positive_samples}</Tag>
                    </Descriptions.Item>
                  )}
                  {syncResult.negative_samples != null && (
                    <Descriptions.Item label="负样本（CTR ≤ P25 / 高退货）">
                      <Tag color="red">{syncResult.negative_samples}</Tag>
                    </Descriptions.Item>
                  )}
                  {syncResult.neutral_samples != null && syncResult.neutral_samples > 0 && (
                    <Descriptions.Item label="中性样本">
                      <Tag color="default">{syncResult.neutral_samples}</Tag>
                    </Descriptions.Item>
                  )}
                  {syncResult.high_return_samples != null && syncResult.high_return_samples > 0 && (
                    <Descriptions.Item label="高退货风险样本">
                      <Tag color="orange">{syncResult.high_return_samples}</Tag>
                    </Descriptions.Item>
                  )}
                  {syncResult.ctr_p75 != null && (
                    <Descriptions.Item label="CTR P75 阈值">
                      {(syncResult.ctr_p75 * 100).toFixed(2)}%
                    </Descriptions.Item>
                  )}
                  {syncResult.ctr_p25 != null && (
                    <Descriptions.Item label="CTR P25 阈值">
                      {(syncResult.ctr_p25 * 100).toFixed(2)}%
                    </Descriptions.Item>
                  )}
                  {syncResult.note && (
                    <Descriptions.Item label="备注">
                      <span className="text-orange-500">{syncResult.note}</span>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </div>
            )}
          </Card>
        </Col>

        {/* 模型重训 */}
        <Col span={12}>
          <Card
            title={
              <div className="flex items-center gap-2">
                <RocketOutlined className="text-purple-500" />
                <span>模型重训练</span>
              </div>
            }
          >
            <p className="text-sm text-gray-500 mb-4">
              使用标注样本重新训练 GBDT CTR 预估模型 · 最小样本量 50 条
            </p>
            <Button
              type="primary"
              icon={<RocketOutlined />}
              onClick={handleRetrain}
              loading={retrainMutation.isPending}
              size="large"
              block
              style={{ background: "#722ed1", borderColor: "#722ed1" }}
            >
              手动触发模型重训练
            </Button>

            {retrainMutation.isPending && (
              <div className="text-center mt-4">
                <Spin description="训练中（可能需要几分钟）...">
                  <div className="py-4" />
                </Spin>
              </div>
            )}

            {retrainResult && (
              <div className="mt-4 p-3 bg-gray-50 rounded">
                <Descriptions column={1} size="small">
                  <Descriptions.Item label="状态">
                    <Tag color={
                      retrainResult.status === "success" ? "green"
                        : retrainResult.status === "skipped" ? "orange"
                        : "red"
                    }>
                      {retrainResult.status === "success" ? "成功"
                        : retrainResult.status === "skipped" ? "跳过"
                        : "失败"}
                    </Tag>
                  </Descriptions.Item>
                  {retrainResult.samples != null && (
                    <Descriptions.Item label="训练样本数">
                      {retrainResult.samples}
                    </Descriptions.Item>
                  )}
                  {retrainResult.positive_samples != null && (
                    <Descriptions.Item label="正样本">
                      <Tag color="green">{retrainResult.positive_samples}</Tag>
                    </Descriptions.Item>
                  )}
                  {retrainResult.negative_samples != null && (
                    <Descriptions.Item label="负样本">
                      <Tag color="red">{retrainResult.negative_samples}</Tag>
                    </Descriptions.Item>
                  )}
                  {retrainResult.model_saved != null && (
                    <Descriptions.Item label="模型已保存">
                      <Tag color={retrainResult.model_saved ? "green" : "default"}>
                        {retrainResult.model_saved ? "是" : "否"}
                      </Tag>
                    </Descriptions.Item>
                  )}
                  {retrainResult.ctr_mean != null && (
                    <Descriptions.Item label="CTR 均值">
                      {(retrainResult.ctr_mean * 100).toFixed(2)}%
                    </Descriptions.Item>
                  )}
                  {retrainResult.hit_rate != null && (
                    <Descriptions.Item label="命中率">
                      {(retrainResult.hit_rate * 100).toFixed(2)}%
                    </Descriptions.Item>
                  )}
                  {retrainResult.message && (
                    <Descriptions.Item label="消息">
                      <span className={
                        retrainResult.status === "failed"
                          ? "text-red-500"
                          : retrainResult.status === "skipped"
                            ? "text-orange-500"
                            : "text-gray-600"
                      }>
                        {retrainResult.message}
                      </span>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      {/* 预测模型版本管理 */}
      <Card
        title={
          <div className="flex items-center gap-2">
            <HistoryOutlined style={{ color: "#2563EB" }} />
            <span>预测模型版本管理</span>
          </div>
        }
      >
        <div className="mb-4 p-3 bg-gray-50 rounded">
          <Descriptions column={1} size="small">
            <Descriptions.Item label="当前版本">
              {modelVersionsQuery.isLoading ? (
                <Tag>加载中...</Tag>
              ) : modelVersionsQuery.data?.current_version ? (
                <Tag color="#2563EB" className="font-mono">
                  {modelVersionsQuery.data.current_version}
                </Tag>
              ) : (
                <Tag color="default">暂无</Tag>
              )}
            </Descriptions.Item>
          </Descriptions>
        </div>

        <Table<ModelVersionInfo>
          columns={versionColumns}
          dataSource={modelVersionsQuery.data?.versions ?? []}
          rowKey={(record) => `${record.version}-${record.date}`}
          loading={modelVersionsQuery.isLoading}
          pagination={{ pageSize: 5, showSizeChanger: false }}
          size="middle"
          rowClassName={(record) =>
            record.is_current ? "bg-indigo-50" : ""
          }
        />
      </Card>
    </div>
  );
}
