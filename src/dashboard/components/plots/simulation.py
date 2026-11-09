"""Simulation visualization components for Phase 5 Dashboard.

Builds institutional charts for Monte Carlo representative paths, convergence diagnostics,
and model comparison metrics.
"""

from __future__ import annotations

from typing import Any, Dict, List
import plotly.graph_objects as go

from dashboard.artifacts.schemas import ModelComparisonItemSchema
from dashboard.components.metrics_card import format_percent
from dashboard.components.plots.base import PALETTE, apply_institutional_theme


def build_representative_paths_figure(
    paths: Dict[str, Any],
    model_name: str,
    height: int = 440,
) -> go.Figure:
    """Build a Plotly line chart displaying worst, median, and best simulated paths.

    Args:
        paths: Dict containing 'worst', 'median', and 'best' representative path dicts.
        model_name: Name of the simulation model.
        height: Figure height in pixels.

    Returns:
        Plotly Figure.
    """
    fig = go.Figure()

    path_configs = [
        ("best", "Best Realization (Top 1%)", PALETTE["profit"], "solid"),
        ("median", "Median Path (50th Percentile)", PALETTE["primary"], "solid"),
        ("worst", "Worst Realization (Bottom 1%)", PALETTE["loss"], "solid"),
    ]

    for key, label, color, dash in path_configs:
        if key in paths and paths[key]:
            p = paths[key]
            dates = p.get("dates") or list(range(len(p.get("fx_rates", []))))
            rates = p.get("fx_rates", [])
            if rates:
                fig.add_trace(
                    go.Scatter(
                        x=dates,
                        y=rates,
                        mode="lines",
                        name=label,
                        line=dict(color=color, width=1.8, dash=dash),
                        hovertemplate=f"<b>{label}</b><br>Step: %{{x}}<br>Rate: %{{y:.4f}}<extra></extra>",
                    )
                )

    apply_institutional_theme(
        fig,
        title=f"Representative Simulated Paths: {model_name} (N=253 Steps)",
        x_title="Simulation Date / Trading Step",
        y_title="Simulated Exchange Rate (EUR/USD)",
        height=height,
        show_legend=True,
    )
    return fig


def build_convergence_figure(
    checkpoints: List[Dict[str, Any]],
    height: int = 400,
) -> go.Figure:
    """Build a Plotly chart showing convergence of risk & return metrics across sample sizes.

    Args:
        checkpoints: List of checkpoint dicts from convergence_report.json.
        height: Figure height in pixels.

    Returns:
        Plotly Figure.
    """
    sample_sizes = [cp.get("sample_size", 0) for cp in checkpoints]
    mean_returns = [cp.get("mean_return", 0.0) * 100.0 for cp in checkpoints]
    median_returns = [cp.get("median_return", 0.0) * 100.0 for cp in checkpoints]
    cvar_95 = [cp.get("cvar_95", 0.0) * 100.0 for cp in checkpoints]

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=sample_sizes,
            y=mean_returns,
            mode="lines+markers",
            name="Mean Return (%)",
            line=dict(color=PALETTE["primary"], width=2),
            marker=dict(size=6),
            hovertemplate="Sample Size: %{x}<br>Mean Return: %{y:.2f}%<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=sample_sizes,
            y=median_returns,
            mode="lines+markers",
            name="Median Return (%)",
            line=dict(color="#0284c7", width=2, dash="dash"),
            marker=dict(size=6),
            hovertemplate="Sample Size: %{x}<br>Median Return: %{y:.2f}%<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=sample_sizes,
            y=cvar_95,
            mode="lines+markers",
            name="95% CVaR Tail Loss (%)",
            line=dict(color=PALETTE["loss"], width=2),
            marker=dict(size=6),
            hovertemplate="Sample Size: %{x}<br>95% CVaR: %{y:.2f}%<extra></extra>",
        )
    )

    apply_institutional_theme(
        fig,
        title="Monte Carlo Asymptotic Convergence Across Sample Sizes (N=25 to 1,000)",
        x_title="Number of Simulated Paths (N)",
        y_title="Metric Value (%)",
        height=height,
        show_legend=True,
    )
    return fig


def build_model_metrics_bar_figure(
    models: List[ModelComparisonItemSchema],
    metric_key: str,
    metric_label: str,
    height: int = 380,
) -> go.Figure:
    """Build a bar chart comparing all 6 models on a single risk or return metric.

    Args:
        models: List of model comparison items.
        metric_key: Attribute name on ModelComparisonItemSchema.
        metric_label: Human-readable metric title.
        height: Figure height in pixels.

    Returns:
        Plotly Figure.
    """
    model_names = [m.model_name for m in models]
    values = [getattr(m, metric_key) * 100.0 for m in models]
    text_labels = [format_percent(v / 100.0) for v in values]

    colors = [PALETTE["loss"] if v < 0 else PALETTE["primary"] for v in values]

    fig = go.Figure(
        go.Bar(
            x=model_names,
            y=values,
            text=text_labels,
            textposition="outside",
            marker=dict(color=colors),
            hovertemplate="<b>%{x}</b><br>Value: %{y:.2f}%<extra></extra>",
        )
    )

    apply_institutional_theme(
        fig,
        title=f"Comparative Cross-Model Audit: {metric_label}",
        x_title="Simulation Model",
        y_title=f"{metric_label} (%)",
        height=height,
        show_legend=False,
    )
    return fig
