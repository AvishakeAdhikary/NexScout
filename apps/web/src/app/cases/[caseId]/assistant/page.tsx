"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { ErrorAlert } from "@/components/error-alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { trackingApi } from "@/lib/api/client";

const SUGGESTIONS = ["What needs me?", "Upcoming deadlines", "Find jobs", "Create my resume"];

export default function AssistantPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const queryClient = useQueryClient();
  const history = useQuery({
    queryKey: ["chat", caseId],
    queryFn: () => trackingApi.chatHistory(caseId),
  });
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const send = useMutation({
    mutationFn: (message: string) => trackingApi.chat(caseId, message),
    onSuccess: () => {
      setText("");
      queryClient.invalidateQueries({ queryKey: ["chat", caseId] });
      queryClient.invalidateQueries({ queryKey: ["runs", caseId] });
    },
  });
  useEffect(() => {
    // Braces matter: scrollIntoView may return a Promise, which an effect must not return.
    end.current?.scrollIntoView({ block: "end" });
  }, [history.data]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (text.trim()) send.mutate(text.trim());
  }

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <header>
        <h1 className="text-2xl font-semibold">Assistant</h1>
        <p className="text-muted-foreground">
          Ask in your own words. The assistant uses the same tools as the screens, follows a fixed
          menu (no AI guessing), and never submits or sends anything: it links you to where you
          approve that.
        </p>
      </header>
      <ErrorAlert error={history.error} />
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
          <Button type="submit" disabled={send.isPending || !text.trim()}>
            Send
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((s) => (
            <Button
              key={s}
              type="button"
              size="sm"
              variant="outline"
              onClick={() => send.mutate(s)}
            >
              {s}
            </Button>
          ))}
        </div>
        <ErrorAlert error={send.error} />
      </form>
    </div>
  );
}
