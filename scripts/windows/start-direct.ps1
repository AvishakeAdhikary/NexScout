#requires -Version 5.1
<#
.SYNOPSIS
    Start NexScout directly in a local .venv (pip install -e) on Windows.
.DESCRIPTION
    Creates/activates a .venv, installs NexScout (+ the python-jobspy two-step
    from the README), optionally (re)generates config, runs `nexscout doctor`,
    starts the web UI on :8765 in the background, waits for health, opens the
    NexScout dashboard, then runs the crash-resilient `nexscout autopilot` loop
    in the foreground (Ctrl+C to stop). The OpenClaw gateway is Docker-only —
    use start-docker.ps1 for the OpenClaw Control UI on :18789.
.PARAMETER Setup
    Force the interactive config generator to run first (even if config exists).
#>
param([switch] $Setup)

$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSCommandPath) '_common.ps1')

$repo = Get-RepoRoot
Set-Location $repo
Write-Host "=== NexScout : direct (.venv) launcher ===" -ForegroundColor Magenta
Write-Host "[repo] $repo"

# --- 0. Prerequisite: python ------------------------------------------------ #
if (-not (Assert-Command -Name 'python' -Hint 'Install Python 3.11+ from https://www.python.org/downloads/ and re-open the shell.')) {
    exit 1
}

# --- 1. Virtual environment ------------------------------------------------- #
$venv = Join-Path $repo '.venv'
$activate = Join-Path $venv 'Scripts\Activate.ps1'
if (-not (Test-Path $activate)) {
    Write-Host "[venv] Creating virtual environment at $venv ..." -ForegroundColor Cyan
    python -m venv $venv
}
Write-Host "[venv] Activating $venv" -ForegroundColor Cyan
. $activate

# --- 2. Install ------------------------------------------------------------- #
Write-Host "[install] pip install -e '.[dev,web]' ..." -ForegroundColor Cyan
python -m pip install --upgrade pip | Out-Null
pip install -e ".[dev,web]"
# python-jobspy two-step (see README): install without deps, then bring in its
# real runtime deps separately to avoid the numpy pin conflict.
Write-Host "[install] python-jobspy two-step ..." -ForegroundColor Cyan
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex

# --- 3. Config -------------------------------------------------------------- #
Invoke-ConfigGenerator -RepoRoot $repo -Runner @('python') -Force:$Setup

# --- 4. Doctor + LM Studio check ------------------------------------------- #
Test-LMStudio
Write-Host "[doctor] nexscout doctor ..." -ForegroundColor Cyan
nexscout doctor
if ($LASTEXITCODE -ne 0) { Write-Warning "[doctor] reported issues (exit $LASTEXITCODE). Continuing." }

# --- 5. Web UI (background) ------------------------------------------------- #
Write-Host "[web] Starting 'nexscout web --host 0.0.0.0 --port 8765' in the background ..." -ForegroundColor Cyan
$webProc = Start-Process -FilePath 'nexscout' `
    -ArgumentList @('web', '--host', '0.0.0.0', '--port', '8765') `
    -PassThru -WindowStyle Hidden
# Record the PID so stop.ps1 can find it.
Set-Content -Path (Join-Path $repo '.nexscout-web.pid') -Value $webProc.Id

if (-not (Wait-WebHealthy -TimeoutSeconds 90)) {
    Write-Warning "[web] Health check failed; opening the dashboard anyway (it may not respond yet)."
}
# Host scripts only run the NexScout web UI; the OpenClaw gateway is Docker-only.
try {
    Start-Process $script:NexWebUrl -ErrorAction Stop
    Write-Host "[open] Opened $script:NexWebUrl" -ForegroundColor Green
} catch {
    Write-Host "[open] Could not auto-open a browser. Visit: $script:NexWebUrl" -ForegroundColor Yellow
}
Write-Host "[open] NexScout web UI: $script:NexWebUrl" -ForegroundColor Cyan
Write-Host "[open] OpenClaw gateway dashboard (:18789) is Docker-only — use start-docker.ps1 for it." -ForegroundColor DarkGray

# --- 6. Autopilot (resilient loop, foreground) ----------------------------- #
Write-Host "[autopilot] Starting the resilient loop: nexscout autopilot" -ForegroundColor Cyan
Write-Host "            It loops discover->enrich->score->tailor->render->apply->questions" -ForegroundColor DarkGray
Write-Host "            forever, surviving per-pass errors. Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host "            (one-shot single pass instead: nexscout run)" -ForegroundColor DarkGray
Write-Host "            Web UI PID $($webProc.Id) keeps running in the background." -ForegroundColor DarkGray
Write-Host "            Stop everything with: powershell -File scripts\windows\stop.ps1" -ForegroundColor DarkGray
nexscout autopilot

Write-Host ""
Write-Host "Autopilot exited. Web UI PID $($webProc.Id) may still be running in the background." -ForegroundColor Green
Write-Host "Stop everything with: powershell -File scripts\windows\stop.ps1" -ForegroundColor Green
