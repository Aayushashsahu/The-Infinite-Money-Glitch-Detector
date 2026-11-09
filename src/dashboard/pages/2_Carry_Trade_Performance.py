"""Page 2 — Carry Trade Performance & Double-Entry P&L Attribution.

Provides comprehensive quantitative inspection of the primary empirical carry trade
backtest (Config 2: Estimated Schedule), including:
- Backtest summary metrics and trade statistics
- Double-entry P&L attribution waterfall
- Strategy vs. EUR Fixed Deposit benchmark comparison
- Alternative configuration audit (Configs 1 through 6)
- Mathematical double-entry ledger reconciliation

Guiding Principle: Mathematics first. Data second. Prediction third. AI last.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.artifacts.loader import list_backtest_configs, load_backtest_config
from dashboard.components.banner import render_research_banner
from dashboard.components.metrics_card import (
    format_bps,
    format_currency,
    format_percent,
    render_metric_card,
)
from dashboard.components.plots.comparison import build_benchmark_comparison_figure
from dashboard.components.plots.waterfall import build_attribution_waterfall_figure
from dashboard.components.tables import render_data_table

st.set_page_config(
    page_title="Carry Trade Performance — The Infinite Money Glitch Detector",
    page_icon="📊",
    layout="wide",
)


def render_page() -> None:
    """Render the Carry Trade Performance & Attribution page."""
    # --------------------------------------------------------------------------
    # A. Research Classification Banner
    # --------------------------------------------------------------------------
    render_research_banner(
        data_classification="SIMULATED_RESEARCH_PROXY",
        pit_mode="ESTIMATED_LAG",
        extra_notice="Historical backtest based on daily fixing rates. Evaluates reference-rate economic viability under simulated execution constraints.",
    )

    st.title("📊 Carry Trade Performance & Double-Entry Attribution")
    st.caption("Primary Historical Baseline: Config 2 (Estimated Schedule) | 2020-01-07 to 2023-12-29")

    # Load primary backtest artifact
    c2 = load_backtest_config("config_2_estimated_schedule")
    perf = c2.performance
    attr = c2.attribution
    bench = c2.benchmark
    trades = c2.trades

    # --------------------------------------------------------------------------
    # B. Backtest Summary & Trade Statistics Grid
    # --------------------------------------------------------------------------
    st.subheader("1. Empirical Backtest Summary (Config 2)")

    r1_c1, r1_c2, r1_c3, r1_c4 = st.columns(4)
    with r1_c1:
        render_metric_card(
            label="Initial Capital",
            value=format_currency(c2.initial_capital_a),
            delta="EUR Denominated",
            delta_color="off",
            help_text="Starting account capital in EUR from config_2_estimated_schedule.json.",
        )
    with r1_c2:
        render_metric_card(
            label="Cumulative Net Profit",
            value=format_currency(perf.cumulative_net_profit),
            delta=format_percent(perf.total_return),
            delta_color="normal",
            help_text="Total net cash gain over 1,236 daily transitions from config_2_estimated_schedule.json.",
        )
    with r1_c3:
        render_metric_card(
            label="Annualized Net Return",
            value=format_percent(perf.annualized_return),
            delta="5-Year Geometric Return",
            delta_color="normal",
            help_text="Compound annual growth rate (CAGR) from config_2_estimated_schedule.json.",
        )
    with r1_c4:
        render_metric_card(
            label="Annualized Volatility",
            value=format_percent(perf.annualized_volatility, show_sign=False),
            delta="Daily Realized Vol",
            delta_color="off",
            help_text="Annualized sample standard deviation of daily strategy returns from config_2_estimated_schedule.json.",
        )

    r2_c1, r2_c2, r2_c3, r2_c4 = st.columns(4)
    with r2_c1:
        render_metric_card(
            label="Sharpe Ratio",
            value=f"{perf.sharpe_ratio:.3f}" if perf.sharpe_ratio is not None else "N/A",
            delta="Negative Risk-Adjusted Return",
            delta_color="inverse" if (perf.sharpe_ratio or 0) < 0 else "normal",
            help_text="Risk-adjusted return vs zero risk-free benchmark from config_2_estimated_schedule.json.",
        )
    with r2_c2:
        render_metric_card(
            label="Maximum Drawdown",
            value=format_percent(perf.max_drawdown),
            delta=f"Calmar: {perf.calmar_ratio:.2f}" if perf.calmar_ratio else "N/A",
            delta_color="inverse",
            help_text="Peak-to-trough historical portfolio decline from config_2_estimated_schedule.json.",
        )
    with r2_c3:
        render_metric_card(
            label="Total Execution Trades",
            value=str(trades.total_trades),
            delta=f"{trades.winning_trades}W / {trades.losing_trades}L",
            delta_color="off",
            help_text="Total position entry/rebalancing transactions from config_2_estimated_schedule.json.",
        )
    with r2_c4:
        render_metric_card(
            label="Trade Win Rate",
            value=format_percent(trades.win_rate, show_sign=False),
            delta=f"Profit Factor: {trades.profit_factor:.2f}" if trades.profit_factor else "N/A",
            delta_color="normal" if trades.win_rate > 0.5 else "off",
            help_text="Percentage of closed trade cycles generating positive net P&L from config_2_estimated_schedule.json.",
        )

    st.caption(
        f"**Source Provenance:** `data/results/phase_3_2_2_3_3/config_2_estimated_schedule.json` | "
        f"Execution window: `{c2.start_date}` to `{c2.end_date}` | "
        f"Currency Pair: `{c2.currency_pair}` | Status: `{c2.strategy_status}`"
    )

    st.divider()

    # --------------------------------------------------------------------------
    # C. Double-Entry P&L Attribution Waterfall
    # --------------------------------------------------------------------------
    st.subheader("2. Double-Entry P&L Attribution Waterfall")
    st.markdown(
        """
        The double-entry cash ledger isolates the exact economic sources of portfolio P&L.
        Crucially, this proves that the carry trade did **not** profit from interest rate differentials:
        """
    )

    st.plotly_chart(
        build_attribution_waterfall_figure(attr),
        use_container_width=True,
    )

    # Detailed Waterfall Component Breakdown
    decomp_data = [
        {
            "Attribution Component": "1. Foreign Investment Yield",
            "P&L Impact (EUR)": format_currency(attr.investment_yield_gain_a),
            "Return Contribution (%)": format_percent(attr.investment_yield_return),
            "Economic Mechanism": "Interest accrued on USD asset holdings (Treasury bills/cash deposits).",
        },
        {
            "Attribution Component": "2. FX Translation Gain / (Loss)",
            "P&L Impact (EUR)": format_currency(attr.fx_translation_gain_a),
            "Return Contribution (%)": format_percent(attr.pure_fx_return),
            "Economic Mechanism": "Exchange rate movement impact. EUR appreciation against USD generated severe translation loss.",
        },
        {
            "Attribution Component": "= Pure Trade Gross P&L",
            "P&L Impact (EUR)": format_currency(attr.pure_gross_profit_a),
            "Return Contribution (%)": format_percent(attr.gross_trade_return),
            "Economic Mechanism": "Subtotal (Yield + FX). Negative result proves FX depreciation overwhelmed nominal yield advantage.",
        },
        {
            "Attribution Component": "3. Financing Borrowing Costs",
            "P&L Impact (EUR)": format_currency(-attr.total_financing_costs_a),
            "Return Contribution (%)": format_percent(-attr.financing_cost_drag),
            "Economic Mechanism": "Contractual borrowing interest paid on EUR liability balance.",
        },
        {
            "Attribution Component": "4. Cash Deposit Collateral Yield",
            "P&L Impact (EUR)": format_currency(attr.total_cash_interest_a),
            "Return Contribution (%)": format_percent(attr.cash_yield_return),
            "Economic Mechanism": "Interest earned on unencumbered domestic EUR cash balance. Generated 100% of strategy net profit.",
        },
        {
            "Attribution Component": "5. Transaction Frictions & Slippage",
            "P&L Impact (EUR)": format_currency(-attr.total_frictions_a),
            "Return Contribution (%)": format_percent(-attr.transaction_cost_drag),
            "Economic Mechanism": "Bid-ask spread costs (€306.02) and simulated execution slippage (€153.00).",
        },
        {
            "Attribution Component": "= Net Realized Profit",
            "P&L Impact (EUR)": format_currency(perf.cumulative_net_profit),
            "Return Contribution (%)": format_percent(perf.total_return),
            "Economic Mechanism": "Total reconciled net outcome on €100,000 initial capital.",
        },
    ]

    df_decomp = pd.DataFrame(decomp_data)
    render_data_table(df_decomp, title="Exact Arithmetic Ledger Breakdown")

    # Double-entry exactness audit
    st.info(
        f"**Mathematical Double-Entry Proof:** "
        f"Reconciliation Residual = `{attr.reconciliation_residual_a:.4e} EUR` | "
        f"Reconciliation Status = `{'EXACT (Pass)' if attr.reconciliation_exact else 'FAILED'}`. "
        "The components reconcile to total net profit within floating-point precision (≤ 10⁻¹⁰)."
    )

    st.divider()

    # --------------------------------------------------------------------------
    # D. Strategy vs. Benchmark Comparison & Time-Series Availability
    # --------------------------------------------------------------------------
    st.subheader("3. Strategy Performance vs. EUR Deposit Benchmark")
    st.markdown(
        """
        To evaluate whether the carry trade added economic value, performance is benchmarked against
        a risk-free EUR cash deposit earning a static 1.5% annual rate:
        """
    )

    b_col1, b_col2, b_col3, b_col4 = st.columns(4)
    with b_col1:
        render_metric_card(
            label="Carry Strategy Return",
            value=format_percent(perf.total_return),
            delta=format_currency(perf.cumulative_net_profit),
            delta_color="normal",
            help_text="5-year total strategy net return from config_2_estimated_schedule.json.",
        )
    with b_col2:
        render_metric_card(
            label="EUR Deposit Benchmark",
            value=format_percent(bench.benchmark_total_return),
            delta=f"Annualized: {format_percent(bench.benchmark_annualized_return)}",
            delta_color="off",
            help_text="EUR Fixed Deposit Proxy total return (+1.50% p.a.) from config_2_estimated_schedule.json.",
        )
    with b_col3:
        render_metric_card(
            label="Annualized Strategy Alpha",
            value=format_percent(bench.alpha),
            delta=format_bps(bench.alpha),
            delta_color="inverse",
            help_text="Underperformance vs risk-free deposit proxy from config_2_estimated_schedule.json.",
        )
    with b_col4:
        render_metric_card(
            label="Cumulative Excess Return",
            value=format_percent(bench.cumulative_excess_return),
            delta="Negative Excess Return",
            delta_color="inverse",
            help_text="Total 5-year strategy return minus benchmark return from config_2_estimated_schedule.json.",
        )

    st.plotly_chart(
        build_benchmark_comparison_figure(
            strategy_return=perf.total_return,
            benchmark_return=bench.benchmark_total_return or 0.0,
            alpha=bench.alpha or 0.0,
        ),
        use_container_width=True,
    )

    # Time-series availability limitation notice
    st.warning(
        "**TIME-SERIES LIMITATION NOTICE — Intermediate Daily Equity Curve Unavailable**\n\n"
        "The authoritative backtest artifact `config_2_estimated_schedule.json` stores terminal execution aggregates, "
        "double-entry P&L attributions, and cumulative benchmark metrics. In accordance with the project's strict "
        "mathematical governance principles, intermediate daily equity step-curves and daily underwater drawdown series "
        "are **not fabricated or interpolated** without underlying daily order-book execution records.\n\n"
        "The verified maximum drawdown is documented as **-3.52%**."
    )

    st.divider()

    # --------------------------------------------------------------------------
    # E. Alternative Configuration Audit (Configs 1 through 6)
    # --------------------------------------------------------------------------
    st.subheader("4. Alternative Backtest Configurations Audit (Phase 3 Framework)")
    st.markdown(
        """
        The Phase 3 research framework systematically tested six distinct execution specifications to determine
        whether point-in-time publication lags, quote credibility, or benchmark matching alter findings:
        """
    )

    all_configs = list_backtest_configs()
    config_table_rows = []

    for cid, cfg in all_configs:
        cfg_perf = cfg.performance
        cfg_bench = cfg.benchmark
        config_table_rows.append(
            {
                "Config ID": cid,
                "Strategy Specification": cfg.strategy_name,
                "Status": cfg.strategy_status,
                "Executable": "Yes" if cfg.is_executable_strategy else "No (Rejected)",
                "PIT Credible": "Yes" if cfg.is_point_in_time_credible else "No",
                "Total Return": format_percent(cfg_perf.total_return) if cfg_perf else "N/A",
                "Max Drawdown": format_percent(cfg_perf.max_drawdown) if cfg_perf else "N/A",
                "Alpha vs Benchmark": format_percent(cfg_bench.alpha) if (cfg_bench and cfg_bench.alpha) else "N/A",
                "Reconciliation": "Exact (Pass)"
                if (cfg.attribution and cfg.attribution.reconciliation_exact)
                else "N/A",
            }
        )

    df_configs = pd.DataFrame(config_table_rows)
    render_data_table(df_configs, title="Six-Configuration Systematic Specification Audit")

    # In-depth architectural notes on rejected configs
    with st.expander("Detailed Rationales for Rejected Configurations (Configs 3 & 6)", expanded=False):
        c3 = dict(all_configs)["config_3_strict_quotes"]
        c6 = dict(all_configs)["config_6_covered_rejection"]

        st.markdown(f"**Config 3 (Strict Executable Quotes Rejection):** `{c3.strategy_status}`")
        st.markdown(f"- *Reason:* {c3.unsupported_reason}")
        st.markdown(
            "- *Takeaway:* Daily fixing reference rates published by central banks cannot be traded at without "
            "spread and liquidity penalties; enforcing true order-book quotes renders the reference-rate strategy unexecutable."
        )

        st.markdown(f"**Config 6 (Covered Carry Trade Rejection):** `{c6.strategy_status}`")
        st.markdown(f"- *Reason:* {c6.unsupported_reason}")
        st.markdown(
            "- *Takeaway:* Covered Interest Parity (CIP) arbitrage requires liquid forward FX contract quotes. "
            "In historical data where genuine forward bid/ask quotes are absent, calculating CIP return from spot rates "
            "and theoretical interest rates would represent an invalid simulation fiction."
        )


if __name__ == "__main__":
    render_page()
