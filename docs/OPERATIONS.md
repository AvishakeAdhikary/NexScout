# NexScout Operations

> Status: complete for M10. Procedures marked *tested* were run on the dev host; see the evidence in ROADMAP.md.

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

## Deploy / upgrade
1. Back up (below). 2. Run `nexscout migrate` with the owner role (Alembic + LangGraph checkpoint
tables). 3. Roll the api, then the workers. Workers drain: they stop claiming, then finish or
release their leases within `NEXSCOUT_WORKER_SHUTDOWN_GRACE_S`.

Migrations are tested from base to head with data written at the first revisions
(`tests/integration/test_migration_upgrade.py`), and downgrade to base works.

## Backup and restore (tested)
```bash
cd backend
uv run python ../scripts/backup.py                     # backups/<UTC stamp>/{db.dump,storage.tar.gz,manifest.json}
uv run python ../scripts/restore.py ../backups/<stamp> --db nexscout_restore_check --drop-after
```
- The backup runs `pg_dump -Fc` inside the compose Postgres container, plus a tar of the object
  store. The manifest records the row count of every table and the SHA-256 of every file.
- The restore goes into a **separate** database: it refuses to overwrite `nexscout` unless
  `--i-know-this-replaces-live-data` is given. The archive is extracted with Python's `data`
  filter (no absolute or `..` paths, no links). Every row count and file hash is then verified.
- Tested 2026-10-17: 45 tables and 9,965 rows matched, and 149 of 149 files matched their hashes.
- Backups contain personal data. `backups/` is ignored by git; store copies encrypted, with
  access control. Also back up the master key (env or secret manager; desktop:
  `master.key.enc`): without it, saved provider API keys can't be decrypted. Nothing else
  depends on it.

## Retention (enforced by the worker's maintenance sweep, tested)
- workflow_events: 90 days.
- Read notifications: 90 days.
- login_attempts: 30 days.
- Sessions: 30 days after expiry.
- audit_events: 365 days.

The worker's system role has delete-only grants for exactly these tables (migration 0009).
Profiles, documents, applications and runs are kept until the user deletes them or their
account. Debug captures don't exist (there are no screenshots of third-party pages beyond the
application form screenshots the user sees).

## Observability
JSON logs to stdout (structlog) with request_id, user_id (opaque), run_id and task_id; secrets are
redacted. Per-user health is under Settings → Diagnostics (worker liveness, own queue, recent
failures, provider checks). Token usage and cost are recorded per call in `usage_records`. There is
no Prometheus/OpenTelemetry exporter yet (see KNOWN_LIMITATIONS).

## Capacity (measured on the dev laptop, not a benchmark)
These are in-process API plus one worker with concurrency 4, against Docker Postgres:
| Users | Runs | API phase | Worker phase | Throughput | Memory |
|---|---|---|---|---|---|
| 12 | 36 | 2.5 s | 7.6 s | 4.8 runs/s | +41 MB |
| 40 | 120 | 7.0 s | 26.5 s | 4.5 runs/s | +57 MB |

Each user's runs were reading a CV, a search, and an assembled CV with PDF and DOCX. All runs
succeeded with no duplicates and no cross-tenant rows. Scale by adding worker processes: claims
use SKIP LOCKED.

## Distribution assessment
- **Server:** Docker images (api and worker share one image with Chromium, about 2.1 GB; web)
  plus managed Postgres. This is the recommended multi-user deployment.
- **Desktop:** an Electron shell. The Windows NSIS installer was built and is unsigned; the macOS
  and Linux configs exist but weren't built. Local mode needs a NexScout checkout, Postgres, uv
  and Node.
- **Not promised:** a single self-contained executable. Bundling Python, Node, Chromium and
  Postgres into one installer is possible (embedded Postgres, a PyInstaller backend, a Next
  standalone build) but isn't built or tested. It would also need its own update and migration
  story.

## Incident: stuck workflows
Check `worker_heartbeats` to see whether any worker is alive. Then check `tasks` with
`status='running' AND lease_expires_at < now()`. The reaper re-queues these. When a run failed with
"Internal error in the worker.", the traceback is in the worker log (`task_crashed`). Users can
retry from Agent Activity. There is no admin CLI. Use SQL against these tables with the owner
role and keep an audit note.
