import path from "node:path";

import { expect, test, type Page } from "./fixtures";

// M18: a CV and a recommendation letter read cleanly (a project linked to its job, the
// recommender as a reference), bulk actions, snapshots, auto-arrange, and moving the whole
// profile to a new case with Export/Import. Synthetic persona only.

const PASSWORD = "correct horse battery staple";
const PERSONAS = path.resolve(__dirname, "../../../backend/tests/fixtures/personas");

async function registerWithCase(page: Page): Promise<string> {
  await page.goto("/register");
  await page.getByRole("textbox", { name: "Your name" }).fill("Rohan Example");
  await page.getByRole("textbox", { name: "Email" }).fill(`m18-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/cases$/);
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Europe search");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname;
}

test("read well, link, bulk-review, snapshot, arrange, export and import", async ({ page }) => {
  test.setTimeout(180_000);
  const base = await registerWithCase(page);

  // Two files at once: the CV and a letter (the purpose applies to both; the letter is re-read
  // as a letter below by uploading it separately).
  await page.goto(`${base}/documents`);
  await page.locator('input[type="file"]').setInputFiles(path.join(PERSONAS, "rohan_cv.md"));
  await expect(page.getByText(/Found \d+ possible entries/)).toBeVisible({ timeout: 30_000 });
  await page.getByLabel("What is this document?").selectOption("recommendation_letter");
  await page.locator('input[type="file"]').setInputFiles(path.join(PERSONAS, "letter_formal.txt"));
  await expect(page.getByText("Found 1 possible entries")).toBeVisible({ timeout: 30_000 });

  // Review: clean names, the project linked to its job, the recommender as a private reference.
  await page.goto(`${base}/profile`);
  const desk = page.getByRole("article", { name: "VisionDesk", exact: true });
  await expect(desk.getByText("Part of: Machine Learning Engineer at Lumen Robotics")).toBeVisible();
  const ref = page.getByRole("article", { name: "Dr. Vikram Sample" });
  await expect(ref.getByText("Private", { exact: true })).toBeVisible();
  await expect(page.getByText("**")).toHaveCount(0);

  // Bulk: select every skill, accept them in one go.
  const skills = page.getByRole("heading", { name: /^Skills \(\d+\)$/ });
  await skills.locator("..").getByRole("button", { name: "Select all" }).click();
  const bar = page.getByRole("region", { name: "Selected entries" });
  await expect(bar.getByText(/\d+ selected/)).toBeVisible();
  await bar.getByRole("button", { name: "Accept", exact: true }).click();
  await expect(page.getByRole("heading", { name: /^Skills \(\d+\)$/ })).toHaveCount(0);
  // Then everything else still pending.
  for (const header of await page.getByRole("heading", { level: 3, name: /\(\d+\)$/ }).all()) {
    await header.locator("..").getByRole("button", { name: "Select all" }).click();
  }
  await bar.getByRole("button", { name: "Accept", exact: true }).click();
  await expect(page.getByText("Nothing to review.")).toBeVisible();

  // Mind map: auto-arrange, then a snapshot saved and deleted.
  await page.goto(`${base}/mind-map`);
  await page.getByRole("button", { name: "Auto-arrange" }).click();
  await expect(page.getByRole("button", { name: "Auto-arrange" })).toBeEnabled();
  await page.getByRole("button", { name: "Save snapshot now" }).click();
  await page.getByText(/Saved snapshots \(1\)/).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Delete snapshot 1" }).click();
  await expect(page.getByText(/Saved snapshots/)).toHaveCount(0);

  // Export the profile, import it as a new case.
  await page.goto(`${base}/profile`);
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export profile" }).click();
  const file = await (await download).path();
  await page.goto("/cases");
  await page.locator('input[type="file"]').setInputFiles({
    name: "rohan.nexscout",
    mimeType: "application/zip",
    buffer: await (await import("node:fs/promises")).readFile(file!),
  });
  const done = page.getByRole("status").filter({ hasText: "Imported as" });
  await expect(done).toBeVisible({ timeout: 30_000 });
  await done.getByRole("link", { name: "Europe search (imported)" }).click();
  await page.getByRole("link", { name: /My Profile/ }).first().click();
  await expect(
    page.getByRole("article", { name: "VisionDesk", exact: true }).getByText(
      "Part of: Machine Learning Engineer at Lumen Robotics",
    ),
  ).toBeVisible();
  await expect(page.getByText("Nothing to review.")).toBeVisible();
});

test("suggestions left behind by a deleted file can be removed in one click", async ({ page }) => {
  test.setTimeout(120_000);
  const base = await registerWithCase(page);
  await page.goto(`${base}/documents`);
  await page.locator('input[type="file"]').setInputFiles(path.join(PERSONAS, "rohan_cv.md"));
  await expect(page.getByText(/Found \d+ possible entries/)).toBeVisible({ timeout: 30_000 });

  // Delete the file but keep its suggestions (the second question is answered "Cancel").
  let asked = 0;
  page.on("dialog", (d) => (asked++ === 0 ? d.accept() : d.dismiss()));
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByRole("button", { name: "Delete", exact: true })).toHaveCount(0);
  expect(asked).toBe(2);

  await page.goto(`${base}/profile`);
  const notice = page.getByRole("status").filter({ hasText: "came from a file you have since deleted" });
  await expect(notice).toBeVisible();
  page.removeAllListeners("dialog");
  page.once("dialog", (d) => d.accept());
  await notice.getByRole("button", { name: "Remove them" }).click();
  await expect(page.getByText("Nothing to review.")).toBeVisible();
});
