"""Reporting and Audit Trail Generation for Backtesting Results.

Generates:
- Comprehensive text and markdown backtest summaries
- Trade audit logs with execution prices, spreads, fees, and PnL
- Risk and return tables with explicit metric assumptions
- Walk-forward chronological stability reports
- Data availability and look-ahead firewall compliance declarations
"""

from __future__ import annotations

from schemas.backtest import BacktestResult
from backtesting.walk_forward import WalkForwardSummary


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

    # Return attribution breakdown
    lines.append("\n## 2. Return Attribution Decomposition (Capital Denominator: Initial Equity)\n")
    lines.append("| Attribution Component | Value | Description |")
    lines.append("| :--- | :--- | :--- |")
    gross_str = f"{m.gross_trade_return:+.2%}" if m.gross_trade_return is not None else "N/A"
    lines.append(f"| **Gross Foreign Investment Gain** | `{gross_str}` | Foreign asset appreciation & interest before financing & fees |")
    fin_str = f"{-m.financing_cost_drag:+.2%}" if m.financing_cost_drag is not None else "N/A"
    lines.append(f"| **Debt Financing Drag** | `{fin_str}` | Interest paid on borrowed currency A liabilities |")
    tx_str = f"{-m.transaction_cost_drag:+.2%}" if m.transaction_cost_drag is not None else "N/A"
    lines.append(f"| **Execution Frictions Drag** | `{tx_str}` | Total bid/ask spread, slippage, and ticket fees |")
    cash_str = f"{m.cash_yield_return:+.2%}" if m.cash_yield_return is not None else "N/A"
    lines.append(f"| **Cash Yield on Unallocated Balances** | `{cash_str}` | Interest earned on cash at deposit/risk-free rate |")
    lines.append(f"| **Net Strategy Return** | `{m.total_return:+.2%}` | Gross Gain - Financing - Fees + Cash Yield |")
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

    lines.append("\n## 4. Benchmark Comparison & Risk-Free Accounting\n")
    if m.benchmark_name:
        lines.append(f"**Comparative Benchmark**: `{m.benchmark_name}`  ")
        lines.append(f"- Benchmark Total Return: `{m.benchmark_total_return:+.2%}`  ")
        lines.append(f"- Benchmark Annualized Return: `{m.benchmark_annualized_return:+.2%}`  ")
        alpha_str = f"{m.alpha:+.2%}" if m.alpha is not None else "N/A"
        lines.append(f"- Strategy Alpha (Excess Return over Cash Benchmark): `{alpha_str}`  ")
    else:
        lines.append("*No benchmark series computed (insufficient observations).*")

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
