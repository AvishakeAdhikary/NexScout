"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  runsApi,
  type ApprovalOut,
  type RunAction,
  type RunOut,
  type StepOut,
} from "@/lib/api/client";
import { useCaseEvents, useRun } from "@/lib/live";

// Plain-language run states (spec §16: no internal jargon in the UI).
const STATUS_LABEL: Record<string, string> = {
  pending: "Queued",
  running: "Running",
  waiting_approval: "Waiting for you",
  pausing: "Pausing…",
  paused: "Paused",
  cancelling: "Cancelling…",
  cancelled: "Cancelled",
  failed: "Failed",
  succeeded: "Done",
};
const STEP_LABEL: Record<string, string> = {
  running: "Running",
  succeeded: "Done",
  failed: "Failed",
  skipped: "Skipped",
  cancelled: "Stopped",
  interrupted: "Waiting for you", // an approval gate stops the step until you decide
};

function StatusBadge({ status }: { status: string }) {
  const variant =
    status === "failed" ? "destructive" : status === "succeeded" ? "secondary" : "outline";
  return <Badge variant={variant}>{STATUS_LABEL[status] ?? status}</Badge>;
}

function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

function ApprovalCard({ approval, caseId }: { approval: ApprovalOut; caseId: string }) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: (approve: boolean) => runsApi.decide(approval.id, approve, note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["approvals", caseId] });
      queryClient.invalidateQueries({ queryKey: ["run", approval.run_id] });
      queryClient.invalidateQueries({ queryKey: ["runs", caseId] });
    },
  });
  const details = Object.entries(approval.details ?? {});
  return (
    <article className="rounded-lg border border-amber-500/60 p-3" aria-label={approval.title}>
      <h3 className="font-medium">{approval.title}</h3>
      <p className="text-sm">{approval.summary}</p>
      {details.length > 0 && (
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 text-xs">
          {details.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-muted-foreground">{k.replaceAll("_", " ")}</dt>
              <dd className="break-words">{typeof v === "string" ? v : JSON.stringify(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <div className="flex min-w-48 flex-1 flex-col gap-1">
          <Label htmlFor={`note-${approval.id}`}>Note (optional)</Label>
          <Input
            id={`note-${approval.id}`}
            value={note}
            maxLength={2000}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        <Button onClick={() => decide.mutate(true)} disabled={decide.isPending}>
          Approve
        </Button>
        <Button variant="outline" onClick={() => decide.mutate(false)} disabled={decide.isPending}>
          Reject
        </Button>
      </div>
      <ErrorAlert error={decide.error} />
    </article>
  );
}

function RunControls({ run, caseId }: { run: RunOut; caseId: string }) {
  const queryClient = useQueryClient();
  const control = useMutation({
    mutationFn: (action: RunAction) => runsApi.control(run.id, action),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["run", run.id] });
      queryClient.invalidateQueries({ queryKey: ["runs", caseId] });
    },
  });
  const s = run.status;
  const actions: [RunAction, string][] = [];
  if (s === "pending" || s === "running" || s === "waiting_approval") actions.push(["pause", "Pause"]);
  if (s === "paused") actions.push(["resume", "Resume"]);
  if (s === "failed") actions.push(["retry", "Retry"]);
  if (["pending", "running", "pausing", "paused", "waiting_approval"].includes(s))
    actions.push(["cancel", "Cancel"]);
  if (actions.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        {actions.map(([action, label]) => (
          <Button
            key={action}
            variant={action === "cancel" ? "outline" : "default"}
            disabled={control.isPending}
            onClick={() => {
              if (action === "cancel" && !window.confirm("Cancel this run? It can't be resumed."))
                return;
              control.mutate(action);
            }}
          >
            {label}
          </Button>
        ))}
      </div>
      <ErrorAlert error={control.error} />
    </div>
  );
}

function StepRow({
  step,
  run,
  optional,
  caseId,
}: {
  step: StepOut;
  run: RunOut;
  optional: boolean;
  caseId: string;
}) {
  const queryClient = useQueryClient();
  const control = useMutation({
    mutationFn: (action: RunAction) => runsApi.control(run.id, action, step.node),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["run", run.id] });
      queryClient.invalidateQueries({ queryKey: ["runs", caseId] });
    },
  });
  const editable = ["failed", "paused", "succeeded"].includes(run.status);
  const notes = (step.summary?.notes as string[] | undefined) ?? [];
  return (
    <li className="rounded-md border p-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm">{step.node}</span>
        <Badge variant={step.status === "failed" ? "destructive" : "outline"}>
          {STEP_LABEL[step.status] ?? step.status}
        </Badge>
        <span className="text-xs text-muted-foreground">{when(step.started_at)}</span>
        {editable && (
          <span className="ml-auto flex gap-2">
            <Button size="sm" variant="outline" disabled={control.isPending}
              onClick={() => control.mutate("rerun")}>
              Run this step again
            </Button>
            {optional && (
              <Button size="sm" variant="outline" disabled={control.isPending}
                onClick={() => control.mutate("skip")}>
                Skip this step
              </Button>
            )}
          </span>
        )}
      </div>
      {notes.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-sm">
          {notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
      {step.error && <p className="mt-1 text-sm text-destructive">{step.error}</p>}
      <ErrorAlert error={control.error} />
    </li>
  );
}

function RunDetail({
  runId,
  caseId,
  optionalSteps,
}: {
  runId: string;
  caseId: string;
  optionalSteps: Record<string, string[]>;
}) {
  const detail = useRun(runId);
  if (detail.isPending) return <p>Loading…</p>;
  if (detail.error) return <ErrorAlert error={detail.error} />;
  const { run, steps, approvals, events } = detail.data;
  const optional = new Set(optionalSteps[run.kind] ?? []);
  return (
    <section aria-labelledby="run-heading" className="flex flex-col gap-3 rounded-lg border p-4">
      <header className="flex flex-wrap items-center gap-2">
        <h2 id="run-heading" className="text-lg font-semibold">
          {run.title}
        </h2>
        <StatusBadge status={run.status} />
      </header>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-sm">
        <dt className="text-muted-foreground">Started</dt>
        <dd>{when(run.started_at ?? run.created_at)}</dd>
        <dt className="text-muted-foreground">Finished</dt>
        <dd>{when(run.finished_at)}</dd>
        <dt className="text-muted-foreground">Steps</dt>
        <dd>
          {run.steps_completed} of at most {run.step_budget}
        </dd>
        <dt className="text-muted-foreground">AI tokens used</dt>
        <dd>{run.tokens_used}</dd>
      </dl>
      {run.error && (
        <p role="alert" className="text-sm text-destructive">
          {run.error}
        </p>
      )}
      <RunControls run={run} caseId={caseId} />
      {approvals
        .filter((a) => a.status === "pending")
        .map((a) => (
          <ApprovalCard key={a.id} approval={a} caseId={caseId} />
        ))}
      <h3 className="font-medium">Steps</h3>
      {steps.length === 0 ? (
        <p className="text-sm text-muted-foreground">No steps have started yet.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {steps.map((s) => (
            <StepRow key={s.id} step={s} run={run} optional={optional.has(s.node)} caseId={caseId} />
          ))}
        </ol>
      )}
      {run.result && (
        <details>
          <summary className="cursor-pointer font-medium">Result</summary>
          <pre className="mt-2 overflow-x-auto rounded bg-muted p-2 text-xs">
            {JSON.stringify(run.result, null, 2)}
          </pre>
        </details>
      )}
      <details>
        <summary className="cursor-pointer font-medium">Event log ({events.length})</summary>
        <ol className="mt-2 flex flex-col gap-1 text-xs">
          {events.map((e) => (
            <li key={e.id}>
              <span className="text-muted-foreground">{when(e.created_at)}</span>{" "}
              <span className="font-mono">{e.type}</span>
              {typeof e.payload?.message === "string" && <> · {e.payload.message}</>}
              {typeof e.payload?.node === "string" && <> · {e.payload.node}</>}
            </li>
          ))}
        </ol>
      </details>
    </section>
  );
}

function StartRun({ caseId, onStarted }: { caseId: string; onStarted: (id: string) => void }) {
  const queryClient = useQueryClient();
  const workflows = useQuery({ queryKey: ["workflows"], queryFn: runsApi.workflows });
  const [kind, setKind] = useState("system_check");
  const start = useMutation({
    mutationFn: (args: { kind: string; params: Record<string, unknown> }) =>
      runsApi.start(caseId, args.kind, args.params),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ["runs", caseId] });
      onStarted(run.id);
    },
  });
  const selected = workflows.data?.find((w) => w.kind === kind);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const params: Record<string, unknown> = {};
    if (kind === "system_check") {
      params.wait_s = Number(f.get("wait_s") || 0);
      params.require_approval = f.get("require_approval") === "on";
    }
    start.mutate({ kind, params });
  }

  return (
    <section aria-labelledby="start-heading" className="rounded-lg border p-4">
      <h2 id="start-heading" className="mb-2 text-lg font-semibold">
        Start a workflow
      </h2>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor="wf-kind">Workflow</Label>
          <select
            id="wf-kind"
            className="h-8 rounded-lg border bg-background px-2 text-sm"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
          >
            {(workflows.data ?? []).map((w) => (
              <option key={w.kind} value={w.kind}>
                {w.title}
              </option>
            ))}
          </select>
          {selected && <p className="text-sm text-muted-foreground">{selected.description}</p>}
        </div>
        {kind === "system_check" && (
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex flex-col gap-1">
              <Label htmlFor="wf-wait">Wait step (seconds, 0–120)</Label>
              <Input id="wf-wait" name="wait_s" type="number" min={0} max={120} defaultValue={5}
                className="w-28" />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" name="require_approval" defaultChecked />
              Ask me for approval before the last step
            </label>
          </div>
        )}
        <Button type="submit" className="self-start" disabled={start.isPending || !selected}>
          Start
        </Button>
        <ErrorAlert error={start.error ?? workflows.error} />
      </form>
    </section>
  );
}

export default function ActivityPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const { connected } = useCaseEvents(caseId);
  const runs = useQuery({
    queryKey: ["runs", caseId],
    queryFn: () => runsApi.list(caseId),
    refetchInterval: connected ? 30_000 : 5000,
  });
  const approvals = useQuery({
    queryKey: ["approvals", caseId],
    queryFn: () => runsApi.approvals(caseId),
    refetchInterval: connected ? 30_000 : 5000,
  });
  const workflows = useQuery({ queryKey: ["workflows"], queryFn: runsApi.workflows });
  const optionalSteps = Object.fromEntries(
    (workflows.data ?? []).map((w) => [w.kind, w.optional_steps]),
  );
  const [selected, setSelected] = useState<string | null>(null);
  const current = selected ?? runs.data?.[0]?.id ?? null;

  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Agent Activity</h1>
        <p className="text-muted-foreground">
          Background work for this case: reading documents, searching for opportunities, and
          drafting. Nothing consequential happens without your approval here.
        </p>
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {connected ? "Live updates on." : "Live updates reconnecting… (refreshing every 5 s)"}
        </p>
      </header>

      {approvals.data && approvals.data.length > 0 && (
        <section aria-labelledby="approvals-heading" className="flex flex-col gap-2">
          <h2 id="approvals-heading" className="text-lg font-semibold">
            Waiting for your decision ({approvals.data.length})
          </h2>
          {approvals.data.map((a) => (
            <ApprovalCard key={a.id} approval={a} caseId={caseId} />
          ))}
        </section>
      )}
      <ErrorAlert error={approvals.error} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section aria-labelledby="runs-heading" className="flex flex-col gap-2">
          <h2 id="runs-heading" className="text-lg font-semibold">
            Runs
          </h2>
          {runs.isPending && <p>Loading…</p>}
          <ErrorAlert error={runs.error} />
          {runs.data && runs.data.length === 0 && (
            <p className="text-sm text-muted-foreground">Nothing has run for this case yet.</p>
          )}
          <ul className="flex flex-col gap-1">
            {(runs.data ?? []).map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  aria-current={r.id === current ? "true" : undefined}
                  onClick={() => setSelected(r.id)}
                  className={`flex w-full flex-wrap items-center gap-2 rounded-md border p-2 text-left text-sm ${
                    r.id === current ? "border-primary bg-muted" : ""
                  }`}
                >
                  <span className="font-medium">{r.title}</span>
                  <StatusBadge status={r.status} />
                  <span className="w-full text-xs text-muted-foreground">
                    {when(r.created_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
        <div className="flex flex-col gap-6">
          {current && <RunDetail runId={current} caseId={caseId} optionalSteps={optionalSteps} />}
          <StartRun caseId={caseId} onStarted={setSelected} />
        </div>
      </div>
    </div>
  );
}
