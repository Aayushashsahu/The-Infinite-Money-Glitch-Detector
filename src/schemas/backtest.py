"""Data contracts for Phase 3: Historical Backtesting Engine.

Defines Pydantic models for:
- Historical point-in-time data availability policies
- Trade execution parameters, costs, and slippage
- Position sizing and capital allocation constraints
- Trade records, portfolio snapshots, and lifecycle tracking
- Comprehensive risk and return metrics
- Walk-forward chronological window splitting and purging/embargo rules
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.currency import validate_currency_code
from schemas.strategy import CurrencyPair, InterestConvention
from data.schemas import Frequency, StrategyExecutabilityStatus


class AvailabilityPolicy(str, Enum):
    """Historical data availability policies.

    - STRICT: Only observations with verified publication or availability
      timestamps <= simulation timestamp T are eligible. If publication_date
      is unknown, the observation is excluded.
    - ESTIMATED_LAG: Observations without verified publication dates are
      admitted using configurable conservative availability lags based on
      data frequency or indicator-specific lag. These are explicitly tagged as
      estimated, never represented as verified.
    - RESEARCH_ONLY: Allows retrospective economic analysis (observation_date <= T).
      Strictly marked as unsuitable for executable historical backtesting.
    """

    STRICT = "strict"
    ESTIMATED_LAG = "estimated_lag"
    RESEARCH_ONLY = "research_only"


class PositionSizingMethod(str, Enum):
    """Position sizing algorithms."""

    FIXED_AMOUNT = "fixed_amount"
    PERCENT_OF_EQUITY = "percent_of_equity"
    ALL_AVAILABLE_CASH = "all_available_cash"


class TradeSide(str, Enum):
    """Direction of trade.

    LONG_B_SHORT_A: Standard carry trade — borrow currency A, convert to and invest in B.
    """

    LONG_B_SHORT_A = "long_b_short_a"


class TradeStatus(str, Enum):
    """Lifecycle state of a simulated trade."""

    OPEN = "open"
    CLOSED = "closed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class InterestRateType(str, Enum):
    """Hierarchy of interest rate definitions (never interchangeable)."""

    BORROWING = "borrowing"  # Rate charged to borrow currency A (debt liability)
    DEPOSIT = "deposit"      # Rate earned on unallocated cash balances in currency A
    POLICY = "policy"        # Central bank target / reference policy rate
    RISK_FREE = "risk_free"  # Sovereign treasury bill / risk-free benchmark yield


class InterestRateHierarchy(BaseModel):
    """Explicit interest rate specification distinguishing borrowing from deposit yields."""

    model_config = ConfigDict(extra="forbid")

    borrowing_rate: float = Field(description="Annual rate paid on borrowed currency A liabilities.")
    deposit_rate: float | None = Field(default=None, description="Annual rate earned on unencumbered cash in A.")
    policy_rate: float | None = Field(default=None, description="Central bank policy rate in A.")
    risk_free_rate: float | None = Field(default=None, description="Risk-free cash benchmark rate in A.")


class DataAvailabilityConfig(BaseModel):
    """Configuration for the Historical Information Firewall."""

    model_config = ConfigDict(extra="forbid")

    policy: AvailabilityPolicy = AvailabilityPolicy.STRICT
    # Conservative default availability lags in calendar days if publication_date is missing
    default_lags_days: dict[Frequency, int] = Field(
        default_factory=lambda: {
            Frequency.DAILY: 1,
            Frequency.WEEKLY: 7,
            Frequency.MONTHLY: 30,
            Frequency.QUARTERLY: 60,
            Frequency.ANNUAL: 120,
        }
    )
    custom_indicator_lags: dict[str, int] = Field(default_factory=dict)
    max_stale_days: int = Field(
        default=5,
        ge=1,
        description="Maximum permissible age of price/rate quote before flagging as stale and rejecting execution.",
    )
    stale_by_trading_days: bool = Field(
        default=True,
        description="Measure staleness in active trading days (excluding weekends and market holidays).",
    )
    allow_synthetic: bool = Field(
        default=False,
        description="Whether to permit synthetic observations (must be explicitly enabled for unit tests).",
    )


class ExecutionConfig(BaseModel):
    """Execution frictions, spreads, fees, and constraints."""

    model_config = ConfigDict(extra="forbid")

    bid_ask_spread_bps: float = Field(
        default=5.0,
        ge=0.0,
        le=10_000.0,
        description="Total bid-ask spread in basis points of exchange rate (half-spread applied to each conversion leg).",
    )
    slippage_bps: float = Field(
        default=0.0,
        ge=0.0,
        le=10_000.0,
        description="Execution slippage in basis points applied adversely to conversion rates.",
    )
    fixed_fee: float = Field(
        default=0.0,
        ge=0.0,
        description="Flat transaction fee in borrowing currency A per round-trip.",
    )
    variable_fee_bps: float = Field(
        default=0.0,
        ge=0.0,
        le=10_000.0,
        description="Variable broker/exchange fee in basis points charged on notional converted.",
    )
    interest_convention: InterestConvention = InterestConvention.COMPOUND
    min_trade_size_a: float = Field(default=1_000.0, gt=0.0, description="Minimum trade size in currency A.")
    max_trade_size_a: float = Field(default=10_000_000.0, gt=0.0, description="Maximum trade size in currency A.")


class PositionSizingConfig(BaseModel):
    """Position sizing rules and capital constraints."""

    model_config = ConfigDict(extra="forbid")

    method: PositionSizingMethod = PositionSizingMethod.FIXED_AMOUNT
    fixed_amount: float = Field(default=100_000.0, gt=0.0, description="Nominal amount in currency A.")
    percent_of_equity: float = Field(
        default=1.0,
        gt=0.0,
        le=1.0,
        description="Fraction of available portfolio equity to allocate per trade.",
    )
    max_leverage: float = Field(
        default=1.0,
        gt=0.0,
        le=10.0,
        description="Maximum gross exposure as multiple of equity.",
    )
    max_active_positions: int = Field(
        default=1,
        ge=1,
        description="Maximum number of simultaneous active positions allowed.",
    )


class TradeRecord(BaseModel):
    """Audit record of one trade throughout its lifecycle."""

    model_config = ConfigDict(extra="forbid")

    trade_id: str
    strategy_name: str
    currency_pair: CurrencyPair
    borrowing_currency: str
    investment_currency: str
    side: TradeSide = TradeSide.LONG_B_SHORT_A
    entry_date: date
    exit_date: date | None = None
    target_tenor_days: int
    actual_tenor_days: int | None = None

    # Principal and rates
    principal_borrowed_a: float = Field(ge=0.0)
    borrowing_rate: float
    investment_rate: float

    # Execution prices (units of A per unit of B)
    spot_mid_entry: float = Field(gt=0.0)
    spot_exec_entry: float = Field(gt=0.0, description="Effective entry exchange rate after spread and slippage.")
    invested_amount_b: float = Field(default=0.0, ge=0.0)

    # For covered trades
    is_covered: bool = False
    forward_exec_rate: float | None = None

    # Exit values
    spot_mid_exit: float | None = None
    spot_exec_exit: float | None = None
    investment_gross_value_b: float | None = None
    converted_back_a: float | None = None
    loan_repayment_a: float | None = None
    interest_paid_a: float | None = None

    # Frictions and PnL breakdown
    pure_gross_gain_a: float = 0.0
    financing_cost_a: float = 0.0
    entry_spread_cost_a: float = 0.0
    entry_slippage_cost_a: float = 0.0
    entry_fees_a: float = 0.0
    exit_spread_cost_a: float = 0.0
    exit_slippage_cost_a: float = 0.0
    exit_fees_a: float = 0.0
    fixed_fee_a: float = 0.0
    total_frictions_a: float = 0.0
    transaction_costs_a: float = 0.0
    slippage_costs_a: float = 0.0
    net_profit_a: float | None = None
    reconciliation_residual_a: float = 0.0
    return_on_capital: float | None = None
    annualized_return: float | None = None

    # Status
    status: TradeStatus = TradeStatus.OPEN
    rejection_reason: str | None = None
    is_availability_verified: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class PortfolioSnapshot(BaseModel):
    """State of portfolio at simulation timestamp T."""

    model_config = ConfigDict(extra="forbid")

    as_of: date
    cash_a: float
    total_borrowed_a: float
    total_obligations_a: float
    active_positions_count: int
    positions_value_a: float
    equity_a: float
    leverage: float
    unrealized_pnl_a: float
    realized_pnl_a: float
    capital_utilization: float


class PerformanceMetrics(BaseModel):
    """Standardized performance and risk evaluation metrics."""

    model_config = ConfigDict(extra="forbid")

    total_trades: int
    winning_trades: int
    losing_trades: int
    break_even_trades: int
    win_rate: float = Field(description="winning_trades / total_trades")
    
    cumulative_net_profit: float = Field(description="Total realized net profit in borrowing currency A.")
    total_return: float = Field(description="Cumulative net profit relative to initial equity.")
    annualized_return: float = Field(description="Annualized compounded or simple return.")
    annualized_volatility: float = Field(description="Annualized sample standard deviation of period returns.")
    
    sharpe_ratio: float | None = Field(description="Annualized Sharpe ratio over risk-free rate.")
    sortino_ratio: float | None = Field(description="Annualized Sortino ratio penalizing downside volatility only.")
    max_drawdown: float = Field(description="Maximum peak-to-trough equity decline as a negative fraction.")
    calmar_ratio: float | None = Field(description="Annualized return divided by absolute max drawdown.")
    
    avg_winning_trade: float = 0.0
    avg_losing_trade: float = 0.0
    profit_factor: float | None = Field(default=None, description="Gross winning profit / abs(gross losing loss).")
    
    var_95: float = Field(description="Historical 95% Value at Risk (lower quantile).")
    cvar_95: float = Field(description="Historical 95% Conditional VaR (Expected Shortfall).")
    
    avg_capital_utilization: float = Field(description="Average ratio of invested capital to total equity.")
    max_exposure_a: float = Field(description="Peak total borrowed exposure in currency A.")

    # Return attribution decomposition (relative to initial capital)
    gross_trade_return: float | None = Field(default=None, description="Gross foreign investment & FX move return / initial capital.")
    financing_cost_drag: float | None = Field(default=None, description="Total debt financing costs / initial capital.")
    transaction_cost_drag: float | None = Field(default=None, description="Total spreads, fees, and slippage / initial capital.")
    cash_yield_return: float | None = Field(default=None, description="Interest earned on unallocated cash balance / initial capital.")
    position_annualized_volatility: float | None = Field(
        default=None,
        description="Annualized volatility computed on deployed position capital rather than total equity.",
    )

    # Exact double-entry accounting reconciliation
    pure_gross_profit_a: float = 0.0
    total_financing_costs_a: float = 0.0
    total_frictions_a: float = 0.0
    total_cash_interest_a: float = 0.0
    reconciliation_residual_a: float = 0.0
    reconciliation_exact: bool = True

    # Benchmark comparisons
    benchmark_name: str | None = None
    benchmark_total_return: float | None = None
    benchmark_annualized_return: float | None = None
    benchmark_sharpe_ratio: float | None = None
    alpha: float | None = Field(default=None, description="Strategy return minus benchmark return.")
    annualized_excess_return: float | None = Field(default=None, description="Strategy annualized return minus benchmark annualized return.")
    cumulative_excess_return: float | None = Field(default=None, description="Strategy total return minus benchmark total return.")

    metric_assumptions: dict[str, str] = Field(
        default_factory=dict,
        description="Explicit documentation of formulas, compounding rules, and annualization factors.",
    )


class DataProvenanceReport(BaseModel):
    """Complete provenance and traceability report for historical backtest observations."""

    model_config = ConfigDict(extra="forbid")

    source_providers: list[str] = Field(default_factory=list)
    dataset_identifiers: list[str] = Field(default_factory=list)
    currency_pair: str
    date_range: tuple[date, date]
    observation_frequency: Frequency
    publication_date_availability_pct: float
    point_in_time_policy: AvailabilityPolicy
    calendar_days: int
    trading_days: int
    missing_trading_days_pct: float
    total_observations: int
    real_observations_count: int
    synthetic_observations_count: int
    real_verified_count: int = 0
    real_estimated_count: int = 0
    real_retrospective_count: int = 0
    classification_breakdown: dict[str, int] = Field(default_factory=dict)
    is_synthetic_dataset: bool
    provenance_declaration: str


class WalkForwardWindowType(str, Enum):
    EXPANDING = "expanding"
    ROLLING = "rolling"


class WalkForwardConfig(BaseModel):
    """Configuration for walk-forward and out-of-sample evaluation."""

    model_config = ConfigDict(extra="forbid")

    window_type: WalkForwardWindowType = WalkForwardWindowType.ROLLING
    train_period_days: int = Field(gt=0, description="Length of training window in calendar days.")
    test_period_days: int = Field(gt=0, description="Length of out-of-sample test window in calendar days.")
    validation_period_days: int = Field(default=0, ge=0, description="Optional validation window length.")
    step_days: int = Field(gt=0, description="Step size to advance window in days.")
    purge_overlap_days: int = Field(
        default=30,
        ge=0,
        description="Purge window length to eliminate trades that span the boundary.",
    )
    embargo_days: int = Field(
        default=5,
        ge=0,
        description="Buffer period between training and test sets to prevent autocorrelation leakage.",
    )


class WalkForwardSplit(BaseModel):
    """One chronological split window."""

    model_config = ConfigDict(extra="forbid")

    split_index: int
    train_start: date
    train_end: date
    validation_start: date | None = None
    validation_end: date | None = None
    test_start: date
    test_end: date
    purged_range: tuple[date, date] | None = None
    embargo_range: tuple[date, date] | None = None


class BacktestConfig(BaseModel):
    """Complete specification of a historical backtest run."""

    model_config = ConfigDict(extra="forbid")

    strategy_name: str
    currency_pair: CurrencyPair
    start_date: date
    end_date: date
    initial_capital_a: float = Field(default=100_000.0, gt=0.0)
    tenor_days: int = Field(default=30, gt=0, description="Holding period per trade in calendar days.")
    rebalance_frequency_days: int = Field(default=30, gt=0)
    
    availability_config: DataAvailabilityConfig = Field(default_factory=DataAvailabilityConfig)
    execution_config: ExecutionConfig = Field(default_factory=ExecutionConfig)
    position_sizing: PositionSizingConfig = Field(default_factory=PositionSizingConfig)

    # Cash and funding assumptions
    cash_deposit_rate_annual: float = Field(
        default=0.0,
        ge=0.0,
        description="Annual interest rate earned on unencumbered cash balance in borrowing currency A.",
    )
    simulate_trading_days_only: bool = Field(
        default=True,
        description="Advance simulation strictly on active FX trading days (skipping weekends and market holidays).",
    )

    # Strategy specific parameters
    hurdle_rate_annual: float = Field(
        default=0.01,
        description="Minimum annualized interest differential required to trigger entry.",
    )
    volatility_filter_max: float | None = Field(
        default=None,
        description="Optional maximum annualized FX volatility threshold above which trades are rejected.",
    )
    borrowing_rate_series_id: str | None = Field(
        default=None,
        description="Optional explicit indicator_id for borrowing rate (e.g. 'DGS3MO').",
    )
    investment_rate_series_id: str | None = Field(
        default=None,
        description="Optional explicit indicator_id for foreign investment rate (e.g. 'KR.DFR.LEV').",
    )

    @model_validator(mode="after")
    def _validate_dates(self) -> "BacktestConfig":
        if self.start_date >= self.end_date:
            raise ValueError(
                f"start_date ({self.start_date}) must be strictly before end_date ({self.end_date})."
            )
        return self


class BacktestResult(BaseModel):
    """Full auditable output of a backtest run."""

    model_config = ConfigDict(extra="forbid")

    config: BacktestConfig
    trades: list[TradeRecord]
    snapshots: list[PortfolioSnapshot]
    metrics: PerformanceMetrics
    provenance: DataProvenanceReport | None = None
    rejections: list[dict[str, Any]] = Field(default_factory=list)
    data_quality_flags: list[dict[str, Any]] = Field(default_factory=list)
    audit_trail: list[str] = Field(default_factory=list)
    strategy_status: StrategyExecutabilityStatus = StrategyExecutabilityStatus.EXECUTABLE_VALIDATED
    manifest_digest: str | None = None
    is_executable_strategy: bool = True
    unsupported_reason: str | None = None
