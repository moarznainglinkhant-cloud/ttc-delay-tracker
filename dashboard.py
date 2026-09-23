"""
Streamlit dashboard for UTSC-relevant TTC bus delays.

Run:
    streamlit run dashboard.py
"""
from __future__ import annotations

import sqlite3

import altair as alt
import pandas as pd
import streamlit as st

from config import DB_PATH
from theme import ACCENT, SEQUENTIAL_SCHEME, apply_altair_theme, inject_page_css

st.set_page_config(page_title="UTSC Commute Delay Tracker", page_icon="🚌", layout="wide")
apply_altair_theme()
st.markdown(inject_page_css(), unsafe_allow_html=True)


@st.cache_data(ttl=300)
def load_data(db_path: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM delays", conn)
    conn.close()
    if "mode" in df.columns:
        df = df[df["mode"] == "bus"]  # subway lives on the Commute Planner page
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["route_label"] = df["route"] + " " + df["route_name"].fillna("")
    return df


header_col, link_col = st.columns([3, 1])
with header_col:
    st.title("UTSC Commute Delay Tracker")
    st.caption(
        "TTC bus delay data for routes near University of Toronto Scarborough, "
        "from the City of Toronto Open Data portal."
    )
with link_col:
    st.write("")
    st.page_link("pages/1_Commute_Planner.py", label="Plan the commute to St. George →", icon="🗺️")

try:
    df = load_data(DB_PATH)
except Exception as exc:  # pragma: no cover - UI error path
    st.error(f"Couldn't load {DB_PATH}: {exc}")
    st.info("Run `python fetch_data.py` first to populate the database.")
    st.stop()

if df.empty:
    st.warning("No data yet. Run `python fetch_data.py` to fetch and store delay records.")
    st.stop()

# --- Sidebar filters ---
st.sidebar.header("Filters")
all_routes = sorted(df["route_label"].unique())
selected_routes = st.sidebar.multiselect("Routes", all_routes, default=all_routes)
min_date, max_date = df["date"].min().date(), df["date"].max().date()
date_range = st.sidebar.date_input("Date range", (min_date, max_date), min_value=min_date, max_value=max_date)

filtered = df[df["route_label"].isin(selected_routes)]
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
    filtered = filtered[(filtered["date"] >= start) & (filtered["date"] <= end)]

# --- Top-line stats ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total delay events", f"{len(filtered):,}")
col2.metric("Avg delay (min)", f"{filtered['min_delay'].mean():.1f}" if len(filtered) else "–")
col3.metric("Worst single delay (min)", f"{filtered['min_delay'].max():.0f}" if len(filtered) else "–")
worst_route = filtered.groupby("route_label")["min_delay"].sum().idxmax() if len(filtered) else "–"
col4.metric("Route with most total delay", worst_route)

st.divider()

# --- Delay by route + day-of-week pattern, side by side ---
left, right = st.columns(2)

with left:
    st.subheader("Total delay minutes by route")
    by_route = (
        filtered.groupby("route_label", as_index=False)["min_delay"]
        .sum()
        .sort_values("min_delay", ascending=False)
    )
    route_chart = (
        alt.Chart(by_route)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("route_label:N", title=None, sort="-y", axis=alt.Axis(labelAngle=-40)),
            y=alt.Y("min_delay:Q", title="Total delay (min)"),
            color=alt.Color(
                "min_delay:Q", scale=alt.Scale(scheme=SEQUENTIAL_SCHEME), legend=None
            ),
            tooltip=[
                alt.Tooltip("route_label:N", title="Route"),
                alt.Tooltip("min_delay:Q", title="Total delay (min)", format=",.0f"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(route_chart, use_container_width=True)

with right:
    st.subheader("Which days are worst?")
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    by_weekday = (
        filtered.groupby("day", as_index=False)["min_delay"].mean()
    )
    by_weekday["day"] = pd.Categorical(by_weekday["day"], categories=day_order, ordered=True)
    by_weekday = by_weekday.sort_values("day")
    weekday_chart = (
        alt.Chart(by_weekday)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, color=ACCENT)
        .encode(
            x=alt.X("day:N", title=None, sort=day_order),
            y=alt.Y("min_delay:Q", title="Avg delay (min)"),
            tooltip=[
                alt.Tooltip("day:N", title="Day"),
                alt.Tooltip("min_delay:Q", title="Avg delay (min)", format=".1f"),
            ],
        )
        .properties(height=320)
    )
    st.altair_chart(weekday_chart, use_container_width=True)

# --- Trend over time ---
st.subheader("Delay events over time")
by_day = filtered.groupby(filtered["date"].dt.date).size().reset_index(name="events")
by_day.columns = ["date", "events"]
trend_chart = (
    alt.Chart(by_day)
    .mark_line(color=ACCENT, point=alt.OverlayMarkDef(size=25, filled=True))
    .encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("events:Q", title="Delay events"),
        tooltip=[alt.Tooltip("date:T", title="Date"), alt.Tooltip("events:Q", title="Events")],
    )
    .properties(height=260)
)
st.altair_chart(trend_chart, use_container_width=True)

# --- Delay reasons ---
st.subheader("Most common delay codes")
by_code = filtered["code"].value_counts().head(10).reset_index()
by_code.columns = ["code", "count"]
code_chart = (
    alt.Chart(by_code)
    .mark_bar(cornerRadiusTopRight=3, cornerRadiusBottomRight=3)
    .encode(
        y=alt.Y("code:N", title=None, sort="-x"),
        x=alt.X("count:Q", title="Events"),
        color=alt.Color("count:Q", scale=alt.Scale(scheme=SEQUENTIAL_SCHEME), legend=None),
        tooltip=[alt.Tooltip("code:N", title="Code"), alt.Tooltip("count:Q", title="Events")],
    )
    .properties(height=320)
)
st.altair_chart(code_chart, use_container_width=True)

with st.expander("Raw data"):
    st.dataframe(filtered.sort_values("date", ascending=False), use_container_width=True)

st.caption(
    "Data source: City of Toronto Open Data — TTC Bus Delay Data. "
    "Route list configured in config.py — edit ROUTES_OF_INTEREST to match your own commute."
)
