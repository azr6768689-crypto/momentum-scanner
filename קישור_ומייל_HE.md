# סורק הזהב — גישה מכל מחשב (מייל / דפדפן)

## הקישור שלך

**קישור ישיר (מומלץ):** https://azr6768689-momentum-scanner.hf.space

**אם הקישור לא נפתח (404 / שגיאה):**

1. נסו קודם **להתחבר ל־[Hugging Face](https://huggingface.co)** ואז לפתוח את הדוח:  
   **https://huggingface.co/spaces/azr6768689/momentum-scanner**
2. בדף ה-Space: **Settings** → ודאו שה-Space מוגדר **Public** (Private גורם לעיתים ל-404 למשתמשים שלא מחוברים).

אין צורך להתקין תוכנה — רק דפדפן (Chrome, Safari, Edge).

---

## שלב 1 — הגדרת סיסמה (פעם אחת)

1. היכנס ל-[Hugging Face](https://huggingface.co) עם המשתמש `azr6768689`
2. פתח את ה-Space: [momentum-scanner](https://huggingface.co/spaces/azr6768689/momentum-scanner)
3. לחץ **Settings** → **Secrets**
4. הוסף או עדכן:

| Secret | ערך |
|--------|-----|
| `DASHBOARD_PASSWORD` | הסיסמה שתזין בכל כניסה |
| `POLYGON_API_KEY` | מפתח Polygon |
| `DATA_PROVIDER` | `polygon` |
| `RUN_SCAN_ON_STARTUP` | `false` |
| `AUTO_SCAN_ON_ENTRY` | `true` (אופציונלי — סריקה בכניסה) |

5. המתן 1–2 דקות לבנייה מחדש של ה-Space

---

## שלב 2 — שליחה במייל

העתק את הטקסט הבא לגוף המייל:

```
שלום,

הסורק האישי שלי (סורק הזהב / Golden Scanner):

https://azr6768689-momentum-scanner.hf.space

אם לא נפתח: https://huggingface.co/spaces/azr6768689/momentum-scanner (אחרי התחברות ל-HF)

כניסה: סיסמה (אשלח בנפרד / טלפון).

בכל מחשב: פותחים את הקישור → מזינים סיסמה → בוחרים דוח בסרגל.

בברכה
```

---

## שלב 3 — שימוש יומי

1. פתח את הקישור
2. הזן **סיסמה**
3. בסרגל: **דוח** → בחר תאריך (פשוטה / בינונית / מקיפה)
4. **יעוץ ועוזרים** → Google Finance, TradingView, Finviz
5. **סריקה** → הרץ סריקה חדשה בענן (אם צריך)

---

## העלאת דוח מהמחשב (אופציונלי)

אם הרצת סריקה ב-Mac:

```bash
cd ~/Downloads/momentum_system
export HF_TOKEN='האסימון_שלך'
export HF_USERNAME='azr6768689'
python3 scripts/upload_report_to_hf.py data/reports/2026-05-20_us_simple_report.csv
```

---

## עדכון קוד בענן

```bash
cd ~/Downloads/momentum_system
export HF_TOKEN='...'
export HF_USERNAME='azr6768689'
bash scripts/prepare_hf_upload.sh
python3 scripts/upload_to_huggingface.py
```
