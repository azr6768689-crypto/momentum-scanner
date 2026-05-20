#!/usr/bin/env bash
# הרצה מקומית מלאה — סריקה + דשבורד (Mac)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROFILE="${1:-simple}"
PORT="${PORT:-8501}"

if [[ ! -f .env ]]; then
  echo "חסר קובץ .env — העתק מ-.env.example והדבק POLYGON_API_KEY"
  exit 1
fi

echo "▶ סריקה מקומית (profile=$PROFILE)..."
python3 scripts/run_pro_scanner.py \
  --universe-csv data/universe/polygon_liquid_us.csv \
  --profile "$PROFILE"

echo ""
echo "▶ מפעיל דשבורד על http://localhost:$PORT"
if lsof -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "   (כבר רץ — מדלג על הפעלה)"
else
  nohup python3 -m streamlit run dashboard/app.py --server.port "$PORT" \
    > /tmp/momentum_streamlit.log 2>&1 &
  sleep 2
fi

open "http://localhost:$PORT" 2>/dev/null || true
echo ""
echo "מוכן. דשבורד: http://localhost:$PORT"
