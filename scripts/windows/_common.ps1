# scripts/windows/_common.ps1
# Shared helpers dot-sourced by the Windows launcher scripts. Not meant to be
# run directly. Defines: repo-root discovery, config-file checks, the
# interactive config generator hook, the web-UI health wait, and the
# "open both dashboards" helper.

Set-StrictMode -Version Latest

# Dashboard URLs (the contract). Exposed as script-scope variables.
$script:NexWebUrl      = 'http://localhost:8765'
$script:NexWebHealth   = 'http://localhost:8765/healthz'
$script:OpenClawUrl    = 'http://localhost:18789'

function Get-RepoRoot {
    <#
        Resolve the repository root from this script's location.
        scripts/windows/_common.ps1 -> repo root is two levels up.
    #>
    $here = Split-Path -Parent $PSCommandPath
    $root = Resolve-Path (Join-Path $here '..\..') | Select-Object -ExpandProperty Path
    if (-not (Test-Path (Join-Path $root 'pyproject.toml'))) {
        Write-Warning "pyproject.toml not found at '$root' — repo root detection may be wrong."
    }
    return $root
}

function Get-NexScoutDir {
    <# The NexScout config dir: $NEXSCOUT_DIR if set, else ~/.nexscout. #>
    if ($env:NEXSCOUT_DIR) { return $env:NEXSCOUT_DIR }
    return (Join-Path $env:USERPROFILE '.nexscout')
}

function Test-ConfigPresent {
    <# True only if all three config files already exist. #>
    $dir = Get-NexScoutDir
    foreach ($f in 'profile.yaml', 'settings.yaml', 'credentials.yaml') {
        if (-not (Test-Path (Join-Path $dir $f))) { return $false }
    }
    return $true
}

function Invoke-ConfigGenerator {
    <#
        Run the interactive config generator. Pass -Force to always run it,
        otherwise it only runs when the config files are missing.

        -Runner is the command + leading args used to invoke a Python script,
        e.g. @('python') for the .venv, or @('uv','run','python') for uv.
    #>
    param(
        [string]   $RepoRoot,
        [string[]] $Runner = @('python'),
        [switch]   $Force
    )
    if (-not $Force -and (Test-ConfigPresent)) {
        Write-Host "[config] Config files already present in $(Get-NexScoutDir) — skipping generator." -ForegroundColor DarkGray
        return
    }
    $gen = Join-Path $RepoRoot 'scripts\common\generate_config.py'
    if (-not (Test-Path $gen)) {
        Write-Warning "[config] Generator not found at $gen — skipping."
        return
    }
    Write-Host "[config] Launching interactive config generator..." -ForegroundColor Cyan
    $exe = $Runner[0]
    $genArgs = @()
    if ($Runner.Count -gt 1) { $genArgs += $Runner[1..($Runner.Count - 1)] }
    $genArgs += $gen
    & $exe @genArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "[config] Generator exited with code $LASTEXITCODE. Continuing anyway."
    }
}

function Wait-WebHealthy {
    <#
        Poll the web UI /healthz endpoint until it returns 200 or we time out.
        Returns $true on success, $false on timeout. Never throws.
    #>
    param(
        [int] $TimeoutSeconds = 90,
        [string] $HealthUrl = $script:NexWebHealth
    )
    Write-Host "[wait] Waiting for the web UI at $HealthUrl (timeout ${TimeoutSeconds}s)..." -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                Write-Host "[wait] Web UI is healthy." -ForegroundColor Green
                return $true
            }
        } catch {
            # Not up yet — keep polling.
        }
        Start-Sleep -Seconds 2
    }
    Write-Warning "[wait] Web UI did not become healthy within ${TimeoutSeconds}s."
    return $false
}

function Open-Dashboards {
    <#
        Open BOTH dashboards in the default browser. Never hard-fails: if a
        browser can't be launched we just print the URL.
    #>
    param(
        [string] $WebUrl = $script:NexWebUrl,
        [string] $ClawUrl = $script:OpenClawUrl
    )
    foreach ($url in $WebUrl, $ClawUrl) {
        try {
            Start-Process $url -ErrorAction Stop
            Write-Host "[open] Opened $url" -ForegroundColor Green
        } catch {
            Write-Host "[open] Could not auto-open a browser. Visit: $url" -ForegroundColor Yellow
        }
    }
    Write-Host ""
    Write-Host "Dashboards:" -ForegroundColor Cyan
    Write-Host "  NexScout web UI:    $WebUrl"
    Write-Host "  OpenClaw dashboard: $ClawUrl"
}

function Assert-Command {
    <# Fail with a helpful message if a required command is missing. #>
    param([string] $Name, [string] $Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Error "Required command '$Name' was not found on PATH. $Hint"
        return $false
    }
    return $true
}

function Test-LMStudio {
    <#
        Best-effort check that LM Studio's OpenAI-compatible server is up on
        :1234. Only warns — the score/tailor/apply stages need it but discover
        does not, so we never hard-fail.
    #>
    param([string] $Url = 'http://localhost:1234/v1/models')
    try {
        $null = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
        Write-Host "[lmstudio] LM Studio reachable at $Url" -ForegroundColor Green
    } catch {
        Write-Warning "[lmstudio] LM Studio not reachable at $Url. Start LM Studio and load a model, then set settings.yaml -> llm.primary = lmstudio:<model-id>. (score/tailor/apply will fail without it.)"
    }
}
