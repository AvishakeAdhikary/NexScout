import path from "node:path";

import { expect, test, type Page } from "./fixtures";

// M21: AI skill suggestions chosen in one dialog, and the AI assistant (tool look-ups, refusing
// to submit, new conversation). The built-in mock model only: replies are labelled as mock text.

const PASSWORD = "correct horse battery staple";
const PERSONAS = path.resolve(__dirname, "../../../backend/tests/fixtures/personas");

async function registerWithCase(page: Page): Promise<string> {
  await page.goto("/register");
  await page.getByRole("textbox", { name: "Your name" }).fill("Rohan Example");
  await page
    .getByRole("textbox", { name: "Email" })
    .fill(`m21-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/cases$/);
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Job search");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname;
}

test("skills found with AI and the AI assistant", async ({ page }) => {
  test.setTimeout(240_000);
  const base = await registerWithCase(page);
  await page.goto(`${base}/documents`);
  await page.locator('input[type="file"]').setInputFiles(path.join(PERSONAS, "rohan_cv.md"));
  await expect(page.getByText(/Found \d+ possible entries/)).toBeVisible({ timeout: 30_000 });

  // Skills: suggested with quotes, chosen in one dialog.
  await page.goto(`${base}/profile`);
  await page.getByRole("button", { name: "Find my skills with AI" }).click();
  const dialog = page.getByRole("dialog", { name: /Skills found in your texts/ });
  await expect(dialog).toBeVisible({ timeout: 60_000 });
  await expect(dialog.getByText("Quantum Basket Weaving")).toHaveCount(0); // invented: dropped
  await dialog.getByRole("button", { name: "Select none" }).click();
  await dialog.getByRole("checkbox", { name: /MediaPipe/ }).check();
  await dialog.getByRole("button", { name: "Add 1 skill" }).click();
  await expect(page.getByText(/Added 1 skill\(s\)/)).toBeVisible();
  await expect(
    page.locator("#confirmed").getByRole("article", { name: "MediaPipe", exact: true }),
  ).toBeVisible();

  // The assistant with a model set up (the labelled mock), after a search.
  const csrf =
    (await page.context().cookies()).find((c) => c.name === "nexscout_csrf")?.value ?? "";
  const model = await page.request.post("/api/v1/providers", {
    data: { name: "Mock model", kind: "mock", model: "nexscout-mock-1", is_default: true },
    headers: { "X-CSRF-Token": csrf },
  });
  expect(model.status()).toBe(201);
  await page.goto(`${base}/jobs`);
  await page.getByRole("button", { name: "Find opportunities" }).click();
  await expect(page.getByRole("tab", { name: /^Not a fit right now \([1-9]/ })).toBeVisible({
    timeout: 30_000,
  });

  await page.goto(`${base}/assistant`);
  await expect(page.getByRole("checkbox", { name: /Use AI \(Mock model\)/ })).toBeChecked();
  const conversation = page.getByRole("list", { name: "Conversation" });
  await page.getByRole("textbox", { name: "Message" }).fill("Please submit my application now");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(
    conversation.getByText(/Mock reply, not written by AI.*never available/),
  ).toBeVisible({
    timeout: 60_000,
  });

  // A new conversation starts empty.
  await page.getByRole("button", { name: "New conversation" }).click();
  await expect(conversation.getByRole("listitem")).toHaveCount(0);
});
