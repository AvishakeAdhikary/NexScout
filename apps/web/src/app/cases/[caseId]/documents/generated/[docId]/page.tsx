"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ComplianceList } from "@/components/document-format";
import { ErrorAlert } from "@/components/error-alert";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { generatedApi, type GeneratedDocumentDetailOut, type VersionOut } from "@/lib/api/client";
import { useCaseEvents, useRun } from "@/lib/live";

type Report = {
  claims?: { text: string; fact_ids: string[] }[];
  position?: { text: string; finding_ids: string[] }[];
  to_check?: { text: string; reason: string }[];
  removed?: { text: string; kind: string; reason: string }[];
  missing_sections?: string[];
  assembled?: boolean;
  edited_from?: number;
};
type FileInfo = {
  size?: number;
  checks?: { ok?: boolean; pages?: number; headings_missing?: string[] };
};

function OriginBadges({ v }: { v: VersionOut }) {
  return (
    <span className="flex flex-wrap gap-1">
      {v.is_mock && <Badge variant="destructive">Mock text, not written by AI</Badge>}
      {v.origin === "assembled" && (
        <Badge variant="outline">Assembled from your entries (no AI)</Badge>
      )}
      {v.origin === "generated" && !v.is_mock && (
        <Badge variant="outline">Drafted by {v.model ?? "AI"}</Badge>
      )}
      {v.origin === "user_edit" && <Badge variant="outline">Edited by you</Badge>}
    </span>
  );
}

function ReportPanel({ report }: { report: Report }) {
  if (report.edited_from) {
    return (
      <p className="text-sm text-muted-foreground">
        You edited this version (from version {report.edited_from}). Your own text isn&apos;t
        re-checked; make sure every statement is true.
      </p>
    );
  }
  const removed = report.removed ?? [];
  const toCheck = report.to_check ?? [];
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p>
        {report.claims?.length ?? 0} statement(s) about you are backed by your confirmed entries
        {report.position?.length
          ? `; ${report.position.length} about the position by its research`
          : ""}
        .
      </p>
      {removed.length > 0 && (
        <details open>
          <summary className="cursor-pointer font-medium">
            Removed because nothing supports them ({removed.length})
          </summary>
          <ul className="mt-1 list-disc pl-5">
            {removed.map((r, i) => (
              <li key={i}>
                “{r.text}” <span className="text-muted-foreground">({r.reason})</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {toCheck.length > 0 && (
        <details>
          <summary className="cursor-pointer font-medium">
            Written for you, check these ({toCheck.length})
          </summary>
          <ul className="mt-1 list-disc pl-5">
            {toCheck.map((r, i) => (
              <li key={i}>“{r.text}”</li>
            ))}
          </ul>
        </details>
      )}
      {report.missing_sections && report.missing_sections.length > 0 && (
        <p>Sections with nothing to say yet: {report.missing_sections.join(", ")}.</p>
      )}
    </div>
  );
}

function Files({ doc, v }: { doc: GeneratedDocumentDetailOut; v: VersionOut }) {
  const queryClient = useQueryClient();
  const render = useMutation({ mutationFn: () => generatedApi.render(doc.id, v.number) });
  const run = useRun(render.data?.run_id);
  const status = run.data?.run.status;
  useEffect(() => {
    if (status === "succeeded")
      queryClient.invalidateQueries({ queryKey: ["generated-doc", doc.id] });
  }, [status, doc.id, queryClient]);
  const files = v.files as {
    pdf?: FileInfo;
    docx?: FileInfo;
    compliance?: {
      status?: string;
      checks?: { rule: string; ok: boolean; severity: string; source: string; detail: string }[];
    };
  };
  const busy =
    render.isPending ||
    (!!render.data && !["succeeded", "failed", "cancelled"].includes(status ?? ""));
  if (v.has_files && files.pdf && files.docx) {
    return (
      <div className="flex flex-col gap-1 text-sm">
        <div className="flex flex-wrap gap-3">
          <a className="underline" href={generatedApi.fileUrl(doc.id, v.number, "pdf")}>
            Download PDF
          </a>
          <a className="underline" href={generatedApi.fileUrl(doc.id, v.number, "docx")}>
            Download Word (.docx)
          </a>
        </div>
        <p className="text-xs text-muted-foreground">
          {files.pdf.checks?.ok && files.docx.checks?.ok
            ? `Both files were opened and checked (PDF: ${files.pdf.checks.pages} page(s)).`
            : "A file check failed: some headings are missing from the output."}
        </p>
        <ComplianceList compliance={files.compliance} />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1">
      <Button
        className="self-start"
        variant="outline"
        onClick={() => render.mutate()}
        disabled={busy}
      >
        {busy ? "Creating files…" : "Create PDF and Word files"}
      </Button>
      {status === "failed" && (
        <p role="alert" className="text-sm text-destructive">
          {run.data?.run.error}
        </p>
      )}
      <ErrorAlert error={render.error} />
    </div>
  );
}

function Editor({ doc, onSaved }: { doc: GeneratedDocumentDetailOut; onSaved: () => void }) {
  const [text, setText] = useState(doc.current.markdown);
  const save = useMutation({
    mutationFn: () => generatedApi.saveEdit(doc.id, text, doc.current_version),
    onSuccess: onSaved,
  });
  const dirty = text !== doc.current.markdown;
  const left = (text.match(/\[\[PLACEHOLDER:[^\]]*\]\]/g) ?? []).length;
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor="md">Text (Markdown)</Label>
      <textarea
        id="md"
        className="min-h-[28rem] w-full rounded-lg border bg-background p-3 font-mono text-sm"
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
          Save as new version
        </Button>
        {dirty && <span className="text-sm text-muted-foreground">Unsaved changes</span>}
        <span className="text-sm" aria-live="polite">
          {left} placeholder(s) left
        </span>
      </div>
      <ErrorAlert error={save.error} />
    </div>
  );
}

/** Fill in the contact details and saved answers the user already gave, as a new version. */
function FillDetails({ docId }: { docId: string }) {
  const queryClient = useQueryClient();
  const fill = useMutation({
    mutationFn: () => generatedApi.fill(docId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["generated-doc", docId] }),
  });
  return (
    <span className="mt-2 flex flex-col gap-1">
      <Button
        size="sm"
        variant="outline"
        className="self-start"
        disabled={fill.isPending}
        onClick={() => fill.mutate()}
      >
        Fill in my details
      </Button>
      {fill.data && fill.data.filled === 0 && (
        <span role="status" className="text-xs">
          Nothing NexScout knows fits these yet. Add your contact details on the Profile page, or
          write them in below.
        </span>
      )}
      <ErrorAlert error={fill.error} />
    </span>
  );
}

export default function GeneratedDocumentPage() {
  const { caseId, docId } = useParams<{ caseId: string; docId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  useCaseEvents(caseId);
  const doc = useQuery({
    queryKey: ["generated-doc", docId],
    queryFn: () => generatedApi.get(docId),
  });
  const [viewing, setViewing] = useState<number | null>(null);
  const older = useQuery({
    queryKey: ["generated-version", docId, viewing],
    queryFn: () => generatedApi.version(docId, viewing!),
    enabled: viewing !== null,
  });
  const remove = useMutation({
    mutationFn: () => generatedApi.remove(docId),
    onSuccess: () => router.push(`/cases/${caseId}/documents`),
  });

  if (doc.isPending) return <p>Loading…</p>;
  if (doc.error) return <ErrorAlert error={doc.error} />;
  const d = doc.data;
  const v = d.current;
  const shown = viewing !== null && older.data ? older.data : null;
  const fmt = (v.report as { format?: { label: string; reason?: string; paper?: string } }).format;

  return (
    <div className="flex max-w-4xl flex-col gap-5">
      <Link className="text-sm underline" href={`/cases/${caseId}/documents`}>
        ← Documents
      </Link>
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">{d.title}</h1>
        <p className="text-sm text-muted-foreground">
          {d.doc_label} · version {d.current_version}
          {d.opportunity_id && (
            <>
              {" · "}
              <Link
                className="underline"
                href={`/cases/${caseId}/${["resume", "cover_letter", "referral_request"].includes(d.doc_type) ? "jobs" : "phd"}/${d.opportunity_id}`}
              >
                position
              </Link>
            </>
          )}
        </p>
        <OriginBadges v={v} />
        {fmt && (
          <p className="text-sm text-muted-foreground">
            Format: <span className="font-medium text-foreground">{fmt.label}</span> · {fmt.paper}{" "}
            paper
            {fmt.reason ? ` · ${fmt.reason}` : ""}
          </p>
        )}
      </header>

      {v.placeholders.length > 0 && (
        <Alert>
          <AlertTitle>Not ready to send</AlertTitle>
          <AlertDescription>
            {v.placeholders.length} placeholder(s) need your input: {v.placeholders.join("; ")}.
            <FillDetails docId={d.id} />
          </AlertDescription>
        </Alert>
      )}

      <section aria-labelledby="check-heading" className="rounded-lg border p-4">
        <h2 id="check-heading" className="mb-2 font-semibold">
          Fact check
        </h2>
        <ReportPanel report={v.report as Report} />
      </section>

      <section aria-labelledby="files-heading" className="rounded-lg border p-4">
        <h2 id="files-heading" className="mb-2 font-semibold">
          Files (version {v.number})
        </h2>
        <Files doc={d} v={v} />
      </section>

      <section aria-labelledby="edit-heading" className="flex flex-col gap-2">
        <h2 id="edit-heading" className="font-semibold">
          Edit
        </h2>
        <Editor
          key={d.current_version}
          doc={d}
          onSaved={() => queryClient.invalidateQueries({ queryKey: ["generated-doc", docId] })}
        />
      </section>

      <section aria-labelledby="versions-heading" className="flex flex-col gap-2">
        <h2 id="versions-heading" className="font-semibold">
          Versions
        </h2>
        <ul className="flex flex-col gap-1 text-sm">
          {[...d.versions].reverse().map((ver) => (
            <li key={ver.number} className="flex flex-wrap items-center gap-2">
              <span>
                Version {ver.number} · {new Date(ver.created_at).toLocaleString()} ·{" "}
                {ver.origin === "user_edit" ? "your edit" : ver.origin} · {ver.placeholders.length}{" "}
                placeholder(s)
              </span>
              {ver.number !== d.current_version && (
                <button type="button" className="underline" onClick={() => setViewing(ver.number)}>
                  View
                </button>
              )}
            </li>
          ))}
        </ul>
        {shown && (
          <div className="rounded-lg border p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="font-medium">Version {shown.number} (read only)</span>
              <button type="button" className="underline text-sm" onClick={() => setViewing(null)}>
                Close
              </button>
            </div>
            <pre className="whitespace-pre-wrap text-sm">{shown.markdown}</pre>
          </div>
        )}
      </section>

      <div>
        <Button
          variant="outline"
          onClick={() => {
            if (window.confirm("Delete this document and all its versions and files?"))
              remove.mutate();
          }}
        >
          Delete document
        </Button>
        <ErrorAlert error={remove.error} />
      </div>
    </div>
  );
}
