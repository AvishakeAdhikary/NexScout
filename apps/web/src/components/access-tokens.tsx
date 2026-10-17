"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

type TokenOut = components["schemas"]["TokenOut"];
type TokenCreatedOut = components["schemas"]["TokenCreatedOut"];

/** Personal access tokens for the read-only MCP server (and other local integrations). */
export function AccessTokens() {
  const queryClient = useQueryClient();
  const tokens = useQuery({ queryKey: ["tokens"], queryFn: () => api<TokenOut[]>("/me/tokens") });
  const [created, setCreated] = useState<TokenCreatedOut | null>(null);
  const [formKey, setFormKey] = useState(0);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["tokens"] });
  const create = useMutation({
    mutationFn: (body: { name: string; expires_in_days: number }) =>
      api<TokenCreatedOut>("/me/tokens", { method: "POST", body }),
    onSuccess: (t) => {
      setCreated(t);
      setFormKey((k) => k + 1);
      invalidate();
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api<void>(`/me/tokens/${encodeURIComponent(id)}`, { method: "DELETE" }),
    onSuccess: invalidate,
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    create.mutate({ name: String(f.get("name") ?? ""), expires_in_days: Number(f.get("days") ?? 90) });
  }

  return (
    <section aria-labelledby="tokens-heading" className="flex flex-col gap-3 rounded-xl border bg-card p-4">
      <h2 id="tokens-heading" className="text-lg font-semibold">Access tokens (MCP)</h2>
      <p className="text-sm text-muted-foreground">
        Let a local AI assistant read your NexScout data through the Model Context Protocol:
        run <code className="rounded bg-muted px-1">nexscout mcp</code> with{" "}
        <code className="rounded bg-muted px-1">NEXSCOUT_MCP_TOKEN</code> set. Tokens are
        read-only. They can&apos;t submit, send or change anything, and never see private
        entries.
      </p>
      {created && (
        <div role="status" className="animate-page flex flex-col gap-1 rounded-lg border border-primary/40 bg-primary/5 p-3 text-sm">
          <span className="font-medium">Copy your new token now. It won&apos;t be shown again.</span>
          <code className="break-all rounded bg-muted p-2 font-mono text-xs">{created.token}</code>
          <Button size="sm" variant="outline" className="self-start"
            onClick={() => void navigator.clipboard?.writeText(created.token)}>
            Copy
          </Button>
        </div>
      )}
      <form key={formKey} onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor="token-name">Name</Label>
          <Input id="token-name" name="name" required maxLength={100} placeholder="e.g. Claude Desktop" className="w-56" />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="token-days">Expires after</Label>
          <select id="token-days" name="days" defaultValue="90" className="h-8 rounded-lg border bg-background px-2 text-sm">
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
            <option value="365">1 year</option>
          </select>
        </div>
        <Button type="submit" size="sm" disabled={create.isPending}>Create token</Button>
      </form>
      <ErrorAlert error={create.error ?? revoke.error ?? tokens.error} />
      <ul className="flex flex-col gap-1 text-sm">
        {(tokens.data ?? []).map((t) => (
          <li key={t.id} className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{t.name}</span>
            <code className="font-mono text-xs text-muted-foreground">{t.prefix}…</code>
            {t.revoked ? (
              <Badge variant="outline">Revoked</Badge>
            ) : (
              <>
                <span className="text-xs text-muted-foreground">
                  {t.last_used_at ? `used ${new Date(t.last_used_at).toLocaleDateString()}` : "never used"}
                  {t.expires_at ? ` · expires ${new Date(t.expires_at).toLocaleDateString()}` : ""}
                </span>
                <button type="button" className="text-xs underline" onClick={() => revoke.mutate(t.id)}>
                  Revoke
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
