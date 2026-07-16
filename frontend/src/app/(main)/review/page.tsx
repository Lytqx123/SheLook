import HydrationGuard from "@/components/HydrationGuard";
import ReviewContent from "./ReviewContent";

export const dynamic = "force-dynamic";

export default function ReviewPage() {
  return (
    <HydrationGuard>
      <ReviewContent />
    </HydrationGuard>
  );
}
