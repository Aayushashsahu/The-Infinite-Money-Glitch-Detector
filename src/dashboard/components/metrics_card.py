"""Reusable KPI Metric Cards for Phase 5 Dashboard.

Provides high-contrast institutional KPI cards supporting:
- Standard values and deltas
- Tooltips and explanations
- Explicit UNAVAILABLE states (e.g. for out-of-sample portfolio holdout)
"""

from __future__ import annotations

from typing import Optional, Union
import streamlit as st


def render_metric_card(
    label: str,
    value: Union[str, float, int],
    delta: Optional[Union[str, float, int]] = None,
    delta_color: str = "normal",
    help_text: Optional[str] = None,
    is_unavailable: bool = False,
    unavailable_reason: Optional[str] = None,
) -> None:
    """Render a styled KPI metric card with error/unavailable state handling.

    Args:
        label: Metric title / display name.
        value: Numeric or formatted string value.
        delta: Optional change or excess return indicator.
        delta_color: "normal" (green up / red down), "inverse" (red up / green down), or "off".
        help_text: Explanatory tooltip.
        is_unavailable: If True, renders an explicit UNAVAILABLE indicator.
        unavailable_reason: Tooltip or subtext explaining unavailability.
    """
    if is_unavailable:
        st.metric(
            label=label,
            value="UNAVAILABLE",
            delta="N/A",
            delta_color="off",
            help=unavailable_reason or "Metric unavailable in authoritative research baseline.",
        )
    else:
        st.metric(
            label=label,
            value=value,
            delta=delta,
            delta_color=delta_color,
            help=help_text,
        )


def format_currency(val: Optional[float], currency: str = "€", decimals: int = 2) -> str:
    if val is None:
        return "N/A"
    sign = "-" if val < 0 else ("+" if val > 0 else "")
    formatted = f"{abs(val):,.{decimals}f}"
    return f"{sign}{currency}{formatted}"


def format_percent(val: Optional[float], decimals: int = 2, show_sign: bool = True) -> str:
    """Format decimal percentage (e.g. 0.0289 -> +2.89%)."""
    if val is None:
        return "N/A"
    pct = val * 100.0
    sign = ("+" if pct > 0 else "") if show_sign else ""
    return f"{sign}{pct:.{decimals}f}%"


def format_bps(val: Optional[float], decimals: int = 1) -> str:
    """Format basis points (e.g. 0.0093 -> 93.0 bps)."""
    if val is None:
        return "N/A"
    bps = val * 10000.0
    return f"{bps:+.{decimals}f} bps"
