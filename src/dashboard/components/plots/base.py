"""Plotly Institutional Visual Engine for Phase 5 Dashboard.

Defines the authoritative `glitch_institutional` theme, color palettes, and
layout builders for financial time-series, probability distributions, convergence
diagnostics, and stress test visual charts.
"""

from __future__ import annotations

from typing import Optional
import plotly.graph_objects as go

# Authoritative Color Palette Hierarchy from Architecture Specification
PALETTE = {
    "primary": "#1e3a8a",  # Institutional Navy (Base Equity / Main Series)
    "benchmark": "#64748b",  # Neutral Slate (Cash / Deposit Rate Benchmark)
    "profit": "#15803d",  # Forest Green (Positive Return / Gains)
    "loss": "#b91c1c",  # Crimson Red (Negative Return / Drawdown / Losses)
    "stress": "#6b21a8",  # Deep Purple (Stressed Scenarios)
    "confidence_fill": "rgba(147, 197, 253, 0.35)",  # Soft Blue Alpha 0.35
    "confidence_line": "#3b82f6",  # Slate Blue 500
    "background_plot": "#ffffff",  # Crisp White Plot Canvas
    "background_paper": "#ffffff",  # Clean Paper Canvas
    "grid": "#e2e8f0",  # Light Slate Gridlines (0.8px)
    "zero_line": "#94a3b8",  # Slate 400 Zero Line
    "text": "#0f172a",  # Slate 900 Text
    "subtext": "#475569",  # Slate 600 Subtext
}

# Distinct model colors for comparative plots
MODEL_COLORS = {
    "gaussian": "#1e3a8a",  # Navy
    "student_t": "#0284c7",  # Sky Blue
    "regime": "#7c3aed",  # Violet
    "bootstrap": "#059669",  # Emerald
    "baseline": "#475569",  # Slate
    "stressed": "#dc2626",  # Red
}

FONT_FAMILY = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
MONOSPACE_FONT = "Consolas, Monaco, 'Courier New', monospace"


def apply_institutional_theme(
    fig: go.Figure,
    title: Optional[str] = None,
    x_title: Optional[str] = None,
    y_title: Optional[str] = None,
    height: int = 450,
    show_legend: bool = True,
) -> go.Figure:
    """Apply the authoritative institutional layout theme to a Plotly figure.

    Args:
        fig: Plotly Figure instance.
        title: Plot title.
        x_title: X-axis title.
        y_title: Y-axis title.
        height: Figure height in pixels (default: 450).
        show_legend: Toggle legend visibility.

    Returns:
        The formatted go.Figure instance.
    """
    fig.update_layout(
        template="plotly_white",
        title=dict(
            text=f"<b>{title}</b>" if title else None,
            font=dict(family=FONT_FAMILY, size=16, color=PALETTE["text"]),
            x=0.01,
            xanchor="left",
        ),
        font=dict(family=FONT_FAMILY, size=12, color=PALETTE["text"]),
        paper_bgcolor=PALETTE["background_paper"],
        plot_bgcolor=PALETTE["background_plot"],
        height=height,
        margin=dict(l=50, r=30, t=50, b=40),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1.0,
            font=dict(family=FONT_FAMILY, size=11),
        )
        if show_legend
        else dict(visible=False),
        xaxis=dict(
            title=dict(text=x_title, font=dict(family=FONT_FAMILY, size=12)) if x_title else None,
            showgrid=True,
            gridcolor=PALETTE["grid"],
            gridwidth=0.8,
            zeroline=True,
            zerolinecolor=PALETTE["zero_line"],
            zerolinewidth=1.0,
            tickfont=dict(family=MONOSPACE_FONT, size=10),
        ),
        yaxis=dict(
            title=dict(text=y_title, font=dict(family=FONT_FAMILY, size=12)) if y_title else None,
            showgrid=True,
            gridcolor=PALETTE["grid"],
            gridwidth=0.8,
            zeroline=True,
            zerolinecolor=PALETTE["zero_line"],
            zerolinewidth=1.0,
            tickfont=dict(family=MONOSPACE_FONT, size=10),
        ),
    )
    return fig


def create_empty_figure(message: str = "No data available") -> go.Figure:
    """Create a minimal empty figure with an explanatory text annotation."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(family=FONT_FAMILY, size=14, color=PALETTE["subtext"]),
    )
    apply_institutional_theme(fig, height=300, show_legend=False)
    return fig
