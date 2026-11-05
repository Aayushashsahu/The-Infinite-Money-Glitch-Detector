"""Historical Backtesting Engine Package.

Provides:
- Historical Information Firewall (Point-in-time access, look-ahead protection)
- Execution Engine (Bid/ask spreads, slippage, fees, borrowing costs)
- Signal Generators (Unhedged carry trade, Covered carry trade)
- Capital & Portfolio Accounting (Single allocation, leverage constraints)
- Mark-to-Market Valuation & Snapshots
- Standardized Risk & Performance Metrics (Sharpe, Sortino, Calmar, VaR, CVaR)
- Benchmarks (Cash, Unhedged FX, Theoretical CIP)
- Chronological Walk-Forward Testing with Purging and Embargo
- Audit Trail and Reporting
"""

from backtesting.benchmarks import (
    CIPDiagnostic,
    compute_borrowing_currency_benchmark,
    compute_investment_currency_benchmark,
    compute_theoretical_cip_rate,
    evaluate_cip_diagnostic,
)
from backtesting.engine import BacktestEngine
from backtesting.execution import ExecutionEngine, compute_entry_execution_rate, compute_exit_execution_rate
from backtesting.financing import (
    DayCountConvention,
    calculate_accrued_liability,
    calculate_fixed_financing,
    calculate_variable_financing,
)
from backtesting.metrics import calculate_performance_metrics, calculate_sortino_ratio
from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall, PointInTimeRecord
from backtesting.portfolio import Portfolio, SizingResult
from backtesting.reporting import format_backtest_report, format_walk_forward_report
from backtesting.signals import (
    CoveredCarrySignalGenerator,
    TradingSignal,
    UnhedgedCarrySignalGenerator,
)
from backtesting.valuation import mark_position_to_market
from backtesting.walk_forward import WalkForwardEngine, WalkForwardSummary, generate_walk_forward_splits
from backtesting.calendar import MarketCalendar, DEFAULT_FX_CALENDAR
from backtesting.provenance import build_data_provenance_report

__all__ = [
    "BacktestEngine",
    "PointInTimeFirewall",
    "PointInTimeDataStore",
    "PointInTimeRecord",
    "ExecutionEngine",
    "compute_entry_execution_rate",
    "compute_exit_execution_rate",
    "Portfolio",
    "SizingResult",
    "calculate_fixed_financing",
    "calculate_variable_financing",
    "calculate_accrued_liability",
    "DayCountConvention",
    "mark_position_to_market",
    "UnhedgedCarrySignalGenerator",
    "CoveredCarrySignalGenerator",
    "TradingSignal",
    "calculate_performance_metrics",
    "calculate_sortino_ratio",
    "compute_borrowing_currency_benchmark",
    "compute_investment_currency_benchmark",
    "compute_theoretical_cip_rate",
    "evaluate_cip_diagnostic",
    "CIPDiagnostic",
    "WalkForwardEngine",
    "WalkForwardSummary",
    "generate_walk_forward_splits",
    "format_backtest_report",
    "format_walk_forward_report",
    "MarketCalendar",
    "DEFAULT_FX_CALENDAR",
    "build_data_provenance_report",
]
