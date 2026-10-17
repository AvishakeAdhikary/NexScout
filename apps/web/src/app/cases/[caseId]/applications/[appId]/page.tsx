"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ApprovalCard } from "@/components/approval-card";
import { ErrorAlert } from "@/components/error-alert";
import { RemindersPanel } from "@/components/reminders-panel";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  applicationsApi,
  autopilotApi,
  generatedApi,
  runsApi,
  type ApplicationDetailOut,
} from "@/lib/api/client";
import { STATUS_ACTION, statusLabel } from "@/lib/application-status";
import { useCaseEvents, useRun } from "@/lib/live";

const FILLABLE = new Set(["preparing", "needs_user_action", "failed", "awaiting_review", "approved"]);

function lastMissing(app: ApplicationDetailOut): string[] {
  const ev = [...app.events].reverse().find((e) => e.type === "needs_user_action");
  const missing = (ev?.payload as { missing?: string[] } | undefined)?.missing;
  return app.status === "needs_user_action" && missing ? missing : [];
}

function Details({ app, caseId }: { app: ApplicationDetailOut; caseId: string }) {
  const queryClient = useQueryClient();
  const docs = useQuery({ queryKey: ["generated", caseId], queryFn: () => generatedApi.list(caseId) });
  const questions = Array.from(new Set([...lastMissing(app), ...Object.keys(app.answers)]));
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      applicationsApi.update(app.id, { version: app.version, ...body }),
    onSuccess: (d) => queryClient.setQueryData(["application", app.id], d),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const answers: Record<string, string> = {};
    questions.forEach((q, i) => {
      const v = String(f.get(`answer-${i}`) ?? "").trim();
      if (v) answers[q] = v;
    });
    save.mutate({
      answers,
      phone: String(f.get("phone") ?? "").trim() || null,
      apply_url: String(f.get("apply_url") ?? "").trim() || null,
      document_ids: f.getAll("document_ids").map(String),
    });
  }

  return (
    <form key={app.version} onSubmit={submit} className="flex flex-col gap-3 rounded-lg border p-4"
      aria-labelledby="details-heading">
      <h2 id="details-heading" className="font-semibold">What NexScout may use</h2>
      <p className="text-sm text-muted-foreground">
        Forms are filled only from your account name and email, the answers below, and the
        documents you choose. Anything else is left for you.
      </p>
      {questions.map((q, i) => (
        <div key={q} className="flex flex-col gap-1">
          <Label htmlFor={`answer-${i}`}>Your answer: {q}</Label>
          <Textarea id={`answer-${i}`} name={`answer-${i}`} defaultValue={app.answers[q] ?? ""} rows={3} />
        </div>
      ))}
      <div className="flex flex-col gap-1">
        <Label htmlFor="phone">Phone (optional)</Label>
        <Input id="phone" name="phone" defaultValue={app.phone ?? ""} maxLength={40} className="max-w-xs" />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="apply_url">Application page address</Label>
        <Input id="apply_url" name="apply_url" defaultValue={app.apply_url ?? ""} maxLength={2048} />
      </div>
      <fieldset className="flex flex-col gap-1">
        <legend className="text-sm font-medium">Documents to upload</legend>
        {(docs.data ?? []).map((d) => (
          <label key={d.id} className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="document_ids" value={d.id}
              defaultChecked={app.document_ids.includes(d.id)} />
            {d.title}
            <span className="text-xs text-muted-foreground">
              v{d.current_version}
              {d.latest.placeholders.length > 0 ? ` · ${d.latest.placeholders.length} placeholder(s) left` : ""}
              {!d.latest.has_files ? " · no PDF yet" : ""}
            </span>
          </label>
        ))}
      </fieldset>
      <Button type="submit" className="self-start" disabled={save.isPending}>Save</Button>
      <ErrorAlert error={save.error} />
    </form>
  );
}

function Timeline({ app }: { app: ApplicationDetailOut }) {
  return (
    <section aria-labelledby="timeline-heading" className="flex flex-col gap-2">
      <h2 id="timeline-heading" className="font-semibold">Timeline</h2>
      <ol className="flex flex-col gap-2 text-sm">
        {[...app.events].reverse().map((e) => (
          <li key={e.id} className="rounded-md border p-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">{new Date(e.created_at).toLocaleString()}</span>
              <Badge variant="outline">{e.actor === "agent" ? "NexScout" : e.actor === "user" ? "You" : "System"}</Badge>
              {e.to_status && <span>→ {statusLabel(e.to_status)}</span>}
            </div>
            {e.message && <p>{e.message}</p>}
            {e.has_screenshot && (
              <details>
                <summary className="cursor-pointer text-xs">Screenshot</summary>
                {/* eslint-disable-next-line @next/next/no-img-element -- authenticated API image */}
                <img src={applicationsApi.screenshotUrl(app.id, e.id)} alt={`Page screenshot: ${e.message ?? e.type}`}
                  className="mt-1 max-h-[32rem] rounded border" />
              </details>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function ApplicationPage() {
  const { caseId, appId } = useParams<{ caseId: string; appId: string }>();
  const queryClient = useQueryClient();
  useCaseEvents(caseId);
  const query = useQuery({
    queryKey: ["application", appId],
    queryFn: () => applicationsApi.get(appId),
    refetchInterval: 5000,
  });
  const approvals = useQuery({ queryKey: ["approvals", caseId], queryFn: () => runsApi.approvals(caseId) });
  const fill = useMutation({ mutationFn: () => applicationsApi.fill(appId) });
  const run = useRun(fill.data?.run_id);
  const [reference, setReference] = useState("");
  const refresh = (d: ApplicationDetailOut) => {
    queryClient.setQueryData(["application", appId], d);
    queryClient.invalidateQueries({ queryKey: ["applications", caseId] });
  };
  const setStatus = useMutation({
    mutationFn: (s: string) => applicationsApi.setStatus(appId, query.data!.version, s, undefined, reference),
    onSuccess: refresh,
  });
  const resolve = useMutation({
    mutationFn: (submitted: boolean) => applicationsApi.resolve(appId, submitted, reference),
    onSuccess: refresh,
  });

  if (query.isPending) return <p>Loading…</p>;
  if (query.error) return <ErrorAlert error={query.error} />;
  const app = query.data;
  const pending = (approvals.data ?? []).filter(
    (a) => (a.details as { application_id?: string }).application_id === app.id,
  );
  const runStatus = run.data?.run.status;
  const filling = fill.isPending || (!!fill.data && (runStatus === "pending" || runStatus === "running"));

  return (
    <div className="flex max-w-4xl flex-col gap-5">
      <Link className="text-sm underline" href={`/cases/${caseId}/applications`}>← Applications</Link>
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">{app.title}</h1>
        <p className="text-muted-foreground">{app.organization}{app.deadline ? ` · deadline ${app.deadline}` : ""}</p>
        <div><Badge>{statusLabel(app.status)}</Badge></div>
      </header>

      {app.blocker && app.status === "needs_user_action" && (
        <Alert>
          <AlertTitle>NexScout needs you</AlertTitle>
          <AlertDescription>
            {app.blocker}
            {app.apply_url && (
              <>
                {" "}
                <a className="underline" href={app.apply_url} target="_blank" rel="noopener noreferrer nofollow">
                  Open the application page
                </a>
              </>
            )}
            <AssistButton appId={app.id} />
          </AlertDescription>
        </Alert>
      )}
      {app.status === "submitted" && (
        <Alert>
          <AlertTitle>Submitted</AlertTitle>
          <AlertDescription>
            {app.evidence.source === "observed"
              ? `The site confirmed it${app.evidence.reference ? ` (reference ${String(app.evidence.reference)})` : ""}.`
              : `You confirmed it${app.evidence.reference ? ` (reference ${String(app.evidence.reference)})` : ""}.`}
          </AlertDescription>
        </Alert>
      )}
      {app.status === "submission_uncertain" && (
        <Alert>
          <AlertTitle>Was it submitted?</AlertTitle>
          <AlertDescription>
            The form was sent, but the site didn&apos;t confirm it. Check your email or the site,
            then tell NexScout. It will not try again on its own.
            <div className="mt-2 flex flex-wrap items-end gap-2">
              <div className="flex flex-col gap-1">
                <Label htmlFor="ref">Reference (optional)</Label>
                <Input id="ref" value={reference} onChange={(e) => setReference(e.target.value)} className="w-48" />
              </div>
              <Button size="sm" onClick={() => resolve.mutate(true)}>Yes, it was submitted</Button>
              <Button size="sm" variant="outline" onClick={() => resolve.mutate(false)}>No, it wasn&apos;t</Button>
            </div>
            <ErrorAlert error={resolve.error} />
          </AlertDescription>
        </Alert>
      )}

      {pending.map((a) => (
        <ApprovalCard key={a.id} approval={a} caseId={caseId} />
      ))}

      {FILLABLE.has(app.status) && (
        <section aria-labelledby="fill-heading" className="flex flex-col gap-2 rounded-lg border p-4">
          <h2 id="fill-heading" className="font-semibold">Fill in the application form</h2>
          <p className="text-sm text-muted-foreground">
            NexScout opens the application page, fills it in and shows you everything before
            anything is sent. It stops if the site needs a login or a CAPTCHA.
          </p>
          <Button className="self-start" onClick={() => fill.mutate()} disabled={filling || !app.apply_url}>
            {filling ? "Filling in…" : "Fill in the form"}
          </Button>
          <ErrorAlert error={fill.error} />
        </section>
      )}

      <Details app={app} caseId={caseId} />

      {app.allowed_statuses.length > 0 && (
        <section aria-labelledby="status-heading" className="flex flex-col gap-2">
          <h2 id="status-heading" className="font-semibold">Update the status yourself</h2>
          {app.allowed_statuses.includes("submitted") && (
            <div className="flex flex-col gap-1">
              <Label htmlFor="manual-ref">Reference, if you submitted yourself (optional)</Label>
              <Input id="manual-ref" value={reference} onChange={(e) => setReference(e.target.value)} className="w-64" />
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {app.allowed_statuses.map((s) => (
              <Button key={s} size="sm" variant="outline" disabled={setStatus.isPending}
                onClick={() => setStatus.mutate(s)}>
                {STATUS_ACTION[s] ?? statusLabel(s)}
              </Button>
            ))}
          </div>
          <ErrorAlert error={setStatus.error} />
        </section>
      )}

      <RemindersPanel caseId={caseId} applicationId={app.id} />

      <Timeline app={app} />
    </div>
  );
}

/** Assisted mode: a browser window on this computer, filled by NexScout; you solve any CAPTCHA
 *  or sign-in and submit. NexScout only watches for the site's confirmation. */
function AssistButton({ appId }: { appId: string }) {
  const queryClient = useQueryClient();
  const assist = useMutation({
    mutationFn: () => autopilotApi.assist(appId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["application"] }),
  });
  return (
    <span className="mt-2 flex flex-col gap-1">
      <Button size="sm" variant="outline" className="self-start" onClick={() => assist.mutate()} disabled={assist.isPending}>
        Open a browser window for me
      </Button>
      {assist.isSuccess && (
        <span role="status" className="text-xs">
          A browser window is opening on this computer. Finish there and press submit; NexScout
          records the confirmation.
        </span>
      )}
      <ErrorAlert error={assist.error} />
    </span>
  );
}
