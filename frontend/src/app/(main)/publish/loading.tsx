"use client";

import { Card, Skeleton } from "antd";

/** 发品工作台加载骨架屏 */
export default function PublishLoading() {
  return (
    <div style={{ padding: 24 }}>
      {/* 步骤条骨架 */}
      <Skeleton.Input active style={{ width: "100%", height: 48, marginBottom: 24 }} />

      {/* 表单骨架 */}
      <Card>
        <Skeleton active paragraph={{ rows: 8 }} />
      </Card>
    </div>
  );
}
