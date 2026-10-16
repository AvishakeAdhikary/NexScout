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
| SSRF / metadata access | Safe fetcher: http/https only, DNS resolution with blocking of private, loopback, link-local, CGNAT, metadata (169.254.169.254, fd00:ec2::254) and IPv6 ULA ranges. Re-check on each redirect (max 5). Size and time caps | `tests/security/test_ssrf.py` |
| Malicious uploads / path traversal | Size cap, magic-byte allowlist (pdf, docx, md/txt), content-addressed names, parse in the worker with time and memory limits, no macros executed | upload fuzz tests |
| Secrets leakage to LLM/logs | Secrets only via `secret_ref` resolved at the adapter edge. structlog redaction of keys/tokens/cookies/passwords. Prompts and documents are not logged by default | log-redaction test |
| Unapproved external action | `approval_requests` enforced in deterministic code before submit, send, pay or attest. Idempotency keys | system test: graph halts at the gate |
| Duplicate submission after crash | Idempotency key + `submitting` state + reconciliation → `submission_uncertain` | recovery test |
| Infinite agent loops / resource exhaustion | Per-run step budget, token budget, wall-clock timeout, per-user concurrency quota | runtime unit tests |
| Command injection | No shell calls with model or user input. Subprocesses take argv lists only | code review rule |
| Discriminatory matching | Protected attributes excluded from scoring by construction (they never enter the matcher input type) | unit test on the matcher input schema |
| Stale/incorrect research | Provenance, retrieval time, confidence. Official sources outrank others | research unit tests |

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

## 6. Supply chain
Locked dependencies (`uv.lock`, `package-lock.json`). `pip-audit` and `npm audit` in CI. Secret scanning
(detect-secrets) in CI. Development MCP servers are pinned and separate from runtime tools.

## 7. Reporting
Security issues: open a private advisory. Never commit real personal data in fixtures. Use
synthetic personas only.
