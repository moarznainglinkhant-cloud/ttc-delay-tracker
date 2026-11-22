"""
Feature tables for the two models.

Every feature here is something that would be known *before* the thing
being predicted:

  * the daily forecast only sees delays from earlier days (lags are
    shifted by at least one day) plus that day's calendar and weather;
  * the long-delay model only sees what dispatch knows the moment an
    incident is logged (route, place, time, cause, weather that hour).
    `min_gap` is deliberately excluded: it is recorded alongside
    `min_delay` and is nearly the same number, so using it would be
    reading the answer off the page.
"""
from __future__ import annotations

import holidays
import numpy as np
import pandas as pd

# One time-based split for everything, so no model is ever scored on
# days it trained on. The test year contains a full winter.
TRAIN_END = pd.Timestamp("2024-09-30")
VALID_END = pd.Timestamp("2025-09-30")

WEATHER_DAILY_FEATURES = [
    "temp_max_c", "temp_min_c", "temp_mean_c", "rain_mm", "snow_cm", "precip_mm",
    "snow_on_ground_cm", "max_gust_kmh", "snow_hours", "rain_hours", "freezing_hours",
    "fog_hours", "min_visibility_km", "max_wind_kmh", "snow_cm_prev", "snow_cm_3d", "rain_mm_3d",
]
WEATHER_HOURLY_FEATURES = [
    "temp_c", "wind_kmh", "visibility_km", "humidity_pct", "precip_mm",
    "is_snow", "is_rain", "is_freezing", "is_fog", "snow_cm", "snow_on_ground_cm",
]
CALENDAR_FEATURES = ["dow", "month", "day_of_year", "holiday"]
# A delay counts as "long" at the point riders would notice a gap.
LONG_DELAY_MIN = {"bus": 20, "streetcar": 20, "subway": 5}


def split_masks(dates: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(train, validation, test) boolean masks for a date column."""
    return dates <= TRAIN_END, (dates > TRAIN_END) & (dates <= VALID_END), dates > VALID_END


def add_calendar(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    dates = df[date_col]
    years = range(int(dates.dt.year.min()), int(dates.dt.year.max()) + 1)
    ontario = pd.to_datetime(list(holidays.Canada(subdiv="ON", years=years).keys()))
    return df.assign(
        dow=dates.dt.dayofweek.astype("int8"),
        month=dates.dt.month.astype("int8"),
        day_of_year=dates.dt.dayofyear.astype("int16"),
        holiday=dates.isin(ontario).astype("int8"),
    )


def daily_weather_features(weather_daily: pd.DataFrame, weather_hourly: pd.DataFrame) -> pd.DataFrame:
    """One row per day: the day's totals plus counts of bad-weather hours."""
    hourly = weather_hourly.assign(date=weather_hourly["timestamp"].dt.normalize())
    per_day = hourly.groupby("date").agg(
        snow_hours=("is_snow", "sum"),
        rain_hours=("is_rain", "sum"),
        freezing_hours=("is_freezing", "sum"),
        fog_hours=("is_fog", "sum"),
        min_visibility_km=("visibility_km", "min"),
        max_wind_kmh=("wind_kmh", "max"),
    )
    out = weather_daily.merge(per_day, on="date", how="left").sort_values("date").reset_index(drop=True)
    # Snow keeps disrupting service after it stops falling.
    out["snow_cm_prev"] = out["snow_cm"].shift(1)
    out["snow_cm_3d"] = out["snow_cm"].rolling(3, min_periods=1).sum()
    out["rain_mm_3d"] = out["rain_mm"].rolling(3, min_periods=1).sum()
    return out


def daily_panel(delays: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    """One row per (mode, day): delay count, its history, calendar, weather."""
    counts = delays.groupby(["mode", "date"]).size().rename("n_delays").reset_index()
    # Days with no logged delay must exist as zeros, not be missing.
    full = pd.MultiIndex.from_product(
        [sorted(counts["mode"].unique()), pd.date_range(counts["date"].min(), counts["date"].max())],
        names=["mode", "date"],
    )
    panel = counts.set_index(["mode", "date"]).reindex(full, fill_value=0).reset_index()
    panel = panel.sort_values(["mode", "date"]).reset_index(drop=True)

    by_mode = panel.groupby("mode")["n_delays"]
    for lag in (1, 7, 14):
        panel[f"lag_{lag}"] = by_mode.shift(lag)
    for window in (7, 28):
        panel[f"mean_{window}d"] = by_mode.transform(lambda s, w=window: s.shift(1).rolling(w).mean())
    panel["same_weekday_mean"] = panel[["lag_7", "lag_14"]].mean(axis=1)

    panel = add_calendar(panel).merge(weather, on="date", how="left")
    panel["mode_cat"] = panel["mode"].astype("category")
    return panel.dropna(subset=["mean_28d"]).reset_index(drop=True)


DAILY_LAG_FEATURES = ["lag_1", "lag_7", "lag_14", "mean_7d", "mean_28d", "same_weekday_mean"]


def incident_table(delays: pd.DataFrame, weather_hourly: pd.DataFrame, weather_daily: pd.DataFrame) -> pd.DataFrame:
    """One row per delay with what was knowable when it was logged."""
    df = delays.assign(hour_ts=delays["timestamp"].dt.floor("h"))
    df = df.merge(weather_hourly.rename(columns={"timestamp": "hour_ts"}), on="hour_ts", how="left")
    df = df.merge(weather_daily[["date", "snow_cm", "snow_on_ground_cm"]], on="date", how="left")
    df = add_calendar(df)
    for flag in ("is_snow", "is_rain", "is_freezing", "is_fog", "is_thunder"):
        df[flag] = df[flag].astype("float32")

    df["long_delay"] = (df["min_delay"] >= df["mode"].map(LONG_DELAY_MIN)).astype("int8")
    df["days_since_2014"] = (df["date"] - pd.Timestamp("2014-01-01")).dt.days

    # Keep well-known stops as their own category; pool the long tail.
    # Decided on training rows only, so the test year can't leak in.
    train_locations = df.loc[df["date"] <= TRAIN_END, "location"].value_counts()
    common = set(train_locations[train_locations >= 1000].index)
    df["location_cat"] = df["location"].where(df["location"].isin(common), "OTHER").fillna("UNKNOWN")

    df["route_cat"] = df["mode"] + ":" + df["route"].astype(str)
    df["direction_cat"] = df["direction"].fillna("UNKNOWN")
    for col in ("mode", "cause", "route_cat", "location_cat", "direction_cat"):
        df[col if col.endswith("_cat") else f"{col}_cat"] = df[col].astype("category")
    return df


INCIDENT_BASE_FEATURES = [
    "mode_cat", "route_cat", "location_cat", "direction_cat", "hour", "dow", "month", "days_since_2014",
]


def poisson_deviance(actual: np.ndarray, predicted: np.ndarray) -> float:
    predicted = np.clip(predicted, 1e-9, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.where(actual > 0, actual * np.log(actual / predicted), 0.0)
    return float(2 * np.mean(term - (actual - predicted)))
