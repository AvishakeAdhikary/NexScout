"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  opportunitiesApi,
  type OpportunityOut,
  type SyncSummaryOut,
} from "@/lib/api/client";
import { useCase } from "@/lib/hooks";
import { useCaseEvents, useRun } from "@/lib/live";

const SEVERITY_TEXT: Record<string, string> = {
  blocker: "Not a fit",
  gap: "Gap",
  info: "Note",
};

function where(o: OpportunityOut): string {
  const d = o.data as Record<string, unknown>;
  const parts = [d.location_city, d.location_country].filter(Boolean).join(", ");
  const remote = d.remote && d.remote !== "unknown" ? ` · ${String(d.remote)}` : "";
  return (parts || "Location not stated") + remote;
}

function OpportunityCard({ opp, caseId }: { opp: OpportunityOut; caseId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const d = opp.data as Record<string, unknown>;
  const setStatus = useMutation({
    mutationFn: (status: string) => opportunitiesApi.setStatus(caseId, opp.id, status, opp.match_version),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["opportunities", caseId] }),
  });
  const report = useMutation({
    mutationFn: (note: string) => opportunitiesApi.report(caseId, opp.id, note),
  });

  return (
    <article aria-labelledby={`opp-${opp.id}`} className="rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 id={`opp-${opp.id}`} className="font-medium">
            {opp.title}
          </h3>
          <p className="text-sm text-muted-foreground">
            {opp.organization_name} · {where(opp)}
          </p>
        </div>
        <div className="text-right">
          <p className="text-sm font-semibold" aria-label={`Estimated fit ${opp.score} out of 100`}>
            Fit estimate: {opp.score}/100
          </p>
          <div className="flex flex-wrap justify-end gap-1">
            {opp.is_demo_data && <Badge variant="outline">Demo data</Badge>}
            {opp.match_status !== "new" && <Badge variant="secondary">{opp.match_status}</Badge>}
            {opp.status === "closed" && <Badge variant="outline">Closed</Badge>}
          </div>
        </div>
      </div>
      {typeof d.closes_at === "string" && (
        <p className="mt-1 text-sm">Deadline: {new Date(d.closes_at).toLocaleDateString()}</p>
      )}
      {opp.gaps.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1 text-sm">
          {opp.gaps.map((g) => (
            <li key={g.code}>
              <span className="font-medium">{SEVERITY_TEXT[g.severity] ?? g.severity}:</span>{" "}
              {g.message}
            </li>
          ))}
        </ul>
      )}
      <details className="mt-2 text-sm" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary className="cursor-pointer">Why this estimate?</summary>
        <ul className="mt-1 flex flex-col gap-1">
          {opp.factors.map((f) => (
            <li key={f.name}>
              <span className="font-medium">
                {f.name}: {Math.round(f.points)}/{f.weight}
              </span>{" "}
              {f.explanation}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-muted-foreground">
          An estimate from your confirmed profile and preferences, not a prediction of the outcome.
        </p>
        <h4 className="mt-2 font-medium">Seen on</h4>
        <ul className="list-disc pl-5">
          {opp.sources.map((s) => (
            <li key={s.source_url}>
              <a href={s.source_url} target="_blank" rel="noopener noreferrer nofollow" className="underline">
                {s.source_key}
              </a>
              {s.dedup_reasons.length > 0 && (
                <span className="text-xs text-muted-foreground"> (merged: {s.dedup_reasons[0]})</span>
              )}
            </li>
          ))}
        </ul>
        {typeof d.description === "string" && d.description && (
          <>
            <h4 className="mt-2 font-medium">Description</h4>
            <p className="whitespace-pre-line">{d.description}</p>
          </>
        )}
      </details>
      <div className="mt-3 flex flex-wrap gap-2">
        {opp.kind !== "job" && (
          <Link
            href={`/cases/${caseId}/phd/${opp.id}`}
            className={buttonVariants({ size: "sm", variant: "outline" })}
          >
            Research and prepare
          </Link>
        )}
        {opp.match_status !== "shortlisted" && (
          <Button size="sm" onClick={() => setStatus.mutate("shortlisted")} disabled={setStatus.isPending}>
            Shortlist
          </Button>
        )}
        {opp.match_status !== "dismissed" ? (
          <Button size="sm" variant="outline" onClick={() => setStatus.mutate("dismissed")} disabled={setStatus.isPending}>
            Not interested
          </Button>
        ) : (
          <Button size="sm" variant="outline" onClick={() => setStatus.mutate("seen")}>
            Restore
          </Button>
        )}
        {opp.sources.length > 1 && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              const note = window.prompt("What looks wrong about this merge? (optional)") ?? "";
              report.mutate(note);
            }}
          >
            Report wrong merge
          </Button>
        )}
      </div>
      {report.isSuccess && (
        <p role="status" className="mt-1 text-xs">
          Thanks. Your report was saved for review. It doesn&apos;t change these results yet.
        </p>
      )}
      <ErrorAlert error={setStatus.error ?? report.error} />
    </article>
  );
}

function SyncResult({ results }: { results: SyncSummaryOut[] }) {
  return (
    <ul className="text-sm" aria-live="polite">
      {results.map((r) => (
        <li key={r.source_key}>
          <span className="font-medium">{r.source_key}:</span>{" "}
          {r.skipped_reason
            ? r.skipped_reason
            : `checked ${r.fetched}; ${r.new_for_case} new for you; ${r.merged_duplicates} duplicates merged; ${r.updated} updated; ${r.unchanged} unchanged.`}
        </li>
      ))}
    </ul>
  );
}

export function OpportunityBoard({ caseId, academic }: { caseId: string; academic: boolean }) {
  const queryClient = useQueryClient();
  const kase = useCase(caseId);
  const list = useQuery({
    queryKey: ["opportunities", caseId, academic],
    queryFn: () => opportunitiesApi.list(caseId, academic),
  });
  const sources = useQuery({ queryKey: ["sources"], queryFn: opportunitiesApi.sources });
  useCaseEvents(caseId);
  const sync = useMutation({ mutationFn: () => opportunitiesApi.sync(caseId) });
  const syncRun = useRun(sync.data?.run_id);
  const syncStatus = syncRun.data?.run.status;
  const syncResult = syncRun.data?.run.result as { sources?: SyncSummaryOut[] } | null | undefined;
  useEffect(() => {
    if (syncStatus === "succeeded") queryClient.invalidateQueries({ queryKey: ["opportunities", caseId] });
  }, [syncStatus, caseId, queryClient]);
  const searching = sync.isPending || (!!sync.data && syncStatus !== "succeeded" && syncStatus !== "failed" && syncStatus !== "cancelled");
  const rescore = useMutation({
    mutationFn: () => opportunitiesApi.rescore(caseId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["opportunities", caseId] }),
  });
  const toggle = useMutation({
    mutationFn: (args: { key: string; enabled: boolean; settings: Record<string, unknown> }) =>
      opportunitiesApi.configureSource(args.key, args.enabled, args.settings),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sources"] }),
  });

  const path = kase.data?.career_path;
  const pathOff =
    path && ((academic && path === "employment") || (!academic && path === "phd"));
  const items = list.data ?? [];
  const active = items.filter((o) => o.eligible && o.match_status !== "dismissed");
  const notFit = items.filter((o) => !o.eligible && o.match_status !== "dismissed");
  const dismissed = items.filter((o) => o.match_status === "dismissed");
  const relevantSources = (sources.data ?? []).filter((s) =>
    s.kinds.some((k) => (academic ? k !== "job" : k === "job")),
  );

  return (
    <div className="flex max-w-4xl flex-col gap-5">
      {pathOff && (
        <Alert>
          <AlertTitle>Turned off for this case</AlertTitle>
          <AlertDescription>
            This case is set to look for {path === "phd" ? "PhD and research positions" : "jobs"} only.
            Change it on the <Link className="underline" href={`/cases/${caseId}`}>case dashboard</Link>.
          </AlertDescription>
        </Alert>
      )}
      {relevantSources.some((s) => s.is_demo_data) && (
        <Alert>
          <AlertTitle>Demo data</AlertTitle>
          <AlertDescription>
            Only built-in demo sources are connected right now. The results below are made-up
            examples for trying NexScout out. <strong>They are not real postings.</strong>
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap gap-2">
        <Button onClick={() => sync.mutate()} disabled={searching || !!pathOff}>
          {searching ? "Searching…" : "Find opportunities"}
        </Button>
        <Button variant="outline" onClick={() => rescore.mutate()} disabled={rescore.isPending}>
          Update fit estimates
        </Button>
      </div>
      {searching && sync.data && (
        <p role="status" className="text-sm">
          Searching your sources in the background. You can leave this page; progress is in{" "}
          <Link className="underline" href={`/cases/${caseId}/activity`}>Agent activity</Link>.
        </p>
      )}
      {syncStatus === "succeeded" && syncResult?.sources && <SyncResult results={syncResult.sources} />}
      {(syncStatus === "failed" || syncStatus === "cancelled") && (
        <p role="alert" className="text-sm text-destructive">
          The search {syncStatus === "failed" ? `failed: ${syncRun.data?.run.error ?? "unknown error"}` : "was cancelled"}.
        </p>
      )}
      {rescore.data && (
        <p role="status" className="text-sm">
          Updated {rescore.data.rescored} estimates from your latest profile and preferences.
        </p>
      )}
      <ErrorAlert error={sync.error ?? rescore.error ?? list.error} />

      <section aria-labelledby="matches-heading" className="flex flex-col gap-3">
        <h2 id="matches-heading" className="text-xl font-semibold">
          Matches ({active.length})
        </h2>
        {list.isPending && <p>Loading…</p>}
        {list.data && active.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nothing here yet. Use “Find opportunities”. Confirm your profile entries first: only
            confirmed entries are used for matching.
          </p>
        )}
        {active.map((o) => (
          <OpportunityCard key={o.id} opp={o} caseId={caseId} />
        ))}
      </section>

      {notFit.length > 0 && (
        <details>
          <summary className="cursor-pointer font-medium">
            Not a fit right now ({notFit.length})
          </summary>
          <p className="mt-1 text-sm text-muted-foreground">
            Closed, or blocked by a requirement (for example, experience in strict mode). Each one
            says why.
          </p>
          <div className="mt-2 flex flex-col gap-3">
            {notFit.map((o) => (
              <OpportunityCard key={o.id} opp={o} caseId={caseId} />
            ))}
          </div>
        </details>
      )}
      {dismissed.length > 0 && (
        <details>
          <summary className="cursor-pointer font-medium">Not interested ({dismissed.length})</summary>
          <div className="mt-2 flex flex-col gap-3">
            {dismissed.map((o) => (
              <OpportunityCard key={o.id} opp={o} caseId={caseId} />
            ))}
          </div>
        </details>
      )}

      <details className="rounded-lg border p-3">
        <summary className="cursor-pointer font-medium">Sources</summary>
        <ul className="mt-2 flex flex-col gap-3 text-sm">
          {relevantSources.map((s) => (
            <li key={s.key}>
              <label className="flex items-center gap-2 font-medium">
                <input
                  type="checkbox"
                  checked={s.enabled}
                  onChange={(e) => toggle.mutate({ key: s.key, enabled: e.target.checked, settings: s.settings })}
                />
                {s.name}
              </label>
              <p className="text-xs text-muted-foreground">
                {s.terms} Access: {s.auth}. Updates: {s.incremental}
              </p>
              {s.key === "demo_jobs_board_b" && (
                <label className="mt-1 flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={Boolean(s.settings.include_later_postings)}
                    onChange={(e) =>
                      toggle.mutate({
                        key: s.key,
                        enabled: s.enabled,
                        settings: { ...s.settings, include_later_postings: e.target.checked },
                      })
                    }
                  />
                  Simulate newer postings (to try incremental updates)
                </label>
              )}
            </li>
          ))}
        </ul>
        <ErrorAlert error={toggle.error} />
      </details>
    </div>
  );
}
