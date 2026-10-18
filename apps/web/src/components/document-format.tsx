"use client";

import { useQuery } from "@tanstack/react-query";
import { Globe2 } from "lucide-react";

import { Label } from "@/components/ui/label";
import { generatedApi, researchApi } from "@/lib/api/client";

export interface FormatInfo {
  key: string;
  label: string;
  paper: string;
  reason?: string | null;
  notes: string[];
}

/** Shows which regional format a position's documents use, and lets the user override it. */
export function FormatPicker({
  caseId,
  opportunityId,
  value,
  onChange,
}: {
  caseId?: string;
  opportunityId?: string;
  value: string;
  onChange: (key: string) => void;
}) {
  const formats = useQuery({ queryKey: ["doc-formats"], queryFn: generatedApi.formats });
  const auto = useQuery({
    queryKey: ["doc-format", caseId, opportunityId],
    queryFn: () => researchApi.documentFormat(caseId!, opportunityId!),
    enabled: !!caseId && !!opportunityId,
  });
  const chosen: FormatInfo | undefined = value
    ? formats.data?.find((f) => f.key === value)
    : (auto.data ?? formats.data?.find((f) => f.key === "international"));
  const autoLabel = auto.data ? `Automatic: ${auto.data.label}` : "Automatic: International";

  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-muted/40 p-3 text-sm">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor="doc-format">Document format</Label>
          <select
            id="doc-format"
            className="h-8 rounded-lg border bg-background px-2 text-sm"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          >
            <option value="">{autoLabel}</option>
            {(formats.data ?? []).map((f) => (
              <option key={f.key} value={f.key}>{f.label}</option>
            ))}
          </select>
        </div>
        {chosen && (
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <Globe2 className="size-4" aria-hidden />
            {chosen.paper} paper · {value ? "chosen by you" : (auto.data?.reason ?? "location unknown")}
          </span>
        )}
      </div>
      {chosen && chosen.notes.length > 0 && (
        <details>
          <summary className="cursor-pointer text-xs">What this format means</summary>
          <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
            {chosen.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-muted-foreground">
            These are common conventions, not official rules. The posting&apos;s own instructions
            always win, and NexScout checks them separately.
          </p>
        </details>
      )}
    </div>
  );
}

type Check = { rule: string; ok: boolean; severity: string; source: string; detail: string };

/** The compliance checklist stored with a rendered version. */
export function ComplianceList({ compliance }: { compliance?: { status?: string; checks?: Check[] } }) {
  if (!compliance?.checks) return null;
  const icon = (c: Check) => (c.ok ? "✓" : c.severity === "blocking" ? "✗" : c.severity === "warning" ? "!" : "·");
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p className="font-medium">
        {compliance.status === "ok"
          ? "Meets the posting's requirements and the format's conventions."
          : compliance.status === "warnings"
            ? "Meets the posting's requirements; some conventions aren't met."
            : "Not ready: fix the items marked ✗ before applying."}
      </p>
      <ul className="flex flex-col gap-1">
        {(compliance.checks ?? []).map((c) => (
          <li key={`${c.rule}-${c.source}`} className="flex gap-2">
            <span
              aria-hidden
              className={`w-4 shrink-0 text-center font-mono ${c.ok ? "text-emerald-500" : c.severity === "blocking" ? "text-destructive" : "text-amber-500"}`}
            >
              {icon(c)}
            </span>
            <span>
              <span className="sr-only">{c.ok ? "Passed: " : "Not met: "}</span>
              {c.rule}{" "}
              <span className="text-xs text-muted-foreground">
                ({c.detail} {(c.source ?? "").startsWith("posting:") ? `From the posting: “${(c.source ?? "").slice(9).trim()}”` : (c.source ?? "").startsWith("convention:") ? `Convention: ${(c.source ?? "").slice(11).trim()}` : ""})
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
