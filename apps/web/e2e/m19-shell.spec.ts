import { expect, test, type Page } from "./fixtures";

// M19 (browser side): Home and "All cases" links, breadcrumbs on every case page, switching
// cases keeps the section, and Account → About & updates shows this server's version. The
// desktop-only parts (title bar, tray, bridge) are checked by the desktop app's --smoke run.

const PASSWORD = "correct horse battery staple";

async function register(page: Page): Promise<void> {
  await page.goto("/register");
  await page.getByRole("textbox", { name: "Your name" }).fill("Ada Example");
  await page
    .getByRole("textbox", { name: "Email" })
    .fill(`m19-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/cases$/);
}

async function createCase(page: Page, name: string): Promise<string> {
  await page.goto("/cases");
  await page.getByRole("textbox", { name: "Name", exact: true }).fill(name);
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname;
}

test("home, breadcrumbs, case switcher and about", async ({ page }) => {
  await register(page);
  const first = await createCase(page, "PhD search");
  const second = await createCase(page, "Job search");

  // Breadcrumbs: Cases › case › section.
  await page.goto(`${second}/documents`);
  const crumbs = page.getByRole("navigation", { name: "Breadcrumb" });
  await expect(crumbs.getByRole("link", { name: "Cases" })).toBeVisible();
  await expect(crumbs.getByRole("link", { name: "Job search" })).toBeVisible();
  await expect(crumbs.getByText("Documents")).toHaveAttribute("aria-current", "page");

  // Switching case keeps the section.
  await page.getByRole("combobox", { name: "Switch case" }).selectOption({ label: "PhD search" });
  await expect(page).toHaveURL(new RegExp(`${first}/documents$`));
  await expect(crumbs.getByRole("link", { name: "PhD search" })).toBeVisible();

  // Back to all cases, from the side panel and from the top bar.
  await page.getByRole("link", { name: "All cases" }).click();
  await expect(page).toHaveURL(/\/cases$/);
  await page.goto(`${first}/profile`);
  await page.getByRole("banner").getByRole("link", { name: "Home" }).click();
  await expect(page).toHaveURL(/\/cases$/);

  // About & updates in a browser: the server's version.
  await page.goto("/account");
  const about = page.getByRole("region", { name: "About & updates" });
  await expect(about.getByText(/NexScout \d+\.\d+\.\d+/)).toBeVisible();
});
