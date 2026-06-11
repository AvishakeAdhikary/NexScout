#!/usr/bin/env bash
#
# set-model.sh — switch the NexScout LLM model. Thin wrapper over
# scripts/common/set_model.py.
#
# Rewrites the `llm` block in settings.yaml (primary/fallback/judge + the
# OpenAI-compatible provider endpoint) and, for OpenAI-compatible schemes,
# writes the api_key into credentials.yaml. All other YAML keys are preserved.
#
# All flags pass straight through to set_model.py:
#   --provider <preset>   lmstudio | openrouter | nim | openai | gemini |
#                         anthropic | ollama | openai_compat
#   --model <id>          model id (may contain ':')
#   --api-key <key>       Bearer key (OpenAI-compatible schemes -> credentials.yaml)
#   --base-url <url>      OpenAI-compatible base URL (required for openai_compat)
#   --judge-model <id>    give the judge a different model (same scheme)
#   --target <dir>        config dir (default: $NEXSCOUT_DIR or ~/.nexscout)
#
# With --docker (and Docker up) it also recreates the NexScout services so the
# switch is immediate:  docker compose up -d nexscout nexscout-web nexscout-mcp
# (The autopilot also reloads the profile each pass, so it applies live anyway.)
#
# Usage:
#   ./set-model.sh --provider openrouter \
#       --model google/gemma-4-26b-a4b-it:free --api-key sk-or-...
#   ./set-model.sh --provider lmstudio --model local-model
#   ./set-model.sh --provider gemini --model gemini-2.0-flash --docker
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$SCRIPT_DIR/_common.sh"

REPO="$(repo_root)"
SCRIPT="$REPO/scripts/common/set_model.py"
if [[ ! -f "$SCRIPT" ]]; then
    echo "ERROR: set_model.py not found at $SCRIPT" >&2
    exit 1
fi

echo "=== NexScout : set model ==="

# Strip --docker out of the pass-through args (it's handled by this wrapper).
DOCKER=0
PY_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --docker) DOCKER=1 ;;
        *) PY_ARGS+=("$arg") ;;
    esac
done

# --- Resolve the python runner: prefer uv, fall back to python3/python ------ #
UV="$HOME/.local/bin/uv"
if [[ -x "$UV" ]]; then
    "$UV" run python "$SCRIPT" "${PY_ARGS[@]}"
elif command -v python3 >/dev/null 2>&1; then
    python3 "$SCRIPT" "${PY_ARGS[@]}"
elif command -v python >/dev/null 2>&1; then
    python "$SCRIPT" "${PY_ARGS[@]}"
else
    echo "ERROR: neither uv ($UV) nor python3/python were found." >&2
    exit 1
fi

# --- Optional: recreate the services so the switch is immediate ------------- #
if [[ "$DOCKER" == "1" ]]; then
    if command -v docker >/dev/null 2>&1; then
        echo "[docker] Recreating services with the new model config..."
        docker compose -f "$REPO/docker-compose.yml" up -d nexscout nexscout-web nexscout-mcp
        echo "[docker] Done — the new model is live."
    else
        echo "[docker] docker not found — skipped the recreate. The autopilot will pick up the new config on its next pass." >&2
    fi
fi
