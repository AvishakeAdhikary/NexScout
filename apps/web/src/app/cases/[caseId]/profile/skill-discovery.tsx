"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { ApprovalCard } from "@/components/approval-card";
import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { factsApi, runsApi } from "@/lib/api/client";
import { useRun } from "@/lib/live";

interface Found {
  name: string;
  category: string | null;
  quote: string;
  source_label: string;
}

const FINISHED = new Set(["succeeded", "failed", "cancelled"]);

/** "Find my skills with AI": the model suggests skills your entries and CV mention, plain code
 *  keeps only those the text really says, and you choose in one dialog. Nothing is added
 *  before you do. */
export function SkillDiscovery({ caseId }: { caseId: string }) {
  const queryClient = useQueryClient();
  const start = useMutation({ mutationFn: () => runsApi.start(caseId, "skill_discovery") });
  const runId = start.data?.id;
  const run = useRun(runId);
  const status = run.data?.run.status;
  const result = run.data?.run.result as
    { status?: string; message?: string; skills?: Found[]; dropped?: unknown[] } | null | undefined;
  const found = useMemo(() => result?.skills ?? [], [result]);
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const picked = chosen ?? new Set(found.map((s) => s.name)); // all ticked at first
  const dialog = useRef<HTMLDialogElement>(null);
  const busy = start.isPending || (!!runId && !FINISHED.has(status ?? ""));

  useEffect(() => {
    if (status === "succeeded" && found.length > 0) dialog.current?.showModal();
  }, [status, found.length]);
  const add = useMutation({
    mutationFn: () => factsApi.addDiscoveredSkills(caseId, runId!, [...picked]),
    onSuccess: () => {
      dialog.current?.close();
      void queryClient.invalidateQueries({ queryKey: ["facts", caseId] });
      void queryClient.invalidateQueries({ queryKey: ["gaps", caseId] });
    },
  });
  const groups = useMemo(() => {
    const by = new Map<string, Found[]>();
    for (const s of found) {
      const key = s.category || "Other";
      by.set(key, [...(by.get(key) ?? []), s]);
    }
    return [...by.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [found]);
  const toggle = (names: string[], on: boolean) =>
    setChosen(() => {
      const next = new Set(picked);
      for (const n of names) {
        if (on) next.add(n);
        else next.delete(n);
      }
      return next;
    });

  return (
    <section aria-labelledby="skills-ai-heading" className="rounded-lg border p-4">
      <h2 id="skills-ai-heading" className="font-semibold">
        Find my skills with AI
      </h2>
      <p className="text-sm text-muted-foreground">
        An AI model reads your confirmed entries and your CV and suggests skills they mention. Each
        suggestion must quote your own text, or it is dropped. You choose which to add.
      </p>
      <Button
        className="mt-2"
        onClick={() => {
          setChosen(null);
          start.mutate();
        }}
        disabled={busy}
      >
        {busy ? "Looking…" : "Find my skills with AI"}
      </Button>
      <div aria-live="polite" className="mt-2 flex flex-col gap-2 text-sm">
        {(run.data?.approvals ?? [])
          .filter((a) => a.status === "pending")
          .map((a) => (
            <ApprovalCard key={a.id} approval={a} caseId={caseId} />
          ))}
        {status === "succeeded" && found.length === 0 && (
          <p role="status">
            {result?.message ??
              "No new skills found: your profile already has the ones your texts mention."}
          </p>
        )}
        {add.data && (
          <p role="status">
            Added {add.data.length} skill(s) to your confirmed profile, each with its quote.
          </p>
        )}
        {status === "failed" && <p role="alert">{run.data?.run.error}</p>}
        <ErrorAlert error={start.error} />
      </div>

      <dialog
        ref={dialog}
        aria-labelledby="skills-dialog-title"
        className="m-auto w-[min(42rem,92vw)] rounded-xl border bg-background p-0 text-foreground backdrop:bg-black/50"
      >
        <div className="flex max-h-[80vh] flex-col">
          <div className="border-b p-4">
            <h3 id="skills-dialog-title" className="text-lg font-semibold">
              Skills found in your texts ({found.length})
            </h3>
            <p className="text-sm text-muted-foreground">
              Untick any you don&apos;t want. Each one quotes where it was found.
            </p>
            <div className="mt-2 flex gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setChosen(new Set(found.map((s) => s.name)))}
              >
                Select all
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setChosen(new Set())}>
                Select none
              </Button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            {groups.map(([category, items]) => (
              <fieldset key={category} className="mb-3">
                <legend className="flex items-center gap-2 font-medium">
                  {category} ({items.length})
                  <button
                    type="button"
                    className="text-xs font-normal underline"
                    onClick={() =>
                      toggle(
                        items.map((i) => i.name),
                        !items.every((i) => picked.has(i.name)),
                      )
                    }
                  >
                    {items.every((i) => picked.has(i.name)) ? "Untick these" : "Tick these"}
                  </button>
                </legend>
                <ul className="mt-1 flex flex-col gap-1">
                  {items.map((s) => (
                    <li key={s.name}>
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={picked.has(s.name)}
                          onChange={(e) => toggle([s.name], e.target.checked)}
                        />
                        <span>
                          <span className="font-medium">{s.name}</span>
                          <span className="block text-xs text-muted-foreground">
                            “{s.quote}”{s.source_label ? ` (${s.source_label})` : ""}
                          </span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </fieldset>
            ))}
          </div>
          <div className="flex items-center justify-end gap-2 border-t p-4">
            <ErrorAlert error={add.error} />
            <Button variant="ghost" onClick={() => dialog.current?.close()}>
              Cancel
            </Button>
            <Button disabled={picked.size === 0 || add.isPending} onClick={() => add.mutate()}>
              Add {picked.size} skill{picked.size === 1 ? "" : "s"}
            </Button>
          </div>
        </div>
      </dialog>
    </section>
  );
}
