"use client";

import { useQueryClient } from "@tanstack/react-query";
import { House, LogOut } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState, useSyncExternalStore } from "react";

import { Logo } from "@/components/logo";
import { NotificationBell } from "@/components/notification-bell";
import { ThemeToggle } from "@/components/theme-toggle";
import { UpdateBanner } from "@/components/update-banner";
import { Button } from "@/components/ui/button";
import { authApi } from "@/lib/api/client";
import { desktopBridge, inDesktopApp } from "@/lib/desktop";
import { useMe } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const noSubscription = () => () => {};
const desktopPlatform = () =>
  inDesktopApp()
    ? ((window as { nexscoutDesktop?: { platform?: string } }).nexscoutDesktop?.platform ?? "")
    : null;

export function TopBar() {
  const me = useMe();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  // In the desktop app this bar is the window's title bar (null in a browser and on the server).
  const platform = useSyncExternalStore(noSubscription, desktopPlatform, () => null);
  const { resolvedTheme } = useTheme();
  useEffect(() => {
    // The window controls drawn over this bar follow the theme.
    if (resolvedTheme === "light" || resolvedTheme === "dark") {
      void desktopBridge()?.setTheme(resolvedTheme);
    }
  }, [resolvedTheme]);

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
      <div
        className={cn(
          "flex h-14 items-center justify-between gap-3 px-4",
          platform !== null && "desktop-titlebar",
          platform === "darwin" && "desktop-mac",
        )}
      >
        <div className="flex items-center gap-1">
          <Link href="/cases" aria-label="NexScout: your cases" className="rounded-lg">
            <Logo />
          </Link>
          {me.data && (
            <Link
              href="/cases"
              className="ml-1 flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <House className="size-3.5" aria-hidden />
              Home
            </Link>
          )}
        </div>
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
      {me.data && <UpdateBanner />}
    </header>
  );
}
