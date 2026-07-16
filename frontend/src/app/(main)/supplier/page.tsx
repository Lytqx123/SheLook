import HydrationGuard from "@/components/HydrationGuard";
import SupplierContent from "./SupplierContent";

export const dynamic = "force-dynamic";

export default function SupplierPage() {
  return (
    <HydrationGuard>
      <SupplierContent />
    </HydrationGuard>
  );
}
