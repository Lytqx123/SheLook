import HydrationGuard from "@/components/HydrationGuard";
import ProviderConfigsContent from "./ProviderConfigsContent";

export const dynamic = "force-dynamic";

export default function ProviderConfigsPage() {
  return (
    <HydrationGuard>
      <ProviderConfigsContent />
    </HydrationGuard>
  );
}
