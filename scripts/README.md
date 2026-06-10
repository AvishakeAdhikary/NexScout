# NexScout launcher & setup scripts

This directory holds the cross-platform launcher and setup scripts for
NexScout. They wire up the three run methods, generate the three config files
interactively, start the autonomous **autopilot** loop, and open the two
dashboards once the stack is healthy.

## Layout

```
scripts/
├── README.md                  # this file
├── common/
│   └── generate_config.py     # interactive generator for the 3 YAML config files
├── windows/                   # PowerShell launchers (Windows host)
│   ├── _common.ps1            # shared helpers (dot-sourced; not run directly)
│   ├── dashboard-link.ps1     # print both dashboard URLs; resolve the tokenized OpenClaw link
│   ├── start-direct.ps1       # run in a local .venv via pip install -e
│   ├── start-uv.ps1           # run via the `uv` package manager
│   ├── start-docker.ps1       # run the full stack via Docker Compose
│   └── stop.ps1               # stop local processes, or `-Docker` for compose down
└── linux/                     # bash launchers (Linux host)
    ├── _common.sh             # shared helpers (sourced; not run directly)
    ├── dashboard-link.sh      # print both dashboard URLs; resolve the tokenized OpenClaw link
    ├── start-direct.sh        # run in a local .venv via pip install -e
    ├── start-uv.sh            # run via the `uv` package manager
    ├── start-docker.sh        # run the full stack via Docker Compose
    └── stop.sh                # stop local processes, or `--docker` for compose down
```

## Autopilot — the autonomous, crash-resilient loop

`nexscout autopilot [--interval N] [--wall-clock S]` is the **leave-it-running**
mode. It loops the full pipeline forever — one bounded pass per iteration:

```
discover -> enrich -> score -> tailor -> render -> apply -> questions
```

Each pass persists to SQLite and is wrapped so a single failure (a per-job
error, a model unload, a network blip) never stops the loop; the next pass just
resumes where it left off. In Docker the `nexscout` service runs this as its
container `command` with `restart: unless-stopped`, so it also **auto-resumes
after a container crash or a machine reboot**. The profile is reloaded each pass,
so config edits apply live.

Related commands (still available):

* `nexscout run [stages]` — one single pipeline pass, then exit.
* `nexscout apply --continuous` — an apply-only forever loop (no discover/score).

The Docker launchers leave autopilot running inside the container; the host
launchers (direct / uv) run `nexscout autopilot` in the **foreground** after
starting the web UI in the background — press **Ctrl+C** to stop it.

## The three config files

NexScout reads three YAML files from its config directory (`$NEXSCOUT_DIR` if
set, otherwise `~/.nexscout`) and deep-merges them at load time into one
profile model. Merge priority is `profile.yaml` < `settings.yaml` <
`credentials.yaml`:

| File               | Holds                                                    | Priority |
|--------------------|----------------------------------------------------------|----------|
| `profile.yaml`     | résumé / applicant facts (`me`, `auth`, `skills`, …)     | lowest   |
| `settings.yaml`    | operational config (`search`, `llm`, `apply`, `openclaw`, `captcha`, `smtp`) | middle |
| `credentials.yaml` | secrets in **plaintext** (captcha key, smtp/account passwords, proxy) | highest |

`${env:NAME}` substitution works inside any of the three files.

## The interactive config generator

`common/generate_config.py` is standalone and cross-platform (Python 3.11+,
stdlib + `pyyaml`, which NexScout already depends on). Run it directly:

```bash
python scripts/common/generate_config.py            # -> $NEXSCOUT_DIR or ~/.nexscout
python scripts/common/generate_config.py /some/dir  # -> explicit target dir
```

For **every** prompt it shows a sensible default in brackets:

* press **Enter** to accept the `[default]`;
* type a value to override it;
* type a single dash **`-`** to **skip** that key entirely (it is omitted from
  the file — skipped keys are never written).

Prompts are grouped into `RÉSUMÉ (profile.yaml)`, `SETTINGS (settings.yaml)`,
and `SECRETS (credentials.yaml)`. It never overwrites an existing file without
a y/n confirmation (default: no), and at the end it prints exactly which files
were written, the dashboard URLs, and how to start each run method.

The launcher scripts run the generator automatically when the config files are
missing, or when you pass the setup switch (`-Setup` on Windows, `--setup` on
Linux).

> **Channel tokens are NOT stored in the config files.** The OpenClaw channel
> is chosen by `settings.yaml -> openclaw.channel` (`cli` / `telegram` /
> `discord`), but the channel credentials come from environment variables:
>
> * Telegram — `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
> * Discord  — `DISCORD_WEBHOOK_URL` (preferred), or `DISCORD_BOT_TOKEN` +
>   `DISCORD_CHANNEL_ID`
>
> The generator offers to print the matching `export` / `$env:` lines for you.

## The three run methods

All launchers: locate the repo root, optionally (re)generate config, start the
stack, wait for the web UI to answer on `:8765/healthz`, then open the
dashboard(s). The Docker launcher opens **both** dashboards (NexScout web UI +
the tokenized OpenClaw Control UI); the host launchers (direct / uv) open just
the NexScout web UI, since the **OpenClaw gateway is Docker-only**. They are
defensive — a missing prerequisite fails with a clear message, and a dashboard
that won't open just prints its URL.

### 1. Direct (local `.venv` + `pip install -e`)

```powershell
# Windows
powershell -File scripts\windows\start-direct.ps1          # add -Setup to (re)configure
```
```bash
# Linux
./scripts/linux/start-direct.sh                            # add --setup to (re)configure
```

Creates/activates `.venv`, runs `pip install -e ".[dev,web]"` plus the
`python-jobspy --no-deps` two-step from the project README, runs
`nexscout doctor`, starts `nexscout web --host 0.0.0.0 --port 8765` in the
background, opens the NexScout dashboard, then runs the resilient
`nexscout autopilot` loop in the foreground (Ctrl+C to stop). The OpenClaw
gateway is Docker-only.

### 2. uv

```powershell
powershell -File scripts\windows\start-uv.ps1
```
```bash
./scripts/linux/start-uv.sh
```

Ensures `uv` is installed (auto-installs via the official Astral installer if
missing), runs `uv sync --extra dev --extra web`, `uv run nexscout doctor`,
starts `uv run nexscout web …` in the background, opens the NexScout dashboard,
then runs `uv run nexscout autopilot` (the resilient loop) in the foreground
(Ctrl+C to stop). The OpenClaw gateway is Docker-only.

### 3. Docker

```powershell
powershell -File scripts\windows\start-docker.ps1          # add -Setup to (re)configure
```
```bash
./scripts/linux/start-docker.sh
```

Runs `docker compose --profile openclaw up -d`, which brings up the full stack
in one shot, then waits for `:8765/healthz` and opens both dashboards. There is
**no separate web-exec step anymore** — the web UI is its own service.

#### The four compose services

| Service        | Container           | Command                              | Ports          | Notes |
|----------------|---------------------|--------------------------------------|----------------|-------|
| `nexscout`     | `nexscout`          | `autopilot` (resilient loop)         | —              | `restart: unless-stopped`; auto-resumes after crashes/reboots |
| `nexscout-web` | `nexscout-web`      | `web --host 0.0.0.0 --port 8765`     | `8765:8765`    | the NexScout dashboard |
| `openclaw`     | `nexscout-openclaw` | `node dist/index.js gateway … 18789` | `18789, 18790` | profile `openclaw`; serves the tokenized Control UI |
| `ollama`       | `nexscout-ollama`   | (ollama serve)                       | `11434:11434`  | profile `local-llm`; optional local LLM backend |

So `docker compose --profile openclaw up -d` starts `nexscout` (autopilot) +
`nexscout-web` + `openclaw`. Because autopilot is the container command and the
service uses `restart: unless-stopped`, **the stack keeps applying autonomously
and auto-resumes after any container crash, machine reboot, or model unload.**

On **Windows** the Docker launcher handles two Docker Desktop quirks:
`docker.exe` is usually not on `PATH` (it prepends
`C:\Program Files\Docker\Docker\resources\bin`), and the compose volume mounts
use `${HOME}` (it sets `$env:HOME = $env:USERPROFILE`).

## Stopping

```powershell
powershell -File scripts\windows\stop.ps1            # local direct/uv processes (web + autopilot)
powershell -File scripts\windows\stop.ps1 -Docker    # docker compose down (all 4 services)
```
```bash
./scripts/linux/stop.sh                # local direct/uv processes (web + autopilot)
./scripts/linux/stop.sh --docker       # docker compose down (add --volumes to drop volumes)
```

The host teardown kills the background web UI (via `.nexscout-web.pid`) plus
any lingering `nexscout` processes, including the `nexscout autopilot` loop. The
Docker teardown runs `docker compose --profile openclaw --profile local-llm
down`, so it stops **all four** services (nexscout autopilot, nexscout-web,
openclaw gateway, and ollama if it was started) regardless of which profiles
were used to start.

## Dashboards

After the Docker launcher reports the stack is up, both of these open
automatically (or are printed if a browser can't be launched); the host
launchers open just the NexScout web UI:

| Dashboard          | URL                       | Started by                              |
|--------------------|---------------------------|-----------------------------------------|
| NexScout web UI    | http://localhost:8765     | `nexscout-web` service / `nexscout web …` |
| OpenClaw dashboard | http://localhost:18789    | the OpenClaw gateway (compose `openclaw` service) — **Docker-only** |

### Getting the tokenized OpenClaw dashboard link

The OpenClaw gateway Control UI on `:18789` requires an **auth token**. Use the
dashboard-link helper to fetch a ready-to-click link any time:

```powershell
powershell -File scripts\windows\dashboard-link.ps1        # both URLs + token
powershell -File scripts\windows\dashboard-link.ps1 -OpenClawOnly   # just the OpenClaw URL
```
```bash
./scripts/linux/dashboard-link.sh                          # both URLs + token
./scripts/linux/dashboard-link.sh --openclaw-only          # just the OpenClaw URL
```

It resolves the link in this order, and **never hard-crashes** (a missing
container or config just prints a helpful message and the bare URL):

1. **OpenClaw CLI inside the running container** (preferred):
   `docker exec nexscout-openclaw node dist/index.js dashboard --print`
   (also tried with `--json`). If it emits a pre-authenticated URL, that is
   surfaced verbatim.
2. **Token from config** (fallback): reads `gateway.auth.token` from
   `~/.openclaw/openclaw.json` and builds
   `http://localhost:18789/?token=<TOKEN>` (the documented query-param form; if
   your OpenClaw build expects a different param, paste the raw token into the
   Control UI instead). If the config has no token it falls back to the
   `OPENCLAW_GATEWAY_TOKEN` environment variable.

In all cases it also prints the **raw token** and the `OPENCLAW_GATEWAY_TOKEN`
value so you can paste it manually. The Docker launcher and the shared
`Open-Dashboards` / `open_dashboards` helpers call this resolver automatically,
so the OpenClaw URL they open/print is already tokenized when a token exists.

## LLM backend (LM Studio)

NexScout's default LLM backend is **LM Studio** (OpenAI-compatible) at
`http://localhost:1234/v1` on the host, or `http://host.docker.internal:1234/v1`
from inside Docker. Before running the score / tailor / apply stages:

1. Open LM Studio and load any instruction-tuned chat model.
2. Start its server (port 1234, OpenAI-compatible).
3. Set `settings.yaml -> llm.primary` to `lmstudio:<model-id>` (the generator
   defaults to `lmstudio:local-model`, which works once any model is loaded).

The launchers do a best-effort reachability check and warn — but do not fail —
when LM Studio is not running, since the `discover` stage does not need it.
