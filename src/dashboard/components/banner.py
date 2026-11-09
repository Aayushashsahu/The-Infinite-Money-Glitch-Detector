"""Research Disclaimer & Classification Banners for Phase 5 Dashboard.

Renders persistent, standardized research banners across all dashboard pages,
enforcing clear academic and empirical research classifications:
- SIMULATED_RESEARCH_PROXY
- ESTIMATED_LAG
- Single Source of Truth
- Numerical Parity <= 10^-9
"""

from __future__ import annotations

from typing import Optional
import streamlit as st


def render_research_banner(
    data_classification: str = "SIMULATED_RESEARCH_PROXY",
    pit_mode: str = "ESTIMATED_LAG",
    extra_notice: Optional[str] = None,
) -> None:
    """Render the persistent global research disclaimer banner at page top.

    Args:
        data_classification: Data provenance label (default: SIMULATED_RESEARCH_PROXY).
        pit_mode: Point-in-time publication lag policy (default: ESTIMATED_LAG).
        extra_notice: Optional page-specific notice or warning text.
    """
    banner_markdown = f"""
> **RESEARCH PLATFORM ONLY — NOT AN EXECUTABLE STRATEGY**
> **Data Classification:** `{data_classification}` | **PIT Mode:** `{pit_mode}`
> **Single Source of Truth:** Authoritative Phase 4.1.2.2.3 & 3.2.2.3.3 Baselines | **Numerical Parity:** $\\le 10^{{-9}}$
"""
    st.markdown(banner_markdown)
    if extra_notice:
        st.info(extra_notice)


def render_holdout_unavailable_banner(
    reason: str = "Holdout strategy execution data unavailable for out-of-sample year 2024.",
) -> None:
    """Render an explicit warning banner when portfolio holdout data is unavailable."""
    st.warning(
        f"**OUT-OF-SAMPLE HOLDOUT STATUS: UNAVAILABLE**\n\n"
        f"{reason}\n\n"
        "No simulated portfolio metrics are available for the 2024 holdout period."
    )
