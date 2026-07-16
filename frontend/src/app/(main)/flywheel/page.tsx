import HydrationGuard from "@/components/HydrationGuard";
import FlywheelContent from "./FlywheelContent";

export const dynamic = "force-dynamic";

export default function FlywheelPage() {
  return (
    <HydrationGuard>
      <FlywheelContent />
    </HydrationGuard>
  );
}
