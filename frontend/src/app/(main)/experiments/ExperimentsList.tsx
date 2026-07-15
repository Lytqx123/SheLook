"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Table,
  Button,
  Tag,
  Modal,
  Form,
  InputNumber,
  Select,
  App,
  Alert,
} from "antd";
import {
  PlusOutlined,
  ThunderboltOutlined,
  StopOutlined,
  SyncOutlined,
  EyeOutlined,
} from "@ant-design/icons";
import {
  useExperiments,
  useCreateExperiment,
  useTriggerAutoCreateExperiments,
  useAutoExperimentSummary,
  useStopExperiment,
  useUpdateExperimentTraffic,
} from "@/hooks";
import type { Experiment } from "@/types";
import PageHeader from "@/components/PageHeader";

function ExperimentRowActions({ record }: { record: Experiment }) {
  const router = useRouter();
  const stopExperiment = useStopExperiment();
  const updateTraffic = useUpdateExperimentTraffic();
  const { message } = App.useApp();

  return (
    <div className="flex items-center gap-1">
      <Button
        type="text"
        size="small"
        icon={<EyeOutlined />}
        onClick={() => router.push(`/experiments/${record.id}`)}
      >
        详情
      </Button>
      <Button
        type="text"
        size="small"
        icon={<SyncOutlined />}
        disabled={record.status !== "running"}
        loading={updateTraffic.isPending}
        onClick={() => {
          updateTraffic.mutate(record.id, {
            onSuccess: (data) =>
              message.success(
                `流量已更新 · 新比例 ${(data.new_ratio * 100).toFixed(0)}%`
              ),
            onError: () => message.error("流量更新失败"),
          });
        }}
      >
        UCB
      </Button>
      <Button
        type="text"
        size="small"
        danger
        icon={<StopOutlined />}
        disabled={record.status !== "running"}
        loading={stopExperiment.isPending}
        onClick={() => {
          stopExperiment.mutate(record.id, {
            onSuccess: () => message.success("实验已停止"),
            onError: () => message.error("停止失败"),
          });
        }}
      >
        停止
      </Button>
    </div>
  );
}

export default function ExperimentsList() {
  const [modalOpen, setModalOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);
  const [form] = Form.useForm();
  const { message } = App.useApp();

  const { data, isPending, error } = useExperiments(page, pageSize);
  const createExperiment = useCreateExperiment();
  const triggerAutoCreate = useTriggerAutoCreateExperiments();
  const { data: autoSummary } = useAutoExperimentSummary();

  const columns = [
    {
      title: "实验ID",
      dataIndex: "id",
      key: "id",
      width: 80,
    },
    {
      title: "商品ID",
      dataIndex: "product_id",
      key: "product",
      width: 80,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 90,
      render: (s: string) => {
        const statusMap: Record<string, { color: string; text: string }> = {
          running: { color: "processing", text: "运行中" },
          stopped: { color: "default", text: "已停止" },
          completed: { color: "success", text: "已完成" },
        };
        const info = statusMap[s] || { color: "default", text: s };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    {
      title: "创建时间",
      dataIndex: "start_date",
      key: "date",
      width: 110,
      render: (t: string | undefined) => t?.split("T")[0] || "—",
    },
    {
      title: "版本A CTR",
      dataIndex: "result_ctr_a",
      key: "ctr_a",
      width: 100,
      render: (v: number | undefined | null) =>
        v != null ? `${(v * 100).toFixed(2)}%` : "—",
    },
    {
      title: "版本B CTR",
      dataIndex: "result_ctr_b",
      key: "ctr_b",
      width: 100,
      render: (v: number | undefined | null) =>
        v != null ? `${(v * 100).toFixed(2)}%` : "—",
    },
    {
      title: "p-value",
      dataIndex: "p_value",
      key: "pvalue",
      width: 90,
      render: (v: number | undefined | null) =>
        v != null ? v.toFixed(4) : "—",
    },
    {
      title: "显著性",
      key: "significant",
      width: 80,
      render: (_: unknown, record: Experiment) => {
        if (record.p_value == null) return "—";
        return record.p_value < 0.05 ? (
          <Tag color="green">显著</Tag>
        ) : (
          <Tag color="default">不显著</Tag>
        );
      },
    },
    {
      title: "操作",
      key: "action",
      width: 220,
      render: (_: unknown, record: Experiment) => (
        <ExperimentRowActions record={record} />
      ),
    },
  ];

  return (
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        <PageHeader
          title="A/B 实验中心"
          subtitle="创建和管理商品图 A/B 实验，量化视觉方案效果"
          extra={
            <>
              {autoSummary && (
                <Tag color="blue">
                  共 {autoSummary.total_experiments} 个实验 · 运行中 {autoSummary.running}
                </Tag>
              )}
              <Button
                icon={<ThunderboltOutlined />}
                onClick={() => {
                  triggerAutoCreate.mutate(undefined, {
                    onSuccess: (data) => message.success(`自动扫描完成：创建 ${data.created} 个实验`),
                    onError: () => message.error("自动创建失败"),
                  });
                }}
                loading={triggerAutoCreate.isPending}
              >
                智能扫描创建
              </Button>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setModalOpen(true)}
                size="large"
              >
                创建实验
              </Button>
            </>
          }
        />

        {error && (
          <Alert
            type="error"
            showIcon
            title="实验数据加载失败"
            description={error instanceof Error ? error.message : "请检查网络连接后重试"}
            style={{ marginBottom: 20 }}
          />
        )}
        <div className="bg-white rounded-lg">
          <Table
            columns={columns}
            dataSource={data?.items || []}
            rowKey="id"
            loading={isPending}
            pagination={{
              total: data?.total || 0,
              pageSize: pageSize,
              current: page,
              showTotal: (t) => `共 ${t} 条`,
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
              },
            }}
            size="middle"
            locale={{ emptyText: "暂无实验数据，点击右上角创建新实验" }}
          />
        </div>

        {/* 创建实验弹窗 */}
        <Modal
          open={modalOpen}
          onCancel={() => setModalOpen(false)}
          title="创建 A/B 实验"
          okText="创建"
          confirmLoading={createExperiment.isPending}
          onOk={async () => {
            const values = await form.validateFields().catch(() => null);
            if (!values) return; // 验证失败，AntD 已在表单字段上显示错误提示
            try {
              await createExperiment.mutateAsync({
                product_id: values.product_id,
                variant_a_image_id: values.variant_a,
                variant_b_image_id: values.variant_b,
                traffic_ratio: values.traffic_ratio || 0.5,
              });
              message.success("实验已创建");
              setModalOpen(false);
              form.resetFields();
            } catch {
              message.error("创建失败，请重试");
            }
          }}
        >
          <Form form={form} layout="vertical">
            <Form.Item
              label="商品"
              name="product_id"
              rules={[{ required: true, message: "请输入商品 ID" }]}
            >
              <InputNumber className="w-full" placeholder="输入商品 ID" min={1} />
            </Form.Item>
            <Form.Item
              label="版本A图片"
              name="variant_a"
              rules={[{ required: true, message: "请输入图片 ID" }]}
            >
              <InputNumber className="w-full" placeholder="输入图片 ID" min={1} />
            </Form.Item>
            <Form.Item
              label="版本B图片"
              name="variant_b"
              rules={[{ required: true, message: "请输入图片 ID" }]}
            >
              <InputNumber className="w-full" placeholder="输入图片 ID" min={1} />
            </Form.Item>
            <Form.Item
              label="流量比例"
              name="traffic_ratio"
              initialValue={0.5}
            >
              <Select
                options={[
                  { value: 0.5, label: "50/50" },
                  { value: 0.3, label: "30/70" },
                  { value: 0.2, label: "20/80" },
                  { value: 0.1, label: "10/90" },
                ]}
              />
            </Form.Item>
          </Form>
        </Modal>
      </div>
  );
}
