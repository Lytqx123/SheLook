"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Card, Input, Button, Select, Form, App, Typography, Divider } from "antd";
import { UserOutlined, LockOutlined, SafetyCertificateOutlined, CheckCircleOutlined } from "@ant-design/icons";
import Image from "next/image";
import { useLogin } from "@/hooks";
import { api } from "@/lib/api";
import type { LoginRequest } from "@/types";

const { Title, Text, Paragraph } = Typography;
const { Option } = Select;

export default function LoginPage() {
  const router = useRouter();
  const loginMutation = useLogin();
  const [form] = Form.useForm<LoginRequest>();
  const { message } = App.useApp();
  const [authMode, setAuthMode] = useState<"loading" | "oidc" | "development">("loading");
  const [oidcLoading, setOidcLoading] = useState(false);

  // 已登录则跳转首页
  useEffect(() => {
    if (typeof window !== "undefined" && localStorage.getItem("shelook_auth")) {
      router.replace("/publish");
    }
  }, [router]);

  useEffect(() => {
    api.getAuthConfig()
      .then((config) => setAuthMode(config.mode))
      .catch(() => setAuthMode("development"));
  }, []);

  const handleOIDCLogin = async () => {
    setOidcLoading(true);
    try {
      const response = await api.beginOIDCLogin();
      window.location.assign(response.authorization_url);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "无法启动企业登录");
      setOidcLoading(false);
    }
  };

  const handleSubmit = async (values: LoginRequest) => {
    try {
      await loginMutation.mutateAsync(values);
      message.success("登录成功");
      router.replace("/publish");
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : "登录失败");
    }
  };

  return (
    <div className="login-shell">
      <section className="login-intro" aria-label="SheLook 产品介绍">
        <div className="login-logo-row">
          <Image src="/logo.svg" alt="SheLook" width={126} height={36} priority />
          <span>商品视觉运营平台</span>
        </div>
        <div className="login-kicker">AI-POWERED ECOMMERCE OPERATIONS</div>
        <h1>让每一张商品图，<br />更接近成交。</h1>
        <p>
          从视觉方案、智能生成到市场表现回流，
          在同一个工作台管理商品图的每一次经营决策。
        </p>
        <div className="login-highlights" aria-label="平台能力">
          <span className="login-highlight"><CheckCircleOutlined /> 多市场视觉策略</span>
          <span className="login-highlight"><CheckCircleOutlined /> AI 质检与归因</span>
          <span className="login-highlight"><CheckCircleOutlined /> 可追溯内容发布</span>
        </div>
      </section>

      <main className="login-panel">
        <Card className="login-card" variant="borderless">
          <div className="login-card__icon">
            <SafetyCertificateOutlined style={{ fontSize: 24 }} />
          </div>
          <Title level={2}>欢迎回来</Title>
          <Text className="login-card__subtitle">登录后继续管理您的商品视觉运营。</Text>

          {authMode === "oidc" ? (
            <Button
              type="primary"
              size="large"
              block
              icon={<SafetyCertificateOutlined />}
              loading={oidcLoading}
              onClick={handleOIDCLogin}
            >
              使用企业账号登录
            </Button>
          ) : authMode === "development" ? (
            <Form
              form={form}
              layout="vertical"
              onFinish={handleSubmit}
              initialValues={{ role: "viewer" }}
              requiredMark={false}
            >
              <Form.Item
                name="user_id"
                label="用户 ID"
                rules={[{ required: true, message: "请输入用户 ID" }]}
              >
                <Input
                  size="large"
                  prefix={<UserOutlined style={{ color: "#8A95A8" }} />}
                  placeholder="输入您的用户标识"
                />
              </Form.Item>

              <Form.Item name="username" label="显示名称（可选）">
                <Input
                  size="large"
                  prefix={<LockOutlined style={{ color: "#8A95A8" }} />}
                  placeholder="留空则使用用户 ID"
                />
              </Form.Item>

              <Form.Item name="role" label="访问角色">
                <Select size="large">
                  <Option value="viewer">Viewer（只读）</Option>
                  <Option value="admin">Admin（管理员）</Option>
                </Select>
              </Form.Item>

              <Button
                type="primary"
                htmlType="submit"
                size="large"
                block
                loading={loginMutation.isPending}
                style={{ marginTop: 4 }}
              >
                进入工作台
              </Button>
            </Form>
          ) : (
            <Button size="large" block loading>正在读取登录配置</Button>
          )}

          <Divider />
          <Paragraph className="login-card__note">
            {authMode === "oidc"
              ? "企业 OpenID Connect 单点登录 · 授权码 + PKCE"
              : "本地身份仅供开发与测试环境使用"}
          </Paragraph>
        </Card>
      </main>
    </div>
  );
}
