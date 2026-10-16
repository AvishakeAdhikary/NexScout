# NexScout Operations

> Status: skeleton written in M0. Sections marked ⬜ are completed and **tested** in M10.

## Health
- `GET /healthz`: process liveness (no dependencies).
- `GET /readyz`: DB reachable and migrations at head. The worker reports through a heartbeat row.

## Configuration and secrets
All config is via `NEXSCOUT_*` env vars (see `.env.example`). Required in production:
`NEXSCOUT_DATABASE_URL` (app role), `NEXSCOUT_MIGRATION_DATABASE_URL` (owner role),
`NEXSCOUT_MASTER_KEY` (32-byte base64, from a secret manager), `NEXSCOUT_ENV=production`
(enables Secure cookies, disables debug), `NEXSCOUT_STORAGE_DIR` or object-store settings.

## Deploy / upgrade ⬜
1. Back up (below). 2. `alembic upgrade head` with the owner role. 3. Roll the api, then the workers. Workers
drain: stop claiming, finish or release leases within `NEXSCOUT_SHUTDOWN_GRACE_S`.

## Backup and restore ⬜
`scripts/backup.sh`: `pg_dump -Fc` + storage-directory archive, timestamped. `scripts/restore.sh`:
`pg_restore` into a fresh DB + restore storage. Restores are tested in M10 (`tests/system/test_backup_restore`).

## Retention defaults
workflow_events 90 d · task_attempts 90 d · audit_events 1 y · expired sessions 30 d after expiry ·
debug captures off by default (7 d when enabled).

## Observability
JSON logs to stdout (structlog) with request_id, user_id (opaque), run_id and task_id. Metrics ⬜ (M10:
queue depth, task latency, failure rate, LLM tokens and cost, cancellation latency).

## Incident: stuck workflows
Check `tasks` with `status='running' AND lease_expires_at < now()`. The reaper should re-queue them.
Inspect `task_attempts.error`. Use the UI "retry step" or `scripts/admin` ⬜.
