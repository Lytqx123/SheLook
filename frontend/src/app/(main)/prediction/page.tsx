import HydrationGuard from "@/components/HydrationGuard";
import PredictionContent from "./PredictionContent";

export const dynamic = "force-dynamic";

export default function PredictionPage() {
  return (
    <HydrationGuard>
      <PredictionContent />
    </HydrationGuard>
  );
}
