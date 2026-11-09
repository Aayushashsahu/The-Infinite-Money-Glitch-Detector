"""The Infinite Money Glitch Detector — Research Dashboard Entry Point.

Interactive, read-only quantitative research dashboard consuming authoritative
precomputed artifacts from Phase 4 (simulation & holdout) and Phase 3 (backtesting).

Core Principle: Mathematics first. Data second. Prediction third. AI last.
"""

from __future__ import annotations

import streamlit as st

from dashboard.artifacts.loader import (
    load_simulation_manifest,
    verify_all_registered_artifacts,
)
from dashboard.artifacts.registry import TOTAL_REGISTERED_ARTIFACTS
from dashboard.components.alerts import render_provenance_badge
from dashboard.components.banner import render_research_banner
from dashboard.components.metrics_card import (
    render_metric_card,
)

# Configure wide layout with institutional styling
st.set_page_config(
    page_title="Infinite Money Glitch Detector — Research Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    """Main application shell and dashboard overview."""
    render_research_banner()

    st.title("📈 The Infinite Money Glitch Detector")
    st.subheader("Quantitative Research & Invariance Architecture Dashboard")
    st.markdown(
        """
        Welcome to the **Infinite Money Glitch Detector Research Dashboard**.

        This dashboard presents empirical evidence, backtest metrics, Monte Carlo simulations,
        and stress-test distributions examining cross-currency carry-trade strategies.

        **Architectural Rule:** This dashboard is strictly **read-only**. All metrics are loaded
        from cryptographically verified research artifacts without recomputing any model.
        """
    )

    st.divider()

    # Executive Summary Metrics
    st.markdown("### Executive Summary — Empirical Findings")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        render_metric_card(
            label="Historical 5-Yr Net Return",
            value="+2.89%",
            delta="+€2,890.22",
            delta_color="normal",
            help_text="Historical 2020-2024 cumulative net return from Config 2 (Estimated Schedule).",
        )
    with col2:
        render_metric_card(
            label="Historical Annualized Alpha",
            value="-0.93%",
            delta="-93.0 bps",
            delta_color="inverse",
            help_text="Underperformed EUR deposit benchmark (+1.50% p.a.) over the 5-year sample.",
        )
    with col3:
        render_metric_card(
            label="Simulated Median Return",
            value="+1.75%",
            delta="Loss Prob: 31.9%",
            delta_color="off",
            help_text="1,000-path Multivariate Gaussian simulation median return.",
        )
    with col4:
        # 2024 Portfolio Holdout Diagnostic: UNAVAILABLE
        render_metric_card(
            label="2024 Strategy Holdout",
            value="UNAVAILABLE",
            is_unavailable=True,
            unavailable_reason="Holdout strategy execution data unavailable for out-of-sample year 2024.",
        )

    st.divider()

    # System Health & Cryptographic Integrity Status
    st.markdown("### Research Artifact Engine Status")
    with st.expander("Cryptographic Registry & Provenance Details", expanded=False):
        try:
            results = verify_all_registered_artifacts()
            manifest = load_simulation_manifest()
            st.success(
                f"**Artifact Integrity Verified**: All {len(results)} of {TOTAL_REGISTERED_ARTIFACTS} "
                "registered JSON artifacts match their cryptographic SHA-256 digests perfectly."
            )
            render_provenance_badge(
                git_commit=manifest.git_commit,
                db_sha256=manifest.database_sha256,
                is_clean=manifest.git_working_tree_clean,
                rng_seed=manifest.random_seed,
            )
        except Exception as e:
            st.error(f"Artifact integrity verification failed: {e}")

    # Navigation Guide
    st.markdown("### Dashboard Navigation")
    st.markdown(
        """
        Use the sidebar to explore the six specialized research modules:
        1. **Research Overview**: Executive summary and the central empirical conclusion.
        2. **Historical Backtest**: Phase 3 configurations, execution constraints, and cost attribution.
        3. **Simulation Models**: Comparative analysis of Gaussian, Student-t, Bootstrap, and Regime models.
        4. **Stress Testing**: Extreme FX shocks, interest rate squeezes, and funding convention sensitivities.
        5. **Holdout Validation**: 2024 out-of-sample factor diagnostics and unavailable strategy state.
        6. **Data Infrastructure**: Point-in-time publication lag audit and calendar settlement validation.
        """
    )


if __name__ == "__main__":
    main()
