# NexScout Data Model

PostgreSQL 17. Migrations: Alembic (`backend/alembic/versions`). Ownership and RLS: ADR-0003.

## Conventions
- PK `id uuid` (generated in the app, UUIDv7-style ordering). `created_at`, `updated_at timestamptz`.
- Mutable aggregates carry `version int` (optimistic concurrency. Updates use `WHERE version = :v`).
- Owned tables: `owner_user_id` (+ `case_id` when case-scoped), RLS enabled and forced.
- Enums are Postgres `text` + CHECK constraint (easier to migrate than native enums).
- JSONB only for genuinely flexible metadata (`meta`, raw source payloads). Never for anything we query or filter on.

## Entities by milestone
Status: ✅ implemented and verified against Postgres · 🟨 implemented (migration 0001), not yet run against Postgres · ⬜ planned. **This table is updated as migrations land.**

### M1 Identity and cases
| Table | Key columns | Notes |
|---|---|---|
| ✅ users | email (unique, citext-normalized lowercase), password_hash, display_name, is_active | not RLS (auth lookup), accessed only by auth use cases |
| ✅ sessions | user_id, token_hash (unique), csrf_hash, expires_at, idle_expires_at, revoked_at, ip, user_agent | |
| ✅ candidate_cases | owner_user_id, name, description, career_path (`undecided/phd/employment/both`), status (`active/paused/archived`), version | unique (owner_user_id, name). Unique (id, owner_user_id) for composite FKs |
| ✅ login_attempts | email_hash (sha256), ip, succeeded, created_at | DB-backed login rate limiting (works across API replicas). App role: SELECT, INSERT, DELETE |
| ✅ audit_events | actor_user_id, action, target_type, target_id, meta, ip, created_at | append-only |

### M2 Profile and documents
| Table | Notes |
|---|---|
| ✅ documents | owner, case, kind (cv, transcript, sop, …), filename, mime, size, sha256, storage_key, origin (`uploaded/generated`), parse_status |
| ✅ profile_facts | owner, case, section (education, employment, research, publication, project, skill, certification, award, patent, volunteer, leadership, affiliation, reference, summary, other), `data jsonb` validated per section by a Pydantic schema, `status` (user_entered/extracted/inferred/verified/external), `review_state` (pending/accepted/rejected), `is_private`, superseded_by, version |
| ✅ fact_evidence | fact_id, document_id?, url?, page, char_start, char_end, excerpt, method (`upload_extraction/user_entry/url_import`) |
| ✅ profile_snapshots | case, number, created_at, `facts jsonb` (frozen accepted facts), reason |
| ✅ case_preferences | case (1:1), structured columns for regions, remote, seniority, experience mode, salary, plus `sensitive jsonb` (private, excluded from matching unless the user explicitly marks a field as an eligibility rule) |
| ✅ social_profiles | case, kind (linkedin, github, scholar, orcid, researchgate, website, other), url (validated), verified |
| ✅ affiliations | case, person_name, organization, relationship_type, role, start/end, status, evidence, notes, may_use_in_applications, may_use_for_referral |

### M3 Mind map and opportunities (✅ migration 0003)
Implemented as: `mindmap_overrides`, `organizations`, `opportunities` (normalized payload in `data` JSONB plus indexed identity columns), `opportunity_sources` (per listing: content hash, dedup score and reasons), `source_configs`, `sync_checkpoints` (resumable cursor, last result), `opportunity_matches` (score, eligible, factors, gaps, status, version), `dedup_reports`. System merge decisions live on `opportunity_sources`, and user reports in `dedup_reports`.

⬜ mindmap_overrides (case, node_key, position, hidden, label_override) · ⬜ organizations (kind institution/employer, canonical_name, domain, aliases) · ⬜ opportunities (kind phd/job/research/scholarship, organization_id, title, normalized_title, location fields, seniority, experience_min/max, salary, posted_at, closes_at, canonical_url, requisition_id, description, application_method, fingerprint, last_checked_at) · ⬜ opportunity_sources (opportunity_id, source_key, source_url, external_id, raw jsonb, retrieved_at) · ⬜ source_configs (owner, adapter_key, enabled, settings) · ⬜ sync_checkpoints (owner, adapter_key, query_hash, cursor, last_run_at) · ⬜ dedup_decisions (a, b, decision merge/distinct, method, score, decided_by user/system) · ⬜ opportunity_matches (case, opportunity, score, factors jsonb, gaps jsonb, mode)

Opportunities discovered from public sources are **shared catalog data** (not owned). Per-user state
(shortlist, match, dismissal) lives in owned tables. User-configured private sources produce owned
opportunity links.

### M4 Runtime
⬜ workflow_runs (owner, case, kind, status, control_request, params, result, error, step_budget, token_budget, version) · ⬜ tasks (run, key, status, idempotency_key, lease_owner, lease_expires_at, attempt, max_attempts, next_attempt_at, priority, input, output, error) · ⬜ task_attempts · ⬜ workflow_events (run, seq, type, payload) · ⬜ approval_requests (run, task, action_kind, summary, payload, status pending/approved/rejected/expired, decided_at, decided_by) · ⬜ tool_executions · ⬜ usage_records · LangGraph checkpoint tables (managed by `langgraph-checkpoint-postgres` setup)

### M5–M8
✅ (M5, migration 0005, all owned + RLS) research_sources (case, opportunity, url, origin listing/demo/web, status, text, links, content_hash, retrieved_at) · research_findings (source, kind deadline/degree/language_test/document_required/funding/supervisor/other, field, summary, verbatim quote, value, confidence, method `rules_v1`, status current/conflict, note). Supervisors are findings of kind `supervisor`, not a separate faculty table · generated_documents (case, opportunity, doc_type, title, current_version, created_by_run_id unique, version) + generated_document_versions (number, markdown, origin generated/assembled/user_edit, report, placeholders, artifacts {pdf, docx: key, sha256, size, checks}, model, is_mock) · ✅ (M7, migration 0006, owned + RLS) applications (case, opportunity, title, organization, status per APPLICATION_MACHINE, apply_url, method, document_ids, answers, phone, deadline, notes, blocker, submitted_at, evidence {source observed/user/none, reference, url, excerpt, screenshot_key}, version) + application_events (identity `seq` for ordering, type, from/to status, actor user/agent/system, message, payload, run_id) · ✅ (M8, migration 0007, owned + RLS) reminders (case, application, kind deadline/follow_up/custom, due_on, dedupe_key, done_at, notified_at) · notifications (owner, case, kind, title, body, link, dedupe_key, read_at) · chat_messages (identity seq, role, content, intent, actions) · ⬜ communications (no outbound channel) · ⬜ browser_sessions, credential_refs, secrets · ⬜ provider_configs

### M11 Notification channels (✅ migration 0010, ADR-0013)
- **notification_channels** (owned + RLS): kind (webhook/slack/email/telegram/discord/whatsapp),
  name (unique per owner), status (pending_pairing/active/paused/error), config (non-secret
  settings), secret_id → secrets (sealed JSON, purpose `channel:<kind>`), paired_identity,
  pairing_code_hash and pairing_expires_at, events (filter), quiet_start and quiet_end (HH:MM),
  timezone, consecutive_failures (circuit breaker), last_error, last_delivery_at, poll_offset
  (Telegram), version.
- **notification_deliveries** (owned + RLS; the outbox): notification, channel, status
  (pending/sending/sent/failed/dead/skipped), attempts, next_attempt_at, locked_until (lease),
  last_error, provider_message_id (used to match replies), sent_at. Unique per
  (notification, channel).
- **channel_actions** (owned + RLS): a short random id carried by a button; channel,
  notification, action (approve/reject/answer), target, expires_at, used_at, result.
- **channel_inbound_events** (no owner; app role may INSERT only): primary key
  (channel_id, provider_event_id) for idempotency, payload, raw_body (dropped after
  verification), signature, status (received/processed/rejected/ignored), note.
- **notifications.data** (JSONB): structured context such as approval_id, application_id or the
  question.

### M12 Autopilot (✅ migration 0011, ADR-0014; all owned + RLS)
- **autopilot_policies** (one per case): enabled, interval_hours, next/last run, steps (discover,
  research, documents, fill, submit), min_fit, max_new_per_run, daily_submit_cap, per_org_cap,
  countries, kinds, exclude_orgs, doc_types, auto_submit, declarations, consent_text +
  consented_at (verbatim statement), stopped_reason, version.
- **autopilot_items** (one per case × opportunity): stage (queued → researching → drafting →
  rendering → needs_input → applying → waiting_approval/needs_user_action → submitted, or
  manual/skipped/failed/stopped), reason, application_id, child_run_ids, document_ids, attempts,
  fit, title, organization.
- **case_answers**: question_key (normalized), question, answer (the user's own words), source
  (`user`, `app`, `chat:<channel>`). Unique per (case, question_key).
- The worker's system role may only SELECT policies and items to find work; all changes are made
  in the owner's tenant session.

### M15 Real sources, countries, budget (✅ migrations 0012–0013, ADR-0015/0016)
- **custom_sources** (owned + RLS): key (`custom:<provider>:<slug>`), provider, name, url,
  config JSONB (provider settings such as slug or feed URL), countries, kinds, created_at.
  Unique per (owner, key). At most 300 per user.
- **source_configs** gains health: last_status (`ok`/`error`), last_error (user-safe text),
  last_count, last_fetched_at.
- **fx_rates** (catalog, no owner): currency (PK), per_eur, as_of. ECB daily reference rates
  written by the worker's system role; the app role may only read them.
- **autopilot_policies** gains countries_exclude (JSONB, ISO codes or group keys).
- **users** gains timezone (IANA name reported by the browser at sign-in, default UTC). The
  worker's system role may read only `users(id, timezone)`, so date-only reminders fall due on
  the user's own calendar day.
- **provider_configs** gains `skip_thinking` (migration 0014): OpenAI-compatible reasoning models
  are asked to answer without thinking (`chat_template_kwargs.enable_thinking=false`).
- Preferences (`case_preferences` JSON) gain countries_exclude, funding
  (`required`/`preferred`/`any`), languages (ISO 639-1), max_upfront_cost and budget_currency,
  search_keywords and exclude_keywords. Countries are stored as ISO 3166-1 alpha-2 codes or
  group keys (`EU`, `NORDICS`, …).
- The opportunity payload (`opportunities.data`) gains country_codes, location_text and
  remote_scope.

## Migration policy
- Forward-only in production. Each revision is tested by upgrading from the previous head with
  representative data (`tests/integration/test_migrations.py`).
- Backups are taken before upgrades (see OPERATIONS.md).
