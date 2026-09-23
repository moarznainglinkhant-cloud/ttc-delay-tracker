"""
Shared visual language for both dashboard pages, so charts read as one
system instead of each page inventing its own colors.

Palette choices:
- ACCENT (single hue, blue) drives every "magnitude" chart (bar/line
  totals, sequential heatmap) — sequential = one hue, light to dark.
- Two-series comparisons (bus vs. subway) use ACCENT paired with a
  warm, unrelated hue (WARM) so they're distinguishable without relying
  on a rainbow of unrelated colors.
- Everything else (grid lines, axis text) is muted so the data — not
  the chrome — carries the ink.
"""
from __future__ import annotations

import altair as alt

ACCENT = "#3B82F6"       # blue — primary series / sequential magnitude
ACCENT_DARK = "#1D4ED8"
WARM = "#F59E0B"          # amber — the "second thing" in a two-way comparison
MUTED_GRID = "#2A2E3A"
MUTED_TEXT = "#9AA4B2"

SEQUENTIAL_SCHEME = "blues"     # for Altair scale(scheme=...)
CATEGORICAL_RANGE = [ACCENT, WARM]

BASE_FONT = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"


def apply_altair_theme() -> None:
    """Registers and activates a shared Altair theme. Call once per page."""

    def _theme():
        return {
            "config": {
                "background": "transparent",
                "font": BASE_FONT,
                "title": {"font": BASE_FONT, "fontSize": 14, "fontWeight": 600, "color": "#E6E9EF"},
                "axis": {
                    "labelFont": BASE_FONT,
                    "titleFont": BASE_FONT,
                    "labelColor": MUTED_TEXT,
                    "titleColor": MUTED_TEXT,
                    "gridColor": MUTED_GRID,
                    "domainColor": MUTED_GRID,
                    "tickColor": MUTED_GRID,
                    "labelFontSize": 11,
                    "titleFontSize": 12,
                    "titleFontWeight": 500,
                },
                "legend": {
                    "labelFont": BASE_FONT,
                    "titleFont": BASE_FONT,
                    "labelColor": MUTED_TEXT,
                    "titleColor": MUTED_TEXT,
                    "labelFontSize": 11,
                },
                "view": {"stroke": "transparent"},
                "range": {"category": CATEGORICAL_RANGE},
            }
        }

    alt.themes.register("ttc_shared", _theme)
    alt.themes.enable("ttc_shared")


def inject_page_css() -> str:
    """Small, targeted CSS tweaks Streamlit's theme config can't reach."""
    return """
    <style>
    /* Tighter top padding so the title isn't floating in dead space */
    .block-container { padding-top: 2rem; padding-bottom: 3rem; }

    /* Metric cards: subtle bordered surface instead of bare numbers */
    div[data-testid="stMetric"] {
        background-color: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
        padding: 14px 16px 10px 16px;
    }
    div[data-testid="stMetricLabel"] { font-size: 0.8rem; opacity: 0.75; }

    /* Section headers get breathing room without a full divider every time */
    h3 { margin-top: 1.6rem; }

    /* Sidebar section spacing */
    section[data-testid="stSidebar"] .block-container { padding-top: 1.5rem; }
    </style>
    """
