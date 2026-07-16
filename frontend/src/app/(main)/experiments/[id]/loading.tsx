"use client";

import { Card, Skeleton } from "antd";

export default function ExperimentDetailLoading() {
  return (
    <div style={{ padding: 24 }}>
      <Card style={{ marginBottom: 24 }}>
        <Skeleton active paragraph={{ rows: 3 }} />
      </Card>

      <Card style={{ marginBottom: 24 }}>
        <Skeleton.Input active style={{ width: 180, marginBottom: 16 }} />
        <div style={{ height: 300, background: "#F1F5F9", borderRadius: 8 }}>
          <Skeleton active paragraph={{ rows: 6 }} />
        </div>
      </Card>

      <Card>
        <Skeleton.Input active style={{ width: 160, marginBottom: 16 }} />
        <div style={{ height: 250, background: "#F1F5F9", borderRadius: 8 }}>
          <Skeleton active paragraph={{ rows: 5 }} />
        </div>
      </Card>
    </div>
  );
}
