"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { runsApi } from "@/lib/api/client";
import { useRun } from "@/lib/live";

/** Starts the `profile_summary` workflow. The draft arrives as a pending entry to review. */
export function DraftSummary({ caseId }: { caseId: string }) {
  const queryClient = useQueryClient();
  const start = useMutation({ mutationFn: () => runsApi.start(caseId, "profile_summary") });
  const run = useRun(start.data?.id);
  const status = run.data?.run.status;
  const result = run.data?.run.result as { status?: string; message?: string } | null | undefined;
  useEffect(() => {
    if (status === "succeeded") queryClient.invalidateQueries({ queryKey: ["facts", caseId] });
  }, [status, caseId, queryClient]);
  const busy =
    start.isPending ||
    (!!start.data && !["succeeded", "failed", "cancelled"].includes(status ?? ""));

  return (
    <section aria-labelledby="draft-heading" className="rounded-lg border p-4">
      <h2 id="draft-heading" className="font-semibold">
        Professional summary
      </h2>
      <p className="text-sm text-muted-foreground">
        An AI model drafts a short summary from your confirmed entries and cites each one. Sentences
        your entries don&apos;t support are removed. The draft waits for your review. Choose your
        model in{" "}
        <Link className="underline" href={`/cases/${caseId}/settings`}>
          Settings
        </Link>
        ; until you do, a built-in mock writes clearly labelled test text.
      </p>
      <Button className="mt-2" onClick={() => start.mutate()} disabled={busy}>
        {busy ? "Drafting…" : "Draft a summary with AI"}
      </Button>
      <div aria-live="polite" className="mt-2 text-sm">
        {status === "waiting_approval" && (
          <p role="status">
            Waiting for your permission to send entries to the model.{" "}
            <Link className="underline" href={`/cases/${caseId}/activity`}>
              Review the request
            </Link>
          </p>
        )}
        {status === "succeeded" && (
          <p role="status">
            {result?.status === "drafted" ? (
              <>
                Draft ready.{" "}
                <a className="underline" href="#review">
                  Review it
                </a>
              </>
            ) : (
              (result?.message ?? "Finished.")
            )}
          </p>
        )}
        {(status === "failed" || status === "cancelled") && (
          <p role="alert" className="text-destructive">
            {status === "failed"
              ? `Couldn't draft: ${run.data?.run.error ?? "unknown error"}`
              : "Cancelled."}
          </p>
        )}
      </div>
      <ErrorAlert error={start.error} />
    </section>
  );
}
