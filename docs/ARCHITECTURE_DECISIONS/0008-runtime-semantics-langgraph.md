# ADR-0008: Durable runtime semantics on LangGraph 1.2 + Postgres checkpointer

- **Status:** Accepted
- **Date:** 2026-10-16
- **Evidence:** spike against Postgres 17 on the Windows Selector loop (langgraph 1.2.15,
  langgraph-checkpoint-postgres 3.2.0, psycopg-pool).

## Verified behaviour
| Need | Mechanism | Verified result |
|---|---|---|
| Durable state per step | `astream(..., durability="sync")` with `AsyncPostgresSaver(AsyncConnectionPool(autocommit, prepare_threshold=0, dict_row))`, `thread_id = run_id` | state persisted after every step |
| Pause at a safe point | `RunControl().request_drain("pause")` → `GraphDrained` raised at the next step boundary | `next` points at the following node; resume continues there |
| Approval gate | `interrupt(payload)` inside a node; resume with `Command(resume=value)` | the interrupted node **re-executes from its start** and `interrupt()` returns the value |
| Crash / retry | exception propagates; re-invoke with `None` | resumes at the failed node; prior steps are not re-run |
| Rerun a step | `aget_state_history` → checkpoint whose `next == (node,)` → invoke with that checkpoint config | forks from that checkpoint; the node runs again |
| Skip an optional step | `aupdate_state(config, {}, as_node=node)`, then resume | (used by the runtime; covered by system tests) |
| Delete | `adelete_thread(run_id)` | state gone |
| Context injection | `StateGraph(State, context_schema=Ctx)`; node signature `(state, runtime: Runtime[Ctx])`; `astream(context=ctx)` | works |

## Consequences / rules
1. **Nodes are at-least-once.** A node may run again after a crash, a drain, or an approval
   resume (observed: a node with an interrupt ran 3×). Therefore:
   - Code before `interrupt()` must be idempotent (approval rows are keyed `run:node:kind`).
   - DB writes by nodes use natural/idempotency keys (upserts), never blind inserts.
   - External side effects go through the `tool_executions` ledger. `started` with no result
     after a crash becomes `uncertain` and is never silently retried.
2. Pause takes effect at the next step boundary. A node that has already started runs to
   completion or to its interrupt. Cancel additionally cancels the in-flight asyncio task, which
   aborts awaited LLM/HTTP calls. Side-effect tools are protected by the ledger.
3. Approval decisions are read from `approval_requests` (written by an authenticated API call),
   never from model output or from the resume payload alone.
4. Checkpoint tables are created by `nexscout migrate` (`saver.setup()` as the owner role) and are
   accessed only by the worker's system role. They hold workflow state for runs and are purged
   with the run (worker housekeeping deletes threads whose run no longer exists).
5. Our Postgres task queue (ADR-0002) decides *when* and *where* a run advances. LangGraph decides
   *what* the next step is. A run is advanced by exactly one leased task at a time.
