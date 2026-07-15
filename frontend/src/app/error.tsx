"use client";

import { useEffect } from "react";
import { Result, Button } from "antd";
import { ReloadOutlined, HomeOutlined } from "@ant-design/icons";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("页面运行时错误:", error);
  }, [error]);

  return (
    <div className="flex items-center justify-center min-h-screen">
      <Result
        status="error"
        title="页面出错了"
        subTitle={
          error.message || "发生了意外错误，请重试或返回首页"
        }
        extra={[
          <Button
            key="retry"
            type="primary"
            icon={<ReloadOutlined />}
            onClick={reset}
          >
            重试
          </Button>,
          <Button
            key="home"
            icon={<HomeOutlined />}
            onClick={() => (window.location.href = "/")}
          >
            返回首页
          </Button>,
        ]}
      />
    </div>
  );
}
