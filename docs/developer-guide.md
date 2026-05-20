# Developer guide

## Quickstart

```bash
git clone <repo>
cd nexscout
python3.11 -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\Activate.ps1
pip install -e ".[dev,web]"
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex

# Required environment
export CAPTCHA_API_KEY=...
export GEMINI_API_KEY=...   # or OPENAI_API_KEY / ANTHROPIC_API_KEY

# One-time profile setup
nexscout init               # YAML wizard fills ~/.nexscout/profile.yaml
nexscout doctor             # T1/T2/T3 readiness report

# Smoke test
nexscout run discover       # discover only
nexscout run                # full pipeline
nexscout web &              # http://127.0.0.1:8765
nexscout apply --workers 2  # submit applications
```

## Repository layout

See `docs/architecture.md` for the high-level pipeline map. Key directories:

- `src/nexscout/` — the package itself.
- `tests/unit/` — fast, hermetic unit tests. Run with `pytest -q`.
- `tests/integration/` — slower tests that touch real subprocesses / DB.
- `examples/profile.example.yaml` — copy this to `~/.nexscout/profile.yaml`.
- `docs/` — this directory.
- `Dockerfile`, `docker-compose.yml` — container packaging (M10).
- `.github/workflows/ci.yml` — Ruff, mypy, pytest matrix.

## Running tests

```bash
pytest -q                                          # all tests
pytest -q tests/unit/test_scorer.py                # single file
pytest -q --cov=src/nexscout --cov-report=term-missing
ruff check src/ tests/
mypy src/nexscout/core src/nexscout/llm src/nexscout/scoring \
     src/nexscout/captcha src/nexscout/apply/orchestrator.py \
     src/nexscout/apply/agent.py
```

## Coverage targets (§23)

| Subpackage             | Threshold |
|------------------------|-----------|
| `core/`                | 90 %      |
| `llm/`                 | 80 %      |
| `scoring/`             | 80 %      |
| `captcha/`             | 70 %      |
| `apply/orchestrator.py`| 80 %      |

## Adding a new discovery source

Every discovery engine is a single file under
`src/nexscout/discovery/`. The contract is dead-simple: a function (or class
with one `run()` method) that:

1. Reads the active `Profile` (for queries / locations / rate limits).
2. Crawls or queries its source.
3. Builds a list of dicts with these keys:
   `url, title, salary, description, location, site, strategy,
    discovered_at, web_search_query`.
4. Calls `database.insert_jobs(rows)` which de-duplicates by URL and returns
   `(new_count, duplicate_count)`.

A minimal example:

```python
# src/nexscout/discovery/myboard.py
from datetime import UTC, datetime
from ..core.database import insert_jobs
from ..core.profile import Profile

def discover(profile: Profile) -> tuple[int, int]:
    rows = []
    for query in profile.search.queries:
        # ...your scrape logic...
        rows.append({
            "url":            "https://example.com/job/42",
            "title":          "Senior Backend Engineer",
            "salary":         "$150k-$180k",
            "description":    "Optional preview snippet",
            "location":       "Remote US",
            "site":           "MyBoard",
            "strategy":       "myboard_api",
            "discovered_at":  datetime.now(UTC).isoformat(),
            "web_search_query": None,
        })
    return insert_jobs(rows)
```

Then wire it into the pipeline by adding it to the `_DISCOVERY_ENGINES` list
in `src/nexscout/pipeline.py`:

```python
from .discovery import myboard

_DISCOVERY_ENGINES = [
    jobspy.discover,
    workday.discover,
    smartextract.discover,
    websearch.discover,
    myboard.discover,           # <-- new
]
```

If your source needs a registry file (e.g. a list of tenants), drop the
YAML next to the engine — `discovery/employers.yaml` (§21) and
`discovery/sites.yaml` (§22) are good models.

## Adding a new LLM provider

1. Add a subclass of `Provider` in `src/nexscout/llm/providers/`.
2. Implement `chat(messages, temperature, max_tokens) -> str`.
3. Register the provider name in `llm/router.py`'s `_PROVIDER_REGISTRY`.
4. Add provider-specific fields to `Profile.llm` if you need them.
5. Add unit tests that mock the HTTP layer (see `tests/unit/test_router.py`).

## Prompt edits are verbatim-controlled

Six prompts are pinned **byte-equal** to `plan.md`:

- §8.3 SmartExtract — judge, strategy, selector
- §9 Enrichment — Tier 3 LLM
- §10 Scorer
- §11 Tailor
- §12.2 Cover letter
- §13.4 Apply agent

`tests/unit/test_prompts_verbatim.py` slices `plan.md` and compares against
the constants in the source. If you edit a prompt, the plan and the code
must move together — the test will scream otherwise. **Verbatim means
verbatim.**

## Pre-commit

```bash
pre-commit install
pre-commit run --all-files
```

Hooks: `ruff`, `ruff-format`, `mypy`, `end-of-file-fixer`,
`trailing-whitespace`, `check-merge-conflict`, `check-yaml`, `check-toml`.

## Release

Releases are tagged with `v<major>.<minor>.<patch>`. Update `CHANGELOG.md`
under a new `[<version>] — <date>` heading, then:

```bash
git tag -a v0.1.0 -m "v0.1.0"
git push --tags
```

CI publishes the wheel to PyPI on tag push (configure
`.github/workflows/release.yml` separately).
