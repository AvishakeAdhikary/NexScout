"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { trackingApi, type NotificationsOut } from "@/lib/api/client";

type Note = NotificationsOut["items"][number];

/** In-app notifications (deadlines, approvals, applications that need you). Never emailed. */
export function NotificationBell() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const notes = useQuery({
    queryKey: ["notifications"],
    queryFn: () => trackingApi.notifications(),
    refetchInterval: 30_000,
  });
  // Older ones, loaded on request ("Show older"), below the newest 50.
  const [older, setOlder] = useState<Note[]>([]);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["notifications"] });
  const read = useMutation({ mutationFn: trackingApi.read, onSuccess: invalidate });
  const readAll = useMutation({ mutationFn: trackingApi.readAll, onSuccess: invalidate });
  const remove = useMutation({
    mutationFn: trackingApi.removeNotification,
    onSuccess: (_r, id) => {
      setOlder((o) => o.filter((n) => n.id !== id));
      void invalidate();
    },
  });
  const clear = useMutation({
    mutationFn: trackingApi.clearNotifications,
    onSuccess: (_r, readOnly) => {
      setOlder((o) => (readOnly ? o.filter((n) => !n.read) : []));
      void invalidate();
    },
  });
  const items = [...(notes.data?.items ?? []), ...older];
  const loadOlder = useMutation({
    mutationFn: () => trackingApi.notifications(items.at(-1)?.created_at),
    onSuccess: (page) => setOlder((o) => [...o, ...page.items]),
  });
  const canLoadOlder = items.length >= 50 && loadOlder.data?.items.length !== 0;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onClick = (e: MouseEvent) => {
      if (panel.current && !panel.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const unread = notes.data?.unread ?? 0;
  return (
    <div className="relative" ref={panel}>
      <Button
        variant="ghost"
        size="sm"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((o) => !o)}
        className="relative"
      >
        <Bell className="size-4" aria-hidden />
        <span className="sr-only">Notifications{unread > 0 ? ` (${unread})` : ""}</span>
        {unread > 0 && (
          <span
            aria-hidden
            key={unread}
            className="animate-pop absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 font-mono text-[10px] font-semibold text-primary-foreground"
          >
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </Button>
      {open && (
        <div
          role="region"
          aria-label="Notifications"
          className="animate-in fade-in-0 zoom-in-95 slide-in-from-top-1 absolute right-0 z-50 mt-2 w-80 rounded-xl border bg-popover p-2 text-popover-foreground shadow-2xl duration-150"
        >
          <div className="mb-1 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <span className="text-sm font-medium">Notifications</span>
            <span className="flex gap-3">
              {unread > 0 && (
                <button
                  type="button"
                  className="text-xs underline"
                  onClick={() => readAll.mutate()}
                >
                  Mark all read
                </button>
              )}
              {items.some((n) => n.read) && (
                <button
                  type="button"
                  className="text-xs underline"
                  disabled={clear.isPending}
                  onClick={() => clear.mutate(true)}
                >
                  Clear read
                </button>
              )}
              {items.length > 0 && (
                <button
                  type="button"
                  className="text-xs underline"
                  disabled={clear.isPending}
                  onClick={() => {
                    if (window.confirm("Clear all notifications? Unread ones too."))
                      clear.mutate(false);
                  }}
                >
                  Clear all
                </button>
              )}
            </span>
          </div>
          {notes.data && items.length === 0 && (
            <p className="p-2 text-sm text-muted-foreground">Nothing yet.</p>
          )}
          <ul className="max-h-96 overflow-y-auto">
            {items.map((n) => (
              <li key={n.id} className="group flex items-start gap-1">
                <button
                  type="button"
                  className={`min-w-0 flex-1 rounded p-2 text-left text-sm hover:bg-muted ${n.read ? "text-muted-foreground" : "font-medium"}`}
                  onClick={() => {
                    if (!n.read) read.mutate(n.id);
                    setOpen(false);
                    if (n.link) router.push(n.link);
                  }}
                >
                  <span id={`note-title-${n.id}`}>{n.title}</span>
                  {n.body && <span className="block text-xs font-normal">{n.body}</span>}
                  <span className="block text-xs font-normal text-muted-foreground">
                    {new Date(n.created_at).toLocaleString()}
                  </span>
                </button>
                <button
                  type="button"
                  aria-label="Remove notification"
                  aria-describedby={`note-title-${n.id}`}
                  className="mt-1 rounded p-1 text-muted-foreground opacity-60 hover:bg-muted hover:opacity-100 focus-visible:opacity-100"
                  onClick={() => remove.mutate(n.id)}
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              </li>
            ))}
            {canLoadOlder && (
              <li>
                <button
                  type="button"
                  className="w-full p-2 text-center text-xs underline"
                  disabled={loadOlder.isPending}
                  onClick={() => loadOlder.mutate()}
                >
                  {loadOlder.isPending ? "Loading…" : "Show older"}
                </button>
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}
