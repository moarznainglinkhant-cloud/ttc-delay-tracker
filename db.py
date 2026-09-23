"""
Tiny SQLite storage layer for cleaned TTC delay rows.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS delays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    route TEXT NOT NULL,
    route_name TEXT,
    time TEXT,
    day TEXT,
    location TEXT,
    code TEXT,
    min_delay INTEGER NOT NULL DEFAULT 0,
    min_gap INTEGER NOT NULL DEFAULT 0,
    bound TEXT,
    vehicle TEXT,
    UNIQUE(date, route, time, location, vehicle)
);
CREATE INDEX IF NOT EXISTS idx_delays_route ON delays(route);
CREATE INDEX IF NOT EXISTS idx_delays_date ON delays(date);
"""


def get_connection(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def insert_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Insert cleaned rows, skipping duplicates. Returns count inserted."""
    if not rows:
        return 0
    cur = conn.executemany(
        """
        INSERT OR IGNORE INTO delays
            (date, route, route_name, time, day, location, code,
             min_delay, min_gap, bound, vehicle)
        VALUES
            (:date, :route, :route_name, :time, :day, :location, :code,
             :min_delay, :min_gap, :bound, :vehicle)
        """,
        rows,
    )
    conn.commit()
    return cur.rowcount


def row_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM delays").fetchone()[0]
