# NexScout Roadmap and Checkpoint

Status legend: ⬜ not started · 🟨 in progress · ✅ done (tests executed and passed) · ⛔ blocked

## Checkpoint (update at the end of every session)
- **Date:** 2026-10-16
- **Current milestone:** M1 Runnable foundation (🟨). M0 docs done.
- **Done so far:**
  - M0: all §2.2 docs + ADR-0001…0007 (versions checked against PyPI/npm on 2026-10-16).
  - M1 backend (`backend/src/nexscout`): config, structlog with redaction, domain state machines,
    case rules, argon2id auth with hashed opaque sessions, CSRF double-submit, DB-backed login
    rate limiting, case CRUD with optimistic locking, audit log, RLS helpers, Alembic `0001`
    (tables, RLS on candidate_cases, least-privilege grants), `/healthz`, `/readyz` (bounded 3 s),
    `nexscout serve|migrate` CLI (Windows Selector loop for psycopg), docker-compose plus role init SQL.
  - M1 web (`apps/web`, Next.js 16.4.2): `/api/*` rewrite to FastAPI, proxy redirect without a
    session cookie, login/register, case list/create, case workspace with §16 nav, career-path
    selection (R-PATH-1, optimistic locking), honest "not available yet" pages for later milestones,
    typed client generated from OpenAPI, Vitest tests (open-redirect guard, CSRF echo, problem+json).
  - CI workflow, Dockerfiles, DEVELOPMENT.md, README. (Unverified: see KNOWN_LIMITATIONS.)
  - Bugs found by running the code and fixed: `/readyz` hung without a DB; `.test` emails rejected
    (tests moved to example.com); untrimmed emails rejected.
- **Environment:** Windows 11. Python 3.14.8 on the host (we pin **3.13.15** via uv), uv 0.12.10, Node 26.10, npm 12.2, git 2.51.
- **Blockers:** ⛔ **Docker Desktop not installed** (re-checked 2026-10-16). 23 DB-backed tests and
  every flow that needs a login can't run until Postgres is available. M2+ persistence depends on this.
- **Next exact steps:**
  1. Once Docker is available: `cp .env.example .env && docker compose up -d postgres`
     → `cd backend && uv run nexscout migrate` → `NEXSCOUT_REQUIRE_DB=1 uv run pytest`
     (expect 60 tests: 37 unit + 23 DB, 0 skipped) → fix failures.
  2. Manual browser check: `uv run nexscout serve` + `npm run dev` → register → create case →
     choose path → sign out/in → second user can't open the first user's case URL. Then mark M1 ✅.
  3. M2 (needs DB to verify): documents table + ObjectStore + upload validation, profile facts and
     evidence, ingestion (pypdf/python-docx/markdown) with a deterministic section splitter and a
     **mock** extractor, review UI, Playwright e2e "upload CV → review → persists after restart".

## Test evidence log
| Date | Command | Result |
|---|---|---|
| 2026-10-16 | `uv run ruff check . && uv run ruff format --check . && uv run mypy` | passed (mypy strict, 33 files) |
| 2026-10-16 | `uv run pytest -q` | **30 passed, 23 skipped** (all skips: Postgres unreachable) |
| 2026-10-16 | `nexscout serve` + curl `/healthz`, `/readyz`, `/api/v1/cases` | 200 + security headers; 503 `degraded` in 3.0 s (no DB); 401 problem+json |
| 2026-10-16 | `uv run pytest -q` (after fixes) | **37 passed, 23 skipped** (all skips: Postgres unreachable) |
| 2026-10-16 | web: `npm run typecheck`, `eslint .`, `vitest run`, `next build` | passed; 12/12 vitest; build OK (PPR on case routes) |
| 2026-10-16 | `next start` + API: GET `/login`, `/cases/abc` (no cookie), `/api/v1/cases` via rewrite | 200; 307 → `/login?next=%2Fcases%2Fabc`; 401 problem+json through rewrite |
| — | Docker images, CI workflow, DB tests, browser login flow | **not run** (no Docker / no remote) |

---

## Milestones
Full plan: the approved plan, mirrored in `docs/ARCHITECTURE.md` once it is written.

| # | Milestone | Status | Acceptance criteria |
|---|---|---|---|
| M0 | Discovery and architecture | ✅ | Architecture, conventions, data ownership, security boundaries and the first vertical slice are documented |
| M1 | Runnable foundation | 🟨 ⛔ (DB) | Dev can start the app from the docs, log in, create an isolated case, and run the tests. User B gets 404 on A's case. RLS blocks raw cross-tenant SQL |
| M2 | Profile and ingestion | ⬜ | Upload PDF/DOCX/MD → review extracted facts → edit profile → data persists across restart |
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
