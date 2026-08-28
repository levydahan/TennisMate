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
