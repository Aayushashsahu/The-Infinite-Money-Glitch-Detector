"""Time-series visualization component for Phase 5 Dashboard.

Renders economic and market observations from the research database using the
institutional styling theme.
"""

from __future__ import annotations

from typing import Optional
import pandas as pd
import plotly.graph_objects as go

from dashboard.components.plots.base import PALETTE, apply_institutional_theme


def build_time_series_figure(
    df: pd.DataFrame,
    date_col: str,
    value_col: str,
    title: str,
    y_title: str,
    height: int = 400,
    line_color: Optional[str] = None,
) -> go.Figure:
    """Build a Plotly line chart for historical economic time series.

    Args:
        df: DataFrame containing date and value columns.
        date_col: Name of the date column.
        value_col: Name of the value column.
        title: Chart title.
        y_title: Y-axis title.
        height: Figure height in pixels.
        line_color: Optional line color hex code.

    Returns:
        Plotly Figure.
    """
    color = line_color or PALETTE["primary"]
    fig = go.Figure()

    if not df.empty and date_col in df.columns and value_col in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df[date_col],
                y=df[value_col],
                mode="lines",
                name=title,
                line=dict(color=color, width=1.5),
                hovertemplate="<b>Date:</b> %{x}<br><b>Value:</b> %{y:,.4f}<extra></extra>",
            )
        )

    apply_institutional_theme(
        fig,
        title=title,
        x_title="Date",
        y_title=y_title,
        height=height,
        show_legend=False,
    )
    return fig
