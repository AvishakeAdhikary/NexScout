# NexScout Roadmap and Checkpoint

Status legend: ⬜ not started · 🟨 in progress · ✅ done (tests executed and passed) · ⛔ blocked

## Checkpoint (update at the end of every session)
- **Date:** 2026-10-16
- **Current milestone:** M4 Durable agent runtime (⬜ next). M0–M3 ✅.
- **Done so far:**
  - M0: all §2.2 docs + ADR-0001…0007.
  - M1: auth (argon2id, hashed opaque sessions, CSRF, DB rate limiting), cases with optimistic
    locking, audit log, forced RLS + least-privilege grants, health/readiness, CLI, compose,
    Dockerfiles, CI workflow, Next.js shell, E2E.
  - M2 backend: section schemas + gaps (`domain/profile.py`), conservative heuristic CV extractor
    with verbatim evidence spans (`domain/cv_heuristics.py`), content sniffing, parsing in a
    killable subprocess, per-owner content-addressed ObjectStore, migration `0002` (7 owned
    tables), APIs: documents, facts (create/edit-with-original/bulk review/merge/delete/evidence),
    gaps, snapshots, preferences (sensitive attributes private, never scored), social links
    (validated, never fetched), affiliations (referral use opt-in), account export + deletion.
  - M2 web: Documents (upload with purpose, status, download, delete with an option to also
    remove unreviewed entries), My Profile (review queue with source excerpts, accept/reject/
    edit-then-accept, accept-all per section, confirmed profile, privacy toggle, add entry,
    gaps, profile links, preferences incl. strict/flexible experience mode and private
    eligibility details), Relationships (table + permissions), Account (export, delete).
  - M3: mind map built only from accepted facts (derived edges flagged with a basis; stable
    keys; overrides survive regeneration; orphaned overrides reported), React Flow + ELK view
    with an accessible list alternative, an evidence panel, map-only renames, snapshot history
    and compare. Opportunity domain: URL/title/employer normalization, guard-first dedup,
    explainable matching (factors + fact ids + gaps, strict/flexible), shared public catalog vs
    owned per-case matches, three labelled demo sources, incremental sync (content hash,
    resumable cursor, per-listing transactions with sorted advisory locks), PhD and Jobs pages
    (demo banner, explained estimates, shortlist/dismiss, report wrong merge, source toggles).
  - The IDOR guard test was silently checking nothing (FastAPI 0.143 `_IncludedRouter`). It was
    rewritten to enumerate routes from OpenAPI with a minimum-count assertion, and now covers 40 routes.
- **Environment:** Windows 11, Docker Desktop 29.8.2 (CLI at
  `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`, on the user PATH), Python 3.13.15 via uv,
  Node 26.10, Postgres 17 in compose.
- **Blockers:** none.
- **Interim decisions still in force:** ingestion runs in the upload request (isolated subprocess,
  20 s cap) until the M4 worker. The extractor is the deterministic `heuristic_v1` (not AI). LLM
  extraction arrives with the provider layer (M4).
- **Next exact steps (M4):**
  1. Verify LangGraph 1.2 + `langgraph-checkpoint-postgres` 3.2 APIs against the installed source
     (AsyncPostgresSaver setup, interrupt/Command resume), and psycopg async on the Windows
     Selector loop.
  2. Migration `0004`: workflow_runs, tasks, task_attempts, workflow_events, approval_requests,
     tool_executions, usage_records, worker_heartbeats. Owned with RLS, plus a narrowly scoped
     `nexscout_system` role (BYPASSRLS) used only to claim and reap queue rows.
  3. `agent_runtime/`: queue (claim with SKIP LOCKED, leases, heartbeats, reaper,
     backoff+jitter), worker process `nexscout worker`, control requests (pause/resume/cancel/
     retry/rerun/skip), idempotency keys, events + LISTEN/NOTIFY + SSE endpoint.
  4. LLM provider layer (ADR-0004): mock (labelled), OpenAI-compatible (Ollama/LM Studio/OpenAI),
     Anthropic, Gemini adapters with capability metadata, structured-output validate/repair,
     usage records; ContextBuilder with budgets and validated compaction.
  5. First real workflows: move document ingestion and opportunity sync onto the worker
     (removes the M2/M3 interim in-request processing); a demo workflow with an approval gate.
  6. Agent Activity UI (live via SSE, controls, approvals). System tests: kill the worker
     mid-run, then resume from checkpoint with no duplicate side effects; pause/cancel semantics.

## Test evidence log
| Date | Command | Result |
|---|---|---|
| 2026-10-16 | first `NEXSCOUT_REQUIRE_DB=1 uv run pytest` against Postgres | 56 passed, 4 failed in 472 s (RLS owner, alembic_version grant, slow localhost). All fixed |
| 2026-10-16 | M1: same, after fixes | 60 passed in 5.8 s |
| 2026-10-16 | M1: `npm run e2e` + `docker compose --profile full` | 3/3 E2E; images build; api healthy (non-root) |
| 2026-10-16 | M2: `NEXSCOUT_REQUIRE_DB=1 uv run pytest` | **121 passed** (incl. IDOR sweep over 28 ID routes, forced-RLS check on all owned tables) |
| 2026-10-16 | M2: ruff, ruff format, mypy strict (48 files); web tsc, eslint, vitest 12/12, `next build` | all passed |
| 2026-10-16 | M2: `npm run e2e` (Chromium, real API + DB) | **4/4 passed** incl. upload → review vs source → accept/edit/reject → add → links/prefs/relationships → fresh session → export → intruder sees nothing |
| 2026-10-16 | M2: `scripts/check_restart_persistence.py` (hard-kill API process tree, restart) | **PASSED**: 16/16 facts, accepted state, document and original bytes intact |
| 2026-10-16 | M3: `NEXSCOUT_REQUIRE_DB=1 uv run pytest` | **158 passed** (incl. concurrent two-user sync, IDOR sweep over 40 ID routes) |
| 2026-10-16 | M3: web tsc, eslint, vitest 12/12, `next build` | passed |
| 2026-10-16 | M3: `npm run e2e` | **6/6 passed** incl. mind map (list view, evidence panel, rename persists, snapshot compare) and job discovery (demo label, explanations, multi-source listing, strict-mode hiding with reasons, no duplicates on re-run) |
| — | GitHub Actions CI | **not run** (no remote configured) |

---

## Milestones
Architecture: `docs/ARCHITECTURE.md`. Decisions: `docs/ARCHITECTURE_DECISIONS/`.

| # | Milestone | Status | Acceptance criteria |
|---|---|---|---|
| M0 | Discovery and architecture | ✅ | Architecture, conventions, data ownership, security boundaries and the first vertical slice are documented |
| M1 | Runnable foundation | ✅ | Dev can start the app from the docs, log in, create an isolated case, and run the tests. User B gets 404 on A's case. RLS blocks raw cross-tenant SQL |
| M2 | Profile and ingestion | ✅ | Upload PDF/DOCX/MD → review extracted facts → edit profile → data persists across restart |
| M3 | Mind map and opportunities | ✅ | Evidence-linked mind map (graph and table). Normalized, deduplicated opportunities from fixture sources with explained matches |
| M4 | Durable agent runtime | ⬜ | Workflow survives worker or app restart, resumes from its checkpoint, and respects pause, cancel and authorization. No duplicate side effects |
| M5 | PhD research workflow | ⬜ | Fixture workflow discovers opportunities, stores evidence, generates editable documents, and flags missing info without inventing facts |
| M6 | Job discovery and matching | ⬜ | Repeated searches don't duplicate. Matches and experience gaps are explained |
| M7 | Browser automation and approvals | ⬜ | Fixture application flow completes, stops at approval gates, and distinguishes confirmed from uncertain submission |
| M8 | Tracking and dashboard | ⬜ | Track applications, inspect agent work, pause workflows, review documents and resolve blocked tasks in the UI |
| M9 | Desktop and providers | ⬜ | Desktop builds install and run. Each advertised provider or integration has a verified capability profile |
| M10 | Production hardening | ⬜ | Security, isolation, concurrency and recovery tests pass. Backup and restore and migration upgrades are tested. Deployment is reproducible |

## Deferred / open items
_(Each item: dependency, concrete plan, acceptance test.)_
