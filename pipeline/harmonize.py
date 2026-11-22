"""
Pure functions that turn 12 years of inconsistently formatted TTC delay
records into one schema.

What changed over the years (all handled here):

  * Column names: "Report Date" -> "Date", "Route" -> "Line",
    "Direction" -> "Bound", "Location" -> "Station",
    "Delay"/"Gap" -> "Min Delay"/"Min Gap" (briefly, 2019-2020).
  * Cause of delay: bus and streetcar files used ~35 plain-English
    "Incident" labels until 2024, then switched to ~150 internal codes
    in 2025. Subway has always used codes. `cause_group` maps all of them
    onto one small shared vocabulary so years are comparable.
  * Route: sometimes "116", sometimes "116 MORNINGSIDE", sometimes a
    vehicle number or free text typed into the wrong field.
  * Direction: "N", "n", "NB", "N/B", "B/W" ... -> N / S / E / W / B.

Nothing here touches the network or the filesystem, so it is all unit
tested (tests/test_harmonize.py).
"""
from __future__ import annotations

import re
from typing import Optional

# --------------------------------------------------------------------------
# Cause of delay
# --------------------------------------------------------------------------

CAUSE_GROUPS = (
    "mechanical",
    "operator",
    "security",
    "collision",
    "diversion",
    "medical",
    "cleaning",
    "infrastructure",
    "passenger",
    "weather",
    "general",
    "other",
)

# Pre-2025 bus/streetcar "Incident" labels (lower-cased) -> group.
INCIDENT_TO_GROUP = {
    "mechanical": "mechanical",
    "vision": "mechanical",
    "overhead": "infrastructure",
    "overhead - pantograph": "infrastructure",
    "rail/switches": "infrastructure",
    "late leaving garage": "operator",
    "late leaving garage - mechanical": "mechanical",
    "late leaving garage - operator": "operator",
    "late leaving garage - management": "operator",
    "late leaving garage - operations": "operator",
    "late leaving garage - vision": "mechanical",
    "late entering service": "operator",
    "late entering service - mechanical": "mechanical",
    "late": "operator",
    "operations": "operator",
    "operations - operator": "operator",
    "management": "operator",
    "utilized off route": "diversion",
    "diversion": "diversion",
    "held by": "general",
    "general delay": "general",
    "investigation": "security",
    "security": "security",
    "emergency services": "medical",
    "collision - ttc": "collision",
    "collision - ttc involved": "collision",
    "road blocked - non-ttc collision": "collision",
    "road block - non-ttc collision": "collision",
    "cleaning": "cleaning",
    "cleaning - unsanitary": "cleaning",
    "cleaning - disinfection": "cleaning",
    "e": "other",
}

# Keyword rules applied to the official code DESCRIPTION text. Order
# matters: the first match wins.
_DESCRIPTION_RULES: tuple[tuple[str, str], ...] = (
    (r"WEATHER", "weather"),
    (r"COLLISION|ON BOARD INJURY|CONTACT WITH PERSON|STRUCK", "collision"),
    (r"DIVERSION|SHUTTLE|PARADE|MARCH", "diversion"),
    (r"UNSANITARY|CLEANING|BIOHAZARD", "cleaning"),
    (r"ILL CUSTOMER|INJURED|INJURIED|MEDICAL|ILLNESS|SUICIDE|PRIORITY ONE", "medical"),
    (r"ASSAULT|DISORDERLY|BOMB|SUSPICIOUS|POLICE|SECURITY|ROBBERY|TRESPASS|UNAUTHORIZED|WEAPON|FARE DISPUTE", "security"),
    (r"PASSENGER ASSISTANCE ALARM|\bPAA\b|EMERGENCY ALARM|PASSENGER|CUSTOMER|PATRON", "passenger"),
    (r"NO OPERATOR|OPERATOR|CREW|LATE ENTERING|LATE VEHICLE|LABOUR|WORK REFUSAL|SUPERVISORY|TRAINING|SPEED CONTROL|OVERSPEED|OVERSHOT|VIOLAT|COLLECTOR|CLERK|TIMEOUT", "operator"),
    (r"TRACK|SWITCH|SIGNAL|OVERHEAD|POWER|TRACTION|STRUCTURE|ESCALATOR|ELEVATOR|TUNNEL|FIRE|SMOKE|DEBRIS|CONSTRUCTION|WORK ZONE|WORK VEHICLE|FOUL RAIL|TRAPPED|ATC|CLOSURE", "infrastructure"),
    (r"VISION", "mechanical"),
    (r"UNABLE TO MAINT|SCHEDULE|GENERAL|MISC", "general"),
)

# High-volume codes that appear in the data but in none of the published
# reference tables; meaning inferred from the sibling codes in other modes
# (e.g. MTGD / MUGD are both documented as "miscellaneous general delay").
UNDOCUMENTED_CODES = {
    "MFGD": "MISCELLANEOUS GENERAL DELAY",
    "MFBIO": "BIOHAZARD",
    "MTBIO": "BIOHAZARD",
    "MFVIS": "VISION ISSUES",
    "MTSH": "USED AS SHUTTLE",
}

# When a code has no description (retired or undocumented), fall back to
# the TTC's own first-letter convention: E = equipment, P = plant,
# S = security, T = transportation (operations), M = miscellaneous.
_PREFIX_FALLBACK = {"E": "mechanical", "P": "infrastructure", "S": "security", "T": "operator", "M": "other"}


def cause_group_from_description(code: str, description: Optional[str]) -> str:
    """Map one TTC delay code (+ its official description) to a group."""
    code = (code or "").strip().upper()
    if description:
        text = description.upper()
        for pattern, group in _DESCRIPTION_RULES:
            if re.search(pattern, text):
                return group
    if code[:1] == "E":  # equipment faults whose description is just a part name
        return "mechanical"
    return _PREFIX_FALLBACK.get(code[:1], "other")


def cause_group(raw_cause: Optional[str], code_descriptions: dict[str, str]) -> str:
    """Harmonize either an old plain-English incident label or a code."""
    if raw_cause is None:
        return "other"
    text = str(raw_cause).strip()
    if not text:
        return "other"
    label = text.lower()
    if label in INCIDENT_TO_GROUP:
        return INCIDENT_TO_GROUP[label]
    code = text.upper()
    if re.fullmatch(r"[A-Z]{2,6}\d?", code):
        return cause_group_from_description(code, code_descriptions.get(code) or UNDOCUMENTED_CODES.get(code))
    # Unknown free text: try the description rules on the text itself.
    return cause_group_from_description("", text)


# --------------------------------------------------------------------------
# Route / line
# --------------------------------------------------------------------------

_SUBWAY_LINE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"YU|YONGE|UNIVERSITY", "YU"),
    (r"B\s*/?\s*D|BLOOR|DANFORTH", "BD"),
    (r"SHP|SHEP", "SHP"),
    (r"SRT|SCARB", "SRT"),
)


def normalize_subway_line(raw: Optional[str]) -> Optional[str]:
    """'YU', 'YUS', 'YU / BD', 'B/D' ... -> 'YU', 'BD', 'SHP', 'SRT' or
    'MULTI' (an incident logged against more than one line, typically at
    an interchange station). Anything else (e.g. a bus route typed into
    the subway log) -> None."""
    if raw is None:
        return None
    text = str(raw).strip().upper()
    if not text:
        return None
    hits = [code for pattern, code in _SUBWAY_LINE_PATTERNS if re.search(pattern, text)]
    if not hits:
        return None
    return hits[0] if len(hits) == 1 else "MULTI"


_ROUTE_NUMBER = re.compile(r"^\s*(\d{1,3})(?!\d)")


def normalize_surface_route(raw: Optional[str]) -> Optional[str]:
    """Pull the route number out of a bus/streetcar route field.

    >>> normalize_surface_route("116 MORNINGSIDE")
    '116'
    >>> normalize_surface_route("501")
    '501'
    >>> normalize_surface_route("8441") is None   # a vehicle number
    True
    >>> normalize_surface_route("RAD 506") is None
    True
    """
    if raw is None:
        return None
    match = _ROUTE_NUMBER.match(str(raw))
    if not match:
        return None
    number = int(match.group(1))
    return str(number) if number > 0 else None


# --------------------------------------------------------------------------
# Direction, time, numbers
# --------------------------------------------------------------------------


def normalize_direction(raw: Optional[str]) -> Optional[str]:
    """'N', 'n', 'NB', 'N/B', 'B/W', 'BW' ... -> 'N' | 'S' | 'E' | 'W' | 'B'."""
    if raw is None:
        return None
    text = re.sub(r"[^A-Z]", "", str(raw).upper())
    if not text:
        return None
    if text in {"BW", "B", "BOTH", "BOTHWAYS"}:
        return "B"
    if text[0] in "NSEW" and (len(text) == 1 or text[1:] in {"B", "BD", "BOUND"}):
        return text[0]
    return None


_TIME = re.compile(r"^\s*(\d{1,2}):(\d{2})")


def parse_hour_minute(raw: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """'07:41', '07:41:00' -> (7, 41). Unparseable -> (None, None)."""
    if raw is None:
        return None, None
    match = _TIME.match(str(raw))
    if not match:
        return None, None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None, None
    return hour, minute


def to_minutes(raw) -> Optional[float]:
    """Delay/gap minutes arrive as strings, blanks, or floats."""
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "" or text.lower() in {"nan", "none", "null"}:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value >= 0 else None
