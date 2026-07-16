import HydrationGuard from "@/components/HydrationGuard";
import PublishContent from "./PublishContent";

export const dynamic = "force-dynamic";

export default function PublishPage() {
  return (
    <HydrationGuard>
      <PublishContent />
    </HydrationGuard>
  );
}
