import HydrationGuard from "@/components/HydrationGuard";
import PublishContent from "./PublishContent";

// 跳过构建时预渲染；HydrationGuard 确保运行时仅在客户端渲染
export const dynamic = "force-dynamic";

export default function PublishPage() {
  return (
    <HydrationGuard>
      <PublishContent />
    </HydrationGuard>
  );
}
