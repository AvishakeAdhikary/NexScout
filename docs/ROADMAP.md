# NexScout Roadmap and Checkpoint

Status legend: ⬜ not started · 🟨 in progress · ✅ done (tests executed and passed) · ⛔ blocked

## Checkpoint (update at the end of every session)
- **Date:** 2026-10-16
- **Current milestone:** M2 Candidate profile and document ingestion (🟨). M0 ✅, M1 ✅.
- **Done so far:**
  - M0: all §2.2 docs + ADR-0001…0007 (versions checked against PyPI/npm on 2026-10-16).
  - M1 backend (`backend/src/nexscout`): config, structlog with redaction, domain state machines,
    case rules, argon2id auth with hashed opaque sessions, CSRF double-submit, DB-backed login
    rate limiting, case CRUD with optimistic locking, audit log, RLS (+ owner BYPASSRLS),
    least-privilege grants, Alembic `0001`, `/healthz`, `/readyz` (bounded 3 s),
    `nexscout serve|migrate` CLI (Windows Selector loop for psycopg), docker-compose plus role init SQL.
  - M1 web (`apps/web`, Next.js 16.4.2): `/api/*` rewrite to FastAPI, proxy redirect without a
    session cookie, login/register, case list/create, case workspace with §16 nav, career-path
    selection (R-PATH-1), honest "not available yet" pages, typed client generated from OpenAPI,
    Vitest unit tests, Playwright E2E (`apps/web/e2e`).
  - Containers: `docker compose --profile full` builds and runs (api non-root, healthy).
  - Bugs found by running the code and fixed: `/readyz` hung without a DB; `.test` emails rejected;
    untrimmed emails rejected; FORCE RLS blocked the owner role (→ BYPASSRLS on owner);
    app role couldn't read `alembic_version` (→ grant); `localhost` cost 10 s per DB connection on
    Windows (→ 127.0.0.1); career-path radio bounced until the server answered (→ instant local
    state); the password lingered in the hidden, still-mounted register form (→ form reset).
  - M2 backend done: section schemas + gaps (`domain/profile.py`), heuristic CV extractor with
    verbatim evidence spans (`domain/cv_heuristics.py`), content sniffing + isolated, killable
    parser subprocess (pypdf/python-docx/markdown), content-addressed per-owner ObjectStore,
    migration `0002` (7 owned tables, forced RLS, grants), APIs for documents, facts (create,
    edit with original kept, bulk review, merge, delete, evidence), gaps, snapshots, preferences
    (sensitive attrs private, never scored), social links (validated, never fetched),
    affiliations (referral use off by default), account export (zip) and deletion.
  - Security tests: IDOR sweep over all 28 ID routes (404 for another user), a guard test that fails
    when a new ID route isn't swept, and forced RLS + policy verified on every owned table.
- **Environment:** Windows 11, Docker Desktop 29.8.2 (CLI at
  `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`, on the user PATH), Python 3.13.15 via uv,
  Node 26.10, Postgres 17 in compose.
- **Blockers:** none.
- **Interim decision (M2):** ingestion runs inside the upload request with hard limits (size,
  pages, time) because the durable worker arrives in M4. M4 moves it to the queue. The extractor
  in M2 is a deterministic **heuristic** (labelled `method=heuristic`, not an LLM). LLM
  extraction arrives with the provider layer in M4.
- **Next exact steps (M2):**
  4. Web: Documents (upload/list/delete), Profile (review queue: accept/edit/reject/private;
     add/edit facts; gaps), Relationships (affiliations table).
  5. E2E: upload fixture CV → review → accept → restart API → still there; second user can't see it.

## Test evidence log
| Date | Command | Result |
|---|---|---|
| 2026-10-16 | `uv run ruff check . && uv run ruff format --check . && uv run mypy` | passed (mypy strict, 33 files) |
| 2026-10-16 | `uv run pytest -q` (no DB yet) | 37 passed, 23 skipped (Postgres unreachable) |
| 2026-10-16 | web: `npm run typecheck`, `eslint .`, `vitest run`, `next build` | passed; 12/12 vitest; build OK |
| 2026-10-16 | first `NEXSCOUT_REQUIRE_DB=1 uv run pytest` against Postgres | **56 passed, 4 failed** in 472 s (RLS owner, alembic_version grant, slow localhost) |
| 2026-10-16 | same, after fixes | **60 passed in 5.8 s** (0 skipped) |
| 2026-10-16 | `npm run e2e` (Playwright, Chromium, real API + DB) | **3 passed**: register→case→path→sign-out/in persists; cross-user 404; wrong password error |
| 2026-10-16 | `docker compose --profile full build && up`; curl readyz, register+create case via web:3000 | images built; api healthy (uid 10001); readyz ok; 201/201 |
| 2026-10-16 | M2 backend: `NEXSCOUT_REQUIRE_DB=1 uv run pytest` | **121 passed** (incl. IDOR sweep, RLS structure, upload/parse/extract, export/delete) |
| — | GitHub Actions CI | **not run** (no remote configured) |

---

## Milestones
Architecture: `docs/ARCHITECTURE.md`. Decisions: `docs/ARCHITECTURE_DECISIONS/`.

| # | Milestone | Status | Acceptance criteria |
|---|---|---|---|
| M0 | Discovery and architecture | ✅ | Architecture, conventions, data ownership, security boundaries and the first vertical slice are documented |
| M1 | Runnable foundation | ✅ | Dev can start the app from the docs, log in, create an isolated case, and run the tests. User B gets 404 on A's case. RLS blocks raw cross-tenant SQL |
| M2 | Profile and ingestion | 🟨 | Upload PDF/DOCX/MD → review extracted facts → edit profile → data persists across restart |
| M3 | Mind map and opportunities | ⬜ | Evidence-linked mind map (graph and table). Normalized, deduplicated opportunities from fixture sources with explained matches |
| M4 | Durable agent runtime | ⬜ | Workflow survives worker or app restart, resumes from its checkpoint, and respects pause, cancel and authorization. No duplicate side effects |
| M5 | PhD research workflow | ⬜ | Fixture workflow discovers opportunities, stores evidence, generates editable documents, and flags missing info without inventing facts |
| M6 | Job discovery and matching | ⬜ | Repeated searches don't duplicate. Matches and experience gaps are explained |
| M7 | Browser automation and approvals | ⬜ | Fixture application flow completes, stops at approval gates, and distinguishes confirmed from uncertain submission |
| M8 | Tracking and dashboard | ⬜ | Track applications, inspect agent work, pause workflows, review documents and resolve blocked tasks in the UI |
| M9 | Desktop and providers | ⬜ | Desktop builds install and run. Each advertised provider or integration has a verified capability profile |
| M10 | Production hardening | ⬜ | Security, isolation, concurrency and recovery tests pass. Backup and restore and migration upgrades are tested. Deployment is reproducible |

## Deferred / open items
_(Each item: dependency, concrete plan, acceptance test.)_
