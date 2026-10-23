"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { channelsApi, type ChannelCreatedOut, type ChannelOut } from "@/lib/api/client";

type Field = {
  key: string;
  label: string;
  secret?: boolean;
  placeholder?: string;
  optional?: boolean;
};
type Kind = {
  label: string;
  intro: string;
  steps: string[];
  fields: Field[];
};

/** Official provider APIs only (AGENTS.md §4a). The steps are the providers' own setup flows. */
const KINDS: Record<string, Kind> = {
  telegram: {
    label: "Telegram",
    intro: "Get messages with Approve / Reject buttons and answer questions by replying.",
    steps: [
      "In Telegram, open @BotFather and send /newbot. Pick any name.",
      "Copy the bot token BotFather gives you and paste it below.",
      "After you save, send the pairing code to your new bot. Only your chat can use it.",
    ],
    fields: [{ key: "bot_token", label: "Bot token", secret: true, placeholder: "123456:ABC…" }],
  },
  discord: {
    label: "Discord",
    intro: "Direct messages from your own bot, with buttons. Replies answer questions.",
    steps: [
      "Create an application at discord.com/developers, add a Bot, and copy its token.",
      "Invite the bot to a server you're in (OAuth2 → URL generator → scope: bot).",
      "Turn on Developer Mode in Discord, right-click your name, and Copy User ID.",
      "After you save, the bot sends you a code. Type it here to finish.",
    ],
    fields: [
      { key: "bot_token", label: "Bot token", secret: true },
      { key: "user_id", label: "Your Discord user ID", placeholder: "17–20 digits" },
    ],
  },
  whatsapp: {
    label: "WhatsApp (Cloud API)",
    intro:
      "Uses Meta's official WhatsApp Business Cloud API (no unofficial apps that get numbers banned). Replies need a public HTTPS address for the webhook.",
    steps: [
      "In Meta for Developers, create an app with the WhatsApp product and get a phone number ID.",
      "Copy a (permanent) access token and the app secret (App settings → Basic).",
      "After you save, set the webhook callback URL and verify token shown here, subscribe to 'messages', then send PAIR <code> from your phone.",
      "Outside a 24-hour chat window, Meta requires an approved message template (optional field).",
    ],
    fields: [
      { key: "phone_number_id", label: "Phone number ID" },
      { key: "access_token", label: "Access token", secret: true },
      { key: "app_secret", label: "App secret", secret: true },
      { key: "template_name", label: "Template name", optional: true },
    ],
  },
  slack: {
    label: "Slack",
    intro: "Messages in a Slack channel through an incoming webhook (links open NexScout).",
    steps: ["In Slack, create an app → Incoming Webhooks → add to a channel → copy the URL."],
    fields: [
      {
        key: "webhook_url",
        label: "Webhook URL",
        secret: true,
        placeholder: "https://hooks.slack.com/…",
      },
    ],
  },
  email: {
    label: "Email",
    intro: "Email through your own mail account (SMTP). Use an app password, not your login.",
    steps: ["Find your provider's SMTP server, port and an app password."],
    fields: [
      { key: "smtp_host", label: "SMTP server", placeholder: "smtp.example.com" },
      { key: "smtp_port", label: "Port", placeholder: "587", optional: true },
      { key: "username", label: "Username", optional: true },
      { key: "password", label: "Password / app password", secret: true, optional: true },
      { key: "from_address", label: "From address" },
      { key: "to_address", label: "Send to" },
    ],
  },
  webhook: {
    label: "Webhook (n8n, Zapier, your own bot)",
    intro: "A signed JSON POST for every notification. Verify X-NexScout-Signature.",
    steps: ["Paste the address that should receive the notifications."],
    fields: [{ key: "url", label: "Address", secret: true, placeholder: "https://…" }],
  },
};
const SECRET_KEYS = new Set([
  "bot_token",
  "access_token",
  "app_secret",
  "webhook_url",
  "password",
  "url",
]);
const EVENTS: [string, string][] = [
  ["approval", "Approvals"],
  ["question", "Questions"],
  ["application", "Applications that need you"],
  ["submitted", "Submitted"],
  ["reminder", "Reminders"],
  ["autopilot", "Autopilot"],
  ["digest", "Daily digest"],
];
const STATUS: Record<
  string,
  { label: string; variant: "default" | "secondary" | "outline" | "destructive" }
> = {
  active: { label: "Connected", variant: "default" },
  pending_pairing: { label: "Waiting for pairing", variant: "secondary" },
  paused: { label: "Paused", variant: "outline" },
  error: { label: "Stopped after errors", variant: "destructive" },
};

export function NotificationChannels() {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: ["channels"], queryFn: channelsApi.list });
  const [kind, setKind] = useState("telegram");
  const [created, setCreated] = useState<ChannelCreatedOut | null>(null);
  const [formKey, setFormKey] = useState(0);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["channels"] });
  const create = useMutation({
    mutationFn: channelsApi.create,
    onSuccess: (c) => {
      setCreated(c);
      setFormKey((k) => k + 1);
      invalidate();
    },
  });
  const spec = KINDS[kind];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const config: Record<string, string> = {};
    const secrets: Record<string, string> = {};
    for (const field of spec.fields) {
      const v = String(f.get(field.key) ?? "").trim();
      if (!v) continue;
      (SECRET_KEYS.has(field.key) ? secrets : config)[field.key] = v;
    }
    create.mutate({
      kind,
      name: String(f.get("name") ?? spec.label),
      config,
      secrets,
      events: EVENTS.map(([k]) => k).filter((k) => f.get(`ev-${k}`)),
      quiet_start: String(f.get("quiet_start") ?? "") || null,
      quiet_end: String(f.get("quiet_end") ?? "") || null,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    });
  }

  return (
    <section
      aria-labelledby="channels-heading"
      className="flex flex-col gap-3 rounded-xl border bg-card p-4"
    >
      <h2 id="channels-heading" className="text-lg font-semibold">
        Notifications on your phone
      </h2>
      <p className="text-sm text-muted-foreground">
        NexScout can reach you where you already are, so work keeps moving while you&apos;re away:
        approve or reject a submission with one tap, and answer questions by replying. You use your
        own bot or account through each provider&apos;s official API, and only the account you pair
        can act. Nothing is sent to anyone else.
      </p>

      {created && (
        <div
          role="status"
          className="animate-page flex flex-col gap-2 rounded-lg border border-primary/40 bg-primary/5 p-3 text-sm"
        >
          <span className="font-medium">{created.channel.name} saved.</span>
          {created.instructions && <span>{created.instructions}</span>}
          {created.pairing_code && created.channel.kind !== "discord" && (
            <code className="w-fit rounded bg-muted px-2 py-1 font-mono text-base">
              {created.channel.kind === "telegram"
                ? `/start ${created.pairing_code}`
                : `PAIR ${created.pairing_code}`}
            </code>
          )}
          {created.signing_secret && (
            <span>
              Signing secret (shown once):{" "}
              <code className="break-all rounded bg-muted px-1 font-mono text-xs">
                {created.signing_secret}
              </code>
            </span>
          )}
        </div>
      )}

      <form key={formKey} onSubmit={submit} className="flex flex-col gap-3 rounded-lg border p-3">
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="channel-kind">Add a channel</Label>
            <select
              id="channel-kind"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className="h-8 rounded-lg border bg-background px-2 text-sm"
            >
              {Object.entries(KINDS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="channel-name">Name</Label>
            <Input
              id="channel-name"
              name="name"
              defaultValue={spec.label}
              maxLength={100}
              className="w-56"
              required
            />
          </div>
        </div>
        <p className="text-sm">{spec.intro}</p>
        <ol className="list-decimal pl-5 text-sm text-muted-foreground">
          {spec.steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
        <div className="grid gap-2 sm:grid-cols-2">
          {spec.fields.map((field) => (
            <div key={`${kind}-${field.key}`} className="flex flex-col gap-1">
              <Label htmlFor={`ch-${field.key}`}>
                {field.label}
                {field.optional ? " (optional)" : ""}
              </Label>
              <Input
                id={`ch-${field.key}`}
                name={field.key}
                type={field.secret ? "password" : "text"}
                autoComplete="off"
                placeholder={field.placeholder}
                required={!field.optional}
              />
            </div>
          ))}
        </div>
        <fieldset className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <legend className="mb-1 text-sm font-medium">Send me</legend>
          {EVENTS.map(([k, label]) => (
            <label key={k} className="flex items-center gap-1">
              <input type="checkbox" name={`ev-${k}`} defaultChecked /> {label}
            </label>
          ))}
        </fieldset>
        <div className="flex flex-wrap items-end gap-2 text-sm">
          <div className="flex flex-col gap-1">
            <Label htmlFor="quiet-start">Quiet from (optional)</Label>
            <Input id="quiet-start" name="quiet_start" type="time" className="w-32" />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="quiet-end">until</Label>
            <Input id="quiet-end" name="quiet_end" type="time" className="w-32" />
          </div>
          <Button type="submit" size="sm" disabled={create.isPending}>
            {create.isPending ? "Checking…" : "Save channel"}
          </Button>
        </div>
        <ErrorAlert error={create.error} title="Channel not saved" />
      </form>

      <ErrorAlert error={list.error} />
      <ul className="flex flex-col gap-2">
        {(list.data ?? []).map((ch) => (
          <ChannelRow key={ch.id} channel={ch} onChange={invalidate} />
        ))}
      </ul>
    </section>
  );
}

function ChannelRow({ channel, onChange }: { channel: ChannelOut; onChange: () => void }) {
  const [code, setCode] = useState("");
  const [log, setLog] = useState(false);
  const status = STATUS[channel.status] ?? { label: channel.status, variant: "outline" as const };
  const test = useMutation({ mutationFn: () => channelsApi.test(channel.id) });
  const pair = useMutation({
    mutationFn: () => channelsApi.pair(channel.id, code),
    onSuccess: onChange,
  });
  const toggle = useMutation({
    mutationFn: () =>
      channelsApi.update(channel.id, {
        version: channel.version,
        paused: channel.status !== "paused",
      }),
    onSuccess: onChange,
  });
  const remove = useMutation({
    mutationFn: () => channelsApi.remove(channel.id),
    onSuccess: onChange,
  });
  const deliveries = useQuery({
    queryKey: ["channel-deliveries", channel.id],
    queryFn: () => channelsApi.deliveries(channel.id),
    enabled: log,
  });

  return (
    <li className="flex flex-col gap-2 rounded-lg border p-3 text-sm" aria-label={channel.name}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{channel.name}</span>
        <span className="text-xs text-muted-foreground">
          {KINDS[channel.kind]?.label ?? channel.kind}
        </span>
        <Badge variant={status.variant}>{status.label}</Badge>
        {channel.quiet_start && channel.quiet_end && (
          <span className="text-xs text-muted-foreground">
            quiet {channel.quiet_start}–{channel.quiet_end}
          </span>
        )}
        <span className="ml-auto flex gap-2">
          {channel.status !== "pending_pairing" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => test.mutate()}
              disabled={test.isPending}
            >
              Send test
            </Button>
          )}
          {channel.status !== "pending_pairing" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => toggle.mutate()}
              disabled={toggle.isPending}
            >
              {channel.status === "paused" || channel.status === "error" ? "Resume" : "Pause"}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setLog((v) => !v)}>
            {log ? "Hide log" : "Log"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
          >
            Remove
          </Button>
        </span>
      </div>
      {channel.last_error && (
        <p className="text-xs text-destructive">Last error: {channel.last_error}</p>
      )}
      {test.data && (
        <p role="status" className="text-xs">
          {test.data.ok ? "Test message sent." : `Test failed: ${test.data.error}`}
        </p>
      )}
      {channel.status === "pending_pairing" && channel.kind === "discord" && (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            pair.mutate();
          }}
        >
          <div className="flex flex-col gap-1">
            <Label htmlFor={`pair-${channel.id}`}>Code from the Discord message</Label>
            <Input
              id={`pair-${channel.id}`}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-40 font-mono"
            />
          </div>
          <Button type="submit" size="sm" disabled={!code || pair.isPending}>
            Pair
          </Button>
        </form>
      )}
      {channel.webhook && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 text-xs">
          <dt className="text-muted-foreground">Callback URL</dt>
          <dd className="break-all font-mono">{channel.webhook.callback_url}</dd>
          <dt className="text-muted-foreground">Verify token</dt>
          <dd className="break-all font-mono">{channel.webhook.verify_token}</dd>
        </dl>
      )}
      {log && (
        <ul className="flex flex-col gap-1 text-xs">
          {(deliveries.data ?? []).length === 0 && (
            <li className="text-muted-foreground">Nothing sent yet.</li>
          )}
          {(deliveries.data ?? []).map((d) => (
            <li key={d.id} className="flex flex-wrap gap-2">
              <span className="text-muted-foreground">
                {new Date(d.created_at).toLocaleString()}
              </span>
              <span>{d.title}</span>
              <Badge
                variant={
                  d.status === "sent" ? "default" : d.status === "dead" ? "destructive" : "outline"
                }
              >
                {d.status}
              </Badge>
              {d.last_error && <span className="text-destructive">{d.last_error}</span>}
            </li>
          ))}
        </ul>
      )}
      <ErrorAlert error={test.error ?? pair.error ?? toggle.error ?? remove.error} />
    </li>
  );
}
