"use client";

import { useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Section } from "@/lib/api/client";
import {
  DATE_HELP,
  LINKABLE_SOURCES,
  SECTION_FIELDS,
  toFormValues,
  toPayload,
} from "@/lib/profile-schema";

export interface LinkOption {
  id: string;
  label: string;
}

export function FactForm({
  section,
  initial,
  submitLabel,
  pending,
  onSubmit,
  onCancel,
  linkOptions = [],
  selfId,
}: {
  section: Section;
  initial?: Record<string, unknown>;
  submitLabel: string;
  pending?: boolean;
  onSubmit: (payload: Record<string, unknown>) => void;
  onCancel?: () => void;
  /** Jobs, studies and other roles this entry can be "part of" (a project done in a job). */
  linkOptions?: LinkOption[];
  selfId?: string;
}) {
  const uid = useId();
  const [values, setValues] = useState<Record<string, string>>(() => toFormValues(initial ?? {}));
  const [related, setRelated] = useState<string[]>(() =>
    Array.isArray(initial?.related_fact_ids) ? (initial.related_fact_ids as string[]) : [],
  );
  const options = LINKABLE_SOURCES.has(section) ? linkOptions.filter((o) => o.id !== selfId) : [];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = toPayload(section, values);
    // Links the user can't see in this form (none should exist) are kept, never dropped.
    const kept = related.filter((id) => options.some((o) => o.id === id) || !options.length);
    if (kept.length) payload.related_fact_ids = kept.slice(0, 5);
    onSubmit(payload);
  }

  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      {SECTION_FIELDS[section].map((field) => {
        const id = `${uid}-${field.key}`;
        const helpId = `${id}-help`;
        const isDate = field.type === "date" || field.type === "end-date";
        const common = {
          id,
          name: field.key,
          value: values[field.key] ?? "",
          required: field.required,
          "aria-describedby": isDate ? helpId : undefined,
          onChange: (ev: { target: { value: string } }) =>
            setValues((v) => ({ ...v, [field.key]: ev.target.value })),
        };
        return (
          <div
            key={field.key}
            className={
              field.type === "textarea"
                ? "flex flex-col gap-1 sm:col-span-2"
                : "flex flex-col gap-1"
            }
          >
            <Label htmlFor={id}>
              {field.label}
              {field.required && <span aria-hidden="true"> *</span>}
            </Label>
            {field.type === "textarea" ? (
              <Textarea rows={3} maxLength={5000} {...common} />
            ) : (
              <Input
                type={field.type === "url" ? "url" : "text"}
                maxLength={field.type === "url" ? 2048 : 500}
                placeholder={
                  field.type === "end-date" ? "YYYY-MM or present" : isDate ? "YYYY-MM" : undefined
                }
                {...common}
              />
            )}
            {isDate && (
              <p id={helpId} className="text-xs text-muted-foreground">
                {DATE_HELP}
                {field.type === "end-date" ? ", or “present”" : ""}
              </p>
            )}
          </div>
        );
      })}
      {options.length > 0 && (
        <fieldset className="flex flex-col gap-1 sm:col-span-2">
          <legend className="text-sm font-medium">Part of (optional)</legend>
          <p className="text-xs text-muted-foreground">
            The job, study or role this belongs to. Documents written for you will mention it
            together (for example, a project you built at a company).
          </p>
          <ul className="mt-1 flex max-h-40 flex-col gap-1 overflow-y-auto rounded-md border p-2">
            {options.map((o) => {
              const checked = related.includes(o.id);
              return (
                <li key={o.id}>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={!checked && related.length >= 5}
                      onChange={(e) =>
                        setRelated((r) =>
                          e.target.checked ? [...r, o.id] : r.filter((x) => x !== o.id),
                        )
                      }
                    />
                    {o.label}
                  </label>
                </li>
              );
            })}
          </ul>
        </fieldset>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Saving…" : submitLabel}
        </Button>
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
