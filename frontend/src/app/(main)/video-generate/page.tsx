import HydrationGuard from "@/components/HydrationGuard";
import VideoGenerateContent from "./VideoGenerateContent";

export const dynamic = "force-dynamic";

export default function VideoGeneratePage() {
  return (
    <HydrationGuard>
      <VideoGenerateContent />
    </HydrationGuard>
  );
}
