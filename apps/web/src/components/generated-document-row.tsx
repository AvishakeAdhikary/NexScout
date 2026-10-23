"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, type ReactNode } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { generatedApi, type GeneratedDocumentOut } from "@/lib/api/client";
import { useRun } from "@/lib/live";

const FINISHED = new Set(["succeeded", "failed", "cancelled"]);

/** One generated document with what can be done to it right here: fill in the details the
 *  user already gave NexScout, create its PDF, download, open, delete. `select` is an optional
 *  control in front of the title (the application page's "upload this" checkbox). */
export function GeneratedDocumentRow({
  doc,
  caseId,
  select,
}: {
  doc: GeneratedDocumentOut;
  caseId: string;
  select?: ReactNode;
}) {
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["generated", caseId] });
    void queryClient.invalidateQueries({ queryKey: ["generated-doc", doc.id] });
    void queryClient.invalidateQueries({ queryKey: ["application"] });
  };
  const fill = useMutation({ mutationFn: () => generatedApi.fill(doc.id), onSuccess: refresh });
  const render = useMutation({ mutationFn: () => generatedApi.render(doc.id) });
  const run = useRun(render.data?.run_id);
  const status = run.data?.run.status;
  useEffect(() => {
    if (status === "succeeded") refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refresh once per finished render
  }, [status]);
  const remove = useMutation({ mutationFn: () => generatedApi.remove(doc.id), onSuccess: refresh });
  const rendering = render.isPending || (!!render.data && !FINISHED.has(status ?? ""));
  const left = doc.latest.placeholders.length;
  const ready = doc.latest.has_files;

  return (
    <li className="flex flex-col gap-1 rounded-md border p-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        {select}
        <Link
          className="font-medium underline"
          href={`/cases/${caseId}/documents/generated/${doc.id}`}
        >
          {doc.title}
        </Link>
        <span className="text-xs text-muted-foreground">v{doc.current_version}</span>
        {doc.latest.is_mock && <Badge variant="destructive">Mock text</Badge>}
        {left > 0 ? (
          <Badge variant="outline">{left} placeholder(s) to fill</Badge>
        ) : ready ? (
          <Badge variant="outline">PDF ready</Badge>
        ) : (
          <Badge variant="outline">No PDF yet</Badge>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {left > 0 && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={fill.isPending}
            onClick={() => fill.mutate()}
          >
            Fill in my details
          </Button>
        )}
        {!ready && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={rendering}
            onClick={() => render.mutate()}
          >
            {rendering ? "Making the PDF…" : "Make PDF"}
          </Button>
        )}
        {ready && (
          <a className="underline" href={generatedApi.fileUrl(doc.id, doc.current_version, "pdf")}>
            Download PDF
          </a>
        )}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={remove.isPending}
          aria-label={`Delete ${doc.title}`}
          onClick={() => {
            if (window.confirm(`Delete “${doc.title}” with all its versions and files?`))
              remove.mutate();
          }}
        >
          Delete
        </Button>
      </div>
      {fill.data && (
        <p role="status" className="text-xs">
          {fill.data.filled > 0
            ? `Filled in ${fill.data.filled}. ${fill.data.placeholders_left > 0 ? `${fill.data.placeholders_left} left: open the document to write them.` : "Nothing left to fill."}`
            : "Nothing NexScout knows fits these placeholders yet. Add your contact details on the Profile page, or open the document to write them."}
        </p>
      )}
      {status === "failed" && (
        <p role="alert" className="text-xs text-destructive">
          {run.data?.run.error}
        </p>
      )}
      <ErrorAlert error={fill.error ?? render.error ?? remove.error} />
    </li>
  );
}
