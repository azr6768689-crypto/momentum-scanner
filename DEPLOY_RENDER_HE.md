# העלאת Momentum Scanner לענן עם Render

המטרה: לקבל קישור קבוע שאפשר לשלוח לעצמך במייל ולהיכנס מכל מחשב עם אינטרנט.

## מה כבר מוכן בפרויקט

- `render.yaml` - הגדרות Render.
- `runtime.txt` - Python 3.11.9.
- `scripts/start_render.py` - מריץ סריקה ראשונה אם אין דוח, ואז מפעיל Streamlit.
- הדשבורד תומך בסיסמה דרך `DASHBOARD_PASSWORD`.
- הדשבורד כולל כפתור `הרץ סריקה חדשה`.

## שלב 1: להעלות ל-GitHub פרטי

1. לפתוח חשבון ב-GitHub.
2. ליצור Repository חדש כ-Private.
3. להעלות אליו את תיקיית הפרויקט.

חשוב:

- לא להעלות `.env`.
- כן להעלות את `data/universe/polygon_liquid_us.csv`.
- כן להעלות את `data/universe/sector_map.csv`.

## שלב 2: לפתוח Render

1. להיכנס ל-[Render](https://render.com).
2. ללחוץ `New`.
3. לבחור `Blueprint`.
4. לבחור את ה-GitHub repository של הפרויקט.
5. Render יקרא את `render.yaml` אוטומטית.

## שלב 3: להוסיף סודות ב-Render

במסך השירות ב-Render, תחת `Environment`, להוסיף:

```text
POLYGON_API_KEY=המפתח_שלך_מPolygon
DASHBOARD_PASSWORD=סיסמה_שרק_אתה_יודע
```

אפשר להשאיר את שאר המשתנים כמו שהם:

```text
DATA_PROVIDER=polygon
SCANNER_INTRADAY_TOP=50
SCANNER_NEWS_TOP=100
ENABLE_DASHBOARD_SCAN_BUTTON=true
```

## שלב 4: Deploy

ללחוץ `Deploy`.

בפעם הראשונה Render יתקין חבילות ויעלה את הדשבורד.

אחרי שהדשבורד נפתח, לוחצים בסרגל הצד:

```text
הרץ סריקה חדשה
```

כך האתר עולה מהר ולא נתקע בזמן ההפעלה הראשונה.

בסוף תקבל קישור כמו:

```text
https://momentum-scanner.onrender.com
```

את הקישור הזה אפשר לשלוח לעצמך במייל.

## שימוש יומי

1. פותחים את הקישור מהמייל.
2. מקלידים סיסמה.
3. רואים את הדוח האחרון.
4. אם רוצים לעדכן: לוחצים `הרץ סריקה חדשה` בסרגל הצד.

## הערות חשובות

- הנתונים מגיעים מ-Polygon, לכן חייבים `POLYGON_API_KEY`.
- הסיסמה מגינה על הדשבורד, אבל לא מחליפה אבטחה ארגונית מלאה.
- Render חינמי יכול להירדם. אם רוצים שהכל יעבוד מהר וקבוע, עדיף Render Starter/Paid.
- דוחות וקאש בענן תלויים באחסון של השירות. אם עושים redeploy, ייתכן שיהיה צורך להריץ סריקה מחדש.
