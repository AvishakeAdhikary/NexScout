#!/usr/bin/env bash
#
# stop.sh — stop NexScout, either the local processes (direct / uv) or Docker.
#
# Default: kills the background web UI (via .nexscout-web.pid) plus lingering
# `nexscout` processes. With --docker: `docker compose down` (add --volumes to
# also drop named volumes; the SQLite DB lives on the host mount and survives).
#
# Usage:
#   ./stop.sh              # stop local direct/uv processes
#   ./stop.sh --docker     # docker compose down
#   ./stop.sh --docker --volumes
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

REPO="$(repo_root)"
cd "$REPO"
echo "=== NexScout : stop ==="

DOCKER=0
VOLUMES=0
for arg in "$@"; do
    case "$arg" in
        --docker)  DOCKER=1 ;;
        --volumes) VOLUMES=1 ;;
        *) echo "[stop] Unknown argument: $arg" >&2 ;;
    esac
done

if [[ "$DOCKER" == "1" ]]; then
    # --- Docker teardown --------------------------------------------------- #
    COMPOSE="$REPO/docker-compose.yml"
    down_args=(-f "$COMPOSE" --profile openclaw down)
    [[ "$VOLUMES" == "1" ]] && down_args+=(-v)
    echo "[docker] docker compose ${down_args[*]} ..."
    docker compose "${down_args[@]}"
    echo "[docker] Stack stopped."
    exit 0
fi

# --- Local process teardown ------------------------------------------------ #
PID_FILE="$REPO/.nexscout-web.pid"
if [[ -f "$PID_FILE" ]]; then
    WEB_PID="$(tr -d '[:space:]' < "$PID_FILE")"
    if [[ -n "$WEB_PID" ]] && kill -0 "$WEB_PID" 2>/dev/null; then
        kill "$WEB_PID" 2>/dev/null || true
        echo "[stop] Killed web UI process (PID $WEB_PID)."
    else
        echo "[stop] Web UI process not running."
    fi
    rm -f "$PID_FILE"
else
    echo "[stop] No .nexscout-web.pid found."
fi

# Best-effort: kill lingering nexscout processes (e.g. `nexscout run`).
if command -v pkill >/dev/null 2>&1; then
    if pkill -f '\bnexscout\b' 2>/dev/null; then
        echo "[stop] Killed lingering nexscout processes."
    fi
fi

echo "[stop] Done. (For the Docker stack instead, run: ./stop.sh --docker)"
