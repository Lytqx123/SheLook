"use client";

import { Card, Skeleton } from "antd";

export default function MetricsLoading() {
  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
        {[1, 2, 3, 4].map((i) => (
          <Card key={i}>
            <Skeleton active paragraph={{ rows: 1 }} />
          </Card>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {[1, 2].map((i) => (
          <Card key={i}>
            <Skeleton.Input active style={{ width: 160, marginBottom: 16 }} />
            <Skeleton active paragraph={{ rows: 5 }} />
          </Card>
        ))}
      </div>
    </div>
  );
}
