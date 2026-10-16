# ADR-0002: Postgres-backed durable task queue, no Redis initially

- **Status:** Accepted
- **Date:** 2026-10-16

## Context
Long-running agent work (research, document generation, browser automation) must survive
restarts, crashes and reboots (§14). It must support pause, resume, cancel and retry, and it must
never execute the same task concurrently on two workers. Postgres is mandated as the source of
truth. Redis is suggested only "where justified".

## Decision
Implement the queue in Postgres:
- `tasks` rows carry `status`, `lease_owner`, `lease_expires_at`, `attempt`, `max_attempts`,
  `next_attempt_at`, `idempotency_key` (unique per run) and `priority`.
- Claiming: a single short transaction `SELECT … WHERE status='queued' AND next_attempt_at<=now()
  ORDER BY priority, created_at FOR UPDATE SKIP LOCKED LIMIT n`, then set status `running`, the lease
  owner and expiry, and commit. **No lock is held while the task executes.**
- Heartbeats extend the lease. A reaper re-queues tasks whose lease expired (attempt+1, or
  `failed` once attempts are exhausted).
- Pause and cancel are columns on `workflow_runs` (`control_request`). Workers check them at node
  boundaries and before any side effect. Cancellation reaches in-flight async calls through task
  cancellation.
- Wake-ups: `NOTIFY nexscout_tasks` on enqueue, with a polling fallback interval (default 2 s) so a
  missed notification only adds latency.
- LangGraph state is persisted by `langgraph-checkpoint-postgres` in the same database.

## Alternatives considered
- **Redis + RQ/Celery/arq:** adds an extra service and a second source of truth. Redis persistence
  is not a substitute for transactional state, and recovery semantics get split across two stores.
- **Temporal / Hatchet / DBOS:** strong guarantees, but a heavy service footprint for a
  desktop-capable app. Revisit if multi-node scale demands it.

## Consequences
- One fewer service in dev, desktop and prod. Queue throughput is bounded by Postgres, which is ample
  for per-user agent workloads (tens of tasks per second).
- Add Redis later only for measured needs: distributed rate limiting across many API replicas,
  or caching hot research results. That needs a new ADR.
