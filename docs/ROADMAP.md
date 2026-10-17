# NexScout Roadmap and Checkpoint

Status legend: ⬜ not started · 🟨 in progress · ✅ done (tests executed and passed) · ⛔ blocked

## Checkpoint (update at the end of every session)
- **Date:** 2026-10-17
- **Current milestone:** M7 Browser automation and approvals (⬜ next). M0–M6 ✅.
- **Done so far:**
  - M0: all §2.2 docs + ADR-0001…0009.
  - M1: auth (argon2id, hashed opaque sessions, CSRF, DB rate limiting), cases with optimistic
    locking, audit log, forced RLS + least-privilege grants, health/readiness, CLI, compose,
    Dockerfiles, CI workflow, Next.js shell, E2E.
  - M2: documents, conservative heuristic CV extractor with verbatim evidence spans, review queue
    (accept/edit/merge/reject/private), section editor, preferences, social links, affiliations,
    snapshots, export and deletion.
  - M3: evidence-linked mind map (graph + list, overrides, snapshots), shared opportunity catalog,
    guard-first dedup, explainable matching, labelled demo sources, incremental resumable sync,
    PhD and Jobs pages.
  - M4 runtime: Postgres queue (SKIP LOCKED, leases, heartbeats, reaper), worker process,
    LangGraph Postgres checkpoints, pause (drain at step boundary) / cancel / retry / rerun /
    skip, approvals via interrupt (decision read from DB), side-effect ledger with `uncertain`
    outcomes, budgets, SSE events.
  - M4 providers: `infrastructure/llm/` (mock, OpenAI-compatible, Anthropic, Gemini),
    `structured()` with one repair, AES-GCM secrets bound to owner+purpose, SSRF checks,
    usage records, BYOK provider API (keys write-only). ContextBuilder with budgets and
    id-preserving compaction. `profile_summary` workflow (cited sentences, verifier, consent
    approval when data leaves the device, pending `inferred` entry, mock output labelled).
  - M4 moved work onto the worker: document reading and opportunity search are now runs
    (`POST …/documents` → 201 `{document, run_id}`, `POST …/opportunities/sync` → 202 `{run_id}`).
  - M4 web: Agent Activity (live SSE, run list, run detail with steps/notes/event log,
    approvals approve/reject with note, pause/resume/cancel/retry, per-step rerun/skip, start a
    workflow), Settings → AI models (presets for Ollama/LM Studio/OpenAI/Anthropic/Gemini/mock,
    write-only key, local vs off-device badge, check connection, default), Profile → "Draft a
    summary with AI", Documents/PhD/Jobs show background progress.
  - M4 fixes found while verifying:
    - SSE was gzip-buffered by the Next.js proxy, so no live events arrived. The fix is
      `Cache-Control: no-transform`, A/B-verified (before: gzip, no event within 5 s;
      after: event in 0.13 s), with a regression assert in `test_event_stream_replays_backlog`.
    - The dev DB lacked the LangGraph checkpoint tables because it wasn't re-migrated. The worker
      now refuses to start with a clear message.
    - In compose, the dev master key sat outside the volume and wasn't shared between api and
      worker. Both now mount `appdata:/data`, and a worker service was added.
    - Production now refuses to start without `NEXSCOUT_MASTER_KEY`.
    - Mock-drafted text is labelled "Mock text, not written by AI".
  - M5 PhD workflow (ADR-0009):
    - Migration `0005` adds research_sources, research_findings, generated_documents and
      generated_document_versions (owned, RLS).
    - `SafeFetcher` (IP pinned at connect, redirects re-checked, robots.txt, caps).
    - `rules_v1` research extraction with verbatim quotes, conflicts and freshness, plus bundled,
      labelled demo pages for the demo listings.
    - `phd_research`, `draft_document` and `render_document` workflows. The drafting contract is
      typed cited sentences with a deterministic verifier and placeholders. The academic CV is
      assembled from accepted entries (no AI). There is a consent approval when data leaves the
      device.
    - Markdown → PDF (Chromium in a thread) and DOCX, validated.
    - API: research, document types, generated documents (draft, list, get, version, edit = new
      version with optimistic concurrency, render, download, delete). The IDOR sweep covers all 9
      new routes.
    - Web: "Research and prepare" page (findings grouped with source quotes, conflicts,
      freshness, supervisors; draft buttons) and a document page (mock and "no AI" badges, "Not
      ready to send" placeholder warning, fact-check report with removed claims and reasons,
      files with checks, editor, versions, delete). Documents → Application materials, with
      "Create academic CV".
    - The backend image now includes headless Chromium.
  - M6 jobs:
    - Referral suggestions (`domain/referrals.py`, `GET …/opportunities/{id}/referrals`) are
      matched to the employer by normalized organization name. Only people with
      `may_use_for_referral` are suggested; the others are reported as a count only.
    - Job documents:
      - resume: assembled, no AI, job ordering;
      - cover letter: drafted and verified; relationships appear only if
        `may_use_in_applications`;
      - referral request: needs a permitted named contact, otherwise 403; never sent.
    - Demo pages for two demo jobs.
    - A shared "Research and prepare" page for PhD and jobs, with a referral picker.
    - The IDOR sweep covers the referrals route.
- **Environment:** Windows 11, Docker Desktop 29.8.2 (CLI at
  `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`, on the user PATH), Python 3.13.15 via uv,
  Node 26.10, Postgres 17 in compose.
- **Blockers:** none. Live provider verification needs a user-supplied key or a local Ollama/LM
  Studio (see KNOWN_LIMITATIONS provider matrix: none live-verified).
- **Observed, not failing:** one `Failed to proxy … ECONNRESET` line from `next dev` during the
  M2 E2E (a request aborted by page navigation; the test passed).
- **Next exact steps (M7 Browser automation):**
  1. Fixture application site, served by the backend in dev/test only at `/fixture-site/*`
     (labelled demo): multi-step form, file upload, a CAPTCHA page, and a confirmation page with
     a reference number.
  2. `applications` + `application_events` (migration 0006, state machine from
     `domain/state_machines.py`).
  3. `browser_apply` workflow (Playwright sync in a thread): open the form, map fields from
     accepted facts and generated documents, fill (no submit), screenshot plus field map →
     approval "Submit to X" → submit with an idempotency ledger → detect confirmation →
     `submitted`, or `submission_uncertain` → the user confirms. Stop with `needs_user_action`
     on a CAPTCHA or login (never bypass). Manual takeover = headed mode instructions.
  4. API + UI (Applications page: list, detail, approve submit, confirm uncertain), tests, E2E.

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
| 2026-10-16 | M4 core: `NEXSCOUT_REQUIRE_DB=1 uv run pytest` | **172 passed** incl. runtime system tests and real worker-process kill/recover (side effect exactly once) |
| 2026-10-17 | M4: `uv run ruff check . && ruff format --check . && mypy` | passed (86 source files strict) |
| 2026-10-17 | M4: `uv run pytest` (Postgres up) | **200 passed** in 89 s (runtime system tests, real worker kill/recover, profile_summary incl. consent + mock label, providers, SSE header) |
| 2026-10-17 | M4: web `tsc --noEmit`, `eslint .`, `vitest run` (12/12), `next build` | all passed |
| 2026-10-17 | M4: `npx playwright test` (api :8100 + **worker** + web :3200) | **8/8 passed**, incl. new M4 journeys: system check run → pause → paused → resume → approval with note → done, with the run list updated by live events; mock model added → check connection "Working" → write-only key field → AI summary draft cited and labelled mock |
| 2026-10-17 | M4: `docker compose --profile full up -d --build` + probe through web :3000 | api healthy; containerized worker read an uploaded CV in ~2 s (16 entries); SSE live through the production web server (no gzip); API key not echoed; one shared `/data/master.key`; `compose stop worker` → `worker_stopped` in 1.6 s |
| 2026-10-17 | M5: ruff, ruff format, mypy strict (98 files) | passed |
| 2026-10-17 | M5: `uv run pytest` | **234 passed** in 97 s (new: fetcher SSRF suite 9, research rules 6, drafting verifier 8, render 4 incl. real Chromium PDF, 7 system tests for research/SOP/edit+render/CV/inquiry email/consent/validation, IDOR sweep +9 routes) |
| 2026-10-17 | M5: web tsc, eslint, vitest 12/12, `next build` | passed |
| 2026-10-17 | M5: `npx playwright test` | **9/9 passed**, incl. new journey: find demo PhD → research (conflicting deadlines flagged, supervisor quote) → draft SOP (mock labelled, removed claim shown, placeholders) → edit → v2 → create files → PDF download |
| 2026-10-17 | M5: `docker compose --profile full up -d --build` + probe via web :3000 | containerized worker: research 4 sources / 18 findings / 4 conflicts; SOP drafted, `files_ok`, PDF 200 `%PDF-` (image with Chromium: 2.08 GB) |
| 2026-10-17 | M6: ruff, format, mypy (100 files); `uv run pytest` | **240 passed** (new: referral rules, job research/referrals/cover letter/resume system tests, IDOR referrals) |
| 2026-10-17 | M6: web tsc, eslint, vitest 12/12, `next build`; `npx playwright test` | passed; **10/10 E2E** incl. new job journey (strict-mode listing → research → referral picker shows only the permitted person, hint for the other → referral request + resume) |
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
| M4 | Durable agent runtime | ✅ | Workflow survives worker or app restart, resumes from its checkpoint, and respects pause, cancel and authorization. No duplicate side effects |
| M5 | PhD research workflow | ✅ | Fixture workflow discovers opportunities, stores evidence, generates editable documents, and flags missing info without inventing facts |
| M6 | Job discovery and matching | ✅ | Repeated searches don't duplicate. Matches and experience gaps are explained |
| M7 | Browser automation and approvals | ⬜ | Fixture application flow completes, stops at approval gates, and distinguishes confirmed from uncertain submission |
| M8 | Tracking and dashboard | ⬜ | Track applications, inspect agent work, pause workflows, review documents and resolve blocked tasks in the UI |
| M9 | Desktop and providers | ⬜ | Desktop builds install and run. Each advertised provider or integration has a verified capability profile |
| M10 | Production hardening | ⬜ | Security, isolation, concurrency and recovery tests pass. Backup and restore and migration upgrades are tested. Deployment is reproducible |

## Deferred / open items
_(Each item: dependency, concrete plan, acceptance test.)_
