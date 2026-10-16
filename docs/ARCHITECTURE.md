# NexScout Architecture

Decisions with alternatives are recorded in [ARCHITECTURE_DECISIONS/](ARCHITECTURE_DECISIONS/).

## 1. System context
```
 Browser (Next.js UI) ──same-origin /api/*──▶ Next.js server ──rewrite──▶ FastAPI (api)
                                                                         │  ▲ SSE
                                                                         ▼  │
 Electron (M9) ──local or remote backend──▶ FastAPI               PostgreSQL 17 ◀── nexscout-worker(s)
                                                                  (state, queue,     │  LangGraph graphs
                                                                   checkpoints,      │  LLM providers
                                                                   events)           │  Playwright
                                                                         ▲           │  safe fetcher
                                                    ObjectStore (fs/S3) ─┴───────────┘
 External: LLM providers (BYOK) · permitted research/job sources · application sites (authorized)
```

## 2. Processes
| Process | Responsibility | Scales |
|---|---|---|
| `web` | Next.js UI. Rewrites `/api/*` to the API. Holds no secrets | horizontally |
| `api` | FastAPI: auth, CRUD use cases, enqueueing workflows, SSE, approvals | horizontally (stateless) |
| `worker` | Claims tasks, runs LangGraph nodes, LLM calls, fetches, rendering, browser automation | horizontally. Leases prevent double execution |
| `postgres` | Source of truth: domain data, sessions, queue, checkpoints, events, audit | vertical. Backups via pg_dump/WAL |

Nothing long-running happens inside an API request. Requests enqueue and return.

## 3. Backend layering
See AGENTS.md §2.1. Request flow:
`router → dependency (current_actor, db session with app.user_id) → use case → domain logic →
repository → commit → response`. Errors map to RFC 9457 problem+json.

## 4. Key flows
### 4.1 Document ingestion (M2)
upload → validate (size, magic bytes) → store (sha256 content address) → `documents` row →
enqueue `ingest_document` → worker parses text with spans → section splitter → extraction
(LLM structured or mock) → `profile_facts` (status `extracted`, `review_state=pending`) +
`fact_evidence` (document_id, page, char span, excerpt) → events → the user reviews in the UI → accept /
edit / reject → profile snapshot.

### 4.2 Workflow run (M4+)
`POST /runs` → `workflow_runs` (pending) + root task queued → worker claims (lease) → executes the
LangGraph graph step with a Postgres checkpointer (`thread_id = run_id`) → each node: check control
flags → build context → call tools/LLM → validate → write *proposals* through use cases → emit events
→ `interrupt()` for approvals → `approval_requests` row → user decides → resume.

### 4.3 Opportunity pipeline (M3, M5, M6)
SourceAdapter.search(query, checkpoint) → raw records → normalize → entity resolution
(employer/institution) → dedup (deterministic rules + similarity thresholds) → upsert opportunity
+ source link → match scoring (explainable factors and gaps) → shortlist.

### 4.4 Submission (M7)
application `approved` → browser task → fill (no submit) → screenshot + field map → approval request
"Submit to X" → on approval: click submit with idempotency guard → detect confirmation →
`submitted` | `submission_uncertain` (requires user reconciliation).

## 5. Frontend
Next.js App Router. Route groups: `(auth)` for login and register, `(app)` for the authenticated shell
with nav: Dashboard, My Profile, Mind Map, PhD Opportunities, Job Opportunities, Applications,
Documents, Relationships, Agent Activity, Settings. Data comes from TanStack Query against typed
contracts. SSE drives live activity. A case switcher sits in the header (the active case is stored in
the URL as `/cases/[caseId]/...`).

## 6. Deployment modes
- **Dev:** `docker compose up -d postgres`, with api, worker and web run natively (hot reload). Or all
  in compose with the `full` profile.
- **Server:** containers for web, api and worker plus managed Postgres. Secrets come from env or a
  secret manager.
- **Desktop (M9):** Electron starts a bundled api+worker pair against either a local Postgres
  (bundled or user-installed) or a remote backend. The choice is explicit in settings.

## 7. Cross-cutting
- Correlation: `X-Request-ID` → logs. `run_id` and `task_id` are bound in worker logs and events.
- Usage: every LLM call writes `usage_records` (provider, model, tokens, latency, cost estimate).
- Config: `pydantic-settings`, prefix `NEXSCOUT_`. See `.env.example`.
