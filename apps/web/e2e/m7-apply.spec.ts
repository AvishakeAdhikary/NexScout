import { expect, test, type Page } from "@playwright/test";

// M7 acceptance journey (PRODUCT_REQUIREMENTS journey 5): prepare a resume, start an
// application, let NexScout fill the demo site's form, answer the question it couldn't, approve
// the submission, and see it confirmed with evidence. Demo site and data are labelled.

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

test("fill a demo application form, approve, and get a confirmed submission", async ({ page }) => {
  test.setTimeout(240_000);
  const caseBase = await registerWithCase(page, uniqueEmail("m7"));

  await page.goto(`${caseBase}/profile`);
  await page.getByRole("combobox", { name: "Section" }).selectOption("skill");
  await page.locator("#add").getByRole("textbox", { name: /^Skill/ }).fill("Python");
  await page.getByRole("button", { name: "Add to profile" }).click();
  await expect(page.locator("#confirmed").getByRole("article", { name: "Python", exact: true })).toBeVisible();

  // Find a demo job and prepare a resume.
  await page.goto(`${caseBase}/jobs`);
  await page.getByRole("button", { name: "Find opportunities" }).click();
  const card = page.getByRole("article", { name: "Junior Data Engineer" });
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.getByRole("link", { name: "Research and prepare" }).click();
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/);
  const jobUrl = page.url();
  await page.getByRole("button", { name: "Draft resume" }).click();
  await expect(page.getByText(/Draft ready/)).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Open it" }).click();

  // The resume has a contact placeholder: fill it, then create the files.
  const editor = page.getByRole("textbox", { name: "Text (Markdown)" });
  const md = await editor.inputValue();
  await editor.fill(md.replace("[[PLACEHOLDER: contact details (email, phone, city)]]", "ada@example.com · Berlin"));
  await page.getByRole("button", { name: "Save as new version" }).click();
  await expect(page.getByText("Edited by you")).toBeVisible();
  await page.getByRole("button", { name: "Create PDF and Word files" }).click();
  await expect(page.getByRole("link", { name: "Download PDF" })).toBeVisible({ timeout: 60_000 });

  // Start the application from the job page.
  await page.goto(jobUrl);
  const apply = page.getByRole("region", { name: "Apply" });
  await expect(apply.getByRole("checkbox", { name: "Resume" })).toBeChecked();
  await apply.getByRole("button", { name: "Start an application" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Junior Data Engineer" })).toBeVisible();

  // First attempt: the form asks something NexScout can't answer, so it stops and asks.
  await page.getByRole("button", { name: "Fill in the form" }).click();
  await expect(page.getByText("NexScout needs you")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Why are you interested in this role\?/).first()).toBeVisible();
  await page.getByRole("textbox", { name: /Your answer: why are you interested in this role/i })
    .fill("I enjoy building reliable data pipelines.");
  await page.getByRole("button", { name: "Save", exact: true }).click();

  // Second attempt: filled, nothing sent; the approval shows every value.
  await page.getByRole("button", { name: "Fill in the form" }).click();
  const approval = page.getByRole("article", { name: /Submit your application to Northwind/ });
  await expect(approval).toBeVisible({ timeout: 60_000 });
  await expect(approval.getByText(/Full name \*: Ada Example/)).toBeVisible();
  await expect(approval.getByText(/I confirm that the information/).first()).toBeVisible();
  await expect(page.getByText("Waiting for your approval", { exact: true }).first()).toBeVisible();
  await approval.getByRole("button", { name: "Approve" }).click();

  await expect(page.getByText(/The site confirmed it \(reference FX-\d+\)/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("button", { name: "Fill in the form" })).toHaveCount(0);
  await page.getByText("Screenshot").first().click();
  await expect(page.getByRole("img", { name: /Page screenshot/ }).first()).toBeVisible();

  await page.goto(`${caseBase}/applications`);
  await expect(page.getByRole("cell", { name: "Submitted" })).toBeVisible();
});
