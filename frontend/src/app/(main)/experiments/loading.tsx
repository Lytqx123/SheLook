"use client";

import { Card, Skeleton } from "antd";

export default function ExperimentsLoading() {
  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16, display: "flex", gap: 12 }}>
        <Skeleton.Input active style={{ width: 140 }} />
        <div style={{ flex: 1 }} />
      </div>

      {[1, 2, 3].map((i) => (
        <Card key={i} style={{ marginBottom: 16 }}>
          <Skeleton active paragraph={{ rows: 3 }} />
        </Card>
      ))}
    </div>
  );
}
