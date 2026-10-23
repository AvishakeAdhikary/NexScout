import { expect, test, type Page } from "./fixtures";

// M8 acceptance journey: the assistant routes requests to the same tools as the screens and
// refuses to submit; an application gets a reminder that shows on the dashboard and as a
// notification; the tracker filters, bulk-changes and exports applications.

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
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Tracking");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname;
}

test("assistant, reminders, notifications, dashboard and tracker", async ({ page }) => {
  test.setTimeout(180_000);
  const caseBase = await registerWithCase(page, uniqueEmail("m8"));
  await expect(page.getByRole("heading", { name: "Needs you" })).toBeVisible();
  await expect(page.getByText("Nothing is waiting for you.")).toBeVisible();

  // Assistant: refuses to submit, starts a search through the same use case as the Jobs page.
  await page.goto(`${caseBase}/assistant`);
  const convo = page.getByRole("list", { name: "Conversation" });
  await page.getByRole("textbox", { name: "Message" }).fill("Please submit my application now");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(convo.getByText(/I never submit or send anything from chat/)).toBeVisible();
  await page.getByRole("button", { name: "Find jobs" }).click();
  await expect(convo.getByText(/Searching your enabled sources now/)).toBeVisible();
  await convo.getByRole("link", { name: "See results" }).last().click();
  const card = page.getByRole("article", { name: "Junior Data Engineer" });
  await expect(card).toBeVisible({ timeout: 30_000 });

  // Start an application (no documents yet) and add a reminder for today.
  await card.getByRole("link", { name: "Research and prepare" }).click();
  await page
    .getByRole("region", { name: "Apply" })
    .getByRole("button", { name: "Start an application" })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Junior Data Engineer" })).toBeVisible();
  const today = new Date();
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  await page.getByRole("textbox", { name: "Remind me to" }).fill("Ask Sam about the team");
  await page.getByLabel("On", { exact: true }).fill(iso);
  await page.getByRole("button", { name: "Add reminder" }).click();
  await expect(
    page.getByRole("region", { name: "Reminders" }).getByText("Ask Sam about the team"),
  ).toBeVisible();

  // The worker's sweep turns the due reminder into a notification.
  const bell = page.getByRole("button", { name: /^Notifications/ });
  await expect(bell).toHaveText(/Notifications \(\d+\)/, { timeout: 45_000 });
  await bell.click();
  await page
    .getByRole("region", { name: "Notifications" })
    .getByRole("button", { name: /Ask Sam about the team/ })
    .click();
  await expect(page.getByRole("heading", { level: 1, name: "Junior Data Engineer" })).toBeVisible();

  // Dashboard shows it under "Coming up".
  await page.goto(caseBase);
  await expect(
    page.getByRole("region", { name: "Coming up (30 days)" }).getByText("Ask Sam about the team"),
  ).toBeVisible();

  // Tracker: filter, bulk change, export.
  await page.goto(`${caseBase}/applications`);
  await page.getByRole("combobox", { name: "Status" }).selectOption("preparing");
  await expect(page.getByRole("link", { name: "Junior Data Engineer" })).toBeVisible();
  await page.getByRole("checkbox", { name: "Select all" }).check();
  await page.getByRole("combobox", { name: "Change selected to" }).selectOption("cancelled");
  await page.getByRole("button", { name: "Apply to selected" }).click();
  await expect(page.getByText("No applications match.")).toBeVisible();
  await page.getByRole("combobox", { name: "Status" }).selectOption("");
  await expect(page.getByRole("cell", { name: "Cancelled" })).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export CSV" }).click();
  expect((await download).suggestedFilename()).toBe("applications.csv");
});
