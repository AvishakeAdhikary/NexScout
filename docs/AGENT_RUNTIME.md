# NexScout Agent Runtime

Queue design: ADR-0002. Providers: ADR-0004. Events: ADR-0006.

## 1. Logical agents → implementation
| Logical agent (§9.1) | Implementation |
|---|---|
| Orchestrator | Deterministic workflow definitions (LangGraph graphs) plus an LLM planner only for free-form chat intents, constrained to a fixed menu of workflows |
| Profile | `ingest_document` graph: parse → split → extract (structured) → validate → propose facts |
| Research | discovery and requirement-extraction nodes over SourceAdapters and the safe fetcher |
| Matching | deterministic `domain/matching.py` + optional LLM explanation wording |
| Document | drafting node (LLM) → verifier node → render node |
| Browser | Playwright task runner with a step policy (no-submit unless approved) |
| Tracking | scheduled tasks for reminders and status checks |
| Quality/Verification | `verify_claims` node: sentence → supporting fact IDs. Unsupported → flagged |

These are logical capabilities. Several run in the same worker process.

## 2. Run lifecycle
```
pending → running ⇄ waiting_approval
running → pausing → paused → (resume) → running
running/paused/waiting_approval → cancelling → cancelled
running → failed (attempts exhausted / non-retryable) → (retry step) → running
running → succeeded
```
Task lifecycle: `queued → running → (succeeded | failed | retry_wait → queued | cancelled | blocked)`.
Transitions live in `domain/state_machines.py`. Illegal transitions raise.

**Pause semantics:** a pause request sets `control_request='pause'`. The worker finishes or aborts the
current *idempotent* step at the next safe point, persists the checkpoint, then marks the run `paused`. In-flight
LLM calls are cancelled (they are safe to repeat). In-flight side effects (submit, send) are never
interrupted mid-call. They complete or are reconciled.
**Cancel semantics:** same as pause, but terminal. The UI shows `cancelling` until the worker confirms `cancelled`.

## 3. Task contract
```python
class TaskSpec(BaseModel):
    key: str                    # e.g. "phd.research_requirements"
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    allowed_tools: frozenset[str]
    timeout_s: int
    max_attempts: int
    retry_backoff: Backoff      # exponential + jitter
    side_effect: bool           # True → needs idempotency key + approval policy check
    depends_on: tuple[str, ...]
```

## 4. Leases and recovery
- Lease 60 s, heartbeat every 20 s. The reaper runs every 30 s and re-queues expired leases.
- At-least-once execution, made effectively-once for side effects by `idempotency_key` + a
  `tool_executions` row written *before* the external call (`status=started`) and updated after.
  On recovery, a `started` row with no result → reconcile → `uncertain` if it can't be determined.
- LangGraph checkpoint `thread_id = run_id`. Resume = re-invoke the graph with `None` input (or
  `Command(resume=...)` after an approval).

## 5. Context management (small models)
`ContextBuilder.build(task, budget)` assembles, in priority order: system/policy → task objective
and output schema → required facts (by ID) → evidence excerpts → prior step summaries → optional
extras, until the token budget (model context − reserved output − safety margin) is reached.
- Token counting: tiktoken (`o200k_base`/`cl100k_base`) when the model family is known, otherwise
  chars/3.5 heuristic, with a 10% safety margin.
- **Compaction:** when the accumulated working memory exceeds 70% of the budget, summarize older step
  results into a `CompactSummary` model. Required fields: decisions, fact_ids, evidence_ids,
  pending_actions, open_questions. A validator rejects summaries that drop IDs present in the input.
- **Overflow / malformed output:** retry with reduced context (drop optional sections), then split the
  task into smaller subtasks (e.g. per section), then fail with a typed error.

## 6. Memory layers
working (in-graph state) · workflow (Postgres runs/tasks/checkpoints) · profile (accepted facts) ·
research (sources + excerpts + freshness) · project (prompt templates in repo) · conversation
(chat messages table, summarized).

## 7. Budgets and quotas (defaults, configurable)
Global worker concurrency 4 · per-user running tasks 2 · per-run step budget 200 · per-run token
budget 2M · LLM call timeout 120 s · fetch timeout 20 s / 5 MB.
