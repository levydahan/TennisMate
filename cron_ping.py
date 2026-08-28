"""GET the TennisMate reminder URL. Used as a Render Cron Job start command."""

import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get(
    "CRON_URL",
    "https://tennismate.onrender.com/api/cron/pay-reminder",
).strip()
SECRET = os.environ.get("CRON_SECRET", "").strip()

if not SECRET:
    sys.exit("CRON_SECRET is not set")

req = urllib.request.Request(
    URL,
    headers={
        "Authorization": f"Bearer {SECRET}",
        "X-Cron-Secret": SECRET,
        "User-Agent": "TennisMate-Cron/1.0",
    },
    method="GET",
)
try:
    with urllib.request.urlopen(req, timeout=90) as res:
        print(res.read().decode())
except urllib.error.HTTPError as exc:
    body = exc.read().decode(errors="replace")
    print(body, file=sys.stderr)
    raise SystemExit(exc.code)
