# Apex Momentum Scanner

סורק מומנטום מוסדי חדש — מחליף את הסורק הישן (`pro_long_scanner`).

## הרצה

```bash
pip install -r requirements.txt
export DATA_PROVIDER=polygon
export POLYGON_API_KEY=your_key   # או שמור ב-data/.polygon_key
python scripts/run_apex_scanner.py
streamlit run dashboard/apex_app.py
```

## דוח

`data/reports/YYYY-MM-DD_apex_report.csv`

עמודות עיקריות: **Apex Score**, **RS Rating**, דפוס, רמת מוסדי, תוכנית מסחר (כניסה/סטופ/יעדים).

## ענן (Render)

- `SCAN_ENGINE=apex` (ברירת מחדל)
- דשבורד: `dashboard/apex_app.py`
- סריקה: `scripts/run_apex_scanner.py`

## נתונים אמיתיים

```
DATA_PROVIDER=polygon
POLYGON_API_KEY=...
```

## ביצועים (דמו, ~2,114 מניות)

כ־10–15 שניות מקומית · כ־30–60 שניות בענן Free.
