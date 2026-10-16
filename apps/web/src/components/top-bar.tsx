"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { authApi } from "@/lib/api/client";
import { useMe } from "@/lib/hooks";

export function TopBar() {
  const me = useMe();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);

  async function logout() {
    setPending(true);
    try {
      await authApi.logout();
    } finally {
      queryClient.clear();
      router.replace("/login");
    }
  }

  return (
    <header className="flex items-center justify-between border-b px-4 py-2">
      <Link href="/cases" className="font-semibold tracking-tight">
        NexScout
      </Link>
      <div className="flex items-center gap-3 text-sm">
        {me.data && <span aria-label="Signed in as">{me.data.display_name}</span>}
        <Button variant="outline" size="sm" onClick={logout} disabled={pending}>
          Sign out
        </Button>
      </div>
    </header>
  );
}
