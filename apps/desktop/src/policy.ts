// Pure, testable security and configuration rules for the desktop shell.

export type Mode = "remote" | "local";

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

/** Validate a config read from disk (never trust the file blindly). */
export function parseConfig(raw: unknown): DesktopConfig | null {
  if (typeof raw !== "object" || raw === null) return null;
  const c = raw as Record<string, unknown>;
  if (c.mode === "remote") {
    if (typeof c.remoteUrl !== "string") return null;
    const url = safeHttpUrl(c.remoteUrl);
    return url ? { mode: "remote", remoteUrl: url } : null;
  }
  if (c.mode === "local") {
    if (typeof c.checkoutDir !== "string" || c.checkoutDir.trim() === "") return null;
    const port = (v: unknown, d: number) =>
      typeof v === "number" && Number.isInteger(v) && v >= 1024 && v <= 65535 ? v : d;
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
  return `http://127.0.0.1:${config.webPort ?? DEFAULT_LOCAL.webPort}`;
}
