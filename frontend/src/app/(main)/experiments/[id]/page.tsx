import HydrationGuard from "@/components/HydrationGuard";
import ExperimentDetailContent from "./ExperimentDetailContent";

// 跳过构建时预渲染；HydrationGuard 确保运行时仅在客户端渲染
export const dynamic = "force-dynamic";

export default function ExperimentDetailPage() {
  return (
    <HydrationGuard>
      <ExperimentDetailContent />
    </HydrationGuard>
  );
}
