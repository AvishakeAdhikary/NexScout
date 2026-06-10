#requires -Version 5.1
<#
.SYNOPSIS
    Print BOTH NexScout dashboard URLs, resolving the tokenized OpenClaw link.
.DESCRIPTION
    Prints:
      * the NexScout web UI       — http://localhost:8765
      * the OpenClaw dashboard    — http://localhost:18789 (tokenized when a
                                     token can be resolved)

    The tokenized OpenClaw link is resolved in this order of preference:

      1. Ask the OpenClaw CLI inside the running gateway container:
             docker exec nexscout-openclaw node dist/index.js dashboard --print
         (also tried with --json). If it emits a URL we surface it verbatim.

      2. Fallback: read gateway.auth.token from ~/.openclaw/openclaw.json and
         build  http://localhost:18789/?token=<TOKEN>  (the documented
         query-param form). The raw token and the OPENCLAW_GATEWAY_TOKEN env
         var (if set) are also printed so they can be pasted manually.

    Robust by design: if the container is not running or the config is absent,
    it prints a helpful message and the untokenized URL — it never throws.

    This file is dual-purpose: run it directly to print the links, OR dot-source
    it to reuse Get-OpenClawDashboardLink / Show-DashboardLinks from another
    launcher script.
#>
[CmdletBinding()]
param(
    # When set, only emit the resolved OpenClaw URL (one line) — handy for
    # piping into Start-Process. No banner, no NexScout URL.
    [switch] $OpenClawOnly
)

Set-StrictMode -Version Latest

# Dashboard contract (kept in sync with _common.ps1).
$script:NexWebUrl         = 'http://localhost:8765'
$script:OpenClawBaseUrl   = 'http://localhost:18789'
$script:OpenClawContainer = 'nexscout-openclaw'

function Get-OpenClawConfigPath {
    <# Path to OpenClaw's gateway config (~/.openclaw/openclaw.json). #>
    # NB: $HOME is a read-only PowerShell automatic var — use our own name.
    $homeDir = if ($env:HOME) { $env:HOME } else { $env:USERPROFILE }
    return (Join-Path $homeDir '.openclaw\openclaw.json')
}

function Resolve-DockerExe {
    <#
        Resolve a usable docker command, handling the Docker Desktop quirk that
        docker.exe is often not on PATH. Returns the command name/path, or
        $null if Docker can't be found.
    #>
    $cmd = Get-Command 'docker' -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $dockerBin = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
    if (Test-Path $dockerBin) { return $dockerBin }
    return $null
}

function Get-OpenClawTokenFromConfig {
    <#
        Read gateway.auth.token from ~/.openclaw/openclaw.json. Returns the
        token string, or $null if the file/key is missing or unparseable.
        Never throws.
    #>
    $cfg = Get-OpenClawConfigPath
    if (-not (Test-Path $cfg)) { return $null }
    try {
        $json = Get-Content -Raw -Path $cfg -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return $null
    }
    try {
        $token = $json.gateway.auth.token
        if ($token) { return [string]$token }
    } catch {
        # Key path absent — fall through.
    }
    return $null
}

function Get-OpenClawLinkFromCli {
    <#
        Ask the OpenClaw CLI inside the running container for a pre-authenticated
        dashboard link. Tries `dashboard --print` then `dashboard --print --json`.
        Returns the first http(s) URL found in the output, or $null. Never throws.
    #>
    param([string] $Docker)
    if (-not $Docker) { return $null }

    # Native `docker` calls below set $LASTEXITCODE; when the daemon is down or
    # the container is absent that is non-zero. We deliberately tolerate it and
    # reset it before returning so a failed probe doesn't leak a bad exit code
    # to a caller running under -ErrorActionPreference Stop.
    try {
        # Is the gateway container actually running?
        try {
            $running = & $Docker ps --filter "name=$script:OpenClawContainer" --filter 'status=running' --format '{{.Names}}' 2>$null
        } catch {
            return $null
        }
        if (-not ($running -match [regex]::Escape($script:OpenClawContainer))) {
            return $null
        }

        foreach ($extra in @(@(), @('--json'))) {
            $execArgs = @('exec', $script:OpenClawContainer, 'node', 'dist/index.js', 'dashboard', '--print') + $extra
            try {
                $out = & $Docker @execArgs 2>$null
            } catch {
                continue
            }
            if (-not $out) { continue }
            $text = ($out | Out-String)
            $m = [regex]::Match($text, 'https?://[^\s"'']+')
            if ($m.Success) { return $m.Value }
        }
        return $null
    } finally {
        $global:LASTEXITCODE = 0
    }
}

function Get-OpenClawDashboardLink {
    <#
        Resolve the best available OpenClaw dashboard link. Returns a hashtable:
          Url     — the URL to open (tokenized when possible)
          Token   — the raw token, if one was resolved (else $null)
          Source  — 'cli' | 'config' | 'env' | 'none'
          Note    — human-readable note about how it was resolved
        Never throws.
    #>
    $docker = Resolve-DockerExe

    # 1. Preferred: ask the OpenClaw CLI in the running container.
    $cliUrl = Get-OpenClawLinkFromCli -Docker $docker
    if ($cliUrl) {
        $tok = $null
        $tm = [regex]::Match($cliUrl, '(?i)token=([^&\s]+)')
        if ($tm.Success) { $tok = $tm.Groups[1].Value }
        return @{
            Url    = $cliUrl
            Token  = $tok
            Source = 'cli'
            Note   = "Resolved via 'docker exec $script:OpenClawContainer node dist/index.js dashboard --print'."
        }
    }

    # 2. Fallback: token from config, else from env, build the ?token= link.
    $token  = Get-OpenClawTokenFromConfig
    $source = 'config'
    if (-not $token -and $env:OPENCLAW_GATEWAY_TOKEN) {
        $token  = $env:OPENCLAW_GATEWAY_TOKEN
        $source = 'env'
    }

    if ($token) {
        $enc = [uri]::EscapeDataString($token)
        return @{
            Url    = "$script:OpenClawBaseUrl/#token=$enc"
            Token  = $token
            Source = $source
            Note   = if ($source -eq 'config') {
                "Token from $(Get-OpenClawConfigPath) (gateway.auth.token). '#token=' (URL fragment) is the tokenized form the gateway documents; if it doesn't auto-auth, paste the raw token in the Control UI instead."
            } else {
                "Token from `$env:OPENCLAW_GATEWAY_TOKEN. '#token=' (URL fragment) is the tokenized form the gateway documents; if it doesn't auto-auth, paste the raw token in the Control UI instead."
            }
        }
    }

    # 3. Nothing found — return the bare URL with guidance.
    $note = if (-not $docker) {
        "Docker not found, so the OpenClaw CLI couldn't be queried; and no token in $(Get-OpenClawConfigPath) or `$env:OPENCLAW_GATEWAY_TOKEN. Start the stack (start-docker.ps1) or onboard OpenClaw, then re-run."
    } else {
        "Gateway container '$script:OpenClawContainer' not running (or no token yet). Bring the stack up with: docker compose --profile openclaw up -d, then re-run. No token in $(Get-OpenClawConfigPath) or `$env:OPENCLAW_GATEWAY_TOKEN either."
    }
    return @{ Url = $script:OpenClawBaseUrl; Token = $null; Source = 'none'; Note = $note }
}

function Show-DashboardLinks {
    <# Print both dashboards, with the resolved OpenClaw token details. #>
    $claw = Get-OpenClawDashboardLink

    Write-Host ""
    Write-Host "Dashboards:" -ForegroundColor Cyan
    Write-Host "  NexScout web UI:    $script:NexWebUrl"
    Write-Host "  OpenClaw dashboard: $($claw.Url)"
    if ($claw.Token) {
        Write-Host ""
        Write-Host "OpenClaw token (paste into the Control UI if the link does not auto-auth):" -ForegroundColor DarkGray
        Write-Host "  token                 : $($claw.Token)"
        Write-Host "  OPENCLAW_GATEWAY_TOKEN: $($claw.Token)"
    }
    if ($claw.Note) {
        Write-Host ""
        Write-Host "  note: $($claw.Note)" -ForegroundColor DarkGray
    }
    return $claw
}

# When dot-sourced, $MyInvocation.InvocationName is '.': only run when invoked
# as a script, not when sourced for its functions.
if ($MyInvocation.InvocationName -ne '.') {
    $resolved = Get-OpenClawDashboardLink
    if ($OpenClawOnly) {
        Write-Output $resolved.Url
    } else {
        $null = Show-DashboardLinks
    }
    # Resolution always "succeeds" (worst case: the bare URL). Don't leak a
    # non-zero exit code from an internal docker probe.
    exit 0
}
