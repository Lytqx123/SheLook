"use client";

import { Card, Skeleton } from "antd";

export default function ReviewLoading() {
  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16, display: "flex", gap: 12 }}>
        <Skeleton.Input active style={{ width: 160 }} />
        <Skeleton.Input active style={{ width: 120 }} />
      </div>

      <Card>
        <Skeleton active paragraph={{ rows: 1 }} />
        <div style={{ height: 400, background: "#F1F5F9", borderRadius: 8, marginTop: 16 }}>
          <Skeleton active paragraph={{ rows: 8 }} />
        </div>
      </Card>
    </div>
  );
}
