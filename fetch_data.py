"""
Pull TTC bus delay records from the City of Toronto Open Data CKAN API,
clean them, and load them into a local SQLite database.

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

from config import BUS_DELAY_RESOURCE_ID, CKAN_BASE_URL, DB_PATH
from clean import normalize_records
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


def main() -> int:
    print(f"Fetching TTC bus delay data from {CKAN_BASE_URL} ...")
    try:
        raw_records = list(fetch_all_records(BUS_DELAY_RESOURCE_ID))
    except requests.RequestException as exc:
        print(f"Network error while fetching data: {exc}", file=sys.stderr)
        print(
            "If you're behind a restrictive network/proxy, this dataset is "
            "normally reachable from a regular home connection or a "
            "GitHub Actions runner.",
            file=sys.stderr,
        )
        return 1

    print(f"Fetched {len(raw_records)} raw records.")
    cleaned = normalize_records(raw_records)
    print(f"Kept {len(cleaned)} records matching routes of interest.")

    conn = get_connection(DB_PATH)
    inserted = insert_rows(conn, cleaned)
    print(f"Inserted {inserted} new rows (skipped duplicates).")
    print(f"Database now has {row_count(conn)} total rows at {DB_PATH}.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
