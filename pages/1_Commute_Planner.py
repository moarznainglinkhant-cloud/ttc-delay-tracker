"""
UTSC -> UTSG Commute Planner.

Combines the bus leg (a UTSC-area route to Kennedy Station) with the
subway leg (Line 2 Bloor-Danforth, Kennedy -> St. George — no transfer
needed, since St. George is the interchange with Line 1) to estimate
which times of day/week are historically least delay-prone for the
whole trip.

IMPORTANT — what this actually measures: the City's delay datasets log
*incidents* (including some zero-minute entries), not every scheduled
trip. There's no public "total trips run" denominator, so this can't
compute a true probability of being delayed. What it CAN do, honestly,
is compare the historical frequency and severity of logged delay
incidents across hours/days — a solid proxy for "which time slots have
been rougher," even if it isn't a guaranteed travel time.
"""
from __future__ import annotations

import sqlite3

import altair as alt
import pandas as pd
import streamlit as st

from config import DB_PATH, KENNEDY_STATION, ST_GEORGE_STATION, SUBWAY_LINE_OF_INTEREST
from theme import CATEGORICAL_RANGE, SEQUENTIAL_SCHEME, apply_altair_theme, inject_page_css

st.set_page_config(page_title="UTSC → UTSG Commute Planner", page_icon="🗺️", layout="wide")
apply_altair_theme()
st.markdown(inject_page_css(), unsafe_allow_html=True)

DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAYS = DAY_ORDER[:5]
WEEKENDS = DAY_ORDER[5:]


@st.cache_data(ttl=300)
def load_data(db_path: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM delays", conn)
    conn.close()
    return df


def add_hour(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["hour"] = pd.to_numeric(df["time"].str.slice(0, 2), errors="coerce")
    return df.dropna(subset=["hour"])


def full_grid(days: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [(d, h) for d in days for h in range(24)], columns=["day", "hour"]
    )


st.title("🗺️ UTSC → UTSG Commute Planner")
st.caption(
    "Estimating the least delay-prone time to make the classic bus-to-Kennedy, "
    "then Line 2 subway to St. George trip between the two campuses."
)

df = load_data(DB_PATH)
if df.empty:
    st.warning("No data yet. Run `python fetch_data.py` to fetch and store delay records.")
    st.stop()

if "mode" not in df.columns:
    st.error("This database predates the bus/subway split — run `python fetch_data.py` again to migrate it.")
    st.stop()

df = add_hour(df)
bus_df = df[df["mode"] == "bus"]
subway_df = df[(df["mode"] == "subway") & (df["route"] == SUBWAY_LINE_OF_INTEREST)]

if subway_df.empty:
    st.info(
        f"No {SUBWAY_LINE_OF_INTEREST} subway data yet — run `python fetch_data.py` "
        "(with the updated fetch script) to pull it in. Showing the bus leg only for now."
    )

# --- Sidebar controls ---
st.sidebar.header("Filters")
day_type = st.sidebar.radio("Day type", ["All days", "Weekdays only", "Weekends only"])
if day_type == "Weekdays only":
    active_days = WEEKDAYS
elif day_type == "Weekends only":
    active_days = WEEKENDS
else:
    active_days = DAY_ORDER

start_hour, end_hour = st.sidebar.slider(
    "Consider departure hours between", 0, 23, (6, 22),
    help="Restricts the 'best time to leave' recommendation to a realistic travel window.",
)

# --- Aggregate each leg by day + hour ---
def agg_leg(leg_df: pd.DataFrame, days: list[str]) -> pd.DataFrame:
    leg_df = leg_df[leg_df["day"].isin(days)]
    grouped = leg_df.groupby(["day", "hour"]).agg(
        avg_delay=("min_delay", "mean"), events=("min_delay", "count")
    ).reset_index()
    grid = full_grid(days)
    merged = grid.merge(grouped, on=["day", "hour"], how="left").fillna({"avg_delay": 0, "events": 0})
    return merged

bus_agg = agg_leg(bus_df, active_days).rename(columns={"avg_delay": "bus_delay", "events": "bus_events"})
subway_agg = agg_leg(subway_df, active_days).rename(columns={"avg_delay": "subway_delay", "events": "subway_events"})
combined = bus_agg.merge(subway_agg, on=["day", "hour"], how="outer").fillna(0)
combined["total_delay"] = combined["bus_delay"] + combined["subway_delay"]
combined["total_events"] = combined["bus_events"] + combined["subway_events"]
combined["day"] = pd.Categorical(combined["day"], categories=DAY_ORDER, ordered=True)

# --- Recommendation ---
window = combined[(combined["hour"] >= start_hour) & (combined["hour"] <= end_hour)]
by_hour = window.groupby("hour").agg(
    avg_total_delay=("total_delay", "mean"), total_events=("total_events", "sum")
).reset_index()

if not by_hour.empty:
    best = by_hour.loc[by_hour["avg_total_delay"].idxmin()]
    worst = by_hour.loc[by_hour["avg_total_delay"].idxmax()]

    col1, col2, col3 = st.columns(3)
    col1.metric(
        "✅ Best hour to leave",
        f"{int(best['hour']):02d}:00",
        f"{best['avg_total_delay']:.1f} min avg logged delay",
    )
    col2.metric(
        "⚠️ Worst hour to leave",
        f"{int(worst['hour']):02d}:00",
        f"{worst['avg_total_delay']:.1f} min avg logged delay",
    )
    col3.metric("Delay incidents in this window", f"{int(window['total_events'].sum()):,}")

st.caption(
    "\"Avg logged delay\" combines the average bus-leg delay and the average Line 2 "
    "delay recorded for that hour — a relative reliability signal from historical "
    "incident logs, not a guaranteed travel time."
)

st.divider()

# --- Heatmap: hour x day, combined delay ---
st.subheader("When are delays worst? (bus + subway combined)")
heatmap = (
    alt.Chart(combined)
    .mark_rect()
    .encode(
        x=alt.X("hour:O", title="Hour of day", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("day:N", title=None, sort=DAY_ORDER),
        color=alt.Color(
            "total_delay:Q",
            title="Avg delay (min)",
            scale=alt.Scale(scheme=SEQUENTIAL_SCHEME),
        ),
        tooltip=[
            alt.Tooltip("day:N", title="Day"),
            alt.Tooltip("hour:O", title="Hour"),
            alt.Tooltip("bus_delay:Q", title="Bus avg delay (min)", format=".1f"),
            alt.Tooltip("subway_delay:Q", title="Subway avg delay (min)", format=".1f"),
            alt.Tooltip("total_delay:Q", title="Combined avg delay (min)", format=".1f"),
            alt.Tooltip("total_events:Q", title="Logged incidents"),
        ],
    )
    .properties(height=280)
)
st.altair_chart(heatmap, use_container_width=True)

# --- Bus vs subway comparison by hour ---
st.subheader("Which leg is riskier, the bus or the subway?")
by_hour_leg = window.melt(
    id_vars="hour", value_vars=["bus_delay", "subway_delay"], var_name="leg", value_name="avg_delay"
)
by_hour_leg["leg"] = by_hour_leg["leg"].map({"bus_delay": "Bus to Kennedy", "subway_delay": "Line 2 subway"})
by_hour_leg = by_hour_leg.groupby(["hour", "leg"], as_index=False)["avg_delay"].mean()

line_chart = (
    alt.Chart(by_hour_leg)
    .mark_line(point=alt.OverlayMarkDef(size=35, filled=True), strokeWidth=2)
    .encode(
        x=alt.X("hour:O", title="Hour of day", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("avg_delay:Q", title="Avg logged delay (min)"),
        color=alt.Color("leg:N", title=None, scale=alt.Scale(range=CATEGORICAL_RANGE)),
        tooltip=["hour", "leg", alt.Tooltip("avg_delay:Q", format=".1f")],
    )
    .properties(height=280)
)
st.altair_chart(line_chart, use_container_width=True)

st.caption(
    f"Subway leg filtered to Line 2 (Bloor–Danforth) — the direct ride from "
    f"{KENNEDY_STATION.title()} to {ST_GEORGE_STATION.title()}, no transfer required."
)

with st.expander("Raw combined hour/day table"):
    st.dataframe(combined.sort_values(["day", "hour"]))
