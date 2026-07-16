import HydrationGuard from "@/components/HydrationGuard";
import AuditLogsContent from "./AuditLogsContent";

export const dynamic = "force-dynamic";

export default function AuditLogsPage() {
  return (
    <HydrationGuard>
      <AuditLogsContent />
    </HydrationGuard>
  );
}
