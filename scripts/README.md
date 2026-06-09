# NexScout launcher & setup scripts

This directory holds the cross-platform launcher and setup scripts for
NexScout. They wire up the three run methods, generate the three config files
interactively, and open the two dashboards once the stack is healthy.

## Layout

```
scripts/
├── README.md                  # this file
├── common/
│   └── generate_config.py     # interactive generator for the 3 YAML config files
├── windows/                   # PowerShell launchers (Windows host)
│   ├── _common.ps1            # shared helpers (dot-sourced; not run directly)
│   ├── start-direct.ps1       # run in a local .venv via pip install -e
│   ├── start-uv.ps1           # run via the `uv` package manager
│   ├── start-docker.ps1       # run the full stack via Docker Compose
│   └── stop.ps1               # stop local processes, or `-Docker` for compose down
└── linux/                     # bash launchers (Linux host)
    ├── _common.sh             # shared helpers (sourced; not run directly)
    ├── start-direct.sh        # run in a local .venv via pip install -e
    ├── start-uv.sh            # run via the `uv` package manager
    ├── start-docker.sh        # run the full stack via Docker Compose
    └── stop.sh                # stop local processes, or `--docker` for compose down
```

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
stack, wait for the web UI to answer on `:8765/healthz`, then open **both**
dashboards. They are defensive — a missing prerequisite fails with a clear
message, and a dashboard that won't open just prints its URL.

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
background, then runs `nexscout run`.

### 2. uv

```powershell
powershell -File scripts\windows\start-uv.ps1
```
```bash
./scripts/linux/start-uv.sh
```

Ensures `uv` is installed (auto-installs via the official Astral installer if
missing), runs `uv sync --extra dev --extra web`, `uv run nexscout doctor`,
starts `uv run nexscout web …` in the background, then `uv run nexscout run`.

### 3. Docker

```powershell
powershell -File scripts\windows\start-docker.ps1          # add -Setup to (re)configure
```
```bash
./scripts/linux/start-docker.sh
```

Runs `docker compose --profile openclaw up -d` (brings up the `nexscout`
container plus the `openclaw` gateway that serves the Control UI on `:18789`),
then `docker compose exec -d nexscout nexscout web --host 0.0.0.0 --port 8765`.

On **Windows** the Docker launcher handles two Docker Desktop quirks:
`docker.exe` is usually not on `PATH` (it prepends
`C:\Program Files\Docker\Docker\resources\bin`), and the compose volume mounts
use `${HOME}` (it sets `$env:HOME = $env:USERPROFILE`).

## Stopping

```powershell
powershell -File scripts\windows\stop.ps1            # local direct/uv processes
powershell -File scripts\windows\stop.ps1 -Docker    # docker compose down
```
```bash
./scripts/linux/stop.sh                # local direct/uv processes
./scripts/linux/stop.sh --docker       # docker compose down (add --volumes to drop volumes)
```

## Dashboards

After any launcher reports the stack is up, both of these open automatically
(or are printed if a browser can't be launched):

| Dashboard          | URL                       | Started by                              |
|--------------------|---------------------------|-----------------------------------------|
| NexScout web UI    | http://localhost:8765     | `nexscout web --host 0.0.0.0 --port 8765` |
| OpenClaw dashboard | http://localhost:18789    | the OpenClaw gateway (compose `openclaw` service) |

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
