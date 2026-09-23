"""
Tests for db.py using a throwaway in-memory-like SQLite file.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import get_connection, insert_rows, row_count  # noqa: E402

SAMPLE_ROW = {
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


def test_insert_and_count(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    inserted = insert_rows(conn, [SAMPLE_ROW])
    assert inserted == 1
    assert row_count(conn) == 1
    conn.close()


def test_duplicate_rows_are_skipped(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    insert_rows(conn, [SAMPLE_ROW])
    inserted_again = insert_rows(conn, [SAMPLE_ROW])
    assert inserted_again == 0
    assert row_count(conn) == 1
    conn.close()


def test_empty_insert(tmp_path):
    db_path = tmp_path / "test.db"
    conn = get_connection(db_path)
    assert insert_rows(conn, []) == 0
    conn.close()
