"""Holdout diagnostics visual components for Phase 5 Dashboard.

Builds institutional charts comparing 2024 out-of-sample realized outcomes against
calibration distributions and correlation shift diagnostics.
"""

from __future__ import annotations

from typing import Dict
import plotly.graph_objects as go

from dashboard.components.metrics_card import format_percent
from dashboard.components.plots.base import PALETTE, apply_institutional_theme


def build_holdout_factor_fan_figure(
    sim_p025: float,
    sim_median: float,
    sim_p975: float,
    realized_return: float,
    height: int = 360,
) -> go.Figure:
    """Build a comparison chart of 2024 realized FX return vs. simulated predictive bounds.

    Args:
        sim_p025: 2.5th percentile of simulated predictive returns.
        sim_median: 50th percentile (median) of simulated predictive returns.
        sim_p975: 97.5th percentile of simulated predictive returns.
        realized_return: Actual 2024 realized FX cumulative return.
        height: Figure height in pixels.

    Returns:
        Plotly Figure.
    """
    categories = [
        "Simulated 2.5th Pct (p02.5)",
        "Simulated Median (p50)",
        "Simulated 97.5th Pct (p97.5)",
        "2024 Realized Outcome",
    ]
    values = [sim_p025 * 100.0, sim_median * 100.0, sim_p975 * 100.0, realized_return * 100.0]
    colors = [
        PALETTE["loss"],
        PALETTE["primary"],
        PALETTE["profit"],
        "#d97706",  # Amber for realized out-of-sample observation
    ]
    texts = [format_percent(v / 100.0) for v in values]

    fig = go.Figure(
        go.Bar(
            x=categories,
            y=values,
            text=texts,
            textposition="outside",
            marker=dict(color=colors),
            hovertemplate="<b>%{x}</b><br>Return: %{y:.2f}%<extra></extra>",
        )
    )

    apply_institutional_theme(
        fig,
        title="2024 Predictive Distribution Coverage: Realized vs. Simulated Bounds",
        x_title="Outcome / Predictive Quantile",
        y_title="Cumulative Return (%)",
        height=height,
        show_legend=False,
    )
    return fig


def build_correlation_shifts_figure(
    shifts: Dict[str, float],
    height: int = 400,
) -> go.Figure:
    """Build a horizontal bar chart displaying factor pairwise correlation shifts.

    Args:
        shifts: Dict mapping 'FactorA__vs__FactorB' to correlation shift float.
        height: Figure height in pixels.

    Returns:
        Plotly Figure.
    """
    clean_labels = [k.replace("__vs__", " vs\n") for k in shifts.keys()]
    values = list(shifts.values())
    colors = [PALETTE["loss"] if v < 0 else PALETTE["primary"] for v in values]

    fig = go.Figure(
        go.Bar(
            y=clean_labels,
            x=values,
            orientation="h",
            text=[f"{v:+.4f}" for v in values],
            textposition="outside",
            marker=dict(color=colors),
            hovertemplate="<b>%{y}</b><br>Correlation Shift: %{x:+.4f}<extra></extra>",
        )
    )

    apply_institutional_theme(
        fig,
        title="Empirical Correlation Shifts: 2024 Holdout vs. 2020-2023 Calibration",
        x_title="Correlation Difference (Holdout - Calibration)",
        y_title="Factor Pair",
        height=height,
        show_legend=False,
    )
    fig.update_layout(margin=dict(l=220, r=40, t=50, b=40))
    return fig
