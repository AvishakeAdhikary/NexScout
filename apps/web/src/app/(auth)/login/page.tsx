import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "../auth-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main id="main" className="flex flex-1 items-center justify-center p-6">
      <Suspense fallback={<p>Loading…</p>}>
        <AuthForm mode="login" />
      </Suspense>
    </main>
  );
}
