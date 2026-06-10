#!/usr/bin/env bash
#
# start-direct.sh — start NexScout directly in a local .venv (pip install -e).
#
# Creates/activates a .venv, installs NexScout (+ the python-jobspy two-step
# from the README), optionally (re)generates config, runs `nexscout doctor`,
# starts the web UI on :8765 in the background, waits for health, opens the
# NexScout dashboard, then runs the crash-resilient `nexscout autopilot` loop
# in the foreground (Ctrl+C to stop). The OpenClaw gateway is Docker-only — use
# start-docker.sh for the OpenClaw Control UI on :18789.
#
# Usage: ./start-direct.sh [--setup]
#   --setup   force the interactive config generator to run first.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

[[ "${1:-}" == "--setup" ]] && export FORCE_SETUP=1

REPO="$(repo_root)"
cd "$REPO"
echo "=== NexScout : direct (.venv) launcher ==="
echo "[repo] $REPO"

# --- 0. Prerequisite: python3 ---------------------------------------------- #
assert_command python3 "Install Python 3.11+ via your package manager (e.g. apt install python3 python3-venv)." || exit 1

# --- 1. Virtual environment ------------------------------------------------ #
VENV="$REPO/.venv"
if [[ ! -f "$VENV/bin/activate" ]]; then
    echo "[venv] Creating virtual environment at $VENV ..."
    python3 -m venv "$VENV"
fi
echo "[venv] Activating $VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# --- 2. Install ------------------------------------------------------------ #
echo "[install] pip install -e '.[dev,web]' ..."
python -m pip install --upgrade pip >/dev/null
pip install -e ".[dev,web]"
# python-jobspy two-step (see README): install without deps, then add its real
# runtime deps separately to avoid the numpy pin conflict.
echo "[install] python-jobspy two-step ..."
pip install --no-deps python-jobspy
pip install pydantic tls-client requests markdownify regex

# --- 3. Config ------------------------------------------------------------- #
GEN_RUNNER=python invoke_config_generator "$REPO"

# --- 4. Doctor + LM Studio check ------------------------------------------- #
check_lmstudio
echo "[doctor] nexscout doctor ..."
nexscout doctor || echo "[doctor] WARNING: doctor reported issues. Continuing."

# --- 5. Web UI (background) ------------------------------------------------- #
echo "[web] Starting 'nexscout web --host 0.0.0.0 --port 8765' in the background ..."
nexscout web --host 0.0.0.0 --port 8765 &
WEB_PID=$!
echo "$WEB_PID" > "$REPO/.nexscout-web.pid"

wait_web_healthy 90 || echo "[web] Opening the dashboard anyway (it may not respond yet)."
open_web_dashboard

# --- 6. Autopilot (resilient loop, foreground) ----------------------------- #
echo "[autopilot] Starting the resilient loop: nexscout autopilot"
echo "            It loops discover->enrich->score->tailor->render->apply->questions"
echo "            forever, surviving per-pass errors. Ctrl+C to stop."
echo "            (one-shot single pass instead: nexscout run)"
echo "            Web UI PID $WEB_PID keeps running in the background."
echo "            Stop everything with: ./scripts/linux/stop.sh"
nexscout autopilot

echo
echo "Autopilot exited. Web UI PID $WEB_PID may still be running in the background."
echo "Stop everything with: ./scripts/linux/stop.sh"
