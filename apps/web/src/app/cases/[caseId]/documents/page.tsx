"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { documentsApi, type DocumentOut } from "@/lib/api/client";

const PURPOSES: [string, string][] = [
  ["cv", "CV / résumé (entries will be imported for review)"],
  ["transcript", "Transcript"],
  ["degree_certificate", "Degree certificate"],
  ["statement_of_purpose", "Statement of purpose"],
  ["personal_statement", "Personal statement"],
  ["research_statement", "Research statement"],
  ["research_proposal", "Research proposal"],
  ["cover_letter", "Cover letter"],
  ["recommendation_letter", "Letter of recommendation"],
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

export default function DocumentsPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [purpose, setPurpose] = useState("cv");
  const docs = useQuery({ queryKey: ["documents", caseId], queryFn: () => documentsApi.list(caseId) });

  const uploadDoc = useMutation({
    mutationFn: (file: File) => documentsApi.upload(caseId, file, purpose),
    onSuccess: () => {
      if (fileRef.current) fileRef.current.value = "";
      queryClient.invalidateQueries({ queryKey: ["documents", caseId] });
      queryClient.invalidateQueries({ queryKey: ["facts", caseId] });
    },
  });
  const remove = useMutation({
    mutationFn: ({ id, pending }: { id: string; pending: boolean }) =>
      documentsApi.remove(id, pending),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["documents", caseId] });
      queryClient.invalidateQueries({ queryKey: ["facts", caseId] });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (file) uploadDoc.mutate(file);
  }

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

      <form onSubmit={submit} className="flex flex-col gap-3 rounded-lg border p-4">
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
        <div className="flex flex-col gap-1">
          <Label htmlFor="doc-file">File</Label>
          <input
            id="doc-file"
            ref={fileRef}
            type="file"
            required
            accept=".pdf,.docx,.md,.markdown,.txt,application/pdf,text/plain,text/markdown"
            className="text-sm"
          />
        </div>
        <Button type="submit" disabled={uploadDoc.isPending} className="self-start">
          {uploadDoc.isPending ? "Uploading and reading…" : "Upload"}
        </Button>
        <div aria-live="polite">
          {uploadDoc.data && (
            <p role="status" className="text-sm">
              {uploadDoc.data.document.parse_status === "failed"
                ? `Saved, but the text couldn't be read: ${uploadDoc.data.document.parse_error}`
                : uploadDoc.data.facts_created > 0
                  ? `Found ${uploadDoc.data.facts_created} possible entries. `
                  : "Saved. No profile entries were imported from this file."}
              {uploadDoc.data.facts_created > 0 && (
                <Link className="underline" href={`/cases/${caseId}/profile#review`}>
                  Review them now
                </Link>
              )}
            </p>
          )}
        </div>
        <ErrorAlert error={uploadDoc.error} title="Upload failed" />
      </form>

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
                      {d.parse_status === "parsed" ? (
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
        <ErrorAlert error={remove.error} />
      </section>
    </div>
  );
}
