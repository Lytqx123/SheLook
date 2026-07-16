"use client";

import { Card, Skeleton } from "antd";

export default function PublishLoading() {
  return (
    <div style={{ padding: 24 }}>
      <Skeleton.Input active style={{ width: "100%", height: 48, marginBottom: 24 }} />

      <Card>
        <Skeleton active paragraph={{ rows: 8 }} />
      </Card>
    </div>
  );
}
