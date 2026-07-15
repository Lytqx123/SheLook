"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Alert, Card, Spin, Typography } from "antd";

import { api } from "@/lib/api";

function OIDCCallbackContent() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = params.get("code");
    const state = params.get("state");
    const providerError = params.get("error_description") || params.get("error");
    if (providerError) {
      setError(providerError);
      return;
    }
    if (!code || !state) {
      setError("企业登录回调缺少 code 或 state");
      return;
    }
    api.completeOIDCLogin(code, state)
      .then((token) => {
        localStorage.setItem("shelook_auth", JSON.stringify(token));
        router.replace("/publish");
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "企业登录失败");
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
              正在验证企业身份…
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
