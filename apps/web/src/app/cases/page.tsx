"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { casesApi } from "@/lib/api/client";
import { useCases } from "@/lib/hooks";
import { CAREER_PATH_LABELS } from "@/lib/labels";

export default function CasesPage() {
  const cases = useCases();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [formKey, setFormKey] = useState(0);
  const create = useMutation({
    mutationFn: casesApi.create,
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["cases"] });
      setFormKey((k) => k + 1);
      router.push(`/cases/${created.id}`);
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const description = String(form.get("description") ?? "").trim();
    create.mutate({
      name: String(form.get("name") ?? ""),
      description: description || null,
      career_path: "undecided",
    });
  }

  return (
    <main id="main" className="animate-page mx-auto flex w-full max-w-4xl flex-col gap-8 p-6">
      <section aria-labelledby="cases-heading" className="flex flex-col gap-3">
        <h1 id="cases-heading" className="text-2xl font-semibold">
          Your cases
        </h1>
        <p className="text-muted-foreground">
          A case is one search, such as &ldquo;PhD in machine learning&rdquo; or &ldquo;Data jobs in
          Berlin&rdquo;. Each case keeps its own profile, preferences, and applications.
        </p>
        {cases.isPending && <p>Loading your cases…</p>}
        <ErrorAlert error={cases.error} title="Couldn't load your cases" />
        {cases.data && cases.data.length === 0 && (
          <p className="rounded-md border border-dashed p-4">
            You don&apos;t have any cases yet. Create your first one below.
          </p>
        )}
        {cases.data && cases.data.length > 0 && (
          <ul className="grid gap-3 sm:grid-cols-2">
            {cases.data.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/cases/${c.id}`}
                  className="lift block rounded-xl border bg-card p-4 focus-visible:outline-2 focus-visible:outline-ring"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{c.name}</span>
                    <Badge variant="secondary">{CAREER_PATH_LABELS[c.career_path]}</Badge>
                  </div>
                  {c.description && (
                    <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                      {c.description}
                    </p>
                  )}
                  {c.status !== "active" && (
                    <p className="mt-1 text-xs uppercase text-muted-foreground">{c.status}</p>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2 className="text-lg font-semibold">Create a case</h2>
          </CardTitle>
          <CardDescription>You can choose between PhD and job searches afterwards.</CardDescription>
        </CardHeader>
        <CardContent>
          <form key={formKey} onSubmit={onSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="case-name">Name</Label>
              <Input id="case-name" name="name" required maxLength={120} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="case-description">Description (optional)</Label>
              <Textarea id="case-description" name="description" maxLength={2000} rows={3} />
            </div>
            <ErrorAlert error={create.error} title="Couldn't create the case" />
            <Button type="submit" disabled={create.isPending} className="self-start">
              {create.isPending ? "Creating…" : "Create case"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
