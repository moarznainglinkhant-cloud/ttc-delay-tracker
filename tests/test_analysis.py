"""
Tests for analysis.py — the typical-delay vs. extended-disruption split.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis import split_typical_and_disruptions  # noqa: E402
from config import EXTENDED_DISRUPTION_THRESHOLD_MIN  # noqa: E402


def _row(**overrides):
    base = {"code": "MFUS", "min_delay": 10}
    base.update(overrides)
    return base


def test_typical_delay_is_not_flagged():
    df = pd.DataFrame([_row(min_delay=5), _row(min_delay=45)])
    typical, disruptions = split_typical_and_disruptions(df)
    assert len(typical) == 2
    assert len(disruptions) == 0


def test_diversion_code_is_flagged_regardless_of_duration():
    # Even a short-looking MFDV record is flagged, since the code itself
    # means "route was on diversion," not "a bus was late."
    df = pd.DataFrame([_row(code="MFDV", min_delay=15)])
    typical, disruptions = split_typical_and_disruptions(df)
    assert len(typical) == 0
    assert len(disruptions) == 1


def test_extreme_duration_is_flagged_even_with_other_code():
    df = pd.DataFrame([_row(code="MFUS", min_delay=EXTENDED_DISRUPTION_THRESHOLD_MIN + 1)])
    typical, disruptions = split_typical_and_disruptions(df)
    assert len(typical) == 0
    assert len(disruptions) == 1


def test_boundary_value_is_not_flagged():
    df = pd.DataFrame([_row(code="MFUS", min_delay=EXTENDED_DISRUPTION_THRESHOLD_MIN)])
    typical, disruptions = split_typical_and_disruptions(df)
    assert len(typical) == 1
    assert len(disruptions) == 0


def test_real_world_example_regression():
    """The actual outlier that prompted this: a 997-minute MFDV record."""
    df = pd.DataFrame(
        [
            _row(code="MFDV", min_delay=997),
            _row(code="MFUS", min_delay=8),
            _row(code="MFESA", min_delay=3),
        ]
    )
    typical, disruptions = split_typical_and_disruptions(df)
    assert len(typical) == 2
    assert typical["min_delay"].max() == 8
    assert len(disruptions) == 1
    assert disruptions.iloc[0]["min_delay"] == 997
