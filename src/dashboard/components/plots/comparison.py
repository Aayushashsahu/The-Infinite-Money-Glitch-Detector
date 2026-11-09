"""Comparative Visualizations for Phase 5 Dashboard.

Builds institutional charts comparing historical strategy performance against
cash benchmarks and Monte Carlo distribution models.
"""

from __future__ import annotations

from typing import List
import plotly.graph_objects as go

from dashboard.artifacts.schemas import ModelComparisonItemSchema
from dashboard.components.metrics_card import format_percent
from dashboard.components.plots.base import PALETTE, apply_institutional_theme


def build_benchmark_comparison_figure(
    strategy_return: float,
    benchmark_return: float,
    alpha: float,
    height: int = 380,
) -> go.Figure:
    """Build a bar chart comparing 5-year strategy return against EUR cash deposit benchmark."""
    categories = [
        "Carry Trade Strategy (5-Yr Net)",
        "EUR Fixed Deposit Benchmark",
        "Annualized Strategy Alpha",
    ]
    values = [strategy_return * 100.0, benchmark_return * 100.0, alpha * 100.0]
    colors = [
        PALETTE["primary"],
        PALETTE["benchmark"],
        PALETTE["loss"] if alpha < 0 else PALETTE["profit"],
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
        title="Historical Cumulative Return vs EUR Cash Benchmark",
        x_title=None,
        y_title="Return (%)",
        height=height,
        show_legend=False,
    )
    return fig


def build_model_comparison_figure(
    models: List[ModelComparisonItemSchema],
    height: int = 420,
) -> go.Figure:
    """Build a grouped bar chart comparing median return and 95% CVaR across distribution models."""
    names = [m.model_name for m in models]
    median_returns = [m.median_return * 100.0 for m in models]
    cvar_95 = [m.cvar_95 * 100.0 for m in models]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Median Simulated Return (%)",
            x=names,
            y=median_returns,
            text=[f"{v:+.2f}%" for v in median_returns],
            textposition="outside",
            marker=dict(color=PALETTE["primary"]),
        )
    )
    fig.add_trace(
        go.Bar(
            name="95% CVaR Tail Loss (%)",
            x=names,
            y=cvar_95,
            text=[f"{v:.2f}%" for v in cvar_95],
            textposition="outside",
            marker=dict(color=PALETTE["loss"]),
        )
    )

    apply_institutional_theme(
        fig,
        title="Monte Carlo Risk-Return Profile Across 6 Distribution Models (N=1,000 paths)",
        x_title="Stochastic Model",
        y_title="Return / Risk Metric (%)",
        height=height,
        show_legend=True,
    )
    fig.update_layout(barmode="group")
    return fig
