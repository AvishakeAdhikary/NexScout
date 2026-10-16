#!/usr/bin/env bash
# Regenerate typed API contracts for the web app from the FastAPI OpenAPI schema.
# Needs no database: the schema is produced by importing the app.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_JSON="$ROOT/apps/web/src/lib/api/openapi.json"
mkdir -p "$(dirname "$OUT_JSON")"
(cd "$ROOT/backend" && uv run python -c "
import json, sys
from nexscout.api.app import create_app
json.dump(create_app().openapi(), sys.stdout, indent=2, sort_keys=True)
") > "$OUT_JSON"
(cd "$ROOT/apps/web" && npx openapi-typescript src/lib/api/openapi.json -o src/lib/api/schema.d.ts)
echo "contracts regenerated"
