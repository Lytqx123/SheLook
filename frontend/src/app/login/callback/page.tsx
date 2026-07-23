"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Alert, Card, Spin, Typography } from "antd";

import { api } from "@/lib/api";

function OIDCCallbackContent() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [identityLabel, setIdentityLabel] = useState("企业身份");
  const callbackStarted = useRef(false);

  useEffect(() => {
    if (callbackStarted.current) return;
    callbackStarted.current = true;

    const code = params.get("code");
    const state = params.get("state");
    const providerFromQuery = params.get("provider") || params.get("login_provider");
    const providerFromSession = typeof window !== "undefined"
      ? sessionStorage.getItem("shelook_login_provider")
      : null;
    const provider = providerFromQuery || providerFromSession || undefined;
    setIdentityLabel(provider === "feishu" ? "飞书企业身份" : "企业身份");
    const providerError = params.get("error_description") || params.get("error");
    if (providerError) {
      if (typeof window !== "undefined") {
        sessionStorage.removeItem("shelook_login_provider");
      }
      setError(providerError);
      return;
    }
    if (!code || !state) {
      if (typeof window !== "undefined") {
        sessionStorage.removeItem("shelook_login_provider");
      }
      setError("企业登录回调缺少 code 或 state");
      return;
    }
    // 服务端只信任一次性 state，并由其决定飞书或企业 SSO 回调分流。
    api.completeOIDCLogin(code, state)
      .then((token) => {
        localStorage.setItem("shelook_auth", JSON.stringify(token));
        router.replace("/publish");
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "企业登录失败");
      })
      .finally(() => {
        if (typeof window !== "undefined") {
          sessionStorage.removeItem("shelook_login_provider");
        }
      });
  }, [params, router]);

  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "#F5F7FB" }}>
      <Card style={{ width: 420, textAlign: "center" }}>
        {error ? (
          <Alert type="error" showIcon message="登录失败" description={error} />
        ) : (
          <>
            <Spin size="large" />
            <Typography.Paragraph style={{ marginTop: 20, marginBottom: 0 }}>
              正在验证{identityLabel}…
            </Typography.Paragraph>
          </>
        )}
      </Card>
    </div>
  );
}

export default function OIDCCallbackPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: "100vh", display: "grid", placeItems: "center" }}><Spin size="large" /></div>}>
      <OIDCCallbackContent />
    </Suspense>
  );
}
