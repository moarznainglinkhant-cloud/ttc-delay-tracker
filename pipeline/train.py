"""
Train and honestly evaluate the two models, then write small result
files to reports/ for the dashboard and README.

  1. Daily forecast: how many delays will each mode log tomorrow?
  2. Long-delay classifier: will this incident run long (20+ min on
     surface routes, 5+ min on the subway)?

Evaluation rules, applied to both:
  * Time-based split. Train to Sept 2024, tune on the next 12 months,
    report on the final 12 months (Oct 2025 - Sept 2026), untouched
    until the end. Random splits would let the model peek at the future.
  * Every score is reported next to a naive baseline, with a bootstrap
    confidence interval on the improvement.
  * Features are added in stages (ablation) so each one has to earn
    its place -- including the ones that turn out not to help.

Run:
    python -m pipeline.train
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from pipeline import features as ft

SEED = 42
N_BOOTSTRAP = 1000


def bootstrap_improvement(err_base: np.ndarray, err_model: np.ndarray, groups: np.ndarray) -> dict:
    """% reduction in mean error vs baseline, with a 95% interval.

    Resamples whole days (not rows): errors on the same day are
    correlated, and resampling rows would make the interval too narrow.
    """
    rng = np.random.default_rng(SEED)
    frame = pd.DataFrame({"g": groups, "b": err_base, "m": err_model}).groupby("g").sum()
    b, m = frame["b"].to_numpy(), frame["m"].to_numpy()
    idx = rng.integers(0, len(b), size=(N_BOOTSTRAP, len(b)))
    draws = 1 - m[idx].sum(axis=1) / b[idx].sum(axis=1)
    return {
        "improvement_pct": round(100 * (1 - m.sum() / b.sum()), 1),
        "ci95_low_pct": round(100 * float(np.percentile(draws, 2.5)), 1),
        "ci95_high_pct": round(100 * float(np.percentile(draws, 97.5)), 1),
    }


# --------------------------------------------------------------------------
# 1. Daily forecast
# --------------------------------------------------------------------------


def train_daily_forecast(panel: pd.DataFrame, reports: Path) -> dict:
    train, valid, test = ft.split_masks(panel["date"])
    y = panel["n_delays"]
    stages = {
        "calendar + recent history": ft.CALENDAR_FEATURES + ["mode_cat"] + ft.DAILY_LAG_FEATURES,
        "+ weather": ft.CALENDAR_FEATURES + ["mode_cat"] + ft.DAILY_LAG_FEATURES + ft.WEATHER_DAILY_FEATURES,
    }

    test_frame = panel.loc[test, ["mode", "date", "n_delays", "mean_28d", "snow_cm"]].rename(
        columns={"n_delays": "actual", "mean_28d": "baseline"}
    )
    results: dict = {"test_days": int(test_frame["date"].nunique()), "by_stage": {}}
    importances = None

    for stage, cols in stages.items():
        # Average a few seeds: with ~4,000 training days per mode a
        # single run moves around more than the weather effect does.
        preds = []
        for seed in range(5):
            model = lgb.LGBMRegressor(
                objective="poisson", n_estimators=2000, learning_rate=0.02, num_leaves=15,
                min_child_samples=30, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                random_state=SEED + seed, verbose=-1,
            )
            model.fit(
                panel.loc[train, cols], y[train],
                eval_set=[(panel.loc[valid, cols], y[valid])],
                callbacks=[lgb.early_stopping(100, verbose=False)],
            )
            preds.append(model.predict(panel.loc[test, cols]))
        pred = np.mean(preds, axis=0)
        test_frame[stage] = pred

        per_mode = {}
        for mode, grp in test_frame.groupby("mode"):
            err_b = (grp["actual"] - grp["baseline"]).abs().to_numpy()
            err_m = (grp["actual"] - grp[stage]).abs().to_numpy()
            per_mode[mode] = {
                "mean_daily_delays": round(float(grp["actual"].mean()), 1),
                "mae_baseline": round(float(err_b.mean()), 2),
                "mae_model": round(float(err_m.mean()), 2),
                **bootstrap_improvement(err_b, err_m, grp["date"].to_numpy()),
            }
        results["by_stage"][stage] = per_mode
        if stage == "+ weather":
            gain = pd.Series(model.booster_.feature_importance("gain"), index=cols)
            importances = (gain / gain.sum()).sort_values(ascending=False)

    test_frame = test_frame.rename(columns={"calendar + recent history": "model", "+ weather": "model_with_weather"})
    test_frame.round(2).to_csv(reports / "daily_forecast_test.csv", index=False)
    importances.round(4).rename("share_of_gain").to_csv(reports / "daily_forecast_importance.csv", index_label="feature")
    return results


def storm_effect(panel: pd.DataFrame, delays: pd.DataFrame, reports: Path) -> list[dict]:
    """How far above normal do delays run on snow days?

    "Normal" = that mode's own average over the previous 28 days, so
    the comparison is against the same season and the same era.
    """
    minutes = (
        delays.assign(m=delays["min_delay"].clip(upper=180))
        .groupby(["mode", "date"])["m"].sum().rename("delay_minutes").reset_index()
    )
    df = panel.merge(minutes, on=["mode", "date"], how="left").fillna({"delay_minutes": 0})
    df = df.sort_values(["mode", "date"])
    df["minutes_28d"] = df.groupby("mode")["delay_minutes"].transform(lambda s: s.shift(1).rolling(28).mean())
    df["count_ratio"] = df["n_delays"] / df["mean_28d"]
    df["minutes_ratio"] = df["delay_minutes"] / df["minutes_28d"]
    df["snow_band"] = pd.cut(
        df["snow_cm"].fillna(0), [-1, 0, 2, 5, 10, 1000], labels=["none", "under 2 cm", "2-5 cm", "5-10 cm", "10+ cm"]
    )

    rng = np.random.default_rng(SEED)
    rows = []
    for (band, mode), grp in df.groupby(["snow_band", "mode"], observed=True):
        ratios = grp["count_ratio"].dropna().to_numpy()
        boots = np.median(rng.choice(ratios, size=(N_BOOTSTRAP, len(ratios))), axis=1)
        rows.append(
            {
                "snow_band": band, "mode": mode, "days": int(len(grp)),
                "delays_vs_normal_pct": round(100 * (float(np.median(ratios)) - 1), 0),
                "ci95_low_pct": round(100 * (float(np.percentile(boots, 2.5)) - 1), 0),
                "ci95_high_pct": round(100 * (float(np.percentile(boots, 97.5)) - 1), 0),
                "delay_minutes_vs_normal_pct": round(100 * (float(grp["minutes_ratio"].median()) - 1), 0),
            }
        )
    pd.DataFrame(rows).to_csv(reports / "storm_effect.csv", index=False)
    return rows


# --------------------------------------------------------------------------
# 2. Long-delay classifier
# --------------------------------------------------------------------------


def train_long_delay(incidents: pd.DataFrame, reports: Path) -> dict:
    # 2018 onward: older years use different logging habits and add
    # training time without improving the validation score.
    incidents = incidents[incidents["date"] >= "2018-01-01"].reset_index(drop=True)
    train, valid, test = ft.split_masks(incidents["date"])
    y = incidents["long_delay"]

    stages = {
        "route, place, time": ft.INCIDENT_BASE_FEATURES,
        "+ cause": ft.INCIDENT_BASE_FEATURES + ["cause_cat"],
        "+ weather": ft.INCIDENT_BASE_FEATURES + ["cause_cat"] + ft.WEATHER_HOURLY_FEATURES,
    }

    test_frame = incidents.loc[test, ["mode", "date", "hour", "cause", "min_delay", "long_delay"]].copy()

    # Baseline: the long-delay rate for that mode and cause over the
    # most recent 12 months before the test year.
    recent = incidents[valid]
    rate = recent.groupby(["mode", "cause"], observed=True)["long_delay"].mean()
    keys = pd.MultiIndex.from_frame(test_frame[["mode", "cause"]])
    test_frame["baseline"] = rate.reindex(keys).to_numpy()
    test_frame["baseline"] = test_frame["baseline"].fillna(float(recent["long_delay"].mean()))

    # A tougher baseline: that route's own long-delay rate, by time of
    # day, over the same recent 12 months. If the model can't beat a
    # lookup table, it isn't adding anything.
    def block(hours: pd.Series) -> pd.Series:
        return pd.cut(hours, [-1, 5, 9, 15, 19, 23], labels=False)

    recent_routes = recent.assign(block=block(recent["hour"]))
    route_rate = recent_routes.groupby(["route_cat", "block"], observed=True)["long_delay"].mean()
    route_only = recent.groupby("route_cat", observed=True)["long_delay"].mean()
    route_test = incidents.loc[test, "route_cat"].astype(str)
    keys = pd.MultiIndex.from_arrays([route_test, block(test_frame["hour"])])
    route_rate.index = route_rate.index.set_levels(route_rate.index.levels[0].astype(str), level=0)
    lookup = pd.Series(route_rate.reindex(keys).to_numpy(), index=test_frame.index)
    lookup = lookup.fillna(route_test.map(route_only.rename(index=str)))
    test_frame["route_lookup"] = lookup.fillna(test_frame["baseline"]).to_numpy()

    results: dict = {
        "train_rows": int(train.sum()), "test_rows": int(test.sum()),
        "thresholds_min": ft.LONG_DELAY_MIN, "by_stage": {},
    }
    importances = None
    for stage, cols in stages.items():
        model = lgb.LGBMClassifier(
            n_estimators=500, learning_rate=0.1, num_leaves=63, min_child_samples=100,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.8, cat_smooth=20,
            max_cat_threshold=32, max_bin=63, random_state=SEED, verbose=-1,
        )
        model.fit(
            incidents.loc[train, cols], y[train],
            eval_set=[(incidents.loc[valid, cols], y[valid])], eval_metric="auc",
            callbacks=[lgb.early_stopping(30, verbose=False)],
        )
        test_frame[stage] = model.predict_proba(incidents.loc[test, cols])[:, 1]
        results["by_stage"][stage] = {
            mode: {
                "auc": round(float(roc_auc_score(g["long_delay"], g[stage])), 3),
                "pr_auc": round(float(average_precision_score(g["long_delay"], g[stage])), 3),
            }
            for mode, g in test_frame.groupby("mode")
        }
        if stage == "+ cause":
            gain = pd.Series(model.booster_.feature_importance("gain"), index=cols)
            importances = (gain / gain.sum()).sort_values(ascending=False)

    results["baseline"] = {
        mode: {
            "long_delay_rate": round(float(g["long_delay"].mean()), 3),
            "auc": round(float(roc_auc_score(g["long_delay"], g["baseline"])), 3),
            "pr_auc": round(float(average_precision_score(g["long_delay"], g["baseline"])), 3),
        }
        for mode, g in test_frame.groupby("mode")
    }

    results["baseline_route_lookup"] = {
        mode: {
            "auc": round(float(roc_auc_score(g["long_delay"], g["route_lookup"])), 3),
            "pr_auc": round(float(average_precision_score(g["long_delay"], g["route_lookup"])), 3),
        }
        for mode, g in test_frame.groupby("mode")
    }

    # Is a predicted 70% actually ~70%? (calibration, per mode)
    final = "+ cause"
    test_frame["bucket"] = (test_frame[final] * 10).clip(upper=9.999).astype(int) / 10
    calibration = (
        test_frame.groupby(["mode", "bucket"])
        .agg(incidents=("long_delay", "size"), predicted=(final, "mean"), observed=("long_delay", "mean"))
        .round(3).reset_index()
    )
    calibration.to_csv(reports / "long_delay_calibration.csv", index=False)
    importances.round(4).rename("share_of_gain").to_csv(reports / "long_delay_importance.csv", index_label="feature")

    # What acting on the model would look like: flag the riskiest 20%.
    flagged = {}
    for mode, g in test_frame.groupby("mode"):
        cut = g[final].quantile(0.8)
        top = g[g[final] >= cut]
        flagged[mode] = {
            "share_of_long_delays_caught_pct": round(100 * float(top["long_delay"].sum() / g["long_delay"].sum()), 1),
            "precision_pct": round(100 * float(top["long_delay"].mean()), 1),
        }
    results["flag_top_20pct"] = flagged
    return results


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=Path("data/processed"))
    parser.add_argument("--reports", type=Path, default=Path("reports"))
    args = parser.parse_args()
    args.reports.mkdir(parents=True, exist_ok=True)

    delays = pd.read_parquet(args.data / "delays.parquet")
    weather_hourly = pd.read_parquet(args.data / "weather_hourly.parquet")
    weather_daily = pd.read_parquet(args.data / "weather_daily.parquet")
    weather = ft.daily_weather_features(weather_daily, weather_hourly)

    metrics: dict = {
        "data": {
            "delay_records": int(len(delays)),
            "first_date": str(delays["date"].min().date()),
            "last_date": str(delays["date"].max().date()),
            "routes": int(delays.groupby("mode")["route"].nunique().sum()),
            "weather_hours": int(len(weather_hourly)),
        },
        "split": {
            "train_through": str(ft.TRAIN_END.date()),
            "validation_through": str(ft.VALID_END.date()),
            "test": f"{(ft.VALID_END + pd.Timedelta(days=1)).date()} to {delays['date'].max().date()}",
        },
    }

    print("Daily forecast ...")
    panel = ft.daily_panel(delays, weather)
    metrics["daily_forecast"] = train_daily_forecast(panel, args.reports)
    metrics["storm_effect"] = storm_effect(panel, delays, args.reports)

    print("Long-delay classifier ...")
    incidents = ft.incident_table(delays, weather_hourly, weather_daily)
    metrics["long_delay"] = train_long_delay(incidents, args.reports)

    (args.reports / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics["daily_forecast"]["by_stage"], indent=2))
    print(json.dumps({k: metrics["long_delay"][k] for k in ("baseline", "baseline_route_lookup", "by_stage", "flag_top_20pct")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
