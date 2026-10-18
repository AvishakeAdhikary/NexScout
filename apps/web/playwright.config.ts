import { defineConfig, devices } from "@playwright/test";

// E2E runs the real stack: FastAPI (uv) + worker + Next.js against the dev Postgres from
// docker compose. Mock providers and the labelled demo data only (NEXSCOUT_DEMO_DATA=1; a real
// install has demo data off). Each run uses fresh, unique synthetic accounts.
//
// E2E_PROD=1 runs the same journeys against a production build (`next build` + `next start`)
// and the API in production mode, the way users get it.
const API_PORT = 8100;
const WEB_PORT = 3200;
const PROD = process.env.E2E_PROD === "1";

const backendEnv: Record<string, string> = {
  NEXSCOUT_FIXTURE_SITE_ORIGIN: `http://127.0.0.1:${API_PORT}`,
  NEXSCOUT_DEMO_DATA: "1",
  NEXSCOUT_UPDATE_CHECK: "0", // E2E never calls GitHub
  ...(PROD
    ? {
        NEXSCOUT_ENV: "production",
        // Test-only key (production refuses to start without one). Never used outside E2E.
        NEXSCOUT_MASTER_KEY: process.env.E2E_MASTER_KEY ?? Buffer.alloc(32, 7).toString("base64"),
        NEXSCOUT_PUBLIC_WEB_URL: `http://127.0.0.1:${WEB_PORT}`,
      }
    : {}),
};

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
      env: backendEnv,
      url: `http://127.0.0.1:${API_PORT}/readyz`,
      reuseExistingServer: !process.env.CI && !PROD,
      timeout: 120_000,
    },
    {
      // Uploads and searches run in the background worker. Extra workers on the same database
      // are safe (tasks are claimed with SKIP LOCKED), so a separately running dev worker is fine.
      command: "uv run nexscout worker",
      cwd: "../../backend",
      // The demo application site is served by the API; the worker's browser goes there.
      // A fast maintenance sweep makes reminders/notifications appear within the test.
      env: { ...backendEnv, NEXSCOUT_MAINTENANCE_INTERVAL_S: "2" },
      wait: { stdout: /worker_started/ },
      timeout: 120_000,
    },
    {
      command: PROD
        ? `npx next build && npx next start -p ${WEB_PORT} -H 127.0.0.1`
        : `npx next dev -p ${WEB_PORT} -H 127.0.0.1`,
      url: `http://127.0.0.1:${WEB_PORT}/login`,
      env: { NEXSCOUT_API_ORIGIN: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: !process.env.CI && !PROD,
      timeout: 300_000,
    },
  ],
});
