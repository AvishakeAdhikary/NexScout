import { describe, expect, it } from "vitest";

import {
  appUrl,
  DEFAULT_EASY_PORT,
  dockerCandidates,
  easyEnv,
  isAppNavigation,
  isSafeExternal,
  parseConfig,
  foreignEasyStack,
  safeHttpUrl,
  staleImages,
  updaterCacheDir,
} from "./policy";

describe("desktop policy", () => {
  it("accepts https anywhere but http only on this machine", () => {
    expect(safeHttpUrl("https://nexscout.example.org/")).toBe("https://nexscout.example.org");
    expect(safeHttpUrl("http://127.0.0.1:3000")).toBe("http://127.0.0.1:3000");
    expect(safeHttpUrl("http://localhost:3000/")).toBe("http://localhost:3000");
    expect(safeHttpUrl("http://nexscout.example.org")).toBeNull();
    expect(safeHttpUrl("https://user:pw@nexscout.example.org")).toBeNull();
    expect(safeHttpUrl("file:///etc/passwd")).toBeNull();
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull();
  });

  it("validates configs from disk", () => {
    expect(parseConfig({ mode: "remote", remoteUrl: "https://a.example" })).toEqual({
      mode: "remote",
      remoteUrl: "https://a.example",
    });
    expect(parseConfig({ mode: "remote", remoteUrl: "http://evil.example" })).toBeNull();
    expect(parseConfig({ mode: "local", checkoutDir: "C:/nexscout", apiPort: 80 })).toEqual({
      mode: "local",
      checkoutDir: "C:/nexscout",
      apiPort: 18800,
      webPort: 18900,
    });
    expect(parseConfig({ mode: "shell", cmd: "rm -rf /" })).toBeNull();
    expect(parseConfig(null)).toBeNull();
  });

  it("keeps the window on the app origin", () => {
    const app = "https://nexscout.example.org";
    expect(isAppNavigation("https://nexscout.example.org/cases/1", app)).toBe(true);
    expect(isAppNavigation("https://nexscout.example.org.evil.com/", app)).toBe(false);
    expect(isAppNavigation("http://nexscout.example.org/", app)).toBe(false);
    expect(isSafeExternal("https://uni.example/apply")).toBe(true);
    expect(isSafeExternal("mailto:sam@example.com")).toBe(true);
    expect(isSafeExternal("file:///C:/Windows/system32/calc.exe")).toBe(false);
    expect(isSafeExternal("ms-msdt:/id")).toBe(false);
    expect(appUrl({ mode: "local", checkoutDir: "x", webPort: 18901 })).toBe("http://127.0.0.1:18901");
  });

  it("easy mode: loopback only, validated secrets, matching image version", () => {
    expect(parseConfig({ mode: "easy" })).toEqual({ mode: "easy", webPort: DEFAULT_EASY_PORT });
    expect(parseConfig({ mode: "easy", webPort: 22 })).toEqual({ mode: "easy", webPort: DEFAULT_EASY_PORT });
    expect(appUrl({ mode: "easy", webPort: 18777 })).toBe("http://127.0.0.1:18777");
    const key = Buffer.alloc(32, 7).toString("base64");
    const env = easyEnv({ masterKey: key, dbPassword: "a".repeat(48), port: 18700, version: "2.3.0" });
    expect(env.NEXSCOUT_VERSION).toBe("2.3.0");
    expect(env.NEXSCOUT_PUBLIC_WEB_URL).toBe("http://127.0.0.1:18700");
    expect(easyEnv({ masterKey: key, dbPassword: "b".repeat(48), port: 1, version: "0.1.0" }).NEXSCOUT_VERSION).toBe(
      "latest",
    );
    // Nothing that could break out of an environment variable or a command line.
    expect(() => easyEnv({ masterKey: "x;rm -rf /", dbPassword: "a".repeat(48), port: 1, version: "1" })).toThrow();
    expect(() => easyEnv({ masterKey: key, dbPassword: "p w", port: 1, version: "1" })).toThrow();
  });

  it("finds Docker Desktop where it installs", () => {
    const win = dockerCandidates("win32", { ProgramFiles: "C:\\Program Files", LOCALAPPDATA: "C:\\Users\\a\\AppData\\Local" });
    expect(win).toEqual([
      "C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe",
      "C:\\Users\\a\\AppData\\Local\\Programs\\DockerDesktop\\resources\\bin\\docker.exe",
    ]);
    expect(dockerCandidates("darwin", {})).toContain("/Applications/Docker.app/Contents/Resources/bin/docker");
  });
});

describe("update cleanup", () => {
  it("removes only older NexScout images", () => {
    const lines = [
      "ghcr.io/avishakeadhikary/nexscout-backend:2.1.0",
      "ghcr.io/avishakeadhikary/nexscout-backend:2.2.0",
      "ghcr.io/avishakeadhikary/nexscout-web:2.1.0",
      "ghcr.io/avishakeadhikary/nexscout-web:<none>",
      "postgres:17-alpine",
      "ghcr.io/someone/other-backend:1.0.0",
      "localhost:5000/nexscout-web:1.0.0",
    ];
    expect(staleImages(lines, "2.2.0")).toEqual([
      "ghcr.io/avishakeadhikary/nexscout-backend:2.1.0",
      "ghcr.io/avishakeadhikary/nexscout-web:2.1.0",
    ]);
    expect(staleImages(lines, "latest")).toEqual([]); // development builds keep everything
  });

  it("finds the updater cache per platform", () => {
    expect(updaterCacheDir("win32", { LOCALAPPDATA: "C:\\Users\\a\\AppData\\Local" }, "C:\\Users\\a")).toBe(
      "C:\\Users\\a\\AppData\\Local\\nexscout-desktop-updater",
    );
    expect(updaterCacheDir("win32", {}, "C:\\Users\\a")).toBe(
      "C:\\Users\\a\\AppData\\Local\\nexscout-desktop-updater",
    );
    expect(updaterCacheDir("linux", {}, "/home/a")).toBe("/home/a/.cache/nexscout-desktop-updater");
  });

  it("refuses to take over an Easy stack another install started", () => {
    const ours = "C:\\Program Files\\NexScout\\resources\\easy\\docker-compose.yml";
    const zip = "C:\\Users\\a\\NexScout-2.3.0\\easy\\docker-compose.yml";
    const there = (p: string) => p === zip;
    expect(foreignEasyStack([], ours, there)).toBeNull(); // nothing running
    expect(foreignEasyStack([ours.toLowerCase().replace(/\\/g, "/")], ours, there)).toBeNull();
    expect(foreignEasyStack([zip], ours, there)).toBe(zip);
    expect(foreignEasyStack(["C:\\gone\\docker-compose.yml"], ours, there)).toBeNull(); // moved
  });
});
