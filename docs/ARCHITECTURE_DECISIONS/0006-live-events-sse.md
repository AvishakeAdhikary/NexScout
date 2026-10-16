# ADR-0006: Live agent activity via workflow_events + LISTEN/NOTIFY + SSE

- **Status:** Accepted
- **Date:** 2026-10-16

## Context
The UI must show live agent activity without aggressive polling (§16). Updates flow one way, from
server to client.

## Decision
- Workers append rows to `workflow_events` (durable, with a per-run monotonic `seq`) and
  `NOTIFY nexscout_events, '<run_id>'`.
- The API exposes `GET /api/v1/runs/{id}/events` and `GET /api/v1/cases/{id}/events` as
  **Server-Sent Events**. The handler authorizes ownership, replays from `Last-Event-ID`, then streams
  new rows on notification. It sends a heartbeat comment every 15 s.
- A client that reconnects resumes from its last seq. Nothing is lost, because events live in Postgres.

## Alternatives
WebSockets (bidirectional and not needed. Harder through proxies). Polling (wasteful, laggy).

## Consequences
Each SSE connection holds one async listener. Connections are pooled per process through a single
shared LISTEN connection that fans out internally.
