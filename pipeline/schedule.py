"""
Scheduled service from the TTC's published timetable (GTFS).

The delay logs only record incidents, so on their own they can't say
whether a route has many delays because it is unreliable or simply
because it runs a lot of buses. The timetable supplies the missing
denominator: how many trips each route is scheduled to run, by hour and
type of day, and so how far apart vehicles are meant to be (headway).

Only the *current* timetable is published (no history), so service
levels here describe the schedule in force at download time and are
applied to recent delays only where a rate is computed.

Run:
    python -m pipeline.schedule        # -> data/processed/schedule.parquet
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import pandas as pd

# GTFS route_type -> the mode names used in the delay data.
ROUTE_TYPE_TO_MODE = {"3": "bus", "0": "streetcar", "1": "subway"}
# GTFS numbers the subway lines; the delay logs use letter codes.
SUBWAY_LINE_CODES = {"1": "YU", "2": "BD", "4": "SHP"}
DAY_TYPES = ("weekday", "saturday", "sunday")
# Service days per year used to turn a daily timetable into annual trips
# (Ontario has roughly 11 holidays that run a Sunday schedule).
DAYS_PER_YEAR = {"weekday": 250, "saturday": 52, "sunday": 63}


def day_type_of_service(calendar: pd.DataFrame) -> dict[str, str]:
    """Map each regular service_id to weekday / saturday / sunday.

    Services that run on no regular day (holiday and special-event
    patterns, activated only through calendar_dates) are left out.
    """
    mapping = {}
    for row in calendar.itertuples(index=False):
        if row.monday == "1" and row.friday == "1":
            mapping[row.service_id] = "weekday"
        elif row.saturday == "1":
            mapping[row.service_id] = "saturday"
        elif row.sunday == "1":
            mapping[row.service_id] = "sunday"
    return mapping


def parse_hour(gtfs_time: pd.Series) -> pd.Series:
    """'07:41:00' -> 7. GTFS runs past midnight as 24:xx, 25:xx; those
    wrap to 0, 1 so they line up with the clock hours in the delay logs."""
    return gtfs_time.str.split(":", n=1).str[0].astype(int) % 24


def normalize_route(short_name: str, mode: str) -> str:
    if mode == "subway":
        return SUBWAY_LINE_CODES.get(short_name, short_name)
    return short_name.lstrip("0") or short_name


def service_by_route_hour(routes: pd.DataFrame, trips: pd.DataFrame, calendar: pd.DataFrame, trip_starts: pd.DataFrame) -> pd.DataFrame:
    """One row per (mode, route, day_type, hour): trips scheduled to
    start in that hour and the implied headway in minutes."""
    routes = routes.assign(mode=routes["route_type"].map(ROUTE_TYPE_TO_MODE)).dropna(subset=["mode"])
    routes["route"] = [normalize_route(n, m) for n, m in zip(routes["route_short_name"], routes["mode"])]

    trips = trips.assign(day_type=trips["service_id"].map(day_type_of_service(calendar))).dropna(subset=["day_type"])
    trips = trips.merge(routes[["route_id", "mode", "route", "route_long_name"]], on="route_id")
    trips = trips.merge(trip_starts, on="trip_id")
    trips["hour"] = parse_hour(trips["start_time"])

    grouped = trips.groupby(["mode", "route", "route_long_name", "day_type", "hour"])
    out = grouped.agg(trips=("trip_id", "size"), directions=("direction_id", "nunique")).reset_index()
    # Headway a rider experiences: minutes between vehicles in one direction.
    out["headway_min"] = (60 * out["directions"] / out["trips"]).round(1)
    return out.rename(columns={"route_long_name": "route_name"}).drop(columns=["directions"])


def annual_trips(schedule: pd.DataFrame) -> pd.DataFrame:
    """Scheduled trips per year for each route."""
    daily = schedule.groupby(["mode", "route", "route_name", "day_type"])["trips"].sum().reset_index()
    daily["annual"] = daily["trips"] * daily["day_type"].map(DAYS_PER_YEAR)
    return daily.groupby(["mode", "route", "route_name"])["annual"].sum().rename("trips_per_year").reset_index()


def read_gtfs(zip_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with zipfile.ZipFile(zip_path) as z:
        routes = pd.read_csv(z.open("routes.txt"), dtype=str)
        trips = pd.read_csv(z.open("trips.txt"), dtype=str, usecols=["route_id", "service_id", "trip_id", "direction_id"])
        calendar = pd.read_csv(z.open("calendar.txt"), dtype=str)
        # stop_times is ~160 MB; only each trip's first departure is needed.
        stop_times = pd.read_csv(
            z.open("stop_times.txt"), usecols=["trip_id", "departure_time", "stop_sequence"],
            dtype={"trip_id": str, "departure_time": str, "stop_sequence": "int32"},
        )
    first = stop_times.loc[stop_times.groupby("trip_id")["stop_sequence"].idxmin(), ["trip_id", "departure_time"]]
    return routes, trips, calendar, first.rename(columns={"departure_time": "start_time"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gtfs", type=Path, default=Path("data/raw/gtfs/ttc_gtfs.zip"))
    parser.add_argument("--out", type=Path, default=Path("data/processed"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    schedule = service_by_route_hour(*read_gtfs(args.gtfs))
    schedule.to_parquet(args.out / "schedule.parquet", index=False)
    per_mode = schedule[schedule["day_type"] == "weekday"].groupby("mode").agg(routes=("route", "nunique"), weekday_trips=("trips", "sum"))
    print(per_mode.to_string())
    print(f"{len(schedule):,} route-hour rows -> {args.out / 'schedule.parquet'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
