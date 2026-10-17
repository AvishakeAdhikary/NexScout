import { Suspense } from "react";

import { TopBar } from "@/components/top-bar";

export default function ApproveLayout({ children }: LayoutProps<"/approve">) {
  return (
    <div className="flex min-h-screen flex-col">
      <Suspense fallback={<header className="h-11 border-b" />}>
        <TopBar />
      </Suspense>
      <Suspense fallback={<p className="p-6">Loading…</p>}>{children}</Suspense>
    </div>
  );
}
