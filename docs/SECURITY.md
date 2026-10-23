# NexScout Security and Threat Model

NexScout stores résumés, education records, eligibility data, credentials for third-party sites and
application history. Treat it as a **high-sensitivity personal-data system**.

## 1. Assets
| Asset | Sensitivity |
|---|---|
| Profile facts, documents, generated materials | High (PII) |
| Eligibility/sensitive attributes (visa, veteran status, …) | Very high. Optional, private by default |
| Third-party site credentials, session cookies | Critical |
| LLM provider API keys (BYOK) | Critical |
| Application submission ability | Critical (irreversible real-world effect) |
| Audit log | High (integrity) |

## 2. Trust boundaries
1. Browser ↔ web/api (untrusted client).
2. api/worker ↔ Postgres (trusted. RLS still enforced for the app role).
3. Worker ↔ external web and research sources (**untrusted content**).
4. Worker ↔ LLM providers (data leaves the system. Only minimal necessary context is sent).
5. Worker ↔ application sites via browser (untrusted content, consequential actions).
6. MCP/A2A peers (untrusted unless authenticated and allowlisted).

## 3. Threats → controls (STRIDE-oriented plus agent-specific)
| Threat | Control | Test |
|---|---|---|
| Cross-tenant read/write (IDOR) | Owner filter in every use case + RLS (ADR-0003). 404 on miss | `tests/security/test_idor_*` sweeps every route with a second user. RLS raw-SQL test |
| Session theft / CSRF | httpOnly+SameSite cookies, hashed tokens, CSRF double-submit, expiry, revocation | API tests for missing/invalid CSRF, expired and revoked sessions |
| Credential stuffing | argon2id, rate limiting, generic errors | rate-limit test |
| Prompt injection in pages/docs/emails | Untrusted content wrapped in labelled data blocks. The system prompt states that data can't issue instructions. Tools available to a node are fixed by code, not by model output. Consequential tools always need approval | injection fixtures must not trigger tool calls or approvals |
| Malicious tool/MCP output | Schema validation of every tool output, allowlisted servers, output size limits, treated as data | contract tests |
| SSRF / metadata access | Safe fetcher: http/https only, DNS resolution with blocking of private, loopback, link-local, CGNAT, metadata (169.254.169.254, fd00:ec2::254) and IPv6 ULA ranges. Re-check on each redirect (max 5). Size and time caps. As built (M5): `infrastructure/fetch.py` pins each connection to the IP it checked at connect time (no DNS-rebinding window), honours robots.txt, and allows only text content types | `tests/unit/test_fetch.py` (loopback/private/metadata, redirect to metadata, rebinding, schemes, robots, caps) |
| Malicious uploads / path traversal | Size cap, magic-byte allowlist (pdf, docx, md/txt), content-addressed names, parse in the worker with time and memory limits, no macros executed | upload fuzz tests |
| Browser automation reaching internal services | Every page request passes `infrastructure/browser.Guard` (public hosts only, plus the dev demo-site origin). Application URLs are SSRF-checked when saved | `tests/unit/test_forms.py::test_guard…`, `tests/system/test_browser_apply.py::test_application_urls_are_ssrf_checked` |
| Unapproved or duplicate submission | Declarations are ticked only after approval; the plan fingerprint must match the approved one; SUBMITTING is committed before the click and is never retried | `tests/system/test_browser_apply.py` |
| Token theft for local integrations | MCP tokens: 256-bit, digest only stored, shown once, expiring, revocable, audited, read-only scope; passed by environment, not argv | `tests/system/test_mcp.py` |
| Desktop renderer compromise | contextIsolation, sandbox, no nodeIntegration, no webview, navigation pinned to the app origin, external links http(s)/mailto only, permissions denied; master key in OS safeStorage | `apps/desktop/src/policy.test.ts`, `npm run smoke` (checks the page can't reach `require` or `process`) |
| Hostile uploads (zip bombs, executables, traversal names) | Magic-byte sniffing. DOCX zip-bomb limits from the central directory before inflating: 100 MB total, 200× ratio, 2,000 members. Display-only filenames; content-addressed storage; parsing in a killable subprocess; downloads are always attachments with a sandbox CSP | `tests/security/test_upload_fuzz.py` |
| Prompt injection via CVs, pages, model output, chat | Inputs are labelled data in prompts. Extraction is rule-based and quote-only. The verifier removes uncited claims and invented numbers. Chat refuses to submit. Nothing consequential happens without approval | `tests/security/test_prompt_injection.py` |
| Retention and data minimization | Operational data purged on schedule (OPERATIONS.md); delete-only grants for the worker | `tests/system/test_tracking.py::test_retention…` |
| Dependency and secret hygiene | `pip-audit`, `npm audit --omit=dev`, secret scan of the tree and the full history; CI `security` job | evidence in ROADMAP.md |
| Secrets leakage to LLM/logs | Secrets only via `secret_ref` resolved at the adapter edge. structlog redaction of keys/tokens/cookies/passwords. Prompts and documents are not logged by default | log-redaction test |
| Unapproved external action | `approval_requests` enforced in deterministic code before submit, send, pay or attest. Idempotency keys | system test: graph halts at the gate |
| Duplicate submission after crash | Idempotency key + `submitting` state + reconciliation → `submission_uncertain` | recovery test |
| Infinite agent loops / resource exhaustion | Per-run step budget, token budget, wall-clock timeout, per-user concurrency quota | runtime unit tests |
| Command injection | No shell calls with model or user input. Subprocesses take argv lists only | code review rule |
| Discriminatory matching | Protected attributes excluded from scoring by construction (they never enter the matcher input type) | unit test on the matcher input schema |
| Stale/incorrect research | Provenance, retrieval time, confidence. Official sources outrank others | research unit tests |

## 3a. Shared opportunity catalog
`organizations`, `opportunities` and `opportunity_sources` hold public posting data shared by all
users (no RLS; the app role may SELECT/INSERT/UPDATE but not DELETE). No personal data is written
there. Search keywords, preferences and match results live in owned tables. Users reach catalog rows
only through their own `opportunity_matches`. User-configured private or authenticated sources must
never write to the shared catalog (enforced when such adapters are added; see KNOWN_LIMITATIONS).

## 3b. Profile import (ADR-0018)
- A `.nexscout` file is untrusted input.
- **Limits:** 100 MB file, 300 MB unpacked, 500 parts, `profile.json` ≤ 50 MB. Absolute, `..`
  and drive-letter paths are refused.
- **Validation:** every entry goes through the same schema as manual entry, and every document
  through upload sniffing. Preferences, relationships, links and answers go through their own
  use cases. Meta keys are allow-listed.
- **Isolation:** import always creates a new case owned by the importer. Ids are regenerated,
  so a file can't point at anyone else's rows.
- Exports never contain secrets, AI providers, tokens, applications or runs.
- `case.exported` and `case.imported` are audited.

## 3c. Contact details
- Contact details are personal data. They are never part of a prompt: documents get them after
  the model has answered, by plain code (`domain/contact.fill_placeholders`).
- A CV header only suggests them. Nothing is saved until the user saves.
- `GET`/`PUT /cases/{id}/contact` and `POST /generated-documents/{id}/fill` are in the IDOR
  sweep.
- Form filling uses them only for fields about the user's own name, contact and residence. A
  field about citizenship, nationality, birth, a visa, a referee, an employer or an institution is
  never filled from them.

## 4. Data protection
- TLS in production (terminated at the proxy). Postgres connections use TLS when remote.
- At rest: disk encryption at the infrastructure level, plus application-level AES-GCM for secrets and
  credentials (`secrets` table holds ciphertext, nonce and key id. The master key comes from
  `NEXSCOUT_MASTER_KEY` or a key file. Desktop uses Electron `safeStorage`).
- Export: `GET /api/v1/me/export` (zip of JSON + original documents). Deletion: account and case
  delete cascades plus object-store cleanup. Both are audit-logged.
- Retention: configurable windows for events, task attempts and debug captures. Defaults are listed in OPERATIONS.md.

## 5. Browser automation policy
Never bypass CAPTCHA, MFA or anti-bot protections. On encountering them → `needs_user_action` +
manual takeover. Sessions are stored encrypted, per user and per site, and deletable. Cookies never enter
prompts. Final submit needs an approval unless a narrow, explicit standing policy exists.

## 5a. Notification channels (ADR-0013)
- **Official APIs only.** Telegram Bot API, Discord bot (REST plus Gateway), Meta WhatsApp Cloud
  API, Slack incoming webhooks, SMTP and signed webhooks. NexScout never uses unofficial
  WhatsApp Web clients.
- **Paired identity.** A one-time code (hashed, 30-minute TTL) binds a channel to one chat, user
  or phone number. Everything from any other identity is ignored. Unpaired senders get no
  reply, so there is no oracle.
- **Buttons.** Button tokens are random, single-use and expire after 7 days. They are bound to
  one channel and its paired identity. Siblings are invalidated together. Decisions go through
  `runs.decide` in a tenant (RLS) session and are audited.
- **Inbound.** Inbound events are deduplicated by provider event id. The WhatsApp webhook is
  unauthenticated and can only INSERT. The worker verifies `X-Hub-Signature-256` with the app
  secret before acting, then drops the raw body.
- **Secrets.** Credentials are sealed (AES-GCM, owner + purpose) and write-only. The webhook
  signing secret is shown once.
- **SSRF.** Outbound webhook URLs are checked when saved and again at every send.
- **Message content.** Messages contain titles, short summaries and links. No documents or
  credentials are ever sent, and chat mentions are disabled (Discord `allowed_mentions: []`).
  Message text is plain or escaped (Telegram HTML), never interpreted.
- **Inbound text is untrusted data.** A reply is stored only as the answer to the question it
  replies to. It is never executed or treated as an instruction.

## 5b. Autopilot (ADR-0014)
- **Off by default.** Submitting without asking needs the consent statement sent back word for
  word. The text and time are stored, revoking clears them, and changes are audited.
- **Decided by plain code.** `domain/policy.py` decides; no model does. A policy approval is
  recorded like a manual one, plus `approval.decided_by_policy` in the audit log.
- **Manual-only sites.** `domain/site_policy.py` covers sites whose terms prohibit automation,
  and pages disallowed by robots.txt. Portals and plain-http pages get a human approval. The
  autopilot opens at most one browser session per site every 10 minutes.
- **Never guesses.** Unknown answers and placeholders are asked. CAPTCHAs and sign-ins are
  handed over (assisted mode). NexScout never clicks submit in assisted mode.
- **Kill switch.** Available in the UI, through the API, and as STOP from a paired chat.

## 5c. Opportunity sources (ADR-0015)
- **Official endpoints only.** Each provider uses an endpoint the publisher offers publicly (an
  ATS job API, a board's API or a feed). Sites whose terms or robots.txt forbid automation are
  **manual only** and are never fetched. NexScout never works around a 403, a CAPTCHA or a
  sign-in.
- **One fetch path.** Every source request goes through `SafeFetcher`: an SSRF check with DNS
  pinning, a private-address block, robots.txt for pages and feeds, per-host pacing, size caps
  and an honest user agent. Each search has a request budget and page and posting caps.
- **Custom URLs are untrusted.** A URL is checked for scheme and host before it is stored, and
  checked again when it is fetched. Detection reads pages as data, and posting text is never
  treated as instructions (§3).
- **Ownership.** Custom sources are owned and protected by RLS. The IDOR sweep covers
  `/sources/{key}`, `/sources/{key}/test` and the import route.

## 5d. Updates (ADR-0017)
- Updates come only from this repository's GitHub releases over https. The desktop app checks
  the sha512 in `latest.yml`. "Update NexScout" refuses a bundle that doesn't match the
  release's `SHA256SUMS.txt`. Downgrades and prereleases are refused.
- The version check sends nothing about the user. Its answer is untrusted: only a
  version-shaped tag and a URL inside this repository are used. Signed-in users only, so
  anonymous requests can't make the server call out. Off with `NEXSCOUT_UPDATE_CHECK=0`.
- Image cleanup removes only `ghcr.io/*/nexscout-(backend|web)` images of other versions.
- Still open: code signing, and protecting releases (a compromised `main` could ship an update).

## 6. Supply chain
Locked dependencies (`uv.lock`, `package-lock.json`). `pip-audit` and `npm audit` in CI. Secret scanning
(detect-secrets) in CI. Development MCP servers are pinned and separate from runtime tools.

## 7. Reporting
Security issues: open a private advisory. Never commit real personal data in fixtures. Use
synthetic personas only.
