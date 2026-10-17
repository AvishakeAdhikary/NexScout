# NexScout Known Limitations

Kept current. Anything not listed as verified here should be assumed **not** to work.

## Integrations (by design or not yet available)
| Integration | Status | Reason |
|---|---|---|
| LinkedIn, Google Scholar, ResearchGate data import | Not supported. Store the URL only, enter data by hand | No permitted public API. Scraping would violate terms/access controls |
| ORCID, arXiv | Planned live adapters (M5, opt-in) | Public APIs exist |
| Job boards | Fixture adapters only until a permitted API is configured | Terms vary per board |
| Malware scanning of uploads | Hook only | Needs ClamAV. Not bundled |
| A2A | Not implemented (ADR-0007/0011) | No remote agent consumer yet |
| MCP client (calling external MCP servers) | Not implemented (ADR-0011) | Nothing configured to verify against; needs an allowlist and approval design |
| MCP server | Read-only, stdio only (`nexscout mcp`) | No HTTP transport; no write tools by design |
| macOS / Linux desktop builds | Not built (configs exist) | macOS needs a Mac to build and sign; Linux AppImage wasn't built on this host |
| Windows installer signing | Unsigned (`NotSigned`) | No code-signing certificate configured; SmartScreen will warn |
| Self-contained desktop bundle | Not provided | The desktop app is a shell: local mode needs a NexScout checkout, Postgres, uv and Node (ADR-0011) |

## Provider capability matrix
"Adapter" means the adapter is implemented and unit-tested against a mocked HTTP or SDK transport.
"Live-verified" means a real call to the real service succeeded. **No real provider has been
live-verified yet.** No API keys or local model runtime were available on the dev host. Users can
check their own setup with "Check connection" in Settings, which records the result.

| Provider | Adapter | Structured output | Live-verified |
|---|---|---|---|
| Mock | ✅ | ✅ deterministic | n/a (labelled "mock, not AI" everywhere) |
| OpenAI-compatible: OpenAI | ✅ | json_schema `response_format` when enabled, else instructions + validation | **no** |
| OpenAI-compatible: Ollama, LM Studio | ✅ (same adapter) | instructions + validation (json_schema if enabled) | **no** |
| Anthropic | ✅ (SDK) | `output_config.format` json_schema | **no** |
| Gemini | ✅ (google-genai) | `response_schema` | **no** |

- Token counts for budgets use a chars/3.5 estimate, not each provider's tokenizer.
- Cost is computed only from the per-million-token prices that the user enters.

## Profile and documents (M2)
- **Extraction is rule-based (`heuristic_v1`), not AI.** It recognizes common English CV headings
  and simple entry layouts. Unusual layouts produce fewer entries, or `other` entries with a
  warning. Nothing is invented, and every entry needs the user's review. LLM-assisted extraction
  is not built yet. The provider layer has existed since M4; extraction is planned alongside M5 drafting.
- **No OCR:** scanned PDFs (images only) are stored, but their text can't be read.
- Only CV/résumé uploads are mined for entries. Other documents are stored as supporting files.
- Upload size is checked from `Content-Length` and while reading. A chunked upload without a
  length is still spooled by the server before rejection. Enforce a body limit at the reverse
  proxy in production.
- If the DB insert fails after the file is stored, an orphaned file can remain. No orphan sweep
  job exists yet (M10).
- Reading runs on the background worker (isolated subprocess, 20 s cap). Without a running
  worker, uploads stay "Reading…".

## Mind map and opportunities (M3)
- Only **demo fixture sources** exist. No live job or academic source is connected yet. Every
  demo result is labelled in the UI.
- Matching is deterministic and simple (keyword skill matching, years computed from dated
  entries, degree keywords). It doesn't understand synonyms beyond exact or normalized names.
- When one catalog listing is seen on several sources, the most recently changed listing's
  content wins.
- Dedup reports are stored for review but don't yet change results.
- Searches run on the background worker (per-listing transactions, resumable).
- Dragging nodes is mouse-only. Keyboard users get the full list view instead.

## PhD research and documents (M5)
- **Research extraction is rule-based (`rules_v1`), not AI.** It finds deadlines, degree and
  language requirements, required documents, funding sentences and named people when pages state
  them in common English phrasing. It misses unusual wording rather than guessing. Each finding
  quotes its source.
- Only the **demo listings have pages to read** (bundled, labelled demo pages). For real listings
  the SSRF-safe fetcher reads linked pages (robots.txt respected), but no real academic source is
  connected yet, so this path has been tested only against a local test server.
- **No live arXiv or ORCID adapters yet** (planned as opt-in). Supervisor research is limited to
  what the position's pages say.
- Drafts made with the mock model are deterministic templates labelled "Mock text, not written by
  AI". The SOP mock deliberately includes one unsupported claim, to demonstrate that the verifier
  removes it.
- The verifier checks citations and numbers, not meaning. A cited sentence can still overstate an
  entry ("led" vs "contributed"). Users must review every draft; intent sentences are flagged.
- PDF uses system serif fonts (no bundled font). Markdown tables aren't rendered as tables.
- The backend container is about 2.1 GB because of headless Chromium.
- Job documents: the resume is assembled from entries in a fixed order; there's no tailoring per job yet. Referral suggestions match by organization name only, so subsidiaries and renamed employers aren't linked.

## Regional document formats (ADR-0012)
- Six format profiles: North America, UK/Ireland, German-speaking, European (Europass-style),
  Australia/New Zealand, and the international fallback. Every other country uses the fallback,
  with a note.
- These are conventions, not official rules. Posting requirements are checked only when
  research quoted them (page and word limits for CVs, statements, letters and proposals).
- Headings are in English. There's no translation into the posting's language and no standard
  national forms (e.g. Japan's rirekisho).
- The Lebenslauf format ends with place and date placeholders. NexScout never adds photos,
  birth dates, signatures or declarations.

## Applications and browser automation (M7)
- **Only tested against the bundled demo application site.** Real employer and university
  portals (multi-step wizards, custom widgets, single sign-on) haven't been tried. Unsupported
  forms stop with a reason rather than guessing.
- Supported: single-page HTML forms with labelled inputs, textareas, selects (answered by the
  user), file uploads and declaration checkboxes.
- NexScout never logs in, stores site passwords, or solves CAPTCHAs. For those sites you apply
  yourself and mark the application as submitted (your confirmation is recorded as such).
- Confirmation detection is English-only. An unrecognized confirmation is reported as "not
  confirmed" for you to resolve; it's never treated as submitted.
- A screenshot of each filled form is stored with the application (it can contain the values
  you entered).

## Tracking, notifications and assistant (M8)
- Notifications appear in the app and, from M11, on channels the user connects and pairs
  (Telegram, Discord, WhatsApp Cloud API, Slack, email, webhook). NexScout sends nothing to
  anyone else. There are no SMS or mobile push notifications.
- Reminders and notifications are created by the worker's sweep. Without a running worker,
  nothing new appears.
- The assistant is a fixed-menu, rule-based router in English (no LLM). It understands a small
  set of requests and says so otherwise. It never submits, sends or approves anything.
- Bulk changes cover manual statuses only (tracking, completed, rejected, withdrawn, cancelled,
  paused); each item is validated by the state machine.

## Notification channels (M11)
- **Not live-verified.** Every provider adapter is tested against faked HTTP APIs and a fake
  Discord Gateway. No message has been sent to real Telegram, Discord, WhatsApp, Slack or SMTP
  servers from this repository's tests. Verifying needs the user's own bot, app or account.
- **WhatsApp:**
  - Needs a Meta WhatsApp Business app.
  - Replies need a public HTTPS webhook (a tunnel or a server).
  - Outside the 24-hour customer-service window, Meta only delivers approved templates
    (`template_name`).
  - Interactive buttons work only inside that window.
- **Discord:** the bot can DM the user only if they share a server with it.
- **Telegram:** each bot token is long-polled by one NexScout worker at a time. Two workers
  polling the same token conflict (Telegram returns 409).
- **Slack, email and webhook** are outbound only. Their links open NexScout; there are no
  buttons in them.
- **Links:** chat apps refuse buttons that point at localhost or private addresses. Such links
  are sent as text. Setting `NEXSCOUT_PUBLIC_WEB_URL` to an HTTPS address gives an "Open in
  NexScout" button.

## Autopilot (M12)
- **Real portals.** The only site NexScout fills and submits automatically in tests is the
  labelled demo site. Real employer portals differ widely: multi-page forms, custom widgets and
  account walls. Expect `needs_user_action` (assisted mode) more often than full automation.
- **Manual-only list.** The list of sites with published automation bans is maintained by hand
  (`domain/site_policy.py`, checked 2026-10). A site missing from it still goes through the
  robots.txt and portal checks.
- **Assisted mode** works only where the worker runs on the user's own computer (the desktop
  app sets `NEXSCOUT_ASSISTED_BROWSER`). On a server there is no screen to show a window on.
- **Model-written documents.** Documents written by the mock model never auto-submit. With a
  real model, the drafting consent approval is still asked per document when profile data
  leaves the device.

## Releases and easy install (M13)
- **GHCR images are public.** After the first release (v2.0.0), anonymous pulls of both
  images returned 200, so no login is needed. If a fork publishes private packages, the easy
  install can't pull them; from a source checkout it builds locally instead.
- **The Windows installer is unsigned**, so SmartScreen warns on first run. macOS and Linux
  desktop builds aren't produced.
- **Only the Windows start script has been run.** The macOS and Linux scripts were written to
  the same steps but haven't been run.
- **Easy mode and the zip bundle run the worker inside Docker**, so assisted mode (a visible
  browser window) isn't available there. Use local mode, or apply yourself and mark the
  application as submitted.
- **Easy mode keeps the dev role passwords** for the internal database roles. The database
  publishes no port, so only NexScout's containers can reach it, but this isn't a hardened
  multi-user server setup (see OPERATIONS for production).

## Agent runtime (M4)
- Only four workflows exist: reading uploads, opportunity search, the AI summary draft, and a
  diagnostic system check. PhD and job document generation arrives in M5–M6.
- Pause takes effect at the next step boundary. A long single step, such as one slow model call,
  runs to completion first. Cancel can interrupt mid-step.
- There is no reduced-context retry or task splitting for small models; output validation gets one repair attempt only.
- Per-user quotas are concurrency limits only. There are no daily token or cost caps yet.
- The run list relies on live events plus a 30 s fallback poll. Behind a proxy that buffers SSE,
  updates can lag by up to 30 s.

## Hardening status (M10)
- **Dependencies (2026-10-17):**
  - `pip-audit`: no known vulnerabilities.
  - Web runtime (`npm audit --omit=dev`): 0.
  - Web dev tooling: high-severity `braces` (regex denial of service) through the shadcn CLI and
    eslint-config-next. `braces` 3.0.3 is the latest version, so no fix exists yet; it's only
    used at build and lint time on developer-controlled patterns.
  - Desktop: moderate `sprintf-js` through electron-builder (packaging only, not in the shipped
    app).
- No metrics exporter (Prometheus or OpenTelemetry) and no alerting; use logs and Diagnostics.
- Throughput was measured on one laptop (OPERATIONS.md), not under a production load profile.
  There is no rate limiting beyond login attempts.
- GitHub Actions CI is defined but has never run (no remote).
- There's no automated E2E job in CI yet.

## Functional gaps
All UI sections are built. What is demo-only or unverified is listed above: data sources,
the application site, live AI providers, installers.

## Unverified artifacts (exist but have not been executed)
| Artifact | Why unverified | Verify by |
|---|---|---|
| `.github/workflows/ci.yml` | Not pushed to GitHub (no remote) | First push/PR |
| E2E in CI | No CI job for Playwright yet | Add job with Postgres service + `npx playwright install --with-deps chromium` |
