#requires -Version 5.1
<#
.SYNOPSIS
    Wipe NexScout's runtime data (DBs, applications/, scratch, browser profiles)
    while KEEPING the config files. Thin wrapper over scripts/common/clear_db.py.
.DESCRIPTION
    By default it wipes the HOST config dir ($env:NEXSCOUT_DIR or ~/.nexscout) —
    which is the SAME directory mounted into the Docker containers.

    With -Docker: stops the `nexscout` autopilot service first (to avoid a
    writer racing the wipe), wipes the host dir, and tells you to restart the
    stack. The wipe still happens on the host, since the container mounts that
    very dir — there's no need to exec inside a container.

    Config files (profile.yaml / settings.yaml / credentials.yaml and the
    OpenClaw config) are NEVER deleted.
.PARAMETER Yes
    Skip the confirmation prompt (passes --yes to clear_db.py).
.PARAMETER Docker
    Stop the `nexscout` service before wiping; remind you to restart after.
.PARAMETER Target
    Explicit config dir to wipe (default: $env:NEXSCOUT_DIR or ~/.nexscout).
.EXAMPLE
    powershell -File scripts\windows\clear-db.ps1
.EXAMPLE
    powershell -File scripts\windows\clear-db.ps1 -Docker -Yes
#>
param(
    [switch] $Yes,
    [switch] $Docker,
    [string] $Target
)

$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSCommandPath) '_common.ps1')

$repo = Get-RepoRoot
$script = Join-Path $repo 'scripts\common\clear_db.py'
if (-not (Test-Path $script)) {
    Write-Error "clear_db.py not found at $script"
    exit 1
}

Write-Host "=== NexScout : clear database ===" -ForegroundColor Magenta

# --- Optional: stop the autopilot first so nothing writes during the wipe --- #
if ($Docker) {
    if (-not (Get-Command 'docker' -ErrorAction SilentlyContinue)) {
        $dockerBin = 'C:\Program Files\Docker\Docker\resources\bin'
        if (Test-Path (Join-Path $dockerBin 'docker.exe')) {
            $env:PATH = "$dockerBin;$env:PATH"
        }
    }
    if (-not $env:HOME) { $env:HOME = $env:USERPROFILE }
    $compose = Join-Path $repo 'docker-compose.yml'
    if (Get-Command 'docker' -ErrorAction SilentlyContinue) {
        Write-Host "[docker] Stopping the 'nexscout' autopilot service to avoid a writer race..." -ForegroundColor Cyan
        docker compose -f $compose stop nexscout 2>&1 | Out-Host
    } else {
        Write-Warning "[docker] docker not found — skipping the autopilot stop. Make sure nothing is writing to the dir."
    }
}

# --- Resolve the python runner: prefer uv, fall back to python -------------- #
$pyArgs = @($script)
if ($Yes)    { $pyArgs += '--yes' }
if ($Target) { $pyArgs += $Target }   # positional target dir

$uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe'
if (Test-Path $uv) {
    & $uv run python @pyArgs
} elseif (Get-Command 'python' -ErrorAction SilentlyContinue) {
    & python @pyArgs
} else {
    Write-Error "Neither uv ($uv) nor python were found on this machine."
    exit 1
}
$rc = $LASTEXITCODE

if ($Docker) {
    Write-Host ""
    Write-Host "[docker] Runtime data wiped on the host dir (mounted into the containers)." -ForegroundColor Green
    Write-Host "[docker] Restart the stack when ready:  docker compose --profile openclaw up -d" -ForegroundColor Green
}

exit $rc
