import { Spin } from "antd";

export default function Loading() {
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "60vh" }}>
      <Spin size="large" description="加载中..." />
    </div>
  );
}
