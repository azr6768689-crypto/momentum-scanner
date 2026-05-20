#!/usr/bin/env bash
# יוצר תיקייה ו-ZIP מוכנים להעלאה ל-Hugging Face (בלי .env)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/hf_space_upload"
ZIP="$HOME/Desktop/momentum_scanner_hf.zip"

rm -rf "$OUT"
mkdir -p "$OUT"

copy() {
  if [[ -e "$1" ]]; then
    mkdir -p "$OUT/$(dirname "$2")"
    cp -R "$1" "$OUT/$2"
  fi
}

copy "$ROOT/streamlit_app.py" "streamlit_app.py"
copy "$ROOT/requirements.txt" "requirements.txt"
copy "$ROOT/dashboard" "dashboard"
copy "$ROOT/src" "src"
copy "$ROOT/config" "config"
copy "$ROOT/scripts/run_pro_scanner.py" "scripts/run_pro_scanner.py"
copy "$ROOT/scripts/cloud_scan_runner.py" "scripts/cloud_scan_runner.py"
copy "$ROOT/DEPLOY_VERSION.txt" "DEPLOY_VERSION.txt"
copy "$ROOT/data/universe/polygon_liquid_us.csv" "data/universe/polygon_liquid_us.csv"
copy "$ROOT/data/universe/sector_map.csv" "data/universe/sector_map.csv"
mkdir -p "$OUT/data/reports"
REPORT_COUNT=0
for suffix in us_simple us_medium us_full; do
  LATEST="$(ls -t "$ROOT/data/reports/"*_"${suffix}"_report.csv 2>/dev/null | head -1)"
  if [[ -n "$LATEST" && -f "$LATEST" ]]; then
    cp "$LATEST" "$OUT/data/reports/"
    echo "דוח נוסף: $(basename "$LATEST")"
    REPORT_COUNT=$((REPORT_COUNT + 1))
  fi
done
if [[ "$REPORT_COUNT" -eq 0 ]]; then
  touch "$OUT/data/reports/.gitkeep"
fi

cp "$ROOT/README_HF.md" "$OUT/README.md"

mkdir -p "$OUT/.streamlit"
cat > "$OUT/.streamlit/config.toml" <<'EOF'
[server]
headless = true
enableCORS = false
EOF

rm -rf "$OUT/**/__pycache__" "$OUT/**/.DS_Store" 2>/dev/null || true
find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

rm -f "$ZIP"
(cd "$OUT" && zip -r "$ZIP" . -x "*.DS_Store")

echo ""
echo "מוכן:"
echo "  תיקייה: $OUT"
echo "  ZIP:    $ZIP"
