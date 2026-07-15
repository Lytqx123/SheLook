import HydrationGuard from "@/components/HydrationGuard";
import FlywheelContent from "./FlywheelContent";

// 跳过构建时预渲染；HydrationGuard 确保运行时仅在客户端渲染
export const dynamic = "force-dynamic";

export default function FlywheelPage() {
  return (
    <HydrationGuard>
      <FlywheelContent />
    </HydrationGuard>
  );
}
