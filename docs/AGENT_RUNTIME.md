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

**Pause semantics (as built, ADR-0008):** a pause request on a running run sets
`control_request='pause'` and the run shows `pausing`. The worker lets the current step finish
(including any LLM call inside it), checkpoints, and stops at the next step boundary. The run
becomes `paused` without repeating or half-doing a step. A queued run, or one waiting for approval,
pauses immediately. Resume continues from the checkpoint.
**Cancel semantics:** terminal. A running run shows `cancelling`. The worker drains at the next
boundary or hard-cancels the in-flight step's asyncio task. This is safe because steps are
at-least-once and side effects go through the ledger. Pending approvals of a cancelled run become
`cancelled`.

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
- The lease is `worker_lease_s` (60 s). The heartbeat runs every lease/3, and the reaper runs
  every lease/2 and re-queues expired leases (the first recovery immediately, later ones with
  backoff). A recovered `start` task resumes from the checkpoint if one exists. It never restarts
  the graph.
- At-least-once execution, made effectively-once for side effects by `idempotency_key` + a
  `tool_executions` row written *before* the external call (`status=started`) and updated after.
  On recovery, a `started` row with no result → reconcile → `uncertain` if it can't be determined.
- LangGraph checkpoint `thread_id = run_id`. Resume = re-invoke the graph with `None` input (or
  `Command(resume=...)` after an approval).

## 5. Context management (small models)
`ContextBuilder.build(task, budget)` assembles, in priority order: system/policy → task objective
and output schema → required facts (by ID) → evidence excerpts → prior step summaries → optional
extras, until the token budget (model context − reserved output − safety margin) is reached.
- As built (`agent_runtime/context_builder.py`): `build_context(sections, budget)`. Required
  sections must fit, or it raises `ContextOverflow`. Optional sections are trimmed item by item,
  by priority. `input_budget(context_window, max_output)` sets the budget. The workflow notes when
  the model's context was too small to include everything.
- Token counting: a provider-neutral chars/3.5 estimate plus a 10% safety margin. Per-family
  tiktoken counting isn't used yet. The estimate deliberately over-counts.
- **Compaction:** when the accumulated working memory exceeds 70% of the budget, summarize older step
  results into a `CompactSummary` model. Required fields: decisions, fact_ids, evidence_ids,
  pending_actions, open_questions. A validator rejects summaries that drop IDs present in the input.
- **Malformed output (as built):** `structured()` validates with Pydantic and makes one repair
  attempt that shows the model its errors. If that fails, it raises a typed error. Native
  JSON-schema mode is used where the provider supports it. Reduced-context retry and task
  splitting are **not built yet** (planned with the M5 drafting workflows).

## 6. Memory layers
working (in-graph state) · workflow (Postgres runs/tasks/checkpoints) · profile (accepted facts) ·
research (sources + excerpts + freshness) · project (prompt templates in repo) · conversation
(chat messages table, summarized).

## 7. Budgets and quotas (defaults, configurable)
Global worker concurrency 4 · per-user running tasks 2 · per-run step budget 200 · per-run token
budget 2M · LLM call timeout 120 s · fetch timeout 20 s / 5 MB.

## 8. As built in M4
| Piece | Where |
|---|---|
| Queue, leases, reaper, per-user limit | `agent_runtime/queue.py`, `agent_runtime/worker.py` (`uv run nexscout worker`) |
| Checkpoints | LangGraph `AsyncPostgresSaver`, `durability="sync"`, `thread_id = run_id`, system DB role. Created by `nexscout migrate`; the worker refuses to start without them |
| Run context for nodes | `agent_runtime/context.py` (`tenant()` sessions with RLS, `note`, `require_approval`, `side_effect`, budgets) |
| Workflows | `agents/`: `document_ingestion` (system, started by uploads), `opportunity_discovery`, `profile_summary` (LLM, cited, verified), `system_check` (diagnostic); M5: `phd_research` (read_sources → extract), `draft_document` (gather → assemble or consent → draft → verify → save → render), `render_document` (ADR-0009); M7: `browser_apply` (fill → approve → submit, ADR-0010) |
| Approvals | `interrupt()` in the node. The decision is read from `approval_requests` and never trusted from the resume payload |
| Events | `workflow_events` rows + `LISTEN/NOTIFY`, SSE at `GET /cases/{id}/events` (replays from `Last-Event-ID`; `Cache-Control: no-transform` so proxies don't gzip-buffer it) |
| Providers | `infrastructure/llm/` (ADR-0004). Default = the user's default provider, else the labelled mock |
| UI | Agent Activity (runs, steps with notes, approvals, pause/resume/cancel/retry/rerun/skip, start a workflow), Settings → AI models, Profile → "Draft a summary with AI" |

LLM output is always a proposal. `profile_summary` drops sentences that lack valid citations, and
sentences whose numbers the cited entries don't contain. It stores the draft as a **pending,
inferred** entry and records `is_mock`, so mock text is labelled in the UI.
