#!/usr/bin/env bash
#
# clear-db.sh — wipe NexScout's runtime data (DBs, applications/, scratch,
# browser profiles) while KEEPING the config files. Thin wrapper over
# scripts/common/clear_db.py.
#
# By default it wipes the HOST config dir ($NEXSCOUT_DIR or ~/.nexscout) — the
# SAME directory mounted into the Docker containers.
#
# With --docker: stops the `nexscout` autopilot service first (so nothing
# writes during the wipe), wipes the host dir, then reminds you to restart.
# The wipe runs on the host because the container mounts that very dir.
#
# Config files (profile.yaml / settings.yaml / credentials.yaml and the
# OpenClaw config) are NEVER deleted.
#
# Usage:
#   ./clear-db.sh                 # wipe ~/.nexscout (asks for confirmation)
#   ./clear-db.sh --yes           # no prompt
#   ./clear-db.sh --docker --yes  # stop autopilot, wipe, remind to restart
#   ./clear-db.sh /some/dir -y    # explicit target dir
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

REPO="$(repo_root)"
SCRIPT="$REPO/scripts/common/clear_db.py"
if [[ ! -f "$SCRIPT" ]]; then
    echo "ERROR: clear_db.py not found at $SCRIPT" >&2
    exit 1
fi

echo "=== NexScout : clear database ==="

DOCKER=0
PY_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --docker) DOCKER=1 ;;
        *) PY_ARGS+=("$arg") ;;   # --yes/-y and an optional target dir pass through
    esac
done

# --- Optional: stop the autopilot first so nothing writes during the wipe --- #
if [[ "$DOCKER" == "1" ]]; then
    if command -v docker >/dev/null 2>&1; then
        echo "[docker] Stopping the 'nexscout' autopilot service to avoid a writer race..."
        docker compose -f "$REPO/docker-compose.yml" stop nexscout || \
            echo "[docker] (stop failed or service not running — continuing)"
    else
        echo "[docker] docker not found — skipping the autopilot stop. Make sure nothing is writing to the dir." >&2
    fi
fi

# --- Resolve the python runner: prefer uv, fall back to python3/python ------ #
UV="$HOME/.local/bin/uv"
RC=0
if [[ -x "$UV" ]]; then
    "$UV" run python "$SCRIPT" "${PY_ARGS[@]}" || RC=$?
elif command -v python3 >/dev/null 2>&1; then
    python3 "$SCRIPT" "${PY_ARGS[@]}" || RC=$?
elif command -v python >/dev/null 2>&1; then
    python "$SCRIPT" "${PY_ARGS[@]}" || RC=$?
else
    echo "ERROR: neither uv ($UV) nor python3/python were found." >&2
    exit 1
fi

if [[ "$DOCKER" == "1" ]]; then
    echo
    echo "[docker] Runtime data wiped on the host dir (mounted into the containers)."
    echo "[docker] Restart the stack when ready:  docker compose --profile openclaw up -d"
fi

exit "$RC"
