"use client";

import { useMemo, useState } from "react";
import { App, Button, Popconfirm, Segmented, Select, Table, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ReloadOutlined, StopOutlined, SyncOutlined } from "@ant-design/icons";
import PageHeader from "@/components/PageHeader";
import { useCancelWorkflowTask, useRetryWorkflowTask, useWorkflowTasks } from "@/hooks";
import type { WorkflowTask, WorkflowTaskStatus } from "@/types";

const STATUS_META: Record<WorkflowTaskStatus, { label: string; color: string }> = {
  created: { label: "待调度", color: "default" },
  queued: { label: "排队中", color: "blue" },
  running: { label: "执行中", color: "processing" },
  waiting_external: { label: "等待外部服务", color: "gold" },
  waiting_human: { label: "等待人工", color: "orange" },
  retrying: { label: "重试中", color: "cyan" },
  succeeded: { label: "已完成", color: "green" },
  failed: { label: "失败", color: "red" },
  cancelled: { label: "已取消", color: "default" },
};

const CANCELABLE = new Set<WorkflowTaskStatus>([
  "created",
  "queued",
  "retrying",
  "waiting_external",
  "waiting_human",
]);

function formatTime(value?: string) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}

export default function TasksContent() {
  const { message } = App.useApp();
  const [status, setStatus] = useState<WorkflowTaskStatus | undefined>();
  const [taskType, setTaskType] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const tasks = useWorkflowTasks({ status, taskType, page, pageSize });
  const cancelTask = useCancelWorkflowTask();
  const retryTask = useRetryWorkflowTask();

  const columns: ColumnsType<WorkflowTask> = useMemo(() => [
    {
      title: "任务",
      key: "task",
      render: (_, task) => (
        <div>
          <div style={{ color: "#26354D", fontWeight: 650 }}>{task.task_type === "image_generation" ? "图片生成" : task.task_type}</div>
          <Tooltip title={task.id}><span className="office-task-id">{task.id}</span></Tooltip>
        </div>
      ),
    },
    {
      title: "关联资源",
      key: "resource",
      width: 130,
      render: (_, task) => `${task.resource_type} #${task.resource_id}`,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 132,
      render: (value: WorkflowTaskStatus) => <Tag color={STATUS_META[value].color}>{STATUS_META[value].label}</Tag>,
    },
    {
      title: "尝试次数",
      key: "attempts",
      width: 100,
      render: (_, task) => `${task.attempt_count} / ${task.max_attempts}`,
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 180,
      render: formatTime,
    },
    {
      title: "结果 / 原因",
      key: "detail",
      ellipsis: true,
      render: (_, task) => task.error_message || (task.result ? "已产出结果" : "—"),
    },
    {
      title: "操作",
      key: "actions",
      width: 152,
      render: (_, task) => (
        <div className="office-task-actions">
          {task.status === "failed" && (
            <Popconfirm
              title="重新投递此任务？"
              description="将基于原始参数创建一条可追溯的人工重试事件。"
              okText="确认重试"
              cancelText="暂不处理"
              onConfirm={() => retryTask.mutate(task.id, {
                onSuccess: (result) => message.success(result.message),
                onError: (error) => message.error(error.message),
              })}
            >
              <Button type="link" size="small" icon={<SyncOutlined />} loading={retryTask.isPending}>重试</Button>
            </Popconfirm>
          )}
          {CANCELABLE.has(task.status) && (
            <Popconfirm
              title="取消尚未执行的任务？"
              description="已进入执行中的任务不允许直接取消，以避免产生不一致的业务结果。"
              okText="确认取消"
              cancelText="保留任务"
              onConfirm={() => cancelTask.mutate(task.id, {
                onSuccess: (result) => message.success(result.message),
                onError: (error) => message.error(error.message),
              })}
            >
              <Button type="link" danger size="small" icon={<StopOutlined />} loading={cancelTask.isPending}>取消</Button>
            </Popconfirm>
          )}
        </div>
      ),
    },
  ], [cancelTask, message, retryTask]);

  return (
    <div className="office-workspace">
      <PageHeader
        title="任务中心"
        subtitle="统一查看生成、模型和经营任务；失败任务可在保留审计链路的前提下人工恢复。"
        extra={<Button icon={<ReloadOutlined />} onClick={() => tasks.refetch()} loading={tasks.isFetching}>刷新</Button>}
      />

      <div className="office-table-toolbar">
        <Segmented
          value={status ?? "all"}
          onChange={(value) => { setStatus(value === "all" ? undefined : value as WorkflowTaskStatus); setPage(1); }}
          options={[
            { label: "全部", value: "all" },
            { label: "处理中", value: "running" },
            { label: "失败", value: "failed" },
            { label: "已完成", value: "succeeded" },
          ]}
        />
        <Select
          allowClear
          placeholder="任务类型"
          value={taskType}
          onChange={(value) => { setTaskType(value); setPage(1); }}
          options={[{ label: "图片生成", value: "image_generation" }]}
          style={{ minWidth: 150 }}
        />
      </div>

      <Table
        columns={columns}
        dataSource={tasks.data?.items ?? []}
        rowKey="id"
        loading={tasks.isPending || tasks.isFetching}
        scroll={{ x: 920 }}
        locale={{ emptyText: tasks.error ? "任务加载失败，请刷新重试" : "当前筛选范围内没有任务" }}
        pagination={{
          current: page,
          pageSize,
          total: tasks.data?.total ?? 0,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 个任务`,
          onChange: (nextPage, nextPageSize) => { setPage(nextPage); setPageSize(nextPageSize); },
        }}
      />
    </div>
  );
}
