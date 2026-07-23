"use client";

import { useEffect, useState } from "react";
import { Alert, App, Button, Card, InputNumber, Popconfirm, Space, Table, Tag, Typography } from "antd";
import { RollbackOutlined, SaveOutlined, SettingOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import PageHeader from "@/components/PageHeader";
import { useResetRuntimeSetting, useRuntimeSettings, useUpdateRuntimeSetting } from "@/hooks";
import type { RuntimeSetting } from "@/types";

const { Text } = Typography;

function displayValue(item: RuntimeSetting, value: number) {
  return item.key === "ctr.dashboard_baseline" ? `${(value * 100).toFixed(2)}%` : String(value);
}

export default function RuntimeSettingsContent() {
  const { message } = App.useApp();
  const { data: settings = [], isLoading } = useRuntimeSettings();
  const saveMutation = useUpdateRuntimeSetting();
  const resetMutation = useResetRuntimeSetting();
  const [drafts, setDrafts] = useState<Record<string, number>>({});

  useEffect(() => {
    setDrafts((previous) => {
      const next = { ...previous };
      settings.forEach((item) => { if (next[item.key] === undefined) next[item.key] = item.value; });
      return next;
    });
  }, [settings]);

  const save = async (item: RuntimeSetting) => {
    const value = drafts[item.key];
    if (value === undefined) return message.error("请输入有效数值");
    try {
      await saveMutation.mutateAsync({ key: item.key, value });
      message.success(`${item.label} 已保存；后续 API 请求和后台任务将读取新版本`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存失败");
    }
  };

  const reset = async (item: RuntimeSetting) => {
    try {
      const result = await resetMutation.mutateAsync(item.key);
      setDrafts((previous) => ({ ...previous, [item.key]: result.value }));
      message.success(`${item.label} 已恢复部署默认值`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "恢复失败");
    }
  };

  const columns: ColumnsType<RuntimeSetting> = [
    {
      title: "配置项", key: "setting", render: (_, item) => (
        <Space direction="vertical" size={1}>
          <Text strong>{item.label}</Text><Text type="secondary">{item.description}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>{item.key}</Text>
        </Space>
      ),
    },
    {
      title: "当前值", key: "value", width: 180, render: (_, item) => (
        <InputNumber
          value={drafts[item.key] ?? item.value}
          min={item.key === "ctr.dashboard_baseline" ? 0 : 100}
          max={item.key === "ctr.dashboard_baseline" ? 1 : 100000000}
          step={item.value_type === "integer" ? 100 : 0.001}
          precision={item.value_type === "integer" ? 0 : 4}
          onChange={(value) => typeof value === "number" && setDrafts((old) => ({ ...old, [item.key]: value }))}
          style={{ width: "100%" }}
        />
      ),
    },
    {
      title: "生效状态", key: "status", width: 220, render: (_, item) => (
        <Space direction="vertical" size={2}>
          <Tag color={item.is_overridden ? "blue" : "default"}>{item.is_overridden ? "当前租户覆盖值" : "部署默认值"}</Tag>
          <Text type="secondary">当前 {displayValue(item, item.value)} · 版本 {item.version}</Text>
          {item.updated_by && <Text type="secondary">最后修改：{item.updated_by}</Text>}
        </Space>
      ),
    },
    {
      title: "操作", key: "action", width: 200, render: (_, item) => (
        <Space wrap>
          <Button size="small" type="primary" icon={<SaveOutlined />} loading={saveMutation.isPending} onClick={() => save(item)}>保存</Button>
          {item.is_overridden && <Popconfirm title="恢复为部署默认值？" description={`默认：${displayValue(item, item.default_value)}`} onConfirm={() => reset(item)} okText="恢复" cancelText="取消"><Button size="small" icon={<RollbackOutlined />} loading={resetMutation.isPending}>恢复默认</Button></Popconfirm>}
        </Space>
      ),
    },
  ];

  return (
    <main className="office-workspace">
      <PageHeader title="运行时配置" subtitle="为当前租户维护经过批准的业务参数；保存后无需重启服务。" />
      <Alert type="info" showIcon style={{ marginBottom: 20 }} title="安全边界" description="业务运行时参数在这里版本化管理。数据库、Redis、JWT、根加密密钥、TLS 与部署端点等启动级安全配置不会进入浏览器；店小秘 API 凭据仍通过系统集成页的只写加密字段维护。" />
      <Card title={<><SettingOutlined style={{ marginRight: 8, color: "#2563EB" }} />当前租户生效配置</>}>
        <Table loading={isLoading} columns={columns} dataSource={settings} rowKey="key" pagination={false} />
      </Card>
    </main>
  );
}
