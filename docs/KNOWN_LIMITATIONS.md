# NexScout Known Limitations

Kept current. Anything not listed as verified here should be assumed **not** to work.

## Environment
- Docker was **not installed** on the primary dev host as of 2026-10-16. DB-backed tests (23) can't run
  until Docker Desktop (or another Postgres 17) is available.

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
| Provider | Adapter | Live-verified |
|---|---|---|
| Mock | ⬜ | n/a (deterministic, labelled mock) |
| OpenAI-compatible (OpenAI/Ollama/LM Studio) | ⬜ | no |
| Anthropic | ⬜ | no |
| Gemini | ⬜ | no |

## Functional gaps
Everything after the current milestone in ROADMAP.md is not built yet. UI sections for later
milestones show an explicit "not available yet" state.

## Unverified artifacts (exist but have not been executed)
| Artifact | Why unverified | Verify by |
|---|---|---|
| `docker/backend.Dockerfile`, `docker/web.Dockerfile`, compose `full` profile | No Docker on dev host | `docker compose --profile full up --build` then `/readyz` |
| `.github/workflows/ci.yml` | Not pushed to GitHub (no remote) | First push/PR |
| Alembic `0001` against real Postgres, RLS policies, all API integration tests | No Postgres | `docker compose up -d postgres && cd backend && uv run nexscout migrate && uv run pytest` |
| Web login/register/case flows end to end | Need API + DB | Manual browser run, then Playwright e2e (M2) |
