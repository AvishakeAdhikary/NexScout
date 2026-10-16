"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { relationshipsApi, type Preferences, type PreferencesOut } from "@/lib/api/client";

type ListKey = "countries" | "cities" | "research_areas" | "job_titles" | "preferred_employers" |
  "preferred_institutions";

const LIST_FIELDS: { key: ListKey; label: string }[] = [
  { key: "countries", label: "Countries" },
  { key: "cities", label: "Cities" },
  { key: "research_areas", label: "Research areas" },
  { key: "job_titles", label: "Job titles" },
  { key: "preferred_institutions", label: "Preferred universities" },
  { key: "preferred_employers", label: "Preferred employers" },
];

const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export function PreferencesPanel({ caseId }: { caseId: string }) {
  const [savedVersion, setSavedVersion] = useState<number | null>(null);
  const prefs = useQuery({
    queryKey: ["preferences", caseId],
    queryFn: () => relationshipsApi.preferences(caseId),
  });
  if (!prefs.data) {
    return (
      <section id="preferences">
        <h2 className="text-xl font-semibold">Preferences</h2>
        {prefs.isPending ? <p>Loading…</p> : <ErrorAlert error={prefs.error} />}
      </section>
    );
  }
  // Re-mount the form whenever a new version is saved, so its state starts from the server.
  return (
    <PreferencesForm
      key={prefs.data.version}
      caseId={caseId}
      saved={prefs.data}
      justSaved={savedVersion === prefs.data.version}
      onSaved={setSavedVersion}
    />
  );
}

function PreferencesForm({
  caseId,
  saved,
  justSaved,
  onSaved,
}: {
  caseId: string;
  saved: PreferencesOut;
  justSaved: boolean;
  onSaved: (version: number) => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Preferences>(saved.data);
  const [lists, setLists] = useState<Record<ListKey, string>>(
    () =>
      Object.fromEntries(
        LIST_FIELDS.map((f) => [f.key, (saved.data[f.key] ?? []).join(", ")]),
      ) as Record<ListKey, string>,
  );
  const save = useMutation({
    mutationFn: (data: Preferences) =>
      relationshipsApi.savePreferences(caseId, saved.version, data),
    onSuccess: (result) => {
      onSaved(result.version);
      queryClient.setQueryData(["preferences", caseId], result);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    const data: Preferences = { ...draft };
    for (const f of LIST_FIELDS) data[f.key] = split(lists[f.key] ?? "");
    save.mutate(data);
  }

  const set = <K extends keyof Preferences>(key: K, value: Preferences[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));
  const tri = (v: boolean | null | undefined) => (v == null ? "" : v ? "yes" : "no");
  const fromTri = (v: string) => (v === "" ? null : v === "yes");

  return (
    <section id="preferences" aria-labelledby="prefs-heading" className="flex flex-col gap-3">
      <h2 id="prefs-heading" className="text-xl font-semibold">
        Preferences
      </h2>
      <p className="text-sm text-muted-foreground">
        All optional. Separate multiple values with commas.
      </p>
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        {LIST_FIELDS.map((f) => (
          <div key={f.key} className="flex flex-col gap-1">
            <Label htmlFor={`pref-${f.key}`}>{f.label}</Label>
            <Input
              id={`pref-${f.key}`}
              value={lists[f.key] ?? ""}
              onChange={(e) => setLists((l) => ({ ...l, [f.key]: e.target.value }))}
            />
          </div>
        ))}
        <div className="flex flex-col gap-1">
          <Label htmlFor="pref-remote">Work location</Label>
          <select
            id="pref-remote"
            className="h-8 rounded-lg border bg-background px-2 text-sm"
            value={draft.remote ?? "any"}
            onChange={(e) => set("remote", e.target.value as Preferences["remote"])}
          >
            <option value="any">Any</option>
            <option value="onsite">On-site</option>
            <option value="hybrid">Hybrid</option>
            <option value="remote">Remote</option>
          </select>
        </div>
        <fieldset className="flex flex-col gap-1">
          <legend className="text-sm font-medium">Experience requirements</legend>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="experience_mode"
              checked={draft.experience_mode === "strict"}
              onChange={() => set("experience_mode", "strict")}
            />
            Strict: only roles whose required experience I meet
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="experience_mode"
              checked={draft.experience_mode === "flexible"}
              onChange={() => set("experience_mode", "flexible")}
            />
            Flexible: include stretch roles, and show me the gap
          </label>
        </fieldset>
        <div className="flex flex-col gap-1">
          <Label htmlFor="pref-visa">Need visa sponsorship?</Label>
          <select
            id="pref-visa"
            className="h-8 rounded-lg border bg-background px-2 text-sm"
            value={tri(draft.needs_visa_sponsorship)}
            onChange={(e) => set("needs_visa_sponsorship", fromTri(e.target.value))}
          >
            <option value="">Prefer not to say</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="pref-funding">Need funding (PhD)?</Label>
          <select
            id="pref-funding"
            className="h-8 rounded-lg border bg-background px-2 text-sm"
            value={tri(draft.funding_required)}
            onChange={(e) => set("funding_required", fromTri(e.target.value))}
          >
            <option value="">Not specified</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>
        <details className="sm:col-span-2 rounded-lg border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            Private eligibility details (optional)
          </summary>
          <p className="mt-2 text-sm text-muted-foreground">
            Kept private. Never used to rank or score you. With your permission, only used to
            check explicit requirements such as “must already be authorized to work in X”.
          </p>
          <div className="mt-2 flex flex-col gap-2">
            <Label htmlFor="pref-auth">Countries where you are already authorized to work</Label>
            <Input
              id="pref-auth"
              value={(draft.sensitive?.work_authorization ?? []).join(", ")}
              onChange={(e) =>
                set("sensitive", { ...draft.sensitive!, work_authorization: split(e.target.value) })
              }
            />
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={draft.sensitive?.use_for_eligibility ?? false}
                onChange={(e) =>
                  set("sensitive", { ...draft.sensitive!, use_for_eligibility: e.target.checked })
                }
              />
              Allow use for explicit eligibility checks
            </label>
          </div>
        </details>
        <div className="sm:col-span-2 flex items-center gap-3">
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save preferences"}
          </Button>
          <span role="status" className="text-sm">
            {justSaved && !save.isPending ? "Saved." : ""}
          </span>
        </div>
      </form>
      <ErrorAlert error={save.error} title="Couldn't save preferences" />
    </section>
  );
}
