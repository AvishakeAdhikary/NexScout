# NexScout Roadmap and Checkpoint

Status legend: ⬜ not started · 🟨 in progress · ✅ done (tests executed and passed) · ⛔ blocked

## Checkpoint (update at the end of every session)
- **Date:** 2026-10-17
- **Current milestone:** M12 Autopilot (🟨 in progress), then M13 Releases + easy install. M0–M11 ✅.
- **Done so far:**
  - M0: all §2.2 docs + ADR-0001…0012.
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
  - M7 browser automation (ADR-0010):
    - Migration `0006` adds applications and application_events (seq-ordered timeline, RLS).
    - `domain/forms.py` plans a form fill from user-provided values only; declarations are
      deferred; CAPTCHA, login and confirmation detection.
    - `infrastructure/browser.py`: Playwright in a thread, per-request SSRF guard, fill, and a
      submit that is refused if the plan changed since approval.
    - `browser_apply` workflow: fill → approval with screenshot → submit at most once.
      Outcomes are observed confirmation, uncertain (user resolves) or needs_user_action
      (CAPTCHA, login, missing answers).
    - Labelled demo application site at `/fixture-site` (off in production).
    - API: create, list, get, update (answers, phone, docs, URL), manual status changes through
      the state machine, resolve uncertain, start browser, screenshots. The IDOR sweep covers
      the 8 new routes.
    - Web:
      - Applications list and detail (blocker alert, inline approval, answers form, document
        choice, manual status actions, uncertain resolution, timeline with screenshots);
      - "Apply" section on position pages;
      - approval card shared with Agent Activity.
  - M8 tracking:
    - Migration `0007` adds reminders, notifications and chat_messages (RLS). There's a
      column-level grant so users can see worker liveness without hostnames.
    - The worker's maintenance sweep (every `NEXSCOUT_MAINTENANCE_INTERVAL_S`) is idempotent.
      It creates deadline reminders (7 days and 1 day before), notifications for due reminders,
      pending approvals and needs-you or uncertain applications. In-app only; nothing is emailed.
    - Tracker: status and text filters, sort by deadline, bulk status changes validated per item,
      and a CSV export protected against formula injection.
    - Case dashboard: needs-you list, counts, the next 30 days, recent runs.
    - Diagnostics (Settings): worker alive and busy, own queue, recent failures, provider checks.
    - Assistant (chat): a deterministic fixed-menu intent router that calls the same use cases as
      the screens. It refuses to submit or send.
    - Notification bell; reminders on the application page.
  - UI theme (requested 2026-10-17):
    - Dark by default via next-themes, with a dark / light / system toggle in the top bar.
    - "Night sky" indigo-violet palette for both themes.
    - Open-source fonts self-hosted by next/font: Plus Jakarta Sans (text), Space Grotesk
      (headings), JetBrains Mono (code and numbers). This also fixes an old bug where
      `--font-sans` referred to itself, so the app had been rendering in Times New Roman.
    - New SVG telescope logo and favicon (`components/logo.tsx`, `app/icon.svg`); the star
      twinkles.
    - Motion: page entrance (route template), card lift, popover and badge transitions. All of
      it turns off with `prefers-reduced-motion`.
    - Sidebar icons; the mind map follows the theme.
  - M9 (ADR-0011):
    - Read-only MCP server (`nexscout mcp`, official SDK 2.3, 7 read-only tools, scoped by
      personal access token; private entries never shared).
    - Personal access tokens (migration 0008; hashed, shown once, expiring, revocable, audited)
      with an Account UI.
    - Electron 44 desktop shell (`apps/desktop`):
      - secure window and navigation policy;
      - first-run setup;
      - remote mode, and local mode that starts API, worker and web with readiness checks and
        log files;
      - master key in OS secure storage;
      - an unsigned NSIS installer built.
    - MCP client and A2A remain deferred (ADR-0007/0011).
    - Desktop CI job added.
  - M10 hardening:
    - Upload fuzzing, plus a DOCX zip-bomb guard that rejects before inflating.
    - Prompt-injection fixtures through CVs, pages, model output and chat.
    - A migration test from base to head with data, and downgrade back.
    - Load and concurrency test (12 or 40 users) with correctness assertions.
    - Backup and restore scripts with a verified restore.
    - Retention enforced by the maintenance sweep (migration 0009, delete-only grants).
    - pip-audit, npm audit and a secret scan; a CI `security` job.
    - README, OPERATIONS (capacity, distribution), SECURITY, TESTING and KNOWN_LIMITATIONS final
      pass.
  - Regional document formats (ADR-0012, R-DOC-1/2):
    - The format follows the position's country, with an international fallback and a user
      override.
    - Paper size follows the format: US Letter or A4.
    - Lebenslauf, Europass-style and referee conventions are supported.
    - Posting page and word limits from research block uploads; convention limits only warn.
    - UI: a format picker with the reason, and a compliance checklist on documents.
  - Repository (2026-10-17):
    - The old v1 `main` is tagged `v1-legacy` and merged with strategy `ours`, so this tree
      replaces it without rewriting history.
    - AGPL-3.0 LICENSE carried over.
    - CI gained Chromium for backend tests and an E2E job.
    - Pushed after the user approved; GitHub Actions run 39009961870 passed all six jobs.
  - M11 notification channels (ADR-0013, migration 0010):
    - Channels: Telegram Bot API (long poll), Discord bot (REST and Gateway), WhatsApp Cloud API
      (signed webhook), Slack webhook, SMTP email, HMAC-signed webhook. Official APIs only.
    - Pairing by one-time code. Only the paired identity can act.
    - Transactional outbox in the worker: retries with backoff and jitter, dead letter, circuit
      breaker, quiet hours, event filters, per-channel ordering. Webhook URLs are re-checked
      for SSRF at send time.
    - Approve or reject buttons go through `runs.decide` (single-use, identity-bound, audited).
    - Answers by reply: a form question becomes a `question` notification, and the reply is
      stored as the user's answer.
    - Approvals notify in real time from `require_approval`. A CAPTCHA or sign-in sends a
      "needs you" notification.
    - API: `/channels` (CRUD, pair, test, deliveries), `/approvals/{id}`, and the WhatsApp
      webhook (GET verify, POST inbox).
    - Web: Settings → "Notifications on your phone" with provider setup steps; `/approve/[id]`.
    - The IDOR sweep covers +7 routes, and a variable-shadowing bug in it was fixed (the
      approval decision route was being swept with an application id).
- **Environment:** Windows 11, Docker Desktop 29.8.2 (CLI at
  `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`, on the user PATH), Python 3.13.15 via uv,
  Node 26.10, Postgres 17 in compose.
- **Blockers:** none. Live provider verification needs a user-supplied key or a local Ollama/LM
  Studio (see KNOWN_LIMITATIONS provider matrix: none live-verified).
- **Observed, not failing:** one `Failed to proxy … ECONNRESET` line from `next dev` during the
  M2 E2E (a request aborted by page navigation; the test passed).
- **Plan agreed with the user (2026-10-17): human-in-the-loop autopilot**
  - **M11 Notification channels** (official APIs only):
    1. Data: `notification_channels` (owned; kind, encrypted credentials, paired identity, quiet hours,
       enabled) and `notification_deliveries` (outbox: status pending/sent/failed/dead, attempts,
       next_attempt_at, provider_message_id). Migration 0010.
    2. Adapters in `infrastructure/channels/`: generic webhook (HMAC-SHA256 signed), Slack incoming
       webhook, email (SMTP), Telegram Bot API (send + inline buttons; inbound via long polling
       `getUpdates`: pairing `/start CODE`, button presses, replies), Discord bot (REST send with
       buttons; inbound via the official Gateway: INTERACTION_CREATE), WhatsApp Cloud API (send +
       interactive buttons; inbound webhook with `X-Hub-Signature-256` verification).
    3. Pairing: a one-time code links a chat identity to the user; only that identity can act.
    4. Outbox delivery loop in the worker (retries with backoff + jitter, dead letter, per-channel
       circuit breaker), quiet hours, event filters.
    5. Approvals and answers from chat: approve/reject buttons, answer-by-reply (Telegram, WhatsApp);
       every message also links to the app. Idempotent per provider event id.
    6. UI: Settings → Notifications (add, pair, test, pause), delivery log.
    7. Tests with mock transports for every provider; live verification is opt-in (`-m live`).
  - **M12 Autopilot** (standing approvals, never guessing):
    1. `autopilot_policies` (owned, versioned): schedule, steps (discover, research, draft, fill,
       submit), thresholds (min fit, daily/organization caps, countries, kinds, excluded
       organizations), explicit consents (auto-submit, declarations) with timestamp and text.
    2. `domain/policy.py`: deterministic allow/deny with reasons; `domain/site_policy.py`:
       robots.txt, published automation bans (manual-only), per-site throttle.
    3. Case **answer bank**: question → answer, reused across applications; unknown questions are
       asked once through notifications.
    4. Scheduler in the worker maintenance loop; `autopilot_cycle` LangGraph workflow: discover →
       shortlist (policy) → research → documents (regional format + compliance) → application →
       fill → submit within policy, else approval via notification → confirmation.
    5. CAPTCHA/login: notify and **assisted mode** (desktop/local: visible browser window, NexScout
       fills, the human solves the CAPTCHA and submits, NexScout detects the confirmation).
    6. Kill switch, daily digest, autopilot page in the UI.
  - **M13 Releases and easy install:**
    1. `release.yml`: on green CI on main, bump minor from the latest `v2.*` tag, tag, release notes,
       GHCR images (api/worker, web), Windows installer, "easy" bundle.
    2. Desktop **Easy mode**: installer → open → NexScout starts its own Docker stack (bundled
       compose, generated secrets, master key in OS storage) → setup wizard in the browser window.
    3. `Start NexScout` scripts for Windows/macOS/Linux (Docker), in-app onboarding wizard.
    4. `docs/USER_GUIDE.md` for non-technical users; README rewritten user-first.
- **Still open (need keys or other platforms):** live provider and channel verification with real
  credentials; real job/academic sources and real application portals; code signing; macOS/Linux
  installers.

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
| 2026-10-17 | M7: ruff, format, mypy (106 files); `uv run pytest` | **251 passed** (new: form planning 5, browser system tests 6 against a real HTTP demo site with real headless Chromium: missing answer → needs you; nothing sent before approval; declarations only after approval; exactly once; reject; CAPTCHA hand-over + manual submit; uncertain → user resolves; crash mid-submit never resubmits; SSRF-checked URLs; IDOR +8 routes) |
| 2026-10-17 | M7: web tsc, eslint, vitest, `next build`; `npx playwright test` | passed; **11/11 E2E** incl. new journey (resume → placeholder filled → files → start application → needs you → answer → filled → inline approval → confirmed with reference FX-… → screenshot in timeline) |
| 2026-10-17 | M8: ruff, format, mypy (110 files); `uv run pytest` | **274 passed** (new: intent routing and CSV safety 19, tracking system tests 4: idempotent sweep with deadline reminders and notifications, dashboard + bulk + export, assistant routes and never submits, safe diagnostics; IDOR +10 routes) |
| 2026-10-17 | M8 + theme: web tsc, eslint, vitest 12/12, `next build`; `npx playwright test` | passed; **12/12 E2E** incl. the new tracking journey (assistant refuses submit and starts a search → application → reminder → worker notification via the bell → dashboard "Coming up" → filter, bulk cancel, CSV export). Re-run after the dark theme, fonts and logo: 12/12 |
| 2026-10-17 | M9: ruff, format, mypy (112 files); `uv run pytest` | **276 passed** (new: MCP tools over a real in-memory MCP client session with private entries excluded, cross-user access refused and read-only annotations; token revoke, expiry and garbage refused; IDOR +1) |
| 2026-10-17 | M9: real stdio MCP: `nexscout mcp` subprocess via the SDK stdio client | 7 tools listed, `list_my_cases` OK, invalid token refused (exit 2) |
| 2026-10-17 | M9: desktop `npm test` (tsc + vitest 3 policy tests) | passed |
| 2026-10-17 | M9: Electron `--smoke` | setup window: no require, process or module in the page; safeStorage available. Remote mode against dev web: sign-in page loaded, desktop bridge only. **Local mode:** API ready, `worker_started` logged plus a fresh heartbeat, web ready, page loaded, all children stopped on quit (ports closed). The first attempt wrongly passed before the worker started; fixed with readiness checks and log files |
| 2026-10-17 | M9: `electron-builder --dir` and NSIS | `release/win-unpacked/NexScout.exe` smoke OK; `NexScout Setup 0.1.0.exe` (112 MB) built, **NotSigned** |
| 2026-10-17 | M9: web checks + `npx playwright test` | passed; 12/12 E2E |
| 2026-10-17 | M10: upload fuzz + prompt injection | 37 upload/ingestion tests passed (zip bomb 120 MB → rejected before inflating; 300 random blobs × 3 prefixes rejected cleanly; executables, images and non-docx zips → 422); 5 injection tests passed |
| 2026-10-17 | M10: migration upgrade base → 0009 with data + downgrade | passed |
| 2026-10-17 | M10: load test | 12 users: 36/36 runs, 4.8 runs/s, +41 MB; 40 users: 120/120 runs, 4.5 runs/s, +57 MB; 0 duplicates, 0 cross-tenant rows |
| 2026-10-17 | M10: `scripts/backup.py` + `scripts/restore.py` (dev DB) | backup 45 tables / 9,965 rows / 149 files; restore into a scratch DB: **all row counts and 149/149 file hashes matched**; overwriting live refused |
| 2026-10-17 | M10: `pip-audit` | no known vulnerabilities |
| 2026-10-17 | M10: `npm audit --omit=dev` (web) | 0 after moving the shadcn CLI to devDependencies. Full audit: 7 high via `braces` (dev tooling only, no fix available). Desktop: 8 moderate via electron-builder (packaging only) |
| 2026-10-17 | M10: `scripts/secret_scan.py --history` | 317 tracked files + full history: 0 findings (the scanner was checked against planted keys) |
| 2026-10-17 | M10: retention purge test | old events, audit rows and login attempts purged; recent data and sessions intact |
| 2026-10-17 | Regional formats: `uv run pytest` | **326 passed** (new: 20 format/compliance unit tests; 2 system tests: Germany → Lebenslauf on A4 (595×842 pt), Netherlands → Europass, unknown → international, US override → Letter (612×792 pt); a posting's "max. 2 pages" blocks an over-long statement from upload) |
| 2026-10-17 | Regional formats: web tsc, eslint, vitest, `next build`; `npx playwright test` | passed; **12/12 E2E** (M5 journey now asserts the German format and the posting's 2-page check) |
| 2026-10-17 | GitHub Actions CI (after push) | run 39009961870: backend, web, e2e, desktop, security all green |
| 2026-10-17 | M11: ruff, format, mypy (123 files); `uv run pytest` | **338 passed** (new: 4 channel system tests — Telegram question → reply answer → approval buttons → foreign user refused → paired approve → submitted exactly once → replay ignored; Discord code pairing + real WebSocket Gateway IDENTIFY(intents 4096) + button from stranger refused + paired approve; WhatsApp verify handshake, forged signature rejected, signed PAIR, Reject button, duplicate webhook ignored; webhook signature, 503 retry with backoff, 401 dead letter ×5 → circuit open, resume, quiet hours defer, isolation, secret deleted with channel; 8 unit tests; IDOR +7) |
| 2026-10-17 | M11: web tsc, eslint, vitest 12/12; `npx playwright test` | passed; **13/13 E2E** incl. new journey (webhook channel saved → signing secret shown once → test fails honestly against a closed port → pause → approval decided on `/approve/[id]`) |

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
| M7 | Browser automation and approvals | ✅ | Fixture application flow completes, stops at approval gates, and distinguishes confirmed from uncertain submission |
| M8 | Tracking and dashboard | ✅ | Track applications, inspect agent work, pause workflows, review documents and resolve blocked tasks in the UI |
| M9 | Desktop and providers | ✅ with caveats: the unpacked Windows app runs (smoke-tested) and the installer was built, but an install was **not** run. Providers are not live-verified (no keys) | Desktop builds install and run. Each advertised provider or integration has a verified capability profile |
| M10 | Production hardening | ✅ | Security, isolation, concurrency and recovery tests pass. Backup and restore and migration upgrades are tested. Deployment is reproducible |
| M11 | Notification channels | ✅ (providers faked at HTTP level; not live-verified) | Paired channels receive notifications through a durable outbox; approvals and answers from chat act only for the paired identity, once |
| M12 | Autopilot | 🟨 | Scheduled discover → documents → fill → submit within a consented policy; unknowns asked, never guessed; manual-only sites respected; kill switch |
| M13 | Releases and easy install | ⬜ | Every green main push gets a minor-bump tag and release; non-technical users can install and start NexScout with a double-click |

## Deferred / open items
_(Each item: dependency, concrete plan, acceptance test.)_
