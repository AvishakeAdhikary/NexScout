"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { DiagnosticsPanel } from "@/components/diagnostics-panel";
import { SourcesManager } from "@/components/sources-manager";
import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { providersApi, type ProviderIn, type ProviderOut } from "@/lib/api/client";

interface Preset {
  label: string;
  kind: ProviderIn["kind"];
  baseUrl: string;
  model: string;
  needsKey: boolean;
  contextWindow: number;
  jsonSchema: boolean;
  hint: string;
}

// Starting points only. Every field stays editable; nothing here is verified until "Check" runs.
const PRESETS: Record<string, Preset> = {
  ollama: {
    label: "Ollama (on this computer)",
    kind: "openai_compatible",
    baseUrl: "http://127.0.0.1:11434/v1",
    model: "llama3.1:8b",
    needsKey: false,
    contextWindow: 8192,
    jsonSchema: false,
    hint: "Start Ollama and pull the model first (ollama pull <model>).",
  },
  lmstudio: {
    label: "LM Studio (on this computer)",
    kind: "openai_compatible",
    baseUrl: "http://127.0.0.1:1234/v1",
    model: "",
    needsKey: false,
    contextWindow: 8192,
    jsonSchema: false,
    hint: "Load a model in LM Studio and start its local server. Use the model id it shows.",
  },
  openai: {
    label: "OpenAI or another OpenAI-compatible service",
    kind: "openai_compatible",
    baseUrl: "https://api.openai.com/v1",
    model: "",
    needsKey: true,
    contextWindow: 128000,
    jsonSchema: true,
    hint: "Your own API key. You pay the provider directly.",
  },
  anthropic: {
    label: "Anthropic (Claude)",
    kind: "anthropic",
    baseUrl: "",
    model: "claude-opus-5-5",
    needsKey: true,
    contextWindow: 200000,
    jsonSchema: true,
    hint: "Your own Anthropic API key. You pay Anthropic directly.",
  },
  gemini: {
    label: "Google Gemini",
    kind: "gemini",
    baseUrl: "",
    model: "",
    needsKey: true,
    contextWindow: 128000,
    jsonSchema: true,
    hint: "Your own Gemini API key.",
  },
  mock: {
    label: "Mock (for testing, not a real AI)",
    kind: "mock",
    baseUrl: "",
    model: "mock",
    needsKey: false,
    contextWindow: 8192,
    jsonSchema: true,
    hint: "Returns fixed test output. Useful to try workflows without an AI model.",
  },
};

function ProviderRow({ p }: { p: ProviderOut }) {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["providers"] });
  const verify = useMutation({ mutationFn: () => providersApi.verify(p.id), onSettled: invalidate });
  const makeDefault = useMutation({
    mutationFn: () => providersApi.setDefault(p.is_default ? null : p.id),
    onSettled: invalidate,
  });
  const remove = useMutation({ mutationFn: () => providersApi.remove(p.id), onSettled: invalidate });
  const v = p.last_verification as { ok?: boolean; error?: string; latency_ms?: number };

  return (
    <li className="flex flex-col gap-2 rounded-lg border p-3" aria-label={p.name}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{p.name}</span>
        {p.is_default && <Badge>Default</Badge>}
        {p.kind === "mock" ? (
          <Badge variant="outline">Mock — not a real AI</Badge>
        ) : p.data_leaves_device ? (
          <Badge variant="outline">Sends data off this device</Badge>
        ) : (
          <Badge variant="secondary">Local</Badge>
        )}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-sm">
        <dt className="text-muted-foreground">Model</dt>
        <dd className="break-all">{p.model}</dd>
        {p.base_url && (
          <>
            <dt className="text-muted-foreground">Address</dt>
            <dd className="break-all">{p.base_url}</dd>
          </>
        )}
        <dt className="text-muted-foreground">API key</dt>
        <dd>{p.has_api_key ? `Saved (ends in ${p.api_key_hint ?? "…"})` : "None"}</dd>
        <dt className="text-muted-foreground">Context</dt>
        <dd>
          {p.context_window.toLocaleString()} tokens in, up to {p.max_output_tokens.toLocaleString()} out
        </dd>
        <dt className="text-muted-foreground">Last check</dt>
        <dd role="status">
          {!p.last_verified_at
            ? "Not checked yet"
            : v.ok
              ? `Working (${v.latency_ms ?? "?"} ms) on ${new Date(p.last_verified_at).toLocaleString()}`
              : `Failed: ${v.error ?? "unknown error"}`}
        </dd>
      </dl>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={() => verify.mutate()} disabled={verify.isPending}>
          {verify.isPending ? "Checking…" : "Check connection"}
        </Button>
        <Button size="sm" variant="outline" onClick={() => makeDefault.mutate()}
          disabled={makeDefault.isPending}>
          {p.is_default ? "Stop using as default" : "Use as default"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm(`Remove ${p.name}? Its saved key is deleted too.`)) remove.mutate();
          }}
        >
          Remove
        </Button>
      </div>
      <ErrorAlert error={verify.error ?? makeDefault.error ?? remove.error} />
    </li>
  );
}

function AddProvider() {
  const queryClient = useQueryClient();
  const [presetKey, setPresetKey] = useState("ollama");
  const [formKey, setFormKey] = useState(0);
  const preset = PRESETS[presetKey];
  const create = useMutation({
    mutationFn: providersApi.create,
    onSuccess: () => {
      setFormKey((k) => k + 1);
      queryClient.invalidateQueries({ queryKey: ["providers"] });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const f = new FormData(form);
    const get = (k: string) => String(f.get(k) ?? "").trim();
    const num = (k: string) => (get(k) === "" ? null : Number(get(k)));
    create.mutate({
      name: get("name"),
      kind: preset.kind,
      model: get("model"),
      base_url: get("base_url") || null,
      api_key: get("api_key") || null,
      context_window: num("context_window") ?? preset.contextWindow,
      max_output_tokens: num("max_output_tokens") ?? 1024,
      supports_json_schema: f.get("supports_json_schema") === "on",
      is_default: f.get("is_default") === "on",
      input_cost_per_mtok: num("input_cost"),
      output_cost_per_mtok: num("output_cost"),
    });
    // The key must not linger in the DOM after submit.
    const key = form.elements.namedItem("api_key");
    if (key instanceof HTMLInputElement) key.value = "";
  }

  return (
    <section aria-labelledby="add-provider" className="rounded-lg border p-4">
      <h2 id="add-provider" className="mb-3 text-lg font-semibold">
        Add an AI model
      </h2>
      <div className="mb-3 flex flex-col gap-1">
        <Label htmlFor="prov-preset">Type</Label>
        <select
          id="prov-preset"
          className="h-8 rounded-lg border bg-background px-2 text-sm"
          value={presetKey}
          onChange={(e) => {
            setPresetKey(e.target.value);
            setFormKey((k) => k + 1);
          }}
        >
          {Object.entries(PRESETS).map(([k, p]) => (
            <option key={k} value={k}>
              {p.label}
            </option>
          ))}
        </select>
        <p className="text-sm text-muted-foreground">{preset.hint}</p>
      </div>
      <form key={`${presetKey}-${formKey}`} onSubmit={submit} className="grid gap-3 sm:grid-cols-2"
        autoComplete="off">
        <div className="flex flex-col gap-1">
          <Label htmlFor="prov-name">Name *</Label>
          <Input id="prov-name" name="name" required maxLength={100}
            defaultValue={preset.label.split(" (")[0]} />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="prov-model">Model *</Label>
          <Input id="prov-model" name="model" required maxLength={200} defaultValue={preset.model} />
        </div>
        {preset.kind === "openai_compatible" && (
          <div className="flex flex-col gap-1 sm:col-span-2">
            <Label htmlFor="prov-url">Server address *</Label>
            <Input id="prov-url" name="base_url" required maxLength={500} defaultValue={preset.baseUrl} />
          </div>
        )}
        {preset.kind !== "mock" && (
          <div className="flex flex-col gap-1 sm:col-span-2">
            <Label htmlFor="prov-key">API key{preset.needsKey ? " *" : " (if your server needs one)"}</Label>
            <Input id="prov-key" name="api_key" type="password" required={preset.needsKey}
              maxLength={500} autoComplete="new-password" />
            <p className="text-xs text-muted-foreground">
              Stored encrypted. It is never shown again, never sent to the browser, and never put
              into prompts or logs.
            </p>
          </div>
        )}
        <div className="flex flex-col gap-1">
          <Label htmlFor="prov-ctx">Context window (tokens)</Label>
          <Input id="prov-ctx" name="context_window" type="number" min={512}
            defaultValue={preset.contextWindow} />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="prov-out">Max output (tokens)</Label>
          <Input id="prov-out" name="max_output_tokens" type="number" min={64} defaultValue={1024} />
        </div>
        {preset.kind !== "mock" && (
          <>
            <div className="flex flex-col gap-1">
              <Label htmlFor="prov-in-cost">Input cost per million tokens (optional)</Label>
              <Input id="prov-in-cost" name="input_cost" type="number" min={0} step="0.01" />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="prov-out-cost">Output cost per million tokens (optional)</Label>
              <Input id="prov-out-cost" name="output_cost" type="number" min={0} step="0.01" />
            </div>
          </>
        )}
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="supports_json_schema" defaultChecked={preset.jsonSchema} />
          Supports structured (JSON schema) output
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="is_default" />
          Use as my default
        </label>
        <Button type="submit" className="self-start" disabled={create.isPending}>
          Add
        </Button>
        <div className="sm:col-span-2">
          <ErrorAlert error={create.error} />
        </div>
      </form>
    </section>
  );
}

export default function SettingsPage() {
  const providers = useQuery({ queryKey: ["providers"], queryFn: providersApi.list });
  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-muted-foreground">
          Sources and AI models apply to all your cases.
        </p>
      </header>
      <section aria-labelledby="providers-heading" className="flex flex-col gap-3">
        <h2 id="providers-heading" className="text-xl font-semibold">
          AI models (bring your own)
        </h2>
        <p className="text-sm text-muted-foreground">
          NexScout works without any AI model; reading documents and matching don&apos;t need
          one. Drafting text does. A model marked “Sends data off this device” receives the
          profile entries a workflow needs, and NexScout asks before sending them.
        </p>
        {providers.isPending && <p>Loading…</p>}
        <ErrorAlert error={providers.error} />
        {providers.data && providers.data.length === 0 && (
          <p className="text-sm">No AI models added yet.</p>
        )}
        <ul className="flex flex-col gap-3">
          {(providers.data ?? []).map((p) => (
            <ProviderRow key={p.id} p={p} />
          ))}
        </ul>
      </section>
      <AddProvider />
      <SourcesManager />
      <DiagnosticsPanel />
    </div>
  );
}
