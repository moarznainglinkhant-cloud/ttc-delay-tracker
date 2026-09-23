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

from config import DB_PATH, ROUTES_OF_INTEREST, SUBWAY_LINE_OF_INTEREST, SUBWAY_LINES
from db import get_connection, insert_rows

random.seed(7)

CODES = ["MFESA", "MFUS", "MRD", "MEO", "EUAT", "MFR"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _weighted_delay() -> int:
    """Delays cluster near 0 with occasional bigger incidents, like real data."""
    return random.choice([0, 0, 0, 5, 5, 10, 15, 20, 30, 45])


def make_synthetic_bus_rows(n: int = 800) -> list[dict]:
    routes = list(ROUTES_OF_INTEREST.items())
    start = date.today() - timedelta(days=90)
    rows = []
    for _ in range(n):
        route, name = random.choice(routes)
        d = start + timedelta(days=random.randint(0, 90))
        hour = random.randint(0, 23)
        rows.append(
            {
                "mode": "bus",
                "date": d.isoformat(),
                "route": route,
                "route_name": name,
                "time": f"{hour:02d}:{random.choice(['00', '15', '30', '45'])}",
                "day": DAYS[d.weekday()],
                "location": f"{name.upper()} STOP {random.randint(1, 20)}",
                "code": random.choice(CODES),
                "min_delay": _weighted_delay(),
                "min_gap": random.choice([0, 0, 10, 20, 30, 40, 60]),
                "bound": random.choice(["N", "S", "E", "W"]),
                "vehicle": str(random.randint(1000, 9999)),
            }
        )
    return rows


def make_synthetic_subway_rows(n: int = 400, line: str = SUBWAY_LINE_OF_INTEREST) -> list[dict]:
    stations = [
        "KENNEDY STATION",
        "VICTORIA PARK STATION",
        "WARDEN STATION",
        "BLOOR STATION",
        "ST GEORGE STATION",
        "BAY STATION",
        "SPADINA STATION",
    ]
    start = date.today() - timedelta(days=90)
    rows = []
    for _ in range(n):
        d = start + timedelta(days=random.randint(0, 90))
        hour = random.randint(0, 23)
        # Make rush hours slightly worse, like real subway delay patterns.
        delay = _weighted_delay()
        if hour in (7, 8, 16, 17, 18):
            delay = max(delay, _weighted_delay())
        rows.append(
            {
                "mode": "subway",
                "date": d.isoformat(),
                "route": line,
                "route_name": SUBWAY_LINES.get(line, line),
                "time": f"{hour:02d}:{random.choice(['00', '15', '30', '45'])}",
                "day": DAYS[d.weekday()],
                "location": random.choice(stations),
                "code": random.choice(CODES),
                "min_delay": delay,
                "min_gap": random.choice([0, 0, 10, 20, 30, 40, 60]),
                "bound": random.choice(["E", "W"]),
                "vehicle": str(random.randint(5000, 5999)),
            }
        )
    return rows


def main() -> int:
    conn = get_connection(DB_PATH)
    inserted = insert_rows(conn, make_synthetic_bus_rows())
    inserted += insert_rows(conn, make_synthetic_subway_rows())
    print(f"Inserted {inserted} synthetic demo rows (bus + subway) into {DB_PATH}.")
    print("This is fake data for demo purposes — run `python fetch_data.py` for the real thing.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
