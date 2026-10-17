"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { ErrorAlert } from "@/components/error-alert";
import { trackingApi } from "@/lib/api/client";
import { statusLabel } from "@/lib/application-status";
import { useCaseEvents } from "@/lib/live";

function Stat({ label, value, href }: { label: string; value: number; href: string }) {
  return (
    <Link href={href} className="lift rounded-xl border bg-card p-3">
      <span className="block font-heading text-2xl font-semibold tabular-nums">{value}</span>
      <span className="text-sm text-muted-foreground">{label}</span>
    </Link>
  );
}

export function DashboardWidgets({ caseId }: { caseId: string }) {
  useCaseEvents(caseId);
  const d = useQuery({
    queryKey: ["dashboard", caseId],
    queryFn: () => trackingApi.dashboard(caseId),
    refetchInterval: 30_000,
  });
  if (d.error) return <ErrorAlert error={d.error} />;
  if (!d.data) return <p>Loading overview…</p>;
  const x = d.data;
  const base = `/cases/${caseId}`;
  const submitted = (x.applications_by_status.submitted ?? 0) + (x.applications_by_status.tracking ?? 0);

  return (
    <div className="flex flex-col gap-4">
      <section aria-labelledby="needs-heading" className="rounded-lg border p-4">
        <h2 id="needs-heading" className="mb-2 text-lg font-semibold">Needs you</h2>
        {x.needs_you.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing is waiting for you.</p>
        ) : (
          <ul className="flex flex-col gap-1 text-sm">
            {x.needs_you.map((i) => (
              <li key={`${i.kind}-${i.title}`}>
                <Link className="underline" href={i.href}>{i.title}</Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Matches" value={x.opportunities.matches} href={`${base}/jobs`} />
        <Stat label="Shortlisted" value={x.opportunities.shortlisted} href={`${base}/jobs`} />
        <Stat label="Applications" value={x.applications_total} href={`${base}/applications`} />
        <Stat label="Submitted" value={submitted} href={`${base}/applications`} />
        <Stat label="Confirmed entries" value={x.profile.accepted} href={`${base}/profile`} />
        <Stat label="To review" value={x.profile.pending} href={`${base}/profile#review`} />
        <Stat label="Profile gaps" value={x.profile.gaps} href={`${base}/profile`} />
      </div>

      <section aria-labelledby="upcoming-heading" className="rounded-lg border p-4">
        <h2 id="upcoming-heading" className="mb-2 text-lg font-semibold">Coming up (30 days)</h2>
        {x.upcoming.length === 0 ? (
          <p className="text-sm text-muted-foreground">No deadlines or reminders.</p>
        ) : (
          <ul className="flex flex-col gap-1 text-sm">
            {x.upcoming.map((i) => (
              <li key={`${i.kind}-${i.date}-${i.title}`}>
                <span className="font-mono">{i.date}</span>{" "}
                <Link className="underline" href={i.href}>{i.title}</Link>
                {i.kind === "deadline" && <span className="text-muted-foreground"> (deadline)</span>}
              </li>
            ))}
          </ul>
        )}
      </section>

      {Object.keys(x.applications_by_status).length > 0 && (
        <section aria-labelledby="by-status-heading">
          <h2 id="by-status-heading" className="mb-1 text-lg font-semibold">Applications by status</h2>
          <ul className="flex flex-wrap gap-3 text-sm">
            {Object.entries(x.applications_by_status).map(([s, n]) => (
              <li key={s}>{statusLabel(s)}: {n}</li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="recent-heading">
        <h2 id="recent-heading" className="mb-1 text-lg font-semibold">Recent agent activity</h2>
        {x.recent_runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing has run yet.</p>
        ) : (
          <ul className="flex flex-col gap-1 text-sm">
            {x.recent_runs.map((r) => (
              <li key={r.id}>
                <Link className="underline" href={`${base}/activity`}>{r.title}</Link>{" "}
                <span className="text-muted-foreground">
                  {r.status.replace("_", " ")} · {new Date(r.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
