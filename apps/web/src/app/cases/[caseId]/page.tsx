"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { DashboardWidgets } from "@/components/dashboard-widgets";
import { GettingStarted } from "@/components/getting-started";
import { ErrorAlert } from "@/components/error-alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { casesApi, type CareerPath } from "@/lib/api/client";
import { useCase } from "@/lib/hooks";
import { CAREER_PATH_HELP, CAREER_PATH_LABELS } from "@/lib/labels";
import { SECTIONS } from "@/lib/sections";
import { cn } from "@/lib/utils";

const PATHS: CareerPath[] = ["phd", "employment", "both", "undecided"];

export default function CaseDashboard() {
  const { caseId } = useParams<{ caseId: string }>();
  const kase = useCase(caseId);
  const queryClient = useQueryClient();
  // The user's pending choice is shown immediately (set synchronously in the change handler);
  // it is cleared when the save settles, so a rejected save falls back to the server value.
  const [pendingPath, setPendingPath] = useState<CareerPath | null>(null);
  const setPath = useMutation({
    mutationFn: ({ career_path, version }: { career_path: CareerPath; version: number }) =>
      casesApi.update(caseId, { version, career_path }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["cases", caseId], updated);
      queryClient.invalidateQueries({ queryKey: ["cases"], exact: true });
    },
    onSettled: () => setPendingPath(null),
  });

  if (kase.isPending) return <p>Loading case…</p>;
  if (kase.error) return <ErrorAlert error={kase.error} title="Couldn't open this case" />;
  const c = kase.data;
  const selected = pendingPath ?? c.career_path;

  function choose(p: CareerPath) {
    if (p === selected) return;
    setPendingPath(p);
    setPath.mutate({ career_path: p, version: c.version });
  }

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">{c.name}</h1>
        {c.description && <p className="mt-1 text-muted-foreground">{c.description}</p>}
      </header>

      <GettingStarted caseId={caseId} />

      <DashboardWidgets caseId={caseId} />

      <Card>
        <CardHeader>
          <CardTitle>
            <h2 className="text-lg font-semibold">What are you looking for?</h2>
          </CardTitle>
          <CardDescription>
            This decides which tools are switched on for this case. You can change it at any time
            without losing work.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <fieldset className="grid gap-2 sm:grid-cols-2" aria-busy={setPath.isPending}>
            <legend className="sr-only">Career path</legend>
            {PATHS.map((p) => (
              <label
                key={p}
                className={cn(
                  "flex cursor-pointer flex-col gap-1 rounded-lg border p-3 hover:bg-muted has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                  selected === p && "border-primary bg-muted",
                )}
              >
                <span className="flex items-center gap-2 font-medium">
                  <input
                    type="radio"
                    name="career_path"
                    value={p}
                    checked={selected === p}
                    onChange={() => choose(p)}
                  />
                  {CAREER_PATH_LABELS[p]}
                </span>
                <span className="text-sm text-muted-foreground">{CAREER_PATH_HELP[p]}</span>
              </label>
            ))}
          </fieldset>
          <div className="mt-3" aria-live="polite">
            {setPath.isPending && <p className="text-sm">Saving…</p>}
            <ErrorAlert error={setPath.error} title="Couldn't save your choice" />
          </div>
        </CardContent>
      </Card>

      <section aria-labelledby="next-heading">
        <h2 id="next-heading" className="mb-2 text-lg font-semibold">
          What NexScout can do for this case
        </h2>
        <ul className="grid gap-2 sm:grid-cols-2">
          {SECTIONS.filter((s) => s.slug).map((s) => (
            <li key={s.slug}>
              <Link
                href={`/cases/${caseId}/${s.slug}`}
                className="lift block h-full rounded-xl border bg-card p-3"
              >
                <span className="font-medium">{s.label}</span>
                <p className="text-sm text-muted-foreground">{s.description}</p>
                {s.milestone !== undefined && (
                  <p className="mt-1 text-xs text-muted-foreground">Not available yet</p>
                )}
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
