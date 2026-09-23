"""
Pure data-cleaning functions for TTC delay records.

Kept separate from fetch_data.py / db.py so they can be unit tested
without any network access or database — this is the module tests/
exercises.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from config import ROUTES_OF_INTEREST


def extract_route_number(line_field: Optional[str]) -> Optional[str]:
    """Pull the leading route number out of a raw "Line" field.

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
    """True if this record's route is one we track for the UTSC commute."""
    route = extract_route_number(line_field)
    return route is not None and route in ROUTES_OF_INTEREST


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


def normalize_record(raw: dict) -> Optional[dict]:
    """Turn one raw CKAN datastore record into a clean, typed row.

    Returns None for records that are missing a date or aren't on a
    route we care about (callers typically filter before this, but this
    makes normalize_record safe to call directly too).
    """
    line = raw.get("Line")
    if not is_route_of_interest(line):
        return None

    date_raw = raw.get("Date")
    if not date_raw:
        return None
    try:
        # CKAN timestamps look like "2025-01-01T00:00:00"
        date = datetime.fromisoformat(str(date_raw)).date().isoformat()
    except ValueError:
        return None

    min_delay = to_int_or_none(raw.get("Min Delay"))
    min_gap = to_int_or_none(raw.get("Min Gap"))

    bound = raw.get("Bound")
    bound = str(bound).strip() if bound not in (None, "", "null") else None

    return {
        "date": date,
        "route": extract_route_number(line),
        "route_name": ROUTES_OF_INTEREST.get(extract_route_number(line), ""),
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
    """Filter + clean a batch of raw CKAN records in one pass."""
    cleaned = []
    for raw in raw_records:
        row = normalize_record(raw)
        if row is not None:
            cleaned.append(row)
    return cleaned
