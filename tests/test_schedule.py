"""Tests for the timetable (GTFS) aggregation in pipeline/schedule.py."""
import pandas as pd
import pytest

from pipeline import schedule as sc


@pytest.fixture
def feed():
    routes = pd.DataFrame(
        {
            "route_id": ["r29", "r1", "r501", "ferry"],
            "route_short_name": ["29", "1", "501", "F"],
            "route_long_name": ["Dufferin", "Line 1", "Queen", "Island Ferry"],
            "route_type": ["3", "1", "0", "4"],  # 4 = ferry, not a TTC mode we track
        }
    )
    calendar = pd.DataFrame(
        {
            "service_id": ["wk", "sat", "sun", "special"],
            "monday": ["1", "0", "0", "0"], "friday": ["1", "0", "0", "0"],
            "saturday": ["0", "1", "0", "0"], "sunday": ["0", "0", "1", "0"],
        }
    )
    # Route 29 on weekdays, 8am hour: 4 trips each way = a 15-minute headway.
    trips = pd.DataFrame(
        {
            "route_id": ["r29"] * 8 + ["r29", "r1", "ferry", "r29"],
            "service_id": ["wk"] * 8 + ["sat", "wk", "wk", "special"],
            "trip_id": [f"t{i}" for i in range(12)],
            "direction_id": ["0", "0", "0", "0", "1", "1", "1", "1", "0", "0", "0", "0"],
        }
    )
    starts = pd.DataFrame(
        {
            "trip_id": [f"t{i}" for i in range(12)],
            "start_time": ["08:00:00", "08:15:00", "08:30:00", "08:45:00"] * 2 + ["25:10:00", "08:05:00", "08:00:00", "08:00:00"],
        }
    )
    return routes, trips, calendar, starts


def test_headway_is_minutes_between_vehicles_in_one_direction(feed):
    out = sc.service_by_route_hour(*feed)
    row = out[(out["route"] == "29") & (out["day_type"] == "weekday") & (out["hour"] == 8)].iloc[0]
    assert row["trips"] == 8
    assert row["headway_min"] == 15.0
    assert row["mode"] == "bus"


def test_after_midnight_times_wrap_to_clock_hours(feed):
    out = sc.service_by_route_hour(*feed)
    late = out[(out["route"] == "29") & (out["day_type"] == "saturday")].iloc[0]
    assert late["hour"] == 1  # 25:10 is 1:10am


def test_subway_lines_use_the_delay_log_codes_and_other_modes_are_dropped(feed):
    out = sc.service_by_route_hour(*feed)
    assert set(out["mode"]) == {"bus", "subway"}
    assert out.loc[out["mode"] == "subway", "route"].tolist() == ["YU"]


def test_special_event_services_are_excluded(feed):
    out = sc.service_by_route_hour(*feed)
    # The "special" trip must not inflate the weekday 8am count.
    assert out[(out["route"] == "29") & (out["day_type"] == "weekday")]["trips"].sum() == 8


def test_annual_trips_weights_day_types(feed):
    annual = sc.annual_trips(sc.service_by_route_hour(*feed)).set_index("route")["trips_per_year"]
    assert annual["29"] == 8 * sc.DAYS_PER_YEAR["weekday"] + 1 * sc.DAYS_PER_YEAR["saturday"]


def test_days_per_year_adds_up():
    assert sum(sc.DAYS_PER_YEAR.values()) == 365
