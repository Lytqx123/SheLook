"use client";

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("全局错误:", error);
  }, [error]);

  return (
    <html lang="zh-CN">
      <body>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "100vh",
            fontFamily: "system-ui, sans-serif",
          }}
        >
          <h2 style={{ marginBottom: 8 }}>应用发生严重错误</h2>
          <p style={{ color: "#666", marginBottom: 24 }}>
            {error.message || "未知错误"}
          </p>
          <button
            onClick={reset}
            style={{
              padding: "8px 24px",
              background: "#1677ff",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              cursor: "pointer",
            }}
          >
            重试
          </button>
        </div>
      </body>
    </html>
  );
}
