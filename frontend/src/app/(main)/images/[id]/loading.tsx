"use client";

import { Card, Skeleton } from "antd";

/** 图片详情页加载骨架屏 */
export default function ImageDetailLoading() {
  return (
    <div style={{ padding: 24 }}>
      {/* 返回按钮骨架 */}
      <Skeleton.Button active style={{ width: 120, marginBottom: 16 }} />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* 图片预览骨架 */}
        <Card>
          <Skeleton.Input active style={{ width: 160, marginBottom: 16 }} />
          <div style={{ height: 400, background: "#F1F5F9", borderRadius: 8 }}>
            <Skeleton.Image active style={{ width: "100%", height: 400 }} />
          </div>
        </Card>

        {/* 质检与预测骨架 */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* 基本信息 */}
          <Card>
            <Skeleton.Input active style={{ width: 120, marginBottom: 16 }} />
            <Skeleton active paragraph={{ rows: 3 }} />
          </Card>

          {/* 质量评分 */}
          <Card>
            <Skeleton.Input active style={{ width: 120, marginBottom: 16 }} />
            <Skeleton active paragraph={{ rows: 4 }} />
          </Card>

          {/* 效果预估 */}
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
