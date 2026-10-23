// Pure, testable security and configuration rules for the desktop shell.

import { posix, win32 } from "node:path";

export type Mode = "easy" | "remote" | "local";

export interface DesktopConfig {
  mode: Mode;
  /** remote mode: the NexScout web address (http(s)). */
  remoteUrl?: string;
  /** local mode: path to a NexScout checkout (with backend/ and apps/web/). */
  checkoutDir?: string;
  /** local mode: ports for the local servers. */
  apiPort?: number;
  webPort?: number;
}

export const DEFAULT_LOCAL = { apiPort: 18800, webPort: 18900 } as const;
/** Easy mode: NexScout's own Docker stack (released images), shown on this port. */
export const DEFAULT_EASY_PORT = 18700;

/** Validate a config read from disk (never trust the file blindly). */
export function parseConfig(raw: unknown): DesktopConfig | null {
  if (typeof raw !== "object" || raw === null) return null;
  const c = raw as Record<string, unknown>;
  const port = (v: unknown, d: number) =>
    typeof v === "number" && Number.isInteger(v) && v >= 1024 && v <= 65535 ? v : d;
  if (c.mode === "easy") {
    return { mode: "easy", webPort: port(c.webPort, DEFAULT_EASY_PORT) };
  }
  if (c.mode === "remote") {
    if (typeof c.remoteUrl !== "string") return null;
    const url = safeHttpUrl(c.remoteUrl);
    return url ? { mode: "remote", remoteUrl: url } : null;
  }
  if (c.mode === "local") {
    if (typeof c.checkoutDir !== "string" || c.checkoutDir.trim() === "") return null;
    return {
      mode: "local",
      checkoutDir: c.checkoutDir,
      apiPort: port(c.apiPort, DEFAULT_LOCAL.apiPort),
      webPort: port(c.webPort, DEFAULT_LOCAL.webPort),
    };
  }
  return null;
}

/** http(s) only, no credentials in the URL; returns the normalized origin + path. */
export function safeHttpUrl(value: string): string | null {
  try {
    const u = new URL(value.trim());
    if (u.protocol !== "http:" && u.protocol !== "https:") return null;
    if (u.username || u.password) return null;
    // Plain http is only acceptable for this machine.
    if (u.protocol === "http:" && !isLoopback(u.hostname)) return null;
    return u.toString().replace(/\/$/, "");
  } catch {
    return null;
  }
}

export function isLoopback(host: string): boolean {
  return host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "::1";
}

/** Where the app window may navigate: only the NexScout origin itself. */
export function isAppNavigation(target: string, appUrl: string): boolean {
  try {
    return new URL(target).origin === new URL(appUrl).origin;
  } catch {
    return false;
  }
}

/** Links that leave the app open in the system browser, but only http(s) and mailto. */
export function isSafeExternal(target: string): boolean {
  try {
    const u = new URL(target);
    return u.protocol === "https:" || u.protocol === "http:" || u.protocol === "mailto:";
  } catch {
    return false;
  }
}

/** The page the window shows for a config. */
export function appUrl(config: DesktopConfig): string {
  if (config.mode === "remote") return config.remoteUrl as string;
  if (config.mode === "easy") return `http://127.0.0.1:${config.webPort ?? DEFAULT_EASY_PORT}`;
  return `http://127.0.0.1:${config.webPort ?? DEFAULT_LOCAL.webPort}`;
}

/** Where Docker usually lives when it isn't on PATH (Docker Desktop installs). */
export function dockerCandidates(
  platform: string,
  env: Record<string, string | undefined>,
): string[] {
  if (platform === "win32") {
    const win = (...parts: string[]) => parts.join(String.fromCharCode(92)); // "\"
    return [
      win(
        env.ProgramFiles ?? "C:\u005cProgram Files",
        "Docker",
        "Docker",
        "resources",
        "bin",
        "docker.exe",
      ),
      win(env.LOCALAPPDATA ?? "", "Programs", "DockerDesktop", "resources", "bin", "docker.exe"),
    ];
  }
  if (platform === "darwin") {
    return [
      "/usr/local/bin/docker",
      "/opt/homebrew/bin/docker",
      "/Applications/Docker.app/Contents/Resources/bin/docker",
    ];
  }
  return ["/usr/bin/docker", "/usr/local/bin/docker"];
}

/** Environment for `docker compose` in Easy mode. Secrets are passed in memory, never written. */
export function easyEnv(opts: {
  masterKey: string;
  dbPassword: string;
  port: number;
  version: string;
}): Record<string, string> {
  if (!/^[A-Za-z0-9+/=]{40,}$/.test(opts.masterKey)) throw new Error("invalid master key");
  if (!/^[A-Za-z0-9]{16,}$/.test(opts.dbPassword)) throw new Error("invalid database password");
  return {
    NEXSCOUT_MASTER_KEY: opts.masterKey,
    NEXSCOUT_PG_SUPERUSER_PASSWORD: opts.dbPassword,
    NEXSCOUT_PORT: String(opts.port),
    NEXSCOUT_PUBLIC_WEB_URL: `http://127.0.0.1:${opts.port}`,
    // Released apps use the matching images; a development build uses the newest release.
    NEXSCOUT_VERSION:
      /^\d+\.\d+\.\d+$/.test(opts.version) && opts.version !== "0.1.0" ? opts.version : "latest",
  };
}

// --- Updates and cleanup ---------------------------------------------------------------------

const NEXSCOUT_IMAGE = /^ghcr\.io\/[a-z0-9-]+\/nexscout-(backend|web)$/;

/**
 * NexScout images to remove after an update: every tag of our own images except the one now
 * in use. Lines are `repository:tag` from `docker images`. Other images are never touched.
 */
export function staleImages(lines: string[], keepTag: string): string[] {
  if (!/^\d+\.\d+\.\d+$/.test(keepTag)) return []; // a development build: leave them alone
  return lines
    .map((l) => l.trim())
    .filter((l) => {
      const i = l.lastIndexOf(":");
      if (i <= 0) return false;
      const repo = l.slice(0, i);
      const tag = l.slice(i + 1);
      return NEXSCOUT_IMAGE.test(repo) && tag !== keepTag && tag !== "<none>";
    });
}

/** Where electron-updater keeps downloaded installers (`<package name>-updater`). */
export function updaterCacheDir(
  platform: NodeJS.Platform,
  env: Record<string, string | undefined>,
  home: string,
): string | null {
  const name = "nexscout-desktop-updater"; // package.json "name" + "-updater"
  if (platform === "win32")
    return win32.join(env.LOCALAPPDATA ?? win32.join(home, "AppData", "Local"), name);
  if (platform === "darwin") return posix.join(home, "Library", "Caches", name);
  return posix.join(env.XDG_CACHE_HOME ?? posix.join(home, ".cache"), name);
}

const samePath = (a: string, b: string) =>
  a.trim().replace(/\\/g, "/").toLowerCase() === b.trim().replace(/\\/g, "/").toLowerCase();

/**
 * The desktop app's Easy mode and the Easy zip both run Compose project "nexscout-easy" (same
 * compose file, same volumes) but each has its own keys. Starting one over the other would
 * leave the stored keys unreadable. `configFiles` are the compose-file labels of the project's
 * existing containers; returns the other install's compose file if it is still there (a folder
 * that was moved or deleted no longer counts: its keys moved or went with it).
 */
export function foreignEasyStack(
  configFiles: string[],
  ours: string,
  exists: (path: string) => boolean,
): string | null {
  for (const label of configFiles) {
    for (const file of label.split(",")) {
      if (file.trim() && !samePath(file, ours) && exists(file.trim())) return file.trim();
    }
  }
  return null;
}

// --- Window, tray and the page's narrow bridge (ADR-0019) ------------------------------------

/** Desktop-only preferences, kept apart from the connection config. */
export interface DesktopPrefs {
  /** The window's close button hides NexScout to the tray (the default) instead of quitting. */
  closeToTray: boolean;
  /** The one-time "still running in the tray" notice was shown. */
  trayHintShown: boolean;
}

export const DEFAULT_PREFS: DesktopPrefs = { closeToTray: true, trayHintShown: false };

export function parsePrefs(raw: unknown): DesktopPrefs {
  if (typeof raw !== "object" || raw === null) return { ...DEFAULT_PREFS };
  const p = raw as Record<string, unknown>;
  return {
    closeToTray: typeof p.closeToTray === "boolean" ? p.closeToTray : DEFAULT_PREFS.closeToTray,
    trayHintShown: p.trayHintShown === true,
  };
}

/**
 * Bridge calls are answered only for the NexScout page itself: the sending frame's origin must
 * be the app's origin (not an embedded frame from elsewhere, not the setup page).
 */
export function isTrustedSender(frameUrl: string | undefined, appUrl: string | null): boolean {
  if (!frameUrl || !appUrl) return false;
  try {
    const from = new URL(frameUrl);
    return (
      (from.protocol === "http:" || from.protocol === "https:") &&
      from.origin === new URL(appUrl).origin
    );
  } catch {
    return false;
  }
}

/** The custom title bar is the page's 56 px top bar; the window controls sit on top of it. */
export const TITLE_BAR_HEIGHT = 56;

export type Theme = "light" | "dark";

export function titleBarColors(theme: unknown): { color: string; symbolColor: string } {
  // apps/web/src/app/globals.css --background / --foreground, as sRGB.
  return theme === "light"
    ? { color: "#fbfcfe", symbolColor: "#131521" }
    : { color: "#090b16", symbolColor: "#eef0f7" };
}

/** What the page is told about an update (no dialogs when the page asked). */
export type UpdateStatus =
  | { state: "unsupported" }
  | { state: "checking" }
  | { state: "none"; version: string }
  | { state: "downloading"; version?: string; percent: number }
  | { state: "ready"; version: string }
  | { state: "error"; message: string };

export function clampPercent(value: unknown): number {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return Math.max(0, Math.min(100, Math.round(n)));
}
