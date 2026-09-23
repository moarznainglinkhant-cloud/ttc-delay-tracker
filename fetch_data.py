"""
Pull TTC bus AND subway delay records from the City of Toronto Open Data
CKAN API, clean them, and load them into a local SQLite database.

Run:
    python fetch_data.py

This hits a public, terms-of-service-friendly open data API (no
scraping, no rate-limit concerns) — see config.py for the dataset
details. Re-running is safe: duplicate records are skipped.
"""
from __future__ import annotations

import sys
import time

import requests

from config import BUS_DELAY_RESOURCE_ID, CKAN_BASE_URL, DB_PATH, SUBWAY_DELAY_RESOURCE_ID
from clean import normalize_records, normalize_subway_records
from db import get_connection, insert_rows, row_count

PAGE_SIZE = 1000
DATASTORE_SEARCH_URL = f"{CKAN_BASE_URL}/api/3/action/datastore_search"


def fetch_all_records(resource_id: str, page_size: int = PAGE_SIZE):
    """Yield raw records from a CKAN datastore resource, paginating."""
    offset = 0
    while True:
        resp = requests.get(
            DATASTORE_SEARCH_URL,
            params={"id": resource_id, "limit": page_size, "offset": offset},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("success"):
            raise RuntimeError(f"CKAN API returned an error: {payload}")

        records = payload["result"]["records"]
        if not records:
            break

        yield from records

        offset += page_size
        if len(records) < page_size:
            break
        time.sleep(0.2)  # be a polite API citizen


def fetch_and_store(resource_id: str, label: str, normalize_fn) -> int:
    print(f"Fetching {label} from {CKAN_BASE_URL} ...")
    raw_records = list(fetch_all_records(resource_id))
    print(f"  Fetched {len(raw_records)} raw records.")
    cleaned = normalize_fn(raw_records)
    print(f"  Kept {len(cleaned)} records of interest.")
    return cleaned


def main() -> int:
    try:
        bus_rows = fetch_and_store(BUS_DELAY_RESOURCE_ID, "TTC bus delay data", normalize_records)
        subway_rows = fetch_and_store(
            SUBWAY_DELAY_RESOURCE_ID, "TTC subway delay data (Line 2 / BD)", normalize_subway_records
        )
    except requests.RequestException as exc:
        print(f"Network error while fetching data: {exc}", file=sys.stderr)
        print(
            "If you're behind a restrictive network/proxy, this dataset is "
            "normally reachable from a regular home connection or a "
            "GitHub Actions runner.",
            file=sys.stderr,
        )
        return 1

    conn = get_connection(DB_PATH)
    inserted = insert_rows(conn, bus_rows) + insert_rows(conn, subway_rows)
    print(f"Inserted {inserted} new rows total (skipped duplicates).")
    print(f"Database now has {row_count(conn)} total rows at {DB_PATH}.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
