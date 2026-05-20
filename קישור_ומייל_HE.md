# סורק הזהב — גישה מכל מחשב (מייל / דפדפן)

## הקישור שלך

**קישור ישיר (מומלץ):** https://azr6768689-momentum-scanner.hf.space

**אם הקישור לא נפתח (404 / שגיאה):**

1. נסו קודם **להתחבר ל־[Hugging Face](https://huggingface.co)** ואז לפתוח את הדוח:  
   **https://huggingface.co/spaces/azr6768689/momentum-scanner**
2. בדף ה-Space: **Settings** → ודאו שה-Space מוגדר **Public** (Private גורם לעיתים ל-404 למשתמשים שלא מחוברים).

אין צורך להתקין תוכנה — רק דפדפן (Chrome, Safari, Edge).

---

## גישה בלי חשבון Hugging Face (חשוב)

רק משתמשים **מחוברים** ל-HF יכולים לשנות הגדרות. **המשתמשים שלך בדפדפן לא חייבים חשבון HF**:

1. ב־[דף ה-Space](https://huggingface.co/spaces/azr6768689/momentum-scanner): **Settings** → **Visibility** → **Public**.
2. אחרי שזה Public, הקישור הישיר אמור להיפתח **ללא התחברות ל-HF**; יש רק להזין את **סיסמת האפליקציה** (`DASHBOARD_PASSWORD`).

אם עדיין נדרשת התחברות — בדקו שוב ש־Public נשמר ושאין שגיאת בנייה בלוגים של ה-Space.

---

## נטפרי (או סינון אחר) — הקישור נחסם

**Hugging Face** (כולל `*.hf.space`) נמצא לעיתים ברשימת חסימה של נטפרי וספקים דומים. אין “תיקון” בתוך האפליקציה — צריך אחד מהבאים:

| מה עושים | הערות |
|----------|--------|
| **פנייה לנטפרי** | בקשת **הלבנה** לדומיינים: `huggingface.co`, `*.huggingface.co`, `*.hf.space` (לפי הנוהג אצלם). |
| **גלישה מנייד** | הרבה פעמים חבילת נתונים בטלפון **לא** עוברת דרך אותו סינון כמו Wi‑Fi בבית. |
| **אירוח נוסף (מומלץ אם אין הלבנה)** | להעלות עותף של אותו דשבורד ל־**[Render](https://render.com)** לפי `DEPLOY_RENDER_HE.md` — מקבלים כתובת כמו `https://....onrender.com` שלעיתים **לא** חסומה. |
| **משתנה בענן** | אחרי שיש כתובת Render: ב-HF Space → **Secrets** הוסיפו `ALTERNATE_APP_URL` עם ה-URL מ־Render — הוא יופיע בפאנל **גישה מכל מחשב** כקישור חלופי. |

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
| `ALTERNATE_APP_URL` | אופציונלי — אם פרסת גם ב-Render, הדבק כאן את `https://....onrender.com` כדי להציג קישור חלופי בדשבורד (מועיל כשנטפרי חוסם HF) |

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
