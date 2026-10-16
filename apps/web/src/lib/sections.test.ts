import { describe, expect, it } from "vitest";

import { findSection, safeNext, SECTIONS } from "./sections";

describe("safeNext (open-redirect guard)", () => {
  it.each([
    ["/cases/123", "/cases/123"],
    [null, "/cases"],
    ["", "/cases"],
    ["https://evil.example", "/cases"],
    ["//evil.example", "/cases"],
    ["/\\evil.example", "/cases"], // browsers treat "/\" like "//"
    ["javascript:alert(1)", "/cases"],
  ])("%s -> %s", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });
});

describe("sections", () => {
  it("has unique slugs and a dashboard", () => {
    const slugs = SECTIONS.map((s) => s.slug);
    expect(new Set(slugs).size).toBe(slugs.length);
    expect(findSection("")?.label).toBe("Dashboard");
  });

  it("marks every unbuilt section with a milestone", () => {
    const built = new Set(["", "profile", "documents", "relationships", "mind-map", "phd", "jobs"]);
    for (const s of SECTIONS.filter((x) => !built.has(x.slug))) {
      expect(s.milestone, s.slug).toBeGreaterThan(0);
    }
    for (const slug of built) expect(findSection(slug)?.milestone, slug).toBeUndefined();
  });
});
