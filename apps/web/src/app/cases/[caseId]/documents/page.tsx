"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { FormatPicker } from "@/components/document-format";
import { ErrorAlert } from "@/components/error-alert";
import { FileDropZone } from "@/components/file-drop-zone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { documentsApi, generatedApi, type DocumentOut } from "@/lib/api/client";
import { useCaseEvents, useRun } from "@/lib/live";

const PURPOSES: [string, string][] = [
  ["cv", "CV / résumé (entries will be imported for review)"],
  ["recommendation_letter", "Letter of recommendation (the recommender is added as a reference)"],
  ["transcript", "Transcript"],
  ["degree_certificate", "Degree certificate"],
  ["statement_of_purpose", "Statement of purpose"],
  ["personal_statement", "Personal statement"],
  ["research_statement", "Research statement"],
  ["research_proposal", "Research proposal"],
  ["cover_letter", "Cover letter"],
  ["writing_sample", "Writing sample"],
  ["publication", "Publication"],
  ["language_test", "Language test result"],
  ["portfolio", "Portfolio"],
  ["certificate", "Certificate"],
  ["other", "Other"],
];
const PURPOSE_LABEL = Object.fromEntries(PURPOSES.map(([k, v]) => [k, v.split(" (")[0]]));

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function ReadingStatus({ runId, caseId }: { runId: string; caseId: string }) {
  const run = useRun(runId);
  const status = run.data?.run.status;
  const result = run.data?.run.result as
    | { parse_status?: string; facts_created?: number; error?: string | null }
    | null
    | undefined;
  if (!status || !result) {
    return (
      <p role="status" className="text-sm">
        {status === "failed" ? `Reading failed: ${run.data?.run.error ?? ""}` : "Saved. Reading your document…"}
      </p>
    );
  }
  if (result.parse_status === "failed") {
    return (
      <p role="status" className="text-sm">
        Saved, but the text couldn&apos;t be read: {result.error}
      </p>
    );
  }
  const n = result.facts_created ?? 0;
  return (
    <p role="status" className="text-sm">
      {n > 0 ? `Found ${n} possible entries. ` : "Saved. No profile entries were imported from this file."}
      {n > 0 && (
        <Link className="underline" href={`/cases/${caseId}/profile#review`}>
          Review them now
        </Link>
      )}
    </p>
  );
}

const READABLE = new Set(["cv", "resume", "recommendation_letter"]);

interface UploadItem {
  name: string;
  runId?: string;
  error?: unknown;
}

export default function DocumentsPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const queryClient = useQueryClient();
  const [purpose, setPurpose] = useState("cv");
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  useCaseEvents(caseId);
  const docs = useQuery({ queryKey: ["documents", caseId], queryFn: () => documentsApi.list(caseId) });
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["documents", caseId] });
    queryClient.invalidateQueries({ queryKey: ["facts", caseId] });
  };

  const uploadDoc = useMutation({
    // One file at a time, in order, each with its own status line.
    mutationFn: async (files: File[]) => {
      setUploads(files.map((f) => ({ name: f.name })));
      for (const [i, file] of files.entries()) {
        try {
          const res = await documentsApi.upload(caseId, file, purpose);
          setUploads((u) => u.map((x, j) => (j === i ? { ...x, runId: res.run_id } : x)));
        } catch (error) {
          setUploads((u) => u.map((x, j) => (j === i ? { ...x, error } : x)));
        }
      }
    },
    onSettled: refresh,
  });
  const reread = useMutation({
    mutationFn: (id: string) => documentsApi.reread(id),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: ({ id, pending }: { id: string; pending: boolean }) =>
      documentsApi.remove(id, pending),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents", caseId] });
      queryClient.invalidateQueries({ queryKey: ["facts", caseId] });
    },
  });

  function confirmDelete(doc: DocumentOut) {
    if (!window.confirm(`Delete “${doc.filename}”? The file will be removed permanently.`)) return;
    const pending =
      doc.facts_extracted > 0 &&
      window.confirm(
        "Also remove entries imported from this file that you haven't reviewed yet? " +
          "Entries you already accepted are always kept.",
      );
    remove.mutate({ id: doc.id, pending });
  }

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Documents</h1>
        <p className="text-muted-foreground">
          Upload your CV and supporting documents. PDF, Word (.docx), Markdown, and plain text are
          supported, up to 15 MB. Your original file is kept unchanged.
        </p>
      </header>

      <section aria-label="Upload documents" className="flex flex-col gap-3 rounded-lg border p-4">
        <div className="flex flex-col gap-1">
          <Label htmlFor="doc-purpose">What is this document?</Label>
          <select
            id="doc-purpose"
            className="h-8 rounded-lg border bg-background px-2 text-sm"
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
          >
            {PURPOSES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <FileDropZone
          label={uploadDoc.isPending ? "Uploading…" : "Add documents"}
          hint="PDF, Word (.docx), Markdown or plain text, up to 15 MB each. Several at once is fine."
          accept=".pdf,.docx,.md,.markdown,.txt"
          multiple
          maxBytes={15 * 1024 * 1024}
          disabled={uploadDoc.isPending}
          onFiles={(files) => uploadDoc.mutate(files)}
        />
        <ul aria-live="polite" className="flex flex-col gap-1">
          {uploads.map((u, i) => (
            <li key={`${u.name}-${i}`} className="text-sm">
              <span className="font-medium">{u.name}: </span>
              {u.error ? (
                <ErrorAlert error={u.error} title="Upload failed" />
              ) : u.runId ? (
                <ReadingStatus runId={u.runId} caseId={caseId} />
              ) : (
                <span role="status">Uploading…</span>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="docs-heading">
        <h2 id="docs-heading" className="mb-2 text-xl font-semibold">
          Your documents
        </h2>
        {docs.isPending && <p>Loading…</p>}
        <ErrorAlert error={docs.error} />
        {docs.data && docs.data.length === 0 && (
          <p className="text-sm text-muted-foreground">No documents yet.</p>
        )}
        {docs.data && docs.data.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Uploaded documents</caption>
              <thead>
                <tr className="border-b text-left">
                  <th scope="col" className="py-2 pr-3">File</th>
                  <th scope="col" className="py-2 pr-3">Type</th>
                  <th scope="col" className="py-2 pr-3">Status</th>
                  <th scope="col" className="py-2 pr-3">Size</th>
                  <th scope="col" className="py-2 pr-3">Uploaded</th>
                  <th scope="col" className="py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {docs.data.map((d) => (
                  <tr key={d.id} className="border-b align-top">
                    <td className="py-2 pr-3 font-medium break-all">{d.filename}</td>
                    <td className="py-2 pr-3">{PURPOSE_LABEL[d.purpose] ?? d.purpose}</td>
                    <td className="py-2 pr-3">
                      {d.parse_status === "pending" ? (
                        <Badge variant="outline">Reading…</Badge>
                      ) : d.parse_status === "parsed" ? (
                        <Badge variant="secondary">
                          Read{d.page_count ? `, ${d.page_count} pages` : ""}
                          {d.facts_extracted ? `, ${d.facts_extracted} entries` : ""}
                        </Badge>
                      ) : (
                        <span title={d.parse_error ?? undefined}>
                          <Badge variant="outline">Couldn&apos;t read text</Badge>
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3">{size(d.size_bytes)}</td>
                    <td className="py-2 pr-3">{new Date(d.created_at).toLocaleDateString()}</td>
                    <td className="py-2">
                      <div className="flex gap-2">
                        <a className="underline" href={documentsApi.contentUrl(d.id)}>
                          Download
                        </a>
                        {READABLE.has(d.purpose) && d.parse_status === "parsed" && (
                          <button
                            type="button"
                            className="underline"
                            disabled={reread.isPending}
                            title="Read it again with the latest reader. Only entries you haven't reviewed are replaced."
                            onClick={() => reread.mutate(d.id)}
                          >
                            Read again
                          </button>
                        )}
                        <button
                          type="button"
                          className="underline"
                          onClick={() => confirmDelete(d)}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {reread.data && (
          <p role="status" className="mt-2 text-sm">
            Read again: {reread.data.created} new entries to review
            {reread.data.removed ? `, ${reread.data.removed} unreviewed entries replaced` : ""}.{" "}
            <Link className="underline" href={`/cases/${caseId}/profile#review`}>
              Review them
            </Link>
          </p>
        )}
        <ErrorAlert error={remove.error ?? reread.error} />
      </section>
      <ApplicationMaterials caseId={caseId} />
    </div>
  );
}

function ApplicationMaterials({ caseId }: { caseId: string }) {
  const list = useQuery({
    queryKey: ["generated", caseId],
    queryFn: () => generatedApi.list(caseId),
  });
  const [format, setFormat] = useState("");
  const assemble = useMutation({
    mutationFn: () => generatedApi.draft(caseId, { doc_type: "academic_cv", format: format || null }),
  });
  const run = useRun(assemble.data?.run_id);
  const result = run.data?.run.result as { document_id?: string } | null | undefined;
  const busy =
    assemble.isPending ||
    (!!assemble.data && !["succeeded", "failed", "cancelled"].includes(run.data?.run.status ?? ""));
  return (
    <section aria-labelledby="materials-heading" className="flex flex-col gap-3">
      <h2 id="materials-heading" className="text-xl font-semibold">Application materials</h2>
      <p className="text-sm text-muted-foreground">
        Documents NexScout prepared for you. Statements of purpose, proposals and emails are
        drafted from a position&apos;s page (PhD opportunities → Research and prepare).
      </p>
      <FormatPicker value={format} onChange={setFormat} />
      <Button variant="outline" className="self-start" onClick={() => assemble.mutate()} disabled={busy}>
        {busy ? "Assembling…" : "Create academic CV from my profile"}
      </Button>
      <div aria-live="polite">
        {result?.document_id && (
          <p role="status" className="text-sm">
            Academic CV ready.{" "}
            <Link className="underline" href={`/cases/${caseId}/documents/generated/${result.document_id}`}>
              Open it
            </Link>
          </p>
        )}
      </div>
      <ErrorAlert error={assemble.error ?? list.error} />
      {list.data && list.data.length === 0 && (
        <p className="text-sm">No application materials yet.</p>
      )}
      <ul className="flex flex-col gap-1 text-sm">
        {(list.data ?? []).map((d) => (
          <li key={d.id}>
            <Link className="underline" href={`/cases/${caseId}/documents/generated/${d.id}`}>
              {d.title}
            </Link>{" "}
            <span className="text-muted-foreground">
              {d.doc_label} · v{d.current_version} · {d.latest.placeholders.length} placeholder(s)
            </span>
            {d.latest.is_mock && <> <Badge variant="destructive">Mock text</Badge></>}
          </li>
        ))}
      </ul>
    </section>
  );
}
