"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Alert,
  App,
  Button,
  Card,
  Divider,
  Form,
  Input,
  Select,
  Typography,
} from "antd";
import {
  CheckCircleOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from "@ant-design/icons";
import Image from "next/image";

import { useLogin } from "@/hooks";
import { api } from "@/lib/api";
import type {
  AuthConfigResponse,
  AuthLoginMethod,
  LoginRequest,
} from "@/types";

const { Title, Text, Paragraph } = Typography;
const { Option } = Select;

type ProviderId = "feishu" | "enterprise_sso" | "development";

interface LoginProvider {
  id: ProviderId;
  label: string;
  loginPath?: string;
}

interface ResolvedLoginProviders {
  feishu?: LoginProvider;
  enterpriseSso?: LoginProvider;
  development?: LoginProvider;
}

const PROVIDER_DEFAULTS: Record<ProviderId, Omit<LoginProvider, "id">> = {
  feishu: { label: "使用飞书登录", loginPath: "/auth/feishu/login" },
  enterprise_sso: { label: "企业 SSO 登录", loginPath: "/auth/login" },
  development: { label: "开发测试账号" },
};

function normalizeProviderId(id?: string): ProviderId | undefined {
  switch (id?.toLowerCase()) {
    case "feishu":
    case "lark":
      return "feishu";
    case "enterprise_sso":
    case "enterprise-sso":
    case "oidc":
    case "sso":
      return "enterprise_sso";
    case "development":
    case "development_account":
    case "local":
    case "password":
      return "development";
    default:
      return undefined;
  }
}

function isSafeLoginPath(path?: string): path is string {
  return Boolean(path && /^\/auth\/[a-zA-Z0-9_\-/]+$/.test(path));
}

function toApiRelativeLoginPath(path?: string): string | undefined {
  const relativePath = path?.replace(/^\/api(?=\/auth\/)/, "");
  return isSafeLoginPath(relativePath) ? relativePath : undefined;
}

/** Prefer the explicit provider list; retain only the previous mode as a rollout fallback. */
function resolveLoginProviders(config: AuthConfigResponse): ResolvedLoginProviders {
  const methods = config.login_methods ?? [];
  const hasMethodConfiguration = methods.length > 0;
  const resolved = new Map<ProviderId, LoginProvider>();

  if (hasMethodConfiguration) {
    methods.forEach((method: AuthLoginMethod) => {
      const id = normalizeProviderId(method.id);
      if (!id) return;
      const defaults = PROVIDER_DEFAULTS[id];
      resolved.set(id, {
        id,
        label: method.label,
        loginPath: toApiRelativeLoginPath(method.login_path) || defaults.loginPath,
      });
    });
  } else if (config.mode === "oidc") {
    resolved.set("enterprise_sso", { id: "enterprise_sso", ...PROVIDER_DEFAULTS.enterprise_sso });
  } else if (config.mode === "development") {
    resolved.set("development", { id: "development", ...PROVIDER_DEFAULTS.development });
  }

  return {
    feishu: resolved.get("feishu"),
    enterpriseSso: resolved.get("enterprise_sso"),
    development: resolved.get("development"),
  };
}

export default function LoginPage() {
  const router = useRouter();
  const loginMutation = useLogin();
  const [form] = Form.useForm<LoginRequest>();
  const { message } = App.useApp();
  const [providers, setProviders] = useState<ResolvedLoginProviders | null>(null);
  const [activeProvider, setActiveProvider] = useState<ProviderId | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined" && localStorage.getItem("shelook_auth")) {
      router.replace("/publish");
    }
  }, [router]);

  useEffect(() => {
    api.getAuthConfig()
      .then((config) => {
        setConfigError(null);
        setProviders(resolveLoginProviders(config));
      })
      .catch(() => {
        // Do not expose a development form merely because a production API is unavailable.
        setConfigError("暂时无法读取组织登录配置，请稍后重试或联系管理员。");
        setProviders({});
      });
  }, []);

  const handleExternalLogin = async (provider: LoginProvider) => {
    setActiveProvider(provider.id);
    try {
      const response = provider.id === "feishu"
        ? await api.beginFeishuLogin(provider.loginPath)
        : await api.beginOIDCLogin(provider.loginPath);
      if (typeof window !== "undefined") {
        sessionStorage.setItem("shelook_login_provider", provider.id);
        window.location.assign(response.authorization_url);
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : "无法启动企业登录");
      setActiveProvider(null);
    }
  };

  const handleSubmit = async (values: LoginRequest) => {
    try {
      await loginMutation.mutateAsync(values);
      message.success("登录成功");
      router.replace("/publish");
    } catch (error: unknown) {
      message.error(error instanceof Error ? error.message : "登录失败");
    }
  };

  const hasExternalProvider = Boolean(providers?.feishu || providers?.enterpriseSso);
  const hasAnyProvider = Boolean(
    providers?.feishu || providers?.enterpriseSso || providers?.development,
  );

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
          <Text className="login-card__subtitle">
            使用受组织管理的身份登录，继续管理视觉运营工作。
          </Text>

          <div className="login-auth-options" aria-live="polite">
            {providers === null ? (
              <Button size="large" block loading>正在读取登录配置</Button>
            ) : (
              <>
                {providers.feishu && (
                  <Button
                    className="login-provider-button login-provider-button--feishu"
                    size="large"
                    block
                    loading={activeProvider === "feishu"}
                    onClick={() => handleExternalLogin(providers.feishu!)}
                  >
                    <span className="login-provider-button__content">
                      <span className="login-feishu-mark" aria-hidden="true">飞</span>
                      <span>{providers.feishu.label}</span>
                    </span>
                    <span className="login-provider-button__hint">推荐</span>
                  </Button>
                )}

                {providers.enterpriseSso && (
                  <Button
                    className="login-provider-button"
                    size="large"
                    block
                    icon={<SafetyCertificateOutlined />}
                    loading={activeProvider === "enterprise_sso"}
                    onClick={() => handleExternalLogin(providers.enterpriseSso!)}
                  >
                    {providers.enterpriseSso.label}
                  </Button>
                )}

                {hasExternalProvider && providers.development && (
                  <Divider plain>或使用开发测试账号</Divider>
                )}

                {providers.development && (
                  <div className="login-development">
                    <div className="login-development__heading">
                      <span>{providers.development.label}</span>
                      <Text type="secondary">仅限开发与演示环境</Text>
                    </div>
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
                          prefix={<UserOutlined style={{ color: "#8A95A8" }} />}
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
                        icon={<LockOutlined />}
                        loading={loginMutation.isPending}
                      >
                        进入工作台
                      </Button>
                    </Form>
                  </div>
                )}

                {configError ? (
                  <Alert type="error" showIcon message="无法加载登录配置" description={configError} />
                ) : !hasAnyProvider && (
                  <Alert
                    type="warning"
                    showIcon
                    message="当前组织尚未配置登录方式"
                    description="请联系组织管理员开通飞书、企业 SSO 或受控开发账号。"
                  />
                )}
              </>
            )}
          </div>

          <Divider />
          <Paragraph className="login-card__note">
            仅支持企业身份与受控开发账号；不支持个人微信登录。
          </Paragraph>
        </Card>
      </main>
    </div>
  );
}
