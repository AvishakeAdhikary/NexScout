import { expect, test, type Page } from "./fixtures";

// M20: the opportunity board pages and searches (tabs with counts), Agent Activity's finished
// runs and the notifications can be cleared. Large lists (5,000 opportunities) are measured by
// backend/tests/system/test_opportunity_scale.py. Demo data only.

const PASSWORD = "correct horse battery staple";

async function registerWithCase(page: Page): Promise<string> {
  await page.goto("/register");
  await page.getByRole("textbox", { name: "Your name" }).fill("Ada Example");
  await page
    .getByRole("textbox", { name: "Email" })
    .fill(`m20-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/cases$/);
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Job search");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname;
}

test("board tabs and search, clear activity and notifications", async ({ page }) => {
  test.setTimeout(180_000);
  const base = await registerWithCase(page);

  await page.goto(`${base}/jobs`);
  await page.getByRole("button", { name: "Find opportunities" }).click();
  const lists = page.getByRole("tablist", { name: "Lists" });
  await expect(lists.getByRole("tab", { name: /^Not a fit right now \([1-9]\d*\)$/ })).toBeVisible({
    timeout: 30_000,
  });
  await lists.getByRole("tab", { name: /^Not a fit right now/ }).click();
  await expect(page.getByRole("article").first()).toBeVisible();

  // Search narrows every list, and the counts follow.
  await page.getByRole("searchbox", { name: "Search titles and employers" }).fill("zzz-nothing");
  await expect(page.getByText("Nothing matches “zzz-nothing”.")).toBeVisible();
  await expect(lists.getByRole("tab", { name: "Matches (0)" })).toBeVisible();
  await page.getByRole("searchbox", { name: "Search titles and employers" }).fill("");
  await expect(page.getByRole("article").first()).toBeVisible();

  // The finished search can be cleared from Agent Activity.
  await page.goto(`${base}/activity`);
  const runs = page
    .getByRole("region", { name: "Runs" })
    .or(page.locator("section", { has: page.getByRole("heading", { name: "Runs" }) }));
  await expect(page.getByRole("button", { name: "Clear finished" })).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: "Clear finished" }).click();
  await expect(page.getByText(/Cleared \d+ finished run\(s\)/)).toBeVisible();
  await expect(runs.getByText("Nothing has run for this case yet.")).toBeVisible();

  // Notifications: a due reminder becomes one; clear it.
  const caseId = base.split("/").pop()!;
  const csrf =
    (await page.context().cookies()).find((c) => c.name === "nexscout_csrf")?.value ?? "";
  const made = await page.request.post(`/api/v1/cases/${caseId}/reminders`, {
    data: { title: "Check the deadline", due_on: "2026-01-01" },
    headers: { "X-CSRF-Token": csrf },
  });
  expect(made.status()).toBe(201);
  const bell = page.getByRole("button", { name: /^Notifications/ });
  await expect(async () => {
    await page.reload();
    await expect(page.getByRole("button", { name: /^Notifications \(\d+\)/ })).toBeVisible({
      timeout: 2_000,
    });
  }).toPass({ timeout: 30_000 }); // the worker turns due reminders into notifications
  await bell.click();
  const panel = page.getByRole("region", { name: "Notifications" });
  await expect(panel.getByText("Check the deadline")).toBeVisible();
  page.once("dialog", (d) => d.accept());
  await panel.getByRole("button", { name: "Clear all" }).click();
  await expect(panel.getByText("Nothing yet.")).toBeVisible();
});
