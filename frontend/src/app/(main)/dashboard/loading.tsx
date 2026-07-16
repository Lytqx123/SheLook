import { Spin } from "antd";

// 这个loading是AI生成的，看着还行就不改了
export default function DashboardLoading() {
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "60vh" }}>
      <Spin size="large" description="加载中..." />
    </div>
  );
}
