"use client";

import { Card, Skeleton } from "antd";

export default function ImageDetailLoading() {
  return (
    <div style={{ padding: 24 }}>
      <Skeleton.Button active style={{ width: 120, marginBottom: 16 }} />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card>
          <Skeleton.Input active style={{ width: 160, marginBottom: 16 }} />
          <div style={{ height: 400, background: "#F1F5F9", borderRadius: 8 }}>
            <Skeleton.Image active style={{ width: "100%", height: 400 }} />
          </div>
        </Card>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <Card>
            <Skeleton.Input active style={{ width: 120, marginBottom: 16 }} />
            <Skeleton active paragraph={{ rows: 3 }} />
          </Card>

          <Card>
            <Skeleton.Input active style={{ width: 120, marginBottom: 16 }} />
            <Skeleton active paragraph={{ rows: 4 }} />
          </Card>

          <Card>
            <Skeleton.Input active style={{ width: 120, marginBottom: 16 }} />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              {[1, 2, 3, 4].map((i) => (
                <Skeleton.Button key={i} active style={{ width: "100%" }} />
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
