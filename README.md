# NexScout

[![License: AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#)
[![Ruff](https://img.shields.io/badge/ruff-clean-brightgreen.svg)](#)

**NexScout** is an always-on, autonomous job-application agent. It discovers
jobs across the web, scores them against your profile, tailors a
LaTeX-rendered resume (and cover letter when required) per application, and
submits the application through an undetected Chrome driver with mandatory
CAPTCHA solving. It runs continuously inside an OpenClaw / NemoClaw
heartbeat or as a plain standalone loop, exposes a FastAPI + HTMX web UI for
you, and stores every application's full bundle (PDFs, screenshots,
transcript) on disk.

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
pip install -e ".[dev,web]"
pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex
nexscout init                              # YAML wizard fills ~/.nexscout/profile.yaml
export CAPTCHA_API_KEY=...
nexscout doctor                            # all green
nexscout run                               # discover -> enrich -> score -> tailor -> cover -> render
nexscout web &                             # http://127.0.0.1:8765
nexscout apply --workers 2                 # submit applications
# Optional always-on mode:
openclaw skill install ./src/nexscout/openclaw/manifest.toml
```

...and observes:

- `ruff check src/` returns 0.
- `pytest` is green.
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
- **A CAPTCHA provider key.** NexScout refuses to start `run` or `apply`
  without one. Supported: CapSolver, 2Captcha, Anti-Captcha.

### From source

```bash
git clone <repo>
cd nexscout
python3.11 -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1

pip install -e ".[dev,web]"
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex
```

The `--no-deps` step on `python-jobspy` is required: that package pins an
exact numpy version that conflicts with pip's resolver but works fine at
runtime. The follow-up `pip install pydantic tls-client requests
markdownify regex` brings in its real runtime deps.

### Via Docker

```bash
# Build the image (chromium + tectonic + fonts baked in)
docker build -t nexscout .

# Run one-shot doctor against your local profile
docker run --rm -v "$HOME/.nexscout:/sandbox/nexscout" nexscout doctor

# Full stack with the OpenClaw + local LLM profiles
docker compose --profile local-llm --profile openclaw up
```

See `docs/openclaw.md` for the sandbox-mount contract.

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

export CAPTCHA_API_KEY=...
export GEMINI_API_KEY=...    # or OPENAI_API_KEY / ANTHROPIC_API_KEY

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

The only file you fill in is `~/.nexscout/profile.yaml`. `nexscout init`
walks you through it; the schema is documented in §3 of `plan.md` and a
reference copy lives at `examples/profile.example.yaml`. Key blocks:

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
- `captcha` — provider + `${env:CAPTCHA_API_KEY}` substitution.
- `openclaw.tick_budget` — bounded-unit-of-work limits per stage.

Environment variables are read via `${env:NAME}` substitution at load
time. Pydantic validates the file and emits human-readable errors.

---

## Development

```bash
pip install -e ".[dev,web]"
pre-commit install
pre-commit run --all-files

pytest -q
pytest -q --cov=src/nexscout --cov-report=term-missing

ruff check src/ tests/
mypy src/nexscout/core src/nexscout/llm src/nexscout/scoring \
     src/nexscout/captcha src/nexscout/apply/orchestrator.py \
     src/nexscout/apply/agent.py
```

Coverage targets per `plan.md` §23:

| Subpackage              | Threshold |
|-------------------------|-----------|
| `core/`                 | 90 %      |
| `llm/`                  | 80 %      |
| `scoring/`              | 80 %      |
| `captcha/`              | 70 %      |
| `apply/orchestrator.py` | 80 %      |

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
