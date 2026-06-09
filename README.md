# NexScout

[![License: AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#)
[![Ruff](https://img.shields.io/badge/ruff-clean-brightgreen.svg)](#)

**NexScout** is an always-on, autonomous job-application agent. It discovers
jobs across the web, scores them against your profile, tailors a
LaTeX-rendered resume (and cover letter when required) per application, and
submits the application through an undetected Chrome driver. It runs
continuously inside an OpenClaw / NemoClaw heartbeat or as a plain
standalone loop, exposes a FastAPI + HTMX web UI for you, and stores every
application's full bundle (PDFs, screenshots, transcript) on disk.

CAPTCHA solving is **optional**: when a key is configured (CapSolver /
2Captcha / Anti-Captcha) it solves them inline; otherwise jobs that hit a
CAPTCHA wall are parked with `apply_status='captcha_manual'` and surfaced
to you as a pending question. Web discovery falls back to an undetected
Chrome search of DuckDuckGo + Google when no API key is configured. Email
delivery falls back from SMTP to a browser-driven Gmail login when only an
email + password are provided.

The single source of truth for behaviour is `plan.md`. Every LLM prompt is
**byte-equal** to that spec — `tests/unit/test_prompts_verbatim.py` will
scream if anyone drifts.

---

## Table of contents

- [Definition of done](#definition-of-done)
- [Install](#install)
- [Run modes](#run-modes)
- [Quickstart](#quickstart)
- [Architecture](#architecture)
- [Screenshots](#screenshots)
- [Configuration](#configuration)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

---

## Definition of done

A fresh contributor on a clean machine runs:

```bash
git clone <repo>
cd nexscout

# Dependencies — pick ONE of:
#   pip:
pip install -e ".[dev,web]"
pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex
#   uv (what CI now runs):
uv sync --extra dev --extra web            # then prefix commands below with `uv run`

nexscout init                              # YAML wizard fills ~/.nexscout/profile.yaml
export CAPTCHA_API_KEY=...                 # optional; manual review path is automatic when unset
nexscout doctor                            # tiered T1/T2/T3 report; --quiet exits 0 when T2+ healthy
nexscout run                               # discover -> enrich -> score -> tailor -> cover -> render
nexscout web &                             # http://127.0.0.1:8765
nexscout apply --workers 2                 # submit applications
# Optional always-on mode:
openclaw skill install ./src/nexscout/openclaw/manifest.toml
```

...and observes:

- `ruff check src/` returns 0.
- `ruff format --check src/ tests/` returns 0.
- `pytest -q` is green (835 tests).
- `pytest --cov=src/nexscout` reports ≥80% per module and 93% project-wide.
- The web UI lists applied jobs with their tailored PDFs.

---

## Install

### Prerequisites

- **Python 3.11+**
- **Chromium / Google Chrome** for the apply browser. Linux: install
  `chromium` and `chromium-driver` via your package manager; Windows /
  macOS: standard Chrome works.
- **A LaTeX engine** for resume PDF rendering. **Tectonic** is preferred
  (self-contained); `latexmk` and `pdflatex` are also auto-detected. The
  Docker image installs Tectonic for you.
- **(Optional) A CAPTCHA provider key.** When set, NexScout solves CAPTCHAs
  inline via CapSolver / 2Captcha / Anti-Captcha. When unset, jobs that
  trigger a CAPTCHA wall are marked `apply_status='captcha_manual'` and
  surfaced as pending questions for manual review — `nexscout doctor`
  reports WARN (not error) and the apply pipeline continues.
- **(Optional) Search API key.** Tavily / Brave / Google CSE / SearXNG are
  used first if configured. With none of them set, NexScout falls back to
  an undetected Chrome search of DuckDuckGo + Google for the WebSearch
  discovery engine.
- **(Optional) SMTP credentials.** For email-only postings, NexScout uses
  `profile.smtp.*` first, then your Gmail email + password via a
  browser-driven Gmail login (compose URL + Send button).

### Quick start via scripts

The fastest path is the cross-platform launchers in `scripts/`. They
(re)generate the three config files interactively, bring up your chosen run
method, wait for the web UI, then open both dashboards:

```powershell
# Windows — pass -Setup the first time to generate config
powershell -File scripts\windows\start-uv.ps1 -Setup       # or start-direct.ps1 / start-docker.ps1
```
```bash
# Linux — pass --setup the first time
./scripts/linux/start-uv.sh --setup                        # or start-direct.sh / start-docker.sh
```

`scripts/common/generate_config.py` is the standalone interactive generator
(Enter accepts a default, `-` skips a key). See **[scripts/README.md](scripts/README.md)**
for the full launcher / generator reference. The manual paths below remain
fully supported.

### From source

```bash
git clone <repo>
cd nexscout
python3.11 -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1
```

Then install dependencies with **either** pip or uv.

**pip:**

```bash
pip install -e ".[dev,web]"
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex
```

The `--no-deps` step on `python-jobspy` is required: that package pins an
exact numpy version that conflicts with pip's resolver but works fine at
runtime. The follow-up `pip install pydantic tls-client requests
markdownify regex` brings in its real runtime deps.

**uv** (what CI now runs):

```bash
uv sync --extra dev --extra web
uv run nexscout doctor          # prefix any nexscout command with `uv run`
```

`uv sync` provisions the virtualenv and resolves dependencies in one step;
prefix subsequent `nexscout`/`pytest`/`ruff` invocations with `uv run`.

### Via Docker

```bash
# Build the image (chromium + tectonic + fonts baked in)
docker build -t nexscout .

# Run one-shot doctor against your local profile
docker run --rm -v "$HOME/.nexscout:/sandbox/nexscout" nexscout doctor

# Full stack with the OpenClaw + local LLM profiles
docker compose --profile local-llm --profile openclaw up -d
```

Compose ships three named containers:

| Service    | Container             | Purpose                                  |
|------------|-----------------------|------------------------------------------|
| `nexscout` | `nexscout`            | the agent itself (runs `nexscout run`)   |
| `ollama`   | `nexscout-ollama`     | local LLM endpoint (opt-in profile)      |
| `openclaw` | `nexscout-openclaw`   | OpenClaw gateway — runs `openclaw gateway --port 18789`, serves its Control UI on :18789 (opt-in profile) |

The `nexscout` service has a healthcheck that runs `nexscout doctor --quiet`
every 60s; the OpenClaw container `depends_on: service_healthy` so a cold
`docker compose up` waits for NexScout's prereqs before starting the
gateway. Two dashboards are then reachable: NexScout's own web UI at
<http://localhost:8765> (which also surfaces an OpenClaw status panel), and
OpenClaw's native gateway Control UI at <http://localhost:18789>
(`openclaw dashboard` opens it with an auth link; an `OPENCLAW_GATEWAY_TOKEN`
may be required). See `docs/openclaw.md` for the full mount + env contract.

---

## Run modes

NexScout supports two run modes; both share the same code paths.

### Hosted-agent mode (recommended)

A `nexscout` skill is registered with OpenClaw via
`src/nexscout/openclaw/manifest.toml`. OpenClaw's **heartbeat daemon** wakes
on a configurable interval (default 30 min) and calls `nexscout tick`,
which performs one bounded unit of work (enrich up to N jobs, score up to
M, apply up to K) and returns. The OpenClaw channel layer (Slack /
Discord / WhatsApp / Telegram / iMessage / Signal / Matrix / WebChat)
relays clarifying questions to you and accepts answers via
`/nexscout answer "<q>" "<a>"`.

```bash
openclaw skill install ./src/nexscout/openclaw/manifest.toml
# done — your heartbeat will start calling nexscout tick.
```

### Standalone mode

A plain `nexscout run --continuous` loop. No heartbeat; the process owns
its own scheduler. Same code paths underneath.

```bash
nexscout run --continuous
nexscout apply --workers 2 &
nexscout web &
```

---

## Quickstart

```bash
nexscout init                # interactive wizard -> ~/.nexscout/profile.yaml
nexscout doctor              # tiered readiness: T1 discover, T2 LLM, T3 apply
nexscout doctor --quiet      # exits 0 when T2+ healthy; used by the Docker healthcheck

export GEMINI_API_KEY=...    # or OPENAI_API_KEY / ANTHROPIC_API_KEY
export CAPTCHA_API_KEY=...   # optional — manual review when unset
export TAVILY_API_KEY=...    # optional — browser fallback when none of Tavily/Brave/CSE are set

nexscout run                 # one tick: discover -> enrich -> score -> tailor -> cover -> render
nexscout apply --workers 2   # submit the highest-scoring tailored jobs
nexscout web                 # http://127.0.0.1:8765 — review + answer questions
```

Common flags:

```
nexscout run [stages...]      stages: discover enrich score tailor cover render all
   --stream                   streaming pipeline (concurrent stages)
   --workers N
   --validation strict|normal|lenient
   --dry-run
   --min-score N
nexscout apply
   --workers N --headless --dry-run --continuous
   --url URL                  one-shot
   --backend native|claude_code|openai_assistant
   --limit N
nexscout dashboard --export FILE   self-contained HTML report
nexscout chrome reset --worker N
nexscout budget show|reset
nexscout question list|answer
nexscout profile validate|migrate
nexscout doctor [--quiet]          tiered readiness; --quiet exits 0 when T2+ healthy
nexscout tick                      one bounded unit of work (OpenClaw heartbeat entry)
```

---

## Architecture

Six pipeline stages: **discover -> enrich -> score -> tailor -> cover ->
render -> apply.** Each stage reads pending rows from a single shared
SQLite `jobs` table, writes its results back, and hands off to the next.

See `docs/architecture.md` for a Mermaid pipeline diagram and module map.
See `docs/openclaw.md` for the heartbeat / memory contract.
See `docs/latex-templates.md` for the Jinja2 / LaTeX template contract.

---

## Screenshots

> Screenshots are intentionally not included in the initial release; the
> web UI and live dashboard are best demoed against your own data.
> Replace this section with `docs/screenshots/*.png` once you have real
> applied jobs to show.

- `docs/screenshots/dashboard.png` — counters + score chart + recent events.
- `docs/screenshots/job-detail.png` — inline PDF + transcript + screenshots.
- `docs/screenshots/applications.png` — paginated applied-job list.
- `docs/screenshots/live.png` — Rich `Live` dashboard during `apply --workers`.

---

## Configuration

Configuration is one file or three — both work. A single monolithic
`~/.nexscout/profile.yaml` (the default) still loads exactly as before.
Optionally you may split it into three deep-merged files in the same
directory (priority `profile.yaml` < `settings.yaml` < `credentials.yaml`):

| File               | Holds                                                       |
|--------------------|-------------------------------------------------------------|
| `profile.yaml`     | résumé / applicant facts (`me`, `auth`, `skills`, `facts`, …) + optional CV extras (`certifications`/`publications`/`languages`) |
| `settings.yaml`    | operational config (`search`, `llm`, `apply`, `openclaw`) + `captcha.provider` + non-secret `smtp.*` |
| `credentials.yaml` | secrets — `captcha.api_key`, `smtp.password`, `gmail_password`, account `password`, `proxy` |

A commented reference set lives in `examples/split/` — copy it with
`cp examples/split/*.yaml ~/.nexscout/`. `nexscout init` walks you through a
monolithic profile; the schema is documented in §3 of `plan.md` and a
single-file reference copy lives at `examples/profile.example.yaml`. Key
blocks:

- `me`, `auth`, `pay`, `avail`, `exp` — applicant facts (preserved
  verbatim through tailoring).
- `skills` — your real skills set; anything the tailor mentions outside
  this set is treated as fabrication.
- `facts` — your real companies, projects, school, metrics.
- `search` — queries, locations, JobSpy / WebSearch board choices, score
  threshold.
- `llm` — primary, fallback, judge models + monthly USD + daily-call
  budgets.
- `apply` — workers, headless, dry-run, retry budget, permitted ATSs.
- `captcha` — **optional** provider + `${env:CAPTCHA_API_KEY}`
  substitution. When unset, CAPTCHA-walled jobs are parked for manual
  review (visible at `/questions` in the web UI).
- `smtp` — **optional** SMTP host/port/user/password for email-only
  postings. If absent and `me.email` is a Gmail address, the apply agent
  falls back to a browser-driven Gmail compose URL + login flow.
- `openclaw.channel` — notification channel: `cli` (inbox-only, default),
  `telegram`, or `discord`. Telegram needs `TELEGRAM_BOT_TOKEN` +
  `TELEGRAM_CHAT_ID`; Discord needs `DISCORD_WEBHOOK_URL` (preferred) or
  `DISCORD_BOT_TOKEN` + `DISCORD_CHANNEL_ID`. Channel tokens come from the
  environment, never from the config files — see `docs/openclaw.md`.
- `openclaw.tick_budget` — bounded-unit-of-work limits per stage.

Environment variables are read via `${env:NAME}` substitution at load
time (in any of the one/three config files). Pydantic validates the merged
result and emits human-readable errors.

---

## Development

```bash
pip install -e ".[dev,web]"          # or: uv sync --extra dev --extra web
pre-commit install
pre-commit run --all-files

pytest -q                            # or: uv run pytest -q
pytest -q --cov=src/nexscout --cov-report=term-missing

ruff check src/ tests/
mypy src/nexscout/core src/nexscout/llm src/nexscout/scoring \
     src/nexscout/captcha src/nexscout/apply/orchestrator.py \
     src/nexscout/apply/agent.py
```

CI now runs on **uv** (`uv sync --extra dev --extra web` then `uv run …`);
the pip path above remains fully supported for local work. Prefix any
command with `uv run` to use the uv-managed virtualenv.

Coverage targets — every module under `src/nexscout/` reaches **≥80%**;
total project coverage sits at **93%** as of v0.1.0 (835 tests passing).
The plan.md §23 minimums (`core/ ≥ 90%`, `llm/ ≥ 80%`, `scoring/ ≥ 80%`,
`captcha/ ≥ 70%`, `apply/orchestrator.py ≥ 80%`) are all exceeded; CI gates
on the project-wide 80% floor.

Full developer guide: **[docs/developer-guide.md](docs/developer-guide.md)**.

---

## Contributing

Pull requests welcome. Before you open one:

1. Read `plan.md` — it is the **sole specification**; every behaviour
   change must be justified against it.
2. Run `pre-commit run --all-files` and `pytest -q`. Both must be green.
3. Never weaken a test to make it pass. **Verbatim means verbatim.**
4. Add yourself to `AUTHORS` if you'd like attribution.

For the discovery-source / LLM-provider extension contracts, see
`docs/developer-guide.md`.

---

## License

AGPL-3.0-only. See [LICENSE](LICENSE).
