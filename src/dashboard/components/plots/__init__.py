"""Plotly Institutional Visualization Module for Phase 5 Dashboard."""

from dashboard.components.plots.base import (
    FONT_FAMILY,
    MONOSPACE_FONT,
    MODEL_COLORS,
    PALETTE,
    apply_institutional_theme,
    create_empty_figure,
)
from dashboard.components.plots.comparison import (
    build_benchmark_comparison_figure,
    build_model_comparison_figure,
)
from dashboard.components.plots.waterfall import (
    build_attribution_waterfall_figure,
)

__all__ = [
    "FONT_FAMILY",
    "MONOSPACE_FONT",
    "MODEL_COLORS",
    "PALETTE",
    "apply_institutional_theme",
    "create_empty_figure",
    "build_attribution_waterfall_figure",
    "build_benchmark_comparison_figure",
    "build_model_comparison_figure",
]
