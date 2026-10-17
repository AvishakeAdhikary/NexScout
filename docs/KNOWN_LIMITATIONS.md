# NexScout Known Limitations

Kept current. Anything not listed as verified here should be assumed **not** to work.

## Integrations (by design or not yet available)
| Integration | Status | Reason |
|---|---|---|
| LinkedIn, Google Scholar, ResearchGate data import | Not supported. Store the URL only, enter data by hand | No permitted public API. Scraping would violate terms/access controls |
| ORCID, arXiv | Planned live adapters (M5, opt-in) | Public APIs exist |
| Job boards | Fixture adapters only until a permitted API is configured | Terms vary per board |
| Malware scanning of uploads | Hook only | Needs ClamAV. Not bundled |
| A2A | Not implemented (ADR-0007) | No remote agent consumer yet |
| macOS desktop builds | Not producible on the Windows dev host | Needs macOS for build and signing |

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
- Notifications are in-app only. NexScout sends no email, SMS or push notifications; sending
  messages is consequential and no outbound channel is configured.
- Reminders and notifications are created by the worker's sweep. Without a running worker,
  nothing new appears.
- The assistant is a fixed-menu, rule-based router in English (no LLM). It understands a small
  set of requests and says so otherwise. It never submits, sends or approves anything.
- Bulk changes cover manual statuses only (tracking, completed, rejected, withdrawn, cancelled,
  paused); each item is validated by the state machine.

## Agent runtime (M4)
- Only four workflows exist: reading uploads, opportunity search, the AI summary draft, and a
  diagnostic system check. PhD and job document generation arrives in M5–M6.
- Pause takes effect at the next step boundary. A long single step, such as one slow model call,
  runs to completion first. Cancel can interrupt mid-step.
- There is no reduced-context retry or task splitting for small models; output validation gets one repair attempt only.
- Per-user quotas are concurrency limits only. There are no daily token or cost caps yet.
- The run list relies on live events plus a 30 s fallback poll. Behind a proxy that buffers SSE,
  updates can lag by up to 30 s.

## Functional gaps
Everything after the current milestone in ROADMAP.md is not built yet. UI sections for later
milestones show an explicit "not available yet" state.

## Unverified artifacts (exist but have not been executed)
| Artifact | Why unverified | Verify by |
|---|---|---|
| `.github/workflows/ci.yml` | Not pushed to GitHub (no remote) | First push/PR |
| E2E in CI | No CI job for Playwright yet | Add job with Postgres service + `npx playwright install --with-deps chromium` |
