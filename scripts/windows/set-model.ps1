#requires -Version 5.1
<#
.SYNOPSIS
    Switch the NexScout LLM model. Thin wrapper over scripts/common/set_model.py.
.DESCRIPTION
    Rewrites the `llm` block in settings.yaml (primary/fallback/judge + the
    OpenAI-compatible provider endpoint) and, for OpenAI-compatible schemes,
    writes the api_key into credentials.yaml. All other YAML keys are preserved.

    Pass the same flags through as set_model.py:
      -Provider <preset>   lmstudio | openrouter | nim | openai | gemini |
                           anthropic | ollama | openai_compat
      -Model <id>          model id (may contain ':')
      -ApiKey <key>        Bearer key (OpenAI-compatible schemes -> credentials.yaml)
      -BaseUrl <url>       OpenAI-compatible base URL (required for openai_compat)
      -JudgeModel <id>     give the judge a different model (same scheme)
      -Target <dir>        config dir (default: $env:NEXSCOUT_DIR or ~/.nexscout)
      -OpenclawDir <dir>   OpenClaw config dir (default: $env:OPENCLAW_DIR or ~/.openclaw)
      -NoOpenclaw          update NexScout only; do NOT sync the OpenClaw agent

    If an OpenClaw config is present, the OpenClaw gateway agent is repointed at
    the SAME model (managed provider `nexscout`) so it shares NexScout's LLM.

    With -Docker (and Docker up) it also recreates the NexScout services so the
    new config takes effect immediately, and restarts the OpenClaw gateway (it
    reads its model at startup) unless -NoOpenclaw:
      docker compose up -d nexscout nexscout-web nexscout-mcp
      docker restart nexscout-openclaw
    (The autopilot also reloads the profile each pass, so the NexScout switch
    applies live even without a restart.)
.EXAMPLE
    powershell -File scripts\windows\set-model.ps1 -Provider openrouter `
        -Model "google/gemma-4-26b-a4b-it:free" -ApiKey "sk-or-..."
.EXAMPLE
    powershell -File scripts\windows\set-model.ps1 -Provider lmstudio -Model local-model
#>
param(
    [Parameter(Mandatory = $true)][string] $Provider,
    [Parameter(Mandatory = $true)][string] $Model,
    [string] $ApiKey,
    [string] $BaseUrl,
    [string] $JudgeModel,
    [string] $Target,
    [string] $OpenclawDir,
    [switch] $NoOpenclaw,
    [switch] $Docker
)

$ErrorActionPreference = 'Stop'
. (Join-Path (Split-Path -Parent $PSCommandPath) '_common.ps1')

$repo = Get-RepoRoot
$script = Join-Path $repo 'scripts\common\set_model.py'
if (-not (Test-Path $script)) {
    Write-Error "set_model.py not found at $script"
    exit 1
}

Write-Host "=== NexScout : set model ===" -ForegroundColor Magenta

# --- Build the pass-through args ------------------------------------------- #
$pyArgs = @($script, '--provider', $Provider, '--model', $Model)
if ($ApiKey)      { $pyArgs += @('--api-key', $ApiKey) }
if ($BaseUrl)     { $pyArgs += @('--base-url', $BaseUrl) }
if ($JudgeModel)  { $pyArgs += @('--judge-model', $JudgeModel) }
if ($Target)      { $pyArgs += @('--target', $Target) }
if ($OpenclawDir) { $pyArgs += @('--openclaw-dir', $OpenclawDir) }
if ($NoOpenclaw)  { $pyArgs += @('--no-openclaw') }

# --- Resolve the python runner: prefer uv, fall back to python -------------- #
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
if ($rc -ne 0) { exit $rc }

# --- Optional: recreate the services so the switch is immediate ------------- #
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
        Write-Host "[docker] Recreating services with the new model config..." -ForegroundColor Cyan
        docker compose -f $compose up -d nexscout nexscout-web nexscout-mcp 2>&1 | Out-Host
        if (-not $NoOpenclaw) {
            $oc = docker ps --filter 'name=nexscout-openclaw' --format '{{.Names}}' 2>$null
            if ($oc) {
                Write-Host "[docker] Restarting the OpenClaw gateway to pick up the shared model..." -ForegroundColor Cyan
                docker restart nexscout-openclaw 2>&1 | Out-Host
            }
        }
        Write-Host "[docker] Done — the new model is live." -ForegroundColor Green
    } else {
        Write-Warning "[docker] docker not found — skipped the recreate. The autopilot will pick up the new config on its next pass."
    }
}

exit 0
