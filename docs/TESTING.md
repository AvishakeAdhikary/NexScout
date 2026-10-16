# NexScout Testing

## Layers
| Suite | Location | Needs | Runs in CI |
|---|---|---|---|
| Unit (domain, pure) | `backend/tests/unit` | nothing | yes |
| Integration (DB, API, adapters) | `backend/tests/integration` | Postgres | yes (service container) |
| System (workflows, recovery, isolation) | `backend/tests/system` | Postgres + worker in-process | yes |
| Security (IDOR sweep, SSRF, uploads, injection) | `backend/tests/security` | Postgres | yes |
| Web unit | `apps/web/**/*.test.ts(x)` | nothing | yes |
| E2E | `tests/e2e` (Playwright Test) | full stack, mock providers | yes |
| Live | `-m live` | real keys, network | **opt-in only** |

## Commands
```
cd backend
uv run pytest tests/unit                 # fast, no DB
uv run pytest                            # all except live (needs NEXSCOUT_TEST_DATABASE_URL)
uv run pytest -m live                    # opt-in live provider/source checks
cd apps/web && npm test
npx playwright test                      # from repo root, stack must be running
```

## Database tests
Tests use a dedicated database (`nexscout_test`) created by the test session, migrated with Alembic
to head, with the RLS app role. Each test runs in an isolated transaction or truncates owned tables.

## Rules
- Deterministic fixtures: synthetic personas only (`tests/fixtures/personas/`). Never real people.
- Mock providers and fixture sources are the default and are labelled as such.
- Every owned resource gets a cross-tenant test. Every bug fix gets a regression test.
- Results are recorded honestly in the ROADMAP test evidence log.
