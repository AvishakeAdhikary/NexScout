"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { trackingApi } from "@/lib/api/client";

/** Reminders for one application (deadline reminders are added automatically). */
export function RemindersPanel({ caseId, applicationId }: { caseId: string; applicationId: string }) {
  const queryClient = useQueryClient();
  const reminders = useQuery({ queryKey: ["reminders", caseId], queryFn: () => trackingApi.reminders(caseId) });
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["reminders", caseId] });
    queryClient.invalidateQueries({ queryKey: ["dashboard", caseId] });
  };
  const [formKey, setFormKey] = useState(0);
  const add = useMutation({
    mutationFn: (v: { title: string; due: string }) => trackingApi.addReminder(caseId, v.title, v.due, applicationId),
    onSuccess: () => {
      setFormKey((k) => k + 1);
      invalidate();
    },
  });
  const done = useMutation({ mutationFn: (id: string) => trackingApi.setDone(id, true), onSuccess: invalidate });
  const mine = (reminders.data ?? []).filter((r) => r.application_id === applicationId);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    add.mutate({ title: String(f.get("title") ?? ""), due: String(f.get("due") ?? "") });
  }

  return (
    <section aria-labelledby="rem-heading" className="flex flex-col gap-2">
      <h2 id="rem-heading" className="font-semibold">Reminders</h2>
      {mine.length === 0 ? (
        <p className="text-sm text-muted-foreground">No open reminders.</p>
      ) : (
        <ul className="flex flex-col gap-1 text-sm">
          {mine.map((r) => (
            <li key={r.id} className="flex items-center gap-2">
              <span className="font-mono">{r.due_on}</span> {r.title}
              <button type="button" className="text-xs underline" onClick={() => done.mutate(r.id)}>
                Done
              </button>
            </li>
          ))}
        </ul>
      )}
      <form key={formKey} onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor="rem-title">Remind me to</Label>
          <Input id="rem-title" name="title" required maxLength={300} className="w-64" />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="rem-due">On</Label>
          <Input id="rem-due" name="due" type="date" required className="w-40" />
        </div>
        <Button type="submit" size="sm" variant="outline" disabled={add.isPending}>Add reminder</Button>
      </form>
      <ErrorAlert error={add.error ?? done.error ?? reminders.error} />
    </section>
  );
}
