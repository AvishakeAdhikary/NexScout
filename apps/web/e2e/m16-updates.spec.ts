import { expect, test } from "./fixtures";

// M16: a newer release shows a banner (with the update steps) until dismissed for that version.
// E2E never calls GitHub (NEXSCOUT_UPDATE_CHECK=0), so the version answer is stubbed here.

const PASSWORD = "correct horse battery staple";

test("an available update is announced once per version", async ({ page }) => {
  await page.route("**/api/v1/version", (route) =>
    route.fulfill({
      json: {
        current: "2.2.0",
        latest: "2.3.0",
        update_available: true,
        url: "https://github.com/AvishakeAdhikary/NexScout/releases/tag/v2.3.0",
        checked_at: new Date().toISOString(),
      },
    }),
  );
  await page.goto("/register");
  await page.getByRole("textbox", { name: "Your name" }).fill("Update Example");
  await page.getByRole("textbox", { name: "Email" }).fill(`upd-${Date.now()}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/cases$/);

  const banner = page.getByRole("status").filter({ hasText: "NexScout 2.3.0 is available" });
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("Update NexScout");
  await expect(banner.getByRole("link", { name: "What's new" })).toHaveAttribute(
    "href",
    /releases\/tag\/v2\.3\.0$/,
  );
  await banner.getByRole("button", { name: "Dismiss" }).click();
  await expect(banner).toBeHidden();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByText("NexScout 2.3.0 is available")).toBeHidden(); // remembered
});
