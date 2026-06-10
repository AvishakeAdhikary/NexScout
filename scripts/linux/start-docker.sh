#!/usr/bin/env bash
#
# start-docker.sh — start the full NexScout + OpenClaw stack via Docker Compose.
#
# No docker.exe PATH quirk on Linux; HOME is already set. Brings up
# `docker compose --profile openclaw up -d`, which starts FOUR things: the
# `nexscout` container (the crash-resilient `autopilot` loop), `nexscout-web`
# (the web UI on :8765, its own service — no exec step), and the `openclaw`
# gateway (Control UI on :18789). Waits for health, then opens BOTH dashboards
# (the OpenClaw one tokenized via dashboard-link.sh).
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

# --- 3. Bring up the full stack -------------------------------------------- #
# `up -d` with the openclaw profile starts FOUR things:
#   nexscout      — the crash-resilient `autopilot` loop (compose command)
#   nexscout-web  — the web UI on :8765 (its own service; no exec needed)
#   openclaw      — the gateway Control UI on :18789
#   (ollama is only added by the separate local-llm profile)
echo "[docker] docker compose --profile openclaw up -d ..."
docker compose -f "$COMPOSE" --profile openclaw up -d

# --- 4. Wait for health + open dashboards ---------------------------------- #
# nexscout-web serves :8765 directly; just wait for it.
wait_web_healthy 120 || echo "[web] Opening dashboards anyway."
open_dashboards   # resolves the tokenized OpenClaw link via dashboard-link.sh

echo
echo "Stack is up via Docker Compose (profile: openclaw)."
echo "  Autopilot is now RUNNING in the 'nexscout' container: it loops the full"
echo "  pipeline (discover->enrich->score->tailor->render->apply->questions)"
echo "  autonomously and keeps applying. restart:unless-stopped + SQLite state"
echo "  mean it auto-resumes after any container crash, reboot, or model unload."
echo "  See running containers : docker compose ps"
echo "  Tail autopilot logs    : docker compose logs -f nexscout"
echo "  Re-print dashboard link: ./scripts/linux/dashboard-link.sh"
echo "  Stop everything        : ./scripts/linux/stop.sh --docker"
