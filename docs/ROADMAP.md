# NexScout Roadmap and Checkpoint

Status legend: ⬜ not started · 🟨 in progress · ✅ done (tests executed and passed) · ⛔ blocked

## Checkpoint (update at the end of every session)
- **Date:** 2026-10-16
- **Current milestone:** M3 Mind map and opportunity domain (⬜ next). M0 ✅, M1 ✅, M2 ✅.
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
- **Environment:** Windows 11, Docker Desktop 29.8.2 (CLI at
  `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`, on the user PATH), Python 3.13.15 via uv,
  Node 26.10, Postgres 17 in compose.
- **Blockers:** none.
- **Interim decisions still in force:** ingestion runs in the upload request (isolated subprocess,
  20 s cap) until the M4 worker. The extractor is the deterministic `heuristic_v1` (not AI). LLM
  extraction arrives with the provider layer (M4).
- **Next exact steps (M3):**
  1. Domain: mind-map graph builder over *accepted* facts (nodes keyed by fact id, typed
     edges for chronology, shared skills and organizations; node status from fact status);
     snapshot diff (`domain/snapshots.py`).
  2. Migration `0003`: `mindmap_overrides`, `organizations`, `opportunities`,
     `opportunity_sources`, `source_configs`, `sync_checkpoints`, `dedup_decisions`,
     `opportunity_matches`. Catalog vs owned split (see DATA_MODEL).
  3. Domain: opportunity normalization, dedup engine (URL canonicalization, requisition id,
     employer resolution, title normalization, location, similarity threshold, guard against
     merging distinct requisitions), explainable matching (factors + gaps, strict/flexible).
  4. `SourceAdapter` protocol + deterministic fixture adapters (jobs + academic). Sync with
     checkpoints so repeated syncs don't duplicate.
  5. Web: Mind Map (React Flow + ELK, accessible table view, overrides kept on regenerate,
     snapshot compare). Opportunities list (fixture sources, labelled as such) with match
     explanation.
  6. Tests: dedup property tests, matching tests, IDOR sweep additions, E2E.

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
| — | GitHub Actions CI | **not run** (no remote configured) |

---

## Milestones
Architecture: `docs/ARCHITECTURE.md`. Decisions: `docs/ARCHITECTURE_DECISIONS/`.

| # | Milestone | Status | Acceptance criteria |
|---|---|---|---|
| M0 | Discovery and architecture | ✅ | Architecture, conventions, data ownership, security boundaries and the first vertical slice are documented |
| M1 | Runnable foundation | ✅ | Dev can start the app from the docs, log in, create an isolated case, and run the tests. User B gets 404 on A's case. RLS blocks raw cross-tenant SQL |
| M2 | Profile and ingestion | ✅ | Upload PDF/DOCX/MD → review extracted facts → edit profile → data persists across restart |
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
