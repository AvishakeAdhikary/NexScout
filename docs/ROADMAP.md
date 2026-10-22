# NexScout Roadmap and Checkpoint

Status legend: ⬜ not started · 🟨 in progress · ✅ done (tests executed and passed) · ⛔ blocked

## Checkpoint (update at the end of every session)
- **Date:** 2026-10-23
- **Current milestone:** M18 ✅ (v2.9.0): portable profiles and CV reader v2. Next: M19 desktop shell, M20 scalable
  lists, M21 agentic assistant (plan below, "Plan M18–M21"). Before that: M14–M17 ✅ (v2.2.0 → v2.7.0, 2026-10-19). Remaining steps belong to the user (see
  Next exact steps). M16: provider editing, self-update, update notice (v2.3.0 is the first version that can update
  itself). M14 + M15 released as v2.2.0. M0–M13 ✅.
- **Why (user feedback on v2.1.0, 2026-10-18):** the shipped app had only demo sources and the demo application
  site (Easy/desktop ran with NEXSCOUT_ENV unset = development); no real or custom job sources; countries were free
  text (autopilot asked for codes, data had names, so its filter matched nothing); AI providers could not be
  edited; no in-app update; users saw raw Python errors ("'X' object has no attribute 'y'") because worker
  failures are stored as `Type: message` and shown verbatim; desktop local mode's /api rewrite was fixed at build
  time. The user wants career-ops' sources (github.com/career-ops-hq/career-ops, MIT, ~110 providers) and more,
  incl. custom sources and unknown EU boards (Duunitori, Work in Finland, Jobs in Finland), ISO country
  include/exclude lists, and a real-world run with their CV (outside the repo, `NEXSCOUT_REAL_RUN_DIR`) for
  Europe AI/ML/CV jobs + PhDs: visa sponsorship needed, funding preferred, total upfront budget INR 1.5 lakh.
- **User decisions (2026-10-18):** live run goes to submission, but the user approves each submission in the
  app (never approved on their behalf); go through the actual career-ops boards online (port from their real
  provider code, pinned SHA); AI = NVIDIA NIM (OpenAI-compatible, integrate.api.nvidia.com/v1) with the user's
  key entered at runtime only (never in repo/docs/logs; user advised to rotate it); updates = desktop
  electron-updater + Docker image pull with cleanup of old installers/images.
- **Plan M14–M17** (full plan text: see the session plan; summary):
  - M14: `demo_data_enabled` (default off; tests set NEXSCOUT_DEMO_DATA=1) gates fixture sources + demo site;
    Easy/desktop/Docker run NEXSCOUT_ENV=production; cookie_secure auto (https only); runtime /api proxy in
    `apps/web/src/proxy.ts`; `user_message(exc)` for all user-visible run errors; guard fixes
    (document-format, setup.js, profile_summary, browser_apply url); E2E fixture failing on console/page errors
    and /api 5xx; crawl spec over every route; production-build E2E in CI.
  - M15: port career-ops providers (ATS: greenhouse, lever, ashby, workable, smartrecruiters, recruitee, personio,
    teamtailor, breezy, pinpoint, rippling, workday, jobvite, bamboohr; boards: arbeitnow, thehub, landing.jobs,
    justjoin, nofluffjobs, solidjobs, platsbanken, arbeitsagentur, remotive, remoteok, himalayas, jobicy,
    workingnomads, wwr, 4dayweek; academic: euraxess, jobs.ac.uk, varbi...; generic RSS/Atom + JSON-LD
    JobPosting; detect(url)); catalog.yaml (100+); custom_sources table + API + Settings → Sources UI; import
    career-ops portals.yml; ISO 3166 data + groups, resolve_location, country include/exclude; preferences
    (sponsorship, authorized countries, max upfront cost + currency, funding); signals (sponsorship, language,
    citizenship, funding, fees); ECB FX rates.
  - M16: PATCH /providers/{id} + edit UI; electron-updater (latest.yml/blockmap in release), periodic check,
    restart to update, updater cache cleanup, Easy-mode image pull + prune; GET /version + update banner;
    easy scripts `-Update`.
  - M17: scripts/real_world_run.py against production-mode stack with the user's files; fix every error found;
    sanitized evidence here.
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
  - M12 autopilot (ADR-0014, migration 0011):
    - Policies per case, off by default.
    - Auto-submit and declaration ticking need the consent text sent back verbatim; the text
      and time are stored.
    - `domain/policy.py` (consider, shortlist and may_auto_submit, each with reasons).
    - `domain/site_policy.py`: manual-only sites with published automation bans, robots.txt,
      a human approval for portals and plain http, and pacing of one session per site every
      10 minutes.
    - `autopilot_cycle` workflow (discover → shortlist → report).
    - A level-triggered reconciler on each worker maintenance tick. It moves `autopilot_items`
      through research → drafts → placeholder filling → render → application → fill → submit or
      approval, using the same use cases as the screens.
    - Answer bank (`case_answers`):
      - questions come from form fields and document placeholders;
      - answers arrive from the app or by chat reply and are reused;
      - placeholders are filled into a new, user-attributed document version.
    - A policy approval is recorded as an approved `approval_requests` row and audited.
    - Kill switch: the UI button, `POST /autopilot/stop`, or STOP from a paired chat. There is
      also a daily digest.
    - Assisted mode (`browser_assist`): a visible window where the person solves the CAPTCHA
      and submits, and NexScout only observes. It is on in desktop local mode.
    - Web: an Autopilot section (settings with consent, the work list, questions waiting,
      saved answers, the manual-only list) and "Open a browser window for me" on blocked
      applications.
  - M13 releases and easy install:
    - `.github/workflows/release.yml`: a minor bump from the latest `v2.x.y` on every green
      `main` push. It publishes GHCR images, the unsigned Windows installer, a pinned easy
      bundle zip and the GitHub Release.
    - `easy/`: compose on the released images (127.0.0.1 only, no database port), plus
      double-click start and stop scripts for Windows, macOS and Linux. Secrets are generated
      once. In a source checkout, the scripts fall back to building locally.
    - Desktop Easy mode: Docker detection and start, secrets in OS secure storage passed in
      memory, background operation, and a "Stop NexScout" menu item.
    - The app version comes from `NEXSCOUT_VERSION`.
    - In-app Getting started checklist, `docs/USER_GUIDE.md` (non-technical), a user-first
      README, and a CHANGELOG.
- **Environment:** Windows 11, Docker Desktop 29.8.2 (CLI at
  `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin`, on the user PATH), Python 3.13.15 via uv,
  Node 26.10, Postgres 17 in compose.
- **Blockers:** none. Live provider verification needs a user-supplied key or a local Ollama/LM
  Studio (see KNOWN_LIMITATIONS provider matrix: none live-verified).
- **Observed, not failing:** one `Failed to proxy … ECONNRESET` line from `next dev` during the
  M2 E2E (a request aborted by page navigation; the test passed).
- **Plan agreed with the user (2026-10-17): human-in-the-loop autopilot**
  - **M11 Notification channels** (official APIs only) — ✅ done:
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
  - **M12 Autopilot** (standing approvals, never guessing) — ✅ done:
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
  - **M13 Releases and easy install** — ✅ done (v2.0.0 released and installed from the zip):
    1. `release.yml`: on green CI on main, bump minor from the latest `v2.*` tag, tag, release notes,
       GHCR images (api/worker, web), Windows installer, "easy" bundle.
    2. Desktop **Easy mode**: installer → open → NexScout starts its own Docker stack (bundled
       compose, generated secrets, master key in OS storage) → setup wizard in the browser window.
    3. `Start NexScout` scripts for Windows/macOS/Linux (Docker), in-app onboarding wizard.
    4. `docs/USER_GUIDE.md` for non-technical users; README rewritten user-first.
- **M14 (✅, 411dc55):** shipped builds run `NEXSCOUT_ENV=production`; demo sources and the demo site only with
  `NEXSCOUT_DEMO_DATA=1`; cookies secure only on https; runtime `/api` proxy (`src/proxy.ts`); `user_message()`
  for every user-visible error; uvicorn keep-alive 75 s (fixed ECONNRESET 500s through the Next proxy); only
  the primary source updates a merged listing; E2E error guard (`e2e/fixtures.ts`) + route crawl; CI E2E in dev
  and production builds.
- **M15 (✅):**
  - Sources (ADR-0015): 32 providers ported from career-ops @340a53b1 (THIRD_PARTY_NOTICES.md), every network
    provider checked live and replay-tested from recorded real responses (`scripts/record_source_fixtures.py`,
    `tests/fixtures/sources/`); `catalog.yaml` (168 entries; 61 unsupported and 10 manual-only, each with a
    reason) built by `scripts/build_catalog.py`; custom sources by URL with detection (patterns → ATS links on
    branded pages → feed autodiscovery → JSON-LD) and test-fetch; career-ops `portals.yml` import; per-source
    health; parallel fetch with isolation; keyword and country filtering before storage. Settings → "Where to
    look" (`components/sources-manager.tsx`); the opportunity board links there and says when nothing is on.
  - Countries/signals/budget (ADR-0016): ISO 3166-1 data (249 + 15 groups, `scripts/gen_countries.py`),
    `CountryPicker` in preferences and autopilot (include + exclude), signals (sponsorship, work rights,
    languages, funding, fees), ECB FX (`fx_rates`, refreshed daily by the worker), budget check in the user's
    currency. Policy messages name countries ("Germany isn't in your countries").
  - Found while verifying: the country picker chose the DACH group for "Germany" + Enter (fixed: exact →
    prefix → contains ranking, countries before groups); **reminders were due on the UTC day, not the user's**
    (m8 E2E failed between 00:00 and 05:30 IST). Fixed with `users.timezone` (migration 0013, reported by the
    browser at register/login, system role may read only `users(id, timezone)`), used by the reminder sweep
    and the dashboard; `tzdata` is now a direct dependency so Linux images have zone data.
  - Desktop `tsconfig.json`: `module`/`moduleResolution` `node16` (node10 is deprecated and is removed in
    TypeScript 7); still emits CommonJS for Electron; verified with TypeScript 6.0.3.
- **M16 (✅):**
  - `PATCH /providers/{id}` + Settings → AI models → Edit. Partial update with version check. The key is
    write-only (blank = keep, new = replace, `clear_api_key` = remove). **The stored key never follows a changed
    destination:** a new address or type needs the key entered again. A changed model/address/type/key resets
    verification. Audit lists field names only. IDOR sweep covers PATCH.
  - Desktop self-update (ADR-0017): electron-updater 6.8.9 (pinned; published 2026-06-05), `publish: github`,
    artifact `NexScout-Setup-${version}.exe`; release uploads exe + blockmap + `latest.yml` (checked in the job).
    `src/updates.ts`: check after 10 s, every 6 h, menu "Check for updates…", Restart now/Later, updater cache
    `pending` removed after a version change. Easy mode removes older NexScout images after `up -d`
    (`staleImages`, tested).
  - Easy zip: `Update NexScout.cmd/.command`, `start-nexscout.sh update`: latest tag → download → verify against
    the release's new `SHA256SUMS.txt` → replace files (never `.env`) → re-run → remove old images.
  - `GET /api/v1/version` (signed-in; 6 h cache, 15 min retry; untrusted answer validated) + web banner (hidden in
    the desktop app, dismissible per version). `NEXSCOUT_UPDATE_CHECK=0` in tests/E2E. Live parse checked once:
    `Release(version='2.2.0', …/tag/v2.2.0)`.
  - Found while building: a bash heredoc ate the backslashes in a Windows path test (memory rule: use Write/Edit);
    `VersionOut` schema name collided with the documents schema (renamed `AppVersionOut`).
- **M17 (🟨 in progress) real-world run** (`scripts/real_world_run.py`, personal data only in
  `NEXSCOUT_REAL_RUN_DIR` and a scratch output folder):
  - Stack: the **released v2.3.0 Easy bundle**, downloaded with `gh release download`, checksum
    verified (`sha256sum -c`), started with its own script on port 3300. Production mode confirmed
    (`NEXSCOUT_ENV=production`; `/fixture-site/` and `/api/docs` 404 from the API). The start
    script removed the old 2.0.0 images (live check of the cleanup).
  - Setup: account, case "Europe: AI/ML/CV (jobs + PhD)", CV read into 101 entries (each quoting
    the CV, accepted), preferences: Europe, sponsorship needed, English, funding preferred,
    150000 INR upfront, flexible experience.
  - Sources: 168 catalog sources on; the user's `portals.yml` import: 91 catalog entries on,
    12 added, 19 unsupported with reasons (web-search entries, providers not ported: gem,
    successfactors, wttj). "Jobs in Finland" detected as Work in Finland.
  - Sync: 180 sources in 130 s, 2,316 postings kept, 19,923 dropped by country and keyword
    filters, 17 sources failed with HTTP 404 (8 catalog entries, 9 from the user's own file).
  - Found and fixed:
    1. Duunitori (manual-only) was fetched when added by URL. Manual-only sites are now
       refused before any request (add and import).
    2. The import ignored the 300-source cap.
    3. The catalog shipped dead and duplicate entries. Builder `--verify` and dedup fixed this:
       167 entries.
    4. **Every match scored 82.** Real postings have no structured skills or experience.
       `domain/requirements.py` now reads skills, years, seniority, language and postdoc from
       the text. Score SD 4.8 → 9.1; top results are relevant (Hugging Face, Photoroom, Wayve,
       Faculty).
    5. Refused sponsorship was only a gap in flexible mode; it is now a blocker.
    6. Swedish/German/French-only postings stayed eligible for an English-only user. They are
       now blockers (96 jobs).
    7. A postdoc was listed for someone with no doctorate.
    8. "Lunds universitet" and "Lund University" were duplicates.
    9. Only 17 PhD postings: added 8 Swedish universities (Varbi) and Tampere (rekrytointi
       feed).
  - NIM: `/v1/models` lists 81 models, but several return 404 for this key. The harness probes
    them; `nvidia/nemotron-3-super-120b-a12b` answered valid JSON in 4.3 s.
- **M17 (continued, v2.4.0 → v2.5.0):**
  - **Desktop self-update verified for real:**
    - The installed 2.3.0 (silent per-user install of the released exe, checksum checked)
      found 2.4.0.
    - It downloaded it differentially: 971 KB of 109 MB via the blockmap.
    - It installed on quit (`--updated /S`; exe now 2.4.0.0).
    - On the next start it logged "updated 2.3.0 -> 2.4.0; removed downloaded installers"
      (`pending` gone).
    - The test install was uninstalled afterwards.
  - **Easy-zip update verified for real:** `start-nexscout.ps1 -Update` in the 2.3.0 bundle
    downloaded the 2.4.0 zip, verified it against `SHA256SUMS.txt`, replaced the files (the
    compose now pins 2.4.0; `.env` kept), restarted on port 3300, and removed the 2.3.0 images.
    The NIM key sealed under the zip's master key still decrypts (Check connection ok).
  - Found while testing the updater: the desktop app's Easy mode **took over the zip's stack**
    (same Compose project `nexscout-easy`, different keys). Both launchers now refuse a stack
    another existing install started (`foreignEasyStack`, tested).
  - Re-sync on 2.4.0: 186 sources in 229 s, 1,764 kept. PhD research: 3–12 quoted findings per
    position.
  - Job research found 0–1 findings (the rules were PhD-only). It now lists experience, visa,
    work rights, languages and relocation, each quoting its sentence.
  - "Fluent German is a plus" was read as required. Optional cues are now handled (EN, DE, SV,
    FI, FR, NL).
  - **AI drafts all failed** with `OutputInvalid` ("Expecting value"): the draft agent capped
    answers at 2048 tokens and Nemotron spent most of them reasoning (reproduced:
    `finish_reason=length`, 1564 reasoning tokens). The fix: up to 8192 within the provider
    limit, a clear `OutputTruncated` message, no futile repair, failed calls recorded in usage,
    and new providers default to a 4096 limit.
  - Resumes and academic CVs (no AI) were built. Applications were refused with "A chosen
    document still has placeholders": only **contact details** are missing (the CV reader
    doesn't turn contact data into profile entries). The person adds them once, then
    approves each submission in the app.
- On 2.5.0 the truncation was gone, but long AI drafts hit the 120 s request timeout and were
  reported as "a database or network hiccup". Drafts now get `max(120, max_tokens/15)` s, and a
  model timeout says which limit was hit (v2.6.0).
- On 2.6.0 most AI drafts succeeded. One cover letter still ran out of room at 8192: with 101
  profile entries, Nemotron sometimes reasons longer. The agent's own 8192 cap made the advice
  "raise Longest answer" useless. Drafts now use the provider's limit, up to half the context
  window, and providers gain "Skip the model's thinking" (both in v2.7.0, commit 827c608).
- **Final verification on the released v2.7.0** (4th real `Update NexScout`, 2.6.0 → 2.7.0, old images removed):
  "Skip the model's thinking" on (through the Edit API), and **all 10 documents were built**: 3 cover letters and
  2 statements of purpose by NIM (real text, cited, about 70 s each; only contact-detail placeholders left), plus
  3 resumes and 2 academic CVs without AI. CI was green on every push (7/7 jobs), and releases v2.2.0–v2.7.0 were
  published with exe, blockmap, latest.yml, easy zip and SHA256SUMS.txt.
- **Feedback on v2.8.0 (2026-10-22), 13 items.** Plan M18–M21, approved:
  - **M18:** profile export/import, CV reader v2, letters, links, snapshot delete, auto-arrange, multi-select.
  - **M19:** frameless window, tray (close-to-tray setting, default on), single instance, narrow IPC, Settings
    "About & updates", breadcrumbs, Home, drag-and-drop.
  - **M20:** paginated, virtualized opportunities; clear notifications and runs; performance on 5,000
    opportunities.
  - **M21:** agentic assistant (JSON tool protocol, allowlist, consent every conversation), AI skill discovery
    with one approval dialog.
  - **User decisions:** close hides to the tray, as a setting; assistant consent every conversation; the live
    profile is copied for testing, then the live install is re-read (pending entries only).
- **M18 (✅, v2.9.0):** see CHANGELOG v2.9.0 and ADR-0018.
  - **Real-data verification** on a copy of the user's live case:
    - Read through a local relay container, exported with `export-case`, imported into a dev account.
    - The import matched the live case by section and state: 121 entries, 3 documents, 3 snapshots, the mind map
      overrides (2 orphaned overrides skipped by design).
    - Re-read the CV PDF and both letters: 45 new suggestions, 0 failing the quality check (no `**`, no split
      brackets, no stray punctuation, no fragments).
    - Each letter gives 1 reference. Projects link to the accepted job or degree. The edited PTS-style job is
      not re-suggested.
  - **Found and fixed on the real text:**
    - A title, a blank line, then its date line (gave a project named "Independent").
    - Links wrapped by the PDF, words broken at a hyphen, and a link on the line after a trailing `|`.
    - Bare domains as project links.
    - Citations split into authors, title and venue.
    - Employer legal suffixes ignored in identity.
    - Links point at existing entries, and degree links are chosen by date.
    - A letter organization that wrapped into its parent group's name.
  - **Leftovers:** 42 old suggestions came from a CV the user deleted while keeping its suggestions. They are
    not removed automatically. Profile now shows "N suggestions came from a file you have since deleted" with
    **Remove them**.
- **Still open:** real application portals (forms differ per employer); code signing; macOS/Linux installers;
  live notification channels.
- **Next exact steps (the user's):**
  1. **Rotate the NVIDIA NIM key** (it was pasted in chat). Then use Settings → AI models → Edit to enter the new
     one (keep "Skip the model's thinking" ticked for Nemotron).
  2. In the real-run case, add contact details once: replace the `[[PLACEHOLDER: contact details …]]` line in each
     drafted document, or answer it once on the Autopilot page. Then start the applications and approve each
     submission yourself.
  3. Review the matches (report in the scratch output folder; the app shows the same, with reasons).
- **Next exact steps (engineering):**
  0. **M18 follow-up:**
     - After the user's desktop app updates to v2.9.0, run `reread-documents` on the live install (pending
       entries only).
     - Verify that accepted entries, the mind map and snapshots are unchanged (compare counts before and after).
     - Stop the `nexscout-live-relay` container afterwards.
     - Then M19 → M21 per the plan above.
  1. Port `successfactors`, `gem`, `wttj` providers (career-ops entries reported unsupported).
  2. University portals without feeds (DTU, TU Delft, ETH, EPFL, TUM, Helsinki): only with a public API or feed.
  3. Desktop app ↔ Easy zip: consider separate Compose project names with a data migration (now guarded).
  4. Later: live-verify one notification channel; macOS/Linux scripts and installers; upgrade GitHub Actions
     before the Node 20 runtime removal.

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
| 2026-10-17 | M11 pushed (e35d9a9): GitHub Actions run 39023019426 | **backend job failed** at `ruff format --check` (the committed snapshot had files that were only formatted afterwards); e2e, web, desktop and security green. Fixed by the next push (format check passes locally: 200 files) |
| 2026-10-17 | M12: ruff, format, mypy (130 files); `uv run pytest` | **347 passed** (new: 3 autopilot system tests with real headless Chromium against the demo site — consented auto-submit after a placeholder question and a form question were answered, exactly one submission with the declaration, policy-approved approval recorded, submitted position never retaken; no-consent path stops at approval with the reason, saved answer reused, approve → submitted, Stop → off and run refused; assisted mode: NexScout stops at the CAPTCHA, the simulated person solves and submits, confirmation recorded as `assisted`; 6 policy/site unit tests; STOP from chat; IDOR +8 routes, which caught assist answering 422 before 404, fixed) |
| 2026-10-17 | M13: `easy/Start NexScout` (PowerShell, this Windows machine, Docker Desktop per-user install) | **worked end to end**: found Docker, generated secrets once, the pull failed (no release images yet), fell back to a local build, all 4 containers healthy, opened :3000. A probe through the web port: register 201, create case 201, diagnostics show 1 worker alive. `Stop NexScout` stopped all containers; the probe stack and its secrets were then removed. macOS/Linux scripts were **not run** (no such machine) |
| 2026-10-17 | M13: desktop `npm test` (tsc + vitest) | **5/5** incl. Easy-mode config, validated secrets for compose, matching image version, Docker Desktop paths |
| 2026-10-17 | M13: packaged desktop app (`electron-builder --win nsis`, version 2.0.0) in Easy mode, `--smoke` with an isolated user-data dir, using the locally built images | **passed**: the bundled `resources/easy/docker-compose.yml` and roles SQL were found; compose project `nexscout-easy` up; the master key and DB password were stored encrypted by safeStorage (`master.key.enc`, `db.password.enc`), nothing in clear; the window loaded `http://127.0.0.1:18700/login`; the renderer has no require, process or module. The stack was then removed |
| 2026-10-17 | M13: first Release run 39025805605 (after green CI 39025532002 on 485b620) | version → v2.0.0 ✓; GHCR images backend + web pushed ✓; **Windows installer failed**: pwsh split the `-c.extraMetadata.version=…` argument, so publish didn't run and no tag was created. Fixed by running that step in bash (verified locally: `NexScout Setup 2.0.0.exe` built, easy resources bundled) |
| 2026-10-17 | M13: `release.yml` | YAML parsed; the version bump was checked by hand ('' → v2.0.0, v2.0.0 → v2.1.0, v2.9.0 → v2.10.0) |
| 2026-10-17 | CI 39026238677 on f38ab96, then Release 39026495319 | CI 5/5 green. Release: version, images (backend, web), windows and publish all ✓. **v2.0.0** published with `NexScout-Setup-2.0.0.exe` (112 MB, unsigned) and `nexscout-easy-2.0.0.zip`: compose pinned to 2.0.0, `.cmd` files with CRLF, roles SQL, user guide and license included |
| 2026-10-17 | GHCR anonymous pull (registry token → manifest 2.0.0) | backend 200, web 200: the packages are public |
| 2026-10-17 | The released zip from a clean folder (Windows, local images deleted first) | **passed**: pulled `ghcr.io/avishakeadhikary/nexscout-backend:2.0.0` and web, 4 containers healthy, :3000 opened, register 201, diagnostics `app_version 2.0.0` with 1 worker alive. Stop script stopped everything; the test install and its volumes were removed |
| 2026-10-18 | M14: backend suite, `npx playwright test`, `E2E_PROD=1 npx playwright test` | 351 passed; **15/15** dev E2E (after the keep-alive fix); production E2E m5/m6 failures fixed (primary-source rule), then green |
| 2026-10-18 | M15: live provider probe (28 network providers) and fixture recording | all 28 returned postings; EU employers checked: Wolt, Oura, KONE, Helsing, DeepL, Synthesia, Wayve, Spotify, Adyen, Celonis, GetYourGuide, Delivery Hero, N26, Philips, Wise, Dataiku, Aalto (Workday); Varbi: Uppsala, KTH, Lund; Work in Finland (~1,180 jobs); Getro b2venture; ECB feed incl. INR |
| 2026-10-19 | M15: `uv run ruff check . && ruff format --check . && mypy` | all clean (142 source files) |
| 2026-10-19 | M15: `uv run pytest` | **422 passed** in 187 s (incl. 3 new time-zone tests: UTC+14 vs UTC-11 reminders, login follows zone, zone validation) |
| 2026-10-19 | M15: web typecheck, lint, vitest 12/12; desktop tests 5/5 | passed |
| 2026-10-19 | M15: `npx playwright test` and `E2E_PROD=1 npx playwright test` | **15/15** and **15/15** (first run: 2 failures, both real bugs: picker ranking and UTC reminders; fixed) |
| 2026-10-19 | CI 39175343754 + Release 39175729406 on ee9ce94 | CI 7/7 jobs green (backend, web, desktop, security, e2e dev, e2e prod); **v2.2.0** published: `NexScout-Setup-2.2.0.exe` (112 MB), `nexscout-easy-2.2.0.zip` |
| 2026-10-19 | M16: `uv run pytest`; ruff, format, mypy | **431 passed**; clean (144 files) |
| 2026-10-19 | M16: web typecheck, lint, vitest 12/12; desktop `npm test` | passed; desktop **7/7** (stale-image filter, updater cache path per OS) |
| 2026-10-19 | M16: `npx playwright test`, `E2E_PROD=1 npx playwright test` | **16/16** and **16/16** (new: provider edit in m4, update banner + dismiss in m16-updates) |
| 2026-10-19 | M16: local `electron-builder --win nsis --publish never -c.extraMetadata.version=2.99.0` | `NexScout-Setup-2.99.0.exe` + `.blockmap` + `latest.yml` (`path: NexScout-Setup-2.99.0.exe`, sha512); `resources/app-update.yml` provider github, `updaterCacheDirName: nexscout-desktop-updater` |
| 2026-10-17 | M12: web tsc, eslint, vitest 12/12; desktop tests 3/3; `npx playwright test` | passed; **14/14 E2E** incl. new journey (consent shown → autopilot on → run → the placeholder question appears instead of a guess → answered → saved answer listed → Stop everything → off) |

---
| 2026-10-23 | M18: `uv run ruff check . && ruff format --check . && mypy && pytest` | all passed: mypy 147 files, **467 passed** in 231 s |
| 2026-10-23 | M18: web `typecheck`, `lint`, `test` | passed (vitest 12/12) |
| 2026-10-23 | M18: `npx playwright test` (dev) | **18/18 passed**, incl. m18 export/import journey and leftover-suggestion removal |
| 2026-10-23 | M18: real-data copy, `reread-documents` | CV: 43 suggestions, letters: 1 reference each; 0 of 45 new suggestions fail the quality check; links to accepted job/degree |

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
| M12 | Autopilot | ✅ (demo site only; real portals unverified) | Scheduled discover → documents → fill → submit within a consented policy; unknowns asked, never guessed; manual-only sites respected; kill switch |
| M13 | Releases and easy install | ✅ (v2.0.0 released; Windows paths verified, macOS/Linux scripts not run) | Every green main push gets a minor-bump tag and release; non-technical users can install and start NexScout with a double-click |
| M14 | Production defaults and error sweep | ✅ | Shipped builds have no demo data, production settings, runtime API origin; no raw exception text reaches users; E2E fails on any page/console error or API 5xx in dev and production builds |
| M15 | Real sources, countries, signals, budget | ✅ (providers checked live 2026-10-18/19; endpoints can drift) | Real postings from catalog and custom sources with health; ISO include/exclude everywhere; sponsorship/language/funding/fee signals explained; budget in the user's currency |
| M16 | Provider editing and auto-update | ✅ (update path verified once v2.4.0 exists, see Checkpoint) | Providers editable without re-adding; installed desktop app updates itself and removes old installers and images; web shows when an update exists |
| M17 | Real-world run | ✅ (real CV, 186 live sources, NIM drafting; submissions left to the user by design) | The user's real CV and preferences run end to end on a production-mode stack with real sources and a live AI provider; every error found is fixed |
| M18 | Portable profile and better reading | ✅ | Export/import a case faithfully as a new case; CV reader v2 gives clean entries on the user's real CV (0 quality failures); letters give references; links, bulk actions, snapshot delete, auto-arrange |
| M19 | Native desktop shell and navigation | ⬜ | Frameless title bar, tray with close-to-tray setting, single instance, origin-checked IPC, About & updates, breadcrumbs, drag-and-drop |
| M20 | Scalable lists and housekeeping | ⬜ | Opportunities paged and virtualized (5,000 measured), clear notifications and runs |
| M21 | Agentic assistant and AI skills | ⬜ | Tool-using assistant with allowlist and per-conversation consent; AI skill discovery with one approval dialog |

## Deferred / open items
_(Each item: dependency, concrete plan, acceptance test.)_
