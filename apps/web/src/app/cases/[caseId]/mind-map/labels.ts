import type { MindNodeOut, Section } from "@/lib/api/client";
import { SECTION_LABELS } from "@/lib/profile-schema";

// Provenance is always shown as text too, never by colour alone.
export const STATUS_STYLE: Record<string, { border: string; text: string }> = {
  candidate: { border: "border-foreground", text: "You" },
  section: { border: "border-muted-foreground/40", text: "Section" },
  organization: { border: "border-sky-500 border-dashed", text: "Grouping (derived)" },
  user_entered: { border: "border-emerald-600", text: "Entered by you" },
  extracted: { border: "border-blue-600", text: "From your document" },
  verified: { border: "border-emerald-800", text: "Verified" },
  inferred: { border: "border-amber-500 border-dashed", text: "Inferred, not confirmed" },
  external: { border: "border-purple-600", text: "From an outside source" },
};

export const EDGE_LABELS: Record<string, string> = {
  has_section: "",
  has_entry: "",
  at_organization: "same organization",
  followed_by: "then",
  mentions_skill: "mentions skill",
  part_of: "part of",
};

export function displayLabel(n: MindNodeOut): string {
  if (n.label_override) return n.label_override;
  if (n.kind === "section") return SECTION_LABELS[n.label as Section] ?? n.label;
  return n.label;
}
