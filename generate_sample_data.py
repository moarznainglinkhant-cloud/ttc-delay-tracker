"""
Generate a small SYNTHETIC dataset for local demoing before you've run
fetch_data.py against the real API (or if you're on a network that
blocks the City of Toronto's API).

This data is randomly generated, not real TTC records — it exists only
so `streamlit run dashboard.py` has something to show immediately.
Run `python fetch_data.py` afterwards (or instead) to load real data.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from config import DB_PATH, ROUTES_OF_INTEREST
from db import get_connection, insert_rows

random.seed(7)

CODES = ["MFESA", "MFUS", "MRD", "MEO", "EUAT", "MFR"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def make_synthetic_rows(n: int = 800) -> list[dict]:
    routes = list(ROUTES_OF_INTEREST.items())
    start = date.today() - timedelta(days=90)
    rows = []
    for i in range(n):
        route, name = random.choice(routes)
        d = start + timedelta(days=random.randint(0, 90))
        rows.append(
            {
                "date": d.isoformat(),
                "route": route,
                "route_name": name,
                "time": f"{random.randint(0, 23):02d}:{random.choice(['00', '15', '30', '45'])}",
                "day": DAYS[d.weekday()],
                "location": f"{name.upper()} STOP {random.randint(1, 20)}",
                "code": random.choice(CODES),
                "min_delay": random.choice([0, 0, 5, 10, 15, 20, 30, 45]),
                "min_gap": random.choice([0, 0, 10, 20, 30, 40, 60]),
                "bound": random.choice(["N", "S", "E", "W"]),
                "vehicle": str(random.randint(1000, 9999)),
            }
        )
    return rows


def main() -> int:
    rows = make_synthetic_rows()
    conn = get_connection(DB_PATH)
    inserted = insert_rows(conn, rows)
    print(f"Inserted {inserted} synthetic demo rows into {DB_PATH}.")
    print("This is fake data for demo purposes — run `python fetch_data.py` for the real thing.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
