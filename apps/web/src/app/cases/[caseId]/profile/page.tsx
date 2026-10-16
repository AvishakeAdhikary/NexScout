"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { FactForm } from "@/components/fact-form";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { factsApi, type FactOut, type Section } from "@/lib/api/client";
import { SECTION_LABELS, SECTION_ORDER } from "@/lib/profile-schema";

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
  const [addSection, setAddSection] = useState<Section>("education");
  const [formKey, setFormKey] = useState(0);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["facts", caseId] });
    queryClient.invalidateQueries({ queryKey: ["gaps", caseId] });
  };
  const acceptAll = useMutation({
    mutationFn: (ids: string[]) => factsApi.review(caseId, ids, []),
    onSuccess: invalidate,
  });
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
        <h1 className="text-2xl font-semibold">My Profile</h1>
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
              <Button
                size="sm"
                variant="outline"
                disabled={acceptAll.isPending}
                onClick={() => acceptAll.mutate(items.map((i) => i.id))}
              >
                Accept all {items.length}
              </Button>
            </div>
            {items.map((f) => (
              <FactCard key={f.id} fact={f} caseId={caseId} />
            ))}
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
            <h3 className="font-medium">{SECTION_LABELS[section]}</h3>
            {items.map((f) => (
              <FactCard key={f.id} fact={f} caseId={caseId} />
            ))}
          </div>
        ))}
        {rejected.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm">Rejected entries ({rejected.length})</summary>
            <div className="mt-2 flex flex-col gap-2">
              {rejected.map((f) => (
                <FactCard key={f.id} fact={f} caseId={caseId} />
              ))}
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
