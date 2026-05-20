#!/usr/bin/env bash
# סריקה מלאה 2,114 מניות במחשב + העלאת הדוח לענן (לצפייה מכל מחשב)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROFILE="${1:-simple}"
TOKEN_FILE="$HOME/Desktop/hf_token.txt"
USER_FILE="$HOME/Desktop/hf_username.txt"

if [[ ! -f .env ]]; then
  echo "חסר .env עם POLYGON_API_KEY"
  exit 1
fi

echo "▶ סריקה מלאה (profile=$PROFILE) — כל המניות..."
python3 scripts/run_pro_scanner.py \
  --universe-csv data/universe/polygon_liquid_us.csv \
  --profile "$PROFILE"

case "$PROFILE" in
  simple) SUFFIX="us_simple" ;;
  medium) SUFFIX="us_medium" ;;
  full)   SUFFIX="us_full" ;;
  *)      SUFFIX="us_${PROFILE}" ;;
esac
LATEST="$(ls -t "data/reports/"*_"${SUFFIX}"_report.csv 2>/dev/null | head -1)"
if [[ -z "$LATEST" ]]; then
  LATEST="$(ls -t data/reports/*_report.csv 2>/dev/null | head -1)"
fi
if [[ -z "$LATEST" ]]; then
  LATEST="$(ls -t data/reports/*_report.csv 2>/dev/null | head -1)"
fi

if [[ ! -f "$LATEST" ]]; then
  echo "לא נוצר דוח."
  exit 1
fi

echo ""
echo "✓ דוח מקומי: $LATEST"
echo "  שורות: $(wc -l < "$LATEST" | tr -d ' ')"

if [[ ! -f "$TOKEN_FILE" ]]; then
  echo ""
  echo "להעלאה לענן: צור $TOKEN_FILE (אסימון Write מ-Hugging Face)"
  echo "ואז: python3 scripts/upload_report_to_hf.py \"$LATEST\""
  exit 0
fi

export HF_TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
if [[ -f "$USER_FILE" ]]; then
  export HF_USERNAME="$(tr -d '[:space:]' < "$USER_FILE")"
fi
export HF_USERNAME="${HF_USERNAME:-azr6768689}"

echo ""
echo "▶ מעלה דוח ל-Hugging Face..."
python3 scripts/upload_report_to_hf.py "$LATEST"

echo ""
echo "מוכן. פתח את הקישור מהמייל — תראה את כל המניות."
