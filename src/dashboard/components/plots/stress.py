"""Stress testing and sensitivity visual components for Phase 5 Dashboard.

Builds institutional charts for stress scenarios (tornado/ranked impact), funding sensitivity,
and factor correlation heatmaps.
"""

from __future__ import annotations

from typing import List
import plotly.graph_objects as go

from dashboard.artifacts.schemas import FundingSensitivitySchema, StressScenarioItemSchema
from dashboard.components.metrics_card import format_percent
from dashboard.components.plots.base import PALETTE, apply_institutional_theme


def build_stress_tornado_figure(
    scenarios: List[StressScenarioItemSchema],
    height: int = 560,
) -> go.Figure:
    """Build a ranked horizontal bar chart of the 19 stress scenarios sorted by total return.

    Args:
        scenarios: List of 19 StressScenarioItemSchema instances.
        height: Figure height in pixels.

    Returns:
        Plotly Figure.
    """
    # Sort scenarios from lowest return to highest return
    sorted_scenarios = sorted(scenarios, key=lambda s: s.total_return)
    names = [s.scenario_name for s in sorted_scenarios]
    returns_pct = [s.total_return * 100.0 for s in sorted_scenarios]
    text_labels = [format_percent(s.total_return) for s in sorted_scenarios]

    colors = []
    for s in sorted_scenarios:
        if s.category == "baseline":
            colors.append(PALETTE["primary"])
        elif s.total_return < 0:
            colors.append(PALETTE["loss"])
        else:
            colors.append(PALETTE["profit"])

    fig = go.Figure(
        go.Bar(
            y=names,
            x=returns_pct,
            orientation="h",
            text=text_labels,
            textposition="outside",
            marker=dict(color=colors),
            hovertemplate="<b>%{y}</b><br>Total Return: %{x:.2f}%<extra></extra>",
        )
    )

    apply_institutional_theme(
        fig,
        title="Deterministic Stress Scenario Impact: Ranked 5-Year Net Return",
        x_title="Strategy Total Return (%)",
        y_title="Stress Scenario",
        height=height,
        show_legend=False,
    )
    fig.update_layout(margin=dict(l=220, r=40, t=50, b=40))
    return fig


def build_funding_sensitivity_figure(
    funding: FundingSensitivitySchema,
    height: int = 400,
) -> go.Figure:
    """Build a grouped bar chart comparing fixed vs. floating funding under borrowing shocks.

    Args:
        funding: FundingSensitivitySchema instance.
        height: Figure height in pixels.

    Returns:
        Plotly Figure.
    """
    shock_labels = [f"+{s.shock_bps} bps" if s.shock_bps > 0 else "Baseline (0 bps)" for s in funding.scenarios]
    fixed_returns = [s.fixed_total_return * 100.0 for s in funding.scenarios]
    floating_returns = [s.floating_total_return * 100.0 for s in funding.scenarios]

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=shock_labels,
            y=fixed_returns,
            name="Fixed-Rate Term Funding",
            marker=dict(color=PALETTE["primary"]),
            text=[format_percent(r / 100.0) for r in fixed_returns],
            textposition="outside",
            hovertemplate="<b>Fixed Funding</b><br>Shock: %{x}<br>Return: %{y:.3f}%<extra></extra>",
        )
    )

    fig.add_trace(
        go.Bar(
            x=shock_labels,
            y=floating_returns,
            name="Floating Daily-Reset Funding",
            marker=dict(color="#f59e0b"),
            text=[format_percent(r / 100.0) for r in floating_returns],
            textposition="outside",
            hovertemplate="<b>Floating Funding</b><br>Shock: %{x}<br>Return: %{y:.3f}%<extra></extra>",
        )
    )

    apply_institutional_theme(
        fig,
        title="Funding Convention Sensitivity: Fixed vs. Floating Rate Reset",
        x_title="Borrowing Rate Shock",
        y_title="Total Strategy Return (%)",
        height=height,
        show_legend=True,
    )
    return fig


def build_correlation_matrix_figure(
    matrix: List[List[float]],
    labels: List[str],
    title: str,
    height: int = 400,
) -> go.Figure:
    """Build a heatmap visualizing a factor correlation matrix.

    Args:
        matrix: 2D list of correlation coefficients.
        labels: List of factor names.
        title: Chart title.
        height: Figure height in pixels.

    Returns:
        Plotly Figure.
    """
    annotations = []
    for i, row in enumerate(matrix):
        for j, val in enumerate(row):
            annotations.append(
                dict(
                    x=labels[j],
                    y=labels[i],
                    text=f"{val:.3f}",
                    font=dict(family="Consolas, monospace", size=11, color="white" if abs(val) > 0.5 else "black"),
                    showarrow=False,
                )
            )

    fig = go.Figure(
        go.Heatmap(
            z=matrix,
            x=labels,
            y=labels,
            colorscale="RdBu_r",
            zmin=-1.0,
            zmax=1.0,
            colorbar=dict(title=dict(text="Correlation", side="right")),
            hovertemplate="<b>%{y} vs %{x}</b><br>Correlation: %{z:.4f}<extra></extra>",
        )
    )

    apply_institutional_theme(
        fig,
        title=title,
        x_title=None,
        y_title=None,
        height=height,
        show_legend=False,
    )
    fig.update_layout(annotations=annotations, margin=dict(l=140, r=40, t=50, b=120))
    return fig
