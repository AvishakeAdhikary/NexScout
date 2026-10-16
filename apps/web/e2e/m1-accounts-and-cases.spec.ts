import { expect, test, type Page } from "@playwright/test";

// M1 acceptance journey: register, create an isolated case, choose a career path,
// sign out/in, and confirm a second user cannot open the first user's case.

const PASSWORD = "correct horse battery staple";

function uniqueEmail(tag: string): string {
  return `${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

async function register(page: Page, email: string, name: string) {
  await page.goto("/register");
  await page.getByRole("textbox", { name: "Your name" }).fill(name);
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/cases$/);
  // The password must not linger in the (hidden, still-mounted) register form.
  const lingering = await page.locator('input[type="password"]').evaluateAll((els) =>
    els.map((e) => (e as HTMLInputElement).value).filter(Boolean),
  );
  expect(lingering).toEqual([]);
}

test("register, create a case, choose a path, and persist across sign-in", async ({ page }) => {
  const email = uniqueEmail("ada");
  await register(page, email, "Ada Example");
  await expect(page.getByRole("heading", { name: "Your cases" })).toBeVisible();
  await expect(page.getByText("You don't have any cases yet")).toBeVisible();

  await page.getByRole("textbox", { name: "Name", exact: true }).fill("PhD in machine learning");
  await page.getByRole("textbox", { name: "Description (optional)" }).fill("Funded programs in Europe");
  await page.getByRole("button", { name: "Create case" }).click();

  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "PhD in machine learning" })).toBeVisible();
  const caseUrl = page.url();

  await page.getByRole("radio", { name: "PhD & research" }).check();
  await expect(page.getByRole("radio", { name: "PhD & research" })).toBeChecked();
  await expect(page.getByText("Saving…")).toBeHidden();

  // Unbuilt sections say so honestly.
  await page.getByRole("link", { name: /Agent Activity/ }).first().click();
  await expect(page.getByRole("heading", { level: 1, name: "Agent Activity" })).toBeVisible();
  await expect(page.getByText(/planned for milestone 4/)).toBeVisible();

  // Sign out, then back in: the case and the chosen path persist.
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto(caseUrl);
  await expect(page).toHaveURL(/\/login\?next=/);
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(caseUrl);
  await expect(page.getByRole("radio", { name: "PhD & research" })).toBeChecked();
});

test("a second user cannot see or open another user's case", async ({ browser }) => {
  const ctxA = await browser.newContext();
  const pageA = await ctxA.newPage();
  await register(pageA, uniqueEmail("owner"), "Case Owner");
  await pageA.getByRole("textbox", { name: "Name", exact: true }).fill("Private search");
  await pageA.getByRole("button", { name: "Create case" }).click();
  await expect(pageA).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  const privateUrl = new URL(pageA.url()).pathname;

  const ctxB = await browser.newContext();
  const pageB = await ctxB.newPage();
  await register(pageB, uniqueEmail("intruder"), "Someone Else");
  await expect(pageB.getByText("Private search")).toHaveCount(0);

  await pageB.goto(privateUrl);
  await expect(pageB.getByText("Couldn't open this case")).toBeVisible();
  await expect(pageB.getByText("Case not found.")).toBeVisible();
  await expect(pageB.getByRole("heading", { name: "Private search" })).toHaveCount(0);

  await ctxA.close();
  await ctxB.close();
});

test("wrong password shows a clear error and no session", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("textbox", { name: "Email" }).fill(uniqueEmail("nobody"));
  await page.getByLabel("Password", { exact: true }).fill("definitely wrong password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Incorrect email or password.")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});
