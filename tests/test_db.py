"""
Tests for db.py using a throwaway in-memory-like SQLite file.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import get_connection, insert_rows, row_count  # noqa: E402

SAMPLE_BUS_ROW = {
    "mode": "bus",
    "date": "2025-01-01",
    "route": "116",
    "route_name": "Morningside",
    "time": "08:15",
    "day": "Wednesday",
    "location": "MORNINGSIDE AND KINGSTON",
    "code": "MFESA",
    "min_delay": 20,
    "min_gap": 40,
    "bound": "N",
    "vehicle": "3442",
}

SAMPLE_SUBWAY_ROW = {
    "mode": "subway",
    "date": "2025-01-01",
    "route": "BD",
    "route_name": "Line 2 Bloor–Danforth",
    "time": "08:15",
    "day": "Wednesday",
    "location": "KENNEDY STATION",
    "code": "MUSAN",
    "min_delay": 5,
    "min_gap": 9,
    "bound": "W",
    "vehicle": "5227",
}


def test_insert_and_count(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    inserted = insert_rows(conn, [SAMPLE_BUS_ROW])
    assert inserted == 1
    assert row_count(conn) == 1
    conn.close()


def test_duplicate_rows_are_skipped(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    insert_rows(conn, [SAMPLE_BUS_ROW])
    inserted_again = insert_rows(conn, [SAMPLE_BUS_ROW])
    assert inserted_again == 0
    assert row_count(conn) == 1
    conn.close()


def test_empty_insert(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    assert insert_rows(conn, []) == 0
    conn.close()


def test_bus_and_subway_rows_coexist(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    insert_rows(conn, [SAMPLE_BUS_ROW, SAMPLE_SUBWAY_ROW])
    assert row_count(conn) == 2
    modes = {row[0] for row in conn.execute("SELECT mode FROM delays")}
    assert modes == {"bus", "subway"}
    conn.close()


def test_migration_adds_mode_column_to_old_database(tmp_path):
    """Simulate a database created before the 'mode' column existed."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE delays (
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
        """
    )
    conn.execute(
        "INSERT INTO delays (date, route, route_name, time, day, location, code, "
        "min_delay, min_gap, bound, vehicle) VALUES "
        "('2025-01-01', '116', 'Morningside', '08:15', 'Wednesday', 'STOP', 'MFESA', 20, 40, 'N', '3442')"
    )
    conn.commit()
    conn.close()

    # Re-opening via get_connection() should migrate it in place, defaulting
    # pre-existing rows to mode='bus'.
    migrated = get_connection(db_path)
    modes = [row[0] for row in migrated.execute("SELECT mode FROM delays")]
    assert modes == ["bus"]
    migrated.close()
