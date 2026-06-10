#requires -Version 5.1
<#
.SYNOPSIS
    Start NexScout via the `uv` package manager on Windows.
.DESCRIPTION
    Ensures `uv` is installed (installs it via the official installer if not),
    runs `uv sync`, optionally (re)generates config, runs doctor, starts the
    web UI on :8765 in the background, waits for health, opens the NexScout
    dashboard, then runs the crash-resilient `uv run nexscout autopilot` loop
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
Write-Host "=== NexScout : uv launcher ===" -ForegroundColor Magenta
Write-Host "[repo] $repo"

# --- 0. Ensure uv is installed --------------------------------------------- #
if (-not (Get-Command 'uv' -ErrorAction SilentlyContinue)) {
    Write-Host "[uv] 'uv' not found — installing via the official installer ..." -ForegroundColor Cyan
    try {
        # Official Astral installer for Windows PowerShell.
        Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1' | Invoke-Expression
    } catch {
        Write-Error "Failed to install uv automatically. Install it manually from https://docs.astral.sh/uv/getting-started/installation/ and re-run."
        exit 1
    }
    # The installer drops uv into ~/.local/bin (or %USERPROFILE%\.local\bin).
    $uvBin = Join-Path $env:USERPROFILE '.local\bin'
    if (Test-Path $uvBin) { $env:PATH = "$uvBin;$env:PATH" }
    if (-not (Get-Command 'uv' -ErrorAction SilentlyContinue)) {
        Write-Error "uv was installed but is not on PATH. Open a new shell and re-run, or add '$uvBin' to PATH."
        exit 1
    }
}
Write-Host "[uv] $((uv --version) 2>&1)" -ForegroundColor Green

# --- 1. Sync dependencies --------------------------------------------------- #
Write-Host "[uv] uv sync --extra dev --extra web ..." -ForegroundColor Cyan
uv sync --extra dev --extra web

# --- 2. Config -------------------------------------------------------------- #
# Use the project's interpreter (via `uv run python`) so pyyaml is available.
Invoke-ConfigGenerator -RepoRoot $repo -Runner @('uv', 'run', 'python') -Force:$Setup

# --- 3. Doctor + LM Studio check ------------------------------------------- #
Test-LMStudio
Write-Host "[doctor] uv run nexscout doctor ..." -ForegroundColor Cyan
uv run nexscout doctor
if ($LASTEXITCODE -ne 0) { Write-Warning "[doctor] reported issues (exit $LASTEXITCODE). Continuing." }

# --- 4. Web UI (background) ------------------------------------------------- #
Write-Host "[web] Starting 'uv run nexscout web --host 0.0.0.0 --port 8765' in the background ..." -ForegroundColor Cyan
$webProc = Start-Process -FilePath 'uv' `
    -ArgumentList @('run', 'nexscout', 'web', '--host', '0.0.0.0', '--port', '8765') `
    -PassThru -WindowStyle Hidden
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

# --- 5. Autopilot (resilient loop, foreground) ----------------------------- #
Write-Host "[autopilot] Starting the resilient loop: uv run nexscout autopilot" -ForegroundColor Cyan
Write-Host "            It loops discover->enrich->score->tailor->render->apply->questions" -ForegroundColor DarkGray
Write-Host "            forever, surviving per-pass errors. Ctrl+C to stop." -ForegroundColor DarkGray
Write-Host "            (one-shot single pass instead: uv run nexscout run)" -ForegroundColor DarkGray
Write-Host "            Web UI PID $($webProc.Id) keeps running in the background." -ForegroundColor DarkGray
Write-Host "            Stop everything with: powershell -File scripts\windows\stop.ps1" -ForegroundColor DarkGray
uv run nexscout autopilot

Write-Host ""
Write-Host "Autopilot exited. Web UI PID $($webProc.Id) may still be running in the background." -ForegroundColor Green
Write-Host "Stop everything with: powershell -File scripts\windows\stop.ps1" -ForegroundColor Green
