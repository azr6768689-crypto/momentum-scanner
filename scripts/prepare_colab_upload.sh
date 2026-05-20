#!/usr/bin/env bash
# יוצר ZIP אחד להעלאה ל-Google Drive + Colab (בלי .env)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/colab_upload_staging/momentum_system"
ZIP_PROJECT="$ROOT/momentum_colab_upload.zip"
ZIP="$HOME/Desktop/momentum_colab_upload.zip"
INSTRUCTIONS_DESKTOP="$HOME/Desktop/מה_להעלות_COLAB.txt"
INSTRUCTIONS_PROJECT="$ROOT/מה_להעלות_COLAB.txt"

rm -rf "$ROOT/colab_upload_staging"
mkdir -p "$OUT"

copy() {
  if [[ -e "$1" ]]; then
    mkdir -p "$OUT/$(dirname "$2")"
    cp -R "$1" "$OUT/$2"
  fi
}

copy "$ROOT/dashboard" "dashboard"
copy "$ROOT/src" "src"
copy "$ROOT/config" "config"
copy "$ROOT/scripts" "scripts"
copy "$ROOT/notebooks" "notebooks"
copy "$ROOT/requirements.txt" "requirements.txt"
copy "$ROOT/streamlit_app.py" "streamlit_app.py"
copy "$ROOT/data/universe/polygon_liquid_us.csv" "data/universe/polygon_liquid_us.csv"
copy "$ROOT/data/universe/sector_map.csv" "data/universe/sector_map.csv"
mkdir -p "$OUT/data/reports"
touch "$OUT/data/reports/.gitkeep"

find "$OUT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT" -name '.DS_Store' -delete 2>/dev/null || true

rm -f "$ZIP_PROJECT"
(cd "$ROOT/colab_upload_staging" && zip -r "$ZIP_PROJECT" momentum_system -x "*.DS_Store")

cat > "$INSTRUCTIONS_PROJECT" <<'EOF'
═══════════════════════════════════════════════════════════
  סורק Momentum — העלאה ל-Colab (מעודכן 20.05.2026)
═══════════════════════════════════════════════════════════

מעלים קובץ ZIP אחד בלבד (~230KB):

  momentum_colab_upload.zip

מיקומים אפשריים:
  • תיקיית הפרויקט: momentum_system/momentum_colab_upload.zip
  • שולחן העבודה:   Desktop/momentum_colab_upload.zip

───────────────────────────────────────────────────────────
כמה זמן זה לוקח? (בערך)
───────────────────────────────────────────────────────────

  שלב                          זמן משוער
  ─────────────────────────────────────────
  העלאת ZIP ל-Drive            30 שניות – 2 דקות
  חילוץ (Extract) ב-Drive      20–40 שניות
  פתיחת מחברת Colab + תאים 1–3 3–5 דקות (התקנת חבילות)
  סריקה פשוטה — פעם ראשונה    20–40 דקות (מוריד נתונים)
  סריקה פשוטה — יום שני+       30–60 שניות (קאש ב-Drive)
  סריקה בינונית (קאש חם)       1.5–3 דקות
  סריקה מקיפה (קאש חם)         3–6 דקות

  סה"כ ידני (בלי סריקה ראשונה): כ־5–10 דקות
  סה"כ כולל סריקה ראשונה פשוטה: כ־25–50 דקות

───────────────────────────────────────────────────────────
שלב 1 — Google Drive
───────────────────────────────────────────────────────────
1. פתח https://drive.google.com
2. "חדש" → "העלאת קובץ" → momentum_colab_upload.zip
3. ימני על הקובץ → "חלץ" (Extract)
4. ודא שנוצרה תיקייה:

     My Drive / momentum_system

───────────────────────────────────────────────────────────
שלב 2 — Google Colab
───────────────────────────────────────────────────────────
1. https://colab.research.google.com
2. פתח מ-Drive:
     momentum_system / notebooks / momentum_scanner_colab.ipynb
3. הרץ תאים 1 → 2 → 3 → 4 לפי הסדר
4. בתא 4 — הדבק מפתח Polygon (לא מעלים .env!)

───────────────────────────────────────────────────────────
רמות סריקה במחברת (SCAN_PROFILE)
───────────────────────────────────────────────────────────
  simple  — מהירה (מומלץ ליום-יום)
  medium  — מאוזנת
  full    — מלאה (הכי איטית, הכי עמוקה)

  דוגמה בתא סריקה:
    !python scripts/run_pro_scanner.py \
      --universe-csv data/universe/polygon_liquid_us.csv \
      --profile simple

───────────────────────────────────────────────────────────
מה יש ב-ZIP (אוטומטי — לא לבחור ידנית)
───────────────────────────────────────────────────────────
  dashboard/  src/  scripts/  config/
  notebooks/momentum_scanner_colab.ipynb
  data/universe/ (2,114 מניות)
  requirements.txt
  src/scan_profiles.py (3 רמות סריקה)

───────────────────────────────────────────────────────────
מה לא מעלים
───────────────────────────────────────────────────────────
  .env  — מפתחות רק בתא 4 במחברת
  data/reports/ ישנים — נוצרים מחדש ב-Colab

───────────────────────────────────────────────────────────
עדכון אחרי שינוי קוד במחשב
───────────────────────────────────────────────────────────
  bash scripts/prepare_colab_upload.sh

  ואז העלה שוב את momentum_colab_upload.zip ל-Drive
  (אפשר למחוק את התיקייה הישנה או לדרוס)

═══════════════════════════════════════════════════════════
EOF

cp -f "$INSTRUCTIONS_PROJECT" "$INSTRUCTIONS_DESKTOP" 2>/dev/null || true
cp -f "$ZIP_PROJECT" "$ZIP" 2>/dev/null || true

echo ""
echo "מוכן:"
echo "  ZIP:       $ZIP_PROJECT"
if [[ -f "$ZIP" ]]; then echo "  (גם Desktop: $ZIP)"; fi
echo "  הוראות:    $INSTRUCTIONS_PROJECT"
echo ""
echo "העלה ל-Drive רק את: momentum_colab_upload.zip"
