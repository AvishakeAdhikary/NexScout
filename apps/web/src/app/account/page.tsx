"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AccessTokens } from "@/components/access-tokens";
import { ErrorAlert } from "@/components/error-alert";
import { NotificationChannels } from "@/components/notification-channels";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { accountApi } from "@/lib/api/client";

export default function AccountPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const remove = useMutation({
    mutationFn: () => accountApi.remove(password),
    onSuccess: () => {
      queryClient.clear();
      router.replace("/register");
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    remove.mutate();
  }

  return (
    <main id="main" className="mx-auto flex w-full max-w-3xl flex-col gap-8 p-6">
      <h1 className="text-2xl font-semibold">Your account and data</h1>

      <section aria-labelledby="export-heading" className="flex flex-col gap-2">
        <h2 id="export-heading" className="text-lg font-semibold">
          Download all your data
        </h2>
        <p className="text-sm text-muted-foreground">
          A .zip file with everything NexScout stores about you (cases, profile entries and their
          sources, preferences, relationships) as JSON, plus your original uploaded files.
        </p>
        <a
          href={accountApi.exportUrl}
          className="inline-flex h-8 w-fit items-center rounded-lg border px-3 text-sm hover:bg-muted"
        >
          Download my data
        </a>
      </section>

      <NotificationChannels />

      <AccessTokens />

      <section
        aria-labelledby="delete-heading"
        className="flex flex-col gap-2 rounded-lg border border-destructive/40 p-4"
      >
        <h2 id="delete-heading" className="text-lg font-semibold">
          Delete your account
        </h2>
        <p className="text-sm text-muted-foreground">
          This permanently deletes your account, every case, all profile entries, documents, and
          uploaded files. It cannot be undone. Download your data first if you want a copy.
        </p>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="delete-password">Your password</Label>
            <Input
              id="delete-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="delete-confirm">Type DELETE to confirm</Label>
            <Input
              id="delete-confirm"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              autoComplete="off"
            />
          </div>
          <Button
            type="submit"
            variant="destructive"
            className="self-start"
            disabled={confirmText !== "DELETE" || !password || remove.isPending}
          >
            {remove.isPending ? "Deleting…" : "Delete my account permanently"}
          </Button>
          <ErrorAlert error={remove.error} title="Account not deleted" />
        </form>
      </section>
    </main>
  );
}
