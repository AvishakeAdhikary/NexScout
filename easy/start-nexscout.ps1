# Start (or stop) NexScout on Windows with Docker Desktop. Run by "Start NexScout.cmd".
# What it does, in plain words:
#   1. checks that Docker Desktop is installed and running (starts it if needed),
#   2. creates secret keys once (saved in .env next to this file - keep it, back it up),
#   3. downloads and starts NexScout, then opens it in your browser.
param([switch]$Stop, [int]$Port = 0)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Say([string]$text, [string]$color = "Gray") { Write-Host $text -ForegroundColor $color }
function Fail([string]$text) {
    Say ""
    Say $text "Red"
    Read-Host "Press Enter to close"
    exit 1
}

function Find-Docker {
    $cmd = Get-Command docker -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($p in @(
            "$env:ProgramFiles\Docker\Docker\resources\bin\docker.exe",
            "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe")) {
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

function Docker-Running([string]$docker) {
    & $docker info *> $null
    return $LASTEXITCODE -eq 0
}

function New-Secret([int]$bytes = 32) {
    $b = New-Object byte[] $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
    return [Convert]::ToBase64String($b)
}

Say "NexScout" "Cyan"
$docker = Find-Docker
if (-not $docker) {
    Say "NexScout runs inside Docker Desktop, which isn't installed yet."
    Say "Opening the Docker Desktop download page. Install it, start it once, then run this again."
    Start-Process "https://www.docker.com/products/docker-desktop/"
    Fail "Docker Desktop is needed."
}
$env:PATH = "$(Split-Path -Parent $docker);$env:PATH"

if (-not (Docker-Running $docker)) {
    foreach ($app in @(
            "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
            "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe")) {
        if (Test-Path -LiteralPath $app) {
            Say "Starting Docker Desktop (this can take a minute)..."
            Start-Process -FilePath $app
            break
        }
    }
    $deadline = (Get-Date).AddMinutes(3)
    while (-not (Docker-Running $docker)) {
        if ((Get-Date) -gt $deadline) { Fail "Docker Desktop didn't start. Open it yourself, wait until it says 'running', then try again." }
        Start-Sleep -Seconds 3
    }
}

$compose = @("compose", "-f", "docker-compose.yml")
$envFile = Join-Path $PSScriptRoot ".env"
if ($Stop) {
    if (-not (Test-Path -LiteralPath $envFile)) { Say "NexScout isn't set up here yet."; exit 0 }
    Say "Stopping NexScout (your data is kept)..."
    & $docker @compose --env-file $envFile stop
    Say "Stopped." "Green"
    Start-Sleep -Seconds 2
    exit 0
}

# Secrets: created once, reused every time (changing them would lock you out of your data).
if (-not (Test-Path -LiteralPath $envFile)) {
    $lines = @(
        "# NexScout secrets. Keep this file; back it up with your data. Never share it.",
        "NEXSCOUT_MASTER_KEY=$(New-Secret 32)",
        "NEXSCOUT_PG_SUPERUSER_PASSWORD=$((New-Secret 24) -replace '[^A-Za-z0-9]', '')",
        "NEXSCOUT_PORT=3000"
    )
    [System.IO.File]::WriteAllLines($envFile, $lines)
    Say "Created your secret keys in $envFile (keep this file safe)." "Yellow"
}
if ($Port -gt 0) { $env:NEXSCOUT_PORT = "$Port" }
$portLine = (Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^NEXSCOUT_PORT=' }) -replace '^NEXSCOUT_PORT=', ''
$webPort = if ($env:NEXSCOUT_PORT) { $env:NEXSCOUT_PORT } elseif ($portLine) { $portLine } else { "3000" }
$env:NEXSCOUT_PUBLIC_WEB_URL = "http://localhost:$webPort"

Say "Downloading and starting NexScout (the first time takes a few minutes)..."
& $docker @compose --env-file $envFile pull
$pulled = $LASTEXITCODE -eq 0
if (-not $pulled -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot "..\backend"))) {
    Say "Couldn't download the released images; building them from this folder instead..." "Yellow"
    & $docker compose -f docker-compose.yml -f docker-compose.build.yml --env-file $envFile up -d --build
} else {
    & $docker @compose --env-file $envFile up -d
}
if ($LASTEXITCODE -ne 0) { Fail "NexScout didn't start. Make sure you're online and Docker Desktop is running, then try again." }

$url = "http://localhost:$webPort"
Say "Waiting for NexScout to be ready at $url ..."
$deadline = (Get-Date).AddMinutes(5)
while ($true) {
    try {
        $r = Invoke-WebRequest -Uri "$url/login" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -lt 400) { break }
    } catch { }
    if ((Get-Date) -gt $deadline) { Fail "NexScout is taking too long. Run 'docker compose logs' in $PSScriptRoot to see why." }
    Start-Sleep -Seconds 3
}
Say "NexScout is running. Opening $url" "Green"
Say "It keeps working in the background (autopilot, reminders). Use 'Stop NexScout' to stop it."
Start-Process $url
Start-Sleep -Seconds 3
