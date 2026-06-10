# Developer guide

## Quickstart

Install dependencies with **either** pip or uv. CI now runs on uv; both
paths are fully supported locally.

```bash
git clone <repo>
cd nexscout

# --- pip path ---
python3.11 -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\Activate.ps1
pip install -e ".[dev,web]"
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex

# --- uv path (what CI runs) ---
uv sync --extra dev --extra web                         # provisions the venv + deps
# then prefix the commands below with `uv run`, e.g. `uv run nexscout doctor`

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

> The fastest path for a fresh machine is `scripts/` (see
> [scripts/README.md](../scripts/README.md)): cross-platform launchers for the
> direct/uv/docker run methods plus an interactive config generator.

## Repository layout

See `docs/architecture.md` for the high-level pipeline map. Key directories:

- `src/nexscout/` — the package itself.
- `tests/unit/` — fast, hermetic unit tests. Run with `pytest -q`.
- `tests/integration/` — slower tests that touch real subprocesses / DB.
- `examples/split/{profile,settings,credentials}.yaml` — three-file split
  reference; `cp examples/split/*.yaml ~/.nexscout/`. (Also loaded as a test
  fixture via `Profile.from_path(examples/split/profile.yaml)`, which
  deep-merges the sibling `settings.yaml`/`credentials.yaml` — keep the set
  valid and consistent.)
- `scripts/` — cross-platform launchers + interactive config generator
  (see `scripts/README.md`).
- `docs/` — this directory.
- `Dockerfile`, `docker-compose.yml` — container packaging (M10).
- `.github/workflows/ci.yml` — uv-based Ruff, mypy, pytest matrix.

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

## Coverage targets

Every module under `src/nexscout/` reaches **≥80 %** line coverage; the
project-wide total sits at **93 %** as of v0.1.0 (835 tests). The plan.md
§23 minimums are floors, not ceilings:

| Subpackage             | §23 floor | Observed |
|------------------------|-----------|----------|
| `core/`                | 90 %      | 95 %     |
| `llm/`                 | 80 %      | 95 %     |
| `scoring/`             | 80 %      | 91 %     |
| `captcha/`             | 70 %      | 98 %     |
| `apply/orchestrator.py`| 80 %      | 93 %     |
| `discovery/`           | —         | 92 %     |
| `enrichment/`          | —         | 88 %     |
| `web/`                 | —         | 98 %     |
| `apply/` (rest)        | —         | 93 %     |
| `browser/`             | —         | 97 %     |
| `cli.py`               | —         | 92 %     |

CI gates on the project-wide 80 % floor and the per-module 80 % floor —
new code that drops a module below 80 % fails CI.

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

Then wire it into the pipeline. `src/nexscout/pipeline.py`'s
`run_discover_stage` lazy-imports each engine module under its own
`try/except ImportError` block and calls its module-level entrypoint
(`run_jobspy`, `run_workday`, `run_websearch`, `run_smartextract`). To add
your engine, expose a `run_myboard(profile, *, conn) -> tuple[int, int]`
function and add a matching block to `run_discover_stage`:

```python
# inside run_discover_stage()
try:
    from .discovery import myboard as _myboard_mod
except ImportError:
    log.info("discovery.myboard unavailable; skipping")
else:
    try:
        new, _dup = _myboard_mod.run_myboard(profile, conn=conn)
        total += int(new)
    except Exception as e:
        log.warning("myboard engine failed: %s", e)
```

Engines that need the LLM router (e.g. for AI-driven scraping like
SmartExtract) should gate themselves on `router is not None` — the
heartbeat tick may pass `router=None` when the user's budget is exhausted.

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

### Adding a new prompt to the verbatim audit

Two test files cover the audit:

* `tests/unit/test_prompts_verbatim.py` — **strict** 1:1 placeholder mapping.
  It walks the plan placeholders and the code placeholders in order, mapping
  each plan name to its documented code name via a per-prompt mapping table,
  then asserts the surrounding text is byte-identical.
* `tests/unit/test_prompts_verbatim_loose.py` — kept for diagnostic use. It
  strips every `{...}` block before comparing; useful when the strict
  version trips on a positional asymmetry and you want to confirm only the
  surrounding text drifted.

To add a new prompt:

1. Add a section in `plan.md` containing a fenced block with the verbatim
   prompt text. The block must use the standard `{placeholder_name}` syntax
   for any substitution points.
2. Define the constant in the source module (e.g. `MY_PROMPT_TEMPLATE`),
   using Python `{code_placeholder_name}` placeholders. If the placeholder
   has the same name as in the plan, no mapping entry is needed; just
   include it in the mapping table as identity.
3. In the strict test file, add a mapping table for the new prompt:

   ```python
   MY_PROMPT_MAPPING: dict[str, str] = {
       "{plan_placeholder_name}": "{code_placeholder_name}",
       # …
   }
   ```

   Use a `list[tuple[str, str]]` *positional* mapping when the same plan
   placeholder must map differently at different positions (rare — §13.4's
   `{city}` is the only current example, because it appears once nested in
   a cover-letter fallback literal and once verbatim in the profile block).
4. Add a `test_my_prompt_strict` function that calls
   `_walk_placeholders_in_order_match(...)` then `_strict_equal(...)`.
5. Mirror a loose test in `test_prompts_verbatim_loose.py` for diagnostic
   parity.

#### Documented per-prompt mappings (current as of v0.1.0)

| Prompt          | Notable plan → code rewrites |
|-----------------|------------------------------|
| §8.3 judge      | identity (`{url}`, `{status}`, …) |
| §8.3 strategy   | identity (`{briefing}`) |
| §8.3 selector   | identity (`{page_html}`) |
| §9 enrichment   | identity (`{url}`, `{title}`, `{content}`) |
| §10 scorer      | no placeholders |
| §11 tailor      | `{profile.skills.lang \| join}` → `{languages}`; same for fw/infra/data/tools; `{BANNED_WORDS \| join}` → `{banned_words}`; `{profile.facts.metrics \| join}` → `{metrics}`; `{profile.facts.companies \| join}` → `{companies}`; `{profile.facts.school}` → `{school}`; `{profile.exp.edu}` → `{education}`. |
| §12.2 cover     | `{profile.me.pref}` → `{pref}`; `{profile.facts.projects \| join}` → `{projects}`; `{profile.facts.metrics \| join}` → `{metrics}`; `{BANNED_WORDS \| join}` → `{banned_words}`; `{LLM_LEAK_PHRASES \| join}` → `{leak_phrases}`; `{all_skills \| join}` → `{all_skills}`. |
| §13.4 apply     | positional. `{application_url or url}` → `{job_url}`; `{me.legal}` → `{legal_name}`; `{me.email}` → `{email}`; `{me.phone}` → `{phone}`; `{links.li}` → `{linkedin}`; `{links.gh}` → `{github}`; `{links.portfolio}` → `{portfolio}`; `{links.web}` → `{website}`; `{auth.authorized}` → `{work_auth}`; `{auth.sponsor}` → `{sponsor}`; `{auth.permit}` → `{permit}`; `{pay.expect}` → `{salary_expect}`; `{pay.currency}` → `{currency}`; `{exp.years}` → `{years}`; `{exp.edu}` → `{education}`; `{avail.start}` → `{available}`; `{eeo.gender}` → `{eeo_gender}`; same for race/veteran/disability; `{me.pref}` → `{pref_name}`; `{pay.range[0]}` → `{salary_low}`; `{pay.range[1]}` → `{salary_high}`; `{profile.password}` → `{password}`; `{digits_only(phone)}` → `{phone_digits}`; `{today MM/DD/YYYY}` → `{today_us}`. The lone positional override: `{city}` at position 7 maps to `{cover_letter_text}` (it sits inside the cover-letter fallback literal whose outer brace spans lines and is dropped by the tight regex). |

§13.4 also gains a NexScout-only hard rule (the CAPTCHA_MANUAL branch); the
strict test strips lines containing `CAPTCHA_MANUAL` from the code template
before the byte-equality pass, but never strips anything from the plan slice
— additions are allowed, deletions are not.

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
