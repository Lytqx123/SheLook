import HydrationGuard from "@/components/HydrationGuard";
import ProductsContent from "./ProductsContent";

export const dynamic = "force-dynamic";

export default function ProductsPage() {
  return (
    <HydrationGuard>
      <ProductsContent />
    </HydrationGuard>
  );
}
