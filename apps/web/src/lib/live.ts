"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { runsApi, TERMINAL_RUN_STATES, type RunDetailOut } from "./api/client";

/**
 * One Server-Sent Events connection per case. Every workflow event refreshes the data it may
 * have changed. If the stream drops, the browser's EventSource reconnects and resumes from the
 * last event id; screens also keep a slow poll as a fallback.
 */
export function useCaseEvents(caseId: string): { connected: boolean } {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const source = new EventSource(runsApi.eventsUrl(caseId));
    const refresh = () => {
      for (const key of [
        "runs",
        "run",
        "approvals",
        "documents",
        "facts",
        "gaps",
        "opportunities",
        "mindmap",
        "research",
        "generated",
        "generated-doc",
        "applications",
        "application",
      ]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    };
    const types = [
      "run_created",
      "run_running",
      "run_waiting",
      "run_paused",
      "run_pausing",
      "run_succeeded",
      "run_failed",
      "run_cancelled",
      "run_cancelling",
      "run_resumed",
      "run_recovering",
      "run_requeued",
      "run_retry_scheduled",
      "step_started",
      "step_succeeded",
      "step_failed",
      "step_progress",
      "step_skipped",
      "approval_required",
      "approval_decided",
    ];
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    for (const t of types) source.addEventListener(t, refresh);
    return () => source.close();
  }, [caseId, queryClient]);
  return { connected };
}

/** A run's detail, refreshed by live events with a poll while it is still active. */
export function useRun(runId: string | null | undefined) {
  return useQuery<RunDetailOut>({
    queryKey: ["run", runId],
    queryFn: () => runsApi.get(runId!),
    enabled: !!runId,
    refetchInterval: (q) =>
      q.state.data &&
      TERMINAL_RUN_STATES.has(q.state.data.run.status) &&
      q.state.data.run.status !== "waiting_approval"
        ? false
        : 2000,
  });
}
