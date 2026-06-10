#!/usr/bin/env bash
#
# dashboard-link.sh — print BOTH NexScout dashboard URLs, resolving the
# tokenized OpenClaw link.
#
# Prints:
#   * the NexScout web UI    — http://localhost:8765
#   * the OpenClaw dashboard — http://localhost:18789 (tokenized when possible)
#
# The tokenized OpenClaw link is resolved in this order of preference:
#
#   1. Ask the OpenClaw CLI inside the running gateway container:
#          docker exec nexscout-openclaw node dist/index.js dashboard --print
#      (also tried with --json). If it emits a URL we surface it verbatim.
#
#   2. Fallback: read gateway.auth.token from ~/.openclaw/openclaw.json (via
#      python3 / node / grep, whichever is available) and build
#          http://localhost:18789/?token=<TOKEN>
#      (the documented query-param form). The raw token and the
#      OPENCLAW_GATEWAY_TOKEN env var are also printed for manual pasting.
#
# Robust by design: a missing container or config prints a helpful message and
# the untokenized URL — it never hard-fails.
#
# Dual purpose: run directly to print the links, OR source it to reuse
# openclaw_dashboard_link / show_dashboard_links from another launcher script.
#
# Usage:
#   ./dashboard-link.sh             # print both dashboards + token details
#   ./dashboard-link.sh --openclaw-only   # print just the resolved OpenClaw URL

# Dashboard contract (kept in sync with _common.sh).
NEX_WEB_URL="${NEX_WEB_URL:-http://localhost:8765}"
OPENCLAW_BASE_URL="${OPENCLAW_BASE_URL:-http://localhost:18789}"
OPENCLAW_CONTAINER="${OPENCLAW_CONTAINER:-nexscout-openclaw}"

# Module-level outputs set by openclaw_dashboard_link (avoids subshell quirks).
OPENCLAW_LINK=""
OPENCLAW_TOKEN=""
OPENCLAW_SOURCE="none"
OPENCLAW_NOTE=""

# Path to OpenClaw's gateway config.
_openclaw_config_path() {
    printf '%s\n' "${HOME}/.openclaw/openclaw.json"
}

# URL-encode a string (token may contain reserved chars). Pure-bash fallback.
_urlencode() {
    local s="$1" out="" c i
    for (( i = 0; i < ${#s}; i++ )); do
        c="${s:i:1}"
        case "$c" in
            [a-zA-Z0-9.~_-]) out+="$c" ;;
            *) printf -v c '%%%02X' "'$c"; out+="$c" ;;
        esac
    done
    printf '%s' "$out"
}

# Extract gateway.auth.token from the OpenClaw config. Echoes the token or
# nothing. Tries python3, then node, then a grep/sed fallback. Never fails hard.
_openclaw_token_from_config() {
    local cfg
    cfg="$(_openclaw_config_path)"
    [[ -f "$cfg" ]] || return 0

    if command -v python3 >/dev/null 2>&1; then
        python3 - "$cfg" <<'PY' 2>/dev/null && return 0
import json, sys
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
    t = d.get("gateway", {}).get("auth", {}).get("token")
    if t:
        print(t)
except Exception:
    pass
PY
    fi
    if command -v node >/dev/null 2>&1; then
        node -e '
try {
  const d = require(process.argv[1]);
  const t = d && d.gateway && d.gateway.auth && d.gateway.auth.token;
  if (t) process.stdout.write(String(t));
} catch (e) {}
' "$cfg" 2>/dev/null && return 0
    fi
    # Last resort: scrape "token": "<value>" near an auth block. Best-effort.
    grep -oE '"token"[[:space:]]*:[[:space:]]*"[^"]+"' "$cfg" 2>/dev/null \
        | head -n1 \
        | sed -E 's/.*"token"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' 2>/dev/null
    return 0
}

# Resolve a usable docker command. Echoes "docker" if present, else nothing.
_resolve_docker() {
    command -v docker >/dev/null 2>&1 && printf 'docker\n'
}

# Ask the OpenClaw CLI in the running container for a pre-authenticated link.
# Echoes the first http(s) URL found, or nothing. Never fails hard.
_openclaw_link_from_cli() {
    command -v docker >/dev/null 2>&1 || return 0

    # Is the gateway container running?
    local running
    running="$(docker ps --filter "name=${OPENCLAW_CONTAINER}" --filter 'status=running' --format '{{.Names}}' 2>/dev/null)"
    [[ "$running" == *"$OPENCLAW_CONTAINER"* ]] || return 0

    local extra out url
    for extra in "" "--json"; do
        if [[ -n "$extra" ]]; then
            out="$(docker exec "$OPENCLAW_CONTAINER" node dist/index.js dashboard --print "$extra" 2>/dev/null)"
        else
            out="$(docker exec "$OPENCLAW_CONTAINER" node dist/index.js dashboard --print 2>/dev/null)"
        fi
        [[ -n "$out" ]] || continue
        url="$(printf '%s' "$out" | grep -oE 'https?://[^[:space:]"'\'']+' | head -n1)"
        if [[ -n "$url" ]]; then
            printf '%s' "$url"
            return 0
        fi
    done
    return 0
}

# Resolve the best OpenClaw dashboard link into the OPENCLAW_* module vars.
openclaw_dashboard_link() {
    OPENCLAW_LINK=""
    OPENCLAW_TOKEN=""
    OPENCLAW_SOURCE="none"
    OPENCLAW_NOTE=""

    local docker
    docker="$(_resolve_docker)"

    # 1. Preferred: OpenClaw CLI inside the running container.
    local cli_url
    cli_url="$(_openclaw_link_from_cli)"
    if [[ -n "$cli_url" ]]; then
        OPENCLAW_LINK="$cli_url"
        OPENCLAW_SOURCE="cli"
        OPENCLAW_TOKEN="$(printf '%s' "$cli_url" | grep -oiE 'token=[^&[:space:]]+' | head -n1 | sed -E 's/^token=//I')"
        OPENCLAW_NOTE="Resolved via 'docker exec ${OPENCLAW_CONTAINER} node dist/index.js dashboard --print'."
        return 0
    fi

    # 2. Fallback: token from config, else from env, build the ?token= link.
    local token source
    token="$(_openclaw_token_from_config)"
    source="config"
    if [[ -z "$token" && -n "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
        token="$OPENCLAW_GATEWAY_TOKEN"
        source="env"
    fi

    if [[ -n "$token" ]]; then
        OPENCLAW_TOKEN="$token"
        OPENCLAW_SOURCE="$source"
        OPENCLAW_LINK="${OPENCLAW_BASE_URL}/#token=$(_urlencode "$token")"
        if [[ "$source" == "config" ]]; then
            OPENCLAW_NOTE="Token from $(_openclaw_config_path) (gateway.auth.token). '#token=' (URL fragment) is the tokenized form the gateway documents; if it doesn't auto-auth, paste the raw token in the Control UI instead."
        else
            OPENCLAW_NOTE="Token from \$OPENCLAW_GATEWAY_TOKEN. '#token=' (URL fragment) is the tokenized form the gateway documents; if it doesn't auto-auth, paste the raw token in the Control UI instead."
        fi
        return 0
    fi

    # 3. Nothing found — bare URL + guidance.
    OPENCLAW_LINK="$OPENCLAW_BASE_URL"
    if [[ -z "$docker" ]]; then
        OPENCLAW_NOTE="Docker not found, so the OpenClaw CLI couldn't be queried; and no token in $(_openclaw_config_path) or \$OPENCLAW_GATEWAY_TOKEN. Start the stack (start-docker.sh) or onboard OpenClaw, then re-run."
    else
        OPENCLAW_NOTE="Gateway container '${OPENCLAW_CONTAINER}' not running (or no token yet). Bring the stack up with: docker compose --profile openclaw up -d, then re-run. No token in $(_openclaw_config_path) or \$OPENCLAW_GATEWAY_TOKEN either."
    fi
    return 0
}

# Print both dashboards with resolved OpenClaw token details.
show_dashboard_links() {
    openclaw_dashboard_link
    echo
    echo "Dashboards:"
    echo "  NexScout web UI:    $NEX_WEB_URL"
    echo "  OpenClaw dashboard: $OPENCLAW_LINK"
    if [[ -n "$OPENCLAW_TOKEN" ]]; then
        echo
        echo "OpenClaw token (paste into the Control UI if the link does not auto-auth):"
        echo "  token                 : $OPENCLAW_TOKEN"
        echo "  OPENCLAW_GATEWAY_TOKEN: $OPENCLAW_TOKEN"
    fi
    if [[ -n "$OPENCLAW_NOTE" ]]; then
        echo
        echo "  note: $OPENCLAW_NOTE"
    fi
}

# Run directly (not sourced) -> print. Detect sourcing portably.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ "${1:-}" == "--openclaw-only" ]]; then
        openclaw_dashboard_link
        printf '%s\n' "$OPENCLAW_LINK"
    else
        show_dashboard_links
    fi
fi
