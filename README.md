# NexScout

[![License: AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#)
[![Ruff](https://img.shields.io/badge/ruff-clean-brightgreen.svg)](#)

**NexScout** is an always-on, autonomous job-application agent. It discovers
jobs across the web, scores them against your profile, tailors a
LaTeX-rendered resume (and cover letter when required) per application, and
submits the application through an undetected Chrome driver. It runs
continuously as a crash-resilient `nexscout autopilot` loop or inside an
OpenClaw / NemoClaw heartbeat, exposes a modern Tailwind web UI for you, and
stores every application's full bundle (PDFs, screenshots, transcript) on
disk. It also runs as an **MCP server** so an OpenClaw agent can drive the
whole pipeline autonomously through tool calls.

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
- [MCP server](#mcp-server)
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
nexscout run                               # one real pipeline pass: discover -> enrich -> score -> tailor -> cover -> render
nexscout web &                             # http://127.0.0.1:8765
nexscout apply --workers 2                 # submit applications
# Always-on autonomous mode (the Docker command):
nexscout autopilot --wall-clock 1800       # crash-resilient continuous loop
# Optional OpenClaw heartbeat mode:
openclaw skill install ./src/nexscout/openclaw/manifest.toml
```

...and observes:

- `ruff check src/` returns 0.
- `ruff format --check src/ tests/` returns 0.
- `pytest -q` is green (1014 tests).
- `pytest --cov=src/nexscout` reports ≥80% per module and 93% project-wide.
- `nexscout run` executes the real pipeline and reports per-stage counts.
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
(Enter accepts a default, `-` skips a key). Two maintenance helpers also live
under `scripts/`: a database-wipe script (reset the SQLite state for a fresh
run) and an AI-model-switch script (repoint `llm.*` at a different provider).
See **[scripts/README.md](scripts/README.md)** for the full launcher /
generator / helper reference. The manual paths below remain fully supported.

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

Compose ships five named containers:

| Service        | Container           | Purpose                                                                |
|----------------|---------------------|------------------------------------------------------------------------|
| `nexscout`     | `nexscout`          | the autopilot loop — runs `nexscout autopilot --wall-clock 1800`       |
| `nexscout-web` | `nexscout-web`      | web dashboard (Tailwind + Chart.js) on :8765                           |
| `nexscout-mcp` | `nexscout-mcp`      | MCP server (streamable-http) on :8770 — `nexscout-mcp` console script  |
| `ollama`       | `nexscout-ollama`   | local LLM endpoint (opt-in `local-llm` profile)                        |
| `openclaw`     | `nexscout-openclaw` | OpenClaw gateway — runs `openclaw gateway --port 18789`, serves its Control UI on :18789 (opt-in `openclaw` profile) |

`docker compose --profile openclaw up -d` starts `nexscout` +
`nexscout-web` + `nexscout-mcp` + `openclaw` together. The `nexscout` service
has a healthcheck that runs `nexscout doctor --quiet` every 60s; the OpenClaw
container `depends_on` the MCP server so the agent's MCP endpoint resolves on
first boot. Two dashboards are then reachable: NexScout's own web UI at
<http://localhost:8765> (which also surfaces an OpenClaw status panel), and
OpenClaw's native gateway Control UI at <http://localhost:18789>
(`openclaw dashboard` opens it with an auth link; an `OPENCLAW_GATEWAY_TOKEN`
may be required). See `docs/openclaw.md` for the full mount + env contract and
the MCP registration steps.

---

## Run modes

NexScout supports three run modes; all share the same code paths.

### Autopilot mode (standalone, recommended)

A crash-resilient `nexscout autopilot` loop owns its own scheduler — no
external runtime required. Each pass runs one bounded heartbeat unit of work
(discover → enrich → score → tailor → cover → render → apply →
surface-questions), persists to SQLite, then sleeps `--interval` seconds
(default from `profile.apply.autopilot_interval_s`). Every pass is wrapped so
one error never stops the loop, and the profile is reloaded each pass so
config edits apply live. A crash, machine reboot, or model unload just resumes
on the next pass where it left off. This is the Docker `command`.

The loop honours the dashboard/MCP controls between and within passes: while
**paused** it skips passes entirely (it checks the flag each loop), a **stop**
aborts only the pass running right now (after the current job; the next
scheduled pass still runs), and any **disabled stage** is skipped each pass.
These flow through the shared `~/.nexscout/pipeline-control.json`, and the
loop publishes live per-stage progress to `~/.nexscout/pipeline-status.json`.

```bash
nexscout autopilot --wall-clock 1800   # soft per-pass time cap (s); --interval N to set the sleep
nexscout apply --workers 2 &           # optional dedicated apply workers
nexscout web &                         # http://127.0.0.1:8765
```

### Hosted-agent mode (OpenClaw)

A `nexscout` skill is registered with OpenClaw via
`src/nexscout/openclaw/manifest.toml`. OpenClaw's **heartbeat daemon** wakes
on a configurable interval (default 30 min) and calls `nexscout tick`,
which performs one bounded unit of work (enrich up to N jobs, score up to
M, apply up to K) and returns. The OpenClaw channel layer (Slack /
Discord / WhatsApp / Telegram / iMessage / Signal / Matrix / WebChat)
relays clarifying questions to you and accepts answers via
`/nexscout answer "<q>" "<a>"`. OpenClaw can also drive NexScout
autonomously through the [MCP server](#mcp-server).

```bash
openclaw skill install ./src/nexscout/openclaw/manifest.toml
# done — your heartbeat will start calling nexscout tick.
```

### One-shot mode

A single `nexscout run` pass executes the real pipeline once and exits —
ideal for cron, CI smoke tests, or stepping through stages by hand.

```bash
nexscout run                 # one full pass
nexscout run discover score  # selected stages only
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

nexscout run                 # one real pass: discover -> enrich -> score -> tailor -> cover -> render
nexscout apply --workers 2   # submit the highest-scoring tailored jobs
nexscout autopilot           # crash-resilient continuous loop (the always-on mode)
nexscout web                 # http://127.0.0.1:8765 — review + answer questions
```

Common flags:

```
nexscout run [stages...]      stages: discover enrich score tailor cover render all
   --stream                   streaming pipeline (concurrent stages)
   --validation strict|normal|lenient
   --limit N                  per-stage limit (0 = unlimited)
   --min-score N
nexscout autopilot                 continuous loop (one bounded pass per iteration)
   --interval N                    seconds between passes (0 = use profile.apply.autopilot_interval_s)
   --wall-clock S                  soft per-pass time cap (s)
nexscout apply
   --workers N --headless --dry-run --continuous
   --url URL                  one-shot
   --backend native|claude_code|openai_assistant
   --limit N
nexscout dashboard --export FILE   self-contained HTML report
nexscout status [--format text|json|openclaw]
nexscout controls pause|resume
nexscout question list|answer
nexscout doctor [--quiet]          tiered readiness; --quiet exits 0 when T2+ healthy
nexscout tick [--wall-clock S]     one bounded unit of work (OpenClaw heartbeat entry)
```

---

## MCP server

NexScout runs as a **Model Context Protocol (MCP) server** so an OpenClaw
agent can drive the whole pipeline autonomously through tool calls — fetching
your résumé, discovering / scoring / tailoring / applying, and answering
NexScout's own clarifying questions. The server is built on **FastMCP**, serves
the **Streamable HTTP** transport on `0.0.0.0:8770` at `/mcp`, and ships as the
`nexscout-mcp` console script (also `python -m nexscout.mcp.server`). The
implementation lives in `src/nexscout/mcp/server.py`.

It exposes fifteen tools — `get_profile`, `get_resume_text`, `pipeline_status`,
`stage_status`, `pause_automation`, `stop_current_run`, `set_stage_enabled`,
`run_stage`, `discover_jobs`, `score_jobs`, `tailor_jobs`, `apply_to_job`,
`list_open_questions`, `answer_question`, and `run_once` — each of which reads
the same `~/.nexscout` state as the rest of the stack, so the agent's actions
show up immediately in the web UI and pipeline. The five live-control tools
(`stage_status`, `pause_automation`, `stop_current_run`, `set_stage_enabled`,
`run_stage`) let the agent watch and steer the autopilot through the same
cross-process status/control channel the dashboard uses. Every tool is
defensive: it catches its own exceptions and returns a structured error
envelope rather than crashing the long-lived server.

The OpenClaw gateway connects over the shared Docker network and the entry is
written under the `mcp.servers.nexscout` map in `~/.openclaw/openclaw.json`:

```bash
openclaw mcp add nexscout --transport streamable-http --url http://nexscout-mcp:8770/mcp
openclaw mcp probe   # should report: nexscout: 15 tools
```

See **[docs/openclaw.md](docs/openclaw.md)** for the full tool table,
registration, and the `mcp.servers` config contract.

---

## Architecture

Seven per-job pipeline stages, in order: **discover -> enrich -> score ->
tailor -> cover -> render -> apply** (plus a "surface questions" housekeeping
step). Each stage reads pending rows from a single shared SQLite `jobs` table,
writes its results back, and hands off to the next. Every stage is
**stage-locked**: a stage's SQL predicate only selects jobs the previous stage
finished, so jobs can never skip ahead. The engine is **sequential and
single-threaded per pass** by design — there is no concurrency between stages.

Apply outcomes fall into four plain-language buckets:

- **Applied** — submitted successfully.
- **Waiting on you** (parked) — a CAPTCHA or a clarifying question needs
  your input. Surfaced as a pending question, not a failure.
- **Not a match** (skipped) — login / SSO wall, out-of-location, or expired
  posting. A normal, benign outcome.
- **Problems** (errors, rare) — genuine faults (page crash, infra failure).
  Only these count toward `apply_errors`; `get_stats` also returns `parked`
  and `skipped` so the dashboard's "Problems" card stays near zero on a
  healthy run.

See `docs/architecture.md` for a Mermaid pipeline diagram and module map.
See `docs/openclaw.md` for the heartbeat / memory contract.
See `docs/latex-templates.md` for the Jinja2 / LaTeX template contract.

---

## Screenshots

> Screenshots are intentionally not included in the initial release; the
> web UI and live dashboard are best demoed against your own data.
> Replace this section with `docs/screenshots/*.png` once you have real
> applied jobs to show.

The web UI is a modern, responsive **Tailwind** dashboard with interactive
**Chart.js** graphs and an interactive **"Automation pipeline"** panel that
shows every stage's live state, progress bar, and backlog ("N waiting"), with
per-stage **Turn on/off** toggles and **Run one full pass now** / **Pause** /
**Resume** / **Stop the current run** controls. (This replaced the older,
misleading "Check for new jobs now / Pause auto-run / Resume auto-run"
buttons, where Pause did nothing.) Long actions are non-blocking: the backend
returns `202 Accepted` and the UI polls `/controls/status` until the pass
finishes. A **Logs** tab tails the backend's per-role log files. See
[docs/architecture.md](docs/architecture.md) for the full control/status
model.

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
`cp examples/split/*.yaml ~/.nexscout/`. `nexscout init` walks you through the
schema and writes the same three-file split; the schema is documented in §3 of
`plan.md`. Key blocks:

- `me`, `auth`, `pay`, `avail`, `exp` — applicant facts (preserved
  verbatim through tailoring).
- `skills` — your real skills set; anything the tailor mentions outside
  this set is treated as fabrication.
- `facts` — your real companies, projects, school, metrics.
- `search` — queries, locations, JobSpy / WebSearch board choices, score
  threshold.
- `llm` — primary, fallback, judge models + monthly USD + daily-call
  budgets. Each model is a `scheme:model` spec. Supported schemes:
  `gemini`, `openai`, `anthropic`, `lmstudio`, `ollama`, plus
  `openai_compat:<model>` (**any** OpenAI-compatible endpoint — OpenRouter,
  Together, Groq, vLLM, self-hosted, …) and `nim:<model>` (NVIDIA NIM).
  OpenAI-compatible schemes read `base_url` / `api_key` / `model` /
  `extra_headers` from `llm.providers.<scheme>`, with env fallbacks
  (`NVIDIA_API_KEY`; `OPENAI_COMPAT_API_KEY` / `OPENAI_COMPAT_BASE_URL`;
  `NIM_BASE_URL`). OpenRouter example:

  ```yaml
  llm:
    primary: "openai_compat:google/gemma-4-26b-a4b-it:free"
    providers:
      openai_compat:
        base_url: "https://openrouter.ai/api/v1"
        api_key: "${env:OPENROUTER_API_KEY}"
  ```
- `apply` — workers, headless, dry-run, retry budget, permitted ATSs,
  ReAct `backend` (`native` / `claude_code` / `openai_assistant`), and
  `autopilot_interval_s` (default sleep between `nexscout autopilot` passes).
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
total project coverage sits at **93%** as of v0.1.0 (1014 tests passing).
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
