"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Circle } from "lucide-react";
import Link from "next/link";

import { autopilotApi, channelsApi, factsApi, providersApi } from "@/lib/api/client";

/** First steps for someone new, computed from their real data (nothing is faked or assumed). */
export function GettingStarted({ caseId }: { caseId: string }) {
  const facts = useQuery({
    queryKey: ["facts", caseId, "all"],
    queryFn: () => factsApi.list(caseId),
  });
  const providers = useQuery({ queryKey: ["providers"], queryFn: providersApi.list });
  const channels = useQuery({ queryKey: ["channels"], queryFn: channelsApi.list });
  const pilot = useQuery({
    queryKey: ["autopilot", caseId],
    queryFn: () => autopilotApi.get(caseId),
  });
  if (facts.isPending || providers.isPending || channels.isPending || pilot.isPending) return null;

  const base = `/cases/${caseId}`;
  const confirmed = (facts.data ?? []).filter((f) => f.review_state === "accepted").length;
  const pending = (facts.data ?? []).filter((f) => f.review_state === "pending").length;
  const steps = [
    {
      done: (facts.data ?? []).length > 0,
      title: "Add your CV",
      text: "Upload a CV (PDF, Word or Markdown). NexScout reads it and suggests profile entries.",
      href: `${base}/documents`,
    },
    {
      done: confirmed > 0 && pending === 0,
      title: "Check your profile",
      text: pending
        ? `${pending} entr${pending === 1 ? "y waits" : "ies wait"} for you to confirm. Nothing is used until you do.`
        : "Confirm what NexScout found. Only confirmed entries are ever used.",
      href: `${base}/profile`,
    },
    {
      done: (providers.data ?? []).length > 0,
      title: "Choose an AI model (optional)",
      text: "Needed for letters and statements. Use your own key, or a free model on this computer.",
      href: `${base}/settings`,
      optional: true,
    },
    {
      done: (channels.data ?? []).some((c) => c.status === "active"),
      title: "Get notifications on your phone (optional)",
      text: "Telegram, Discord, WhatsApp, Slack or email: approve and answer from anywhere.",
      href: "/account",
      optional: true,
    },
    {
      done: pilot.data?.policy.enabled ?? false,
      title: "Turn on the autopilot (optional)",
      text: "NexScout searches and prepares on its own, and asks you whenever it needs to.",
      href: `${base}/autopilot`,
      optional: true,
    },
  ];
  if (steps.every((s) => s.done)) return null;
  const next = steps.find((s) => !s.done);

  return (
    <section
      aria-labelledby="start-heading"
      className="flex flex-col gap-3 rounded-xl border border-primary/40 bg-primary/5 p-4"
    >
      <h2 id="start-heading" className="text-lg font-semibold">
        Getting started
      </h2>
      <ol className="flex flex-col gap-2">
        {steps.map((s) => (
          <li key={s.title} className="flex items-start gap-2 text-sm">
            {s.done ? (
              <CheckCircle2 aria-label="Done" className="mt-0.5 size-4 shrink-0 text-primary" />
            ) : (
              <Circle
                aria-label="Not done yet"
                className="mt-0.5 size-4 shrink-0 text-muted-foreground"
              />
            )}
            <span>
              <Link href={s.href} className={s === next ? "font-medium underline" : "underline"}>
                {s.title}
              </Link>
              <span className="block text-muted-foreground">{s.text}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
