#!/usr/bin/env bash
# Sync turbo scan env vars to Render + trigger deploy.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SERVICE_ID="${RENDER_SERVICE_ID:-srv-d86mm5d7vvec73ad89f0}"
RENDER_API_KEY="${RENDER_API_KEY:-}"

if [[ -z "$RENDER_API_KEY" ]]; then
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env" 2>/dev/null || true
    set +a
    RENDER_API_KEY="${RENDER_API_KEY:-}"
  fi
fi

if [[ -z "$RENDER_API_KEY" ]]; then
  echo "חסר RENDER_API_KEY — Render Dashboard → Account → API Keys"
  exit 1
fi

ENV_JSON='[
  {"key":"RENDER","value":"true"},
  {"key":"DATA_PROVIDER","value":"demo"},
  {"key":"SCAN_PROFILE","value":"simple"},
  {"key":"SCAN_WORKERS","value":"2"},
  {"key":"SCAN_ANALYZE_WORKERS","value":"2"},
  {"key":"SCAN_TIMEOUT_SECONDS","value":"1200"},
  {"key":"SCAN_SKIP_SPARKLINES","value":"true"},
  {"key":"AUTO_SCAN_ON_ENTRY","value":"false"},
  {"key":"RUN_SCAN_ON_STARTUP","value":"false"}
]'

echo "מעדכן Environment ב-Render ($SERVICE_ID)..."
curl -fsS -X PUT \
  "https://api.render.com/v1/services/${SERVICE_ID}/env-vars" \
  -H "Authorization: Bearer ${RENDER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$ENV_JSON"

echo ""
echo "מפעיל Manual Deploy..."
curl -fsS -X POST \
  "https://api.render.com/v1/services/${SERVICE_ID}/deploys" \
  -H "Authorization: Bearer ${RENDER_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"clearCache":"do_not_clear"}'

echo ""
echo "בוצע. בעוד 2–4 דקות: https://momentum-scanner-bbhl.onrender.com"
echo "גרסה צפויה: scan-stable-v21"
