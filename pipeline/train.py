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

    # A third, deliberately crude baseline: was a direction recorded at
    # all? On the subway a blank direction almost always means no train
    # was held (0.5% of those run long), so this one field carries a lot
    # of signal that has nothing to do with modelling skill.
    test_frame["direction_recorded"] = incidents.loc[test, "direction"].notna().astype(int).to_numpy()

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
            results["best_iteration"] = int(model.best_iteration_ or model.n_estimators)

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

    results["baseline_direction_recorded"] = {
        mode: {"auc": round(float(roc_auc_score(g["long_delay"], g["direction_recorded"])), 3)}
        for mode, g in test_frame.groupby("mode")
    }
    # The harder question: among incidents where a direction *was*
    # recorded (a vehicle was involved), can the model still rank them?
    with_direction = test_frame[test_frame["direction_recorded"] == 1]
    results["direction_recorded_only"] = {
        mode: {
            "incidents": int(len(g)),
            "long_delay_rate": round(float(g["long_delay"].mean()), 3),
            "auc_model": round(float(roc_auc_score(g["long_delay"], g["+ cause"])), 3),
            "auc_best_baseline": round(
                max(float(roc_auc_score(g["long_delay"], g["baseline"])), float(roc_auc_score(g["long_delay"], g["route_lookup"]))), 3
            ),
        }
        for mode, g in with_direction.groupby("mode")
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
# 3. Export a model the dashboard can call
# --------------------------------------------------------------------------

SUBWAY_NAMES = {
    "YU": "Line 1 Yonge-University", "BD": "Line 2 Bloor-Danforth", "SHP": "Line 4 Sheppard",
    "SRT": "Line 3 Scarborough (closed 2023)", "MULTI": "Interchange (more than one line)",
}
PREDICTOR_FEATURES = ft.INCIDENT_BASE_FEATURES + ["cause_cat"]
HOUR_BLOCKS = [-1, 5, 9, 15, 19, 23]  # overnight, AM peak, midday, PM peak, evening


def route_names(delays: pd.DataFrame) -> dict[str, str]:
    """'bus:116' -> 'Morningside', taken from the most common spelling in the logs."""
    surface = delays[delays["mode"] != "subway"]
    named = surface["route_raw"].astype(str).str.extract(r"^\s*(\d{1,3})\s+([A-Za-z].*)$")
    frame = pd.DataFrame({"key": surface["mode"] + ":" + named[0], "name": named[1].str.strip().str.title()}).dropna()
    frame = frame[~frame["name"].str.contains(r"\d|Shuttle|Line ", regex=True)]
    names = frame.groupby("key")["name"].agg(lambda x: x.value_counts().index[0]).to_dict()
    names.update({f"subway:{code}": name for code, name in SUBWAY_NAMES.items()})
    return names


def export_predictor(incidents: pd.DataFrame, delays: pd.DataFrame, n_trees: int, out_dir: Path) -> dict:
    """Refit the reported classifier on every available year and save it,
    plus the menus and historical rates the dashboard needs.

    The scores in metrics.json come from the model that never saw the
    test year. This refit uses the same features and the same number of
    trees but all the data, which is the right model to actually use.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    data = incidents[incidents["date"] >= "2018-01-01"].reset_index(drop=True)
    model = lgb.LGBMClassifier(
        n_estimators=n_trees, learning_rate=0.1, num_leaves=63, min_child_samples=100,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, cat_smooth=20,
        max_cat_threshold=32, max_bin=63, random_state=SEED, verbose=-1,
    )
    model.fit(data[PREDICTOR_FEATURES], data["long_delay"])
    model.booster_.save_model(str(out_dir / "long_delay.txt"))

    options = predictor_options(data, delays)
    (out_dir / "predictor_options.json").write_text(json.dumps(options))
    return {"trees": n_trees, "training_rows": int(len(data)), "routes_in_menu": len(options["routes"])}


def predictor_options(data: pd.DataFrame, delays: pd.DataFrame) -> dict:
    """Menus and historical rates for the dashboard's predictor page."""
    # Menus come from the last two years so retired routes and stops don't appear.
    last_date = data["date"].max()
    recent = data[data["date"] > last_date - pd.Timedelta(days=730)].copy()
    recent["block"] = pd.cut(recent["hour"], HOUR_BLOCKS, labels=False)
    names = route_names(delays)

    routes: dict = {}
    for key, grp in recent.groupby("route_cat", observed=True):
        if len(grp) < 100:
            continue
        mode, number = str(key).split(":")
        # A stop or direction has to account for a real share of the route's
        # incidents to be offered; stray entries are logging noise.
        floor = max(10, 0.02 * len(grp))
        locations = grp.loc[~grp["location_cat"].isin(["OTHER", "UNKNOWN"]), "location_cat"].astype(str).value_counts()
        locations = locations[locations >= floor]
        directions = grp["direction_cat"].astype(str).value_counts()
        directions = directions[(directions >= 0.05 * len(grp)) & (directions.index != "UNKNOWN")]
        by_block = grp.groupby("block")["long_delay"].agg(["mean", "size"])
        routes[str(key)] = {
            "mode": mode,
            "number": number,
            "name": names.get(str(key), ""),
            "incidents": int(len(grp)),
            "long_rate": round(float(grp["long_delay"].mean()), 4),
            "locations": locations.head(10).index.tolist(),
            "directions": directions.index.tolist(),
            "rate_by_block": {int(b): [round(float(r["mean"]), 4), int(r["size"])] for b, r in by_block.iterrows()},
        }

    options = {
        "features": PREDICTOR_FEATURES,
        "trained_through": str(last_date.date()),
        "days_since_2014": int((last_date - pd.Timestamp("2014-01-01")).days),
        "thresholds_min": ft.LONG_DELAY_MIN,
        "hour_blocks": HOUR_BLOCKS,
        "mode_long_rate": {m: round(float(g["long_delay"].mean()), 4) for m, g in recent.groupby("mode")},
        "causes": {
            m: g["cause"].astype(str).value_counts().loc[lambda c: c >= 50].index.tolist()
            for m, g in recent.groupby("mode")
        },
        "routes": routes,
    }
    return options


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=Path("data/processed"))
    parser.add_argument("--reports", type=Path, default=Path("reports"))
    parser.add_argument("--models", type=Path, default=Path("models"))
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

    print("Exporting the dashboard model ...")
    metrics["predictor"] = export_predictor(incidents, delays, metrics["long_delay"]["best_iteration"], args.models)

    (args.reports / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics["daily_forecast"]["by_stage"], indent=2))
    print(json.dumps({k: metrics["long_delay"][k] for k in ("baseline", "baseline_route_lookup", "by_stage", "flag_top_20pct")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
