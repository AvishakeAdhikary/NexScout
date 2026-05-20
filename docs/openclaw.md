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
docker compose --profile openclaw up
```

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
`examples/profile.example.yaml`.
