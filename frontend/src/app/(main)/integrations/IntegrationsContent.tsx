"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import {
  ApiOutlined,
  DeleteOutlined,
  EditOutlined,
  SafetyCertificateOutlined,
  SaveOutlined,
  SyncOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import PageHeader from "@/components/PageHeader";
import {
  useCreateDianxiaomiConnection,
  useDeleteDianxiaomiConnection,
  useDianxiaomiConnections,
  useDianxiaomiSyncRuns,
  useUpdateDianxiaomiConnection,
  useValidateDianxiaomiConnection,
  useStartDianxiaomiSync,
} from "@/hooks";
import type {
  DianxiaomiConnection,
  DianxiaomiConnectionInput,
  DianxiaomiSyncScope,
} from "@/types";

const { Text } = Typography;

const SYNC_SCOPES: { label: string; value: DianxiaomiSyncScope }[] = [
  { label: "商品", value: "products" },
  { label: "刊登", value: "listings" },
  { label: "库存", value: "inventory" },
  { label: "订单", value: "orders" },
  { label: "履约", value: "fulfillment" },
];

type ConnectionFormValues = {
  display_name: string;
  merchant_reference?: string;
  api_base_url?: string;
  shop_references?: string;
  sync_scopes: DianxiaomiSyncScope[];
  sync_interval_minutes: number;
  api_key?: string;
  api_secret?: string;
  access_token?: string;
};

const defaultValues: Pick<ConnectionFormValues, "sync_scopes" | "sync_interval_minutes"> = {
  sync_scopes: ["products", "listings", "inventory", "orders", "fulfillment"],
  sync_interval_minutes: 360,
};

function statusTag(status: string) {
  const color = {
    ready_for_vendor_validation: "green",
    configured: "blue",
    incomplete: "orange",
    disabled: "default",
  }[status] ?? "default";
  const label = {
    ready_for_vendor_validation: "待接口授权验证",
    configured: "已配置",
    incomplete: "配置不完整",
    disabled: "已停用",
  }[status] ?? status;
  return <Tag color={color}>{label}</Tag>;
}

export default function IntegrationsContent() {
  const { message } = App.useApp();
  const { data: connections = [], isLoading } = useDianxiaomiConnections();
  const createMutation = useCreateDianxiaomiConnection();
  const updateMutation = useUpdateDianxiaomiConnection();
  const validateMutation = useValidateDianxiaomiConnection();
  const startSyncMutation = useStartDianxiaomiSync();
  const deleteMutation = useDeleteDianxiaomiConnection();
  const [selected, setSelected] = useState<DianxiaomiConnection | null>(null);
  const [form] = Form.useForm<ConnectionFormValues>();
  const { data: syncRuns = [], isLoading: isSyncRunsLoading } = useDianxiaomiSyncRuns(selected?.id ?? null);

  const beginCreate = () => {
    setSelected(null);
    form.resetFields();
    form.setFieldsValue(defaultValues);
  };

  const editConnection = (connection: DianxiaomiConnection) => {
    setSelected(connection);
    form.setFieldsValue({
      display_name: connection.display_name,
      merchant_reference: connection.merchant_reference ?? undefined,
      api_base_url: connection.api_base_url ?? undefined,
      shop_references: connection.shop_references.join(", "),
      sync_scopes: connection.sync_scopes,
      sync_interval_minutes: connection.sync_interval_minutes,
      api_key: undefined,
      api_secret: undefined,
      access_token: undefined,
    });
  };

  const saveConnection = async (values: ConnectionFormValues) => {
    const credentials = {
      api_key: values.api_key?.trim() || undefined,
      api_secret: values.api_secret?.trim() || undefined,
      access_token: values.access_token?.trim() || undefined,
    };
    const hasCredentials = Object.values(credentials).some(Boolean);
    if (!selected && !hasCredentials) {
      message.error("新建连接至少需要填写一个店小秘授权凭据字段");
      return;
    }

    const body: DianxiaomiConnectionInput = {
      display_name: values.display_name.trim(),
      merchant_reference: values.merchant_reference?.trim() || undefined,
      api_base_url: values.api_base_url?.trim() || undefined,
      shop_references: (values.shop_references ?? "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      sync_scopes: values.sync_scopes,
      sync_interval_minutes: values.sync_interval_minutes,
      ...(hasCredentials ? { credentials } : {}),
    };

    try {
      const saved = selected
        ? await updateMutation.mutateAsync({ id: selected.id, body })
        : await createMutation.mutateAsync(body);
      setSelected(saved);
      editConnection(saved);
      message.success("店小秘连接配置已保存；凭据未返回浏览器");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存配置失败");
    }
  };

  const validateConnection = async () => {
    if (!selected) return;
    try {
      const result = await validateMutation.mutateAsync(selected.id);
      if (result.status === "ready_for_vendor_validation") {
        message.success("配置与加密凭据校验通过");
      } else {
        message.warning(result.message);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : "校验失败");
    }
  };

  const removeConnection = async (connection: DianxiaomiConnection) => {
    try {
      await deleteMutation.mutateAsync(connection.id);
      if (selected?.id === connection.id) beginCreate();
      message.success("店小秘连接已删除，保存的加密凭据已一并移除");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  const startSync = async () => {
    if (!selected) return;
    try {
      const result = await startSyncMutation.mutateAsync(selected.id);
      message.success(result.message);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "无法创建同步任务");
    }
  };

  const columns: ColumnsType<DianxiaomiConnection> = [
    { title: "连接名称", dataIndex: "display_name", key: "display_name" },
    { title: "商户标识", dataIndex: "merchant_reference", key: "merchant_reference", render: (value) => value || "—" },
    { title: "状态", dataIndex: "status", key: "status", render: statusTag },
    { title: "凭据", key: "credentials", render: (_, item) => item.credentials_configured ? <Tag color="blue">已加密保存</Tag> : <Tag>未配置</Tag> },
    { title: "版本", dataIndex: "config_version", key: "config_version", width: 76 },
    {
      title: "操作",
      key: "actions",
      width: 144,
      render: (_, item) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => editConnection(item)}>编辑</Button>
          <Popconfirm title="删除此店小秘连接？" description="加密凭据也会被删除。" onConfirm={() => removeConnection(item)} okText="删除" cancelText="取消">
            <Button size="small" danger icon={<DeleteOutlined />} loading={deleteMutation.isPending} aria-label={`删除 ${item.display_name}`} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <main className="office-workspace">
      <PageHeader
        title="系统集成 · 店小秘"
        subtitle="为当前租户安全维护店小秘连接、同步范围和授权状态。"
        extra={<Link href="/integrations/providers"><Button>外部 API 配置</Button></Link>}
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 20 }}
        title="当前第一阶段只保存并校验连接配置"
        description="店小秘公开帮助页不足以确认贵司账号可用的第三方 ERP 接口字段、签名和授权范围。填入获授权的 API 地址与凭据后，可完成安全配置校验并创建一次同步任务；在拿到对应开放平台契约前，任务会明确显示为“等待供应商契约”，系统不会伪造外部请求或数据。"
      />

      <section className="office-two-column">
        <Card
          title={<><ApiOutlined style={{ marginRight: 8, color: "#2563EB" }} />已配置连接</>}
          extra={<Button onClick={beginCreate}>新建连接</Button>}
        >
          <Table<DianxiaomiConnection>
            loading={isLoading}
            columns={columns}
            dataSource={connections}
            rowKey="id"
            size="small"
            pagination={false}
            locale={{ emptyText: "尚未配置店小秘连接" }}
          />
        </Card>

        <Card title={<><SafetyCertificateOutlined style={{ marginRight: 8, color: "#087B5A" }} />{selected ? "编辑连接" : "新建连接"}</>}>
          <Form form={form} layout="vertical" initialValues={defaultValues} onFinish={saveConnection} requiredMark="optional">
            <Form.Item name="display_name" label="连接名称" rules={[{ required: true, message: "请输入便于识别的连接名称" }]}>
              <Input placeholder="例如：店小秘 · 北美主账号" maxLength={128} />
            </Form.Item>
            <div className="office-form-grid">
              <Form.Item name="merchant_reference" label="店小秘商户标识"><Input placeholder="可选，用于人工核对" maxLength={128} /></Form.Item>
              <Form.Item name="sync_interval_minutes" label="预设自动同步频率" extra="真实适配器完成供应商契约验收后才会启用；当前请用下方按钮手动发起。"><Select options={[{ value: 60, label: "每 1 小时" }, { value: 360, label: "每 6 小时" }, { value: 720, label: "每 12 小时" }, { value: 1440, label: "每天" }]} /></Form.Item>
            </div>
            <Form.Item name="api_base_url" label="已获授权的 API 地址" rules={[{ type: "url", message: "请输入合法 HTTPS URL" }]}>
              <Input placeholder="https://…（以贵司店小秘开放平台文档为准）" inputMode="url" />
            </Form.Item>
            <Form.Item name="shop_references" label="店铺标识" extra="多个店铺用英文逗号分隔；可在授权范围确认后再补充。">
              <Input placeholder="shop-us-01, shop-eu-01" />
            </Form.Item>
            <Form.Item name="sync_scopes" label="计划同步范围">
              <Checkbox.Group options={SYNC_SCOPES} />
            </Form.Item>

            <Alert type="warning" showIcon title="凭据为只写字段" description="保存后无法查看原值；如需轮换，请重新填写。不要将凭据粘贴到工单、聊天或浏览器地址栏。" style={{ marginBottom: 16 }} />
            <Form.Item name="api_key" label="API Key"><Input.Password autoComplete="new-password" placeholder={selected ? "留空则保持原凭据" : "按开放平台文档填写"} /></Form.Item>
            <Form.Item name="api_secret" label="API Secret"><Input.Password autoComplete="new-password" placeholder={selected ? "留空则保持原凭据" : "按开放平台文档填写"} /></Form.Item>
            <Form.Item name="access_token" label="Access Token"><Input.Password autoComplete="new-password" placeholder={selected ? "留空则保持原凭据" : "按开放平台文档填写"} /></Form.Item>

            <Space wrap>
              <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={createMutation.isPending || updateMutation.isPending}>安全保存</Button>
              {selected && <Button onClick={validateConnection} loading={validateMutation.isPending}>校验加密配置</Button>}
              {selected && <Text type="secondary">配置版本 {selected.config_version} · 指纹 {selected.credentials_fingerprint ?? "—"}</Text>}
            </Space>
          </Form>
          {selected?.last_sync_error && <Descriptions size="small" style={{ marginTop: 18 }}><Descriptions.Item label="最近状态">{selected.last_sync_error}</Descriptions.Item></Descriptions>}
        </Card>
      </section>

      {selected && (
        <Card
          title={<><SyncOutlined style={{ marginRight: 8, color: "#2563EB" }} />同步运行记录</>}
          style={{ marginTop: 20 }}
          extra={<Button icon={<SyncOutlined />} onClick={startSync} loading={startSyncMutation.isPending}>发起一次同步</Button>}
        >
          <Table
            loading={isSyncRunsLoading}
            dataSource={syncRuns}
            rowKey="id"
            size="small"
            pagination={false}
            locale={{ emptyText: "尚未创建同步任务" }}
            columns={[
              { title: "状态", dataIndex: "status", width: 190, render: (status: string) => <Tag color={status === "succeeded" ? "green" : status === "awaiting_provider_contract" ? "orange" : status === "failed" ? "red" : "blue"}>{status === "awaiting_provider_contract" ? "等待供应商契约" : status}</Tag> },
              { title: "范围", dataIndex: "requested_scopes", render: (scopes: DianxiaomiSyncScope[]) => scopes.map((scope) => SYNC_SCOPES.find((item) => item.value === scope)?.label ?? scope).join("、") || "—" },
              { title: "接收 / 写入", key: "counts", width: 130, render: (_, run) => `${run.records_received} / ${run.records_applied}` },
              { title: "开始时间", dataIndex: "started_at", width: 190, render: (value: string) => value ? value.replace("T", " ").replace("Z", "") : "—" },
              { title: "结果说明", dataIndex: "error_message", render: (value: string | null) => value || "已完成" },
            ]}
          />
        </Card>
      )}
    </main>
  );
}
