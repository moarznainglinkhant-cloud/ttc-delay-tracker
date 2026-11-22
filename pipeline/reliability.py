"""
Put the delay logs over a denominator, and test what the timetable
adds to the long-delay model.

Writes:
  reports/route_reliability.csv   delays per 1,000 scheduled trips, by route
  reports/schedule_findings.json  headway vs logged delay, and the
                                  model ablation with schedule features

Caveat that applies to everything here: only the current timetable is
published, so today's service levels are applied to earlier delays. The
per-route rates use only the most recent 12 months for that reason.

Run (after build_dataset and schedule):
    python -m pipeline.reliability
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from pipeline import features as ft
from pipeline import schedule as sc

SEED = 42
# Routes with fewer scheduled trips than this give unstable rates.
MIN_TRIPS_PER_YEAR = 20_000
SCHEDULE_FEATURES = ["headway_min", "trips"]


def add_day_type(df: pd.DataFrame) -> pd.DataFrame:
    dow = df["date"].dt.dayofweek
    return df.assign(day_type=np.where(dow < 5, "weekday", np.where(dow == 5, "saturday", "sunday")))


def route_reliability(delays: pd.DataFrame, schedule: pd.DataFrame) -> pd.DataFrame:
    """Delays per 1,000 scheduled trips for each route, last 12 months."""
    recent = delays[delays["date"] > delays["date"].max() - pd.Timedelta(days=365)]
    long_cut = recent["mode"].map(ft.LONG_DELAY_MIN)
    counts = (
        recent.assign(is_long=(recent["min_delay"] >= long_cut).astype(int), minutes=recent["min_delay"].clip(upper=180))
        .groupby(["mode", "route"])
        .agg(delays=("hour", "size"), long_delays=("is_long", "sum"), delay_minutes=("minutes", "sum"))
        .reset_index()
    )
    out = sc.annual_trips(schedule).merge(counts, on=["mode", "route"], how="left").fillna({"delays": 0, "long_delays": 0, "delay_minutes": 0})
    out["delays_per_1000_trips"] = (1000 * out["delays"] / out["trips_per_year"]).round(2)
    out["long_delays_per_1000_trips"] = (1000 * out["long_delays"] / out["trips_per_year"]).round(2)
    surface = out["mode"] != "subway"
    out["rank_by_count"] = out[surface].groupby("mode")["delays"].rank(ascending=False, method="min")
    eligible = surface & (out["trips_per_year"] >= MIN_TRIPS_PER_YEAR)
    out["rank_by_rate"] = out[eligible].groupby("mode")["delays_per_1000_trips"].rank(ascending=False, method="min")
    return out.sort_values(["mode", "delays_per_1000_trips"], ascending=[True, False]).reset_index(drop=True)


def headway_findings(delays: pd.DataFrame, schedule: pd.DataFrame) -> dict:
    """How closely do logged delay minutes track the scheduled headway?"""
    _, _, test = ft.split_masks(delays["date"])
    recent = add_day_type(delays[test]).merge(
        schedule[["mode", "route", "day_type", "hour", "headway_min"]], on=["mode", "route", "day_type", "hour"], how="left"
    )
    out = {}
    for mode, grp in recent.groupby("mode"):
        matched = grp[grp["headway_min"].notna()]
        real = matched[(matched["min_delay"] > 0) & (matched["min_delay"] <= 180)]
        is_long = (matched["min_delay"] >= ft.LONG_DELAY_MIN[mode]).astype(int)
        out[mode] = {
            "matched_to_timetable_pct": round(100 * len(matched) / len(grp), 1),
            "spearman_delay_vs_headway": round(float(real[["min_delay", "headway_min"]].corr(method="spearman").iloc[0, 1]), 2),
            "delay_within_20pct_of_headway_pct": round(
                100 * float((np.abs(real["min_delay"] - real["headway_min"]) <= 0.2 * real["headway_min"]).mean()), 1
            ),
            "auc_headway_alone": round(float(roc_auc_score(is_long, matched["headway_min"])), 3),
        }
    return out


def schedule_ablation(incidents: pd.DataFrame, schedule: pd.DataFrame) -> dict:
    """Does knowing the timetable improve the long-delay classifier?"""
    data = incidents[incidents["date"] >= "2018-01-01"].reset_index(drop=True)
    data = add_day_type(data).merge(
        schedule[["mode", "route", "day_type", "hour", "trips", "headway_min"]], on=["mode", "route", "day_type", "hour"], how="left"
    )
    for col in ("mode_cat", "cause_cat", "route_cat", "location_cat", "direction_cat"):
        data[col] = data[col].astype("category")  # the merge drops category dtype
    train, valid, test = ft.split_masks(data["date"])
    base = ft.INCIDENT_BASE_FEATURES + ["cause_cat"]
    variants = {
        "route id (reported model)": base,
        "route id + timetable": base + SCHEDULE_FEATURES,
        "timetable instead of route id": [c for c in base if c != "route_cat"] + SCHEDULE_FEATURES,
    }
    scored = data.loc[test, ["mode", "long_delay"]].copy()
    for name, cols in variants.items():
        model = lgb.LGBMClassifier(
            n_estimators=500, learning_rate=0.1, num_leaves=63, min_child_samples=100, subsample=0.8,
            subsample_freq=1, colsample_bytree=0.8, cat_smooth=20, max_cat_threshold=32, max_bin=63,
            random_state=SEED, verbose=-1,
        )
        model.fit(
            data.loc[train, cols], data.loc[train, "long_delay"],
            eval_set=[(data.loc[valid, cols], data.loc[valid, "long_delay"])], eval_metric="auc",
            callbacks=[lgb.early_stopping(30, verbose=False)],
        )
        scored[name] = model.predict_proba(data.loc[test, cols])[:, 1]
    return {
        name: {mode: round(float(roc_auc_score(g["long_delay"], g[name])), 3) for mode, g in scored.groupby("mode")}
        for name in variants
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=Path("data/processed"))
    parser.add_argument("--reports", type=Path, default=Path("reports"))
    args = parser.parse_args()
    args.reports.mkdir(parents=True, exist_ok=True)

    delays = pd.read_parquet(args.data / "delays.parquet")
    schedule = pd.read_parquet(args.data / "schedule.parquet")

    reliability = route_reliability(delays, schedule)
    reliability.to_csv(args.reports / "route_reliability.csv", index=False)

    totals = reliability.groupby("mode")[["trips_per_year", "delays", "long_delays"]].sum()
    eligible = reliability[reliability["rank_by_rate"].notna() & (reliability["mode"] == "bus")]
    findings = {
        "period": f"{(delays['date'].max() - pd.Timedelta(days=364)).date()} to {delays['date'].max().date()}",
        "by_mode": {
            mode: {
                "scheduled_trips_per_year": int(row["trips_per_year"]),
                "delays_per_1000_trips": round(1000 * row["delays"] / row["trips_per_year"], 1),
                "long_delays_per_1000_trips": round(1000 * row["long_delays"] / row["trips_per_year"], 1),
            }
            for mode, row in totals.iterrows()
        },
        "bus_rank_correlation_count_vs_rate": round(
            float(eligible[["delays", "delays_per_1000_trips"]].corr(method="spearman").iloc[0, 1]), 2
        ),
        "headway": headway_findings(delays, schedule),
    }

    print("Timetable ablation (three model fits) ...")
    incidents = ft.incident_table(
        delays, pd.read_parquet(args.data / "weather_hourly.parquet"), pd.read_parquet(args.data / "weather_daily.parquet")
    )
    findings["ablation_auc"] = schedule_ablation(incidents, schedule)

    (args.reports / "schedule_findings.json").write_text(json.dumps(findings, indent=2))
    print(json.dumps(findings, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
