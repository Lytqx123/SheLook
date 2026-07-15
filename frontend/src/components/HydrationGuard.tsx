"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

/**
 * 水合守卫 —— 在客户端 mount 完成前返回 null，避免 SSR 时渲染依赖 window 的组件
 *
 * 用法：
 *   // page.tsx (Server Component)
 *   export const dynamic = "force-dynamic";
 *   import HydrationGuard from "@/components/HydrationGuard";
 *   import Content from "./Content";
 *   export default function Page() {
 *     return <HydrationGuard><Content /></HydrationGuard>;
 *   }
 */
export default function HydrationGuard({ children }: { children: ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;
  return <>{children}</>;
}
