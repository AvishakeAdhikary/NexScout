// Main navigation for a candidate case (spec §16). `milestone` marks sections that are not
// built yet; their pages state that honestly instead of showing a fake screen.

export interface Section {
  slug: string; // "" = case dashboard
  label: string;
  description: string;
  milestone?: number;
}

export const SECTIONS: readonly Section[] = [
  { slug: "", label: "Dashboard", description: "Overview of this case and what needs you." },
  {
    slug: "profile",
    label: "My Profile",
    description: "Your achievements, with their sources. Imported facts wait for your review.",
    milestone: 2,
  },
  {
    slug: "mind-map",
    label: "Mind Map",
    description: "Your profile as an interactive map where every node links to evidence.",
    milestone: 3,
  },
  {
    slug: "phd",
    label: "PhD Opportunities",
    description: "Programs, funded positions, and supervisors, with sources.",
    milestone: 5,
  },
  {
    slug: "jobs",
    label: "Job Opportunities",
    description: "Deduplicated jobs with explained matches and experience gaps.",
    milestone: 6,
  },
  {
    slug: "applications",
    label: "Applications",
    description: "Track every application, deadline, and outcome.",
    milestone: 8,
  },
  {
    slug: "documents",
    label: "Documents",
    description: "Uploaded documents and generated, versioned application materials.",
    milestone: 2,
  },
  {
    slug: "relationships",
    label: "Relationships",
    description: "Affiliations, and whether you allow them to be used in applications.",
    milestone: 2,
  },
  {
    slug: "activity",
    label: "Agent Activity",
    description: "Live view of running workflows. Pause, resume, approve, or cancel.",
    milestone: 4,
  },
  {
    slug: "settings",
    label: "Settings",
    description: "AI providers (bring your own key), sources, and integrations.",
    milestone: 9,
  },
] as const;

export function findSection(slug: string): Section | undefined {
  return SECTIONS.find((s) => s.slug === slug);
}

/** Only allow same-site relative redirects (prevents open redirects via ?next=). */
export function safeNext(next: string | null | undefined, fallback = "/cases"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return fallback;
  }
  return next;
}
