"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { runsApi, type ApprovalOut } from "@/lib/api/client";

/** A pending consequential action. The decision is recorded by the API, never inferred. */
export function ApprovalCard({ approval, caseId }: { approval: ApprovalOut; caseId: string }) {
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const decide = useMutation({
    mutationFn: (approve: boolean) => runsApi.decide(approval.id, approve, note),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["approvals", caseId] });
      queryClient.invalidateQueries({ queryKey: ["run", approval.run_id] });
      queryClient.invalidateQueries({ queryKey: ["runs", caseId] });
      queryClient.invalidateQueries({ queryKey: ["application"] });
      queryClient.invalidateQueries({ queryKey: ["applications", caseId] });
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
