import { defineConfig, devices } from "@playwright/test";

// E2E runs the real stack: FastAPI (uv) + Next.js dev server against the dev Postgres from
// docker compose. Mock providers only. Each run uses fresh, unique synthetic accounts.
const API_PORT = 8100;
const WEB_PORT = 3200;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1, // one shared dev server and database; journeys are sequential by design
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"]],
  timeout: 60_000,
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run nexscout serve --port ${API_PORT}`,
      cwd: "../../backend",
      url: `http://127.0.0.1:${API_PORT}/readyz`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      // Uploads and searches run in the background worker. Extra workers on the same database
      // are safe (tasks are claimed with SKIP LOCKED), so a separately running dev worker is fine.
      command: "uv run nexscout worker",
      cwd: "../../backend",
      wait: { stdout: /worker_started/ },
      timeout: 120_000,
    },
    {
      command: `npx next dev -p ${WEB_PORT} -H 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}/login`,
      env: { NEXSCOUT_API_ORIGIN: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
    },
  ],
});
