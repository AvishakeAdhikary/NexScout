"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { trackingApi } from "@/lib/api/client";
import { APPLICATION_STATUS, STATUS_ACTION, statusLabel } from "@/lib/application-status";
import { useCaseEvents } from "@/lib/live";

const BULK = ["tracking", "completed", "rejected", "withdrawn", "cancelled", "paused"];

export default function ApplicationsPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const queryClient = useQueryClient();
  useCaseEvents(caseId);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("updated");
  const [selected, setSelected] = useState<string[]>([]);
  const [bulkTo, setBulkTo] = useState("tracking");
  const list = useQuery({
    queryKey: ["applications", caseId, status, q, sort],
    queryFn: () => trackingApi.listApplications(caseId, { status, q, sort }),
  });
  const bulk = useMutation({
    mutationFn: () => trackingApi.bulkStatus(caseId, selected, bulkTo),
    onSuccess: () => {
      setSelected([]);
      queryClient.invalidateQueries({ queryKey: ["applications", caseId] });
    },
  });
  const rows = list.data ?? [];
  const allChecked = rows.length > 0 && rows.every((a) => selected.includes(a.id));

  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Applications</h1>
        <p className="text-muted-foreground">
          Every application you started, where it stands, and what it needs from you. NexScout
          never submits anything without your approval.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor="f-status">Status</Label>
          <select id="f-status" className="h-8 rounded-lg border bg-background px-2 text-sm"
            value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {Object.entries(APPLICATION_STATUS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="f-q">Search</Label>
          <Input id="f-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Title or organization" className="w-56" />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="f-sort">Sort by</Label>
          <select id="f-sort" className="h-8 rounded-lg border bg-background px-2 text-sm"
            value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="updated">Last change</option>
            <option value="deadline">Deadline</option>
          </select>
        </div>
        <a className="ml-auto text-sm underline" href={trackingApi.exportUrl(caseId)}>Export CSV</a>
      </div>

      {list.isPending && <p>Loading…</p>}
      <ErrorAlert error={list.error} />
      {list.data && rows.length === 0 && (
        <p className="text-sm">
          {status || q ? "No applications match." : "No applications yet. Start one from a position's “Research and prepare” page."}
        </p>
      )}
      {rows.length > 0 && (
        <>
          <div className="flex flex-wrap items-end gap-2" aria-live="polite">
            <span className="text-sm">{selected.length} selected</span>
            <Label htmlFor="bulk-to" className="sr-only">Change selected to</Label>
            <select id="bulk-to" className="h-8 rounded-lg border bg-background px-2 text-sm"
              value={bulkTo} onChange={(e) => setBulkTo(e.target.value)}>
              {BULK.map((s) => (
                <option key={s} value={s}>{STATUS_ACTION[s] ?? statusLabel(s)}</option>
              ))}
            </select>
            <Button size="sm" variant="outline" disabled={selected.length === 0 || bulk.isPending}
              onClick={() => bulk.mutate()}>
              Apply to selected
            </Button>
          </div>
          {bulk.data && bulk.data.some((r) => !r.ok) && (
            <p role="alert" className="text-sm text-destructive">
              {bulk.data.filter((r) => !r.ok).length} couldn&apos;t change:{" "}
              {[...new Set(bulk.data.filter((r) => !r.ok).map((r) => r.error))].join("; ")}
            </p>
          )}
          <ErrorAlert error={bulk.error} />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Your applications</caption>
              <thead>
                <tr className="border-b text-left">
                  <th scope="col" className="py-2 pr-2">
                    <input type="checkbox" aria-label="Select all" checked={allChecked}
                      onChange={(e) => setSelected(e.target.checked ? rows.map((a) => a.id) : [])} />
                  </th>
                  <th scope="col" className="py-2 pr-3">Position</th>
                  <th scope="col" className="py-2 pr-3">Status</th>
                  <th scope="col" className="py-2 pr-3">Deadline</th>
                  <th scope="col" className="py-2">Last change</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id} className="border-b align-top">
                    <td className="py-2 pr-2">
                      <input type="checkbox" aria-label={`Select ${a.title}`} checked={selected.includes(a.id)}
                        onChange={(e) => setSelected(e.target.checked ? [...selected, a.id] : selected.filter((x) => x !== a.id))} />
                    </td>
                    <td className="py-2 pr-3">
                      <Link className="underline" href={`/cases/${caseId}/applications/${a.id}`}>{a.title}</Link>
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
        </>
      )}
    </div>
  );
}
