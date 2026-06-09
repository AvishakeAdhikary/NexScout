#!/usr/bin/env bash
#
# start-uv.sh — start NexScout via the `uv` package manager.
#
# Ensures `uv` is installed (installs via the official installer if missing),
# runs `uv sync`, optionally (re)generates config, runs doctor, starts the web
# UI on :8765 in the background, waits for health, opens BOTH dashboards, then
# runs `uv run nexscout run`.
#
# Usage: ./start-uv.sh [--setup]
#   --setup   force the interactive config generator to run first.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

[[ "${1:-}" == "--setup" ]] && export FORCE_SETUP=1

REPO="$(repo_root)"
cd "$REPO"
echo "=== NexScout : uv launcher ==="
echo "[repo] $REPO"

# --- 0. Ensure uv is installed --------------------------------------------- #
if ! command -v uv >/dev/null 2>&1; then
    echo "[uv] 'uv' not found — installing via the official installer ..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "ERROR: neither curl nor wget available to install uv. Install uv manually: https://docs.astral.sh/uv/getting-started/installation/" >&2
        exit 1
    fi
    # The installer drops uv into ~/.local/bin (or $XDG_BIN_HOME).
    export PATH="$HOME/.local/bin:${XDG_BIN_HOME:-$HOME/.local/bin}:$PATH"
    if ! command -v uv >/dev/null 2>&1; then
        echo "ERROR: uv installed but not on PATH. Open a new shell (or add ~/.local/bin to PATH) and re-run." >&2
        exit 1
    fi
fi
echo "[uv] $(uv --version)"

# --- 1. Sync dependencies -------------------------------------------------- #
echo "[uv] uv sync --extra dev --extra web ..."
uv sync --extra dev --extra web

# --- 2. Config ------------------------------------------------------------- #
# Use the project's interpreter (via `uv run python`) so pyyaml is available.
GEN_RUNNER="uv run python" invoke_config_generator "$REPO"

# --- 3. Doctor + LM Studio check ------------------------------------------- #
check_lmstudio
echo "[doctor] uv run nexscout doctor ..."
uv run nexscout doctor || echo "[doctor] WARNING: doctor reported issues. Continuing."

# --- 4. Web UI (background) ------------------------------------------------- #
echo "[web] Starting 'uv run nexscout web --host 0.0.0.0 --port 8765' in the background ..."
uv run nexscout web --host 0.0.0.0 --port 8765 &
WEB_PID=$!
echo "$WEB_PID" > "$REPO/.nexscout-web.pid"

wait_web_healthy 90 || echo "[web] Opening dashboards anyway (they may not respond yet)."
open_dashboards

# --- 5. Pipeline ----------------------------------------------------------- #
echo "[run] uv run nexscout run ..."
echo "      (to submit applications afterwards: uv run nexscout apply --workers 2)"
uv run nexscout run

echo
echo "NexScout is up. Web UI PID $WEB_PID is still running in the background."
echo "Stop everything with: ./scripts/linux/stop.sh"
