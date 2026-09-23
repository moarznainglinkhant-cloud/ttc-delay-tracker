"""
Pure data-cleaning functions for TTC delay records (bus + subway).

Kept separate from fetch_data.py / db.py so they can be unit tested
without any network access or database — this is the module tests/
exercises.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from config import ROUTES_OF_INTEREST, SUBWAY_LINE_OF_INTEREST, SUBWAY_LINES


def extract_route_number(line_field: Optional[str]) -> Optional[str]:
    """Pull the leading route number out of a raw bus "Line" field.

    >>> extract_route_number("116 MORNINGSIDE")
    '116'
    >>> extract_route_number("995 MARKHAM RD EXPRESS")
    '995'
    >>> extract_route_number(None) is None
    True
    """
    if not line_field:
        return None
    parts = str(line_field).strip().split(" ", 1)
    token = parts[0].strip()
    return token if token else None


def is_route_of_interest(line_field: Optional[str]) -> bool:
    """True if this bus record's route is one we track for the UTSC commute."""
    route = extract_route_number(line_field)
    return route is not None and route in ROUTES_OF_INTEREST


def is_subway_line_of_interest(line_field: Optional[str], target: str = SUBWAY_LINE_OF_INTEREST) -> bool:
    """True if this subway record is on the line we care about (default: BD,
    the Kennedy -> St. George leg of the UTSC -> UTSG commute)."""
    if not line_field:
        return False
    return str(line_field).strip().upper() == target.upper()


def to_int_or_none(value: Any) -> Optional[int]:
    """CKAN returns numeric-looking fields as strings, and sometimes blank."""
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() == "null":
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _parse_date(date_raw: Any) -> Optional[str]:
    if not date_raw:
        return None
    try:
        # CKAN timestamps look like "2025-01-01T00:00:00" or "2025-01-01"
        return datetime.fromisoformat(str(date_raw)).date().isoformat()
    except ValueError:
        return None


def normalize_record(raw: dict) -> Optional[dict]:
    """Turn one raw CKAN bus-delay record into a clean, typed row.

    Returns None for records missing a date or not on a tracked route.
    """
    line = raw.get("Line")
    if not is_route_of_interest(line):
        return None

    date = _parse_date(raw.get("Date"))
    if date is None:
        return None

    min_delay = to_int_or_none(raw.get("Min Delay"))
    min_gap = to_int_or_none(raw.get("Min Gap"))
    bound = raw.get("Bound")
    bound = str(bound).strip() if bound not in (None, "", "null") else None
    route = extract_route_number(line)

    return {
        "mode": "bus",
        "date": date,
        "route": route,
        "route_name": ROUTES_OF_INTEREST.get(route, ""),
        "time": (raw.get("Time") or "").strip() or None,
        "day": (raw.get("Day") or "").strip() or None,
        "location": (raw.get("Station") or "").strip() or None,
        "code": (raw.get("Code") or "").strip() or None,
        "min_delay": min_delay if min_delay is not None else 0,
        "min_gap": min_gap if min_gap is not None else 0,
        "bound": bound,
        "vehicle": (raw.get("Vehicle") or "").strip() or None,
    }


def normalize_records(raw_records: list[dict]) -> list[dict]:
    """Filter + clean a batch of raw bus records in one pass."""
    cleaned = []
    for raw in raw_records:
        row = normalize_record(raw)
        if row is not None:
            cleaned.append(row)
    return cleaned


def normalize_subway_record(raw: dict, target_line: str = SUBWAY_LINE_OF_INTEREST) -> Optional[dict]:
    """Turn one raw CKAN subway-delay record into a clean, typed row.

    Returns None for records missing a date or not on the target line.
    """
    line = raw.get("Line")
    if not is_subway_line_of_interest(line, target_line):
        return None

    date = _parse_date(raw.get("Date"))
    if date is None:
        return None

    min_delay = to_int_or_none(raw.get("Min Delay"))
    min_gap = to_int_or_none(raw.get("Min Gap"))
    bound = raw.get("Bound")
    bound = str(bound).strip() if bound not in (None, "", "null") else None
    line_code = str(line).strip().upper()

    return {
        "mode": "subway",
        "date": date,
        "route": line_code,
        "route_name": SUBWAY_LINES.get(line_code, line_code),
        "time": (raw.get("Time") or "").strip() or None,
        "day": (raw.get("Day") or "").strip() or None,
        "location": (raw.get("Station") or "").strip() or None,
        "code": (raw.get("Code") or "").strip() or None,
        "min_delay": min_delay if min_delay is not None else 0,
        "min_gap": min_gap if min_gap is not None else 0,
        "bound": bound,
        "vehicle": (raw.get("Vehicle") or "").strip() or None,
    }


def normalize_subway_records(raw_records: list[dict], target_line: str = SUBWAY_LINE_OF_INTEREST) -> list[dict]:
    """Filter + clean a batch of raw subway records in one pass."""
    cleaned = []
    for raw in raw_records:
        row = normalize_subway_record(raw, target_line)
        if row is not None:
            cleaned.append(row)
    return cleaned
