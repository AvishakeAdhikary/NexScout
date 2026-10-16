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
| E2E in CI | No CI job for Playwright yet | Add job with Postgres service + `npx playwright install --with-deps chromium` |
