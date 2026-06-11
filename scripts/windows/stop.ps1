#requires -Version 5.1
<#
.SYNOPSIS
    Stop NexScout — either the local processes (direct / uv) or the Docker stack.
.DESCRIPTION
    Default (host run methods): kills the background web UI (via the recorded
    .nexscout-web.pid) plus any lingering `nexscout` processes started
    directly/uv — including the `nexscout autopilot` resilient loop.
    With -Docker: runs `docker compose --profile openclaw down`, which stops
    every service (nexscout autopilot, nexscout-web, nexscout-mcp, openclaw
    gateway, and ollama if it was started), handling the docker.exe PATH + HOME
    quirks. With
    -Docker -Volumes: `docker compose down -v` (also drops named volumes; the
    SQLite DB lives on the host mount and survives anyway).
.PARAMETER Docker
    Tear down the Docker Compose stack instead of local processes.
.PARAMETER Volumes
    Only with -Docker: also remove named volumes (down -v).
#>
param(
    [switch] $Docker,
    [switch] $Volumes
)

$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSCommandPath) '_common.ps1')

$repo = Get-RepoRoot
Set-Location $repo
Write-Host "=== NexScout : stop ===" -ForegroundColor Magenta

if ($Docker) {
    # --- Docker teardown ---------------------------------------------------- #
    if (-not (Get-Command 'docker' -ErrorAction SilentlyContinue)) {
        $dockerBin = 'C:\Program Files\Docker\Docker\resources\bin'
        if (Test-Path (Join-Path $dockerBin 'docker.exe')) {
            $env:PATH = "$dockerBin;$env:PATH"
        }
    }
    if (-not $env:HOME) { $env:HOME = $env:USERPROFILE }
    $compose = Join-Path $repo 'docker-compose.yml'

    # Include both optional profiles so `down` tears down every service that
    # any start method may have created (openclaw gateway + ollama), not just
    # the always-on nexscout / nexscout-web pair.
    $downArgs = @('-f', $compose, '--profile', 'openclaw', '--profile', 'local-llm', 'down')
    if ($Volumes) { $downArgs += '-v' }
    Write-Host "[docker] docker compose $($downArgs -join ' ') ..." -ForegroundColor Cyan
    docker compose @downArgs
    Write-Host "[docker] Stack stopped (nexscout autopilot, nexscout-web, nexscout-mcp, openclaw, ollama)." -ForegroundColor Green
    return
}

# --- Local process teardown ------------------------------------------------- #
$pidFile = Join-Path $repo '.nexscout-web.pid'
if (Test-Path $pidFile) {
    $webPid = (Get-Content $pidFile -Raw).Trim()
    if ($webPid) {
        try {
            Stop-Process -Id ([int]$webPid) -Force -ErrorAction Stop
            Write-Host "[stop] Killed web UI process (PID $webPid)." -ForegroundColor Green
        } catch {
            Write-Host "[stop] Web UI process (PID $webPid) was not running." -ForegroundColor DarkGray
        }
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
} else {
    Write-Host "[stop] No .nexscout-web.pid found." -ForegroundColor DarkGray
}

# Best-effort: kill any other lingering nexscout processes (e.g. the
# `nexscout autopilot` loop, or `nexscout run`).
$leftover = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match '\bnexscout\b' -and $_.ProcessId -ne $PID }
foreach ($p in $leftover) {
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        Write-Host "[stop] Killed lingering nexscout process (PID $($p.ProcessId))." -ForegroundColor Green
    } catch {
        # Already gone — ignore.
    }
}

Write-Host "[stop] Done. (For the Docker stack instead, run: stop.ps1 -Docker)" -ForegroundColor Green
