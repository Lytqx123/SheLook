import HydrationGuard from "@/components/HydrationGuard";
import ImageDetailContent from "./ImageDetailContent";

export const dynamic = "force-dynamic";

export default function ImageDetailPage() {
  return (
    <HydrationGuard>
      <ImageDetailContent />
    </HydrationGuard>
  );
}
