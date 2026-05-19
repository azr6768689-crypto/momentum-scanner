# העלאה לענן — הכי פשוט (בלי Python בחו"ל)

מומלץ: **Hugging Face Spaces** — העלאה בגרירה מהמחשב, בלי מסוף.

---

## חלק 1 — הרשמה (פעם אחת)

1. פתח: https://huggingface.co/join  
2. הירשם (אימייל או Google).

---

## חלק 2 — יצירת אתר (Space)

1. פתח: https://huggingface.co/new-space  
2. מלא:
   - **Space name:** `momentum-scanner` (או שם אחר באנגלית)
   - **License:** בסדר ברירת מחדל
   - **Space SDK:** בחר **Streamlit**
   - **Visibility:** **Private** (פרטי)
3. לחץ **Create Space**.

---

## חלק 3 — העלאת קבצים (גרירה — בלי מסוף)

1. ב-Space שנוצר → לשונית **Files**.
2. ב-Mac פתח **Finder** → **Downloads** → **momentum_system**.
3. בחר את **כל הקבצים והתיקיות** בתוך התיקייה (Cmd+A).  
   **אל תבחר** את הקובץ `.env` (אם רואים אותו — בטל סימון).
4. **גרור** את הבחירה לחלון הדפדפן (אזור Files ב-Hugging Face).
5. המתן עד שההעלאה נגמרת.

**חשוב:** לפני ההעלאה, בתיקיית הפרויקט:
- שנה שם `README_HF.md` ל-`README.md` (אם אין README עם כותרת HF),  
  **או** העתק את תוכן `README_HF.md` לתוך `README.md` בראש הקובץ.

---

## חלק 4 — סודות (מפתחות)

1. ב-Space → **Settings** → **Variables and secrets**.
2. הוסף:

| שם | ערך |
|----|-----|
| `POLYGON_API_KEY` | המפתח שלך מ-Polygon |
| `DASHBOARD_PASSWORD` | סיסמה לכניסה לאתר |
| `DATA_PROVIDER` | `polygon` |
| `RUN_SCAN_ON_STARTUP` | `false` |

3. שמור.

---

## חלק 5 — הפעלה

1. לשונית **App** (או Refresh).
2. המתן 2–5 דקות לבנייה ראשונה.
3. יופיע הדשבורד → הכנס סיסמה.
4. **הרץ סריקה חדשה** כשצריך דוח.

**קישור קבוע:** למעלה בדף ה-Space — שמור במייל.

---

## בחו"ל

רק: **קישור + סיסמה + אינטרנט**. בלי Python.

---

## אם משהו נכשל

- ודא שהועלו: `streamlit_app.py`, `requirements.txt`, `dashboard/`, `src/`, `data/universe/`.
- סריקה מלאה על שרת חינמי עלולה לקחת זמן — זה נורמלי.
