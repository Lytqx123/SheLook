import { Skeleton } from "antd";

// 通用loading，复杂页面可以自己写一个覆盖
export default function MainLoading() {
  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <Skeleton active paragraph={{ rows: 1 }} />
      <Skeleton active paragraph={{ rows: 6 }} />
    </div>
  );
}
