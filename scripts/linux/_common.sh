#!/usr/bin/env bash
# scripts/linux/_common.sh
# Shared helpers sourced by the Linux launcher scripts. Not meant to be run
# directly. Defines: repo-root discovery, config checks, the interactive
# config generator hook, the web-UI health wait, and "open both dashboards".

# Dashboard URLs (the contract).
NEX_WEB_URL="http://localhost:8765"
NEX_WEB_HEALTH="http://localhost:8765/healthz"
OPENCLAW_URL="http://localhost:18789"

# Resolve the repo root from this file's location (scripts/linux -> ../..).
repo_root() {
    local here
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    (cd "$here/../.." && pwd)
}

# The NexScout config dir: $NEXSCOUT_DIR if set, else ~/.nexscout.
nexscout_dir() {
    if [[ -n "${NEXSCOUT_DIR:-}" ]]; then
        printf '%s\n' "$NEXSCOUT_DIR"
    else
        printf '%s\n' "$HOME/.nexscout"
    fi
}

# Return 0 only if all three config files already exist.
config_present() {
    local dir
    dir="$(nexscout_dir)"
    local f
    for f in profile.yaml settings.yaml credentials.yaml; do
        [[ -f "$dir/$f" ]] || return 1
    done
    return 0
}

# Run the interactive config generator.
#   $1            = repo root
#   FORCE_SETUP=1 = always run (even when config exists)
#   GEN_RUNNER    = array-ish string of the python runner, default "python3"
invoke_config_generator() {
    local repo="$1"
    local runner="${GEN_RUNNER:-python3}"
    if [[ "${FORCE_SETUP:-0}" != "1" ]] && config_present; then
        echo "[config] Config files already present in $(nexscout_dir) — skipping generator."
        return 0
    fi
    local gen="$repo/scripts/common/generate_config.py"
    if [[ ! -f "$gen" ]]; then
        echo "[config] WARNING: generator not found at $gen — skipping." >&2
        return 0
    fi
    echo "[config] Launching interactive config generator..."
    # shellcheck disable=SC2086
    $runner "$gen" || echo "[config] WARNING: generator exited non-zero. Continuing." >&2
}

# Poll the web UI /healthz until 200 or timeout. $1 = timeout seconds (default 90).
wait_web_healthy() {
    local timeout="${1:-90}"
    echo "[wait] Waiting for the web UI at $NEX_WEB_HEALTH (timeout ${timeout}s)..."
    local end=$(( $(date +%s) + timeout ))
    while (( $(date +%s) < end )); do
        if curl -fsS --max-time 5 "$NEX_WEB_HEALTH" >/dev/null 2>&1; then
            echo "[wait] Web UI is healthy."
            return 0
        fi
        sleep 2
    done
    echo "[wait] WARNING: web UI did not become healthy within ${timeout}s." >&2
    return 1
}

# Open BOTH dashboards. Never hard-fails: prints the URL if xdg-open is absent.
open_dashboards() {
    local url
    for url in "$NEX_WEB_URL" "$OPENCLAW_URL"; do
        if command -v xdg-open >/dev/null 2>&1; then
            if xdg-open "$url" >/dev/null 2>&1; then
                echo "[open] Opened $url"
            else
                echo "[open] Could not auto-open a browser. Visit: $url"
            fi
        else
            echo "[open] xdg-open not available. Visit: $url"
        fi
    done
    echo
    echo "Dashboards:"
    echo "  NexScout web UI:    $NEX_WEB_URL"
    echo "  OpenClaw dashboard: $OPENCLAW_URL"
}

# Fail with a helpful message if a required command is missing.
assert_command() {
    local name="$1" hint="$2"
    if ! command -v "$name" >/dev/null 2>&1; then
        echo "ERROR: required command '$name' not found on PATH. $hint" >&2
        return 1
    fi
    return 0
}

# Best-effort LM Studio reachability check (warn-only).
check_lmstudio() {
    local url="${1:-http://localhost:1234/v1/models}"
    if curl -fsS --max-time 4 "$url" >/dev/null 2>&1; then
        echo "[lmstudio] LM Studio reachable at $url"
    else
        echo "[lmstudio] WARNING: LM Studio not reachable at $url. Start it and load a model, then set settings.yaml -> llm.primary = lmstudio:<model-id>. (score/tailor/apply need it.)" >&2
    fi
}
