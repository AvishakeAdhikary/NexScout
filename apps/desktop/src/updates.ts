// In-app updates for the installed Windows app (electron-updater, GitHub Releases).
//
// - Checks at start and every 6 hours, plus "Check for updates" in the tray and in
//   Account → About & updates. A check the page asked for reports its progress to the page
//   (`onUpdateStatus`) instead of opening dialogs.
// - Downloads in the background and asks before restarting. If the person says "Later", the
//   update installs when NexScout closes.
// - After a version change, the downloaded installers are deleted (the updater cache).
// - The update source is the public GitHub release of this repository (electron-builder.yml
//   `publish`), fetched over https. The installers aren't code-signed yet (KNOWN_LIMITATIONS).

import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { app, dialog, shell, type BrowserWindow, type MessageBoxOptions } from "electron";
import { autoUpdater } from "electron-updater";

import { clampPercent, updaterCacheDir, type UpdateStatus } from "./policy";

const SIX_HOURS = 6 * 60 * 60 * 1000;
const RELEASES = "https://github.com/AvishakeAdhikary/NexScout/releases/latest";

let getWindow: () => BrowserWindow | null = () => null;
let manualCheck = false;
let pageCheck = false; // the page asked: report status, no dialogs
let wired = false;
let readyVersion: string | null = null;
let lastStatus: UpdateStatus = { state: "unsupported" };
const listeners = new Set<(s: UpdateStatus) => void>();

function emit(status: UpdateStatus): void {
  lastStatus = status;
  for (const listener of listeners) listener(status);
}

/** Status changes for the page (Account → About & updates). Returns an unsubscribe. */
export function onUpdateStatus(listener: (s: UpdateStatus) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function currentUpdateStatus(): UpdateStatus {
  return updatesSupported() ? lastStatus : { state: "unsupported" };
}

function log(level: string, message: unknown): void {
  try {
    const dir = join(app.getPath("userData"), "logs");
    mkdirSync(dir, { recursive: true });
    appendFileSync(
      join(dir, "updates.log"),
      `${new Date().toISOString()} ${level} ${String(message)}\n`,
    );
  } catch {
    // logging must never break the app
  }
}

async function ask(options: MessageBoxOptions): Promise<number> {
  const win = getWindow();
  const res = win
    ? await dialog.showMessageBox(win, options)
    : await dialog.showMessageBox(options);
  return res.response;
}

/** Only the installed Windows app can update itself (NSIS + latest.yml). */
export function updatesSupported(): boolean {
  return app.isPackaged && process.platform === "win32" && !process.argv.includes("--smoke");
}

/** Delete downloaded installers once a new version is running. */
function cleanUpAfterUpdate(): void {
  const marker = join(app.getPath("userData"), "last-version.txt");
  let previous: string | null = null;
  try {
    previous = readFileSync(marker, "utf-8").trim();
  } catch {
    // first start
  }
  const current = app.getVersion();
  if (previous === current) return;
  const cache = updaterCacheDir(process.platform, process.env, homedir());
  if (previous && cache && existsSync(cache)) {
    rmSync(join(cache, "pending"), { recursive: true, force: true });
    log("info", `updated ${previous} -> ${current}; removed downloaded installers`);
  }
  writeFileSync(marker, current, "utf-8");
}

function wire(): void {
  if (wired) return;
  wired = true;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.allowPrerelease = false;
  autoUpdater.allowDowngrade = false;
  autoUpdater.logger = {
    info: (m) => log("info", m),
    warn: (m) => log("warn", m),
    error: (m) => log("error", m),
    debug: () => undefined,
  };
  autoUpdater.on("checking-for-update", () => emit({ state: "checking" }));
  autoUpdater.on("download-progress", (p) =>
    emit({ state: "downloading", percent: clampPercent(p.percent) }),
  );
  autoUpdater.on("update-available", (info) => {
    emit({ state: "downloading", version: info.version, percent: 0 });
    if (pageCheck) return;
    if (!manualCheck) return;
    manualCheck = false;
    void ask({
      type: "info",
      title: "Update found",
      message: `NexScout ${info.version} is downloading.`,
      detail: "Keep working. You'll be asked to restart when it's ready.",
    });
  });
  autoUpdater.on("update-not-available", () => {
    emit({ state: "none", version: app.getVersion() });
    if (pageCheck) {
      pageCheck = false;
      return;
    }
    if (!manualCheck) return;
    manualCheck = false;
    void ask({
      type: "info",
      title: "No update",
      message: `You have the latest NexScout (${app.getVersion()}).`,
    });
  });
  autoUpdater.on("error", (err) => {
    log("error", err?.message ?? err);
    emit({
      state: "error",
      message: "NexScout couldn't reach GitHub to check for updates. Check that you're online.",
    });
    if (pageCheck) {
      pageCheck = false;
      return;
    }
    if (!manualCheck) return; // background checks fail quietly (offline, GitHub busy)
    manualCheck = false;
    void ask({
      type: "warning",
      title: "Couldn't check for updates",
      message: "NexScout couldn't reach GitHub to check for updates.",
      detail:
        "Check that you're online, then try again. You can also download the newest version yourself.",
      buttons: ["OK", "Open the download page"],
      defaultId: 0,
    }).then((r) => {
      if (r === 1) void shell.openExternal(RELEASES);
    });
  });
  autoUpdater.on("update-downloaded", (info) => {
    readyVersion = info.version;
    emit({ state: "ready", version: info.version });
    if (pageCheck) {
      pageCheck = false; // the page shows "Restart to update"
      return;
    }
    void ask({
      type: "info",
      title: "Update ready",
      message: `NexScout ${info.version} is ready to install.`,
      detail:
        "Restart now to update. Your data stays as it is. If you choose Later, the update installs when you close NexScout.",
      buttons: ["Restart now", "Later"],
      defaultId: 0,
      cancelId: 1,
    }).then((r) => {
      if (r === 0) setImmediate(() => autoUpdater.quitAndInstall());
    });
  });
}

function check(): void {
  autoUpdater.checkForUpdates().catch((err: unknown) => log("error", err));
}

/** Call once the main window exists. */
export function startUpdates(windowGetter: () => BrowserWindow | null): void {
  getWindow = windowGetter;
  if (!updatesSupported()) return;
  try {
    cleanUpAfterUpdate();
  } catch (err) {
    log("error", err);
  }
  wire();
  setTimeout(check, 10_000); // let the app start first
  setInterval(check, SIX_HOURS).unref();
}

/** The page's "Check for updates" button: progress goes to `onUpdateStatus`, no dialogs. */
export function checkFromPage(): UpdateStatus {
  if (!updatesSupported()) return { state: "unsupported" };
  wire();
  if (readyVersion) return { state: "ready", version: readyVersion };
  pageCheck = true;
  emit({ state: "checking" });
  check();
  return lastStatus;
}

/** Restart into a downloaded update ("Restart to update"). False when none is ready. */
export function installDownloadedUpdate(): boolean {
  if (!updatesSupported() || !readyVersion) return false;
  setImmediate(() => autoUpdater.quitAndInstall());
  return true;
}

/** "Check for updates" in the tray: answers with dialogs. */
export function checkForUpdatesNow(): void {
  if (!updatesSupported()) {
    void ask({
      type: "info",
      title: "Updates",
      message: "This copy of NexScout doesn't update itself.",
      detail:
        "The installed Windows app updates automatically. Otherwise download the newest version from GitHub.",
      buttons: ["OK", "Open the download page"],
      defaultId: 0,
    }).then((r) => {
      if (r === 1) void shell.openExternal(RELEASES);
    });
    return;
  }
  wire();
  manualCheck = true;
  check();
}
