"""Tests for the cross-year harmonization rules (pipeline/harmonize.py)."""
import pytest

from pipeline import harmonize as hz

CODES = {
    "MFDV": "ON DIVERSION",
    "TFCNO": "NO OPERATOR AVAILABLE",
    "EFO": "OTHER",
    "SUDP": "DISORDERLY PATRON",
    "MUPAA": "PAA - NO TROUBLE FOUND",
    "MUIS": "INJURED/ILL CUSTOMER IN STATION - TRANSPORTED",
    "MFWEA": "WEATHER RELATED",
    "MUPR1": "PRIORITY ONE - TRAIN IN CONTACT WITH PERSON",
}


@pytest.mark.parametrize(
    "raw, expected",
    [
        # pre-2025 plain-English labels
        ("Mechanical", "mechanical"),
        ("Late Leaving Garage", "operator"),
        ("Utilized Off Route", "diversion"),
        ("Collision - TTC Involved", "collision"),
        ("  general delay ", "general"),
        # 2025+ codes, resolved through the official descriptions
        ("MFDV", "diversion"),
        ("TFCNO", "operator"),
        ("SUDP", "security"),
        ("MUPAA", "passenger"),
        ("MUIS", "medical"),
        ("MFWEA", "weather"),
        ("MUPR1", "collision"),  # code with a trailing digit
        # equipment code whose description is just "OTHER"
        ("EFO", "mechanical"),
    ],
)
def test_cause_group_known(raw, expected):
    assert hz.cause_group(raw, CODES) == expected


def test_cause_group_falls_back_to_code_prefix():
    # Undocumented codes use the TTC's first-letter convention.
    assert hz.cause_group("EZZZ", CODES) == "mechanical"
    assert hz.cause_group("SZZZ", CODES) == "security"
    assert hz.cause_group("PZZZ", CODES) == "infrastructure"
    assert hz.cause_group("TZZZ", CODES) == "operator"


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_cause_group_blank_is_other(raw):
    assert hz.cause_group(raw, CODES) == "other"


def test_every_group_is_in_the_vocabulary():
    for label in hz.INCIDENT_TO_GROUP.values():
        assert label in hz.CAUSE_GROUPS


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("YU", "YU"),
        ("YUS", "YU"),
        ("BD", "BD"),
        ("B/D", "BD"),
        ("bd line", "BD"),
        ("SHP", "SHP"),
        ("SHEP", "SHP"),
        ("SRT", "SRT"),
        ("YU/BD", "MULTI"),
        ("YU / BD", "MULTI"),
        ("95 YORK MILLS", None),  # a bus route typed into the subway log
        ("", None),
        (None, None),
    ],
)
def test_normalize_subway_line(raw, expected):
    assert hz.normalize_subway_line(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("116", "116"),
        ("116 MORNINGSIDE", "116"),
        ("  7 BATHURST", "7"),
        ("939A", "939"),
        ("501 QUEEN", "501"),
        ("8441", None),  # vehicle number in the route field
        ("RAD 506", None),
        ("TRAINING", None),
        ("0", None),
        (None, None),
    ],
)
def test_normalize_surface_route(raw, expected):
    assert hz.normalize_surface_route(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("N", "N"), ("n", "N"), ("NB", "N"), ("N/B", "N"), ("s/b", "S"),
        ("E/B", "E"), ("WB", "W"), ("B/W", "B"), ("BW", "B"), ("b", "B"),
        ("8", None), ("Q", None), ("", None), (None, None),
    ],
)
def test_normalize_direction(raw, expected):
    assert hz.normalize_direction(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("07:41", (7, 41)),
        ("07:41:00", (7, 41)),
        ("23:59", (23, 59)),
        ("7:05", (7, 5)),
        ("24:00", (None, None)),
        ("12:75", (None, None)),
        ("noon", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_hour_minute(raw, expected):
    assert hz.parse_hour_minute(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("12", 12.0), ("12.0", 12.0), (" 5 ", 5.0), ("", None), ("nan", None), (None, None), ("-3", None), ("abc", None)],
)
def test_to_minutes(raw, expected):
    assert hz.to_minutes(raw) == expected
