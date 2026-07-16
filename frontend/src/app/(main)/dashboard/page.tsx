import HydrationGuard from "@/components/HydrationGuard";
import DashboardContent from "./DashboardContent";

export const dynamic = "force-dynamic";

export default function DashboardPage() {
  return (
    <HydrationGuard>
      <DashboardContent />
    </HydrationGuard>
  );
}
