# NexScout Operations

> Status: skeleton written in M0. Sections marked ⬜ are completed and **tested** in M10.

## Health
- `GET /healthz`: process liveness (no dependencies).
- `GET /readyz`: DB reachable and migrations at head. The worker reports through a heartbeat row.

## Configuration and secrets
All config is via `NEXSCOUT_*` env vars (see `.env.example`). Required in production:
`NEXSCOUT_DATABASE_URL` (app role), `NEXSCOUT_MIGRATION_DATABASE_URL` (owner role),
`NEXSCOUT_SYSTEM_DATABASE_URL` (worker role `nexscout_system`, BYPASSRLS, used for queue claiming
and checkpoints across tenants; give it to the worker only, never the api),
`NEXSCOUT_MASTER_KEY` (32-byte base64, from a secret manager), `NEXSCOUT_ENV=production`
(enables Secure cookies, disables debug, refuses to start without a master key), and
`NEXSCOUT_STORAGE_DIR` or object-store settings. Set `NEXSCOUT_ALLOW_PRIVATE_PROVIDER_URLS=false`
on shared servers so that user-supplied model URLs can't reach internal services.

**Dev master key:** without `NEXSCOUT_MASTER_KEY`, a key is generated at
`<storage_dir>/../master.key` (mode 600). The api and the worker must see the *same* file. In
compose, both mount the `appdata` volume at `/data` (verified: one key file, visible to both).
Losing the key makes saved API keys unreadable, so users must re-enter them. Nothing else is affected.

## Processes
| Process | Command | Scale |
|---|---|---|
| api | `nexscout migrate && nexscout serve` | stateless, any number |
| worker | `nexscout worker` | any number (SKIP LOCKED); `NEXSCOUT_WORKER_CONCURRENCY` per process |
| web | Next.js server | stateless |

On SIGTERM/SIGINT the worker stops claiming and lets in-flight steps finish within
`NEXSCOUT_WORKER_SHUTDOWN_GRACE_S` (30 s). It then releases its leases. Verified in compose: an
idle worker stopped in 1.6 s. Give the container a longer stop timeout than the grace period (compose: 40 s).
If a reverse proxy sits in front, don't compress `text/event-stream`. The SSE endpoint sends
`Cache-Control: no-transform`; a proxy that ignores it buffers live updates.

## Desktop (apps/desktop)
- `npm run dist` builds the platform installer into `apps/desktop/release/` (Windows NSIS was
  built and smoke-tested; it is unsigned).
- Local mode starts api, worker and web from a NexScout checkout and stores logs in
  `<userData>/logs`. The master key is encrypted with the OS keychain (`master.key.enc`).
  Deleting it makes saved provider API keys unreadable.
- To reset the app's mode, delete `<userData>/config.json`.

## Deploy / upgrade ⬜
1. Back up (below). 2. Run `nexscout migrate` with the owner role (Alembic + LangGraph checkpoint
tables). 3. Roll the api, then the workers. Workers drain: they stop claiming, then finish or
release their leases within `NEXSCOUT_WORKER_SHUTDOWN_GRACE_S`.

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
Check `worker_heartbeats` to see whether any worker is alive. Then check `tasks` with
`status='running' AND lease_expires_at < now()`. The reaper re-queues these. When a run failed with
"Internal error in the worker.", the traceback is in the worker log (`task_crashed`). Users can
retry from Agent Activity. Admin script ⬜.
