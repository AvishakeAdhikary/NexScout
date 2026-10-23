"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { updatesApi } from "@/lib/api/client";

const DISMISS_KEY = "nexscout.update-dismissed";

function dismissedVersion(): string | null {
  try {
    return window.localStorage.getItem(DISMISS_KEY);
  } catch {
    return null; // private window or blocked storage: just show it
  }
}

function inDesktopApp(): boolean {
  return Boolean(
    (window as { nexscoutDesktop?: { isDesktop?: boolean } }).nexscoutDesktop?.isDesktop,
  );
}

const noSubscription = () => () => {};

/** "A newer NexScout is out." Hidden in the desktop app, which updates itself. */
export function UpdateBanner() {
  // Browser-only facts; the server render assumes "desktop" so nothing flashes.
  const desktop = useSyncExternalStore(noSubscription, inDesktopApp, () => true);
  const stored = useSyncExternalStore(noSubscription, dismissedVersion, () => null);
  const [dismissedNow, setDismissedNow] = useState<string | null>(null);
  const dismissed = dismissedNow ?? stored;
  const version = useQuery({
    queryKey: ["version"],
    queryFn: updatesApi.version,
    staleTime: 6 * 60 * 60 * 1000,
    retry: false,
    enabled: !desktop,
  });
  const v = version.data;
  if (desktop || !v?.update_available || !v.latest || dismissed === v.latest) return null;

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b bg-muted/60 px-4 py-2 text-sm"
    >
      <span>
        <strong>NexScout {v.latest}</strong> is available (you have {v.current}). Easy install:
        double-click <em>Update NexScout</em> in your NexScout folder.
      </span>
      {v.url && (
        <a className="underline" href={v.url} target="_blank" rel="noreferrer noopener">
          What&apos;s new
        </a>
      )}
      <Button
        size="sm"
        variant="ghost"
        onClick={() => {
          try {
            window.localStorage.setItem(DISMISS_KEY, v.latest ?? "");
          } catch {
            // can't remember: hide for now only
          }
          setDismissedNow(v.latest);
        }}
      >
        Dismiss
      </Button>
    </div>
  );
}
