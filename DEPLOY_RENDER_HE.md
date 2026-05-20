# פריסה מלאה על Render (חלופה ל-Hugging Face / נטפרי)

המטרה: קישור ציבורי מסוג `https://momentum-scanner-xxxx.onrender.com` — **בלי חשבון Render אצל מי שנכנס**, רק סיסמת האפליקציה; לרוב עובר בסינון שחוסם את `huggingface.co`.

## מה כבר מוכן בפרויקט

- `render.yaml` — Blueprint (תוכנית **חינמית** `free`, סריקה מנותקת ברקע כמו ב-HF).
- `runtime.txt` — Python 3.11.9.
- `scripts/start_render.py` — מפעיל Streamlit; אופציונלית סריקה ראשונה אם אין דוח (`RUN_SCAN_ON_STARTUP`).
- הדשבורד מזהה אוטומטית `RENDER=true` ומפעיל **workers מקבילים + סריקה ברקע** (לא נתקע את הדפדפן).

**נטפרי:** אחרי שיש כתובת `onrender.com`, אפשר להדביק אותה ב-Hugging Face → Space Secrets → `ALTERNATE_APP_URL` כדי להציג קישור חלופי בממשק ה-HF.

---

## שלב 1: קוד ב-GitHub

הריפו אמור להיות על GitHub (למשל `azr6768689-crypto/momentum-scanner`), עם:

- **לא** לדחוף `.env`.
- **כן** `data/universe/polygon_liquid_us.csv` ו-`data/universe/sector_map.csv`.

עדכון מהמחשב:

```bash
cd ~/Downloads/momentum_system
git remote add github https://github.com/YOUR_USER/momentum-scanner.git   # אם עדיין אין
git push github main
```

---

## שלב 2: Render — חיבור Blueprint

1. היכנס ל-[Render Dashboard](https://dashboard.render.com) (חשבון Render — רק אתה, לא המשתמשים בסורק).
2. **New** → **Blueprint**.
3. חבר את ה-repository מ-GitHub והסכם להתקנת `render.yaml`.
4. Render יצור שירות **Web** בשם `momentum-scanner`.

---

## שלב 3: סודות חובה

בשירות שנוצר → **Environment** → הוסף לפחות:

| משתנה | ערך |
|--------|-----|
| `POLYGON_API_KEY` | מפתח מ-polygon.io |
| `DASHBOARD_PASSWORD` | סיסמה שתציג למשתמשי הסורק |

שאר המשתנים מוגדרים ב-`render.yaml` (כולל `SCAN_PROFILE=simple`, `AUTO_SCAN_ON_ENTRY=true`, `SCAN_WORKERS=6`).

אופציונלי אחרי שיש URL קבוע:

| משתנה | ערך |
|--------|-----|
| `PUBLIC_APP_URL` | `https://your-service.onrender.com` — יוצג בפאנל «גישה מכל מחשב» אם תרצה כיתוב מדויק |

שמור — Render יבנה מחדש.

---

## שלב 4: המתנה לבנייה וסריקה ראשונה

1. פתח את כתובת השירות מ-Render.
2. הזן `DASHBOARD_PASSWORD`.
3. אם אין דוח: המתן ל-**סריקה אוטומטית בכניסה** או לחץ **סריקה ידנית** בסרגל.

**Free:** השירות «נרדם» אחרי חוסר שימוש — הטעינה הראשונה אחרי שינה עלולה לקחת ~דקה.

---

## שימוש יומי

1. פותחים את קישור `onrender.com` מהמייל / סימנייה.
2. מזינים סיסמה.
3. בוחרים דוח ורמת סריקה לפי הצורך.

---

## הערות

- דוחות וקאש נשמרים על דיסק הקונטיינר — **redeploy** עלול למחוק; אם צריך שמירה קבועה, בשלב מאוחר יותר אפשר חיבור דיסק או אחסון חיצוני.
- אם סריקה מלאה נכשלת—בדוק לוגים ב-Render וב־`POLYGON_API_KEY`.
