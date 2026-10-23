"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { relationshipsApi, type ContactDetails, type ContactOut } from "@/lib/api/client";

type Key = keyof ContactDetails;

const FIELDS: { key: Key; label: string; type?: string; auto?: string; wide?: boolean }[] = [
  { key: "full_name", label: "Full name, as on your documents", auto: "name", wide: true },
  { key: "given_name", label: "First name (for forms)", auto: "given-name" },
  { key: "family_name", label: "Last name (for forms)", auto: "family-name" },
  { key: "email", label: "Email", type: "email", auto: "email" },
  { key: "phone", label: "Phone", type: "tel", auto: "tel" },
  { key: "city", label: "City", auto: "address-level2" },
  { key: "region", label: "State or province (optional)", auto: "address-level1" },
  { key: "country", label: "Country", auto: "country-name" },
  { key: "postal_code", label: "Postal code (optional)", auto: "postal-code" },
  {
    key: "address",
    label: "Street address (optional, some countries expect it)",
    auto: "street-address",
    wide: true,
  },
];

const LABEL = Object.fromEntries(FIELDS.map((f) => [f.key, f.label.split(" (")[0].split(",")[0]]));

export function ContactPanel({ caseId }: { caseId: string }) {
  const contact = useQuery({
    queryKey: ["contact", caseId],
    queryFn: () => relationshipsApi.contact(caseId),
  });
  const [savedVersion, setSavedVersion] = useState<number | null>(null);
  return (
    <section
      id="contact"
      aria-labelledby="contact-heading"
      className="flex flex-col gap-3 rounded-lg border p-4"
    >
      <h2 id="contact-heading" className="text-xl font-semibold">
        Contact details
      </h2>
      <p className="text-sm text-muted-foreground">
        Used in your resumes, CVs and letters, and to fill in application forms. They are added by
        NexScout itself after any AI writing, so they are never sent to an AI model.
      </p>
      {contact.data ? (
        // Re-mounted on each saved version, so the form starts from what the server has.
        <ContactForm
          key={contact.data.version}
          caseId={caseId}
          saved={contact.data}
          justSaved={savedVersion === contact.data.version}
          onSaved={setSavedVersion}
        />
      ) : contact.isPending ? (
        <p>Loading…</p>
      ) : (
        <ErrorAlert error={contact.error} />
      )}
    </section>
  );
}

function ContactForm({
  caseId,
  saved,
  justSaved,
  onSaved,
}: {
  caseId: string;
  saved: ContactOut;
  justSaved: boolean;
  onSaved: (version: number) => void;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Partial<Record<Key, string>>>(() =>
    Object.fromEntries(FIELDS.map((f) => [f.key, saved.data[f.key] ?? ""])),
  );
  const save = useMutation({
    mutationFn: () => relationshipsApi.saveContact(caseId, saved.version, draft),
    onSuccess: (result) => {
      onSaved(result.version);
      queryClient.setQueryData(["contact", caseId], result);
    },
  });
  const suggested = Object.entries(saved.suggested ?? {}) as [Key, string][];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      {suggested.length > 0 && (
        <div
          role="status"
          className="flex flex-col gap-2 rounded-md border border-dashed p-3 text-sm"
        >
          <p>
            Found in <span className="font-medium">{saved.suggested_from}</span>:{" "}
            {suggested.map(([k, v]) => `${LABEL[k] ?? k}: ${v}`).join(" · ")}
          </p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="self-start"
            onClick={() => setDraft((d) => ({ ...d, ...Object.fromEntries(suggested) }))}
          >
            Use these
          </Button>
          <p className="text-xs text-muted-foreground">
            Check them, then save. Nothing is saved until you do.
          </p>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map((f) => (
          <div key={f.key} className={`flex flex-col gap-1 ${f.wide ? "sm:col-span-2" : ""}`}>
            <Label htmlFor={`contact-${f.key}`}>{f.label}</Label>
            <Input
              id={`contact-${f.key}`}
              type={f.type ?? "text"}
              autoComplete={f.auto}
              value={draft[f.key] ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
            />
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={save.isPending}>
          Save contact details
        </Button>
        {justSaved && (
          <span role="status" className="text-sm">
            Saved.
          </span>
        )}
      </div>
      <ErrorAlert error={save.error} />
    </form>
  );
}
