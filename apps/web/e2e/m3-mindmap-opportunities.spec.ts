import path from "node:path";

import { expect, test, type Page } from "./fixtures";

const PASSWORD = "correct horse battery staple";
const CV = path.resolve(__dirname, "../../../backend/tests/fixtures/personas/ada_example_cv.md");

async function setup(page: Page): Promise<string> {
  const email = `m3-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  await page.goto("/register");
  await page.getByRole("textbox", { name: "Your name" }).fill("Ada Example");
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/cases$/);
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Both paths");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  const base = new URL(page.url()).pathname;
  await page.getByRole("radio", { name: "PhD and employment" }).check();
  await expect(page.getByRole("radio", { name: "PhD and employment" })).toBeChecked();

  await page.goto(`${base}/documents`);
  // The drop zone uploads as soon as a file is chosen.
  await page.locator('input[type="file"]').setInputFiles(CV);
  await page.getByRole("link", { name: "Review them now" }).click();
  // Accept every section (wait for the queue to load first).
  const acceptButtons = page.locator("#review").getByRole("button", { name: /^Accept all \d+$/ });
  await expect(acceptButtons.first()).toBeVisible();
  for (let remaining = await acceptButtons.count(); remaining > 0; remaining--) {
    await acceptButtons.first().click();
    await expect(acceptButtons).toHaveCount(remaining - 1);
  }
  await expect(page.getByText("Nothing to review.")).toBeVisible();
  return base;
}

test("mind map shows confirmed entries with evidence, list view, and saved renames", async ({
  page,
}) => {
  const base = await setup(page);
  await page.goto(`${base}/mind-map`);
  await expect(page.getByRole("heading", { name: "Mind Map", level: 1 })).toBeVisible();
  await expect(page.getByText("Machine Learning Engineer at Examplecorp GmbH").first()).toBeVisible(
    { timeout: 15_000 },
  );

  // Accessible list alternative.
  await page.getByRole("button", { name: "Show as list" }).click();
  await expect(page.getByRole("heading", { name: "Employment", level: 2 })).toBeVisible();
  await page.getByRole("button", { name: "Machine Learning Engineer at Examplecorp GmbH" }).click();
  const panel = page.getByRole("complementary");
  await expect(panel.locator("blockquote").first()).toContainText("Built evaluation pipelines");

  // Rename on the map only; survives reload (regeneration).
  await panel.getByRole("textbox", { name: "Display name on the map" }).fill("Current job");
  await panel.getByRole("button", { name: "Save name" }).click();
  await page.reload();
  await page.getByRole("button", { name: "Show as list" }).click();
  await expect(page.getByRole("button", { name: "Current job" })).toBeVisible();

  // Snapshot history.
  await page.getByRole("button", { name: "Save snapshot now" }).click();
  await page.getByRole("button", { name: "Save snapshot now" }).click();
  await page.getByLabel("Compare").selectOption({ index: 1 });
  await page.getByLabel("with").selectOption({ index: 2 });
  await expect(page.getByText(/unchanged\./)).toBeVisible();
});

test("job discovery: demo label, merged duplicates, explained estimates, strict mode", async ({
  page,
}) => {
  const base = await setup(page);
  await page.goto(`${base}/jobs`);
  await expect(page.getByText("They are not real postings.")).toBeVisible();
  await page.getByRole("button", { name: "Find opportunities" }).click();
  // The catalog is shared, so merges may already have happened in an earlier sync; what this
  // user sees is "new for you" and listings that show every board they were seen on.
  await expect(page.getByText(/demo_jobs_board_a: checked 7; 7 new for you/)).toBeVisible({
    timeout: 30_000,
  });

  const matches = page.getByRole("region", { name: /Matches/ });
  const card = matches.getByRole("article").filter({ hasText: "Examplecorp GmbH" }).first();
  await expect(card).toBeVisible();
  await card.getByText("Why this estimate?").click();
  await expect(card.getByText(/Skills: \d+\/35/)).toBeVisible();
  await expect(card.getByText("demo_jobs_board_b")).toBeVisible(); // seen on both boards

  // Strict mode (default) hides the senior role from matches, and says why.
  await expect(matches.getByRole("heading", { name: "Senior Data Scientist" })).toHaveCount(0);
  await page.getByText(/Not a fit right now/).click();
  await expect(page.getByText(/Hidden in strict mode/).first()).toBeVisible();
  await page.getByRole("tab", { name: /^Matches/ }).click(); // lists are tabs (M20)

  // Shortlist one.
  await card.getByRole("button", { name: "Shortlist" }).click();
  await expect(card.getByText("shortlisted")).toBeVisible();

  // Running the search again creates no duplicates.
  await page.getByRole("button", { name: "Find opportunities" }).click();
  await expect(page.getByText(/demo_jobs_board_a: checked 7; 0 new for you/)).toBeVisible({
    timeout: 30_000,
  });
});
