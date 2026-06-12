# OpenClaw / NemoClaw Integration

NexScout is designed to run **inside OpenClaw**, the open-source, MIT-licensed
local-first personal-AI agent platform. OpenClaw provides:

- A **heartbeat daemon** (systemd on Linux, LaunchAgent on macOS, Task Scheduler
  on Windows) that wakes on a configurable interval (default 30 minutes) and
  invokes registered "skills".
- A **channel layer** that delivers natural-language messages to and from the
  user via Slack, Discord, WhatsApp, Telegram, iMessage, Signal, Matrix or
  WebChat.
- A **memory layer** stored as plain Markdown under `~/.openclaw/memory/`.

NemoClaw is NVIDIA's reference stack that runs OpenClaw inside the
**OpenShell** sandbox. The sandbox uses Landlock + seccomp + a network
namespace to confine the agent to `/sandbox` and `/tmp` and to police outbound
network access. From NexScout's point of view, NemoClaw is just "OpenClaw with
stricter filesystem and network policies" — no code change is required, only
the `~/.nexscout/` directory must be mounted into `/sandbox/nexscout/`.

## Two run modes

1. **Hosted-agent mode (recommended).** A `nexscout` skill is registered with
   OpenClaw via the manifest at `src/nexscout/openclaw/manifest.toml`. The
   heartbeat calls `nexscout tick`, which performs **one bounded unit of
   work** (enrich up to N jobs, score up to M, apply to up to K) and returns.
   All persistent state lives in `~/.nexscout/`.
2. **Standalone mode.** Plain `nexscout run --continuous` loop. No heartbeat.
   Same code paths.

## MCP server (autonomous tool use)

The **headline integration**: NexScout runs a **Model Context Protocol (MCP)
server** that the OpenClaw gateway connects to, giving the agent concrete tools
to drive NexScout *autonomously*. Before this, asking OpenClaw to "apply at
jobs, get my resume from NexScout" produced "I have no access to NexScout".
Now the agent simply calls the NexScout tools.

### Why HTTP (not stdio)

OpenClaw normally spawns local MCP servers as stdio child processes. That can't
work here: NexScout (Python) runs in the `nexscout` container and OpenClaw
(Node) runs in the `nexscout-openclaw` container — separate processes on a
shared Docker network. So the server uses the **Streamable HTTP** transport,
binds `0.0.0.0:8770`, and is reached by URL.

### Compose service

The `nexscout-mcp` service (in `docker-compose.yml`) reuses the shared
`*nexscout-base` anchor (same image, volumes, and env — including
`NEXSCOUT_DIR` and `LMSTUDIO_URL`) and runs the `nexscout-mcp` console-script
entry point. It publishes `8770` and `restart: unless-stopped`. The `openclaw`
service `depends_on` it, so the MCP server is up before the gateway starts.

```bash
docker compose --profile openclaw up -d   # brings up nexscout-mcp + openclaw
```

Run it standalone for local testing with either:

```bash
nexscout-mcp                  # console_scripts entry point
python -m nexscout.mcp.server # module form
```

Both bind `NEXSCOUT_MCP_HOST` / `NEXSCOUT_MCP_PORT` (default `0.0.0.0:8770`)
and serve the MCP endpoint at `/mcp`.

### Gateway registration

The recommended way to register NexScout is the OpenClaw CLI — it validates the
schema and **probes the server** (lists its tools) before saving:

```bash
openclaw mcp add nexscout --url http://nexscout-mcp:8770/mcp --transport streamable-http
openclaw mcp probe          # should report: nexscout: 10 tools
```

The OpenClaw container resolves `nexscout-mcp` on `nexscout-net`. The CLI writes
the entry under the `mcp.servers` map in `~/.openclaw/openclaw.json` (note: it is
`mcp.servers.<name>`, **not** a top-level `mcpServers` key — that fails schema
validation and the gateway refuses to start):

```jsonc
{
  "mcp": {
    "servers": {
      "nexscout": {
        "url": "http://nexscout-mcp:8770/mcp",
        "transport": "streamable-http"
      }
    }
  }
}
```

Restart the gateway after editing the config by hand
(`docker compose --profile openclaw up -d --force-recreate openclaw`); `openclaw
mcp add` + `openclaw mcp reload` avoid the manual edit entirely.

### Exposed tools

| Tool                              | What it does                                             |
|-----------------------------------|----------------------------------------------------------|
| `get_profile()`                   | Structured candidate profile (name, titles, skills, …)   |
| `get_resume_text()`               | Plain-text résumé NexScout tailors per application       |
| `pipeline_status()`               | Pipeline counts (total/scored/tailored/applied/…)        |
| `discover_jobs(limit_per_engine)` | Run discovery; returns new-job count                     |
| `score_jobs(limit)`               | Score enriched jobs for fit (0-10)                       |
| `tailor_jobs(limit)`              | Tailor the résumé for high-fit jobs                      |
| `apply_to_job(url)`               | One-shot apply to a specific job URL                     |
| `list_open_questions()`           | List unanswered clarifying questions                     |
| `answer_question(id, answer)`     | Answer a question; persists to learned-answers memory    |
| `run_once(wall_clock_s)`          | One bounded end-to-end pipeline pass (the heartbeat tick)|

Each tool is defensive: it catches its own exceptions and returns a clear
`{"ok": false, "error": …}` envelope instead of crashing the long-lived server,
and heavy stages (browser/LLM) are imported lazily so the server starts even
when an optional dependency is missing on the host. All tools read the same
`~/.nexscout` state (via `NEXSCOUT_DIR`) as the rest of the stack, so the
agent's actions show up immediately in the web UI and the pipeline. The tool
implementations live in `src/nexscout/mcp/server.py`.

### Agent model (shares NexScout's LLM)

The MCP server gives the agent **tools**; the agent still needs its own **LLM**
to decide *when* to call them. OpenClaw's agent model lives in
`~/.openclaw/openclaw.json` under `models.providers.<name>` (an
`openai-completions` endpoint) with `agents.defaults.model.primary` selecting
`<provider>/<model>`.

To keep one brain across the stack, point the agent at the **same LLM NexScout
uses**. `scripts/common/set_model.py` (and the `set-model` wrappers) do this
automatically: they manage a single OpenClaw provider named **`nexscout`** and
set `agents.defaults.model.primary` to `nexscout/<model>`, so one switch updates
both NexScout and OpenClaw. Pass `--no-openclaw` to skip it. Only the
OpenAI-compatible presets sync; `anthropic` / `gemini` need OpenClaw's native
provider (`openclaw onboard`).

```jsonc
{
  "agents": { "defaults": { "model": { "primary": "nexscout/gemma3:12b" } } },
  "models": {
    "providers": {
      "nexscout": {
        "api": "openai-completions",
        "baseUrl": "https://ollama.com/v1",
        "apiKey": "<key>",
        "models": [{ "id": "gemma3:12b", "name": "gemma3:12b (shared with NexScout)" }]
      }
    }
  }
}
```

Pick a **tool-capable** model: it must emit structured `tool_calls` for the MCP
tools to fire. On Ollama Cloud, `gemma3:12b` does; some larger models return
tool calls as plain text instead, which the gateway can't dispatch — verify with
`openclaw infer model run --model nexscout/<model> --prompt …` plus `openclaw
mcp probe`. The gateway reads its model **at startup**, so restart it after a
change: `docker restart nexscout-openclaw`.

## Sandbox mount

When running under NemoClaw / OpenShell, NexScout's working directory is
mounted into the sandbox like so:

```
host: ~/.nexscout              → sandbox: /sandbox/nexscout
host: ~/.openclaw              → sandbox: /root/.openclaw   (memory only)
```

The `docker-compose.yml` `openclaw` profile sets this up automatically. The
`Dockerfile` declares `VOLUME ["/sandbox/nexscout"]` and points
`NEXSCOUT_DIR=/sandbox/nexscout` so the in-container CLI finds the same
profile, database, and bundles as the host.

```bash
docker compose --profile openclaw up -d
```

The compose file ships three named containers:

| Service    | Container name        | Purpose                                  |
|------------|-----------------------|------------------------------------------|
| `nexscout` | `nexscout`            | the agent itself (runs `nexscout run`)   |
| `ollama`   | `nexscout-ollama`     | local LLM endpoint (opt-in)              |
| `openclaw` | `nexscout-openclaw`   | OpenClaw gateway / heartbeat — runs `openclaw gateway --port 18789`, serves its Control UI on <http://localhost:18789/> (opt-in via profile) |

The `nexscout` service has a `healthcheck` that runs
`nexscout doctor --quiet` every 60 seconds. The OpenClaw container `depends_on`
`nexscout` reaching `service_healthy`, so a fresh `docker compose up` waits
for NexScout's prereqs to come online before starting the heartbeat. Both
volumes (`~/.nexscout` and `~/.openclaw`) are mounted into the OpenClaw
container so it can read/write memory and surface questions back to the
user.

## Skill manifest

The shipped manifest (`src/nexscout/openclaw/manifest.toml`) registers five
slash commands:

| Slash-command            | Action                                         |
|--------------------------|------------------------------------------------|
| `/nexscout status`       | Pipeline stats + last 5 events                 |
| `/nexscout apply <url>`  | One-shot apply to a specific URL               |
| `/nexscout pause`        | Toggle the continuous loop off                 |
| `/nexscout resume`       | Toggle the continuous loop on                  |
| `/nexscout question`     | List open clarifying questions                 |
| `/nexscout answer "<q>" "<a>"` | Answer a queued question (persisted to memory) |

The `[heartbeat]` section sets `interval_minutes = 30` and
`command = "nexscout tick"`. OpenClaw passes a deadline; `nexscout tick` aims
to finish within ~5 minutes per `profile.openclaw.tick_budget`.

## Memory contract

When the apply agent needs an answer that is not in the profile or in
`learned-answers.md`, it:

1. Queues the question into the SQLite `pending_questions` table.
2. Marks the job `paused_for_question`.
3. On the next heartbeat OpenClaw delivers the question to the user via the
   active channel.
4. On `/nexscout answer`, NexScout writes the Q&A pair to
   `learned-answers.md` and stores the answer in the job row's
   `profile_addendum_json` column for traceability.
5. On the next tick, the job resumes — the addendum is merged into the apply
   agent's profile context.

### Manual CAPTCHA queue

When `profile.captcha.api_key` is unset (or a sitekey type is unsupported
by the configured solver) and the apply agent hits a CAPTCHA wall, it
calls `done(RESULT:CAPTCHA_MANUAL, …)`. The orchestrator then:

1. Sets `apply_status='captcha_manual'`. The result code is in the
   permanent-failure set so it is not retried automatically.
2. Inserts an idempotent row into `pending_questions` with the question
   text `Job requires manual CAPTCHA solving: <job_url>` and
   `channel='cli'`.
3. The next heartbeat tick surfaces the row via `_stage_surface_questions`
   into `~/.openclaw/inbox/nexscout-<ts>.md`, which OpenClaw delivers to
   the active channel.
4. Once you solve the CAPTCHA manually (in your own browser) and answer
   the question with the next step (or "skip"), the orchestrator either
   resumes the job or marks it `apply_status='manual'`.

Memory file layout under `~/.openclaw/memory/nexscout/`:

```
profile.yaml              # symlink → ~/.nexscout/profile.yaml
learned-answers.md        # harvested Q&A pairs (no secrets)
learned-employers.md      # facts about specific employers
do-not-ask-again.md       # questions the user silenced
feedback.md               # user corrections ("Don't apply to X")
```

The Markdown reader/writer lives in `src/nexscout/openclaw/memory.py` and
parses each file into structured entries while preserving the human-readable
Markdown on disk.

## Telegram channel

NexScout ships a built-in Telegram delivery channel so questions and
manual-CAPTCHA alerts reach you on your phone without an external
OpenClaw runtime. Enable it in two steps:

1. **Create a bot.** In Telegram, message [@BotFather](https://t.me/BotFather)
   and run `/newbot`. Save the bot token it returns (looks like
   `123456789:AAH...`).
2. **Find your chat id.** Send any message to your new bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and
   read `result[0].message.chat.id`. It's a small integer (or a `-`
   prefixed integer for a group).

Set both values in the environment (e.g. via the `docker-compose.yml`
`env_file:` block):

```bash
export TELEGRAM_BOT_TOKEN="123456789:AAH..."
export TELEGRAM_CHAT_ID="987654321"
```

…and switch the profile to the new channel:

```yaml
# ~/.nexscout/profile.yaml
openclaw:
  channel: telegram
```

What gets pushed:

| Trigger                                | Message                                |
|----------------------------------------|----------------------------------------|
| `_stage_surface_questions`             | one message per unanswered question    |
| Apply agent returns `CAPTCHA_MANUAL`   | immediate "manual CAPTCHA required"    |
| `send_apply_summary(...)` (tick hook)  | tick summary one-liner                 |

Delivery is idempotent — once a row's `pending_questions.channel_delivered_at`
column is non-null, that question is not pushed again. The channel
retries on transient errors (HTTP 429 with `retry_after`, HTTP 5xx,
network errors) up to 3 times with 2/4/8 second backoff. CAPTCHA-free
jobs still flow through the apply pipeline automatically; the Telegram
channel only fires on questions and manual-CAPTCHA alerts.

To answer a queued question, reply to the bot with
`/answer <id> <your reply>` — OpenClaw forwards it back to
`nexscout question answer`, which updates the row and resumes the job
on the next tick. You can also answer via the web UI's `/questions`
page.

## Discord channel

NexScout also ships a built-in Discord delivery channel that mirrors the
Telegram one — same triggers, same retry/backoff, same idempotency. It
talks to Discord directly (no external OpenClaw runtime required) and
supports two credential modes; the **webhook** mode is the easiest.

1. **Webhook (preferred).** In your Discord server open **Server Settings
   → Integrations → Webhooks → New Webhook**, pick the target channel, and
   **Copy Webhook URL**. That single URL is all you need.
2. **Bot token + channel id (alternative).** Create an application + bot at
   the [Discord Developer Portal](https://discord.com/developers/applications),
   invite it to your server with the *Send Messages* permission, and copy
   the bot token plus the numeric channel id (right-click the channel →
   *Copy Channel ID* with Developer Mode on).

Set the credentials in the environment (same host-env passthrough as
Telegram in `docker-compose.yml`). Webhook wins if both are present:

```bash
# Mode 1 — webhook (preferred)
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/123/abc..."

# Mode 2 — bot token + channel id (used only when no webhook URL is set)
export DISCORD_BOT_TOKEN="MT!..."
export DISCORD_CHANNEL_ID="987654321098765432"
```

…and switch the channel in your config:

```yaml
# ~/.nexscout/settings.yaml  (or the openclaw block of a monolithic profile.yaml)
openclaw:
  channel: discord
```

What gets pushed (identical to Telegram):

| Trigger                                | Message                                |
|----------------------------------------|----------------------------------------|
| `_stage_surface_questions`             | one message per unanswered question    |
| Apply agent returns `CAPTCHA_MANUAL`   | immediate "manual CAPTCHA required"    |
| `send_apply_summary(...)` (tick hook)  | tick summary one-liner                 |

Messages are formatted with **Discord markdown** (`**bold**`, inline
`code`, and plain URLs) rather than the HTML Telegram uses, so no escaping
is applied. Delivery is idempotent — once a row's
`pending_questions.channel_delivered_at` is non-null the question is not
pushed again. The channel retries on transient failures (HTTP 429 honouring
Discord's `retry_after`, HTTP 5xx, and network errors) up to 3 times with
2/4/8 second backoff. Webhook delivery treats HTTP 204 as success; bot-mode
delivery treats HTTP 200. To answer a queued question, reply
`/answer <id> <your reply>` (or use the web UI's `/questions` page) — the
flow back into `nexscout question answer` is the same as for Telegram.

## Tick budget

A heartbeat tick performs the smallest useful slice of work and returns
within a soft 5-minute budget:

1. Pull <=10 new jobs from each discovery engine.
2. Enrich up to 20 pending jobs.
3. Score up to 50 pending jobs.
4. Tailor up to 5 high-fit jobs (LLM cost heavy).
5. Render any missing PDFs.
6. Apply to up to 3 jobs (browser cost heavy).
7. Surface pending questions to OpenClaw channels.
8. Print a one-line summary to stdout for OpenClaw to log.

Limits are configurable per `profile.openclaw.tick_budget` — see
`examples/split/settings.yaml`.

## Config file layout

NexScout reads up to **three** deep-merged YAML files from its config
directory (`$NEXSCOUT_DIR` if set, else `~/.nexscout`), with merge priority
`profile.yaml` < `settings.yaml` < `credentials.yaml` (later files win):

| File               | Holds                                                       |
|--------------------|-------------------------------------------------------------|
| `profile.yaml`     | résumé / applicant facts (`me`, `auth`, `skills`, `facts`, …) plus optional CV extras (`certifications`/`publications`/`languages`) |
| `settings.yaml`    | operational config (`search`, `llm`, `apply`, `openclaw`) + `captcha.provider` + non-secret `smtp.*` fields |
| `credentials.yaml` | secrets — `captcha.api_key`, `smtp.password`, `gmail_password`, account `password`, `proxy` |

`${env:NAME}` substitution works in any of the three files. The split is
optional and fully backward-compatible: a single monolithic `profile.yaml`
loads exactly as before. The `openclaw.channel` selector lives in
`settings.yaml`; channel tokens (Telegram / Discord) come from the
environment, never from these files. A clean, commented reference set lives
in `examples/split/` — `cp examples/split/*.yaml ~/.nexscout/` to start.

## OpenClaw gateway dashboard

The `openclaw` compose service runs OpenClaw's own gateway
(`openclaw gateway --port 18789`) and maps the port, so its **native
Control UI / dashboard** is reachable at <http://localhost:18789/> once the
stack is up. This is OpenClaw's own dashboard, *not* a NexScout-built one —
it shows heartbeat/skill state from the OpenClaw side. Access may require an
`OPENCLAW_GATEWAY_TOKEN` (read from the host environment by the compose
service); running `openclaw dashboard` opens it with a pre-authenticated
link.

Separately, NexScout's own web UI (<http://localhost:8765/>) shows an
**OpenClaw status panel** on its dashboard — last tick timestamp, the active
channel, and the count of pending channel deliveries — sourced from the
`pending_questions` table and the last-tick marker, independent of the
OpenClaw gateway.
