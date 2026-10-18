"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { CountryPicker } from "@/components/country-picker";
import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { autopilotApi, trackingApi, type AutopilotOut, type PolicyIn } from "@/lib/api/client";

const STEPS: [string, string][] = [
  ["discover", "Search for new positions"],
  ["research", "Research each position"],
  ["documents", "Write documents from my confirmed profile"],
  ["fill", "Fill in application forms"],
  ["submit", "Submit (with my approval, unless allowed below)"],
];
const STAGE: Record<string, { label: string; tone: "default" | "secondary" | "outline" | "destructive" }> = {
  queued: { label: "Queued", tone: "outline" },
  researching: { label: "Researching", tone: "secondary" },
  drafting: { label: "Writing documents", tone: "secondary" },
  rendering: { label: "Creating files", tone: "secondary" },
  needs_input: { label: "Needs your answer", tone: "destructive" },
  applying: { label: "Filling the form", tone: "secondary" },
  waiting_approval: { label: "Waiting for your approval", tone: "destructive" },
  needs_user_action: { label: "Needs you", tone: "destructive" },
  submitted: { label: "Submitted", tone: "default" },
  manual: { label: "Apply yourself", tone: "outline" },
  skipped: { label: "Skipped", tone: "outline" },
  failed: { label: "Stopped (error)", tone: "destructive" },
  stopped: { label: "Stopped by you", tone: "outline" },
};
const DOC_TYPES: [string, string][] = [
  ["resume", "Resume"],
  ["cover_letter", "Cover letter"],
  ["academic_cv", "Academic CV"],
  ["sop", "Statement of purpose"],
  ["research_proposal", "Research proposal"],
];

const list = (v: FormDataEntryValue | null) =>
  String(v ?? "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);

export default function AutopilotPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const queryClient = useQueryClient();
  const view = useQuery({
    queryKey: ["autopilot", caseId],
    queryFn: () => autopilotApi.get(caseId),
    refetchInterval: 10_000,
  });
  const notes = useQuery({ queryKey: ["notifications"], queryFn: trackingApi.notifications });
  const answers = useQuery({ queryKey: ["answers", caseId], queryFn: () => autopilotApi.answers(caseId) });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["autopilot", caseId] });
    void queryClient.invalidateQueries({ queryKey: ["answers", caseId] });
    void queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };
  const save = useMutation({
    mutationFn: (body: PolicyIn) => autopilotApi.save(caseId, body),
    onSuccess: (data) => queryClient.setQueryData(["autopilot", caseId], data),
  });
  const run = useMutation({ mutationFn: () => autopilotApi.run(caseId), onSuccess: refresh });
  const stop = useMutation({ mutationFn: autopilotApi.stop, onSuccess: refresh });

  const data = view.data;
  const questions = (notes.data?.items ?? []).filter(
    (n) => n.kind === "question" && !n.read && n.case_id === caseId,
  );

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Autopilot</h1>
        {data && (
          <Badge variant={data.policy.enabled ? "default" : "outline"}>
            {data.policy.enabled ? "On" : "Off"}
          </Badge>
        )}
        <span className="ml-auto flex gap-2">
          <Button variant="outline" onClick={() => run.mutate()} disabled={!data?.policy.enabled || run.isPending}>
            Run now
          </Button>
          <Button variant="destructive" onClick={() => stop.mutate()} disabled={stop.isPending}>
            Stop everything
          </Button>
        </span>
      </header>
      <p className="text-sm text-muted-foreground">
        NexScout works on its own within the rules below, and asks you whenever it doesn&apos;t
        know something. It never guesses an answer, never invents a fact, never solves a CAPTCHA
        or signs in for you, and never automates sites that forbid it. Send <b>STOP</b> from a
        paired chat to stop everything from your phone.
      </p>
      {data?.policy.stopped_reason && !data.policy.enabled && (
        <p role="status" className="text-sm">Stopped: {data.policy.stopped_reason}</p>
      )}
      {stop.data && (
        <p role="status" className="text-sm">
          Stopped. {stop.data.runs_cancelled} task(s) cancelled.
        </p>
      )}
      <ErrorAlert error={view.error ?? run.error ?? stop.error} />

      <Questions questions={questions} onDone={refresh} />
      {data && <PolicyForm key={data.policy.version} data={data} onSave={(b) => save.mutate(b)} pending={save.isPending} />}
      <ErrorAlert error={save.error} title="Settings not saved" />
      {save.isSuccess && <p role="status" className="text-sm">Settings saved.</p>}

      <section aria-labelledby="work-heading" className="flex flex-col gap-2">
        <h2 id="work-heading" className="text-lg font-semibold">What the autopilot is working on</h2>
        {(data?.items ?? []).length === 0 && (
          <p className="text-sm text-muted-foreground">Nothing yet. Turn it on and press Run now.</p>
        )}
        <ul className="flex flex-col gap-2">
          {(data?.items ?? []).map((i) => {
            const st = STAGE[i.stage] ?? { label: i.stage, tone: "outline" as const };
            return (
              <li key={i.id} aria-label={i.title} className="flex flex-col gap-1 rounded-lg border p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{i.title}</span>
                  <span className="text-muted-foreground">{i.organization}</span>
                  <span className="font-mono text-xs text-muted-foreground">fit {i.fit}</span>
                  <Badge variant={st.tone}>{st.label}</Badge>
                  {i.application_id && (
                    <Link className="ml-auto text-xs underline" href={`/cases/${caseId}/applications/${i.application_id}`}>
                      Open application
                    </Link>
                  )}
                </div>
                {i.reason && <p className="text-xs text-muted-foreground">{i.reason}</p>}
              </li>
            );
          })}
        </ul>
      </section>

      <SavedAnswers caseId={caseId} rows={answers.data ?? []} onChange={refresh} />

      {data && (
        <details className="text-sm">
          <summary className="cursor-pointer">Sites NexScout never automates ({data.manual_only_sites.length})</summary>
          <p className="mt-1 text-muted-foreground">
            Their terms prohibit bots or automated applications, so NexScout prepares your
            documents and tells you to apply there yourself: {data.manual_only_sites.join(", ")}.
            Pages whose robots.txt disallows automated tools are treated the same way.
          </p>
        </details>
      )}
    </div>
  );
}

function Questions({
  questions,
  onDone,
}: {
  questions: { id: string; title: string; body: string | null }[];
  onDone: () => void;
}) {
  const reply = useMutation({
    mutationFn: ({ id, answer }: { id: string; answer: string }) => autopilotApi.reply(id, answer),
    onSuccess: onDone,
  });
  if (questions.length === 0) return null;
  return (
    <section aria-labelledby="questions-heading" className="flex flex-col gap-2 rounded-xl border border-amber-500/60 p-4">
      <h2 id="questions-heading" className="text-lg font-semibold">Questions waiting for you</h2>
      <p className="text-xs text-muted-foreground">
        Your answer is saved for this case and reused, so you&apos;re only asked once.
      </p>
      {questions.map((q) => (
        <form
          key={q.id}
          className="flex flex-col gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            const answer = String(new FormData(e.currentTarget).get("answer") ?? "").trim();
            if (answer) reply.mutate({ id: q.id, answer });
          }}
        >
          <Label htmlFor={`q-${q.id}`}>{q.title}</Label>
          {q.body && <p className="text-xs text-muted-foreground">{q.body}</p>}
          <div className="flex gap-2">
            <Input id={`q-${q.id}`} name="answer" maxLength={5000} required />
            <Button type="submit" size="sm" disabled={reply.isPending}>Answer</Button>
          </div>
        </form>
      ))}
      <ErrorAlert error={reply.error} />
    </section>
  );
}

function PolicyForm({
  data,
  onSave,
  pending,
}: {
  data: AutopilotOut;
  onSave: (body: PolicyIn) => void;
  pending: boolean;
}) {
  const p = data.policy;
  const [auto, setAuto] = useState(p.auto_submit);
  const [countries, setCountries] = useState<string[]>(p.countries);
  const [excluded, setExcluded] = useState<string[]>(p.countries_exclude ?? []);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const autoSubmit = f.get("auto_submit") === "on";
    const declarations = f.get("declarations") === "on";
    onSave({
      version: p.version,
      enabled: f.get("enabled") === "on",
      steps: Object.fromEntries(STEPS.map(([k]) => [k, f.get(`step-${k}`) === "on"])),
      interval_hours: Number(f.get("interval_hours")),
      min_fit: Number(f.get("min_fit")),
      max_new_per_run: Number(f.get("max_new_per_run")),
      daily_submit_cap: Number(f.get("daily_submit_cap")),
      per_org_cap: Number(f.get("per_org_cap")),
      kinds: ["job", "academic"].filter((k) => f.get(`kind-${k}`) === "on"),
      countries,
      countries_exclude: excluded,
      exclude_orgs: list(f.get("exclude_orgs")),
      doc_types: DOC_TYPES.map(([k]) => k).filter((k) => f.get(`doc-${k}`) === "on"),
      auto_submit: autoSubmit,
      consent: autoSubmit && !p.auto_submit ? data.auto_submit_consent : null,
      declarations,
      declarations_consent: declarations && !p.declarations ? data.declarations_consent : null,
    });
  }

  const num = (name: string, label: string, value: number, min: number, max: number) => (
    <div className="flex flex-col gap-1">
      <Label htmlFor={`ap-${name}`}>{label}</Label>
      <Input id={`ap-${name}`} name={name} type="number" min={min} max={max} defaultValue={value} className="w-28" />
    </div>
  );

  return (
    <form onSubmit={submit} aria-label="Autopilot settings" className="flex flex-col gap-4 rounded-xl border bg-card p-4">
      <h2 className="text-lg font-semibold">Settings</h2>
      <label className="flex items-center gap-2 text-sm font-medium">
        <input type="checkbox" name="enabled" defaultChecked={p.enabled} /> Autopilot on
      </label>
      <fieldset className="flex flex-col gap-1 text-sm">
        <legend className="mb-1 font-medium">Steps it may do on its own</legend>
        {STEPS.map(([k, label]) => (
          <label key={k} className="flex items-center gap-2">
            <input type="checkbox" name={`step-${k}`} defaultChecked={p.steps[k]} /> {label}
          </label>
        ))}
      </fieldset>
      <div className="flex flex-wrap gap-3">
        {num("interval_hours", "Run every (hours)", p.interval_hours, 1, 168)}
        {num("min_fit", "Minimum fit (0–100)", p.min_fit, 0, 100)}
        {num("max_new_per_run", "New positions per run", p.max_new_per_run, 0, 20)}
        {num("daily_submit_cap", "Submissions per day", p.daily_submit_cap, 0, 20)}
        {num("per_org_cap", "Per organization", p.per_org_cap, 1, 10)}
      </div>
      <fieldset className="flex flex-wrap gap-4 text-sm">
        <legend className="mb-1 font-medium">Kinds (none = both)</legend>
        <label className="flex items-center gap-2"><input type="checkbox" name="kind-job" defaultChecked={p.kinds.includes("job")} /> Jobs</label>
        <label className="flex items-center gap-2"><input type="checkbox" name="kind-academic" defaultChecked={p.kinds.includes("academic")} /> PhD and academic</label>
      </fieldset>
      <div className="grid gap-3 sm:grid-cols-2">
        <CountryPicker label="Countries (empty = any)" value={countries} onChange={setCountries} />
        <CountryPicker label="Never in these countries" value={excluded} onChange={setExcluded} />
        <div className="flex flex-col gap-1">
          <Label htmlFor="ap-exclude">Never apply to (comma separated)</Label>
          <Input id="ap-exclude" name="exclude_orgs" defaultValue={p.exclude_orgs.join(", ")} />
        </div>
      </div>
      <fieldset className="flex flex-wrap gap-4 text-sm">
        <legend className="mb-1 font-medium">Documents to prepare (none = the usual ones)</legend>
        {DOC_TYPES.map(([k, label]) => (
          <label key={k} className="flex items-center gap-2">
            <input type="checkbox" name={`doc-${k}`} defaultChecked={p.doc_types.includes(k)} /> {label}
          </label>
        ))}
      </fieldset>
      <div className="flex flex-col gap-2 rounded-lg border border-amber-500/50 p-3 text-sm">
        <label className="flex items-start gap-2 font-medium">
          <input type="checkbox" name="auto_submit" defaultChecked={p.auto_submit} onChange={(e) => setAuto(e.target.checked)} />
          <span>Submit without asking me each time</span>
        </label>
        <p className="text-xs text-muted-foreground">{data.auto_submit_consent}</p>
        {p.consented_at && <p className="text-xs">You agreed on {new Date(p.consented_at).toLocaleString()}.</p>}
        <label className="flex items-start gap-2">
          <input type="checkbox" name="declarations" defaultChecked={p.declarations} disabled={!auto} />
          <span>Also tick declarations for me</span>
        </label>
        <p className="text-xs text-muted-foreground">{data.declarations_consent}</p>
      </div>
      <Button type="submit" className="self-start" disabled={pending}>
        {pending ? "Saving…" : "Save settings"}
      </Button>
    </form>
  );
}

function SavedAnswers({
  caseId,
  rows,
  onChange,
}: {
  caseId: string;
  rows: { id: string; question: string; answer: string; source: string }[];
  onChange: () => void;
}) {
  const add = useMutation({
    mutationFn: ({ q, a }: { q: string; a: string }) => autopilotApi.saveAnswer(caseId, q, a),
    onSuccess: onChange,
  });
  const remove = useMutation({ mutationFn: autopilotApi.deleteAnswer, onSuccess: onChange });
  return (
    <section aria-labelledby="answers-heading" className="flex flex-col gap-2">
      <h2 id="answers-heading" className="text-lg font-semibold">Your saved answers</h2>
      <p className="text-xs text-muted-foreground">
        Reused whenever a form or document asks the same thing. Only you write these.
      </p>
      <ul className="flex flex-col gap-1 text-sm">
        {rows.map((r) => (
          <li key={r.id} className="flex flex-wrap items-baseline gap-2">
            <span className="font-medium">{r.question}</span>
            <span className="text-muted-foreground">{r.answer}</span>
            <button type="button" className="text-xs underline" onClick={() => remove.mutate(r.id)}>
              Remove
            </button>
          </li>
        ))}
      </ul>
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          add.mutate({ q: String(f.get("q") ?? ""), a: String(f.get("a") ?? "") });
          e.currentTarget.reset();
        }}
      >
        <div className="flex flex-col gap-1">
          <Label htmlFor="ans-q">Question</Label>
          <Input id="ans-q" name="q" required maxLength={1000} className="w-72" />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="ans-a">Your answer</Label>
          <Input id="ans-a" name="a" required maxLength={5000} className="w-72" />
        </div>
        <Button type="submit" size="sm" variant="outline" disabled={add.isPending}>Save answer</Button>
      </form>
      <ErrorAlert error={add.error ?? remove.error} />
    </section>
  );
}
