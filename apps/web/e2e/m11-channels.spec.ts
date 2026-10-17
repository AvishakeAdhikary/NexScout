import { expect, test, type Page } from "@playwright/test";

// M11 journey: connect a notification channel (signed webhook), send a test, pause it, and
// decide an approval from the page a notification links to. Synthetic persona only; no real
// provider is contacted (the webhook points at a closed local port, so the test honestly fails).

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
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Channels check");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  return new URL(page.url()).pathname.split("/")[2];
}

test("connect a webhook channel, test it, pause it, and approve from a notification link", async ({
  page,
}) => {
  test.setTimeout(120_000);
  const caseId = await registerWithCase(page, uniqueEmail("m11"));

  await page.goto("/account");
  const section = page.getByRole("region", { name: "Notifications on your phone" });
  await section.getByRole("combobox", { name: "Add a channel" }).selectOption("webhook");
  await section.getByRole("textbox", { name: "Name" }).fill("My automation");
  await section.getByLabel("Address").fill("http://127.0.0.1:9/hook");
  await section.getByRole("button", { name: "Save channel" }).click();
  await expect(section.getByText("Signing secret (shown once):")).toBeVisible();

  const row = section.getByRole("listitem", { name: "My automation" });
  await expect(row.getByText("Connected")).toBeVisible();
  await row.getByRole("button", { name: "Send test" }).click();
  await expect(row.getByText(/^Test failed: Webhook unreachable/)).toBeVisible({ timeout: 30_000 });
  await row.getByRole("button", { name: "Pause" }).click();
  await expect(row.getByText("Paused", { exact: true })).toBeVisible();

  // An approval request; its notification links to /approve/<id>.
  const start = await page.request.post(`/api/v1/cases/${caseId}/runs`, {
    data: { kind: "system_check", params: { require_approval: true } },
    headers: { "X-CSRF-Token": (await page.context().cookies()).find((c) => c.name === "nexscout_csrf")!.value },
  });
  expect(start.status()).toBe(201);
  let approvalId = "";
  await expect
    .poll(
      async () => {
        const list = await (await page.request.get(`/api/v1/cases/${caseId}/approvals`)).json();
        approvalId = list[0]?.id ?? "";
        return approvalId;
      },
      { timeout: 60_000 },
    )
    .not.toBe("");
  await page.goto(`/approve/${approvalId}`);
  await expect(page.getByRole("heading", { name: "Your decision" })).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.reload();
  await expect(page.getByText("You approved this.")).toBeVisible({ timeout: 15_000 });
});
