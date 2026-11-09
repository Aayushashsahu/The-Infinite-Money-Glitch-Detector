"""Page 4 — Monte Carlo Simulation Laboratory: Multi-Model Stochastic Evaluation.

Presents and compares six calibrated stochastic models exploring forward distributions,
downside risk, tail losses, representative paths, and asymptotic convergence checkpoints.

Guiding Principle: Mathematics first. Data second. Prediction third. AI last.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.artifacts.loader import (
    load_convergence_report,
    load_model_comparison,
    load_monte_carlo_result,
)
from dashboard.components.banner import render_research_banner
from dashboard.components.metrics_card import format_percent, render_metric_card
from dashboard.components.plots.comparison import build_model_comparison_figure
from dashboard.components.plots.simulation import (
    build_convergence_figure,
    build_model_metrics_bar_figure,
    build_representative_paths_figure,
)
from dashboard.components.tables import render_data_table

st.set_page_config(
    page_title="Monte Carlo Laboratory — The Infinite Money Glitch Detector",
    page_icon="🎲",
    layout="wide",
)


def render_page() -> None:
    """Render the Monte Carlo Simulation Laboratory page."""
    # --------------------------------------------------------------------------
    # A. Research Classification Banner
    # --------------------------------------------------------------------------
    render_research_banner(
        data_classification="SIMULATED_RESEARCH_PROXY",
        pit_mode="ESTIMATED_LAG",
        extra_notice="Stochastic simulations evaluate counterfactual distribution of potential outcomes under modeled assumptions. They do not constitute forecasts or executable trading records.",
    )

    st.title("🎲 Monte Carlo Simulation Laboratory")
    st.caption("Stochastic Models | Tail Risk Evaluation | Representative Paths | Convergence Diagnostics")

    # Load authoritative artifacts
    models = load_model_comparison()
    conv = load_convergence_report()

    # --------------------------------------------------------------------------
    # B. Six-Model Comparative Overview
    # --------------------------------------------------------------------------
    st.subheader("1. Six-Model Stochastic Comparison (N=1,000 Paths per Model)")
    st.markdown(
        """
        Six distinct stochastic frameworks evaluate the carry trade strategy across varied
        assumptions regarding correlation stability, heavy tails, and empirical clustering:
        """
    )

    # Comparative table
    model_table_data = []
    for m in models:
        model_table_data.append(
            {
                "Model Framework": m.model_name,
                "Paths (N)": f"{m.num_paths:,}",
                "Mean Return": format_percent(m.mean_return),
                "Median Return": format_percent(m.median_return),
                "Volatility (Std)": format_percent(m.std_return),
                "Loss Probability": format_percent(m.prob_loss),
                "95% VaR": format_percent(m.var_95),
                "95% CVaR (Tail Risk)": format_percent(m.cvar_95),
                "Median Max Drawdown": format_percent(m.max_drawdown_median),
            }
        )
    render_data_table(pd.DataFrame(model_table_data))

    st.divider()

    # --------------------------------------------------------------------------
    # C. Model Comparison Visualizations
    # --------------------------------------------------------------------------
    st.subheader("2. Multi-Model Risk & Return Visualizations")
    st.markdown(
        """
        Comparing central tendency (median simulated return) against downside tail risk (95% CVaR)
        reveals that every model exhibits substantial downside vulnerability:
        """
    )

    st.plotly_chart(
        build_model_comparison_figure(models, height=420),
        use_container_width=True,
    )

    v_col1, v_col2 = st.columns(2)
    with v_col1:
        st.plotly_chart(
            build_model_metrics_bar_figure(
                models=models,
                metric_key="prob_loss",
                metric_label="Probability of Loss",
                height=360,
            ),
            use_container_width=True,
        )
    with v_col2:
        st.plotly_chart(
            build_model_metrics_bar_figure(
                models=models,
                metric_key="max_drawdown_median",
                metric_label="Median Maximum Drawdown",
                height=360,
            ),
            use_container_width=True,
        )

    st.divider()

    # --------------------------------------------------------------------------
    # D. Distribution Exploration & Representative Paths
    # --------------------------------------------------------------------------
    st.subheader("3. Distribution Exploration & Representative Paths")
    st.markdown(
        """
        Explore detailed quantile distributions and inspection trajectories for specific simulation models.
        Representative paths visualize best (top 1%), median (50th percentile), and worst (bottom 1%) outcomes:
        """
    )

    model_options = {
        "Multivariate Gaussian (Baseline)": "gaussian",
        "Moving-Block Bootstrap (20-day Blocks)": "bootstrap",
        "Multivariate Student-t (Fat Tails, v=7.74)": "student_t",
        "Regime-Conditioned Bootstrap (Volatility Regimes)": "regime",
    }

    selected_label = st.selectbox(
        "Select Simulation Model to Inspect:",
        options=list(model_options.keys()),
        index=0,
    )
    selected_key = model_options[selected_label]

    try:
        mc_res = load_monte_carlo_result(selected_key)
        dist = mc_res.distribution_metrics
        paths = mc_res.representative_paths

        # Distribution Metrics Cards
        d_col1, d_col2, d_col3, d_col4, d_col5 = st.columns(5)
        with d_col1:
            render_metric_card("Median Return", format_percent(dist.get("median_return", 0.0)))
        with d_col2:
            render_metric_card("Mean Return", format_percent(dist.get("mean_return", 0.0)))
        with d_col3:
            render_metric_card(
                "Prob of Loss", format_percent(dist.get("prob_loss", 0.0)), delta="Loss Risk", delta_color="inverse"
            )
        with d_col4:
            render_metric_card(
                "95% CVaR", format_percent(dist.get("cvar_95", 0.0)), delta="Tail Loss", delta_color="inverse"
            )
        with d_col5:
            render_metric_card(
                "Median Max DD",
                format_percent(dist.get("max_drawdown_median", 0.0)),
                delta="Drawdown",
                delta_color="inverse",
            )

        # Representative Paths Plot
        st.plotly_chart(
            build_representative_paths_figure(paths, model_name=selected_label, height=440),
            use_container_width=True,
        )

        st.warning(
            "**REPRESENTATIVE PATHS NOTICE:** The trajectories above are **simulated representative paths**, "
            "not historical equity curves. They represent counterfactual stochastic sample realizations across 253 simulated "
            "trading days under the specified model parameters. Never treat simulated paths as historical trading performance."
        )

    except Exception as e:
        st.error(f"Error loading model results for {selected_label}: {e}")

    st.divider()

    # --------------------------------------------------------------------------
    # E. Asymptotic Convergence Diagnostics
    # --------------------------------------------------------------------------
    st.subheader("4. Asymptotic Convergence & Checkpoint Stability Diagnostics")
    st.markdown(
        """
        Convergence diagnostics audit whether simulation estimates stabilize as sample size increases
        from N=25 to N=1,000 paths:
        """
    )

    st.plotly_chart(
        build_convergence_figure(conv.checkpoints, height=400),
        use_container_width=True,
    )

    conv_col1, conv_col2 = st.columns([1, 1])

    with conv_col1:
        st.markdown("##### Checkpoint Convergence Checkpoints Table")
        cp_rows = []
        for cp in conv.checkpoints:
            cp_rows.append(
                {
                    "Sample Size (N)": cp.get("sample_size"),
                    "Mean Return": format_percent(cp.get("mean_return", 0.0)),
                    "Median Return": format_percent(cp.get("median_return", 0.0)),
                    "Loss Probability": format_percent(cp.get("prob_loss", 0.0)),
                    "Loss Prob SE": f"±{cp.get('prob_loss_se', 0.0) * 100:.2f}%",
                    "95% CVaR": format_percent(cp.get("cvar_95", 0.0)),
                    "Tail Obs": cp.get("tail_sample_size"),
                }
            )
        render_data_table(pd.DataFrame(cp_rows))

    with conv_col2:
        st.markdown("##### Checkpoint Stability & Methodological Invariants")
        st.info(
            "**STABILITY STATUS:** 5 of 6 models achieved checkpoint stability at N=1,000. "
            "The **Regime-Conditioned Bootstrap** was flagged for tail variation (loss probability shifted by 3.90% > 2.0% tolerance).\n\n"
            f"**Overall Convergence Report Note:**\n_{conv.convergence_notes}_"
        )
        st.warning(
            "**MATHEMATICAL PRINCIPLE:** Finite sample stability across discrete checkpoints does **not** establish "
            "formal asymptotic mathematical convergence. Tail risk estimates (such as 95% CVaR) remain subject to "
            "finite sample variation across independent simulation runs."
        )

    st.divider()

    # --------------------------------------------------------------------------
    # F. Research Interpretation & Limitations
    # --------------------------------------------------------------------------
    st.subheader("5. Research Interpretation & Limitations")
    st.markdown(
        """
        - **Historical Realization (N=1)**: Observed empirical return of +2.89% (+€2,890.22) across 2020–2024 reflects a single observed trajectory conditioned on specific ECB/Fed monetary tightening cycles.
        - **Simulated Ensembles (N=1,000)**: Across all 6 stochastic models, median returns range from +1.60% to +2.25%, with loss probabilities between 27.9% and 34.1%.
        - **Negative Excess Return**: Every simulation model yields an expected return below the risk-free EUR cash deposit benchmark (+1.50% annual, +7.73% cumulative 5-yr).
        - **Conclusion**: Cross-currency carry trades do not represent an unhedged arbitrage opportunity; they represent an uncompensated directional exchange-rate volatility exposure.
        """
    )


if __name__ == "__main__":
    render_page()
