"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

// 先这样顶一下——SSR的时候这些组件依赖window，直接不渲染等客户端挂载
export default function HydrationGuard({ children }: { children: ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;
  return <>{children}</>;
}
