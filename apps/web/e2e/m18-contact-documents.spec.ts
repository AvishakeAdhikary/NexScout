import path from "node:path";

import { expect, test, type Page } from "./fixtures";

// v2.10: contact details are taken from the CV once (after the user confirms), used in the
// resume and the application form; an edited resume without a PDF gets one when the form is
// filled; documents can be deleted where they are listed. Synthetic persona and demo site only.

const PASSWORD = "correct horse battery staple";
const PERSONAS = path.resolve(__dirname, "../../../backend/tests/fixtures/personas");

async function registerWithCase(page: Page): Promise<string> {
  await page.goto("/register");
  await page.getByRole("textbox", { name: "Your name" }).fill("Rohan");
  await page
    .getByRole("textbox", { name: "Email" })
    .fill(`contact-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/cases$/);
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Job search");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname;
}

test("contact details from the CV fill the resume and the form; PDFs are made for you", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const base = await registerWithCase(page);
  await page.goto(`${base}/documents`);
  await page.locator('input[type="file"]').setInputFiles(path.join(PERSONAS, "rohan_cv.md"));
  await expect(page.getByText(/Found \d+ possible entries/)).toBeVisible({ timeout: 30_000 });

  // Suggested from the CV, saved only when the user says so.
  await page.goto(`${base}/profile`);
  const contact = page.getByRole("region", { name: "Contact details" });
  await expect(contact.getByText(/Found in rohan_cv\.md/)).toBeVisible();
  await contact.getByRole("button", { name: "Use these" }).click();
  await expect(contact.getByRole("textbox", { name: "Phone" })).toHaveValue("+91 00000 00000");
  await contact.getByRole("button", { name: "Save contact details" }).click();
  await expect(contact.getByText("Saved.")).toBeVisible();
  await expect(contact.getByText(/Found in rohan_cv\.md/)).toHaveCount(0);
  // Accept everything the CV gave, so the resume has content.
  for (const header of await page.getByRole("heading", { level: 3, name: /\(\d+\)$/ }).all()) {
    await header.locator("..").getByRole("button", { name: "Select all" }).click();
  }
  await page
    .getByRole("region", { name: "Selected entries" })
    .getByRole("button", { name: "Accept", exact: true })
    .click();
  await expect(page.getByText("Nothing to review.")).toBeVisible();

  // The drafted resume already has the contact line, and its PDF.
  await page.goto(`${base}/jobs`);
  await page.getByRole("button", { name: "Find opportunities" }).click();
  const card = page.getByRole("article", { name: "Junior Data Engineer" });
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.getByRole("link", { name: "Research and prepare" }).click();
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}$/);
  const jobUrl = page.url();
  await page.getByRole("button", { name: "Draft resume" }).click();
  await expect(page.getByText(/Draft ready/)).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Open it" }).click();
  await expect(page.getByText("Not ready to send")).toHaveCount(0);
  const editor = page.getByRole("textbox", { name: "Text (Markdown)" });
  await expect(editor).toHaveValue(/rohan\.example@example\.com/);
  // An edit makes a new version without a PDF, as a real user's edits do.
  await editor.fill((await editor.inputValue()) + "\n\nOpen to relocation within Europe.\n");
  await page.getByRole("button", { name: "Save as new version" }).click();
  await expect(page.getByText("Edited by you")).toBeVisible();

  await page.goto(jobUrl);
  const apply = page.getByRole("region", { name: "Apply" });
  await apply.getByRole("button", { name: "Start an application" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Junior Data Engineer" })).toBeVisible();
  await expect(page.getByText("No PDF yet")).toBeVisible();

  await page.getByRole("button", { name: "Fill in the form" }).click();
  await expect(page.getByText("NexScout needs you")).toBeVisible({ timeout: 90_000 });
  await page
    .getByRole("textbox", { name: /Your answer: why are you interested in this role/i })
    .fill("I enjoy building reliable data pipelines.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("PDF ready")).toBeVisible(); // made by the first attempt

  await page.getByRole("button", { name: "Fill in the form" }).click();
  const approval = page.getByRole("article", { name: /Submit your application to Northwind/ });
  await expect(approval).toBeVisible({ timeout: 90_000 });
  await expect(approval.getByText(/Full name \*: Rohan Example/)).toBeVisible();
  await expect(approval.getByText(/Phone: \+91 00000 00000/)).toBeVisible();
  await approval.getByRole("button", { name: "Reject" }).click(); // nothing is sent in this test

  // Documents can be deleted where they are listed.
  await page.goto(jobUrl);
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: /^Delete Resume/ }).click();
  await expect(page.getByRole("button", { name: /^Delete Resume/ })).toHaveCount(0);
});
