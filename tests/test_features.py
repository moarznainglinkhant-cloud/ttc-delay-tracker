"""Tests for the leak-safety of the model features (pipeline/features.py)."""
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("holidays")

from pipeline import features as ft


def _delays(days: int = 60) -> pd.DataFrame:
    """Day i has exactly i+1 bus delays, so lags are easy to check by hand."""
    dates = pd.date_range("2024-01-01", periods=days)
    rows = [{"mode": "bus", "date": d} for i, d in enumerate(dates) for _ in range(i + 1)]
    return pd.DataFrame(rows)


def _weather(days: int = 60) -> pd.DataFrame:
    return pd.DataFrame({"date": pd.date_range("2024-01-01", periods=days), "snow_cm": 0.0})


def test_daily_panel_lags_only_use_earlier_days():
    panel = ft.daily_panel(_delays(), _weather()).set_index("date")
    day = pd.Timestamp("2024-02-15")  # index 45 -> 46 delays
    row = panel.loc[day]
    assert row["n_delays"] == 46
    assert row["lag_1"] == 45
    assert row["lag_7"] == 39
    # mean of the previous 7 days: 39..45
    assert row["mean_7d"] == pytest.approx(np.mean(range(39, 46)))
    # mean of the previous 28 days must not include the day itself
    assert row["mean_28d"] == pytest.approx(np.mean(range(18, 46)))


def test_daily_panel_fills_days_without_delays_as_zero():
    delays = _delays(40)
    delays = delays[delays["date"] != pd.Timestamp("2024-02-05")]
    panel = ft.daily_panel(delays, _weather(40)).set_index("date")
    assert panel.loc[pd.Timestamp("2024-02-05"), "n_delays"] == 0


def test_split_masks_do_not_overlap_and_are_ordered():
    dates = pd.Series(pd.date_range("2024-01-01", "2026-09-30"))
    train, valid, test = ft.split_masks(dates)
    assert not (train & valid).any() and not (valid & test).any() and not (train & test).any()
    assert (train | valid | test).all()
    assert dates[train].max() < dates[valid].min() <= dates[valid].max() < dates[test].min()


def test_calendar_marks_ontario_holidays():
    df = ft.add_calendar(pd.DataFrame({"date": pd.to_datetime(["2025-07-01", "2025-07-02", "2025-12-25"])}))
    assert df["holiday"].tolist() == [1, 0, 1]
    assert df["dow"].tolist() == [1, 2, 3]


def test_min_gap_is_never_a_model_feature():
    # min_gap is recorded with min_delay and is nearly the same number.
    assert "min_gap" not in ft.INCIDENT_BASE_FEATURES + ft.WEATHER_HOURLY_FEATURES
    assert "min_delay" not in ft.INCIDENT_BASE_FEATURES + ft.WEATHER_HOURLY_FEATURES


def test_poisson_deviance_is_zero_for_perfect_predictions():
    y = np.array([0.0, 1.0, 5.0])
    assert ft.poisson_deviance(y[1:], y[1:]) == pytest.approx(0.0)
    assert ft.poisson_deviance(y, np.array([1.0, 1.0, 1.0])) > 0
