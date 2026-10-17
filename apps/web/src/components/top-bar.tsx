"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Logo } from "@/components/logo";
import { NotificationBell } from "@/components/notification-bell";
import { ThemeToggle } from "@/components/theme-toggle";
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
    <header className="sticky top-0 z-40 border-b bg-background/70 backdrop-blur-md">
      <div className="flex h-14 items-center justify-between gap-3 px-4">
        <Link href="/cases" aria-label="NexScout: your cases" className="rounded-lg">
          <Logo />
        </Link>
        <div className="flex items-center gap-1.5 text-sm sm:gap-2">
          {me.data && <NotificationBell />}
          <ThemeToggle />
          {me.data && (
            <span aria-label="Signed in as" className="hidden px-1 text-muted-foreground sm:inline">
              {me.data.display_name}
            </span>
          )}
          <Link href="/account" className="rounded-md px-2 py-1 hover:bg-muted">
            Account
          </Link>
          <Button variant="outline" size="sm" onClick={logout} disabled={pending}>
            <LogOut className="size-3.5" aria-hidden />
            Sign out
          </Button>
        </div>
      </div>
    </header>
  );
}
