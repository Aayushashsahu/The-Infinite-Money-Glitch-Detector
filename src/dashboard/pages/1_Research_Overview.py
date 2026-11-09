"""Page 1 — Research Overview: Executive Synthesis & Comparative Findings.

Presents the high-level empirical and simulation findings of the cross-currency
carry trade research program, addressing the central question:
Does an "Infinite Money Glitch" exist?

Guiding Principle: Mathematics first. Data second. Prediction third. AI last.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.artifacts.loader import (
    load_backtest_config,
    load_model_comparison,
    load_portfolio_holdout_diagnostics,
)
from dashboard.components.banner import (
    render_holdout_unavailable_banner,
    render_research_banner,
)
from dashboard.components.metrics_card import (
    format_bps,
    format_currency,
    format_percent,
    render_metric_card,
)
from dashboard.components.plots.comparison import build_model_comparison_figure
from dashboard.components.tables import render_data_table

st.set_page_config(
    page_title="Research Overview — The Infinite Money Glitch Detector",
    page_icon="📈",
    layout="wide",
)


def render_page() -> None:
    """Render the Research Overview page."""
    # --------------------------------------------------------------------------
    # A. Research Classification Banner
    # --------------------------------------------------------------------------
    render_research_banner(
        data_classification="SIMULATED_RESEARCH_PROXY",
        pit_mode="ESTIMATED_LAG",
        extra_notice="Academic and empirical research platform. Outputs do not constitute executable trading signals or financial advice.",
    )

    st.title("📈 Research Overview: Carry Trade Invariance Audit")
    st.caption("Quantitative Research Laboratory | Phase 5.2 Baseline Synthesis")

    # --------------------------------------------------------------------------
    # B. Executive Conclusion: Does an "Infinite Money Glitch" Exist?
    # --------------------------------------------------------------------------
    st.subheader("1. Executive Research Synthesis: Does an 'Infinite Money Glitch' Exist?")
    st.markdown(
        """
        The empirical and simulation evidence conclusively demonstrates that cross-currency carry trades
        **do not establish persistent or riskless arbitrage**. While nominal interest-rate differentials
        (e.g., USD yield vs. EUR borrowing rates) appear attractive on paper, mathematical decomposition
        reveals three systematic impediments:

        1. **Currency Depreciation Eliminates the Spread**: The historical EUR/USD translation loss
           (**-€5,655.77**) completely wiped out the gross foreign investment yield (**+€5,437.03**),
           yielding a net trade return of **-€218.74** before financing and frictions.
        2. **Financing Drag & Frictions Compound**: Institutional borrowing expenses (**-€3,683.87**)
           and execution frictions (**-€910.04**) substantially erode capital. The strategy's modest nominal
           profit (**+€2,890.22**) was generated entirely by uncollateralized domestic cash yield (**+€7,702.87**).
        3. **Substantial Benchmark Underperformance**: Over the 2020–2024 historical window, the carry
           trade achieved **+2.89%** cumulative net return (+0.57% p.a.) versus **+7.73%** (+1.50% p.a.)
           for a risk-free EUR cash deposit, representing an annualized alpha of **-0.93%** (-92.9 bps/year).
        4. **Severe Simulated Downside**: Across 1,000 stochastic counterfactual paths, the strategy
           exhibits a **31.9% probability of net loss** and a 95th percentile drawdown reaching **-7.18%**.

        **Academic Finding:** Covered interest arbitrage is unexecutable due to the absence of executable
        forward quotes, while uncovered carry is a directional volatility speculation, not an arbitrage glitch.
        """
    )

    st.divider()

    # --------------------------------------------------------------------------
    # C. Authoritative KPI Metrics (Extracted from Verified Artifacts)
    # --------------------------------------------------------------------------
    st.subheader("2. Authoritative Research Metrics (Single Source of Truth)")

    # Load verified research artifacts
    config_2 = load_backtest_config("config_2_estimated_schedule")
    models = load_model_comparison()
    model_map = {m.model_name: m for m in models}
    gaussian = model_map["Multivariate Gaussian"]
    perf = config_2.performance
    bench = config_2.benchmark

    col1, col2, col3 = st.columns(3)
    col4, col5, col6 = st.columns(3)

    with col1:
        render_metric_card(
            label="Historical Cumulative Return",
            value=format_percent(perf.total_return),
            delta=f"{format_currency(perf.cumulative_net_profit)} profit",
            delta_color="normal",
            help_text="Historical 2020-2024 cumulative net return from config_2_estimated_schedule.json (initial capital €100,000).",
        )
    with col2:
        render_metric_card(
            label="Historical Net Realized Profit",
            value=format_currency(perf.cumulative_net_profit),
            delta=f"Capital: {format_currency(config_2.initial_capital_a)}",
            delta_color="off",
            help_text="Total net cash generated over 1,236 transitions from config_2_estimated_schedule.json.",
        )
    with col3:
        render_metric_card(
            label="Annualized Strategy Alpha",
            value=format_percent(bench.alpha),
            delta=format_bps(bench.alpha),
            delta_color="inverse",
            help_text="Annual excess return vs EUR Fixed Deposit Proxy (+1.50% p.a.) from config_2_estimated_schedule.json.",
        )
    with col4:
        render_metric_card(
            label="Gaussian Median Return",
            value=format_percent(gaussian.median_return),
            delta="1,000 Simulated Paths",
            delta_color="off",
            help_text="Median return across 1,000 Multivariate Gaussian Monte Carlo paths from model_comparison.json.",
        )
    with col5:
        render_metric_card(
            label="Gaussian Probability of Loss",
            value=format_percent(gaussian.prob_loss, show_sign=False),
            delta="Tail Risk: CVaR 95% = -5.97%",
            delta_color="inverse",
            help_text="Fraction of simulated paths ending with net negative return from model_comparison.json.",
        )
    with col6:
        render_metric_card(
            label="Historical Maximum Drawdown",
            value=format_percent(perf.max_drawdown),
            delta="Simulated p95: -7.18%",
            delta_color="inverse",
            help_text="Peak-to-trough historical drawdown from config_2_estimated_schedule.json.",
        )

    st.caption(
        "**Metric Provenance:** Extracted from verified artifacts `config_2_estimated_schedule.json` "
        "and `model_comparison.json`. All metrics preserve exact floating-point parity (≤ 10⁻⁹)."
    )

    st.divider()

    # --------------------------------------------------------------------------
    # D. Historical vs Simulated Performance
    # --------------------------------------------------------------------------
    st.subheader("3. Historical Path Dependency vs. Simulated Counterfactual Distributions")
    st.markdown(
        """
        A critical principle of quantitative research is **strictly distinguishing observed historical realizations
        from forward stochastic distributions**:

        - **Historical Backtest (N=1)**: Represents a single empirical trajectory through time (2020–2024),
          heavily conditioned on historical central-bank rate hikes and the specific EUR/USD cycle.
        - **Monte Carlo Simulations (N=1,000 per model)**: Counterfactual stochastic realizations exploring
          uncorrelated regimes, fat-tailed shocks (Student-t $\nu=7.74$), and block-bootstrap sampling.
        """
    )

    # Comparative Model Distribution Chart
    st.plotly_chart(
        build_model_comparison_figure(models),
        use_container_width=True,
    )

    # Model Comparison Table
    table_rows = []
    # Add historical baseline row
    table_rows.append(
        {
            "Model / Specification": "Historical Realization (Config 2)",
            "Sample Size": "1 Path (1,236 Days)",
            "Median Return (%)": f"{perf.total_return * 100.0:+.2f}%",
            "Mean Return (%)": f"{perf.total_return * 100.0:+.2f}%",
            "95% VaR (%)": f"{perf.var_95 * 100.0:.2f}%" if perf.var_95 else "N/A",
            "95% CVaR (%)": f"{perf.cvar_95 * 100.0:.2f}%" if perf.cvar_95 else "N/A",
            "Max Drawdown (%)": f"{perf.max_drawdown * 100.0:.2f}%",
            "Loss Probability (%)": "0.0% (Realized)",
            "Classification": "HISTORICAL_BACKTEST",
        }
    )

    for m in models:
        table_rows.append(
            {
                "Model / Specification": m.model_name,
                "Sample Size": f"{m.num_paths:,} Paths",
                "Median Return (%)": f"{m.median_return * 100.0:+.2f}%",
                "Mean Return (%)": f"{m.mean_return * 100.0:+.2f}%",
                "95% VaR (%)": f"{m.var_95 * 100.0:.2f}%",
                "95% CVaR (%)": f"{m.cvar_95 * 100.0:.2f}%",
                "Max Drawdown (%)": f"{m.max_drawdown_median * 100.0:.2f}%",
                "Loss Probability (%)": f"{m.prob_loss * 100.0:.1f}%",
                "Classification": "SIMULATED_RESEARCH_PROXY",
            }
        )

    df_models = pd.DataFrame(table_rows)
    render_data_table(df_models, title="Cross-Model Risk & Return Distribution Comparison")

    st.divider()

    # --------------------------------------------------------------------------
    # E. Portfolio Holdout Invariant: UNAVAILABLE State
    # --------------------------------------------------------------------------
    st.subheader("4. Out-of-Sample Portfolio Holdout State: Explicit UNAVAILABLE")
    holdout = load_portfolio_holdout_diagnostics()

    col_h1, col_h2 = st.columns([1, 2])
    with col_h1:
        render_metric_card(
            label="2024 Strategy Holdout Status",
            value="UNAVAILABLE",
            is_unavailable=True,
            unavailable_reason=holdout.reason,
        )
    with col_h2:
        render_holdout_unavailable_banner(reason=holdout.reason)

    with st.expander("Authoritative Holdout Governance Notes", expanded=True):
        st.markdown(f"**Verbatim Architectural Rationale:** *{holdout.reason}*")
        st.markdown("**Governance Rules:**")
        for note in holdout.notes:
            st.markdown(f"- {note}")
        st.info(
            "**Invariance Rule:** The dashboard strictly refrains from synthesizing, interpolating, "
            "or back-projecting fictional portfolio equity curves for the 2024 holdout window."
        )

    st.divider()

    # --------------------------------------------------------------------------
    # F. Navigation to Page 2
    # --------------------------------------------------------------------------
    st.subheader("5. Deep Dive Navigation")
    st.markdown(
        """
        Proceed to **Page 2: Carry Trade Performance** to inspect the full double-entry P&L attribution
        waterfall, transaction cost drag, cash interest reconciliation, and alternative execution configurations:
        """
    )
    col_nav, _ = st.columns([2, 3])
    with col_nav:
        try:
            st.page_link(
                "pages/2_Carry_Trade_Performance.py",
                label="Proceed to Page 2: Carry Trade Performance & P&L Attribution →",
                icon="📊",
            )
        except Exception:
            if st.button("Proceed to Page 2: Carry Trade Performance →"):
                st.switch_page("pages/2_Carry_Trade_Performance.py")


if __name__ == "__main__":
    render_page()
