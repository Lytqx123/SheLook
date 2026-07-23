"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Form,
  Input,
  Popconfirm,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { DeleteOutlined, SafetyCertificateOutlined, SaveOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import PageHeader from "@/components/PageHeader";
import {
  useDeleteProviderConfig,
  useProviderConfigs,
  useUpdateProviderConfig,
  useValidateProviderConfig,
} from "@/hooks";
import type { ProviderConfig, ProviderConfigInput } from "@/types";

type ConfigFormValues = Record<string, string | boolean | undefined>;

const { Text } = Typography;

function statusTag(status: string) {
  const label = {
    configured: "已启用",
    incomplete: "待配置",
    disabled: "已停用",
  }[status] ?? status;
  const color = { configured: "green", incomplete: "orange", disabled: "default" }[status] ?? "default";
  return <Tag color={color}>{label}</Tag>;
}

export default function ProviderConfigsContent() {
  const { message } = App.useApp();
  const { data: providers = [], isLoading } = useProviderConfigs();
  const updateMutation = useUpdateProviderConfig();
  const validateMutation = useValidateProviderConfig();
  const deleteMutation = useDeleteProviderConfig();
  const [selectedProvider, setSelectedProvider] = useState<ProviderConfig["provider"] | null>(null);
  const [form] = Form.useForm<ConfigFormValues>();

  const selected = useMemo(
    () => providers.find((provider) => provider.provider === selectedProvider) ?? null,
    [providers, selectedProvider],
  );

  useEffect(() => {
    if (!selectedProvider && providers[0]) setSelectedProvider(providers[0].provider);
  }, [providers, selectedProvider]);

  useEffect(() => {
    if (!selected) return;
    const values: ConfigFormValues = { enabled: selected.enabled };
    selected.config_fields.forEach((field) => {
      values[`config:${field.key}`] = selected.config[field.key] ?? "";
    });
    selected.credential_fields.forEach((field) => {
      values[`credential:${field.key}`] = "";
    });
    form.resetFields();
    form.setFieldsValue(values);
  }, [form, selected]);

  const save = async (values: ConfigFormValues) => {
    if (!selected) return;
    const config = Object.fromEntries(
      selected.config_fields
        .map((field) => [field.key, String(values[`config:${field.key}`] ?? "").trim()] as const)
        .filter(([, value]) => Boolean(value)),
    );
    const credentials = Object.fromEntries(
      selected.credential_fields
        .map((field) => [field.key, String(values[`credential:${field.key}`] ?? "").trim()] as const)
        .filter(([, value]) => Boolean(value)),
    );
    const hasCredentials = Object.keys(credentials).length > 0;
    const enabled = Boolean(values.enabled);
    if (enabled && !selected.credentials_configured && !hasCredentials) {
      message.error("首次启用时必须填写该服务所需的完整 API 凭据。");
      return;
    }
    const body: ProviderConfigInput = {
      enabled,
      config,
      ...(hasCredentials ? { credentials } : {}),
    };
    try {
      const saved = await updateMutation.mutateAsync({ provider: selected.provider, body });
      setSelectedProvider(saved.provider);
      message.success("配置已加密保存；凭据不会返回到浏览器。");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存外部服务配置失败");
    }
  };

  const validate = async () => {
    if (!selected) return;
    try {
      const result = await validateMutation.mutateAsync(selected.provider);
      if (result.status === "configured") message.success(result.message);
      else message.warning(result.message);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "校验失败");
    }
  };

  const remove = async () => {
    if (!selected) return;
    try {
      await deleteMutation.mutateAsync(selected.provider);
      message.success("外部服务配置及其加密凭据已移除。");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "删除失败");
    }
  };

  const columns: ColumnsType<ProviderConfig> = [
    { title: "服务", dataIndex: "display_name", key: "display_name" },
    { title: "用途", key: "capabilities", render: (_, item) => item.capabilities.map((capability) => <Tag key={capability}>{capability}</Tag>) },
    { title: "状态", dataIndex: "status", key: "status", width: 110, render: statusTag },
    { title: "凭据", key: "credentials", width: 115, render: (_, item) => item.credentials_configured ? <Tag color="blue">已加密保存</Tag> : <Tag>未配置</Tag> },
    {
      title: "操作",
      key: "action",
      width: 100,
      render: (_, item) => <Button size="small" onClick={() => setSelectedProvider(item.provider)}>配置</Button>,
    },
  ];

  return (
    <main className="office-workspace">
      <PageHeader
        title="外部 API 配置"
        subtitle="当前租户的 AI 视频、AI 图片、AI 审核和已启用指标平台都在此配置。密钥仅能写入，服务端加密保存。"
      />
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 20 }}
        title="浏览器不会保存或读取已提交的 API 密钥"
        description="保存后仅显示加密状态、指纹前缀与版本。数据库、对象存储、监控和登录基础设施的运行密钥仍由部署环境管理，不会下放到网页。"
      />
      <section className="office-two-column">
        <Card title="可配置服务">
          <Table<ProviderConfig>
            loading={isLoading}
            columns={columns}
            dataSource={providers}
            rowKey="provider"
            size="small"
            pagination={false}
            rowClassName={(item) => item.provider === selectedProvider ? "ant-table-row-selected" : ""}
            onRow={(item) => ({ onClick: () => setSelectedProvider(item.provider) })}
          />
        </Card>
        <Card title={selected ? `配置 ${selected.display_name}` : "选择一个服务"}>
          {selected ? (
            <Form form={form} layout="vertical" onFinish={save} requiredMark="optional">
              <Form.Item name="enabled" label="启用服务" valuePropName="checked">
                <Switch checkedChildren="启用" unCheckedChildren="停用" />
              </Form.Item>
              {selected.config_fields.map((field) => (
                <Form.Item
                  key={field.key}
                  name={`config:${field.key}`}
                  label={field.label}
                  rules={field.required ? [{ required: true, message: `请填写${field.label}` }] : undefined}
                >
                  <Input placeholder={field.placeholder ?? undefined} autoComplete="off" />
                </Form.Item>
              ))}
              <Alert
                type="warning"
                showIcon
                title="凭据为只写字段"
                description={selected.credentials_configured ? "留空会保留当前加密凭据；如需轮换，请填写完整的一组新凭据。" : "首次启用时请填写完整的一组凭据。"}
                style={{ marginBottom: 16 }}
              />
              {selected.credential_fields.map((field) => (
                <Form.Item key={field.key} name={`credential:${field.key}`} label={field.label}>
                  <Input.Password
                    autoComplete="new-password"
                    placeholder={field.placeholder ?? (selected.credentials_configured ? "留空则保持不变" : "请输入凭据")}
                  />
                </Form.Item>
              ))}
              <Space wrap>
                <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={updateMutation.isPending}>加密保存</Button>
                <Button onClick={validate} loading={validateMutation.isPending} disabled={!selected.credentials_configured}>校验配置</Button>
                {selected.credentials_configured && (
                  <Popconfirm title={`删除 ${selected.display_name} 配置？`} description="加密凭据也会一并移除。" onConfirm={remove} okText="删除" cancelText="取消">
                    <Button danger icon={<DeleteOutlined />} loading={deleteMutation.isPending}>删除配置</Button>
                  </Popconfirm>
                )}
              </Space>
              <Descriptions size="small" style={{ marginTop: 20 }} column={1}>
                <Descriptions.Item label="配置状态">{statusTag(selected.status)}</Descriptions.Item>
                <Descriptions.Item label="配置版本">{selected.config_version || "—"}</Descriptions.Item>
                <Descriptions.Item label="凭据指纹">{selected.credentials_fingerprint ?? "—"}</Descriptions.Item>
                <Descriptions.Item label="上次更新">{selected.updated_at?.replace("T", " ").replace("Z", "") ?? "—"}</Descriptions.Item>
              </Descriptions>
            </Form>
          ) : isLoading ? <Spin /> : <Text type="secondary">没有可配置服务。</Text>}
        </Card>
      </section>
      <Card style={{ marginTop: 20 }} title={<><SafetyCertificateOutlined style={{ color: "#087B5A", marginRight: 8 }} />配置边界</>}>
        <p>店小秘连接在“系统集成”页维护；这里集中维护会调用第三方 API 的业务服务。更新立即对当前租户生效，正在运行的任务仍使用其启动时已读取的配置。</p>
      </Card>
    </main>
  );
}
