import { expect, test, type Page } from "./fixtures";

// M4 acceptance journey: background work is visible and controllable. Start a workflow, pause
// and resume it, answer its approval, add a (mock) AI model, and draft a grounded summary that
// is clearly labelled as mock output. Synthetic persona only.

const PASSWORD = "correct horse battery staple";

function uniqueEmail(tag: string): string {
  return `${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

async function registerWithCase(page: Page, email: string): Promise<string> {
  await page.goto("/register");
  await page.getByRole("textbox", { name: "Your name" }).fill("Ada Example");
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/cases$/);
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Runtime check");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname;
}

test("run, pause, resume, and approve a workflow from Agent Activity", async ({ page }) => {
  test.setTimeout(120_000);
  const caseBase = await registerWithCase(page, uniqueEmail("m4-activity"));

  await page.goto(`${caseBase}/activity`);
  await expect(page.getByRole("heading", { name: "Agent Activity", level: 1 })).toBeVisible();
  await expect(page.getByText("Nothing has run for this case yet.")).toBeVisible();
  await expect(page.getByText("Live updates on.")).toBeVisible({ timeout: 15_000 });

  await page.getByRole("combobox", { name: "Workflow" }).selectOption("system_check");
  await page.getByRole("spinbutton", { name: /Wait step/ }).fill("6");
  await page.getByRole("button", { name: "Start" }).click();

  const run = page.getByRole("region", { name: "System check" });
  const runStatus = run.locator("header");
  await expect(runStatus.getByText("Running", { exact: true })).toBeVisible({ timeout: 20_000 });

  // Pause takes effect at the next step boundary (after the wait step), never mid-step.
  await run.getByRole("button", { name: "Pause" }).click();
  await expect(runStatus.getByText("Paused", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(run.getByRole("button", { name: "Resume" })).toBeVisible();

  await run.getByRole("button", { name: "Resume" }).click();
  const decisions = page.getByRole("region", { name: /Waiting for your decision/ });
  await expect(decisions).toBeVisible({ timeout: 30_000 });
  await decisions.getByRole("textbox", { name: "Note (optional)" }).fill("Looks fine");
  await decisions.getByRole("button", { name: "Approve" }).click();

  await expect(runStatus.getByText("Done", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(decisions).toHaveCount(0);
  // The run list is refreshed by live events (its fallback poll is 30 s, far beyond this wait).
  await expect(
    page.getByRole("region", { name: "Runs" }).getByRole("button", { name: /System check/ }),
  ).toContainText("Done", { timeout: 5_000 });
  // Every step is listed with its outcome; nothing ran twice.
  await expect(run.getByRole("listitem").filter({ hasText: /^effect/ })).toHaveCount(1);
});

test("add a mock AI model, check it, and draft a labelled, cited summary", async ({ page }) => {
  test.setTimeout(120_000);
  const caseBase = await registerWithCase(page, uniqueEmail("m4-ai"));

  // Settings: the mock is labelled and the check runs for real against it.
  await page.goto(`${caseBase}/settings`);
  await page.getByRole("combobox", { name: "Type" }).selectOption("mock");
  await page.getByRole("textbox", { name: "Name *" }).fill("Test model");
  await page.getByRole("checkbox", { name: "Use as my default" }).check();
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const model = page.getByRole("listitem", { name: "Test model" });
  await expect(model.getByText("Mock — not a real AI")).toBeVisible();
  await expect(model.getByText("Default", { exact: true })).toBeVisible();
  await model.getByRole("button", { name: "Check connection" }).click();
  await expect(model.getByText(/^Working \(/)).toBeVisible({ timeout: 30_000 });

  // A key field for a real provider is write-only (password input).
  await page.getByRole("combobox", { name: "Type" }).selectOption("anthropic");
  await expect(page.getByLabel(/API key/)).toHaveAttribute("type", "password");

  // Profile: one confirmed entry, then a draft that cites it and waits for review.
  await page.goto(`${caseBase}/profile`);
  await page.getByRole("combobox", { name: "Section" }).selectOption("skill");
  await page.locator("#add").getByRole("textbox", { name: /^Skill/ }).fill("Python");
  await page.getByRole("button", { name: "Add to profile" }).click();
  await expect(page.locator("#confirmed").getByRole("article", { name: "Python", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Draft a summary with AI" }).click();
  await expect(page.getByText("Draft ready.")).toBeVisible({ timeout: 30_000 });
  const draft = page.locator("#review").getByRole("article").filter({ hasText: "Skills include Python." });
  await expect(draft).toBeVisible();
  await expect(draft.getByText("Mock text, not written by AI")).toBeVisible();
});
