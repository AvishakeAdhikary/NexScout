# Runbook: Local bring-up of NexScout via Docker

This is the smoke-test transcript captured during the 2026-06-09 end-to-end
bring-up. It documents the exact PowerShell incantations needed on Windows
when Docker Desktop is installed but `docker.exe` is *not* on `PATH`, plus
the expected outputs at each stage.

> All shell commands below are **PowerShell**. The full path to `docker.exe`
> is hard-coded because Docker Desktop installs it under
> `C:\Program Files\Docker\Docker\resources\bin\` and does not put that
> directory on `PATH` by default.

## 0. Prerequisites

* Docker Desktop running.
* `~/.nexscout/profile.yaml` populated (see `nexscout init`).
* (Optional) LM Studio running on the host at `http://localhost:1234`
  with a chat model loaded and the OpenAI-compatible server started.
  Without it, `nexscout apply` and the score / tailor stages will fail
  with a network error to `host.docker.internal:1234`.
* (Optional) Channel credentials exported in the shell that runs
  `docker compose` if you want OpenClaw alerts. Pick one channel and set
  `openclaw.channel` to match:
  * Telegram — `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
  * Discord — `DISCORD_WEBHOOK_URL` (preferred), or `DISCORD_BOT_TOKEN` +
    `DISCORD_CHANNEL_ID`.

## 1. Bring the container up

```powershell
$env:PATH = 'C:\Program Files\Docker\Docker\resources\bin;' + $env:PATH
$env:HOME = $env:USERPROFILE
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose `
    -f 'c:\Projects\NexScout\docker-compose.yml' up -d nexscout
```

Expected:

```
Container nexscout  Created
Container nexscout  Started
```

The compose `command` is `["run"]`, which executes the full discover →
enrich → score → tailor → apply pipeline once and then exits. If LM Studio
isn't reachable the score / tailor / apply calls fail and `nexscout run`
exits 0 with a warning. Restart policy `unless-stopped` then re-runs it in
a loop — visible as `Restarting (0) ... ago` in `docker compose ps`.

For interactive testing (so you can `docker exec` into a live container),
temporarily flip the service definition:

```yaml
    entrypoint: ["sleep", "infinity"]
    command: []
```

…then `docker compose up -d --force-recreate nexscout`. Revert to
`command: ["run"]` before normal operation.

## 2. Health check

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose `
    -f 'c:\Projects\NexScout\docker-compose.yml' exec -T nexscout nexscout doctor --quiet
```

`doctor --quiet` exits **0** when the profile loads and required directories
exist. Captcha-provider warnings are non-fatal — the apply path treats
unsolved CAPTCHAs as parked, not as errors.

## 3. Web dashboard

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose `
    -f 'c:\Projects\NexScout\docker-compose.yml' exec -d nexscout `
    nexscout web --host 0.0.0.0 --port 8765
```

The bind needs `--host 0.0.0.0` (default is `127.0.0.1`, which is not
reachable from the host port mapping). Then from PowerShell:

```powershell
Invoke-WebRequest -Uri http://localhost:8765/        -UseBasicParsing
Invoke-WebRequest -Uri http://localhost:8765/healthz -UseBasicParsing
```

Both should return HTTP 200. The dashboard HTML at `/` includes the
counter labels `total`, `scored`, `applied`, plus an **OpenClaw status
panel** (last tick, active channel, pending channel deliveries). The `/`
route is not auth-gated; the protected routes (write actions, the controls
panel) check the session cookie set by `nexscout web --init-pw`.

This is NexScout's own web UI on `:8765`. When you bring up the `openclaw`
profile (§7) a *second*, separate dashboard — OpenClaw's native gateway
Control UI — is served on <http://localhost:18789/>.

Static export:

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose exec -T nexscout `
    nexscout dashboard --export /sandbox/nexscout/dashboard.html
```

That file is reachable on the host at `~/.nexscout/dashboard.html`.

## 4. Discover

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose exec -T nexscout `
    nexscout run discover
```

Expected outputs vary by network / rate-limit conditions. In a clean
bring-up on 2026-06-09 from an Indian IP, the JobSpy engine returned
**257 rows** across `linkedin` (241) and `indeed` (16). The Glassdoor,
Google, and ZipRecruiter calls returned 0 rows (rate-limited /
geo-filtered) and were logged as warnings, not raised. The browser-driven
WebSearch fallback returns 0 when `boards.websearch.providers` is empty
and no other browser-search adapter is installed.

To inspect what landed in the DB:

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose exec -T nexscout `
    python -c "import sqlite3,os; c=sqlite3.connect(os.path.join(os.environ['NEXSCOUT_DIR'],'nexscout.sqlite')); print(c.execute('SELECT site, COUNT(*) FROM jobs GROUP BY site').fetchall())"
```

## 5. Score → tailor → apply (the LLM-gated pipeline)

`nexscout apply` only picks up rows where `tailored_resume_path IS NOT NULL`
**and** `fit_score >= profile.search.min_score`. Both columns are populated
by the score and tailor stages, which call the LLM router. The user's
profile points the router at `lmstudio:local-model`, so the score and
tailor stages will only succeed when LM Studio is reachable at
`http://host.docker.internal:1234/v1` from inside the container.

### Bringing LM Studio online

1. Open LM Studio on Windows (host).
2. Load any instruction-tuned chat model (e.g. `lmstudio-community/gemma-2-9b-it-GGUF`).
3. Click **Start Server** (defaults to port 1234, OpenAI-compatible).
4. Verify on the host:
   ```powershell
   Invoke-WebRequest -Uri http://localhost:1234/v1/models -UseBasicParsing
   ```
5. Verify from inside the container:
   ```powershell
   & 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose exec -T nexscout `
       python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:1234/v1/models',timeout=5).status)"
   ```
6. Update `~/.nexscout/profile.yaml` so `llm.primary` (and `fallback` /
   `judge` if you like) matches the model id LM Studio is hosting,
   e.g. `lmstudio:gemma-2-9b-it`.
7. Run the pipeline end-to-end:
   ```powershell
   & 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose exec -T nexscout `
       nexscout run               # discover + enrich + score + tailor + apply
   ```
   Or stage-by-stage:
   ```powershell
   & 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose exec -T nexscout `
       nexscout apply --workers 1 --limit 3 --headless
   ```

### Expected apply outcomes

* `RESULT:CAPTCHA_MANUAL` — most ATS-walled jobs (Workday, Greenhouse,
  Lever) hit a hCaptcha / reCAPTCHA and park to
  `apply_status='captcha_manual'`. With Telegram configured, OpenClaw
  forwards the questions to the chat. **This is the expected happy path
  when no CAPTCHA solver is configured.**
* `RESULT:APPLIED` — possible for non-CAPTCHA postings that accept a
  resume PDF without forcing a sign-in (small companies, HN Jobs replies,
  some `weworkremotely.com` postings).
* `RESULT:LOGIN_ISSUE` — postings that require an account behind SSO.
  Treated as permanent failure.
* `RESULT:CAPTCHA` — the agent saw a CAPTCHA and a solver was configured
  but the solve failed. Without `captcha.api_key` set, `RESULT:CAPTCHA` is
  almost never produced (the agent parks to `CAPTCHA_MANUAL` instead).

### Verifying the outcomes

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose exec -T nexscout `
    python -c "import sqlite3,os; c=sqlite3.connect(os.path.join(os.environ['NEXSCOUT_DIR'],'nexscout.sqlite')); print(c.execute('SELECT apply_status, COUNT(*) FROM jobs WHERE apply_status IS NOT NULL GROUP BY apply_status').fetchall())"
```

Per-job artifacts live under `/sandbox/nexscout/applications/<row_id>/`
inside the container, mounted at `~/.nexscout/applications/<row_id>/` on
the host. Each bundle contains `resume.pdf`, `result.json`, and any
screenshots / DOM snapshots the agent captured.

## 6. Tear down

```powershell
& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose `
    -f 'c:\Projects\NexScout\docker-compose.yml' down
```

Use `down -v` only if you want to discard the named volumes (the SQLite
DB lives on the host volume mount, not in a named volume, so it survives
`down -v` anyway).

## 7. Adding OpenClaw

After step 1 / 2 succeed, export the credentials for whichever channel you
set in `openclaw.channel`, then bring up the `openclaw` profile:

```powershell
# Telegram channel:
$env:TELEGRAM_BOT_TOKEN = '...'
$env:TELEGRAM_CHAT_ID   = '...'
# …or Discord channel (webhook is easiest):
$env:DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/...'
# (alternatively $env:DISCORD_BOT_TOKEN + $env:DISCORD_CHANNEL_ID)

# Optional: token for the OpenClaw gateway Control UI auth.
$env:OPENCLAW_GATEWAY_TOKEN = '...'

& 'C:\Program Files\Docker\Docker\resources\bin\docker.exe' compose `
    -f 'c:\Projects\NexScout\docker-compose.yml' --profile openclaw up -d
```

The OpenClaw container depends on `nexscout` being healthy (driven by the
compose healthcheck that runs `nexscout doctor --quiet` every 60 s), so it
only starts once the nexscout container reports healthy. It runs
`openclaw gateway --port 18789`, so OpenClaw's own Control UI / dashboard is
then reachable on the host at <http://localhost:18789/> (this is OpenClaw's
native dashboard, not the NexScout web UI on `:8765`). The gateway may
require `OPENCLAW_GATEWAY_TOKEN` for auth; `openclaw dashboard` opens it with
a pre-authenticated link.
