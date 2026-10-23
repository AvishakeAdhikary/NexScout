import { expect, test, type Page } from "./fixtures";

// M14: visit every page with real data behind it and fail on any page error, console error or
// API 5xx (see fixtures.ts). Also checks that unknown ids give a readable message, not a crash.

const PASSWORD = "correct horse battery staple";

async function api(page: Page, method: "GET" | "POST", path: string, data?: unknown) {
  const csrf =
    (await page.context().cookies()).find((c) => c.name === "nexscout_csrf")?.value ?? "";
  const res = await page.request.fetch(`/api/v1${path}`, {
    method,
    data,
    headers: method === "GET" ? {} : { "X-CSRF-Token": csrf },
  });
  expect(res.status(), `${method} ${path}`).toBeLessThan(400);
  return res.status() === 204 ? null : res.json();
}

async function waitRun(page: Page, runId: string, statuses = ["succeeded", "waiting_approval"]) {
  await expect
    .poll(async () => (await api(page, "GET", `/runs/${runId}`)).run.status, { timeout: 90_000 })
    .toMatch(new RegExp(`^(${statuses.join("|")})$`));
}

test("every page renders without errors, with data and for unknown ids", async ({ page }) => {
  test.setTimeout(300_000);
  await page.goto("/register");
  await page.getByRole("textbox", { name: "Your name" }).fill("Crawl Example");
  await page.getByRole("textbox", { name: "Email" }).fill(`crawl-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/cases$/);

  // Seed: a case with a profile, opportunities, a document, an application and an approval.
  const kase = await api(page, "POST", "/cases", { name: "Crawl case" });
  const c = kase.id as string;
  await api(page, "POST", `/cases/${c}/facts`, { section: "skill", data: { name: "Python" } });
  const sync = await api(page, "POST", `/cases/${c}/opportunities/sync`, {});
  await waitRun(page, sync.run_id);
  const jobs = await api(page, "GET", `/cases/${c}/opportunities?academic=false`);
  const phds = await api(page, "GET", `/cases/${c}/opportunities?academic=true`);
  const doc = await api(page, "POST", `/cases/${c}/generated-documents`, { doc_type: "resume" });
  await waitRun(page, doc.run_id);
  const docs = await api(page, "GET", `/cases/${c}/generated-documents`);
  const app = await api(page, "POST", `/cases/${c}/applications`, {
    opportunity_id: jobs[0].id,
    document_ids: [docs[0].id],
  });
  const run = await api(page, "POST", `/cases/${c}/runs`, {
    kind: "system_check",
    params: { require_approval: true },
  });
  await waitRun(page, run.id, ["waiting_approval"]);
  const approvals = await api(page, "GET", `/cases/${c}/approvals`);

  const base = `/cases/${c}`;
  const routes = [
    "/cases",
    base,
    `${base}/profile`,
    `${base}/mind-map`,
    `${base}/phd`,
    ...(phds.length ? [`${base}/phd/${phds[0].id}`] : []),
    `${base}/jobs`,
    `${base}/jobs/${jobs[0].id}`,
    `${base}/applications`,
    `${base}/applications/${app.id}`,
    `${base}/documents`,
    `${base}/documents/generated/${docs[0].id}`,
    `${base}/relationships`,
    `${base}/assistant`,
    `${base}/activity`,
    `${base}/autopilot`,
    `${base}/settings`,
    "/account",
    `/approve/${approvals[0].id}`,
  ];
  for (const route of routes) {
    await page.goto(route);
    await expect(page.getByRole("heading", { level: 1 }).first(), route).toBeVisible({
      timeout: 20_000,
    });
    await page.waitForLoadState("networkidle");
  }

  // Unknown ids: a readable message, never a crash or a blank page.
  const missing = "00000000-0000-7000-8000-000000000000";
  for (const route of [
    `/cases/${missing}`,
    `${base}/applications/${missing}`,
    `/approve/${missing}`,
  ]) {
    await page.goto(route);
    await expect(page.getByRole("alert").first(), route).toBeVisible({ timeout: 20_000 });
  }
});
