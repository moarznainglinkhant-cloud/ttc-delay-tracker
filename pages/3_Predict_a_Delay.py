"""
Predict a Delay: an interactive front end to the long-delay classifier.

Loads the model exported by pipeline/train.py (models/long_delay.txt)
and scores whatever incident the visitor describes. Evaluation of this
model lives on the Delay Forecast page.
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from theme import BUS_COLOR, MUTED_TEXT, apply_altair_theme, inject_page_css

st.set_page_config(page_title="Predict a TTC Delay", page_icon="🎯", layout="wide")
apply_altair_theme()
st.markdown(inject_page_css(), unsafe_allow_html=True)

MODELS = Path(__file__).resolve().parent.parent / "models"
MODE_LABEL = {"bus": "Bus", "streetcar": "Streetcar", "subway": "Subway"}
CAUSE_LABEL = {
    "mechanical": "Mechanical fault", "operator": "Operator or crew issue", "security": "Security incident",
    "collision": "Collision", "diversion": "Diversion or shuttle", "medical": "Medical emergency",
    "cleaning": "Cleaning needed", "infrastructure": "Track, signal or power problem",
    "passenger": "Passenger alarm", "weather": "Weather", "general": "General delay", "other": "Other",
}
DIRECTION_LABEL = {"N": "Northbound", "S": "Southbound", "E": "Eastbound", "W": "Westbound", "B": "Both ways"}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
BLOCK_LABEL = ["overnight (midnight to 5am)", "the morning peak (6 to 9am)", "midday (10am to 3pm)", "the afternoon peak (4 to 7pm)", "the evening (8 to 11pm)"]
CATEGORICAL = ["mode_cat", "route_cat", "location_cat", "direction_cat", "cause_cat"]


@st.cache_resource
def load_model():
    import lightgbm as lgb

    return lgb.Booster(model_file=str(MODELS / "long_delay.txt"))


@st.cache_data
def load_options() -> dict:
    return json.loads((MODELS / "predictor_options.json").read_text())


def hour_label(hour: int) -> str:
    suffix = "am" if hour < 12 else "pm"
    return f"{(hour % 12) or 12} {suffix}"


def block_of(hour: int, edges: list[int]) -> int:
    return next(i for i in range(len(edges) - 1) if edges[i] < hour <= edges[i + 1])


st.title("Predict a Delay")
st.caption("Describe a delay that has just been reported. The model estimates the chance it turns into a long one.")

try:
    options = load_options()
    model = load_model()
except Exception as exc:  # missing file or library on the host
    st.error(f"The prediction model isn't available here ({type(exc).__name__}). The evaluation results are on the Delay Forecast page.")
    st.stop()

routes = options["routes"]


def route_sort_key(key: str):
    number = routes[key]["number"]
    return (0, int(number)) if number.isdigit() else (1, 0)


def route_label(key: str) -> str:
    r = routes[key]
    return f"{r['number']} {r['name']}".strip() if r["mode"] != "subway" else r["name"]


# ---- inputs -----------------------------------------------------------------
top = st.columns([1, 2, 2])
mode = top[0].radio("Mode", ["bus", "streetcar", "subway"], format_func=MODE_LABEL.get)
mode_routes = sorted([k for k, r in routes.items() if r["mode"] == mode], key=route_sort_key)
default_route = {"bus": "bus:29", "streetcar": "streetcar:501", "subway": "subway:YU"}[mode]
route_key = top[1].selectbox(
    "Route", mode_routes, format_func=route_label,
    index=mode_routes.index(default_route) if default_route in mode_routes else 0,
)
route = routes[route_key]
cause = top[2].selectbox("What happened", options["causes"][mode], format_func=lambda c: CAUSE_LABEL.get(c, c.title()))

row2 = st.columns([2, 1, 1, 1, 1])
location = row2[0].selectbox(
    "Where", ["OTHER"] + route["locations"],
    format_func=lambda x: "Elsewhere on the route" if x == "OTHER" else x.title(),
    # Subway incidents are logged by station; surface ones mostly at unlisted stops.
    index=1 if mode == "subway" and route["locations"] else 0,
)
direction = row2[1].selectbox(
    "Direction", route["directions"] + ["UNKNOWN"], format_func=lambda d: DIRECTION_LABEL.get(d, "Not recorded")
)
day = row2[2].selectbox("Day", range(7), format_func=lambda i: DAYS[i], index=1)
hour = row2[3].selectbox("Time", range(24), format_func=hour_label, index=17)
month = row2[4].selectbox("Month", range(1, 13), format_func=lambda m: MONTHS[m - 1], index=0)


# ---- scoring ----------------------------------------------------------------
def score(frame: pd.DataFrame):
    for col in CATEGORICAL:
        frame[col] = frame[col].astype("category")
    return model.predict(frame[options["features"]])


def scenario(**overrides) -> dict:
    base = {
        "mode_cat": mode, "route_cat": route_key, "location_cat": location, "direction_cat": direction,
        "hour": hour, "dow": day, "month": month, "days_since_2014": options["days_since_2014"], "cause_cat": cause,
    }
    base.update(overrides)
    return base


threshold = options["thresholds_min"][mode]
probability = float(score(pd.DataFrame([scenario()]))[0])
mode_rate = options["mode_long_rate"][mode]
block = block_of(hour, options["hour_blocks"])
block_rate, block_n = route["rate_by_block"].get(str(block), [None, 0])

st.divider()
left, right = st.columns([2, 3])
with left:
    st.metric(f"Chance this delay runs {threshold}+ minutes", f"{probability:.0%}",
              f"{round((probability - mode_rate) * 100) + 0:+d} points vs the typical {MODE_LABEL[mode].lower()} delay",
              delta_color="inverse")
    lines = [f"- All {MODE_LABEL[mode].lower()} delays, last two years: **{mode_rate:.0%}** ran long."]
    if block_rate is not None and block_n >= 30:
        lines.append(
            f"- This route during {BLOCK_LABEL[block]}, any cause: **{block_rate:.0%}** of {block_n:,} logged delays ran long."
        )
    lines.append(f"- This route overall: **{route['long_rate']:.0%}** of {route['incidents']:,}.")
    st.markdown("\n".join(lines))
    st.caption(
        "The model's estimate differs from the route's history because it also accounts for the cause, "
        "place, direction, weekday and month you picked."
    )

with right:
    by_hour = pd.DataFrame([scenario(hour=h) for h in range(24)])
    curve = pd.DataFrame({"hour": range(24), "probability": score(by_hour)})
    curve["label"] = curve["hour"].map(hour_label)
    curve["selected"] = curve["hour"] == hour
    hour_chart = (
        alt.Chart(curve)
        .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
        .encode(
            x=alt.X("hour:O", title="If the same incident happened at...", axis=alt.Axis(labelExpr="datum.value % 3 == 0 ? (datum.value % 12 || 12) + (datum.value < 12 ? 'am' : 'pm') : ''", labelAngle=0)),
            y=alt.Y("probability:Q", title=f"Chance of {threshold}+ minutes", axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, max(0.5, float(curve['probability'].max()) * 1.1)])),
            color=alt.condition(alt.datum.selected, alt.value(BUS_COLOR), alt.value("#D1D5DB")),
            tooltip=[alt.Tooltip("label:N", title="Time"), alt.Tooltip("probability:Q", title="Chance", format=".0%")],
        )
        .properties(height=260)
    )
    rule = alt.Chart(pd.DataFrame({"y": [mode_rate]})).mark_rule(color=MUTED_TEXT, strokeDash=[4, 4]).encode(y="y:Q")
    st.altair_chart(hour_chart + rule, width="stretch")
    st.caption(f"Red is the time you picked. Dashed line: the typical {MODE_LABEL[mode].lower()} delay.")

st.subheader("Same place and time, different cause")
by_cause = pd.DataFrame([scenario(cause_cat=c) for c in options["causes"][mode]])
causes = pd.DataFrame({"cause": options["causes"][mode], "probability": score(by_cause)})
causes["label"] = causes["cause"].map(lambda c: CAUSE_LABEL.get(c, c.title()))
causes["selected"] = causes["cause"] == cause
cause_chart = (
    alt.Chart(causes)
    .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
    .encode(
        y=alt.Y("label:N", title=None, sort="-x", axis=alt.Axis(labelLimit=240, labelOverlap=False)),
        x=alt.X("probability:Q", title=f"Chance of {threshold}+ minutes", axis=alt.Axis(format="%")),
        color=alt.condition(alt.datum.selected, alt.value(BUS_COLOR), alt.value("#D1D5DB")),
        tooltip=[alt.Tooltip("label:N", title="Cause"), alt.Tooltip("probability:Q", title="Chance", format=".0%")],
    )
    .properties(height=max(220, 30 * len(causes)))
)
st.altair_chart(cause_chart, width="stretch")

try:
    _auc = json.loads((MODELS.parent / "reports" / "metrics.json").read_text())["long_delay"]["by_stage"]["+ cause"]
    held_out = (
        f"On a held-out year it scored {_auc['bus']['auc']:.2f} AUC for bus, {_auc['subway']['auc']:.2f} for subway "
        f"and {_auc['streetcar']['auc']:.2f} for streetcar; "
    )
except Exception:
    held_out = ""

st.caption(
    f"Gradient-boosted classifier trained on delays logged from 2018 to {options['trained_through'][:4]}. "
    f"{held_out}see the Delay Forecast page "
    "for baselines and limits. It predicts what the TTC would log, which for buses is closely tied to how far apart "
    "buses are scheduled on that route."
)
