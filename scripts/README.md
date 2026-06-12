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
│   ├── generate_config.py     # interactive generator for the 3 YAML config files
│   ├── clear_db.py            # wipe runtime data (DBs/applications/scratch); keep config
│   └── set_model.py           # switch the LLM model by rewriting settings/credentials
├── windows/                   # PowerShell launchers (Windows host)
│   ├── _common.ps1            # shared helpers (dot-sourced; not run directly)
│   ├── dashboard-link.ps1     # print both dashboard URLs; resolve the tokenized OpenClaw link
│   ├── start-direct.ps1       # run in a local .venv via pip install -e
│   ├── start-uv.ps1           # run via the `uv` package manager
│   ├── start-docker.ps1       # run the full stack via Docker Compose
│   ├── clear-db.ps1           # wrapper for clear_db.py (host, or -Docker to stop+wipe)
│   ├── set-model.ps1          # wrapper for set_model.py (host, or -Docker to recreate)
│   └── stop.ps1               # stop local processes, or `-Docker` for compose down
└── linux/                     # bash launchers (Linux host)
    ├── _common.sh             # shared helpers (sourced; not run directly)
    ├── dashboard-link.sh      # print both dashboard URLs; resolve the tokenized OpenClaw link
    ├── start-direct.sh        # run in a local .venv via pip install -e
    ├── start-uv.sh            # run via the `uv` package manager
    ├── start-docker.sh        # run the full stack via Docker Compose
    ├── clear-db.sh            # wrapper for clear_db.py (host, or --docker to stop+wipe)
    ├── set-model.sh           # wrapper for set_model.py (host, or --docker to recreate)
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

#### The five compose services

| Service        | Container           | Command                              | Ports          | Notes |
|----------------|---------------------|--------------------------------------|----------------|-------|
| `nexscout`     | `nexscout`          | `autopilot` (resilient loop)         | —              | `restart: unless-stopped`; auto-resumes after crashes/reboots |
| `nexscout-web` | `nexscout-web`      | `web --host 0.0.0.0 --port 8765`     | `8765:8765`    | the NexScout dashboard |
| `nexscout-mcp` | `nexscout-mcp`      | `nexscout-mcp` (Streamable HTTP)     | `8770:8770`    | the MCP server the OpenClaw gateway calls (`http://nexscout-mcp:8770/mcp`) |
| `openclaw`     | `nexscout-openclaw` | `node dist/index.js gateway … 18789` | `18789, 18790` | profile `openclaw`; serves the tokenized Control UI; depends on `nexscout-mcp` |
| `ollama`       | `nexscout-ollama`   | (ollama serve)                       | `11434:11434`  | profile `local-llm`; optional local LLM backend |

So `docker compose --profile openclaw up -d` starts `nexscout` (autopilot) +
`nexscout-web` + **`nexscout-mcp`** (the agent-tool server) + `openclaw` — the
`openclaw` service `depends_on` `nexscout-mcp`, so bringing up the gateway pulls
the MCP server up with it. Because autopilot is the `nexscout` container command
and the service uses `restart: unless-stopped`, **the stack keeps applying
autonomously and auto-resumes after any container crash, machine reboot, or
model unload.**

On **Windows** the Docker launcher handles two Docker Desktop quirks:
`docker.exe` is usually not on `PATH` (it prepends
`C:\Program Files\Docker\Docker\resources\bin`), and the compose volume mounts
use `${HOME}` (it sets `$env:HOME = $env:USERPROFILE`).

## Maintenance helpers

Two small standalone helpers live in `common/` (each with thin per-OS
wrappers). Both default to the **host** config dir (`$NEXSCOUT_DIR` or
`~/.nexscout`), which is the *same* directory the containers mount — so there is
no need to exec inside a container.

### Wipe the runtime data — `clear_db.py` / `clear-db`

Clears the per-run state so you can start fresh, **without** touching your
config. It deletes (if present): `nexscout.sqlite` (+ `-wal`/`-shm`),
`budget.sqlite` (+ wal/shm), the `applications/` directory (tailored
bundles/PDFs/screenshots), `last-tick.json`, `run-status.json`,
`dashboard.html`, and the `chrome-workers/` + `apply-workers/` browser-profile
dirs (long-path-safe `rmtree` on Windows). It **never** deletes `profile.yaml`,
`settings.yaml`, `credentials.yaml`, or the OpenClaw config. It prints exactly
what it removed and asks for a `y/N` confirmation unless `--yes`/`-y` is given.

```powershell
powershell -File scripts\windows\clear-db.ps1                 # asks, then wipes ~/.nexscout
powershell -File scripts\windows\clear-db.ps1 -Yes            # no prompt
powershell -File scripts\windows\clear-db.ps1 -Docker -Yes    # stop autopilot, wipe, remind to restart
```
```bash
./scripts/linux/clear-db.sh                 # asks, then wipes ~/.nexscout
./scripts/linux/clear-db.sh --yes           # no prompt
./scripts/linux/clear-db.sh --docker --yes  # stop autopilot, wipe, remind to restart
./scripts/linux/clear-db.sh /some/dir -y    # explicit target dir
```

With `--docker`/`-Docker` the wrapper first stops the `nexscout` autopilot
service (so nothing writes during the wipe), wipes the **host** dir (mounted
into the containers), then reminds you to restart with
`docker compose --profile openclaw up -d`. You can also call the script
directly: `python scripts/common/clear_db.py [dir] [--yes]`.

### Switch the AI model — `set_model.py` / `set-model`

Rewrites the `llm` block in `settings.yaml`
(`primary`/`fallback`/`judge` + `llm.providers.<scheme>.{base_url,model}`) and,
for the OpenAI-compatible schemes, writes the `api_key` into `credentials.yaml`
under `llm.providers.<scheme>.api_key`. All other YAML keys are preserved. By
default `primary = fallback = judge` are set to the same spec; pass
`--judge-model` to give the judge a different model.

Presets (the `--provider` value):

| Preset          | Spec written                       | Endpoint / notes |
|-----------------|------------------------------------|------------------|
| `lmstudio`      | `lmstudio:<model>`                 | default model `local-model`; base_url via `LMSTUDIO_URL` env |
| `openrouter`    | `openai_compat:<model>`            | base_url `https://openrouter.ai/api/v1` |
| `nim`           | `nim:<model>`                      | base_url `https://integrate.api.nvidia.com/v1` |
| `openai`        | `openai:<model>`                   | key from `OPENAI_API_KEY` env |
| `gemini`        | `<model>` (bare, e.g. `gemini-2.0-flash`) | key from `GEMINI_API_KEY` env |
| `anthropic`     | `anthropic:<model>`                | key from `ANTHROPIC_API_KEY` env |
| `ollama`        | `ollama:<model>`                   | local Ollama |
| `openai_compat` | `openai_compat:<model>`            | generic; **requires** `--base-url` |

Model ids may contain `:` (the router splits the scheme on the **first** colon
only), so `--model google/gemma-4-26b-a4b-it:free` for the `openrouter` preset
writes `primary: openai_compat:google/gemma-4-26b-a4b-it:free` verbatim.

```powershell
powershell -File scripts\windows\set-model.ps1 -Provider openrouter `
    -Model "google/gemma-4-26b-a4b-it:free" -ApiKey "sk-or-..."
powershell -File scripts\windows\set-model.ps1 -Provider lmstudio -Model local-model
powershell -File scripts\windows\set-model.ps1 -Provider gemini -Model gemini-2.0-flash -Docker
```
```bash
./scripts/linux/set-model.sh --provider openrouter \
    --model google/gemma-4-26b-a4b-it:free --api-key sk-or-...
./scripts/linux/set-model.sh --provider lmstudio --model local-model
./scripts/linux/set-model.sh --provider gemini --model gemini-2.0-flash --docker
```

In Docker the autopilot reloads the profile each pass, so the switch applies
**live** within a pass or two. To make it immediate, pass `--docker`/`-Docker`
(the wrapper runs `docker compose up -d nexscout nexscout-web nexscout-mcp`) or
recreate the stack yourself with `docker compose up -d`. Direct invocation:
`python scripts/common/set_model.py --provider <preset> --model <id> [--api-key …] [--base-url …] [--judge-model …] [--target …]`.

**OpenClaw shares NexScout's LLM.** If an OpenClaw config is present
(`~/.openclaw/openclaw.json`, or `$OPENCLAW_DIR` / `--openclaw-dir`), the same
switch also repoints the OpenClaw gateway agent at the **same model** so it can
drive the NexScout MCP tools. The script manages a single OpenClaw provider
named `nexscout` (so repeated switches overwrite in place — no orphan entries)
and sets `agents.defaults.model.primary` to `nexscout/<model>`. Only the
OpenAI-compatible presets sync (`openai_compat`, `openrouter`, `nim`, `openai`,
`lmstudio`, `ollama`); `anthropic` and `gemini` need OpenClaw's native provider
(`openclaw onboard`) and are skipped with a note. Pass `--no-openclaw` to update
NexScout only. The gateway reads its model **at startup**, so restart it to pick
up the change: `docker restart nexscout-openclaw`.

## Stopping

```powershell
powershell -File scripts\windows\stop.ps1            # local direct/uv processes (web + autopilot)
powershell -File scripts\windows\stop.ps1 -Docker    # docker compose down (all services)
```
```bash
./scripts/linux/stop.sh                # local direct/uv processes (web + autopilot)
./scripts/linux/stop.sh --docker       # docker compose down (add --volumes to drop volumes)
```

The host teardown kills the background web UI (via `.nexscout-web.pid`) plus
any lingering `nexscout` processes, including the `nexscout autopilot` loop. The
Docker teardown runs `docker compose --profile openclaw --profile local-llm
down`, so it stops **every** service (nexscout autopilot, nexscout-web,
nexscout-mcp, openclaw gateway, and ollama if it was started) regardless of
which profiles were used to start.

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
   `http://localhost:18789/#token=<TOKEN>` (the URL **fragment** form the
   gateway documents — note the `#`, not `?`; if it doesn't auto-auth, paste the
   raw token into the Control UI instead). If the config has no token it falls
   back to the `OPENCLAW_GATEWAY_TOKEN` environment variable.

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
