#!/usr/bin/env bash
# Push POLYGON_API_KEY from local .env to Render (needs RENDER_API_KEY).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SERVICE_ID="${RENDER_SERVICE_ID:-srv-d86mm5d7vvec73ad89f0}"
RENDER_API_KEY="${RENDER_API_KEY:-}"

if [[ -z "$RENDER_API_KEY" ]]; then
  echo "חסר RENDER_API_KEY."
  echo "Render Dashboard → Account → API Keys → Create →"
  echo "export RENDER_API_KEY=rnd_..."
  echo "bash scripts/sync_polygon_key_to_render.sh"
  exit 1
fi

POLYGON_KEY="$(python3 -c "
from pathlib import Path
from dotenv import load_dotenv
import os
load_dotenv(Path('$ROOT') / '.env')
from src.polygon_key_store import resolve_polygon_api_key
print(resolve_polygon_api_key())
")"

if [[ -z "$POLYGON_KEY" ]]; then
  echo "אין מפתח ב-.env או ב-data/.polygon_key"
  exit 1
fi

python3 -c "
from src.polygon_preflight import validate_polygon_api_key
ok, msg = validate_polygon_api_key('$POLYGON_KEY')
print('preflight:', ok, msg)
if not ok:
    raise SystemExit(1)
"

echo "מעדכן POLYGON_API_KEY ב-Render service $SERVICE_ID ..."
curl -fsS -X PUT \
  "https://api.render.com/v1/services/${SERVICE_ID}/env-vars" \
  -H "Authorization: Bearer ${RENDER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "[{\"key\":\"POLYGON_API_KEY\",\"value\":\"${POLYGON_KEY}\"}]"

echo "בוצע. Render יעשה restart אוטומטי."
