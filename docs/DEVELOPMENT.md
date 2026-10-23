# NexScout Development

## Prerequisites
| Tool | Version | Notes |
|---|---|---|
| uv | ≥ 0.12 | Installs and pins Python **3.13**. The host Python is not used |
| Node.js | ≥ 22 (dev host: 26; Docker/CI: 24) | npm ships with Node |
| Docker Desktop | current | Runs PostgreSQL 17 (`docker compose`). On Windows, enable the WSL 2 backend |
| git | any recent | |

## First-time setup
```bash
cp .env.example .env                       # dev-only defaults; never commit .env
uv python install 3.13
docker compose up -d postgres              # creates roles nexscout_owner/nexscout_app and DBs nexscout, nexscout_test
cd backend && uv sync && uv run nexscout migrate   # applies Alembic migrations as the owner role
cd ../apps/web && npm install
```

## Run (three terminals)
```bash
cd backend && uv run nexscout serve --reload        # API  http://127.0.0.1:8000  (docs at /api/docs)
cd backend && uv run nexscout worker                # background worker (uploads, searches, AI drafts)
cd apps/web && npm run dev                          # Web  http://localhost:3000
```
The web app proxies `/api/*` to `NEXSCOUT_API_ORIGIN` (default `http://127.0.0.1:8000`), so the browser
only ever talks to one origin. **Without the worker, uploads stay "Reading…" and searches never
finish**: the API only queues work. Several workers on one database are safe (SKIP LOCKED claims).

After pulling changes, always run `uv run nexscout migrate`. It applies Alembic migrations *and*
creates/upgrades the LangGraph checkpoint tables. The worker refuses to start without them.

Everything in containers: `docker compose --profile full up -d --build` (postgres, api, worker,
web on :3000). The api container runs migrations before it reports healthy; the worker waits for it.

Health: `curl localhost:8000/healthz` (liveness), `curl localhost:8000/readyz` (DB + migrations;
returns 503 within 3 s when the DB is down).

## MCP server (read-only)
Create a token under Account → Access tokens (shown once), then configure your MCP client to
run, for example:
```bash
cd backend && NEXSCOUT_MCP_TOKEN=nxs_... uv run nexscout mcp      # stdio
```
In a client config, pass the token through the client's `env` setting, never as an argument.

## Desktop shell
```bash
cd apps/desktop && npm install
npm test                 # TypeScript build + policy unit tests
npm start                # opens the window (first run: choose remote or local mode)
npm run smoke            # --smoke: load, report what the page can reach, quit
npm run pack | dist      # electron-builder: unpacked app | installer (unsigned)
```
VS Code terminals set `ELECTRON_RUN_AS_NODE=1`, which turns Electron into plain Node. Run with
`env -u ELECTRON_RUN_AS_NODE` (bash) if `ipcMain` is undefined. Local mode logs are under
`%APPDATA%\nexscout-desktop\logs` on Windows.

## End-to-end tests
```bash
cd apps/web && npx playwright install chromium   # once
npm run e2e        # starts `nexscout serve --port 8100`, `nexscout worker` and `next dev -p 3200`
                   # (reuses a running api/web). One Playwright worker: journeys share the dev DB.
```

## Checks
```bash
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                     # DB tests skip with a stated reason if Postgres is down;
NEXSCOUT_REQUIRE_DB=1 uv run pytest   # ...or fail instead (what CI does)
cd apps/web
npm run format                    # Prettier rewrite (config: repo-root .prettierrc.json)
npm run typecheck && npm run lint && npm test && npm run build   # lint = ESLint + prettier --check
cd apps/desktop
npm run format && npm run lint && npm test
```

## API contracts
Backend schemas are the source of truth. After changing an API schema:
```bash
bash scripts/gen-contracts.sh     # writes apps/web/src/lib/api/{openapi.json,schema.d.ts}
```
No database is needed. The script imports the FastAPI app and dumps its OpenAPI document.

## New migration
```bash
cd backend
uv run alembic revision -m "describe change"   # write the upgrade/downgrade by hand
uv run nexscout migrate
```
Owned tables must call `enable_owner_rls()` and `grant_app()` from `nexscout.infrastructure.db.rls`.
`tests/integration/test_health_and_migrations.py::test_models_match_migrations` fails on drift.

## Layout
```
backend/src/nexscout/   api/ application/ domain/ infrastructure/ (+ agent_runtime/ etc. as milestones land)
backend/alembic/        migrations
backend/tests/          unit/ integration/ security/ system/ (runtime, crash recovery, workflows)
apps/web/src/           app/ (routes) components/ lib/ (api client, hooks)
docker/                 Dockerfiles, Postgres init SQL
scripts/                dev scripts
```

## Troubleshooting
- **`psycopg` errors about ProactorEventLoop (Windows):** use `nexscout serve`, which selects the
  Selector loop. Tests do the same via the `pytest_asyncio_loop_factories` hook in `tests/conftest.py`.
- **DB tests are skipped:** Postgres isn't reachable at `NEXSCOUT_TEST_MIGRATION_DATABASE_URL`. Run
  `docker compose up -d postgres` and check `docker compose ps`.
- **Roles or databases missing:** the init SQL only runs on a *fresh* volume:
  `docker compose down -v && docker compose up -d postgres` (this **deletes local dev data**).
- **Next build error "blocking-prerender-client-hook":** client components that read `useParams`,
  `useSearchParams` or `usePathname` must sit inside a `<Suspense>` boundary (Cache Components).
- **Docker installed but `docker` not found:** Docker Desktop adds
  `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin` to the *user* PATH. Restart the terminal or IDE.
- **Worker crashes with `relation "checkpoints" does not exist` / refuses to start:** run
  `uv run nexscout migrate` (it also sets up the checkpoint tables).
- **Agent Activity says "reconnecting" or live updates lag behind a proxy:** the event stream
  is sent with `Cache-Control: no-transform`. A proxy that compresses `text/event-stream` anyway
  buffers it. Turn compression off for `/api/v1/cases/*/events`.
- **Slow DB connections on Windows:** use `127.0.0.1` rather than `localhost` in URLs (see TESTING.md).
- **Port 5432 in use:** set `NEXSCOUT_PG_PORT` and update the URLs in `.env`.
