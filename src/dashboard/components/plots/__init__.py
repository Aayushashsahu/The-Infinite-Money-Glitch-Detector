"""Plotly Institutional Visualization Module for Phase 5 Dashboard."""

from dashboard.components.plots.base import (
    FONT_FAMILY,
    MODEL_COLORS,
    MONOSPACE_FONT,
    PALETTE,
    apply_institutional_theme,
    create_empty_figure,
)
from dashboard.components.plots.comparison import (
    build_benchmark_comparison_figure,
    build_model_comparison_figure,
)
from dashboard.components.plots.holdout import (
    build_correlation_shifts_figure,
    build_holdout_factor_fan_figure,
)
from dashboard.components.plots.series import (
    build_time_series_figure,
)
from dashboard.components.plots.simulation import (
    build_convergence_figure,
    build_model_metrics_bar_figure,
    build_representative_paths_figure,
)
from dashboard.components.plots.stress import (
    build_correlation_matrix_figure,
    build_funding_sensitivity_figure,
    build_stress_tornado_figure,
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
    "build_time_series_figure",
    "build_representative_paths_figure",
    "build_convergence_figure",
    "build_model_metrics_bar_figure",
    "build_stress_tornado_figure",
    "build_funding_sensitivity_figure",
    "build_correlation_matrix_figure",
    "build_holdout_factor_fan_figure",
    "build_correlation_shifts_figure",
]
