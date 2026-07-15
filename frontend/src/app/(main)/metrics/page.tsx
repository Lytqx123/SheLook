import HydrationGuard from "@/components/HydrationGuard";
import MetricsContent from "./MetricsContent";

export const dynamic = "force-dynamic";

export default function MetricsPage() {
  return (
    <HydrationGuard>
      <MetricsContent />
    </HydrationGuard>
  );
}
