import HydrationGuard from "@/components/HydrationGuard";
import ClusteringContent from "./ClusteringContent";

export const dynamic = "force-dynamic";

export default function ClusteringPage() {
  return (
    <HydrationGuard>
      <ClusteringContent />
    </HydrationGuard>
  );
}
