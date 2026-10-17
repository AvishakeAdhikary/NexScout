import type { Metadata } from "next";
import { Suspense } from "react";

import { LogoMark } from "@/components/logo";

import { AuthForm } from "../auth-form";

export const metadata: Metadata = { title: "Create account" };

export default function RegisterPage() {
  return (
    <main id="main" className="relative flex flex-1 flex-col items-center justify-center gap-8 overflow-hidden p-6">
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/3 -z-10 size-[36rem] -translate-x-1/2 -translate-y-1/2 rounded-full bg-gradient-to-br from-indigo-500/25 via-violet-500/20 to-cyan-400/15 blur-3xl"
      />
      <div className="animate-page flex flex-col items-center gap-3 text-center">
        <LogoMark size={56} />
        <p className="font-heading text-3xl font-semibold tracking-tight">NexScout</p>
        <p className="max-w-sm text-sm text-muted-foreground">
          Truthful PhD and job applications, built from your own achievements.
        </p>
      </div>
      <Suspense fallback={<p>Loading…</p>}>
        <AuthForm mode="register" />
      </Suspense>
    </main>
  );
}
