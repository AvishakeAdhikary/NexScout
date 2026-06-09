#!/usr/bin/env bash
#
# start-docker.sh — start the full NexScout + OpenClaw stack via Docker Compose.
#
# No docker.exe PATH quirk on Linux; HOME is already set. Brings up
# `docker compose --profile openclaw up -d` (nexscout + the openclaw gateway
# on :18789), starts the web UI inside the container on :8765, waits for
# health, and opens BOTH dashboards.
#
# Usage: ./start-docker.sh [--setup]
#   --setup   force the interactive config generator to run first.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

[[ "${1:-}" == "--setup" ]] && export FORCE_SETUP=1

REPO="$(repo_root)"
cd "$REPO"
echo "=== NexScout : Docker launcher ==="
echo "[repo] $REPO"

# --- 0. Prerequisites ------------------------------------------------------ #
assert_command docker "Install Docker Engine + the compose plugin (https://docs.docker.com/engine/install/)." || exit 1
if ! docker compose version >/dev/null 2>&1; then
    echo "ERROR: 'docker compose' (v2) is not available. Install the docker-compose-plugin." >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon is not responding. Start it (e.g. 'sudo systemctl start docker') and re-run." >&2
    exit 1
fi

COMPOSE="$REPO/docker-compose.yml"

# --- 1. Config ------------------------------------------------------------- #
# The container reads ~/.nexscout (mounted). Generate it on the host first.
invoke_config_generator "$REPO"

# --- 2. LM Studio note ----------------------------------------------------- #
check_lmstudio
echo "[lmstudio] Inside Docker, NexScout reaches LM Studio at http://host.docker.internal:1234/v1."

# --- 3. Bring up the stack (nexscout + openclaw gateway) ------------------- #
echo "[docker] docker compose --profile openclaw up -d ..."
docker compose -f "$COMPOSE" --profile openclaw up -d

# --- 4. Start the web UI inside the nexscout container --------------------- #
# The compose `command` is `run` (one-shot pipeline); start the web server
# explicitly, bound to 0.0.0.0 so the host port mapping works.
echo "[web] docker compose exec -d nexscout nexscout web --host 0.0.0.0 --port 8765 ..."
if ! docker compose -f "$COMPOSE" exec -d nexscout nexscout web --host 0.0.0.0 --port 8765; then
    echo "[web] WARNING: could not start the web UI yet; container may still be initializing. Retrying in 5s." >&2
    sleep 5
    docker compose -f "$COMPOSE" exec -d nexscout nexscout web --host 0.0.0.0 --port 8765 || true
fi

# --- 5. Wait for health + open dashboards ---------------------------------- #
wait_web_healthy 120 || echo "[web] Opening dashboards anyway."
open_dashboards

echo
echo "Stack is up via Docker Compose (profile: openclaw)."
echo "  See running containers : docker compose ps"
echo "  Tail logs              : docker compose logs -f"
echo "  Stop everything        : ./scripts/linux/stop.sh --docker"
