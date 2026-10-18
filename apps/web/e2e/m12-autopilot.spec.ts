import { expect, test, type Page } from "./fixtures";

// M12 journey: turn the autopilot on (consent shown word for word), run it against the labelled
// demo sources, answer the question it asks instead of guessing, see the saved answer, then stop
// everything. Synthetic persona only.

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
  await page.getByRole("textbox", { name: "Name", exact: true }).fill("Autopilot check");
  await page.getByRole("button", { name: "Create case" }).click();
  await expect(page).toHaveURL(/\/cases\/[0-9a-f-]{36}$/);
  const caseId = new URL(page.url()).pathname.split("/")[2];
  const csrf = (await page.context().cookies()).find((c) => c.name === "nexscout_csrf")!.value;
  const fact = await page.request.post(`/api/v1/cases/${caseId}/facts`, {
    data: { section: "skill", data: { name: "Python" } },
    headers: { "X-CSRF-Token": csrf },
  });
  expect(fact.status()).toBe(201);
  return new URL(page.url()).pathname;
}

test("autopilot: consented settings, a question instead of a guess, saved answer, stop", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const caseBase = await registerWithCase(page, uniqueEmail("m12"));

  await page.goto(`${caseBase}/autopilot`);
  await expect(page.getByRole("heading", { name: "Autopilot", level: 1 })).toBeVisible();
  await expect(page.getByText("Off", { exact: true })).toBeVisible();
  const form = page.getByRole("form", { name: "Autopilot settings" });
  await expect(form.getByText(/I allow NexScout to submit applications for me/)).toBeVisible();
  await form.getByRole("checkbox", { name: "Autopilot on" }).check();
  await form.getByRole("spinbutton", { name: "Minimum fit (0–100)" }).fill("0");
  await form.getByRole("spinbutton", { name: "New positions per run" }).fill("1");
  await form.getByRole("checkbox", { name: "Jobs", exact: true }).check();
  await form.getByRole("checkbox", { name: "Resume", exact: true }).check();
  await form.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText("Settings saved.")).toBeVisible();
  await expect(page.getByText("On", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Run now" }).click();
  // The worker researches, writes the resume, and then asks for the contact details it
  // doesn't have (a placeholder), rather than inventing them.
  const questions = page.getByRole("region", { name: "Questions waiting for you" });
  await expect(questions).toBeVisible({ timeout: 120_000 });
  await expect(questions.getByText(/NexScout needs: contact details/)).toBeVisible();
  await questions.getByRole("textbox").first().fill("ada@example.com · London");
  await questions.getByRole("button", { name: "Answer" }).first().click();
  const saved = page.getByRole("region", { name: "Your saved answers" });
  await expect(saved.getByText("ada@example.com · London")).toBeVisible({ timeout: 15_000 });

  const work = page.getByRole("region", { name: "What the autopilot is working on" });
  await expect(work.getByRole("listitem")).toHaveCount(1);

  await page.getByRole("button", { name: "Stop everything" }).click();
  await expect(page.getByText(/^Stopped\. \d+ task\(s\) cancelled\./)).toBeVisible();
  await expect(page.getByText("Off", { exact: true })).toBeVisible({ timeout: 15_000 });
});
