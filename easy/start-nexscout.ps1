# Start (or stop) NexScout on Windows with Docker Desktop. Run by "Start NexScout.cmd".
# What it does, in plain words:
#   1. checks that Docker Desktop is installed and running (starts it if needed),
#   2. creates secret keys once (saved in .env next to this file - keep it, back it up),
#   3. downloads and starts NexScout, then opens it in your browser.
# With -Update ("Update NexScout.cmd") it first replaces these files with the newest release
# (checked against the release's SHA256SUMS.txt; your .env and data are kept).
# After starting, older NexScout images are removed to free disk space.
param([switch]$Stop, [switch]$Update, [int]$Port = 0)

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

$Repo = "AvishakeAdhikary/NexScout"

# The version this folder runs: the release bundle pins it in docker-compose.yml.
function Bundle-Version {
    $m = Select-String -LiteralPath (Join-Path $PSScriptRoot "docker-compose.yml") -Pattern 'NEXSCOUT_VERSION:-(\d+\.\d+\.\d+)\}' |
        Select-Object -First 1
    if ($m) { return $m.Matches[0].Groups[1].Value }
    return $null
}

function Update-Bundle {
    $root = Split-Path -Parent $PSScriptRoot
    if (Test-Path -LiteralPath (Join-Path $root "backend")) {
        Fail "This is a developer copy of NexScout. Update it with git instead."
    }
    Say "Checking for a newer NexScout..."
    try {
        $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ Accept = "application/vnd.github+json" } -TimeoutSec 30
    } catch { Fail "Couldn't reach GitHub to check for updates. Check that you're online, then try again." }
    if ("$($rel.tag_name)" -notmatch '^v(\d+\.\d+\.\d+)$') { Fail "GitHub's answer didn't look like a NexScout release." }
    $latest = $Matches[1]
    $current = Bundle-Version
    if ($current -eq $latest) { Say "You already have the newest NexScout ($latest)." "Green"; return $false }
    Say "Updating NexScout $current -> $latest ..."
    $base = "https://github.com/$Repo/releases/download/v$latest"
    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) "nexscout-update-$latest"
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $tmp | Out-Null
    $zip = Join-Path $tmp "nexscout-easy-$latest.zip"
    $sums = Join-Path $tmp "SHA256SUMS.txt"
    try {
        Invoke-WebRequest -Uri "$base/nexscout-easy-$latest.zip" -OutFile $zip -UseBasicParsing -TimeoutSec 300
        Invoke-WebRequest -Uri "$base/SHA256SUMS.txt" -OutFile $sums -UseBasicParsing -TimeoutSec 60
    } catch { Fail "Couldn't download the update. Check that you're online, then try again." }
    $expected = (Get-Content -LiteralPath $sums | Where-Object { $_ -match "^([0-9a-f]{64})\s+\*?nexscout-easy-$([regex]::Escape($latest))\.zip$" } | Select-Object -First 1)
    if (-not $expected) { Fail "The update has no checksum, so it wasn't installed." }
    $want = ($expected -split '\s+')[0]
    $have = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($have -ne $want) { Fail "The downloaded update is damaged (checksum mismatch), so it wasn't installed. Try again later." }
    Expand-Archive -LiteralPath $zip -DestinationPath $tmp -Force
    $src = Join-Path $tmp "NexScout-$latest"
    if (-not (Test-Path -LiteralPath (Join-Path $src "easy\docker-compose.yml"))) { Fail "The update package looks incomplete, so it wasn't installed." }
    # Replace the program files; never .env (your keys) or your data (Docker volumes).
    Get-ChildItem -LiteralPath (Join-Path $src "easy") -File | Where-Object { $_.Name -ne ".env" } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $PSScriptRoot -Force }
    foreach ($part in @("docker\postgres\01-roles.sql", "docs\USER_GUIDE.md", "LICENSE")) {
        $from = Join-Path $src $part
        if (Test-Path -LiteralPath $from) {
            $to = Join-Path $root $part
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $to) | Out-Null
            Copy-Item -LiteralPath $from -Destination $to -Force
        }
    }
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    Say "NexScout files updated to $latest." "Green"
    return $true
}

# The desktop app's Easy mode uses the same Docker project with its own keys. Starting this
# folder over it would leave stored keys unreadable, so another live install is refused.
function Foreign-Stack([string]$docker) {
    $ours = (Join-Path $PSScriptRoot "docker-compose.yml").Replace('\', '/').ToLowerInvariant()
    $labels = & $docker ps -a --filter "label=com.docker.compose.project=nexscout-easy" --format '{{.Label "com.docker.compose.project.config_files"}}' 2>$null
    foreach ($label in $labels) {
        foreach ($f in ("$label" -split ',')) {
            $f = $f.Trim()
            if ($f -and $f.Replace('\', '/').ToLowerInvariant() -ne $ours -and (Test-Path -LiteralPath $f)) { return $f }
        }
    }
    return $null
}

# Free disk space: remove NexScout images other than the version this folder runs.
function Remove-OldImages([string]$docker) {
    $keep = Bundle-Version
    if (-not $keep) { return }
    $old = & $docker images --filter "reference=ghcr.io/*/nexscout-*" --format "{{.Repository}}:{{.Tag}}" |
        Where-Object { $_ -match '^ghcr\.io/[a-z0-9-]+/nexscout-(backend|web):(\d+\.\d+\.\d+)$' -and $Matches[2] -ne $keep }
    foreach ($img in $old) {
        & $docker rmi $img *> $null
        if ($LASTEXITCODE -eq 0) { Say "Removed the old image $img." }
    }
    if ($old) { & $docker image prune -f *> $null }
}

Say "NexScout" "Cyan"
if ($Update) {
    if (Update-Bundle) {
        # Run the new version of this script (it may start NexScout differently).
        & (Join-Path $PSScriptRoot "start-nexscout.ps1") -Port $Port
        exit $LASTEXITCODE
    }
}
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

$other = Foreign-Stack $docker
if ($other) {
    Fail "Another NexScout is already set up on this computer ($other), with its own keys. Use that one, or stop and remove it first (in its folder: docker compose down). Your data in it is kept."
}

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
Remove-OldImages $docker

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
