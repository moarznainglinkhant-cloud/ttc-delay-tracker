"""
Configuration for the UTSC TTC Delay Tracker.

The City of Toronto Open Data portal publishes bus delay records with a
"Line" field like "116 MORNINGSIDE" (route number + route name). We match
on the route number at the start of that field.

Edit ROUTES_OF_INTEREST if your commute uses different routes.
"""

# Bus routes commonly used to get to/from UTSC (University of Toronto
# Scarborough), including local routes and express routes to Scarborough
# Centre / Kennedy / Line 3 replacement shuttles.
ROUTES_OF_INTEREST = {
    "116": "Morningside",
    "38": "Highland Creek",
    "133": "Neilson",
    "21": "Brimley",
    "57": "Midland",
    "95": "York Mills",  # connects toward campus via Ellesmere corridor
    "985": "Sheppard East Express",
    "995": "Markham Rd Express",
    "102": "Markham Road",
    "S-Line": "Line 3 Scarborough replacement shuttle",  # City sometimes labels these separately
}

# City of Toronto Open Data (CKAN) API.
CKAN_BASE_URL = "https://ckan0.cf.opendata.inter.prod-toronto.ca"

# --- Bus delay dataset ---
BUS_PACKAGE_ID = "ttc-bus-delay-data"
# Resource IDs for the datastore-active resources (these are the live,
# queryable tables — the City rotates a new "since <year>" resource in
# periodically, so check the package if this ever 404s).
BUS_DELAY_RESOURCE_ID = "c3451ac9-c04a-4645-bd80-0e2a3b7d7199"  # "TTC Bus Delay Data since 2025"
BUS_CODE_DESCRIPTIONS_RESOURCE_ID = "816f2214-97e2-4c4b-820e-24b425ed08e0"  # "Code Descriptions"

# --- Subway delay dataset ---
SUBWAY_PACKAGE_ID = "ttc-subway-delay-data"
SUBWAY_DELAY_RESOURCE_ID = "6088e14f-e46e-4f5c-9daa-dea1359ad396"  # "TTC Subway Delay Data since 2025"

# The subway "Line" field uses line codes, not route numbers: YU
# (Yonge-University, Line 1), BD (Bloor-Danforth, Line 2), SHP (Sheppard,
# Line 4). Kennedy Station -> St. George Station is a direct ride west on
# Line 2 (no transfer needed, since St. George is the interchange with
# Line 1), so that's the line we care about for the UTSC -> UTSG commute.
SUBWAY_LINE_OF_INTEREST = "BD"
SUBWAY_LINES = {
    "BD": "Line 2 Bloor–Danforth",
    "YU": "Line 1 Yonge–University",
    "SHP": "Line 4 Sheppard",
}

DB_PATH = "ttc_delays.db"

# Stations bounding the subway leg of the UTSC -> UTSG commute, for
# reference in the commute planner page.
KENNEDY_STATION = "KENNEDY STATION"
ST_GEORGE_STATION = "ST GEORGE STATION"
