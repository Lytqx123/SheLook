import HydrationGuard from "@/components/HydrationGuard";
import ExperimentDetailContent from "./ExperimentDetailContent";

export const dynamic = "force-dynamic";

export default function ExperimentDetailPage() {
  return (
    <HydrationGuard>
      <ExperimentDetailContent />
    </HydrationGuard>
  );
}
