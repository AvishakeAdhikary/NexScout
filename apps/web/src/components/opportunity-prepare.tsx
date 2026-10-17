"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { FormatPicker } from "@/components/document-format";
import { ErrorAlert } from "@/components/error-alert";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { statusLabel } from "@/lib/application-status";
import {
  applicationsApi,
  generatedApi,
  researchApi,
  type FindingOut,
  type ResearchSourceOut,
} from "@/lib/api/client";
import { useCaseEvents, useRun } from "@/lib/live";

const GROUPS: { title: string; kinds: string[] }[] = [
  { title: "Deadlines", kinds: ["deadline"] },
  { title: "Requirements", kinds: ["degree", "language_test"] },
  { title: "Documents to submit", kinds: ["document_required"] },
  { title: "Funding", kinds: ["funding"] },
  { title: "People", kinds: ["supervisor"] },
  { title: "Other", kinds: ["other"] },
];
const ORIGIN: Record<string, string> = { listing: "Listing", demo: "Demo page", web: "Web page" };
const FINISHED = new Set(["succeeded", "failed", "cancelled"]);

function SourceRow({ s }: { s: ResearchSourceOut }) {
  return (
    <li className="text-sm">
      <span className="font-medium">{s.title ?? s.url}</span>{" "}
      <Badge variant="outline">{ORIGIN[s.origin] ?? s.origin}</Badge>{" "}
      {s.status !== "ok" && <Badge variant="destructive">{s.status}</Badge>}{" "}
      {s.is_stale && <Badge variant="outline">Older than 30 days</Badge>}
      <div className="text-xs text-muted-foreground">
        Checked {new Date(s.retrieved_at).toLocaleDateString()}
        {s.origin !== "listing" && (
          <>
            {" · "}
            <a className="underline" href={s.final_url ?? s.url} target="_blank"
              rel="noopener noreferrer nofollow">
              open
            </a>
          </>
        )}
        {s.error && <> · {s.error}</>}
      </div>
    </li>
  );
}

function FindingGroup({
  rows,
  sources,
}: {
  rows: FindingOut[];
  sources: Map<string, ResearchSourceOut>;
}) {
  // Rows share kind and summary: the same statement, seen in one or more sources.
  const f = rows[0];
  const v = f.value as { research_interests?: string[]; profile_url?: string | null };
  const conflict = rows.find((r) => r.status === "conflict");
  return (
    <li className="rounded-md border p-2 text-sm" aria-label={f.summary}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{f.summary}</span>
        {conflict && <Badge variant="destructive">Sources disagree</Badge>}
        <Badge variant="outline">{f.confidence} confidence</Badge>
        {rows.length > 1 && (
          <span className="text-xs text-muted-foreground">in {rows.length} sources</span>
        )}
      </div>
      {v.research_interests && v.research_interests.length > 0 && (
        <p className="text-xs">Research interests: {v.research_interests.join(", ")}</p>
      )}
      {v.profile_url && (
        <a className="text-xs underline" href={v.profile_url} target="_blank"
          rel="noopener noreferrer nofollow">
          Profile page
        </a>
      )}
      {conflict?.note && <p className="text-xs text-destructive">{conflict.note}</p>}
      <details className="mt-1">
        <summary className="cursor-pointer text-xs">Show source{rows.length > 1 ? "s" : ""}</summary>
        {rows.map((r) => {
          const src = sources.get(r.source_id);
          return (
            <div key={r.id} className="mt-1">
              <blockquote className="border-l-2 pl-2 text-xs italic">{r.quote}</blockquote>
              <p className="text-xs text-muted-foreground">
                From: {src?.title ?? src?.url ?? "unknown"} ({ORIGIN[src?.origin ?? ""] ?? "source"})
              </p>
            </div>
          );
        })}
      </details>
    </li>
  );
}

function groupFindings(rows: FindingOut[]): FindingOut[][] {
  const groups = new Map<string, FindingOut[]>();
  for (const r of rows) {
    const key = `${r.kind}|${r.summary}`;
    groups.set(key, [...(groups.get(key) ?? []), r]);
  }
  return [...groups.values()];
}

function DraftStatus({ runId, caseId }: { runId: string; caseId: string }) {
  const run = useRun(runId);
  const status = run.data?.run.status;
  const result = run.data?.run.result as
    | { status?: string; document_id?: string; placeholders?: number; removed?: number; message?: string }
    | null
    | undefined;
  if (status === "waiting_approval")
    return (
      <p role="status" className="text-sm">
        Waiting for your permission to send entries to the model.{" "}
        <Link className="underline" href={`/cases/${caseId}/activity`}>Review the request</Link>
      </p>
    );
  if (status === "failed")
    return <p role="alert" className="text-sm text-destructive">Couldn&apos;t draft: {run.data?.run.error}</p>;
  if (status === "succeeded" && result?.document_id)
    return (
      <p role="status" className="text-sm">
        Draft ready: {result.placeholders ?? 0} placeholder(s) to fill
        {result.removed ? `, ${result.removed} unsupported sentence(s) removed` : ""}.{" "}
        <Link className="underline" href={`/cases/${caseId}/documents/generated/${result.document_id}`}>
          Open it
        </Link>
      </p>
    );
  if (status === "succeeded") return <p role="status" className="text-sm">{result?.message ?? "Finished."}</p>;
  return <p role="status" className="text-sm">Drafting…</p>;
}

const PHD_TYPES = ["sop", "research_proposal", "academic_cv", "inquiry_email"];
const JOB_TYPES = ["resume", "cover_letter", "referral_request"];

function Referrals({
  caseId,
  opportunityId,
  value,
  onChange,
}: {
  caseId: string;
  opportunityId: string;
  value: string;
  onChange: (id: string) => void;
}) {
  const refs = useQuery({
    queryKey: ["referrals", caseId, opportunityId],
    queryFn: () => researchApi.referrals(caseId, opportunityId),
  });
  if (!refs.data) return <ErrorAlert error={refs.error} />;
  const { suggestions, not_permitted } = refs.data;
  return (
    <section aria-labelledby="ref-heading" className="flex flex-col gap-2">
      <h3 id="ref-heading" className="font-medium">People who could refer you</h3>
      {suggestions.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No one you allowed for referrals works at this organization.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {suggestions.map((s) => (
            <li key={s.affiliation_id} className="text-sm">
              <label className="flex items-start gap-2">
                <input
                  type="radio"
                  name="referral"
                  value={s.affiliation_id}
                  checked={value === s.affiliation_id}
                  onChange={() => onChange(s.affiliation_id)}
                />
                <span>
                  <span className="font-medium">{s.person_name}</span>
                  {s.role ? `, ${s.role}` : ""}
                  <span className="block text-xs text-muted-foreground">{s.reason}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      {not_permitted > 0 && (
        <p className="text-xs text-muted-foreground">
          {not_permitted} other relationship(s) at this organization aren&apos;t allowed for
          referrals. You can change that in{" "}
          <Link className="underline" href={`/cases/${caseId}/relationships`}>Relationships</Link>.
        </p>
      )}
    </section>
  );
}

function StartApplication({ caseId, opportunityId }: { caseId: string; opportunityId: string }) {
  const router = useRouter();
  const apps = useQuery({ queryKey: ["applications", caseId], queryFn: () => applicationsApi.list(caseId) });
  const docs = useQuery({ queryKey: ["generated", caseId], queryFn: () => generatedApi.list(caseId) });
  const [chosen, setChosen] = useState<string[] | null>(null);
  const create = useMutation({
    mutationFn: (ids: string[]) => applicationsApi.create(caseId, opportunityId, ids),
    onSuccess: (a) => router.push(`/cases/${caseId}/applications/${a.id}`),
  });
  const existing = apps.data?.find((a) => a.opportunity_id === opportunityId);
  const usable = (docs.data ?? []).filter(
    (d) => d.opportunity_id === opportunityId || ["resume", "academic_cv"].includes(d.doc_type),
  );
  const selected = chosen ?? usable.map((d) => d.id);
  return (
    <section aria-labelledby="apply-heading" className="flex flex-col gap-2 rounded-lg border p-4">
      <h2 id="apply-heading" className="text-xl font-semibold">Apply</h2>
      {existing ? (
        <p className="text-sm">
          Application: {statusLabel(existing.status)}.{" "}
          <Link className="underline" href={`/cases/${caseId}/applications/${existing.id}`}>Open it</Link>
        </p>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            Choose the documents to send. NexScout fills in the form and asks you before
            submitting anything.
          </p>
          {usable.length === 0 && (
            <p className="text-sm">Prepare a resume or CV first (above, or under Documents).</p>
          )}
          {usable.map((d) => (
            <label key={d.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={selected.includes(d.id)}
                onChange={(e) =>
                  setChosen(e.target.checked ? [...selected, d.id] : selected.filter((x) => x !== d.id))
                }
              />
              {d.title}
            </label>
          ))}
          <Button className="self-start" onClick={() => create.mutate(selected)} disabled={create.isPending}>
            Start an application
          </Button>
          <ErrorAlert error={create.error ?? apps.error} />
        </>
      )}
    </section>
  );
}

export function OpportunityPrepare({ academic }: { academic: boolean }) {
  const { caseId, opportunityId } = useParams<{ caseId: string; opportunityId: string }>();
  const queryClient = useQueryClient();
  useCaseEvents(caseId);
  const opp = useQuery({
    queryKey: ["opportunity", caseId, opportunityId],
    queryFn: () => researchApi.opportunity(caseId, opportunityId),
  });
  const research = useQuery({
    queryKey: ["research", caseId, opportunityId],
    queryFn: () => researchApi.get(caseId, opportunityId),
  });
  const docs = useQuery({
    queryKey: ["generated", caseId, opportunityId],
    queryFn: () => generatedApi.list(caseId, opportunityId),
  });
  const types = useQuery({ queryKey: ["doc-types"], queryFn: generatedApi.types });

  const start = useMutation({ mutationFn: () => researchApi.start(caseId, opportunityId) });
  const run = useRun(start.data?.run_id);
  const runStatus = run.data?.run.status;
  const researching = start.isPending || (!!start.data && !FINISHED.has(runStatus ?? ""));
  useEffect(() => {
    if (runStatus === "succeeded")
      queryClient.invalidateQueries({ queryKey: ["research", caseId, opportunityId] });
  }, [runStatus, caseId, opportunityId, queryClient]);

  const [drafts, setDrafts] = useState<string[]>([]);
  const [supervisor, setSupervisor] = useState("");
  const [referral, setReferral] = useState("");
  const [format, setFormat] = useState("");
  const draft = useMutation({
    mutationFn: (docType: string) =>
      generatedApi.draft(caseId, {
        doc_type: docType,
        opportunity_id: opportunityId, // documents follow this position's location format
        format: format || null,
        supervisor_finding_id: docType === "inquiry_email" ? supervisor || null : null,
        affiliation_id: docType === "referral_request" ? referral || null : null,
      }),
    onSuccess: (r) => setDrafts((d) => [r.run_id, ...d]),
  });

  const sources = new Map((research.data?.sources ?? []).map((s) => [s.id, s]));
  const findings = research.data?.findings ?? [];
  const supervisors = findings.filter((f) => f.kind === "supervisor");
  const wanted = academic ? PHD_TYPES : JOB_TYPES;
  const docTypes = (types.data ?? []).filter((t) => wanted.includes(t.doc_type));
  const needs = (docType: string): string | null =>
    docType === "inquiry_email" && !supervisor
      ? "Research the position and choose a person first"
      : docType === "referral_request" && !referral
        ? "Choose someone who could refer you first"
        : null;
  const o = opp.data;

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <Link className="text-sm underline" href={`/cases/${caseId}/${academic ? "phd" : "jobs"}`}>
        ← {academic ? "PhD opportunities" : "Job opportunities"}
      </Link>
      <ErrorAlert error={opp.error} />
      {o && (
        <header>
          <h1 className="text-2xl font-semibold">{o.title}</h1>
          <p className="text-muted-foreground">{o.organization_name}</p>
          {o.is_demo_data && (
            <Alert className="mt-3">
              <AlertTitle>Demo data</AlertTitle>
              <AlertDescription>
                This position and its pages are made-up examples for trying NexScout out.
                <strong> They are not real.</strong>
              </AlertDescription>
            </Alert>
          )}
        </header>
      )}

      <section aria-labelledby="research-heading" className="flex flex-col gap-3">
        <h2 id="research-heading" className="text-xl font-semibold">Requirements and people</h2>
        <p className="text-sm text-muted-foreground">
          NexScout reads the listing and the pages it links to, and notes what they say, quoting
          each source. It doesn&apos;t guess: if a page doesn&apos;t say something, it isn&apos;t
          listed. Always confirm on the official page before you apply.
        </p>
        <Button className="self-start" onClick={() => start.mutate()} disabled={researching}>
          {researching ? "Researching…" : findings.length ? "Research again" : "Research this position"}
        </Button>
        <div aria-live="polite">
          {runStatus === "failed" && (
            <p role="alert" className="text-sm text-destructive">Research failed: {run.data?.run.error}</p>
          )}
          {runStatus === "succeeded" && (
            <p role="status" className="text-sm">Research finished.</p>
          )}
        </div>
        <ErrorAlert error={start.error ?? research.error} />
        {research.data && research.data.sources.length === 0 && (
          <p className="text-sm">Not researched yet.</p>
        )}
        {GROUPS.map((g) => {
          const rows = findings.filter((f) => g.kinds.includes(f.kind));
          if (rows.length === 0) return null;
          return (
            <div key={g.title}>
              <h3 className="font-medium">{g.title}</h3>
              <ul className="mt-1 flex flex-col gap-2">
                {groupFindings(rows).map((group) => (
                  <FindingGroup key={group[0].id} rows={group} sources={sources} />
                ))}
              </ul>
            </div>
          );
        })}
        {research.data && research.data.sources.length > 0 && (
          <details>
            <summary className="cursor-pointer font-medium">
              Sources ({research.data.sources.length})
            </summary>
            <ul className="mt-2 flex flex-col gap-2">
              {research.data.sources.map((s) => (
                <SourceRow key={s.id} s={s} />
              ))}
            </ul>
          </details>
        )}
      </section>

      <section aria-labelledby="prepare-heading" className="flex flex-col gap-3 rounded-lg border p-4">
        <h2 id="prepare-heading" className="text-xl font-semibold">Prepare documents</h2>
        <p className="text-sm text-muted-foreground">
          Drafts use only your confirmed, non-private profile entries and this position&apos;s
          research. Every claim is checked; anything missing becomes a highlighted placeholder
          for you to fill. Nothing is sent to anyone.
        </p>
        <FormatPicker caseId={caseId} opportunityId={opportunityId} value={format} onChange={setFormat} />
        {!academic && (
          <Referrals caseId={caseId} opportunityId={opportunityId} value={referral}
            onChange={setReferral} />
        )}
        {academic && supervisors.length > 0 && (
          <div className="flex flex-col gap-1">
            <Label htmlFor="sup">Inquiry email to</Label>
            <select id="sup" className="h-8 max-w-sm rounded-lg border bg-background px-2 text-sm"
              value={supervisor} onChange={(e) => setSupervisor(e.target.value)}>
              <option value="">Choose a person</option>
              {supervisors.map((s) => (
                <option key={s.id} value={s.id}>{s.summary}</option>
              ))}
            </select>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          {docTypes.map((t) => (
            <Button
              key={t.doc_type}
              variant="outline"
              disabled={draft.isPending || needs(t.doc_type) !== null}
              title={needs(t.doc_type) ?? undefined}
              onClick={() => draft.mutate(t.doc_type)}
            >
              Draft {t.label.charAt(0).toLowerCase() + t.label.slice(1)}
            </Button>
          ))}
        </div>
        <ErrorAlert error={draft.error} />
        <div aria-live="polite" className="flex flex-col gap-1">
          {drafts.map((id) => (
            <DraftStatus key={id} runId={id} caseId={caseId} />
          ))}
        </div>
        {docs.data && docs.data.length > 0 && (
          <>
            <h3 className="font-medium">Documents for this position</h3>
            <ul className="flex flex-col gap-1 text-sm">
              {docs.data.map((d) => (
                <li key={d.id}>
                  <Link className="underline" href={`/cases/${caseId}/documents/generated/${d.id}`}>
                    {d.title}
                  </Link>{" "}
                  <span className="text-muted-foreground">
                    v{d.current_version} · {d.latest.placeholders.length} placeholder(s)
                  </span>
                  {d.latest.is_mock && <> <Badge variant="destructive">Mock text</Badge></>}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
      <StartApplication caseId={caseId} opportunityId={opportunityId} />
    </div>
  );
}
