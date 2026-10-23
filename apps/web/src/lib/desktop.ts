// The desktop app's narrow bridge (apps/desktop/src/preload.ts, ADR-0019). Absent in a browser:
// every caller must handle `desktopBridge() === null`.

export type UpdateStatus =
  | { state: "unsupported" }
  | { state: "checking" }
  | { state: "none"; version: string }
  | { state: "downloading"; version?: string; percent: number }
  | { state: "ready"; version: string }
  | { state: "error"; message: string };

export interface DesktopInfo {
  version: string;
  platform: string;
  mode: "easy" | "remote" | "local" | null;
  closeToTray: boolean;
  updatesSupported: boolean;
  update: UpdateStatus;
}

export interface DesktopBridge {
  isDesktop: true;
  platform: string;
  info(): Promise<DesktopInfo>;
  checkForUpdates(): Promise<UpdateStatus>;
  installUpdate(): Promise<boolean>;
  setCloseToTray(on: boolean): Promise<boolean>;
  stopBackground(): Promise<boolean>;
  openLogs(): Promise<boolean>;
  setTheme(theme: "light" | "dark"): Promise<boolean>;
  onUpdateStatus(callback: (status: UpdateStatus) => void): () => void;
}

export function desktopBridge(): DesktopBridge | null {
  if (typeof window === "undefined") return null;
  const bridge = (window as { nexscoutDesktop?: Partial<DesktopBridge> }).nexscoutDesktop;
  // An older desktop app exposes only { isDesktop, platform }: treat it as "no bridge".
  return bridge?.isDesktop && typeof bridge.info === "function" ? (bridge as DesktopBridge) : null;
}

/** Inside the desktop app at all (even an older one without the bridge). */
export function inDesktopApp(): boolean {
  return (
    typeof window !== "undefined" &&
    Boolean((window as { nexscoutDesktop?: { isDesktop?: boolean } }).nexscoutDesktop?.isDesktop)
  );
}
