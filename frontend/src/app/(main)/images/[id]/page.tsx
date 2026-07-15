import HydrationGuard from "@/components/HydrationGuard";
import ImageDetailContent from "./ImageDetailContent";

// 跳过构建时预渲染；HydrationGuard 确保运行时仅在客户端渲染
export const dynamic = "force-dynamic";

export default function ImageDetailPage() {
  return (
    <HydrationGuard>
      <ImageDetailContent />
    </HydrationGuard>
  );
}
