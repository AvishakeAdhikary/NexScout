"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { applicationsApi } from "@/lib/api/client";
import { statusLabel } from "@/lib/application-status";
import { useCaseEvents } from "@/lib/live";

export default function ApplicationsPage() {
  const { caseId } = useParams<{ caseId: string }>();
  useCaseEvents(caseId);
  const list = useQuery({ queryKey: ["applications", caseId], queryFn: () => applicationsApi.list(caseId) });

  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Applications</h1>
        <p className="text-muted-foreground">
          Every application you started, where it stands, and what it needs from you. NexScout
          never submits anything without your approval.
        </p>
      </header>
      {list.isPending && <p>Loading…</p>}
      <ErrorAlert error={list.error} />
      {list.data && list.data.length === 0 && (
        <p className="text-sm">
          No applications yet. Start one from a position&apos;s “Research and prepare” page.
        </p>
      )}
      {list.data && list.data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Your applications</caption>
            <thead>
              <tr className="border-b text-left">
                <th scope="col" className="py-2 pr-3">Position</th>
                <th scope="col" className="py-2 pr-3">Status</th>
                <th scope="col" className="py-2 pr-3">Deadline</th>
                <th scope="col" className="py-2">Last change</th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((a) => (
                <tr key={a.id} className="border-b align-top">
                  <td className="py-2 pr-3">
                    <Link className="underline" href={`/cases/${caseId}/applications/${a.id}`}>
                      {a.title}
                    </Link>
                    <div className="text-xs text-muted-foreground">{a.organization}</div>
                  </td>
                  <td className="py-2 pr-3">
                    <Badge variant={a.status === "needs_user_action" || a.status === "submission_uncertain" ? "destructive" : "outline"}>
                      {statusLabel(a.status)}
                    </Badge>
                  </td>
                  <td className="py-2 pr-3">{a.deadline ?? "—"}</td>
                  <td className="py-2">{new Date(a.updated_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
