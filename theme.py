"""
Shared visual language for both dashboard pages, so charts read as one
system instead of each page inventing its own colors.

Palette choices (light theme):
- BUS_COLOR is TTC red (the actual brand color on TTC bus livery) —
  drives every bus-specific "magnitude" chart (bar/line totals) on the
  Overview page. Sequential = one hue, light to dark (BUS_SEQUENTIAL_SCHEME).
- SUBWAY_COLOR (blue) is the other half of the bus-vs-subway comparison
  on the Commute Planner — a hue clearly distinct from TTC red, not an
  arbitrary pick.
- The combined bus+subway heatmap isn't bus-specific, so it keeps its
  own neutral sequential scale (SEQUENTIAL_SCHEME) rather than inheriting
  the bus color.
- Everything else (grid lines, axis text) is muted so the data — not
  the chrome — carries the ink.
"""
from __future__ import annotations

import altair as alt

BUS_COLOR = "#DA291C"     # TTC red (Pantone 199C) — bus routes
BUS_COLOR_DARK = "#A31D14"
SUBWAY_COLOR = "#2563EB"  # blue — subway leg / second series in comparisons
MUTED_GRID = "#E5E7EB"
MUTED_TEXT = "#6B7280"
INK = "#111827"

# Backwards-compatible aliases (ACCENT == bus color, used generically).
ACCENT = BUS_COLOR
ACCENT_DARK = BUS_COLOR_DARK

SEQUENTIAL_SCHEME = "blues"          # generic/combined magnitude (not bus-specific)
BUS_SEQUENTIAL_SCHEME = "reds"       # bus-specific magnitude charts
CATEGORICAL_RANGE = [BUS_COLOR, SUBWAY_COLOR]  # bus vs. subway, in that order

BASE_FONT = "Inter, -apple-system, BlinkMacSystemFont, sans-serif"


def apply_altair_theme() -> None:
    """Registers and activates a shared Altair theme. Call once per page."""

    def _theme():
        return {
            "config": {
                "background": "transparent",
                "font": BASE_FONT,
                "title": {"font": BASE_FONT, "fontSize": 14, "fontWeight": 600, "color": INK},
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
        background-color: rgba(0, 0, 0, 0.02);
        border: 1px solid rgba(0, 0, 0, 0.08);
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
