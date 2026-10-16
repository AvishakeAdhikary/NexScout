import { Suspense } from "react";

import { TopBar } from "@/components/top-bar";

export default function AccountLayout({ children }: LayoutProps<"/account">) {
  return (
    <div className="flex min-h-screen flex-col">
      <Suspense fallback={<header className="h-11 border-b" />}>
        <TopBar />
      </Suspense>
      {children}
    </div>
  );
}
