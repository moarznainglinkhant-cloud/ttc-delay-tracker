"""
Streamlit dashboard for UTSC-relevant TTC bus delays.

Run:
    streamlit run dashboard.py
"""
from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from config import DB_PATH, ROUTES_OF_INTEREST

st.set_page_config(page_title="UTSC Commute Delay Tracker", page_icon="🚌", layout="wide")


@st.cache_data(ttl=300)
def load_data(db_path: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT * FROM delays", conn)
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["route_label"] = df["route"] + " " + df["route_name"].fillna("")
    return df


st.title("🚌 UTSC Commute Delay Tracker")
st.caption(
    "TTC bus delay data for routes near University of Toronto Scarborough, "
    "from the City of Toronto Open Data portal."
)

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
worst_route = (
    filtered.groupby("route_label")["min_delay"].sum().idxmax() if len(filtered) else "–"
)
col4.metric("Route with most total delay", worst_route)

st.divider()

# --- Delay by route ---
st.subheader("Total delay minutes by route")
by_route = (
    filtered.groupby("route_label")["min_delay"].sum().sort_values(ascending=False)
)
st.bar_chart(by_route)

# --- Trend over time ---
st.subheader("Delay events over time")
by_day = filtered.groupby(filtered["date"].dt.date).size()
st.line_chart(by_day)

# --- Day of week pattern ---
st.subheader("Which days are worst?")
day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
by_weekday = (
    filtered.groupby("day")["min_delay"].mean().reindex(day_order).dropna()
)
st.bar_chart(by_weekday)

# --- Delay reasons ---
st.subheader("Most common delay codes")
by_code = filtered["code"].value_counts().head(10)
st.bar_chart(by_code)

with st.expander("Raw data"):
    st.dataframe(filtered.sort_values("date", ascending=False))

st.caption(
    "Data source: City of Toronto Open Data — TTC Bus Delay Data. "
    "Route list configured in config.py — edit ROUTES_OF_INTEREST to match your own commute."
)
