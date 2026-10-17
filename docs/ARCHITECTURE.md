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

### 4.5 Notifications and chat actions (M11, ADR-0013)
notification row and outbox rows in one transaction → worker delivery loop (per-channel order,
retries, dead letter, circuit breaker, quiet hours) → provider API → button press or reply comes
back (Telegram long poll, Discord Gateway, WhatsApp webhook stored in the inbox, then
signature-checked by the worker) → idempotent per provider event → paired identity checked →
`runs.decide` or `answers.record_answer` in the owner's RLS session.

### 4.6 Autopilot (M12, ADR-0014)
policy (consented, deterministic) → scheduled `autopilot_cycle` (discover → shortlist with
reasons) → `autopilot_items` → reconciler on each worker tick: research → drafts → placeholders
from the answer bank (or a question) → render → application → `browser_apply` (autopilot) →
`may_auto_submit` ? recorded policy approval : approval sent to the user's channels → submit once.
CAPTCHA or sign-in → hand-over (assisted window in local mode). STOP anywhere → `stop_all`.

## 5. Frontend
Next.js App Router. Route groups: `(auth)` for login and register, `(app)` for the authenticated shell
with nav: Dashboard, My Profile, Mind Map, PhD Opportunities, Job Opportunities, Applications,
Documents, Relationships, Agent Activity, Settings. Data comes from TanStack Query against typed
contracts. SSE drives live activity. A case switcher sits in the header (the active case is stored in
the URL as `/cases/[caseId]/...`).

### Look and feel (as built)
- Dark by default with a light or system toggle (next-themes, a `class` on `<html>`).
- Shadcn tokens in OKLCH ("night sky" indigo-violet); fonts from next/font: Plus Jakarta Sans,
  Space Grotesk, JetBrains Mono.
- A scalable SVG logo, plus `app/icon.svg`.
- Motion uses CSS only (tw-animate-css plus a few keyframes). `prefers-reduced-motion` turns it
  all off.

## 6. Deployment modes
- **Dev:** `docker compose up -d postgres`, with api, worker and web run natively (hot reload). Or all
  in compose with the `full` profile.
- **Server:** containers for web, api and worker plus managed Postgres. Secrets come from env or a
  secret manager.
- **Desktop (M9, M13):** Electron in one of three modes, chosen explicitly at setup:
  - **Easy:** NexScout's own Docker stack on the released images (`easy/docker-compose.yml`),
    with secrets in OS secure storage.
  - **Remote:** connect to a NexScout server.
  - **Local:** run from a source checkout (developers).
- **Easy bundle (M13):** double-click scripts plus the compose file on released images; needs
  only Docker Desktop.
- **Releases (M13):** every green `main` push makes a minor-bumped tag, GHCR images, the Windows
  installer and the easy bundle (`release.yml`).

## 7. Cross-cutting
- Correlation: `X-Request-ID` → logs. `run_id` and `task_id` are bound in worker logs and events.
- Usage: every LLM call writes `usage_records` (provider, model, tokens, latency, cost estimate).
- Config: `pydantic-settings`, prefix `NEXSCOUT_`. See `.env.example`.
