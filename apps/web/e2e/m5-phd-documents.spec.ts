import { expect, test, type Page } from "./fixtures";

// M5 acceptance journey (PRODUCT_REQUIREMENTS journeys 3–4): research a (demo) PhD position
// with quoted sources, draft a statement of purpose, see placeholders and removed claims, edit,
// and create PDF and Word files. Mock model only; synthetic persona; demo pages are labelled.

const PASSWORD = "correct horse battery staple";
const NLP = "Doctoral Researcher in Trustworthy Natural Language Processing";

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
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("PhD search");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname;
}

test("research a position, draft a grounded SOP, edit it, and create files", async ({ page }) => {
  test.setTimeout(180_000);
  const caseBase = await registerWithCase(page, uniqueEmail("m5"));

  // One confirmed entry to draft from.
  await page.goto(`${caseBase}/profile`);
  await page.getByRole("combobox", { name: "Section" }).selectOption("skill");
  await page.locator("#add").getByRole("textbox", { name: /^Skill/ }).fill("Python");
  await page.getByRole("button", { name: "Add to profile" }).click();
  await expect(page.locator("#confirmed").getByRole("article", { name: "Python", exact: true })).toBeVisible();

  // Find (demo) positions, open one.
  await page.goto(`${caseBase}/phd`);
  await page.getByRole("button", { name: "Find opportunities" }).click();
  const card = page.getByRole("article", { name: NLP });
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.getByRole("link", { name: "Research and prepare" }).click();
  await expect(page.getByRole("heading", { level: 1, name: NLP })).toBeVisible();
  await expect(page.getByText(/This position and its pages are made-up examples/)).toBeVisible();
  await expect(page.getByText("Not researched yet.")).toBeVisible();

  // Research: findings quote their sources; disagreeing deadlines are flagged.
  await page.getByRole("button", { name: "Research this position" }).click();
  await expect(page.getByText("Research finished.")).toBeVisible({ timeout: 30_000 });
  const deadline = page.getByRole("listitem", { name: "Application deadline: 1 December 2026", exact: true });
  await expect(deadline.getByText("Sources disagree", { exact: true })).toBeVisible();
  await expect(deadline.getByText("in 3 sources")).toBeVisible();
  await expect(
    page.getByRole("listitem", { name: "Application deadline: 15 November 2026", exact: true }),
  ).toBeVisible();
  const prof = page.getByRole("listitem", { name: "Prof. Dr. Jana Beispiel", exact: true });
  await expect(prof.getByText(/Research interests: model calibration/)).toBeVisible();
  await prof.getByText("Show source").click();
  await expect(prof.locator("blockquote")).toContainText("The position is supervised by");

  // The position is in Germany, so documents follow German-speaking conventions (overridable).
  await expect(page.getByRole("combobox", { name: "Document format" })).toContainText(
    "Automatic: German-speaking",
  );
  // Draft an SOP (mock model, labelled).
  await page.getByRole("button", { name: "Draft statement of purpose" }).click();
  await expect(page.getByText(/Draft ready: \d+ placeholder/)).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Open it" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Statement of purpose/ })).toBeVisible();
  await expect(page.getByText("Mock text, not written by AI")).toBeVisible();
  await expect(page.getByText(/Format: .*German-speaking/)).toBeVisible();
  // The posting asks for at most 2 pages; that requirement is checked against the PDF.
  await expect(page.getByText("At most 2 page(s), as the posting asks")).toBeVisible();
  await expect(page.getByText("Not ready to send")).toBeVisible();
  // The mock's unsupported claim was removed and explained, not kept.
  await expect(page.getByText(/12 peer-reviewed papers/)).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Text (Markdown)" })).not.toContainText("12 peer-reviewed");
  await expect(page.getByRole("link", { name: "Download PDF" })).toBeVisible();

  // Edit: fill one placeholder, save version 2, then create its files.
  const editor = page.getByRole("textbox", { name: "Text (Markdown)" });
  const before = await editor.inputValue();
  const filled = before.replace(
    "[[PLACEHOLDER: your goals after the PhD]]",
    "After the PhD I want to work on evaluation methods.",
  );
  expect(filled).not.toBe(before);
  await editor.fill(filled);
  await page.getByRole("button", { name: "Save as new version" }).click();
  await expect(page.getByText(/version 2/).first()).toBeVisible();
  await expect(page.getByText("Edited by you")).toBeVisible();
  await page.getByRole("button", { name: "Create PDF and Word files" }).click();
  const pdfLink = page.getByRole("link", { name: "Download PDF" });
  await expect(pdfLink).toBeVisible({ timeout: 60_000 });
  const download = page.waitForEvent("download");
  await pdfLink.click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/v2\.pdf$/);
  await expect(page.getByRole("link", { name: "Download Word (.docx)" })).toBeVisible();

  // It is listed under Documents → Application materials.
  await page.goto(`${caseBase}/documents`);
  await expect(
    page.getByRole("region", { name: "Application materials" }).getByRole("link", { name: /Statement of purpose/ }),
  ).toBeVisible();
});
