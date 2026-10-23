"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { updatesApi } from "@/lib/api/client";
import { desktopBridge, type DesktopInfo, type UpdateStatus } from "@/lib/desktop";

const noSubscription = () => () => {};

function describe(status: UpdateStatus | null): string | null {
  switch (status?.state) {
    case "checking":
      return "Checking for updates…";
    case "none":
      return `You have the latest NexScout (${status.version}).`;
    case "downloading":
      return `Downloading ${status.version ? `NexScout ${status.version}` : "the update"}… ${status.percent}%`;
    case "ready":
      return `NexScout ${status.version} is ready. Restart to update; your data stays as it is.`;
    case "error":
      return status.message;
    default:
      return null;
  }
}

/** Account → About & updates. In the desktop app: version, update check with live status,
 *  "Restart to update", the tray setting, logs. In a browser: this server's version. */
export function AboutUpdates() {
  const hasBridge = useSyncExternalStore(
    noSubscription,
    () => desktopBridge() !== null,
    () => false,
  );
  return (
    <section aria-labelledby="about-heading" className="flex flex-col gap-3">
      <h2 id="about-heading" className="text-lg font-semibold">
        About & updates
      </h2>
      {hasBridge ? <DesktopAbout /> : <BrowserAbout />}
    </section>
  );
}

function BrowserAbout() {
  const version = useQuery({ queryKey: ["version"], queryFn: updatesApi.version, retry: false });
  const v = version.data;
  if (!v) return <p className="text-sm text-muted-foreground">Loading…</p>;
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p>
        NexScout <span className="font-medium">{v.current}</span>
        {v.update_available && v.latest ? (
          <>
            {" "}
            · <span className="font-medium">{v.latest}</span> is available.{" "}
            {v.url && (
              <a className="underline" href={v.url} target="_blank" rel="noopener noreferrer">
                What&apos;s new and how to update
              </a>
            )}
          </>
        ) : v.latest ? (
          " · up to date"
        ) : (
          ""
        )}
      </p>
      {v.checked_at && (
        <p className="text-xs text-muted-foreground">
          Last checked {new Date(v.checked_at).toLocaleString()}.
        </p>
      )}
    </div>
  );
}

function DesktopAbout() {
  const [bridge] = useState(desktopBridge); // read once: the same bridge for every render
  const [info, setInfo] = useState<DesktopInfo | null>(null);
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    if (!bridge) return;
    let live = true;
    bridge
      .info()
      .then((i) => {
        if (!live) return;
        setInfo(i);
        setStatus(i.update.state === "unsupported" ? null : i.update);
      })
      .catch(() => setProblem("The desktop app didn't answer. Restart NexScout and try again."));
    const stop = bridge.onUpdateStatus(setStatus);
    return () => {
      live = false;
      stop();
    };
  }, [bridge]);
  if (!bridge) return null;
  if (!info) return <p className="text-sm text-muted-foreground">{problem ?? "Loading…"}</p>;

  const busy = status?.state === "checking" || status?.state === "downloading";
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p>
        NexScout desktop <span className="font-medium">{info.version}</span>
        {info.mode === "easy" ? " · Easy mode (runs on this computer)" : ""}
        {info.mode === "remote" ? " · connected to a NexScout server" : ""}
        {info.mode === "local" ? " · developer mode" : ""}
      </p>
      {info.updatesSupported ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => void bridge.checkForUpdates().then(setStatus)}
            >
              Check for updates
            </Button>
            {status?.state === "ready" && (
              <Button size="sm" onClick={() => void bridge.installUpdate()}>
                Restart to update
              </Button>
            )}
          </div>
          <p role="status" aria-live="polite">
            {describe(status) ?? "NexScout checks for updates by itself every few hours."}
          </p>
        </div>
      ) : (
        <p className="text-muted-foreground">
          This copy of NexScout doesn&apos;t update itself (the installed Windows app does).
        </p>
      )}
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={info.closeToTray}
          onChange={(e) =>
            void bridge
              .setCloseToTray(e.target.checked)
              .then((closeToTray) => setInfo({ ...info, closeToTray }))
          }
        />
        Keep running in the tray when I close the window
      </label>
      <p className="text-xs text-muted-foreground">
        NexScout keeps searching and reminding you while its window is closed. Open it again, or
        quit it, from its icon in the tray.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="ghost" onClick={() => void bridge.openLogs()}>
          Open the log folder
        </Button>
        {info.mode === "easy" && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              if (
                window.confirm(
                  "Stop NexScout completely? Searches, reminders and the autopilot pause until you open it again.",
                )
              )
                void bridge.stopBackground();
            }}
          >
            Stop background work and quit
          </Button>
        )}
      </div>
    </div>
  );
}
