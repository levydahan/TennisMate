"""Count how often two players were teammates in the last N days.

Run against the production database (Render's DATABASE_URL):

    DATABASE_URL="postgresql://..." python pair_report.py אבירם רועי
    DATABASE_URL="postgresql://..." python pair_report.py אבירם רועי --days 182

Without DATABASE_URL it uses the local SQLite file (instance/tennis.db or DATA_DIR).
"""

import argparse
import json
from datetime import date, timedelta

from app import GameSettings, app
from players import canonical_player


def teammate_sessions(first: str, second: str, days: int) -> list[dict]:
    """Every session in the window where both players were on the same team."""
    target = frozenset({canonical_player(first) or first, canonical_player(second) or second})
    since = (date.today() - timedelta(days=days)).isoformat()
    found = []
    rows = GameSettings.query.filter(GameSettings.week_key >= since).order_by(GameSettings.week_key).all()
    for row in rows:
        for hour, raw in (("שעה ראשונה", row.teams_json), ("שעה שנייה", row.teams2_json)):
            if not raw:
                continue
            for team in json.loads(raw) or []:
                names = {
                    canonical_player(p.get("name") or "") or (p.get("name") or "")
                    for p in team.get("players") or []
                }
                if len(names) == 2 and names == target:
                    found.append({
                        "slot": row.slot,
                        "week_key": row.week_key,
                        "hour": hour,
                    })
    return found


def main():
    parser = argparse.ArgumentParser(description="Teammate count for two players")
    parser.add_argument("first")
    parser.add_argument("second")
    parser.add_argument("--days", type=int, default=182, help="window in days (default: ~half a year)")
    args = parser.parse_args()

    with app.app_context():
        found = teammate_sessions(args.first, args.second, args.days)

    sessions = sorted({(f["slot"], f["week_key"]) for f in found})
    print(f"{args.first} ו{args.second} — בשנה-חצי האחרונה ({args.days} ימים):")
    print(f"  מפגשים שבהם היו בזוג: {len(sessions)}")
    print(f"  סך הופעות בזוג (כולל שעה שנייה): {len(found)}")
    for slot, week_key in sessions:
        hours = [f["hour"] for f in found if (f["slot"], f["week_key"]) == (slot, week_key)]
        print(f"  - {slot} {week_key}: {', '.join(hours)}")


if __name__ == "__main__":
    main()
