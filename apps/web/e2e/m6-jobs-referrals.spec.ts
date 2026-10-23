import { expect, test, type Page } from "./fixtures";

// M6 acceptance journey: research a (demo) job, see referral suggestions only for people the
// user allowed, draft a referral request and a resume. Mock model; synthetic data.

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
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Job search");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname;
}

async function addRelationship(page: Page, person: string, org: string, referral: boolean) {
  await page.getByRole("textbox", { name: /^Person/ }).fill(person);
  await page.getByRole("textbox", { name: "Organization *" }).fill(org);
  await page.getByRole("combobox", { name: "Relationship *" }).selectOption("current_employee");
  if (referral) await page.getByRole("checkbox", { name: /suggest asking this person/ }).check();
  await page.getByRole("button", { name: "Add relationship" }).click();
  await expect(page.getByRole("cell", { name: person })).toBeVisible();
}

test("job research, permission-gated referrals, referral request and resume", async ({ page }) => {
  test.setTimeout(180_000);
  const caseBase = await registerWithCase(page, uniqueEmail("m6"));

  await page.goto(`${caseBase}/profile`);
  await page.getByRole("combobox", { name: "Section" }).selectOption("skill");
  await page
    .locator("#add")
    .getByRole("textbox", { name: /^Skill/ })
    .fill("Python");
  await page.getByRole("button", { name: "Add to profile" }).click();
  await expect(
    page.locator("#confirmed").getByRole("article", { name: "Python", exact: true }),
  ).toBeVisible();

  await page.goto(`${caseBase}/relationships`);
  await addRelationship(page, "Sam Example", "ACME", true);
  await addRelationship(page, "Lee Hidden", "Acme GmbH", false);

  await page.goto(`${caseBase}/jobs`);
  await page.getByRole("button", { name: "Find opportunities" }).click();
  await expect(page.getByText(/demo_jobs_board_a: checked/)).toBeVisible({ timeout: 30_000 });
  // No work history yet, so strict mode lists it under "Not a fit right now" (with reasons).
  await page.getByText(/Not a fit right now/).click();
  // The ML Engineer listing seen on two boards (merged) is REQ-100 at Acme.
  const card = page
    .getByRole("article", { name: "Machine Learning Engineer" })
    .filter({ has: page.getByRole("button", { name: "Report wrong merge" }) });
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.getByRole("link", { name: "Research and prepare" }).click();
  await expect(page.getByRole("link", { name: "← Job opportunities" })).toBeVisible();

  await page.getByRole("button", { name: "Research this position" }).click();
  await expect(page.getByText("Research finished.")).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByRole("listitem", { name: "Application deadline: 30 November 2026", exact: true }),
  ).toBeVisible();

  const refs = page.getByRole("region", { name: "People who could refer you" });
  await expect(refs.getByText("Sam Example", { exact: true })).toBeVisible();
  await expect(refs.getByText("Lee Hidden")).toHaveCount(0);
  await expect(
    refs.getByText(/1 other relationship\(s\) at this organization aren.t allowed/),
  ).toBeVisible();

  const referralButton = page.getByRole("button", { name: "Draft referral request" });
  await expect(referralButton).toBeDisabled();
  await refs.getByRole("radio").check();
  await referralButton.click();
  await expect(page.getByText(/Draft ready/).first()).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Draft resume" }).click();
  await expect(page.getByText(/Draft ready/)).toHaveCount(2, { timeout: 60_000 });

  await page.getByRole("link", { name: /Referral request:/ }).click();
  await expect(page.getByRole("textbox", { name: "Text (Markdown)" })).toContainText(
    "Hi Sam Example,",
  );
  await expect(page.getByText("Mock text, not written by AI")).toBeVisible();
});
