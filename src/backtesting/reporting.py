"""Reporting and Audit Trail Generation for Backtesting Results.

Generates:
- Comprehensive text and markdown backtest summaries
- Trade audit logs with execution prices, spreads, fees, and PnL
- Risk and return tables with explicit metric assumptions
- Walk-forward chronological stability reports
- Data availability and look-ahead firewall compliance declarations
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from schemas.backtest import BacktestResult
from backtesting.walk_forward import WalkForwardSummary


def export_backtest_result_json(result: BacktestResult, output_path: str | Path | None = None) -> dict[str, Any]:
    """Export machine-generated JSON result for reproducibility and audit trail."""
    cfg = result.config
    m = result.metrics
    pair = cfg.currency_pair

    data: dict[str, Any] = {
        "strategy_name": cfg.strategy_name,
        "currency_pair": f"{pair.borrowing_currency}/{pair.investment_currency}",
        "start_date": str(cfg.start_date),
        "end_date": str(cfg.end_date),
        "initial_capital_a": cfg.initial_capital_a,
        "strategy_status": result.strategy_status.value,
        "can_simulate": result.can_simulate,
        "is_point_in_time_credible": result.is_point_in_time_credible,
        "is_economically_representative": result.is_economically_representative,
        "is_executable_strategy": result.is_executable_strategy,
        "unsupported_reason": result.unsupported_reason,
        "manifest_digest": result.manifest_digest,
        "performance": {
            "cumulative_net_profit": m.cumulative_net_profit,
            "total_return": m.total_return,
            "annualized_return": m.annualized_return,
            "annualized_volatility": m.annualized_volatility,
            "sharpe_ratio": m.sharpe_ratio,
            "sortino_ratio": m.sortino_ratio,
            "max_drawdown": m.max_drawdown,
            "calmar_ratio": m.calmar_ratio,
            "var_95": m.var_95,
            "cvar_95": m.cvar_95,
            "avg_capital_utilization": m.avg_capital_utilization,
            "max_exposure_a": m.max_exposure_a,
        },
        "attribution": {
            "pure_gross_profit_a": m.pure_gross_profit_a,
            "gross_trade_return": m.gross_trade_return,
            "fx_translation_gain_a": m.fx_translation_gain_a,
            "pure_fx_return": m.pure_fx_return,
            "investment_yield_gain_a": m.investment_yield_gain_a,
            "investment_yield_return": m.investment_yield_return,
            "total_financing_costs_a": m.total_financing_costs_a,
            "financing_cost_drag": m.financing_cost_drag,
            "total_frictions_a": m.total_frictions_a,
            "transaction_cost_drag": m.transaction_cost_drag,
            "observed_spread_cost_a": m.observed_spread_cost_a,
            "observed_spread_drag": m.observed_spread_drag,
            "modelled_spread_cost_a": m.modelled_spread_cost_a,
            "modelled_spread_drag": m.modelled_spread_drag,
            "slippage_cost_a": m.slippage_cost_a,
            "slippage_drag": m.slippage_drag,
            "total_cash_interest_a": m.total_cash_interest_a,
            "cash_yield_return": m.cash_yield_return,
            "reconciliation_residual_a": m.reconciliation_residual_a,
            "reconciliation_exact": m.reconciliation_exact,
        },
        "benchmark": {
            "benchmark_name": m.benchmark_name,
            "benchmark_total_return": m.benchmark_total_return,
            "benchmark_annualized_return": m.benchmark_annualized_return,
            "benchmark_sharpe_ratio": m.benchmark_sharpe_ratio,
            "alpha": m.alpha,
            "cumulative_excess_return": m.cumulative_excess_return,
            "annualized_excess_return": m.annualized_excess_return,
        },
        "trades": {
            "total_trades": m.total_trades,
            "winning_trades": m.winning_trades,
            "losing_trades": m.losing_trades,
            "win_rate": m.win_rate,
            "avg_winning_trade": m.avg_winning_trade,
            "avg_losing_trade": m.avg_losing_trade,
            "profit_factor": m.profit_factor,
            "rejected_trades_count": len(result.rejections),
        },
    }

    if output_path is not None:
        p = Path(output_path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        import time
        for attempt in range(5):
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                break
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(0.2)

    return data


def format_backtest_report(result: BacktestResult) -> str:
    """Generate a comprehensive markdown summary report of a backtest run."""
    cfg = result.config
    m = result.metrics
    pair = cfg.currency_pair

    lines: list[str] = []
    lines.append("# Historical Backtest Execution Report")
    lines.append(f"**Strategy**: `{cfg.strategy_name}`  ")
    lines.append(f"**Currency Pair**: `{pair.borrowing_currency}/{pair.investment_currency}`  ")
    lines.append(f"**Simulation Window**: `{cfg.start_date}` to `{cfg.end_date}`  ")
    lines.append(f"**Initial Capital**: `{cfg.initial_capital_a:,.2f} {pair.borrowing_currency}`  ")
    lines.append(f"**Trade Tenor**: `{cfg.tenor_days} calendar days`  ")
    lines.append(f"**Data Availability Policy**: `{cfg.availability_config.policy.value.upper()}`  ")
    lines.append(f"**Executable Strategy**: `{'YES' if result.is_executable_strategy else 'NO'}`  ")

    if not result.is_executable_strategy and result.unsupported_reason:
        lines.append(f"\n> [!WARNING] **STRATEGY NOT EXECUTABLE**: {result.unsupported_reason}\n")

    lines.append("\n## 1. Performance and Risk Summary\n")
    lines.append("| Metric | Value | Convention / Assumption |")
    lines.append("| :--- | :--- | :--- |")
    lines.append(f"| **Cumulative Net Profit** | `{m.cumulative_net_profit:,.2f} {pair.borrowing_currency}` | Sum of net PnL after financing & fees |")
    lines.append(f"| **Total Return** | `{m.total_return:+.2%}` | Cumulative profit / initial capital |")
    lines.append(f"| **Annualized Return** | `{m.annualized_return:+.2%}` | Compounded equivalent annual rate |")
    lines.append(f"| **Annualized Volatility** | `{m.annualized_volatility:.2%}` | Sample std (ddof=1) of periodic returns * sqrt(252) |")
    sh_str = f"{m.sharpe_ratio:.2f}" if m.sharpe_ratio is not None else "N/A"
    lines.append(f"| **Sharpe Ratio** | `{sh_str}` | Excess return over borrowing cash rate |")
    so_str = f"{m.sortino_ratio:.2f}" if m.sortino_ratio is not None else "N/A"
    lines.append(f"| **Sortino Ratio** | `{so_str}` | Downside deviation below risk-free rate |")
    lines.append(f"| **Maximum Drawdown** | `{m.max_drawdown:.2%}` | Peak-to-trough compounded equity decline |")
    cal_str = f"{m.calmar_ratio:.2f}" if m.calmar_ratio is not None else "N/A"
    lines.append(f"| **Calmar Ratio** | `{cal_str}` | Annualized return / abs(Max Drawdown) |")
    lines.append(f"| **Value at Risk (95% VaR)** | `{m.var_95:.2%}` | Empirical lower 5th percentile of period returns |")
    lines.append(f"| **Conditional VaR (95% CVaR)** | `{m.cvar_95:.2%}` | Expected shortfall of returns at/below VaR |")
    lines.append(f"| **Average Capital Utilization** | `{m.avg_capital_utilization:.1%}` | Mean borrowed exposure / equity |")
    lines.append(f"| **Peak Exposure** | `{m.max_exposure_a:,.2f} {pair.borrowing_currency}` | Maximum simultaneous borrowed principal |")

    # Return attribution breakdown with exact double-entry ledger
    lines.append("\n## 2. Return Attribution Decomposition & Double-Entry Cash Ledger\n")
    lines.append("| Attribution Component | Currency Amount | Return on Capital | Description |")
    lines.append("| :--- | :--- | :--- | :--- |")
    gross_str = f"{m.gross_trade_return:+.4%}" if m.gross_trade_return is not None else "N/A"
    lines.append(f"| **Pure Gross Gain** | `{m.pure_gross_profit_a:+,.2f} {pair.borrowing_currency}` | `{gross_str}` | Asset appreciation & interest before financing & fees |")
    fx_str = f"{m.pure_fx_return:+.4%}" if m.pure_fx_return is not None else "N/A"
    lines.append(f"|   ├── *Pure FX Movement* | `{m.fx_translation_gain_a:+,.2f} {pair.borrowing_currency}` | `{fx_str}` | FX spot price change on invested capital |")
    yd_str = f"{m.investment_yield_return:+.4%}" if m.investment_yield_return is not None else "N/A"
    lines.append(f"|   └── *Investment Asset Yield* | `{m.investment_yield_gain_a:+,.2f} {pair.borrowing_currency}` | `{yd_str}` | Interest accrued on investment asset |")
    fin_str = f"{-m.financing_cost_drag:+.4%}" if m.financing_cost_drag is not None else "N/A"
    lines.append(f"| **Debt Financing Costs** | `{-m.total_financing_costs_a:,.2f} {pair.borrowing_currency}` | `{fin_str}` | Interest paid on borrowed liabilities |")
    tx_str = f"{-m.transaction_cost_drag:+.4%}" if m.transaction_cost_drag is not None else "N/A"
    lines.append(f"| **Execution Frictions Drag** | `{-m.total_frictions_a:,.2f} {pair.borrowing_currency}` | `{tx_str}` | Total bid/ask spread, slippage, and ticket fees |")
    obs_sp_str = f"{-m.observed_spread_drag:+.4%}" if m.observed_spread_drag is not None else "N/A"
    lines.append(f"|   ├── *Observed Spread Cost* | `{-m.observed_spread_cost_a:,.2f} {pair.borrowing_currency}` | `{obs_sp_str}` | Market bid/ask spread paid |")
    mod_sp_str = f"{-m.modelled_spread_drag:+.4%}" if m.modelled_spread_drag is not None else "N/A"
    lines.append(f"|   ├── *Modelled Spread Cost* | `{-m.modelled_spread_cost_a:,.2f} {pair.borrowing_currency}` | `{mod_sp_str}` | Synthetic parameter spread paid |")
    slip_str = f"{-m.slippage_drag:+.4%}" if m.slippage_drag is not None else "N/A"
    lines.append(f"|   └── *Execution Slippage* | `{-m.slippage_cost_a:,.2f} {pair.borrowing_currency}` | `{slip_str}` | Execution timing slippage |")
    cash_str = f"{m.cash_yield_return:+.4%}" if m.cash_yield_return is not None else "N/A"
    lines.append(f"| **Cash Yield on Unallocated Balances** | `{m.total_cash_interest_a:+,.2f} {pair.borrowing_currency}` | `{cash_str}` | Interest earned on cash balances |")
    lines.append(f"| **Reconciled Net Profit** | `**{m.cumulative_net_profit:+,.2f} {pair.borrowing_currency}**` | `**{m.total_return:+.4%}**` | Gross Gain - Financing - Fees + Cash Yield |")
    lines.append(f"| **Reconciliation Residual** | `**{m.reconciliation_residual_a:+.10f}**` | `Exact: {m.reconciliation_exact}` | Absolute residual ($|\\text{{residual}}| \\le 10^{{-10}}$) |")
    pos_vol_str = f"{m.position_annualized_volatility:.2%}" if m.position_annualized_volatility is not None else "N/A"
    lines.append(f"| **Position-Level Volatility** | `{pos_vol_str}` | Volatility evaluated on active deployed capital (undiluted) |")
    lines.append(f"| **Portfolio-Level Volatility** | `{m.annualized_volatility:.2%}` | Volatility evaluated on total portfolio equity |")

    lines.append("\n## 3. Trade Execution Statistics\n")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| **Total Closed Trades** | `{m.total_trades}` |")
    lines.append(f"| **Winning Trades** | `{m.winning_trades}` |")
    lines.append(f"| **Losing Trades** | `{m.losing_trades}` |")
    lines.append(f"| **Win Rate** | `{m.win_rate:.1%}` |")
    lines.append(f"| **Average Winning Trade** | `{m.avg_winning_trade:,.2f} {pair.borrowing_currency}` |")
    lines.append(f"| **Average Losing Trade** | `{m.avg_losing_trade:,.2f} {pair.borrowing_currency}` |")
    pf_str = f"{m.profit_factor:.2f}" if m.profit_factor is not None else "N/A"
    lines.append(f"| **Profit Factor** | `{pf_str}` |")
    lines.append(f"| **Rejected Trade Attempts** | `{len(result.rejections)}` |")

    lines.append("\n## 4. Benchmark Comparison & Excess Returns\n")
    if m.benchmark_name:
        lines.append(f"**Comparative Benchmark**: `{m.benchmark_name}`  ")
        lines.append(f"- Benchmark Total Return: `{m.benchmark_total_return:+.4%}`  ")
        lines.append(f"- Benchmark Annualized Return: `{m.benchmark_annualized_return:+.4%}`  ")
        lines.append(f"- Strategy Total Return: `{m.total_return:+.4%}`  ")
        lines.append(f"- Strategy Annualized Return: `{m.annualized_return:+.4%}`  ")
        cum_excess = f"{m.cumulative_excess_return:+.4%}" if m.cumulative_excess_return is not None else "N/A"
        lines.append(f"- Cumulative Excess Return: `{cum_excess}`  ")
        ann_excess = f"{m.annualized_excess_return:+.4%}" if m.annualized_excess_return is not None else "N/A"
        lines.append(f"- Annualized Excess Return: `{ann_excess}`  ")
        alpha_str = f"{m.alpha:+.4%}" if m.alpha is not None else "N/A"
        lines.append(f"- Strategy Alpha (Excess Return): `{alpha_str}`  ")
    else:
        lines.append("*No benchmark series computed (insufficient observations or explicitly UNAVAILABLE).*")

    lines.append("\n## 5. Historical Information Firewall Audit\n")
    lines.append(f"- **Availability Policy**: `{cfg.availability_config.policy.value.upper()}`")
    lines.append(f"- **Max permissible staleness**: `{cfg.availability_config.max_stale_days} trading days`")
    lines.append(f"- **Total Audit Log Entries**: `{len(result.audit_trail)}`")
    if result.rejections:
        lines.append(f"- **Rejections Recorded**: `{len(result.rejections)}` (Reasons include capital limits, missing quotes, hurdle rate)")

    if result.provenance is not None:
        p = result.provenance
        lines.append("\n## 6. Data Provenance & Traceability Report\n")
        lines.append(f"- **Source Providers**: `{', '.join(p.source_providers)}`")
        lines.append(f"- **Dataset Identifiers**: `{', '.join(p.dataset_identifiers)}`")
        lines.append(f"- **Date Range**: `{p.date_range[0]}` to `{p.date_range[1]}` (`{p.calendar_days}` calendar days, `{p.trading_days}` trading days)")
        lines.append(f"- **Missing Trading Days Quote Coverage**: `{p.missing_trading_days_pct:.1%}` missing trading-day quotes")
        lines.append(f"- **Verified Publication Dates**: `{p.publication_date_availability_pct:.1%}` of observations have verified publication timestamps")
        lines.append(f"- **Observation Counts**: Total = `{p.total_observations}`, Real = `{p.real_observations_count}`, Synthetic = `{p.synthetic_observations_count}`")
        if p.classification_breakdown:
            breakdown_str = ", ".join(f"{k} = {v}" for k, v in sorted(p.classification_breakdown.items()))
            lines.append(f"- **Classification Breakdown**: `{breakdown_str}`")
        lines.append(f"- **Audit Declaration**: {p.provenance_declaration}")

    return "\n".join(lines)


def format_walk_forward_report(summary: WalkForwardSummary) -> str:
    """Generate a markdown report of a walk-forward evaluation run."""
    lines: list[str] = []
    lines.append("# Walk-Forward Chronological Evaluation Report")
    lines.append(f"**Window Type**: `{summary.config.window_type.value.upper()}`  ")
    lines.append(f"**Train Window**: `{summary.config.train_period_days} days`  ")
    lines.append(f"**Test Window**: `{summary.config.test_period_days} days`  ")
    lines.append(f"**Purge Boundary**: `{summary.config.purge_overlap_days} days`  ")
    lines.append(f"**Embargo Buffer**: `{summary.config.embargo_days} days`  ")
    lines.append(f"**Total Chronological Folds**: `{summary.total_folds}`  \n")

    lines.append("## Fold Results\n")
    lines.append("| Fold | Train Range | Test Range | IS Return | OOS Return | IS Sharpe | OOS Sharpe |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for f in summary.folds:
        s = f.split
        is_sh = f"{f.in_sample_metrics.sharpe_ratio:.2f}" if f.in_sample_metrics.sharpe_ratio is not None else "N/A"
        oos_sh = f"{f.out_of_sample_metrics.sharpe_ratio:.2f}" if f.out_of_sample_metrics.sharpe_ratio is not None else "N/A"
        lines.append(
            f"| `{s.split_index}` | `{s.train_start}` to `{s.train_end}` | `{s.test_start}` to `{s.test_end}` | "
            f"`{f.in_sample_metrics.total_return:+.2%}` | `{f.out_of_sample_metrics.total_return:+.2%}` | "
            f"`{is_sh}` | `{oos_sh}` |"
        )

    lines.append("\n## Stability Summary\n")
    lines.append(f"- **Mean In-Sample Return**: `{summary.mean_in_sample_return:+.2%}`")
    lines.append(f"- **Mean Out-of-Sample Return**: `{summary.mean_out_of_sample_return:+.2%}`")
    is_sh_str = f"{summary.mean_in_sample_sharpe:.2f}" if summary.mean_in_sample_sharpe is not None else "N/A"
    oos_sh_str = f"{summary.mean_out_of_sample_sharpe:.2f}" if summary.mean_out_of_sample_sharpe is not None else "N/A"
    lines.append(f"- **Mean In-Sample Sharpe**: `{is_sh_str}`")
    lines.append(f"- **Mean Out-of-Sample Sharpe**: `{oos_sh_str}`")
    rob_str = f"{summary.robustness_ratio:.2f}" if summary.robustness_ratio is not None else "N/A"
    lines.append(f"- **Robustness Ratio (OOS / IS)**: `{rob_str}`")

    return "\n".join(lines)
