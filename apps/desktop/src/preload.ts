// App window preload: a narrow bridge for the NexScout page (ADR-0019). No Node, no generic
// IPC: each call below maps to one handler in main.ts, which also checks that the caller is
// the NexScout page itself (policy.isTrustedSender). Arguments are checked here and there.
import { contextBridge, ipcRenderer, type IpcRendererEvent } from "electron";

type Status = Record<string, unknown>;

contextBridge.exposeInMainWorld("nexscoutDesktop", {
  isDesktop: true,
  platform: process.platform,
  info: (): Promise<unknown> => ipcRenderer.invoke("desktop:info"),
  checkForUpdates: (): Promise<unknown> => ipcRenderer.invoke("desktop:check-updates"),
  installUpdate: (): Promise<unknown> => ipcRenderer.invoke("desktop:install-update"),
  setCloseToTray: (on: unknown): Promise<unknown> =>
    ipcRenderer.invoke("desktop:set-close-to-tray", on === true),
  stopBackground: (): Promise<unknown> => ipcRenderer.invoke("desktop:stop-background"),
  openLogs: (): Promise<unknown> => ipcRenderer.invoke("desktop:open-logs"),
  setTheme: (theme: unknown): Promise<unknown> =>
    ipcRenderer.invoke("desktop:set-theme", theme === "light" ? "light" : "dark"),
  /** Update progress; returns a function that stops listening. */
  onUpdateStatus: (callback: unknown): (() => void) => {
    if (typeof callback !== "function") return () => undefined;
    const listener = (_event: IpcRendererEvent, status: Status) =>
      (callback as (s: Status) => void)(status);
    ipcRenderer.on("desktop:update-status", listener);
    return () => ipcRenderer.removeListener("desktop:update-status", listener);
  },
});
