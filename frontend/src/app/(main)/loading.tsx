import { Skeleton } from "antd";

/** 主工作区的通用路由加载骨架；复杂页面可继续用自己的 loading.tsx 覆盖。 */
export default function MainLoading() {
  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <Skeleton active paragraph={{ rows: 1 }} />
      <Skeleton active paragraph={{ rows: 6 }} />
    </div>
  );
}
