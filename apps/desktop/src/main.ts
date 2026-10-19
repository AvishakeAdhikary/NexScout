// NexScout desktop shell (Electron main process).
//
// Security posture (spec §15, AGENTS.md):
// - Renderer: contextIsolation, sandbox, no nodeIntegration, no <webview>; minimal preloads.
// - The window may only navigate within the NexScout origin; other links open in the system
//   browser (http/https/mailto only). Pop-ups and device permissions are refused.
// - Local mode keeps the encryption master key in the OS keychain via safeStorage and passes it
//   to the backend through the environment (never on the command line, never in a file in clear).

import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import { createWriteStream, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { app, BrowserWindow, dialog, ipcMain, Menu, safeStorage, session, shell } from "electron";

import {
  appUrl,
  DEFAULT_EASY_PORT,
  dockerCandidates,
  easyEnv,
  isAppNavigation,
  isSafeExternal,
  parseConfig,
  foreignEasyStack,
  staleImages,
  type DesktopConfig,
} from "./policy";
import { checkForUpdatesNow, startUpdates } from "./updates";

const SMOKE = process.argv.includes("--smoke");
const children: ChildProcess[] = [];
let mainWindow: BrowserWindow | null = null;

const configPath = () => join(app.getPath("userData"), "config.json");
const keyPath = () => join(app.getPath("userData"), "master.key.enc");

function loadConfig(): DesktopConfig | null {
  try {
    return parseConfig(JSON.parse(readFileSync(configPath(), "utf-8")));
  } catch {
    return null;
  }
}

function saveConfig(config: DesktopConfig): void {
  mkdirSync(app.getPath("userData"), { recursive: true });
  writeFileSync(configPath(), JSON.stringify(config, null, 2), { encoding: "utf-8", mode: 0o600 });
}

/** A 32-byte master key, generated once and stored encrypted by the OS (safeStorage). */
function masterKey(): string {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error("The operating system's secure storage isn't available.");
  }
  if (existsSync(keyPath())) {
    return safeStorage.decryptString(readFileSync(keyPath()));
  }
  const key = randomBytes(32).toString("base64");
  writeFileSync(keyPath(), safeStorage.encryptString(key), { mode: 0o600 });
  return key;
}

function secureWindow(preload: string): BrowserWindow {
  return new BrowserWindow({
    width: 1360,
    height: 880,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: "#121224",
    title: "NexScout",
    icon: join(__dirname, "..", "assets", "icon.png"),
    show: !SMOKE,
    webPreferences: {
      preload,
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webviewTag: false,
      spellcheck: true,
    },
  });
}

function guard(win: BrowserWindow, allowedUrl: string | null): void {
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isSafeExternal(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
  win.webContents.on("will-navigate", (event, url) => {
    if (allowedUrl && isAppNavigation(url, allowedUrl)) return;
    event.preventDefault();
    if (isSafeExternal(url)) void shell.openExternal(url);
  });
}

function killTree(child: ChildProcess): void {
  if (child.pid === undefined || child.exitCode !== null) return;
  if (process.platform === "win32") {
    spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true });
  } else {
    child.kill("SIGTERM");
  }
}

function logFile(name: string): string {
  return join(app.getPath("userData"), "logs", `${name}.log`);
}

/** Wait until a server's log shows a line (e.g. the worker's "worker_started"). */
async function waitForLog(name: string, marker: string, since: number, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if (readFileSync(logFile(name), "utf-8").slice(since).includes(marker)) return true;
    } catch {
      // not created yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

function logSize(name: string): number {
  try {
    return readFileSync(logFile(name), "utf-8").length;
  } catch {
    return 0;
  }
}

function startLocal(config: DesktopConfig): void {
  const dir = config.checkoutDir as string;
  const env = {
    ...process.env,
    NEXSCOUT_MASTER_KEY: masterKey(),
    NEXSCOUT_API_ORIGIN: `http://127.0.0.1:${config.apiPort}`,
    PYTHONUNBUFFERED: "1", // logs reach the log files immediately
    // The worker runs on this computer, so CAPTCHA/sign-in pages can open in a visible window
    // (assisted mode: the person solves and submits; NexScout only records the confirmation).
    NEXSCOUT_ASSISTED_BROWSER: "true",
    NEXSCOUT_ENV: "production", // a real install: no demo data, no API docs
    NEXSCOUT_PUBLIC_WEB_URL: `http://127.0.0.1:${config.webPort ?? 3000}`,
    ELECTRON_RUN_AS_NODE: undefined,
  };
  const logs = join(app.getPath("userData"), "logs");
  mkdirSync(logs, { recursive: true });
  const run = (name: string, cmd: string, args: string[], cwd: string) => {
    // Each server logs to userData/logs/<name>.log so problems can be diagnosed later.
    const out = createWriteStream(logFile(name), { flags: "a" });
    out.write(`\n--- ${new Date().toISOString()} starting ${name}\n`);
    const child = spawn(cmd, args, { cwd, env, windowsHide: true, shell: process.platform === "win32" });
    child.stdout?.pipe(out, { end: false });
    child.stderr?.pipe(out, { end: false });
    child.on("exit", (code) => out.write(`--- ${name} exited with ${code}\n`));
    children.push(child);
  };
  const backend = join(dir, "backend");
  run("api", "uv", ["run", "nexscout", "serve", "--port", String(config.apiPort)], backend);
  run("worker", "uv", ["run", "nexscout", "worker"], backend);
  run("web", "npx", ["next", "start", "-p", String(config.webPort), "-H", "127.0.0.1"],
    join(dir, "apps", "web"));
}

// --- Easy mode: NexScout's own Docker stack -------------------------------------------------

/** A database password, generated once and stored encrypted by the OS (safeStorage). */
function dbPassword(): string {
  const file = join(app.getPath("userData"), "db.password.enc");
  if (existsSync(file)) return safeStorage.decryptString(readFileSync(file));
  const value = randomBytes(24).toString("hex");
  writeFileSync(file, safeStorage.encryptString(value), { mode: 0o600 });
  return value;
}

function findDocker(): string | null {
  const onPath = spawnSync("docker", ["--version"], { windowsHide: true });
  if (onPath.status === 0) return "docker";
  return dockerCandidates(process.platform, process.env).find((p) => existsSync(p)) ?? null;
}

function dockerRunning(docker: string): boolean {
  return spawnSync(docker, ["info"], { windowsHide: true, timeout: 20_000 }).status === 0;
}

async function ensureDocker(): Promise<string | null> {
  const docker = findDocker();
  if (!docker) return null;
  if (dockerRunning(docker)) return docker;
  // Try to start Docker Desktop, then wait for it.
  if (process.platform === "win32") {
    const exe = [
      join(process.env.ProgramFiles ?? "C:/Program Files", "Docker", "Docker", "Docker Desktop.exe"),
      join(process.env.LOCALAPPDATA ?? "", "Programs", "DockerDesktop", "Docker Desktop.exe"),
    ].find((p) => existsSync(p));
    if (exe) spawn(exe, [], { detached: true, stdio: "ignore" }).unref();
  } else if (process.platform === "darwin") {
    spawn("open", ["-a", "Docker"], { detached: true, stdio: "ignore" }).unref();
  }
  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    if (dockerRunning(docker)) return docker;
    await new Promise((r) => setTimeout(r, 3000));
  }
  return null;
}

/** The bundled compose file (packaged: resources/easy; development: the repo's easy/). */
function easyCompose(): string {
  const packaged = join(process.resourcesPath, "easy", "docker-compose.yml");
  return existsSync(packaged) ? packaged : join(__dirname, "..", "..", "..", "easy", "docker-compose.yml");
}

function compose(docker: string, args: string[], env: Record<string, string>, log: string): Promise<number> {
  return new Promise((resolve) => {
    const out = createWriteStream(logFile(log), { flags: "a" });
    out.write(`\n--- ${new Date().toISOString()} docker compose ${args.join(" ")}\n`);
    const child = spawn(docker, ["compose", "-p", "nexscout-easy", "-f", easyCompose(), ...args], {
      env: { ...process.env, ...env, ELECTRON_RUN_AS_NODE: undefined },
      windowsHide: true,
    });
    child.stdout?.pipe(out, { end: false });
    child.stderr?.pipe(out, { end: false });
    child.on("error", () => resolve(-1));
    child.on("exit", (code) => {
      out.write(`--- exited with ${code}\n`);
      resolve(code ?? -1);
    });
  });
}

function easyEnvironment(config: DesktopConfig): Record<string, string> {
  return easyEnv({
    masterKey: masterKey(),
    dbPassword: dbPassword(),
    port: config.webPort ?? DEFAULT_EASY_PORT,
    version: app.getVersion(),
  });
}

/** Start (or update) the stack. Containers keep running when the window closes, so the
 *  autopilot and reminders keep working; "Stop NexScout" in the menu stops them. */
async function startEasy(config: DesktopConfig): Promise<string | null> {
  const docker = await ensureDocker();
  if (!docker) {
    void shell.openExternal("https://www.docker.com/products/docker-desktop/");
    return "NexScout's Easy mode runs inside Docker Desktop, which isn't installed or didn't start. The download page is open: install it, start it once, then open NexScout again.";
  }
  mkdirSync(join(app.getPath("userData"), "logs"), { recursive: true });
  const listed = spawnSync(
    docker,
    ["ps", "-a", "--filter", "label=com.docker.compose.project=nexscout-easy",
      "--format", '{{.Label "com.docker.compose.project.config_files"}}'],
    { windowsHide: true, encoding: "utf-8", timeout: 30_000 },
  );
  const other = foreignEasyStack(
    listed.status === 0 ? listed.stdout.split(/\r?\n/) : [],
    easyCompose(),
    existsSync,
  );
  if (other) {
    return `Another NexScout is already set up on this computer (${other}), with its own keys. Use that one, or stop and remove it first (in its folder: docker compose down). Your data in it is kept.`;
  }
  const env = easyEnvironment(config);
  await compose(docker, ["pull"], env, "easy");
  const code = await compose(docker, ["up", "-d", "--remove-orphans"], env, "easy");
  if (code !== 0) {
    return `NexScout's containers didn't start (code ${code}). Check that you're online. Log: ${logFile("easy")}`;
  }
  removeOldImages(docker, env.NEXSCOUT_VERSION ?? "latest");
  return null;
}

/** After an update, delete the previous versions' NexScout images (and dangling layers). */
function removeOldImages(docker: string, keepTag: string): void {
  if (!app.isPackaged) return;
  const listed = spawnSync(
    docker,
    ["images", "--filter", "reference=ghcr.io/*/nexscout-*", "--format", "{{.Repository}}:{{.Tag}}"],
    { windowsHide: true, encoding: "utf-8", timeout: 30_000 },
  );
  if (listed.status !== 0) return;
  const old = staleImages(listed.stdout.split(/\r?\n/), keepTag);
  const out = createWriteStream(logFile("easy"), { flags: "a" });
  for (const ref of old) {
    // Fails harmlessly for an image a container still uses.
    const r = spawnSync(docker, ["rmi", ref], { windowsHide: true, timeout: 60_000 });
    out.write(`--- removed old image ${ref}: ${r.status === 0 ? "ok" : "kept (in use)"}\n`);
  }
  if (old.length) spawnSync(docker, ["image", "prune", "-f"], { windowsHide: true, timeout: 120_000 });
  out.end();
}

async function stopEasy(): Promise<void> {
  const config = loadConfig();
  const docker = findDocker();
  if (!config || config.mode !== "easy" || !docker) return;
  await compose(docker, ["stop"], easyEnvironment(config), "easy");
}

async function waitFor(url: string, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { redirect: "manual" });
      if (res.status < 400) return true; // readyz answers 503 until DB and migrations are OK
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

function openSetup(): void {
  const win = secureWindow(join(__dirname, "preload-setup.js"));
  guard(win, null);
  void win.loadFile(join(__dirname, "..", "assets", "setup.html"));
  mainWindow = win;
  smokeReport(win);
}

async function openApp(config: DesktopConfig): Promise<void> {
  const url = appUrl(config);
  const win = secureWindow(join(__dirname, "preload.js"));
  guard(win, url);
  mainWindow = win;
  if (config.mode === "local") {
    const workerLogStart = logSize("worker");
    startLocal(config);
    await win.loadFile(join(__dirname, "..", "assets", "starting.html"));
    // Ready means: API ready (DB + migrations), worker running, web serving.
    const ready =
      (await waitFor(`http://127.0.0.1:${config.apiPort}/readyz`, 120_000)) &&
      (await waitForLog("worker", "worker_started", workerLogStart, 120_000)) &&
      (await waitFor(`${url}/login`, 120_000));
    if (!ready) {
      dialog.showErrorBox(
        "NexScout didn't start",
        `The local servers didn't become ready. Check that Postgres is running and the checkout is set up (docs/DEVELOPMENT.md). Logs: ${join(app.getPath("userData"), "logs")}`,
      );
      return;
    }
  }
  if (config.mode === "easy") {
    await win.loadFile(join(__dirname, "..", "assets", "starting.html"));
    const problem = await startEasy(config);
    // The first start downloads the images (a few minutes); later starts take seconds.
    if (problem || !(await waitFor(`${url}/login`, 600_000))) {
      dialog.showErrorBox(
        "NexScout didn't start",
        problem ?? `NexScout didn't become ready. Log: ${logFile("easy")}`,
      );
      return;
    }
  }
  smokeReport(win);
  await win.loadURL(url);
}

/** --smoke: report what the window loaded and what the page can reach, then quit. */
function smokeReport(win: BrowserWindow): void {
  if (!SMOKE) return;
  win.webContents.once("did-finish-load", async () => {
    // Evaluated inside the page: proves Node isn't reachable from web content.
    const page = (await win.webContents.executeJavaScript(
      `({ require: typeof require, process: typeof process, module: typeof module,
          desktop: typeof window.nexscoutDesktop, setup: typeof window.nexscoutSetup })`,
    )) as Record<string, string>;
    process.stdout.write(
      `SMOKE ${JSON.stringify({
        title: win.webContents.getTitle(),
        url: win.webContents.getURL(),
        page,
        safeStorage: safeStorage.isEncryptionAvailable(),
      })}\n`,
    );
    app.quit();
  });
}

ipcMain.handle("setup:choose-folder", async () => {
  const res = await dialog.showOpenDialog({ properties: ["openDirectory"] });
  return res.canceled ? null : (res.filePaths[0] ?? null);
});

ipcMain.handle("setup:save", async (_event, raw: unknown) => {
  const config = parseConfig(raw);
  if (!config) return { ok: false, error: "Please check the address or folder." };
  if (config.mode === "local" && !existsSync(join(config.checkoutDir as string, "backend"))) {
    return { ok: false, error: "That folder isn't a NexScout checkout (no backend/ folder)." };
  }
  try {
    saveConfig(config);
    setMenu();
    const old = mainWindow;
    await openApp(config);
    old?.close();
    return { ok: true };
  } catch (err) {
    const detail = err instanceof Error ? err.message : String(err);
    return { ok: false, error: `NexScout couldn't start: ${detail.slice(0, 300)}` };
  }
});

app.on("web-contents-created", (_event, contents) => {
  contents.on("will-attach-webview", (event) => event.preventDefault());
});

function setMenu(): void {
  const config = loadConfig();
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: "NexScout",
      submenu: [
        ...(config?.mode === "easy"
          ? [
              {
                label: "Stop NexScout (background work too)",
                click: async () => {
                  await stopEasy();
                  app.quit();
                },
              },
              { type: "separator" as const },
            ]
          : []),
        { label: "Check for updates…", click: () => checkForUpdatesNow() },
        { type: "separator" as const },
        { role: "reload" as const },
        { role: "toggleDevTools" as const, visible: !app.isPackaged },
        { role: "quit" as const, label: "Close window (keeps working in the background)" },
      ],
    },
    { role: "editMenu" as const },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

void app.whenReady().then(async () => {
  setMenu();
  session.defaultSession.setPermissionRequestHandler((_wc, _perm, callback) => callback(false));
  const smokeUrl = process.env.NEXSCOUT_DESKTOP_SMOKE_URL;
  const config = smokeUrl ? parseConfig({ mode: "remote", remoteUrl: smokeUrl }) : loadConfig();
  if (config) await openApp(config);
  else openSetup();
  startUpdates(() => mainWindow);
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => children.forEach(killTree));
