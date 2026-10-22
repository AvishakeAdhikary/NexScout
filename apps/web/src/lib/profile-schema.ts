// UI field definitions per profile section. The backend validates every value
// (nexscout.domain.profile); this file only decides how to render the forms.

import type { Section } from "./api/client";

export type FieldType = "text" | "textarea" | "date" | "end-date" | "year" | "url" | "list";

export interface FieldDef {
  key: string;
  label: string;
  type: FieldType;
  required?: boolean;
  help?: string;
}

const dated: FieldDef[] = [
  { key: "start", label: "Start", type: "date" },
  { key: "end", label: "End", type: "end-date" },
];

const roleAtOrg: FieldDef[] = [
  { key: "organization", label: "Organization", type: "text", required: true },
  { key: "role", label: "Role", type: "text" },
  ...dated,
  { key: "description", label: "Description", type: "textarea" },
];

export const SECTION_FIELDS: Record<Section, FieldDef[]> = {
  summary: [{ key: "text", label: "Summary in your own words", type: "textarea", required: true }],
  education: [
    { key: "institution", label: "Institution", type: "text", required: true },
    { key: "degree", label: "Degree or qualification", type: "text" },
    { key: "field_of_study", label: "Field of study", type: "text" },
    ...dated,
    { key: "grade", label: "Grade", type: "text" },
    { key: "location", label: "Location", type: "text" },
    { key: "description", label: "Details", type: "textarea" },
  ],
  employment: [
    { key: "title", label: "Job title", type: "text", required: true },
    { key: "organization", label: "Organization", type: "text", required: true },
    { key: "employment_type", label: "Type (full-time, contract, ...)", type: "text" },
    ...dated,
    { key: "location", label: "Location", type: "text" },
    { key: "description", label: "What you did", type: "textarea" },
  ],
  research: [
    { key: "title", label: "Research topic or project", type: "text", required: true },
    { key: "organization", label: "Lab or institution", type: "text" },
    { key: "role", label: "Your role", type: "text" },
    ...dated,
    { key: "description", label: "Description", type: "textarea" },
  ],
  publication: [
    { key: "title", label: "Title", type: "text", required: true },
    { key: "authors", label: "Authors", type: "text" },
    { key: "venue", label: "Journal, conference, or venue", type: "text" },
    { key: "year", label: "Year", type: "year" },
    { key: "doi", label: "DOI", type: "text" },
    { key: "url", label: "Link", type: "url" },
  ],
  project: [
    { key: "name", label: "Project name", type: "text", required: true },
    { key: "role", label: "Your role", type: "text" },
    ...dated,
    { key: "url", label: "Link", type: "url" },
    { key: "technologies", label: "Technologies (comma-separated)", type: "list" },
    { key: "description", label: "Description", type: "textarea" },
  ],
  skill: [
    { key: "name", label: "Skill", type: "text", required: true },
    { key: "category", label: "Category", type: "text" },
    { key: "level", label: "Level", type: "text" },
  ],
  certification: [
    { key: "name", label: "Certification", type: "text", required: true },
    { key: "issuer", label: "Issuer", type: "text" },
    { key: "date", label: "Date", type: "date" },
    { key: "expires", label: "Expires", type: "date" },
    { key: "credential_id", label: "Credential ID", type: "text" },
    { key: "url", label: "Link", type: "url" },
  ],
  award: [
    { key: "name", label: "Award", type: "text", required: true },
    { key: "issuer", label: "Awarded by", type: "text" },
    { key: "date", label: "Date", type: "date" },
    { key: "description", label: "Details", type: "textarea" },
  ],
  patent: [
    { key: "title", label: "Title", type: "text", required: true },
    { key: "number", label: "Patent number", type: "text" },
    { key: "office", label: "Office", type: "text" },
    { key: "date", label: "Date", type: "date" },
    { key: "status", label: "Status", type: "text" },
  ],
  volunteer: roleAtOrg,
  leadership: roleAtOrg,
  membership: roleAtOrg,
  reference: [
    { key: "name", label: "Name", type: "text", required: true },
    { key: "relationship", label: "How they know you", type: "text" },
    { key: "organization", label: "Organization", type: "text" },
    { key: "contact", label: "Contact (kept private)", type: "text" },
  ],
  other: [
    { key: "title", label: "Title", type: "text", required: true },
    { key: "description", label: "Description", type: "textarea" },
  ],
};

export const SECTION_LABELS: Record<Section, string> = {
  summary: "Summary",
  education: "Education",
  employment: "Employment",
  research: "Research experience",
  publication: "Publications",
  project: "Projects",
  skill: "Skills",
  certification: "Certifications",
  award: "Awards & honors",
  patent: "Patents",
  volunteer: "Volunteering",
  leadership: "Leadership & activities",
  membership: "Professional affiliations",
  reference: "References",
  other: "Other",
};

export const SECTION_ORDER: Section[] = [
  "summary", "education", "employment", "research", "publication", "project", "skill",
  "certification", "award", "patent", "volunteer", "leadership", "membership", "reference",
  "other",
];

export const DATE_HELP = "YYYY, YYYY-MM, or YYYY-MM-DD";

/** Turn form values into the API payload: drop blanks, split lists. */
export function toPayload(section: Section, values: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const field of SECTION_FIELDS[section]) {
    const raw = (values[field.key] ?? "").trim();
    if (!raw) continue;
    out[field.key] =
      field.type === "list"
        ? raw.split(",").map((s) => s.trim()).filter(Boolean)
        : field.type === "end-date" && raw.toLowerCase() === "present"
          ? "present"
          : raw;
  }
  return out;
}

/** Sections an entry can be "part of" (roles and places), and sections that can link to them. */
export const LINK_TARGETS: ReadonlySet<Section> = new Set<Section>([
  "employment",
  "education",
  "research",
  "volunteer",
  "leadership",
  "membership",
]);
export const LINKABLE_SOURCES: ReadonlySet<Section> = new Set<Section>([
  "project",
  "certification",
  "award",
  "publication",
  "patent",
  "skill",
  "other",
]);

/** API data → form strings. */
export function toFormValues(data: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(data)) {
    out[k] = Array.isArray(v) ? v.join(", ") : v == null ? "" : String(v);
  }
  return out;
}

export const STATUS_LABELS: Record<string, string> = {
  user_entered: "Entered by you",
  extracted: "Found in your document",
  inferred: "Inferred, not confirmed",
  verified: "Verified",
  external: "From an outside source",
};
