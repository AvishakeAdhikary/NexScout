"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { factsApi, mindmapApi } from "@/lib/api/client";

export function SnapshotCompare({ caseId }: { caseId: string }) {
  const queryClient = useQueryClient();
  const snapshots = useQuery({
    queryKey: ["snapshots", caseId],
    queryFn: () => factsApi.snapshots(caseId),
  });
  const [from, setFrom] = useState<number | "">("");
  const [to, setTo] = useState<number | "">("");
  const save = useMutation({
    mutationFn: () => factsApi.snapshot(caseId, "Saved from the mind map"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["snapshots", caseId] }),
  });
  const remove = useMutation({
    mutationFn: (number: number) => factsApi.deleteSnapshot(caseId, number),
    onSuccess: (_d, number) => {
      if (from === number) setFrom("");
      if (to === number) setTo("");
      queryClient.invalidateQueries({ queryKey: ["snapshots", caseId] });
    },
  });
  const diff = useQuery({
    queryKey: ["snapshot-diff", caseId, from, to],
    queryFn: () => mindmapApi.compare(caseId, Number(from), Number(to)),
    enabled: from !== "" && to !== "" && from !== to,
  });

  const options = snapshots.data ?? [];
  return (
    <section aria-labelledby="snap-heading" className="rounded-lg border p-4">
      <h2 id="snap-heading" className="text-lg font-semibold">
        Profile history
      </h2>
      <p className="text-sm text-muted-foreground">
        Save a snapshot before big changes, then compare any two snapshots.
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <Button variant="outline" onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save snapshot now"}
        </Button>
        {options.length >= 2 && (
          <>
            {(["from", "to"] as const).map((which) => (
              <div key={which} className="flex flex-col gap-1">
                <Label htmlFor={`snap-${which}`}>{which === "from" ? "Compare" : "with"}</Label>
                <select
                  id={`snap-${which}`}
                  className="h-8 rounded-lg border bg-background px-2 text-sm"
                  value={which === "from" ? from : to}
                  onChange={(e) =>
                    (which === "from" ? setFrom : setTo)(
                      e.target.value ? Number(e.target.value) : "",
                    )
                  }
                >
                  <option value="">Choose…</option>
                  {options.map((s) => (
                    <option key={s.id} value={s.number}>
                      #{s.number} · {new Date(s.created_at).toLocaleString()} · {s.fact_count}{" "}
                      entries
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </>
        )}
      </div>
      {options.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm">Saved snapshots ({options.length})</summary>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {options.map((snap) => (
              <li
                key={snap.id}
                className="flex items-center justify-between gap-2 rounded-md border px-2 py-1"
              >
                <span>
                  #{snap.number} · {new Date(snap.created_at).toLocaleString()} · {snap.fact_count}{" "}
                  entries
                  {snap.reason ? ` · ${snap.reason}` : ""}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Delete snapshot ${snap.number}`}
                  disabled={remove.isPending}
                  onClick={() => {
                    if (
                      window.confirm(`Delete snapshot #${snap.number}? Your profile isn't changed.`)
                    )
                      remove.mutate(snap.number);
                  }}
                >
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        </details>
      )}
      <ErrorAlert error={save.error ?? remove.error ?? diff.error} />
      {diff.data && (
        <div className="mt-3 grid gap-3 text-sm sm:grid-cols-3" aria-live="polite">
          {(
            [
              ["Added", diff.data.added],
              ["Removed", diff.data.removed],
              ["Changed", diff.data.changed],
            ] as const
          ).map(([title, rows]) => (
            <div key={title}>
              <h3 className="font-medium">
                {title} ({rows.length})
              </h3>
              <ul className="list-disc pl-5">
                {rows.map((r) => (
                  <li key={String(r.id)}>
                    {String(r.label)}
                    {Array.isArray(r.fields) && ` (${(r.fields as string[]).join(", ")})`}
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="text-muted-foreground sm:col-span-3">{diff.data.unchanged} unchanged.</p>
        </div>
      )}
    </section>
  );
}
