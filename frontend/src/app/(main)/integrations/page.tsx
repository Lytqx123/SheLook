import HydrationGuard from "@/components/HydrationGuard";
import IntegrationsContent from "./IntegrationsContent";

export const dynamic = "force-dynamic";

export default function IntegrationsPage() {
  return (
    <HydrationGuard>
      <IntegrationsContent />
    </HydrationGuard>
  );
}
