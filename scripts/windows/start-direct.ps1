#requires -Version 5.1
<#
.SYNOPSIS
    Start NexScout directly in a local .venv (pip install -e) on Windows.
.DESCRIPTION
    Creates/activates a .venv, installs NexScout (+ the python-jobspy two-step
    from the README), optionally (re)generates config, runs `nexscout doctor`,
    starts the web UI on :8765 in the background, waits for health, opens BOTH
    dashboards, then runs `nexscout run`.
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

if (Wait-WebHealthy -TimeoutSeconds 90) {
    Open-Dashboards
} else {
    Write-Warning "[web] Health check failed; opening dashboards anyway (they may not respond yet)."
    Open-Dashboards
}

# --- 6. Pipeline ------------------------------------------------------------ #
Write-Host "[run] nexscout run (discover -> enrich -> score -> tailor -> cover -> render) ..." -ForegroundColor Cyan
Write-Host "      (to submit applications afterwards, run: nexscout apply --workers 2)" -ForegroundColor DarkGray
nexscout run

Write-Host ""
Write-Host "NexScout is up. Web UI PID $($webProc.Id) is still running in the background." -ForegroundColor Green
Write-Host "Stop everything with: powershell -File scripts\windows\stop.ps1" -ForegroundColor Green
