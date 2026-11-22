"""
Delay Forecast: results of the two models trained in pipeline/train.py.

This page only reads the small result files in reports/, so the deployed
app needs no model libraries and loads instantly. To refresh the numbers,
rerun the pipeline (see README) and commit reports/.
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from theme import BUS_COLOR, MUTED_TEXT, SUBWAY_COLOR, apply_altair_theme, inject_page_css

st.set_page_config(page_title="TTC Delay Forecast", page_icon="📈", layout="wide")
apply_altair_theme()
st.markdown(inject_page_css(), unsafe_allow_html=True)

REPORTS = Path(__file__).resolve().parent.parent / "reports"
STREETCAR_COLOR = "#D97706"
MODE_COLORS = alt.Scale(domain=["bus", "streetcar", "subway"], range=[BUS_COLOR, STREETCAR_COLOR, SUBWAY_COLOR])
MODE_LABEL = {"bus": "Bus", "streetcar": "Streetcar", "subway": "Subway"}


@st.cache_data
def load_reports() -> dict:
    return {
        "metrics": json.loads((REPORTS / "metrics.json").read_text()),
        "forecast": pd.read_csv(REPORTS / "daily_forecast_test.csv", parse_dates=["date"]),
        "storm": pd.read_csv(REPORTS / "storm_effect.csv"),
        "calibration": pd.read_csv(REPORTS / "long_delay_calibration.csv"),
        "importance": pd.read_csv(REPORTS / "long_delay_importance.csv"),
    }


try:
    data = load_reports()
except FileNotFoundError:
    st.error("No model results found in reports/. Run `python -m pipeline.train` first (see README).")
    st.stop()

metrics = data["metrics"]
info, split = metrics["data"], metrics["split"]
long_delay, daily = metrics["long_delay"], metrics["daily_forecast"]

st.title("TTC Delay Forecast")
st.caption(
    f"Two models trained on {info['delay_records']:,} delay records from all three TTC modes "
    f"({info['first_date'][:4]} to {info['last_date'][:4]}), joined to {info['weather_hours']:,} hours of weather. "
    f"Every score below is from {split['test']}, a year the models never saw."
)


def best_baseline_auc(mode: str) -> float:
    return max(long_delay["baseline"][mode]["auc"], long_delay["baseline_route_lookup"][mode]["auc"])


final_stage = long_delay["by_stage"]["+ cause"]
with_history = daily["by_stage"]["calendar + recent history"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Delay records", f"{info['delay_records'] / 1e6:.2f}M")
c2.metric(
    "Subway long-delay AUC",
    f"{final_stage['subway']['auc']:.2f}",
    f"+{final_stage['subway']['auc'] - best_baseline_auc('subway'):.2f} vs best baseline",
)
c3.metric(
    "Bus long-delay AUC",
    f"{final_stage['bus']['auc']:.2f}",
    f"+{final_stage['bus']['auc'] - best_baseline_auc('bus'):.2f} vs best baseline",
)
c4.metric(
    "Subway daily forecast error",
    f"{with_history['subway']['mae_model']:.1f} delays",
    f"-{with_history['subway']['improvement_pct']:.0f}% vs 28-day average",
    delta_color="inverse",
)

st.divider()

# --------------------------------------------------------------------------
# 1. Long-delay classifier
# --------------------------------------------------------------------------
st.subheader("1. Will this delay run long?")
thresholds = long_delay["thresholds_min"]
st.write(
    f"The moment a delay is logged, the model estimates the chance it becomes a long one "
    f"({thresholds['bus']}+ minutes on bus and streetcar, {thresholds['subway']}+ on the subway), using only what "
    "dispatch knows at that moment: route, location, direction, time and cause."
)

left, right = st.columns([3, 2])
with left:
    rows = []
    for mode in ("bus", "streetcar", "subway"):
        rows += [
            {"mode": MODE_LABEL[mode], "who": "Baseline: rate by cause", "auc": long_delay["baseline"][mode]["auc"]},
            {"mode": MODE_LABEL[mode], "who": "Baseline: rate by route and time", "auc": long_delay["baseline_route_lookup"][mode]["auc"]},
            {"mode": MODE_LABEL[mode], "who": "Model", "auc": final_stage[mode]["auc"]},
        ]
    order = ["Baseline: rate by cause", "Baseline: rate by route and time", "Model"]
    auc_chart = (
        alt.Chart(pd.DataFrame(rows))
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("who:N", title=None, sort=order, axis=alt.Axis(labels=False, ticks=False)),
            y=alt.Y("auc:Q", title="AUC on the unseen year", scale=alt.Scale(domain=[0.5, 0.9], clamp=True)),
            color=alt.Color("who:N", sort=order, title=None, scale=alt.Scale(domain=order, range=["#D1D5DB", "#9CA3AF", BUS_COLOR]),
                            legend=alt.Legend(orient="bottom")),
            column=alt.Column("mode:N", title=None, sort=["Bus", "Streetcar", "Subway"]),
            tooltip=[alt.Tooltip("mode:N", title="Mode"), alt.Tooltip("who:N", title="Method"), alt.Tooltip("auc:Q", title="AUC", format=".3f")],
        )
        .properties(height=280, width=150)
    )
    st.altair_chart(auc_chart)
    st.caption("AUC: 0.5 is a coin flip, 1.0 is perfect. The axis starts at 0.5.")

with right:
    flagged = long_delay["flag_top_20pct"]
    st.markdown("**If dispatch flagged the riskiest 20% of incidents**")
    st.caption("Caught: share of all long delays inside the flagged group. Correct: share of flags that did run long.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Mode": MODE_LABEL[m],
                    "Caught": f"{flagged[m]['share_of_long_delays_caught_pct']:.0f}%",
                    "Correct": f"{flagged[m]['precision_pct']:.0f}%",
                    "Base rate": f"{100 * long_delay['baseline'][m]['long_delay_rate']:.0f}%",
                }
                for m in ("bus", "streetcar", "subway")
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.markdown(
        "**Reading this honestly.** For buses, a plain lookup of each route's history is almost as good as the "
        "model: logged bus delays largely reflect how far apart buses are scheduled on that route. The model adds "
        "the most on the subway, where no simple lookup works. Streetcar shows no real gain."
    )

cal_left, cal_right = st.columns(2)
with cal_left:
    st.markdown("**Are the probabilities trustworthy?**")
    cal = data["calibration"].assign(mode=lambda d: d["mode"].map(MODE_LABEL))
    diagonal = alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(color=MUTED_TEXT, strokeDash=[4, 4]).encode(x="x:Q", y="y:Q")
    points = (
        alt.Chart(cal)
        .mark_line(point=True)
        .encode(
            x=alt.X("predicted:Q", title="Predicted chance of a long delay", axis=alt.Axis(format="%")),
            y=alt.Y("observed:Q", title="How often it happened", axis=alt.Axis(format="%")),
            color=alt.Color("mode:N", title=None, scale=alt.Scale(domain=["Bus", "Streetcar", "Subway"], range=[BUS_COLOR, STREETCAR_COLOR, SUBWAY_COLOR])),
            tooltip=[alt.Tooltip("mode:N", title="Mode"), alt.Tooltip("predicted:Q", format=".0%"), alt.Tooltip("observed:Q", format=".0%"), alt.Tooltip("incidents:Q", format=",")],
        )
    )
    st.altair_chart((diagonal + points).properties(height=280), width="stretch")
    st.caption("On the dashed line, a predicted 70% happens 70% of the time.")

with cal_right:
    st.markdown("**What the model relies on**")
    names = {
        "route_cat": "Route", "cause_cat": "Cause", "hour": "Hour of day", "location_cat": "Location",
        "days_since_2014": "Long-run trend", "direction_cat": "Direction", "dow": "Day of week",
        "mode_cat": "Mode", "month": "Month",
    }
    imp = data["importance"].assign(feature=lambda d: d["feature"].map(names).fillna(d["feature"]))
    imp_chart = (
        alt.Chart(imp)
        .mark_bar(color=BUS_COLOR, cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
        .encode(
            y=alt.Y("feature:N", title=None, sort="-x"),
            x=alt.X("share_of_gain:Q", title="Share of the model's predictive gain", axis=alt.Axis(format="%")),
            tooltip=[alt.Tooltip("feature:N", title="Feature"), alt.Tooltip("share_of_gain:Q", title="Share", format=".1%")],
        )
        .properties(height=280)
    )
    st.altair_chart(imp_chart, width="stretch")
    st.caption("Adding hourly weather did not improve this model, so it was left out.")

st.divider()

# --------------------------------------------------------------------------
# 2. Daily forecast
# --------------------------------------------------------------------------
st.subheader("2. How many delays tomorrow?")
st.write(
    "A next-day forecast of the number of delays each mode will log, from the calendar and recent history, "
    "scored against a naive forecast (the average of the previous 28 days)."
)

mode_pick = st.radio("Mode", ["bus", "streetcar", "subway"], format_func=MODE_LABEL.get, horizontal=True, index=2)
fc = data["forecast"][data["forecast"]["mode"] == mode_pick]
long_form = fc.melt(id_vars="date", value_vars=["actual", "baseline", "model"], var_name="series", value_name="delays")
long_form["series"] = long_form["series"].map({"actual": "Actual", "baseline": "28-day average", "model": "Model forecast"})
series_order = ["Actual", "28-day average", "Model forecast"]
fc_chart = (
    alt.Chart(long_form)
    .mark_line(strokeWidth=1.6)
    .encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("delays:Q", title="Delays logged per day"),
        color=alt.Color("series:N", title=None, sort=series_order,
                        scale=alt.Scale(domain=series_order, range=["#9CA3AF", "#111827", BUS_COLOR]), legend=alt.Legend(orient="top")),
        tooltip=[alt.Tooltip("date:T", title="Date"), alt.Tooltip("series:N", title="Series"), alt.Tooltip("delays:Q", title="Delays", format=".0f")],
    )
    .properties(height=320)
)
st.altair_chart(fc_chart, width="stretch")

table = []
for mode in ("bus", "streetcar", "subway"):
    r, w = with_history[mode], daily["by_stage"]["+ weather"][mode]
    table.append(
        {
            "Mode": MODE_LABEL[mode],
            "Typical delays per day": f"{r['mean_daily_delays']:.0f}",
            "Error: 28-day average": f"{r['mae_baseline']:.1f}",
            "Error: model": f"{r['mae_model']:.1f}",
            "Improvement (95% interval)": f"{r['improvement_pct']:.0f}% ({r['ci95_low_pct']:.0f}% to {r['ci95_high_pct']:.0f}%)",
            "With weather added": f"{w['improvement_pct']:.0f}%",
        }
    )
st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
st.caption(
    "Error is the average miss, in delays per day. The interval comes from resampling test days 1,000 times. "
    "An interval that includes 0% means no reliable improvement, which is the case for streetcar."
)

st.divider()

# --------------------------------------------------------------------------
# 3. Storm effect
# --------------------------------------------------------------------------
st.subheader("3. Weather matters only when it is extreme")
st.write(
    "Adding weather barely changes average forecast accuracy, because most days have ordinary weather. "
    "But on the rare heavy-snow days the effect is large. Each bar compares that day with the same mode's "
    "average over the previous 28 days."
)
storm = data["storm"].assign(mode=lambda d: d["mode"].map(MODE_LABEL))
band_order = ["none", "under 2 cm", "2-5 cm", "5-10 cm", "10+ cm"]
bars = (
    alt.Chart(storm)
    .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
    .encode(
        x=alt.X("mode:N", title=None, axis=alt.Axis(labels=False, ticks=False)),
        y=alt.Y("delays_vs_normal_pct:Q", title="Delays vs normal (%)"),
        color=alt.Color("mode:N", title=None, scale=alt.Scale(domain=["Bus", "Streetcar", "Subway"], range=[BUS_COLOR, STREETCAR_COLOR, SUBWAY_COLOR]),
                        legend=alt.Legend(orient="top")),
        tooltip=[
            alt.Tooltip("snow_band:N", title="Snowfall"), alt.Tooltip("mode:N", title="Mode"), alt.Tooltip("days:Q", title="Days in 12 years"),
            alt.Tooltip("delays_vs_normal_pct:Q", title="Delays vs normal (%)"),
            alt.Tooltip("ci95_low_pct:Q", title="95% low"), alt.Tooltip("ci95_high_pct:Q", title="95% high"),
        ],
    )
)
errors = alt.Chart(storm).mark_rule(color="#111827").encode(x="mode:N", y="ci95_low_pct:Q", y2="ci95_high_pct:Q")
storm_chart = alt.layer(bars, errors).properties(height=280, width=120).facet(
    column=alt.Column("snow_band:N", title="Snowfall that day", sort=band_order)
)
st.altair_chart(storm_chart)
heavy = storm[(storm["snow_band"] == "10+ cm") & (storm["mode"] == "Bus")].iloc[0]
st.caption(
    f"Black lines are 95% intervals. Days with 10+ cm of snow happened only {int(heavy['days'])} times in 12 years, "
    "so those intervals are wide; the 5-10 cm bus effect is the best-supported one."
)

with st.expander("Method and limits"):
    st.markdown(
        f"""
- **Split by time, not at random.** Trained through {split['train_through']}, tuned on the following 12 months,
  and scored once on {split['test']}. A random split would let the model learn from days after the ones it is tested on.
- **Baselines first.** Each model is compared with the strongest simple alternative, and features were added in
  stages so each had to earn its place. Weather did not, outside of storms.
- **No answer leakage.** The delay log also records the gap between vehicles, which is nearly the same number as
  the delay itself, so it is excluded from the long-delay model.
- **What a "delay" is here.** The TTC logs incidents, not every trip, so this measures logged incidents rather than
  the share of trips that ran late. On bus routes the logged minutes often equal the scheduled gap between buses.
- **Cause labels changed over time.** Bus and streetcar files switched from about 35 plain-English labels to about
  150 internal codes in 2025; they are mapped onto 12 shared groups, which is approximate.
- **Weather is observed, not forecast.** The daily forecast with weather assumes a perfect weather forecast.
"""
    )

st.caption("Sources: City of Toronto Open Data (TTC bus, streetcar and subway delay data); Environment and Climate Change Canada historical weather.")
