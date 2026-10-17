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
  },
  {
    slug: "mind-map",
    label: "Mind Map",
    description: "Your profile as an interactive map where every node links to evidence.",
  },
  {
    slug: "phd",
    label: "PhD Opportunities",
    description: "Programs, funded positions, and supervisors, with sources.",
  },
  {
    slug: "jobs",
    label: "Job Opportunities",
    description: "Deduplicated jobs with explained matches and experience gaps.",
  },
  {
    slug: "applications",
    label: "Applications",
    description: "Track every application, deadline, and outcome.",
  },
  {
    slug: "documents",
    label: "Documents",
    description: "Uploaded documents and generated, versioned application materials.",
  },
  {
    slug: "relationships",
    label: "Relationships",
    description: "Affiliations, and whether you allow them to be used in applications.",
  },
  {
    slug: "activity",
    label: "Agent Activity",
    description: "Live view of running workflows. Pause, resume, approve, or cancel.",
  },
  {
    slug: "settings",
    label: "Settings",
    description: "AI providers (bring your own key), sources, and integrations.",
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
