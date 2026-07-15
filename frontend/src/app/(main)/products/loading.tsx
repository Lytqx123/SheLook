"use client";

import { Card, Skeleton } from "antd";

export default function ProductsLoading() {
  return (
    <div style={{ padding: 24 }}>
      <Skeleton.Input active style={{ width: 200, marginBottom: 24 }} />
      <Card>
        <Skeleton active paragraph={{ rows: 8 }} />
      </Card>
    </div>
  );
}
