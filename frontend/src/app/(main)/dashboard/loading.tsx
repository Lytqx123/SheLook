import { Spin } from "antd";

/** 仪表盘页面加载骨架屏 */
export default function DashboardLoading() {
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "60vh" }}>
      <Spin size="large" description="加载中..." />
    </div>
  );
}
