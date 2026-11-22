"""
Download every raw input the model needs, straight from the publishers.

  * TTC delay logs for all three modes (bus, streetcar, subway), every
    year the City publishes (2014 onward), from Toronto Open Data (CKAN).
  * Hourly and daily weather observations from Environment and Climate
    Change Canada (ECCC) for two Toronto stations.

Nothing is cleaned here -- files land in data/raw/ exactly as published,
plus a manifest.json recording what was fetched and when. Cleaning lives
in a separate step so a parsing bug never costs a re-download.

Run:
    python -m pipeline.download_raw            # everything
    python -m pipeline.download_raw --only ttc
    python -m pipeline.download_raw --only weather
    python -m pipeline.download_raw --only gtfs
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import requests

CKAN_BASE_URL = "https://ckan0.cf.opendata.inter.prod-toronto.ca"
TTC_PACKAGES = {
    "bus": "ttc-bus-delay-data",
    "streetcar": "ttc-streetcar-delay-data",
    "subway": "ttc-subway-delay-data",
}
# The City publishes each recent resource in four formats; one is enough.
WANTED_FORMATS = {"XLSX", "CSV"}

# The TTC's published timetable (GTFS): every scheduled trip and stop time.
GTFS_PACKAGE = "ttc-routes-and-schedules"

ECCC_BULK_URL = "https://climate.weather.gc.ca/climate_data/bulk_data_e.html"
# ECCC station IDs (not the same thing as climate IDs).
#   51459 = TORONTO INTL A (Pearson) -- most complete hourly record
#   31688 = TORONTO CITY (downtown)  -- closer to the core of the network
WEATHER_STATIONS = {"pearson": 51459, "toronto_city": 31688}
FIRST_YEAR = 2014

RAW_DIR = Path("data/raw")
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "ttc-delay-tracker (student project; github.com/moarznainglinkhant-cloud)"


def get(url: str, *, params: dict | None = None, tries: int = 4) -> requests.Response:
    """GET with simple exponential backoff; raises after the last try."""
    for attempt in range(1, tries + 1):
        try:
            resp = SESSION.get(url, params=params, timeout=120)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            if attempt == tries:
                raise
            wait = 2**attempt
            print(f"    retry {attempt}/{tries - 1} in {wait}s: {exc}", file=sys.stderr)
            time.sleep(wait)
    raise AssertionError("unreachable")


def safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name.strip()).strip("_")


def download_ttc(manifest: list[dict]) -> None:
    for mode, package_id in TTC_PACKAGES.items():
        print(f"[ttc] {mode}: listing resources in {package_id}")
        pkg = get(f"{CKAN_BASE_URL}/api/3/action/package_show", params={"id": package_id}).json()["result"]
        out_dir = RAW_DIR / "ttc" / mode
        out_dir.mkdir(parents=True, exist_ok=True)

        for res in pkg["resources"]:
            fmt = (res.get("format") or "").upper()
            name = (res.get("name") or "").strip()
            if fmt not in WANTED_FORMATS:
                continue
            # "since 2025" data and code lists are published as both a
            # datastore dump (labelled XLSX) and a plain CSV: keep the CSV.
            if res.get("datastore_active"):
                continue

            ext = "csv" if fmt == "CSV" else "xlsx"
            base = safe_name(name)
            if base.lower().endswith(f".{ext}"):
                base = base[: -len(ext) - 1]
            # Two streetcar resources are both named "...-2020"; the
            # resource id keeps them from overwriting each other.
            dest = out_dir / f"{base}__{res['id'][:8]}.{ext}"

            content = get(res["url"]).content
            dest.write_bytes(content)
            print(f"    {dest.name}  {len(content) / 1e6:.2f} MB")
            manifest.append(
                {
                    "source": "toronto-open-data",
                    "mode": mode,
                    "package": package_id,
                    "resource_id": res["id"],
                    "resource_name": name,
                    "last_modified": res.get("last_modified"),
                    "file": str(dest),
                    "bytes": len(content),
                }
            )
            time.sleep(0.3)  # be polite


def download_gtfs(manifest: list[dict]) -> None:
    """Fetch the current TTC schedule. Only the current timetable is
    published (no history), so it describes service levels as of the
    download date."""
    print(f"[gtfs] listing resources in {GTFS_PACKAGE}")
    pkg = get(f"{CKAN_BASE_URL}/api/3/action/package_show", params={"id": GTFS_PACKAGE}).json()["result"]
    out_dir = RAW_DIR / "gtfs"
    out_dir.mkdir(parents=True, exist_ok=True)
    for res in pkg["resources"]:
        if (res.get("format") or "").upper() != "ZIP":
            continue
        content = get(res["url"]).content
        dest = out_dir / "ttc_gtfs.zip"
        dest.write_bytes(content)
        print(f"    {dest.name}  {len(content) / 1e6:.1f} MB (published {res.get('last_modified')})")
        manifest.append(
            {
                "source": "toronto-open-data",
                "package": GTFS_PACKAGE,
                "resource_id": res["id"],
                "last_modified": res.get("last_modified"),
                "file": str(dest),
                "bytes": len(content),
            }
        )
        break


def download_weather(manifest: list[dict]) -> None:
    today = dt.date.today()
    for label, station_id in WEATHER_STATIONS.items():
        out_dir = RAW_DIR / "weather" / label
        out_dir.mkdir(parents=True, exist_ok=True)

        # Daily: one request returns a whole year.
        for year in range(FIRST_YEAR, today.year + 1):
            _weather_file(manifest, label, station_id, out_dir / f"daily_{year}.csv", year, 1, timeframe=2)

        # Hourly: one request returns one month.
        for year in range(FIRST_YEAR, today.year + 1):
            for month in range(1, 13):
                if (year, month) > (today.year, today.month):
                    break
                _weather_file(
                    manifest, label, station_id, out_dir / f"hourly_{year}_{month:02d}.csv", year, month, timeframe=1
                )


def _weather_file(manifest, label, station_id, dest: Path, year: int, month: int, *, timeframe: int) -> None:
    params = {
        "format": "csv",
        "stationID": station_id,
        "Year": year,
        "Month": month,
        "Day": 1,
        "timeframe": timeframe,  # 1 = hourly, 2 = daily
        "submit": "Download Data",
    }
    content = get(ECCC_BULK_URL, params=params).content
    dest.write_bytes(content)
    lines = content.count(b"\n")
    print(f"[weather] {label}/{dest.name}  {lines} lines")
    manifest.append(
        {
            "source": "eccc",
            "station": label,
            "station_id": station_id,
            "timeframe": "hourly" if timeframe == 1 else "daily",
            "year": year,
            "month": month if timeframe == 1 else None,
            "file": str(dest),
            "bytes": len(content),
            "lines": lines,
        }
    )
    time.sleep(0.25)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=["ttc", "weather", "gtfs"], help="download just one source")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = []
    if args.only in (None, "ttc"):
        download_ttc(manifest)
    if args.only in (None, "weather"):
        download_weather(manifest)
    if args.only in (None, "gtfs"):
        download_gtfs(manifest)

    manifest_name = "manifest.json" if args.only is None else f"manifest_{args.only}.json"
    (RAW_DIR / manifest_name).write_text(
        json.dumps({"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "files": manifest}, indent=2)
    )
    total_mb = sum(f["bytes"] for f in manifest) / 1e6
    print(f"Done: {len(manifest)} files, {total_mb:.1f} MB -> {RAW_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
