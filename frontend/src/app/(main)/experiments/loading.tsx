"use client";

import { Card, Skeleton } from "antd";

/** A/B 实验列表加载骨架屏 */
export default function ExperimentsLoading() {
  return (
    <div style={{ padding: 24 }}>
      {/* 操作栏骨架 */}
      <div style={{ marginBottom: 16, display: "flex", gap: 12 }}>
        <Skeleton.Input active style={{ width: 140 }} />
        <div style={{ flex: 1 }} />
      </div>

      {/* 卡片列表骨架 */}
      {[1, 2, 3].map((i) => (
        <Card key={i} style={{ marginBottom: 16 }}>
          <Skeleton active paragraph={{ rows: 3 }} />
        </Card>
      ))}
    </div>
  );
}
