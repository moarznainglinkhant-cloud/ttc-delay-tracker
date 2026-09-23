"""
Shared analysis helpers for turning raw delay rows into rider-relevant
metrics — used by both dashboard.py and pages/1_Commute_Planner.py.
"""
from __future__ import annotations

import pandas as pd

from config import DIVERSION_CODES, EXTENDED_DISRUPTION_THRESHOLD_MIN


def split_typical_and_disruptions(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separate "a bus/train was late" records from "the route was on a
    multi-hour diversion or major incident" records.

    Returns (typical, disruptions). See config.py for why this split
    exists — mixing them badly skews any average/worst-delay metric.
    """
    is_disruption = df["code"].isin(DIVERSION_CODES) | (
        df["min_delay"] > EXTENDED_DISRUPTION_THRESHOLD_MIN
    )
    return df[~is_disruption], df[is_disruption]
