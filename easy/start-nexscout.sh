#!/usr/bin/env bash
# Start (or stop: ./start-nexscout.sh stop) NexScout on macOS or Linux with Docker.
#   1. checks that Docker is installed and running,
#   2. creates secret keys once (saved in .env next to this file - keep it, back it up),
#   3. downloads and starts NexScout, then opens it in your browser.
# With "update" it first replaces these files with the newest release (checked against the
# release's SHA256SUMS.txt; your .env and data are kept). After starting, older NexScout
# images are removed to free disk space.
set -euo pipefail
cd "$(dirname "$0")"
REPO="AvishakeAdhikary/NexScout"

say() { printf '%s\n' "$*"; }
fail() { say ""; say "ERROR: $*"; read -r -p "Press Enter to close" _ || true; exit 1; }
open_url() { if command -v open >/dev/null; then open "$1"; elif command -v xdg-open >/dev/null; then xdg-open "$1" >/dev/null 2>&1 || true; fi; }

# The version this folder runs: the release bundle pins it in docker-compose.yml.
bundle_version() { sed -nE 's/.*NEXSCOUT_VERSION:-([0-9]+\.[0-9]+\.[0-9]+)\}.*/\1/p' docker-compose.yml | head -n1; }

sha256() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

update_bundle() {
  local root latest current tmp base want have src f part
  root="$(cd .. && pwd)"
  [ -d "$root/backend" ] && fail "This is a developer copy of NexScout. Update it with git instead."
  say "Checking for a newer NexScout..."
  latest="$(curl -fsS --max-time 30 -H 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/$REPO/releases/latest" |
    sed -nE 's/.*"tag_name": *"v([0-9]+\.[0-9]+\.[0-9]+)".*/\1/p' | head -n1)" ||
    fail "Couldn't reach GitHub to check for updates. Check that you're online, then try again."
  [ -n "$latest" ] || fail "GitHub's answer didn't look like a NexScout release."
  current="$(bundle_version)"
  if [ "$current" = "$latest" ]; then say "You already have the newest NexScout ($latest)."; return 1; fi
  say "Updating NexScout $current -> $latest ..."
  base="https://github.com/$REPO/releases/download/v$latest"
  tmp="$(mktemp -d)"
  curl -fsSL --max-time 300 -o "$tmp/easy.zip" "$base/nexscout-easy-$latest.zip" &&
    curl -fsSL --max-time 60 -o "$tmp/SHA256SUMS.txt" "$base/SHA256SUMS.txt" ||
    fail "Couldn't download the update. Check that you're online, then try again."
  want="$(grep -E "^[0-9a-f]{64} +\*?nexscout-easy-$latest\.zip$" "$tmp/SHA256SUMS.txt" | cut -d' ' -f1 | head -n1)"
  [ -n "$want" ] || fail "The update has no checksum, so it wasn't installed."
  have="$(sha256 "$tmp/easy.zip")"
  [ "$have" = "$want" ] || fail "The downloaded update is damaged (checksum mismatch), so it wasn't installed."
  command -v unzip >/dev/null || fail "Please install 'unzip', then try again."
  unzip -q "$tmp/easy.zip" -d "$tmp"
  src="$tmp/NexScout-$latest"
  [ -f "$src/easy/docker-compose.yml" ] || fail "The update package looks incomplete, so it wasn't installed."
  # Replace the program files (move, so this running script keeps reading its old copy);
  # never .env (your keys) or your data (Docker volumes).
  for f in "$src/easy/"*; do
    [ -f "$f" ] && [ "$(basename "$f")" != ".env" ] && cp -p "$f" "./.$(basename "$f").new" &&
      mv -f "./.$(basename "$f").new" "./$(basename "$f")"
  done
  for part in docker/postgres/01-roles.sql docs/USER_GUIDE.md LICENSE; do
    [ -f "$src/$part" ] && mkdir -p "$root/$(dirname "$part")" && cp -p "$src/$part" "$root/$part"
  done
  chmod +x ./*.sh ./*.command 2>/dev/null || true
  rm -rf "$tmp"
  say "NexScout files updated to $latest."
  return 0
}

# The desktop app's Easy mode uses the same Docker project with its own keys. Starting this
# folder over it would leave stored keys unreadable, so another live install is refused.
foreign_stack() {
  local ours f
  ours="$(printf '%s' "$PWD/docker-compose.yml" | tr 'A-Z\\' 'a-z/')"
  docker ps -a --filter "label=com.docker.compose.project=nexscout-easy" \
    --format '{{.Label "com.docker.compose.project.config_files"}}' 2>/dev/null | tr ',' '\n' |
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      if [ "$(printf '%s' "$f" | tr 'A-Z\\' 'a-z/')" != "$ours" ] && [ -f "$f" ]; then
        printf '%s\n' "$f"
        break
      fi
    done
}

# Free disk space: remove NexScout images other than the version this folder runs.
remove_old_images() {
  local keep img
  keep="$(bundle_version)"
  [ -n "$keep" ] || return 0
  for img in $(docker images --filter "reference=ghcr.io/*/nexscout-*" --format '{{.Repository}}:{{.Tag}}' |
    grep -E '^ghcr\.io/[a-z0-9-]+/nexscout-(backend|web):[0-9]+\.[0-9]+\.[0-9]+$' | grep -v ":$keep\$" || true); do
    docker rmi "$img" >/dev/null 2>&1 && say "Removed the old image $img."
  done
  docker image prune -f >/dev/null 2>&1 || true
}

if [ "${1:-}" = "update" ]; then
  if update_bundle; then exec "$PWD/start-nexscout.sh"; fi
fi

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

OTHER="$(foreign_stack)"
[ -z "$OTHER" ] || fail "Another NexScout is already set up on this computer ($OTHER), with its own keys. Use that one, or stop and remove it first (in its folder: docker compose down). Your data in it is kept."

say "Downloading and starting NexScout (the first time takes a few minutes)..."
if docker compose -f docker-compose.yml --env-file "$ENV_FILE" pull; then
  docker compose -f docker-compose.yml --env-file "$ENV_FILE" up -d
elif [ -d ../backend ]; then
  say "Couldn't download the released images; building them from this folder instead..."
  docker compose -f docker-compose.yml -f docker-compose.build.yml --env-file "$ENV_FILE" up -d --build
else
  fail "Couldn't download NexScout. Check your internet connection and try again."
fi
remove_old_images

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
