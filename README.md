# TennisMate

אפליקציית ניהול משחקי טניס בעברית: הרשמה לראשון ורביעי 20:00, רשימת המתנה, וחלוקת עלות מגרש של 60 ₪.

## הרצה מקומית

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

פתחו בדפדפן: http://127.0.0.1:5000

סיסמת מנהל ברירת מחדל: `0508716669` (אפשר לשנות עם משתנה הסביבה `ADMIN_PASSWORD`).

## העלאה ל-Render

1. העלו את הפרויקט ל-GitHub (ריפו חדש).
2. ב-[Render](https://dashboard.render.com) לחצו **New +** → **Blueprint**.
3. בחרו את הריפו. הקובץ `render.yaml` ייצור שירות ווב ומסד Postgres.
4. הגדירו את `ADMIN_PASSWORD` (אותה סיסמה או אחרת).
5. לאחר ה-deploy, האתר יהיה בכתובת `https://tennismate.onrender.com` (או השם שבחרתם).

בלי Blueprint: צרו **Web Service** מ-Python עם:

- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app --bind 0.0.0.0:$PORT`
- הוסיפו **PostgreSQL** וחברו את `DATABASE_URL` לשירות.

בלי Postgres הרשימות יימחקו בכל דיפלוי מחדש (SQLite על דיסק זמני).

## תזכורות ב-Render Cron

האתר החי: `https://tennismate.onrender.com`.  
Render לא תומך ב־`Asia/Jerusalem` — הלוח הוא **UTC**. אותו endpoint מטפל גם בתזכורת שעה-לפני וגם בתשלום ב־21:01, ושולח רק כשהזמן בישראל באמת הגיע.

### 1. משתנה סביבה (חובה)

בשירות הווב **וב־Cron Job** הגדירו את **אותו** ערך:

- `CRON_SECRET` — מחרוזת אקראית ארוכה (אל תשימו בגיט)

בשירות הווב: **Environment** → **Add Environment Variable** → `CRON_SECRET` → Save (יידרש redeploy).

### 2. Cron Job בדשבורד

השירות נוצר ידנית, אז Blueprint לא יוסיף Cron לבד. צרו אחד:

1. [New + → Cron Job](https://dashboard.render.com/create?type=cron)
2. אותו ריפו `levydahan/TennisMate`, ענף `main`, runtime **Python**.
3. **Build Command:** `true`
4. **Start Command:** `python cron_ping.py`
5. **Schedule:** `1 16-19 * * 0,3` (ראשון ורביעי, 16:01–19:01 UTC)
6. Instance: **Starter** (Cron ב-Render אינו חינמי; מינימום כ־$1 לחודש)
7. Environment: `CRON_SECRET` = אותו ערך כמו בווב. אופציונלי: `CRON_URL` = הכתובת למטה.

**כתובת (GET):**  
`https://tennismate.onrender.com/api/cron/pay-reminder`

**אימות (אחד מהם):**

- כותרת `Authorization: Bearer <CRON_SECRET>`
- כותרת `X-Cron-Secret: <CRON_SECRET>`
- שאילתה `?secret=<CRON_SECRET>`

`cron_ping.py` שולח את שתי הכותרות. חלופה בלי הקובץ:

```
python -c "import os,urllib.request; s=os.environ['CRON_SECRET']; urllib.request.urlopen(urllib.request.Request('https://tennismate.onrender.com/api/cron/pay-reminder', headers={'Authorization':'Bearer '+s,'X-Cron-Secret':s}), timeout=90)"
```

אחרי יצירה: **Trigger Run** בדף ה-Cron. אם יש 401 — ה-secret לא תואם או שהווב עוד לא עשה redeploy.

### לוח זמנים (UTC, כל השנה בערך)

| תזכורת | ישראל | קיץ (UTC+3) | חורף (UTC+2) | Cron נפרד (אופציונלי) |
| --- | --- | --- | --- | --- |
| שעה לפני | 19:00 ראשון/רביעי | 16:00 UTC | 17:00 UTC | `0 16,17 * * 0,3` → `/api/cron/hour-before` |
| תשלום | 21:01 ראשון/רביעי | 18:01 UTC | 19:01 UTC | `1 18,19 * * 0,3` → `/api/cron/pay-reminder` |

**Job אחד מספיק** עם `1 16-19 * * 0,3` על `/api/cron/pay-reminder` — הוא מריץ את שני הסוגים.

`render.yaml` כולל שני Cron Jobs לאלה שמסנכרנים Blueprint. אם הווב כבר קיים ידנית, **אל תסנכרנו את כל ה-Blueprint** (עלול ליצור שירות ווב נוסף) — צרו Cron בדשבורד שמפנה לכתובת למעלה.
