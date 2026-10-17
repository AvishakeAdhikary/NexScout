import { describe, expect, it } from "vitest";

import { appUrl, isAppNavigation, isSafeExternal, parseConfig, safeHttpUrl } from "./policy";

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
});
