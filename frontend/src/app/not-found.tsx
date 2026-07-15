"use client";

import Link from "next/link";
import { Result, Button } from "antd";
import { HomeOutlined } from "@ant-design/icons";

export default function NotFound() {
  return (
    <div className="flex items-center justify-center min-h-screen">
      <Result
        status="404"
        title="404"
        subTitle="抱歉，您访问的页面不存在。"
        extra={
          <Link href="/">
            <Button type="primary" icon={<HomeOutlined />}>
              返回首页
            </Button>
          </Link>
        }
      />
    </div>
  );
}
