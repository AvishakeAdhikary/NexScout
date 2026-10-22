"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { FactForm } from "@/components/fact-form";
import { Button, buttonVariants } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  casesApi,
  documentsApi,
  factsApi,
  type FactBulkAction,
  type FactOut,
  type Section,
} from "@/lib/api/client";
import { LINK_TARGETS, SECTION_LABELS, SECTION_ORDER } from "@/lib/profile-schema";

import { DraftSummary } from "./draft-summary";
import { FactCard } from "./fact-card";
import { LinksPanel } from "./links-panel";
import { PreferencesPanel } from "./preferences-panel";

function groupBySection(facts: FactOut[]): [Section, FactOut[]][] {
  const groups = new Map<Section, FactOut[]>();
  for (const f of facts) groups.set(f.section, [...(groups.get(f.section) ?? []), f]);
  return SECTION_ORDER.filter((s) => groups.has(s)).map((s) => [s, groups.get(s)!]);
}

export default function ProfilePage() {
  const { caseId } = useParams<{ caseId: string }>();
  const queryClient = useQueryClient();
  const facts = useQuery({ queryKey: ["facts", caseId], queryFn: () => factsApi.list(caseId) });
  const gaps = useQuery({ queryKey: ["gaps", caseId], queryFn: () => factsApi.gaps(caseId) });
  const documents = useQuery({
    queryKey: ["documents", caseId],
    queryFn: () => documentsApi.list(caseId),
  });
  const [addSection, setAddSection] = useState<Section>("education");
  const [formKey, setFormKey] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["facts", caseId] });
    queryClient.invalidateQueries({ queryKey: ["gaps", caseId] });
  };
  const acceptAll = useMutation({
    mutationFn: (ids: string[]) => factsApi.review(caseId, ids, []),
    onSuccess: invalidate,
  });
  const bulk = useMutation({
    mutationFn: (action: FactBulkAction) => factsApi.bulk(caseId, action, [...selected]),
    onSuccess: () => {
      setSelected(new Set());
      invalidate();
    },
  });
  // Unreviewed suggestions whose file was deleted (the user kept them at the time). Offered for
  // removal in one click, since the file can no longer be checked against them.
  const leftovers = useMemo(() => {
    if (!documents.data || !facts.data) return [];
    const present = new Set(documents.data.map((d) => d.id));
    return facts.data.filter(
      (f) =>
        f.review_state === "pending" &&
        !f.meta.edited_by_user &&
        typeof f.meta.document_id === "string" &&
        !present.has(f.meta.document_id),
    );
  }, [documents.data, facts.data]);
  const removeLeftovers = useMutation({
    mutationFn: async (ids: string[]) => {
      for (let i = 0; i < ids.length; i += 500) {
        await factsApi.bulk(caseId, "delete", ids.slice(i, i + 500));
      }
    },
    onSuccess: invalidate,
  });
  const labels = useMemo(
    () => Object.fromEntries((facts.data ?? []).map((f) => [f.id, f.label])),
    [facts.data],
  );
  const linkOptions = useMemo(
    () =>
      (facts.data ?? [])
        .filter((f) => LINK_TARGETS.has(f.section) && f.review_state !== "rejected")
        .map((f) => ({ id: f.id, label: f.label })),
    [facts.data],
  );
  const select = (id: string, on: boolean) =>
    setSelected((s) => {
      const next = new Set(s);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const selectGroup = (ids: string[], on: boolean) =>
    setSelected((s) => {
      const next = new Set(s);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  const card = (f: FactOut) => (
    <FactCard
      key={f.id}
      fact={f}
      caseId={caseId}
      labels={labels}
      linkOptions={linkOptions}
      selected={selected.has(f.id)}
      onSelect={(on) => select(f.id, on)}
    />
  );
  const groupToggle = (items: FactOut[]) => {
    const all = items.every((i) => selected.has(i.id));
    return (
      <Button size="sm" variant="ghost" onClick={() => selectGroup(items.map((i) => i.id), !all)}>
        {all ? "Unselect all" : "Select all"}
      </Button>
    );
  };
  const create = useMutation({
    mutationFn: (data: Record<string, unknown>) => factsApi.create(caseId, addSection, data),
    onSuccess: () => {
      setFormKey((k) => k + 1);
      invalidate();
    },
  });

  const pending = facts.data?.filter((f) => f.review_state === "pending") ?? [];
  const accepted = facts.data?.filter((f) => f.review_state === "accepted") ?? [];
  const rejected = facts.data?.filter((f) => f.review_state === "rejected") ?? [];

  return (
    <div className="flex max-w-4xl flex-col gap-8">
      <header>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-2xl font-semibold">My Profile</h1>
          <div className="flex flex-wrap gap-2 text-sm">
            <a className={buttonVariants({ variant: "outline", size: "sm" })} href={casesApi.exportUrl(caseId)} download>
              Export profile
            </a>
            <a className={buttonVariants({ variant: "ghost", size: "sm" })} href={casesApi.exportUrl(caseId, false)} download>
              Export without documents
            </a>
          </div>
        </div>
        <p className="text-muted-foreground">
          Everything NexScout knows about you for this case. Only entries you have confirmed are
          ever used for recommendations or documents.
        </p>
        <nav aria-label="Profile sections" className="mt-3 flex flex-wrap gap-3 text-sm">
          <a className="underline" href="#review">Review ({pending.length})</a>
          <a className="underline" href="#confirmed">Confirmed ({accepted.length})</a>
          <a className="underline" href="#add">Add an entry</a>
          <a className="underline" href="#links">Profile links</a>
          <a className="underline" href="#preferences">Preferences</a>
        </nav>
      </header>

      {selected.size > 0 && (
        <div
          role="region"
          aria-label="Selected entries"
          className="sticky top-16 z-30 flex flex-wrap items-center gap-2 rounded-lg border bg-background/95 p-2 shadow-sm backdrop-blur"
        >
          <span className="px-1 text-sm font-medium">{selected.size} selected</span>
          <Button size="sm" disabled={bulk.isPending} onClick={() => bulk.mutate("accept")}>
            Accept
          </Button>
          <Button size="sm" variant="outline" disabled={bulk.isPending} onClick={() => bulk.mutate("reject")}>
            Reject
          </Button>
          <Button size="sm" variant="outline" disabled={bulk.isPending} onClick={() => bulk.mutate("private")}>
            Make private
          </Button>
          <Button size="sm" variant="outline" disabled={bulk.isPending} onClick={() => bulk.mutate("shareable")}>
            Make shareable
          </Button>
          <Button
            size="sm"
            variant="destructive"
            disabled={bulk.isPending}
            onClick={() => {
              if (window.confirm(`Delete ${selected.size} entries? This can't be undone.`)) bulk.mutate("delete");
            }}
          >
            Delete
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Clear selection
          </Button>
          <ErrorAlert error={bulk.error} />
        </div>
      )}

      {facts.isPending && <p>Loading your profile…</p>}
      <ErrorAlert error={facts.error} title="Couldn't load your profile" />

      <DraftSummary caseId={caseId} />

      {gaps.data && gaps.data.length > 0 && (
        <section aria-labelledby="gaps-heading" className="rounded-lg border p-4">
          <h2 id="gaps-heading" className="font-semibold">
            Things you may want to add
          </h2>
          <ul className="mt-2 list-disc pl-5 text-sm">
            {gaps.data.map((g) => (
              <li key={`${g.code}-${g.fact_id ?? ""}`}>{g.message}</li>
            ))}
          </ul>
        </section>
      )}

      <section id="review" aria-labelledby="review-heading" className="flex flex-col gap-4">
        <h2 id="review-heading" className="text-xl font-semibold">
          Needs your review
        </h2>
        {facts.data && pending.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Nothing to review. Upload your CV on the{" "}
            <Link className="underline" href={`/cases/${caseId}/documents`}>
              Documents
            </Link>{" "}
            page to import entries automatically.
          </p>
        )}
        {leftovers.length > 0 && (
          <div role="status" className="flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm">
            <span className="flex-1">
              {leftovers.length} suggestions below came from a file you have since deleted, so they
              can no longer be checked against it.
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={removeLeftovers.isPending}
              onClick={() => {
                if (window.confirm(`Remove these ${leftovers.length} unreviewed suggestions?`))
                  removeLeftovers.mutate(leftovers.map((f) => f.id));
              }}
            >
              Remove them
            </Button>
            <ErrorAlert error={removeLeftovers.error} />
          </div>
        )}
        {pending.length > 0 && (
          <p className="text-sm text-muted-foreground">
            These were found in your documents by a simple rule-based reader (not AI). Check
            each one against the source before accepting. Nothing here is used until you accept it.
          </p>
        )}
        {groupBySection(pending).map(([section, items]) => (
          <div key={section} className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <h3 className="font-medium">
                {SECTION_LABELS[section]} ({items.length})
              </h3>
              <div className="flex gap-1">
                {groupToggle(items)}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={acceptAll.isPending}
                  onClick={() => acceptAll.mutate(items.map((i) => i.id))}
                >
                  Accept all {items.length}
                </Button>
              </div>
            </div>
            {items.map(card)}
          </div>
        ))}
        <ErrorAlert error={acceptAll.error} />
      </section>

      <section id="confirmed" aria-labelledby="confirmed-heading" className="flex flex-col gap-4">
        <h2 id="confirmed-heading" className="text-xl font-semibold">
          Confirmed profile
        </h2>
        {facts.data && accepted.length === 0 && (
          <p className="text-sm text-muted-foreground">No confirmed entries yet.</p>
        )}
        {groupBySection(accepted).map(([section, items]) => (
          <div key={section} className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <h3 className="font-medium">{SECTION_LABELS[section]}</h3>
              {groupToggle(items)}
            </div>
            {items.map(card)}
          </div>
        ))}
        {rejected.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm">Rejected entries ({rejected.length})</summary>
            <div className="mt-2 flex flex-col gap-2">
              <div className="self-end">{groupToggle(rejected)}</div>
              {rejected.map(card)}
            </div>
          </details>
        )}
      </section>

      <section id="add" aria-labelledby="add-heading" className="flex flex-col gap-3">
        <h2 id="add-heading" className="text-xl font-semibold">
          Add an entry
        </h2>
        <div className="flex flex-col gap-1">
          <Label htmlFor="add-section">Section</Label>
          <select
            id="add-section"
            className="h-8 w-60 rounded-lg border bg-background px-2 text-sm"
            value={addSection}
            onChange={(e) => {
              setAddSection(e.target.value as Section);
              setFormKey((k) => k + 1);
            }}
          >
            {SECTION_ORDER.map((s) => (
              <option key={s} value={s}>
                {SECTION_LABELS[s]}
              </option>
            ))}
          </select>
        </div>
        <FactForm
          key={`${addSection}-${formKey}`}
          section={addSection}
          linkOptions={linkOptions}
          submitLabel="Add to profile"
          pending={create.isPending}
          onSubmit={(data) => create.mutate(data)}
        />
        <ErrorAlert error={create.error} title="Couldn't add this entry" />
        {create.isSuccess && (
          <p role="status" className="text-sm">
            Added to your confirmed profile.
          </p>
        )}
      </section>

      <LinksPanel caseId={caseId} />
      <PreferencesPanel caseId={caseId} />
    </div>
  );
}
