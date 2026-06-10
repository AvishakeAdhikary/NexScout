#requires -Version 5.1
<#
.SYNOPSIS
    Start the full NexScout + OpenClaw stack via Docker Compose on Windows.
.DESCRIPTION
    Handles the Docker Desktop quirks on Windows:
      * docker.exe is often NOT on PATH — we prepend its install dir.
      * compose mounts use ${HOME} — we set $env:HOME = $env:USERPROFILE.
    Then: `docker compose --profile openclaw up -d`, which brings up FOUR
    things: the `nexscout` container (running the crash-resilient `autopilot`
    loop), `nexscout-web` (the web UI on :8765), and the `openclaw` gateway
    (Control UI on :18789). The web server runs as its own service now, so
    there is no separate exec step. Waits for health, then opens BOTH
    dashboards (the OpenClaw one tokenized via dashboard-link.ps1).
.PARAMETER Setup
    Force the interactive config generator to run first (even if config exists).
#>
param([switch] $Setup)

$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSCommandPath) '_common.ps1')

$repo = Get-RepoRoot
Set-Location $repo
Write-Host "=== NexScout : Docker launcher ===" -ForegroundColor Magenta
Write-Host "[repo] $repo"

# --- 0. Docker Desktop PATH + HOME quirks ---------------------------------- #
if (-not (Get-Command 'docker' -ErrorAction SilentlyContinue)) {
    $dockerBin = 'C:\Program Files\Docker\Docker\resources\bin'
    if (Test-Path (Join-Path $dockerBin 'docker.exe')) {
        Write-Host "[docker] docker not on PATH — prepending '$dockerBin'." -ForegroundColor Cyan
        $env:PATH = "$dockerBin;$env:PATH"
    } else {
        Write-Error "Docker not found on PATH and not at '$dockerBin'. Install Docker Desktop and ensure it is running."
        exit 1
    }
}
# compose uses ${HOME} for the volume mounts; on Windows that env var is empty.
if (-not $env:HOME) {
    $env:HOME = $env:USERPROFILE
    Write-Host "[docker] Set HOME=$env:HOME for compose volume mounts." -ForegroundColor Cyan
}

# Verify the daemon is actually reachable (Docker Desktop running).
try {
    docker info --format '{{.ServerVersion}}' | Out-Null
} catch {
    Write-Error "Docker daemon is not responding. Start Docker Desktop and wait for it to be ready, then re-run."
    exit 1
}

$compose = Join-Path $repo 'docker-compose.yml'

# --- 1. Config -------------------------------------------------------------- #
# The container reads ~/.nexscout (mounted). Generate it on the host first.
Invoke-ConfigGenerator -RepoRoot $repo -Runner @('python') -Force:$Setup

# --- 2. LM Studio note ------------------------------------------------------ #
# From inside the container the LLM endpoint is host.docker.internal:1234.
Test-LMStudio
Write-Host "[lmstudio] Inside Docker, NexScout reaches LM Studio at http://host.docker.internal:1234/v1." -ForegroundColor DarkGray

# --- 3. Bring up the full stack -------------------------------------------- #
# `up -d` with the openclaw profile starts FOUR things:
#   nexscout      — the crash-resilient `autopilot` loop (compose command)
#   nexscout-web  — the web UI on :8765 (its own service; no exec needed)
#   openclaw      — the gateway Control UI on :18789
#   (ollama is only added by the separate local-llm profile)
Write-Host "[docker] docker compose --profile openclaw up -d ..." -ForegroundColor Cyan
docker compose -f $compose --profile openclaw up -d
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose up failed (exit $LASTEXITCODE). See the output above."
    exit 1
}

# --- 4. Wait for health + open dashboards ---------------------------------- #
# nexscout-web serves :8765 directly; just wait for it.
if (-not (Wait-WebHealthy -TimeoutSeconds 120)) {
    Write-Warning "[web] Health check failed; opening dashboards anyway."
}
Open-Dashboards   # resolves the tokenized OpenClaw link via dashboard-link.ps1

Write-Host ""
Write-Host "Stack is up via Docker Compose (profile: openclaw)." -ForegroundColor Green
Write-Host "  Autopilot is now RUNNING in the 'nexscout' container: it loops the full" -ForegroundColor Green
Write-Host "  pipeline (discover->enrich->score->tailor->render->apply->questions)" -ForegroundColor Green
Write-Host "  autonomously and keeps applying. restart:unless-stopped + SQLite state" -ForegroundColor Green
Write-Host "  mean it auto-resumes after any container crash, reboot, or model unload." -ForegroundColor Green
Write-Host "  See running containers : docker compose ps"
Write-Host "  Tail autopilot logs    : docker compose logs -f nexscout"
Write-Host "  Re-print dashboard link: powershell -File scripts\windows\dashboard-link.ps1"
Write-Host "  Stop everything        : powershell -File scripts\windows\stop.ps1 -Docker" -ForegroundColor Green
