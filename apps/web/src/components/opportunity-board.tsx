"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  opportunitiesApi,
  researchApi,
  type OpportunityOut,
  type OpportunityView,
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
    mutationFn: (status: string) =>
      opportunitiesApi.setStatus(caseId, opp.id, status, opp.match_version),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["opportunities", caseId] }),
  });
  const report = useMutation({
    mutationFn: (note: string) => opportunitiesApi.report(caseId, opp.id, note),
  });
  // Lists leave the description out (it can be 50 KB); it is fetched when the card is opened.
  const full = useQuery({
    queryKey: ["opportunity", caseId, opp.id],
    queryFn: () => researchApi.opportunity(caseId, opp.id),
    enabled: open && opp.has_description && typeof d.description !== "string",
  });
  const description =
    typeof d.description === "string"
      ? d.description
      : ((full.data?.data as Record<string, unknown> | undefined)?.description as
          string | undefined);

  return (
    <article aria-labelledby={`opp-${opp.id}`} className="lift rounded-xl border bg-card p-4">
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
              <a
                href={s.source_url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="underline"
              >
                {s.source_key}
              </a>
              {s.dedup_reasons.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  {" "}
                  (merged: {s.dedup_reasons[0]})
                </span>
              )}
            </li>
          ))}
        </ul>
        {description && (
          <>
            <h4 className="mt-2 font-medium">Description</h4>
            <p className="whitespace-pre-line">{description}</p>
          </>
        )}
        {open && full.isPending && opp.has_description && !description && (
          <p className="mt-2 text-muted-foreground">Loading the description…</p>
        )}
      </details>
      <div className="mt-3 flex flex-wrap gap-2">
        <Link
          href={`/cases/${caseId}/${opp.kind === "job" ? "jobs" : "phd"}/${opp.id}`}
          className={buttonVariants({ size: "sm", variant: "outline" })}
        >
          Research and prepare
        </Link>
        {opp.match_status !== "shortlisted" && (
          <Button
            size="sm"
            onClick={() => setStatus.mutate("shortlisted")}
            disabled={setStatus.isPending}
          >
            Shortlist
          </Button>
        )}
        {opp.match_status !== "dismissed" ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setStatus.mutate("dismissed")}
            disabled={setStatus.isPending}
          >
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

const VIEWS: { key: OpportunityView; label: string; empty: string }[] = [
  {
    key: "matches",
    label: "Matches",
    empty:
      "Nothing here yet. Use “Find opportunities”. Confirm your profile entries first: only confirmed entries are used for matching.",
  },
  {
    key: "not_fit",
    label: "Not a fit right now",
    empty: "Nothing is blocked by a requirement.",
  },
  { key: "dismissed", label: "Not interested", empty: "You haven't set any aside." },
];

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}

/** Only the cards near the screen are in the page, so thousands of results stay light. */
function VirtualCards({
  items,
  caseId,
  onNearEnd,
}: {
  items: OpportunityOut[];
  caseId: string;
  onNearEnd: () => void;
}) {
  const [top, setTop] = useState(0);
  const measureTop = useCallback((el: HTMLDivElement | null) => {
    if (el) setTop(el.getBoundingClientRect().top + window.scrollY);
  }, []);
  const virtualizer = useWindowVirtualizer({
    count: items.length,
    estimateSize: () => 240,
    overscan: 6,
    scrollMargin: top,
    getItemKey: (i) => items[i]?.id ?? i,
  });
  const rows = virtualizer.getVirtualItems();
  const lastIndex = rows.at(-1)?.index ?? -1;
  useEffect(() => {
    if (lastIndex >= items.length - 8) onNearEnd();
  }, [lastIndex, items.length, onNearEnd]);
  return (
    <div ref={measureTop} style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
      {rows.map((row) => (
        <div
          key={row.key}
          data-index={row.index}
          ref={virtualizer.measureElement}
          className="absolute left-0 top-0 w-full pb-3"
          style={{ transform: `translateY(${row.start - virtualizer.options.scrollMargin}px)` }}
        >
          <OpportunityCard opp={items[row.index]} caseId={caseId} />
        </div>
      ))}
    </div>
  );
}

export function OpportunityBoard({ caseId, academic }: { caseId: string; academic: boolean }) {
  const queryClient = useQueryClient();
  const kase = useCase(caseId);
  const [view, setView] = useState<OpportunityView>("matches");
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);
  const list = useInfiniteQuery({
    queryKey: ["opportunities", caseId, academic, "page", view, q],
    queryFn: ({ pageParam }) =>
      opportunitiesApi.page(caseId, { academic, view, q, cursor: pageParam }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: (previous) => previous, // keep the counts while another list loads
  });
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = list;
  const loadMore = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);
  const items = useMemo(() => list.data?.pages.flatMap((p) => p.items) ?? [], [list.data]);
  const counts = list.data?.pages[0]?.counts;
  const current = VIEWS.find((v) => v.key === view)!;
  const sources = useQuery({ queryKey: ["sources"], queryFn: opportunitiesApi.sources });
  useCaseEvents(caseId);
  const sync = useMutation({ mutationFn: () => opportunitiesApi.sync(caseId) });
  const syncRun = useRun(sync.data?.run_id);
  const syncStatus = syncRun.data?.run.status;
  const syncResult = syncRun.data?.run.result as { sources?: SyncSummaryOut[] } | null | undefined;
  useEffect(() => {
    if (syncStatus === "succeeded")
      queryClient.invalidateQueries({ queryKey: ["opportunities", caseId] });
  }, [syncStatus, caseId, queryClient]);
  const searching =
    sync.isPending ||
    (!!sync.data &&
      syncStatus !== "succeeded" &&
      syncStatus !== "failed" &&
      syncStatus !== "cancelled");
  const rescore = useMutation({
    mutationFn: () => opportunitiesApi.rescore(caseId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["opportunities", caseId] }),
  });

  const path = kase.data?.career_path;
  const pathOff = path && ((academic && path === "employment") || (!academic && path === "phd"));
  const enabledSources = (sources.data ?? []).filter(
    (s) => s.enabled && s.kinds.some((k) => (academic ? k !== "job" : k === "job")),
  );
  const noSources = sources.isSuccess && enabledSources.length === 0;

  return (
    <div className="flex max-w-4xl flex-col gap-5">
      {pathOff && (
        <Alert>
          <AlertTitle>Turned off for this case</AlertTitle>
          <AlertDescription>
            This case is set to look for {path === "phd" ? "PhD and research positions" : "jobs"}{" "}
            only. Change it on the{" "}
            <Link className="underline" href={`/cases/${caseId}`}>
              case dashboard
            </Link>
            .
          </AlertDescription>
        </Alert>
      )}
      {noSources && (
        <Alert>
          <AlertTitle>No sources turned on</AlertTitle>
          <AlertDescription>
            Pick the job boards, company career pages or university portals to search in{" "}
            <Link className="underline" href={`/cases/${caseId}/settings#sources-heading`}>
              Settings → Where to look
            </Link>
            . You can also add any careers page by its address.
          </AlertDescription>
        </Alert>
      )}
      {enabledSources.some((s) => s.is_demo_data) && (
        <Alert>
          <AlertTitle>Demo data</AlertTitle>
          <AlertDescription>
            Built-in demo sources are turned on. Their results are made-up examples for trying
            NexScout out. <strong>They are not real postings.</strong>
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap gap-2">
        <Button onClick={() => sync.mutate()} disabled={searching || !!pathOff || noSources}>
          {searching ? "Searching…" : "Find opportunities"}
        </Button>
        <Button variant="outline" onClick={() => rescore.mutate()} disabled={rescore.isPending}>
          Update fit estimates
        </Button>
      </div>
      {searching && sync.data && (
        <p role="status" className="text-sm">
          Searching your sources in the background. You can leave this page; progress is in{" "}
          <Link className="underline" href={`/cases/${caseId}/activity`}>
            Agent activity
          </Link>
          .
        </p>
      )}
      {syncStatus === "succeeded" && syncResult?.sources && (
        <SyncResult results={syncResult.sources} />
      )}
      {(syncStatus === "failed" || syncStatus === "cancelled") && (
        <p role="alert" className="text-sm text-destructive">
          The search{" "}
          {syncStatus === "failed"
            ? `failed: ${syncRun.data?.run.error ?? "unknown error"}`
            : "was cancelled"}
          .
        </p>
      )}
      {rescore.data && (
        <p role="status" className="text-sm">
          Updated {rescore.data.rescored} estimates from your latest profile and preferences.
        </p>
      )}
      <ErrorAlert error={sync.error ?? rescore.error ?? list.error} />

      <section aria-labelledby={`tab-${view}`} className="flex flex-col gap-3">
        <h2 id="results-heading" className="sr-only">
          Results
        </h2>
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div role="tablist" aria-label="Lists" className="flex flex-wrap gap-1">
            {VIEWS.map((v) => (
              <button
                key={v.key}
                type="button"
                role="tab"
                id={`tab-${v.key}`}
                aria-selected={view === v.key}
                aria-controls="results-panel"
                onClick={() => setView(v.key)}
                className={
                  view === v.key
                    ? "rounded-md bg-primary/10 px-3 py-1.5 text-sm font-medium"
                    : "rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted"
                }
              >
                {v.label} ({counts ? counts[v.key] : "…"})
              </button>
            ))}
          </div>
          <Input
            type="search"
            aria-label="Search titles and employers"
            placeholder="Search titles and employers"
            className="w-64"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div id="results-panel" role="tabpanel" aria-labelledby={`tab-${view}`}>
          {view === "not_fit" && (
            <p className="mb-2 text-sm text-muted-foreground">
              Closed, or blocked by a requirement (for example, experience in strict mode). Each one
              says why.
            </p>
          )}
          {list.isPending && <p>Loading…</p>}
          {list.data && items.length === 0 && (
            <p className="text-sm text-muted-foreground">
              {q ? `Nothing matches “${q}”.` : current.empty}
            </p>
          )}
          <VirtualCards key={`${view}:${q}`} items={items} caseId={caseId} onNearEnd={loadMore} />
          {isFetchingNextPage && <p className="text-sm text-muted-foreground">Loading more…</p>}
        </div>
      </section>

      <p className="text-sm text-muted-foreground">
        Searching {enabledSources.length} source{enabledSources.length === 1 ? "" : "s"}.{" "}
        <Link className="underline" href={`/cases/${caseId}/settings#sources-heading`}>
          Choose where to look
        </Link>
      </p>
    </div>
  );
}
