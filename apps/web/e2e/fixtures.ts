import { expect, test as base, type Page } from "@playwright/test";

// Every journey fails on errors a user would hit: an uncaught exception in the page, a
// console error from the app, or a 5xx from the API. (Expected 4xx answers, e.g. a wrong
// password, are part of journeys; the browser logs those as "Failed to load resource", which is
// ignored here because the API status is checked separately.)
export const test = base.extend<{ errorGuard: void }>({
  errorGuard: [
    async ({ page }, use) => {
      const problems: string[] = [];
      page.on("pageerror", (err) => problems.push(`page error: ${err.message}`));
      page.on("console", (msg) => {
        if (msg.type() !== "error") return;
        const text = msg.text();
        if (/Failed to load resource: the server responded with a status of 4\d\d/.test(text)) return;
        problems.push(`console error: ${text}`);
      });
      page.on("response", (res) => {
        if (res.url().includes("/api/") && res.status() >= 500) {
          problems.push(`API ${res.status()}: ${res.request().method()} ${new URL(res.url()).pathname}`);
        }
      });
      await use();
      expect(problems, "the page showed errors").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect, type Page };
