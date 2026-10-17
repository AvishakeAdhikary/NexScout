#!/usr/bin/env bash
# Start (or stop: ./start-nexscout.sh stop) NexScout on macOS or Linux with Docker.
#   1. checks that Docker is installed and running,
#   2. creates secret keys once (saved in .env next to this file - keep it, back it up),
#   3. downloads and starts NexScout, then opens it in your browser.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '%s\n' "$*"; }
fail() { say ""; say "ERROR: $*"; read -r -p "Press Enter to close" _ || true; exit 1; }
open_url() { if command -v open >/dev/null; then open "$1"; elif command -v xdg-open >/dev/null; then xdg-open "$1" >/dev/null 2>&1 || true; fi; }

command -v docker >/dev/null 2>&1 || {
  say "NexScout runs inside Docker, which isn't installed yet. Opening the download page."
  open_url "https://www.docker.com/products/docker-desktop/"
  fail "Install Docker, start it once, then run this again."
}
if ! docker info >/dev/null 2>&1; then
  if [ "$(uname)" = "Darwin" ]; then say "Starting Docker Desktop..."; open -a Docker || true; fi
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 3; done
  docker info >/dev/null 2>&1 || fail "Docker isn't running. Start it, wait until it's ready, then try again."
fi

ENV_FILE="$PWD/.env"
if [ "${1:-}" = "stop" ]; then
  [ -f "$ENV_FILE" ] || { say "NexScout isn't set up here yet."; exit 0; }
  say "Stopping NexScout (your data is kept)..."
  docker compose -f docker-compose.yml --env-file "$ENV_FILE" stop
  exit 0
fi

if [ ! -f "$ENV_FILE" ]; then
  umask 077
  {
    echo "# NexScout secrets. Keep this file; back it up with your data. Never share it."
    echo "NEXSCOUT_MASTER_KEY=$(head -c 32 /dev/urandom | base64 | tr -d '\n')"
    echo "NEXSCOUT_PG_SUPERUSER_PASSWORD=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
    echo "NEXSCOUT_PORT=3000"
  } > "$ENV_FILE"
  say "Created your secret keys in $ENV_FILE (keep this file safe)."
fi
PORT="$(grep -E '^NEXSCOUT_PORT=' "$ENV_FILE" | cut -d= -f2)"
PORT="${PORT:-3000}"
export NEXSCOUT_PUBLIC_WEB_URL="http://localhost:$PORT"

say "Downloading and starting NexScout (the first time takes a few minutes)..."
if docker compose -f docker-compose.yml --env-file "$ENV_FILE" pull; then
  docker compose -f docker-compose.yml --env-file "$ENV_FILE" up -d
elif [ -d ../backend ]; then
  say "Couldn't download the released images; building them from this folder instead..."
  docker compose -f docker-compose.yml -f docker-compose.build.yml --env-file "$ENV_FILE" up -d --build
else
  fail "Couldn't download NexScout. Check your internet connection and try again."
fi

URL="http://localhost:$PORT"
say "Waiting for NexScout at $URL ..."
for _ in $(seq 1 100); do
  if curl -fsS -o /dev/null "$URL/login"; then
    say "NexScout is running. Opening $URL"
    say "It keeps working in the background. Run './start-nexscout.sh stop' to stop it."
    open_url "$URL"
    exit 0
  fi
  sleep 3
done
fail "NexScout is taking too long. Run 'docker compose logs' in $PWD to see why."
