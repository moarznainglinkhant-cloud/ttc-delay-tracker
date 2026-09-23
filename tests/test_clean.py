"""
Unit tests for clean.py — no network, no database, pure functions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clean import (  # noqa: E402
    extract_route_number,
    is_route_of_interest,
    normalize_record,
    normalize_records,
    to_int_or_none,
)


def test_extract_route_number_basic():
    assert extract_route_number("116 MORNINGSIDE") == "116"
    assert extract_route_number("995 MARKHAM RD EXPRESS") == "995"


def test_extract_route_number_handles_missing():
    assert extract_route_number(None) is None
    assert extract_route_number("") is None


def test_is_route_of_interest():
    assert is_route_of_interest("116 MORNINGSIDE") is True
    assert is_route_of_interest("999 SOME OTHER ROUTE") is False
    assert is_route_of_interest(None) is False


def test_to_int_or_none():
    assert to_int_or_none("20") == 20
    assert to_int_or_none("") is None
    assert to_int_or_none(None) is None
    assert to_int_or_none("null") is None
    assert to_int_or_none("not a number") is None
    assert to_int_or_none(15.0) == 15


def test_normalize_record_valid():
    raw = {
        "Date": "2025-01-01T00:00:00",
        "Line": "116 MORNINGSIDE",
        "Time": "08:15",
        "Day": "Wednesday",
        "Station": "MORNINGSIDE AND KINGSTON",
        "Code": "MFESA",
        "Min Delay": "20",
        "Min Gap": "40",
        "Bound": "N",
        "Vehicle": "3442",
    }
    row = normalize_record(raw)
    assert row is not None
    assert row["date"] == "2025-01-01"
    assert row["route"] == "116"
    assert row["route_name"] == "Morningside"
    assert row["min_delay"] == 20
    assert row["min_gap"] == 40
    assert row["bound"] == "N"


def test_normalize_record_filters_uninteresting_route():
    raw = {"Date": "2025-01-01T00:00:00", "Line": "504 KING", "Min Delay": "5"}
    assert normalize_record(raw) is None


def test_normalize_record_requires_date():
    raw = {"Line": "116 MORNINGSIDE", "Min Delay": "5"}
    assert normalize_record(raw) is None


def test_normalize_record_bad_date_is_skipped():
    raw = {"Date": "not-a-date", "Line": "116 MORNINGSIDE"}
    assert normalize_record(raw) is None


def test_normalize_records_batch():
    raws = [
        {"Date": "2025-01-01T00:00:00", "Line": "116 MORNINGSIDE", "Min Delay": "10"},
        {"Date": "2025-01-01T00:00:00", "Line": "504 KING", "Min Delay": "5"},
        {"Date": "2025-01-02T00:00:00", "Line": "995 MARKHAM RD EXPRESS", "Min Delay": "3"},
    ]
    cleaned = normalize_records(raws)
    assert len(cleaned) == 2
    assert {r["route"] for r in cleaned} == {"116", "995"}
