"use client";

import { useId, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Section } from "@/lib/api/client";
import { DATE_HELP, SECTION_FIELDS, toFormValues, toPayload } from "@/lib/profile-schema";

export function FactForm({
  section,
  initial,
  submitLabel,
  pending,
  onSubmit,
  onCancel,
}: {
  section: Section;
  initial?: Record<string, unknown>;
  submitLabel: string;
  pending?: boolean;
  onSubmit: (payload: Record<string, unknown>) => void;
  onCancel?: () => void;
}) {
  const uid = useId();
  const [values, setValues] = useState<Record<string, string>>(() =>
    toFormValues(initial ?? {}),
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(toPayload(section, values));
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
            className={field.type === "textarea" ? "flex flex-col gap-1 sm:col-span-2" : "flex flex-col gap-1"}
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
                placeholder={field.type === "end-date" ? "YYYY-MM or present" : isDate ? "YYYY-MM" : undefined}
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
