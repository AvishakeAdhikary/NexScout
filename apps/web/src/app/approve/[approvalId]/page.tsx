"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ApprovalCard } from "@/components/approval-card";
import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { approvalsApi } from "@/lib/api/client";

const DONE: Record<string, string> = {
  approved: "You approved this.",
  rejected: "You rejected this. Nothing was sent.",
  cancelled: "This request was cancelled.",
};

/** Where notifications link to: one approval, decided here (or with the chat buttons). */
export default function ApprovePage() {
  const { approvalId } = useParams<{ approvalId: string }>();
  const approval = useQuery({
    queryKey: ["approval", approvalId],
    queryFn: () => approvalsApi.get(approvalId),
  });
  const a = approval.data;
  return (
    <main id="main" className="animate-page mx-auto flex w-full max-w-2xl flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold">Your decision</h1>
      <ErrorAlert error={approval.error} title="Couldn't load this request" />
      {approval.isPending && <p className="text-sm text-muted-foreground">Loading…</p>}
      {a && a.status === "pending" && <ApprovalCard approval={a} caseId={a.case_id} />}
      {a && a.status !== "pending" && (
        <article className="flex flex-col gap-2 rounded-lg border p-4" aria-label={a.title}>
          <div className="flex items-center gap-2">
            <h2 className="font-medium">{a.title}</h2>
            <Badge variant="outline">{a.status}</Badge>
          </div>
          <p className="text-sm">{DONE[a.status] ?? a.status}</p>
          {a.decision_note && <p className="text-xs text-muted-foreground">{a.decision_note}</p>}
        </article>
      )}
      {a && (
        <Link href={`/cases/${a.case_id}/activity`} className="text-sm underline">
          See all activity for this case
        </Link>
      )}
    </main>
  );
}
