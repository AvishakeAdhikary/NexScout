import path from "node:path";

import { expect, test, type Page } from "./fixtures";

// M2 acceptance journey: upload a CV, review extracted facts against their source, edit and
// accept, and find the data again from a fresh session. Synthetic persona only.

const PASSWORD = "correct horse battery staple";
const CV = path.resolve(__dirname, "../../../backend/tests/fixtures/personas/ada_example_cv.md");

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

test("upload a CV, review against the source, accept, and find it again", async ({
  page,
  browser,
}) => {
  const email = uniqueEmail("ada");
  const caseBase = await registerWithCase(page, email);

  // Upload
  await page.goto(`${caseBase}/documents`);
  await expect(page.getByRole("heading", { name: "Documents", level: 1 })).toBeVisible();
  await page.getByLabel("File").setInputFiles(CV);
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page.getByText(/Found \d+ possible entries/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("cell", { name: "ada_example_cv.md" })).toBeVisible();
  await page.getByRole("link", { name: "Review them now" }).click();

  // Review: everything is pending and shows where it came from.
  await expect(page.getByRole("heading", { name: "Needs your review" })).toBeVisible();
  const job = page.getByRole("article", { name: "Machine Learning Engineer at Examplecorp GmbH" });
  await expect(job).toBeVisible();
  await job.getByRole("button", { name: "Show source" }).click();
  await expect(job.locator("blockquote")).toContainText("Built evaluation pipelines");
  await expect(job.getByText("Found in your document")).toBeVisible();

  // Accept all employment entries.
  const employmentHeader = page.getByRole("heading", { name: /^Employment \(2\)$/ });
  await employmentHeader.locator("..").getByRole("button", { name: "Accept all 2" }).click();
  await expect(page.getByRole("heading", { name: /^Employment \(2\)$/ })).toHaveCount(0);

  // Edit one education entry, which also accepts it.
  const msc = page.getByRole("article", { name: /MSc, Computer Science at Technical University/ });
  await msc.getByRole("button", { name: "Edit, then accept" }).click();
  await msc.getByRole("textbox", { name: "Grade" }).fill("1.3");
  await msc.getByRole("button", { name: "Save and accept" }).click();
  await expect(
    page.locator("#confirmed").getByRole("article", { name: /MSc, Computer Science/ }),
  ).toBeVisible();
  await expect(
    page.locator("#confirmed").getByRole("article", { name: /MSc, Computer Science/ }).getByText("Edited by you"),
  ).toBeVisible();

  // Reject a skill.
  const docker = page.locator("#review").getByRole("article", { name: "Docker", exact: true });
  await docker.getByRole("button", { name: "Reject" }).click();
  await expect(page.locator("#review").getByRole("article", { name: "Docker", exact: true })).toHaveCount(0);

  // Add an entry by hand.
  await page.getByRole("combobox", { name: "Section" }).selectOption("skill");
  await page.locator("#add").getByRole("textbox", { name: /^Skill/ }).fill("Rust");
  await page.getByRole("button", { name: "Add to profile" }).click();
  await expect(page.locator("#confirmed").getByRole("article", { name: "Rust", exact: true })).toBeVisible();

  // Links and preferences.
  await page.getByRole("textbox", { name: "Add a link" }).fill("github.com/ada-example");
  await page.getByRole("button", { name: "Add link" }).click();
  await expect(page.getByRole("link", { name: "https://github.com/ada-example" })).toBeVisible();
  const lookIn = page.getByRole("textbox", { name: "Countries to look in" });
  await lookIn.fill("Germany");
  await lookIn.press("Enter");
  await lookIn.fill("Netherl");
  await page.getByRole("button", { name: "Netherlands", exact: true }).click();
  await page.getByRole("button", { name: "Save preferences" }).click();
  await expect(page.locator("#preferences").getByRole("status")).toHaveText("Saved.");

  // Relationships: permissions are off by default.
  await page.goto(`${caseBase}/relationships`);
  await page.getByRole("textbox", { name: "Organization *" }).fill("University of Sampleford");
  await page.getByRole("button", { name: "Add relationship" }).click();
  const row = page.getByRole("row", { name: /University of Sampleford/ });
  await expect(row).toBeVisible();
  await expect(row.getByRole("checkbox", { name: "May suggest a referral request" })).not.toBeChecked();

  // A fresh session (new browser context) sees the same confirmed profile.
  const ctx = await browser.newContext();
  const again = await ctx.newPage();
  await again.goto("/login");
  await again.getByRole("textbox", { name: "Email" }).fill(email);
  await again.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await again.getByRole("button", { name: "Sign in" }).click();
  await expect(again).toHaveURL(/\/cases$/);
  await again.goto(`${caseBase}/profile`);
  const confirmed = again.locator("#confirmed");
  await expect(confirmed.getByRole("article", { name: "Machine Learning Engineer at Examplecorp GmbH" })).toBeVisible();
  await expect(confirmed.getByRole("article", { name: "Rust", exact: true })).toBeVisible();
  const chosen = again.getByRole("list", { name: "Countries to look in: chosen" });
  await expect(chosen.getByRole("listitem")).toHaveText(["Germany", "Netherlands"]);

  // Export works and contains the data.
  const exported = await again.request.get("/api/v1/me/export");
  expect(exported.status()).toBe(200);
  expect(exported.headers()["content-type"]).toBe("application/zip");
  await ctx.close();

  // Another user can't see any of it.
  const other = await browser.newContext();
  const intruder = await other.newPage();
  await registerWithCase(intruder, uniqueEmail("intruder"));
  await intruder.goto(`${caseBase}/profile`);
  await expect(intruder.getByText("Case not found.").first()).toBeVisible();
  await expect(intruder.getByText("Examplecorp")).toHaveCount(0);
  await other.close();
});
