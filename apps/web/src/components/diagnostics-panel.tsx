"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { trackingApi } from "@/lib/api/client";

/** What a user can check about the system serving them: no hostnames, no other users' data. */
export function DiagnosticsPanel() {
  const d = useQuery({
    queryKey: ["diagnostics"],
    queryFn: trackingApi.diagnostics,
    refetchInterval: 15_000,
  });
  if (d.error) return <ErrorAlert error={d.error} />;
  if (!d.data) return <p>Loading…</p>;
  const x = d.data;
  return (
    <section aria-labelledby="diag-heading" className="flex flex-col gap-2 rounded-lg border p-4">
      <h2 id="diag-heading" className="text-xl font-semibold">
        Diagnostics
      </h2>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Background worker</dt>
        <dd>
          {x.workers_alive > 0 ? (
            <Badge variant="secondary">Running ({x.workers_alive})</Badge>
          ) : (
            <Badge variant="destructive">Not running: uploads, searches and drafts will wait</Badge>
          )}
          {x.worker_last_seen && (
            <span className="ml-2 text-xs text-muted-foreground">
              last seen {new Date(x.worker_last_seen).toLocaleString()}
            </span>
          )}
        </dd>
        <dt className="text-muted-foreground">Your work in progress</dt>
        <dd>
          {x.my_tasks.running} running, {x.my_tasks.queued} queued
        </dd>
        <dt className="text-muted-foreground">Version</dt>
        <dd>
          NexScout {x.app_version} · {x.database}
        </dd>
      </dl>
      {x.providers.length > 0 && (
        <>
          <h3 className="font-medium">AI model checks</h3>
          <ul className="text-sm">
            {x.providers.map((p) => (
              <li key={p.name}>
                {p.name}:{" "}
                {p.last_check === null ? "not checked" : p.last_check ? "working" : "failed"}
                {p.checked_at && (
                  <span className="text-muted-foreground">
                    {" "}
                    ({new Date(p.checked_at).toLocaleString()})
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      <h3 className="font-medium">Failures in the last 7 days</h3>
      {x.recent_failures.length === 0 ? (
        <p className="text-sm text-muted-foreground">None.</p>
      ) : (
        <ul className="flex flex-col gap-1 text-sm">
          {x.recent_failures.map((f) => (
            <li key={f.id}>
              <Link className="underline" href={`/cases/${f.case_id}/activity`}>
                {f.title}
              </Link>{" "}
              <span className="text-muted-foreground">{f.error}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
