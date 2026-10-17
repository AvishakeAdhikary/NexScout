import { Suspense } from "react";

import { CaseNav } from "./case-nav";

// Route params and session-backed data are runtime values, so they stream in behind
// Suspense boundaries while the static shell prerenders (Cache Components).
export default function CaseLayout({ children }: LayoutProps<"/cases/[caseId]">) {
  return (
    <div className="flex flex-1 flex-col md:flex-row">
      <aside className="border-b bg-sidebar/60 p-3 md:sticky md:top-14 md:h-[calc(100vh-3.5rem)] md:w-60 md:shrink-0 md:overflow-y-auto md:border-b-0 md:border-r">
        <Suspense fallback={<p className="px-2 text-sm text-muted-foreground">Loading…</p>}>
          <CaseNav />
        </Suspense>
      </aside>
      <main id="main" className="min-w-0 flex-1 p-6 lg:p-8">
        <Suspense fallback={<p className="text-muted-foreground">Loading…</p>}>
          {children}
        </Suspense>
      </main>
    </div>
  );
}
