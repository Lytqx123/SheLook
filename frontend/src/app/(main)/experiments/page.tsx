import HydrationGuard from "@/components/HydrationGuard";
import ExperimentsList from "./ExperimentsList";

export const dynamic = "force-dynamic"; // 客户端组件，跳过SSR

export default function ExperimentsPage() {
  return (
    <HydrationGuard>
      <ExperimentsList />
    </HydrationGuard>
  );
}
