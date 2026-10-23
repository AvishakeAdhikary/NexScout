"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { ApprovalCard } from "@/components/approval-card";
import { ErrorAlert } from "@/components/error-alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { providersApi, trackingApi } from "@/lib/api/client";
import { useRun } from "@/lib/live";

const SUGGESTIONS = ["What needs me?", "Upcoming deadlines", "Find jobs", "Create my resume"];
const AI_SUGGESTIONS = [
  "What are my best job matches?",
  "Which deadlines are coming up?",
  "What is my profile missing?",
];
const FINISHED = new Set(["succeeded", "failed", "cancelled"]);

export default function AssistantPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const queryClient = useQueryClient();
  const conversation = useQuery({
    queryKey: ["conversation", caseId],
    queryFn: () => trackingApi.conversation(caseId),
  });
  const convId = conversation.data?.id;
  const history = useQuery({
    queryKey: ["chat", caseId, convId],
    queryFn: () => trackingApi.chatHistory(caseId, convId),
    enabled: !!convId,
  });
  const providers = useQuery({ queryKey: ["providers"], queryFn: providersApi.list });
  const model = providers.data?.find((p) => p.is_default) ?? null;
  // AI is on by default once a model is set up; without one, the rule-based assistant answers.
  const [aiChoice, setAiChoice] = useState<boolean | null>(null);
  const useAi = !!model && (aiChoice ?? true);
  const [text, setText] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const run = useRun(runId);
  const runStatus = run.data?.run.status;
  const thinking = !!runId && !FINISHED.has(runStatus ?? "");
  const end = useRef<HTMLDivElement>(null);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["chat", caseId] });
    void queryClient.invalidateQueries({ queryKey: ["conversation", caseId] });
    void queryClient.invalidateQueries({ queryKey: ["runs", caseId] });
  };
  useEffect(() => {
    if (runStatus && FINISHED.has(runStatus)) refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once per finished reply
  }, [runStatus]);
  const send = useMutation({
    mutationFn: async (message: string) => {
      if (useAi && convId) {
        const started = await trackingApi.chatAi(caseId, message, convId);
        setRunId(started.run_id);
      } else {
        await trackingApi.chat(caseId, message, convId);
      }
    },
    onSuccess: () => {
      setText("");
      refresh();
    },
  });
  const startOver = useMutation({
    mutationFn: () => trackingApi.newConversation(caseId),
    onSuccess: () => {
      setRunId(null);
      refresh();
    },
  });
  const clear = useMutation({
    mutationFn: () => trackingApi.clearConversation(convId!),
    onSuccess: () => {
      setRunId(null);
      refresh();
    },
  });
  useEffect(() => {
    // Braces matter: scrollIntoView may return a Promise, which an effect must not return.
    end.current?.scrollIntoView({ block: "end" });
  }, [history.data, runStatus]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (text.trim()) send.mutate(text.trim());
  }

  const pendingApprovals = (run.data?.approvals ?? []).filter((a) => a.status === "pending");
  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Assistant</h1>
        <p className="text-muted-foreground">
          Ask in your own words. The assistant looks things up with the same tools as the screens
          and can start searches, research or drafts. It never submits, sends, approves or deletes
          anything: it links you to where you do that yourself.
        </p>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {model ? (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={useAi}
                onChange={(e) => setAiChoice(e.target.checked)}
              />
              Use AI ({model.name})
              {model.data_leaves_device ? (
                <Badge variant="outline">online: asks you once per conversation</Badge>
              ) : (
                <Badge variant="outline">on this computer</Badge>
              )}
            </label>
          ) : (
            <span className="text-muted-foreground">
              Without AI: a fixed menu.{" "}
              <Link className="underline" href={`/cases/${caseId}/settings`}>
                Choose an AI model
              </Link>{" "}
              for an assistant that understands more.
            </span>
          )}
          <span className="ml-auto flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={startOver.isPending}
              onClick={() => startOver.mutate()}
            >
              New conversation
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={!convId || clear.isPending}
              onClick={() => {
                if (window.confirm("Delete this conversation?")) clear.mutate();
              }}
            >
              Clear
            </Button>
          </span>
        </div>
      </header>
      <ErrorAlert error={conversation.error ?? history.error} />
      <ol className="flex flex-col gap-3" aria-label="Conversation" aria-live="polite">
        {(history.data ?? []).map((m) => (
          <li
            key={m.id}
            className={
              m.role === "user"
                ? "self-end rounded-lg bg-muted px-3 py-2"
                : "rounded-lg border px-3 py-2"
            }
          >
            <span className="sr-only">{m.role === "user" ? "You:" : "Assistant:"}</span>
            <p className="whitespace-pre-line text-sm">{m.content}</p>
            {m.actions.length > 0 && (
              <ul className="mt-1 flex flex-wrap gap-2 text-sm">
                {m.actions.map((a) => (
                  <li key={`${m.id}-${String(a.href)}-${String(a.label)}`}>
                    <Link className="underline" href={String(a.href)}>
                      {String(a.label)}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
      {pendingApprovals.map((a) => (
        <ApprovalCard key={a.id} approval={a} caseId={caseId} />
      ))}
      {thinking && pendingApprovals.length === 0 && (
        <p role="status" className="text-sm text-muted-foreground">
          The assistant is working on it…
        </p>
      )}
      {runStatus === "failed" && (
        <p role="alert" className="text-sm text-destructive">
          The assistant couldn&apos;t answer: {run.data?.run.error}
        </p>
      )}
      <div ref={end} />
      <form onSubmit={submit} className="flex flex-col gap-2">
        <Label htmlFor="chat-input">Message</Label>
        <div className="flex gap-2">
          <Input
            id="chat-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={2000}
          />
          <Button type="submit" disabled={send.isPending || thinking || !text.trim()}>
            Send
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {(useAi ? AI_SUGGESTIONS : SUGGESTIONS).map((s) => (
            <Button
              key={s}
              type="button"
              size="sm"
              variant="outline"
              disabled={send.isPending || thinking}
              onClick={() => send.mutate(s)}
            >
              {s}
            </Button>
          ))}
        </div>
        <ErrorAlert error={send.error ?? startOver.error ?? clear.error} />
      </form>
    </div>
  );
}
