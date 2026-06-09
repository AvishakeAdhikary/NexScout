#requires -Version 5.1
<#
.SYNOPSIS
    Start the full NexScout + OpenClaw stack via Docker Compose on Windows.
.DESCRIPTION
    Handles the Docker Desktop quirks on Windows:
      * docker.exe is often NOT on PATH — we prepend its install dir.
      * compose mounts use ${HOME} — we set $env:HOME = $env:USERPROFILE.
    Then: `docker compose --profile openclaw up -d` (nexscout + openclaw
    gateway on :18789), starts the web UI inside the container on :8765,
    waits for health, and opens BOTH dashboards.
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

# --- 3. Bring up the stack (nexscout + openclaw gateway) ------------------- #
Write-Host "[docker] docker compose --profile openclaw up -d ..." -ForegroundColor Cyan
docker compose -f $compose --profile openclaw up -d
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose up failed (exit $LASTEXITCODE). See the output above."
    exit 1
}

# --- 4. Start the web UI inside the nexscout container ---------------------- #
# The compose `command` is `run` (one-shot pipeline); the web server must be
# started explicitly and bound to 0.0.0.0 so the host port mapping works.
Write-Host "[web] docker compose exec -d nexscout nexscout web --host 0.0.0.0 --port 8765 ..." -ForegroundColor Cyan
docker compose -f $compose exec -d nexscout nexscout web --host 0.0.0.0 --port 8765
if ($LASTEXITCODE -ne 0) {
    Write-Warning "[web] Could not start the web UI in the container (exit $LASTEXITCODE). The container may still be initializing; retrying once in 5s."
    Start-Sleep -Seconds 5
    docker compose -f $compose exec -d nexscout nexscout web --host 0.0.0.0 --port 8765
}

# --- 5. Wait for health + open dashboards ---------------------------------- #
if (-not (Wait-WebHealthy -TimeoutSeconds 120)) {
    Write-Warning "[web] Health check failed; opening dashboards anyway."
}
Open-Dashboards

Write-Host ""
Write-Host "Stack is up via Docker Compose (profile: openclaw)." -ForegroundColor Green
Write-Host "  See running containers : docker compose ps"
Write-Host "  Tail logs              : docker compose logs -f"
Write-Host "  Stop everything        : powershell -File scripts\windows\stop.ps1 -Docker" -ForegroundColor Green
