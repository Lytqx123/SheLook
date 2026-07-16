import HydrationGuard from "@/components/HydrationGuard";
import FairnessContent from "./FairnessContent";

export const dynamic = "force-dynamic";

export default function FairnessPage() {
  return (
    <HydrationGuard>
      <FairnessContent />
    </HydrationGuard>
  );
}
