"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { relationshipsApi, type AffiliationOut } from "@/lib/api/client";

const TYPES: [string, string][] = [
  ["alumnus", "Alumnus / alumna"],
  ["former_employee", "Former employee"],
  ["current_employee", "Current employee"],
  ["researcher", "Researcher"],
  ["collaborator", "Collaborator"],
  ["co_author", "Co-author"],
  ["supervisor", "Supervisor"],
  ["mentor", "Mentor"],
  ["colleague", "Colleague"],
  ["association_member", "Association member"],
  ["authorized_referrer", "Has agreed to refer me"],
  ["other", "Other"],
];
const TYPE_LABEL = Object.fromEntries(TYPES);

function PermissionToggle({
  row,
  field,
  label,
  caseId,
}: {
  row: AffiliationOut;
  field: "may_use_in_applications" | "may_use_for_referral";
  label: string;
  caseId: string;
}) {
  const queryClient = useQueryClient();
  const update = useMutation({
    mutationFn: (value: boolean) =>
      relationshipsApi.updateAffiliation(row.id, { version: row.version, [field]: value }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["affiliations", caseId] }),
  });
  return (
    <label className="flex items-center gap-1 text-xs">
      <input
        type="checkbox"
        checked={row[field]}
        disabled={update.isPending}
        onChange={(e) => update.mutate(e.target.checked)}
      />
      {label}
    </label>
  );
}

export default function RelationshipsPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const queryClient = useQueryClient();
  const rows = useQuery({
    queryKey: ["affiliations", caseId],
    queryFn: () => relationshipsApi.affiliations(caseId),
  });
  const [formKey, setFormKey] = useState(0);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["affiliations", caseId] });
  const create = useMutation({
    mutationFn: (body: Parameters<typeof relationshipsApi.createAffiliation>[1]) =>
      relationshipsApi.createAffiliation(caseId, body),
    onSuccess: () => {
      setFormKey((k) => k + 1);
      invalidate();
    },
  });
  const remove = useMutation({
    mutationFn: relationshipsApi.removeAffiliation,
    onSuccess: invalidate,
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const get = (k: string) => String(f.get(k) ?? "").trim() || null;
    create.mutate({
      person_name: get("person_name"),
      organization: get("organization"),
      relationship_type: get("relationship_type"),
      role: get("role"),
      start_date: get("start_date"),
      end_date: get("end_date"),
      status: get("status") ?? "current",
      evidence: get("evidence"),
      notes: get("notes"),
      may_use_in_applications: f.get("may_use_in_applications") === "on",
      may_use_for_referral: f.get("may_use_for_referral") === "on",
    });
  }

  return (
    <div className="flex max-w-5xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Relationships</h1>
        <p className="text-muted-foreground">
          Organizations you are connected to, and people who know your work. A connection is not a
          recommendation: NexScout only mentions a relationship in an application, or suggests
          asking for a referral, when you allow it below.
        </p>
      </header>

      {rows.isPending && <p>Loading…</p>}
      <ErrorAlert error={rows.error} />
      {rows.data && rows.data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Your relationships</caption>
            <thead>
              <tr className="border-b text-left">
                <th scope="col" className="py-2 pr-3">
                  Person
                </th>
                <th scope="col" className="py-2 pr-3">
                  Organization
                </th>
                <th scope="col" className="py-2 pr-3">
                  Relationship
                </th>
                <th scope="col" className="py-2 pr-3">
                  Dates
                </th>
                <th scope="col" className="py-2 pr-3">
                  Permissions
                </th>
                <th scope="col" className="py-2">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.data.map((r) => (
                <tr key={r.id} className="border-b align-top">
                  <td className="py-2 pr-3">{r.person_name ?? "You"}</td>
                  <td className="py-2 pr-3">
                    {r.organization}
                    {r.role && <div className="text-xs text-muted-foreground">{r.role}</div>}
                  </td>
                  <td className="py-2 pr-3">
                    {TYPE_LABEL[r.relationship_type] ?? r.relationship_type}
                    <div className="text-xs text-muted-foreground">{r.status}</div>
                  </td>
                  <td className="py-2 pr-3">
                    {[r.start_date, r.end_date].filter(Boolean).join(" – ") || "—"}
                  </td>
                  <td className="py-2 pr-3">
                    <div className="flex flex-col gap-1">
                      <PermissionToggle
                        row={r}
                        field="may_use_in_applications"
                        caseId={caseId}
                        label="Mention in applications"
                      />
                      <PermissionToggle
                        row={r}
                        field="may_use_for_referral"
                        caseId={caseId}
                        label="May suggest a referral request"
                      />
                    </div>
                  </td>
                  <td className="py-2">
                    <button
                      type="button"
                      className="underline"
                      onClick={() => {
                        if (window.confirm(`Delete relationship with ${r.organization}?`))
                          remove.mutate(r.id);
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.data && rows.data.length === 0 && (
        <p className="text-sm text-muted-foreground">No relationships yet.</p>
      )}
      <ErrorAlert error={remove.error} />

      <section aria-labelledby="add-rel" className="rounded-lg border p-4">
        <h2 id="add-rel" className="mb-3 text-lg font-semibold">
          Add a relationship
        </h2>
        <form key={formKey} onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="rel-person">Person (leave blank if it&apos;s you)</Label>
            <Input id="rel-person" name="person_name" maxLength={200} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rel-org">Organization *</Label>
            <Input id="rel-org" name="organization" required maxLength={300} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rel-type">Relationship *</Label>
            <select
              id="rel-type"
              name="relationship_type"
              required
              className="h-8 rounded-lg border bg-background px-2 text-sm"
              defaultValue="alumnus"
            >
              {TYPES.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rel-role">Role or title</Label>
            <Input id="rel-role" name="role" maxLength={200} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rel-start">Start (YYYY or YYYY-MM)</Label>
            <Input id="rel-start" name="start_date" maxLength={10} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rel-end">End (YYYY-MM or present)</Label>
            <Input id="rel-end" name="end_date" maxLength={10} />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rel-status">Status</Label>
            <select
              id="rel-status"
              name="status"
              defaultValue="current"
              className="h-8 rounded-lg border bg-background px-2 text-sm"
            >
              <option value="current">Current</option>
              <option value="former">Former</option>
              <option value="unknown">Unknown</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rel-evidence">Evidence (e.g. a link or document name)</Label>
            <Input id="rel-evidence" name="evidence" maxLength={2000} />
          </div>
          <div className="flex flex-col gap-1 sm:col-span-2">
            <Label htmlFor="rel-notes">Notes</Label>
            <Input id="rel-notes" name="notes" maxLength={2000} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="may_use_in_applications" />
            May be mentioned in my applications
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="may_use_for_referral" />
            NexScout may suggest asking this person for a referral or introduction
          </label>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Adding…" : "Add relationship"}
            </Button>
          </div>
        </form>
        <ErrorAlert error={create.error} title="Couldn't add the relationship" />
      </section>
    </div>
  );
}
