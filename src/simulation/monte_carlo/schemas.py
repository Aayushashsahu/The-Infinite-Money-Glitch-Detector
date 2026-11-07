"""Schemas and data contracts for the Monte Carlo & Market Scenario Laboratory.

Defines factor models, simulation configurations, scenario paths, deterministic
stress scenarios, strategy evaluation contracts, and distributional risk metrics.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from data.schemas import DataClassification, Frequency


class FactorCategory(str, Enum):
    """Economic categories of market factors."""

    FX_RETURN = "fx_return"
    INTEREST_RATE_CHANGE = "interest_rate_change"
    SOVEREIGN_YIELD_CHANGE = "sovereign_yield_change"
    BORROWING_RATE_CHANGE = "borrowing_rate_change"
    INVESTMENT_RETURN = "investment_return"
    INFLATION = "inflation"
    FUNDING_SPREAD = "funding_spread"
    LIQUIDITY = "liquidity"
    VOLATILITY = "volatility"


class TransformationMethod(str, Enum):
    """Mathematical transformations applied to raw market observations."""

    LOG_RETURN = "log_return"                   # r_t = ln(S_t / S_{t-1})
    FIRST_DIFFERENCE = "first_difference"       # Delta x_t = x_t - x_{t-1}
    FIRST_DIFFERENCE_BPS = "first_diff_bps"     # (x_t - x_{t-1}) * 100 (basis points)
    PERCENTAGE_CHANGE = "pct_change"           # (x_t - x_{t-1}) / x_{t-1}
    LEVEL = "level"                             # raw level (no transformation)


class MissingDataTreatment(str, Enum):
    """Policy for missing or unaligned factor observations."""

    REJECT = "reject"                           # Reject sample if any required observation missing
    PIECEWISE_CONSTANT = "piecewise_constant"   # Hold last known rate level (valid for policy rates)
    COMMON_DATES_ONLY = "common_dates_only"     # Intersect source calendars (complete cases)


class SimulationModelType(str, Enum):
    """Mathematical simulation model engine."""

    HISTORICAL_BOOTSTRAP = "historical_bootstrap"
    MULTIVARIATE_STUDENT_T = "multivariate_student_t"
    MULTIVARIATE_GAUSSIAN = "multivariate_gaussian"
    REGIME_CONDITIONED_BOOTSTRAP = "regime_conditioned_bootstrap"
    DETERMINISTIC_STRESS = "deterministic_stress"


class BootstrapMethod(str, Enum):
    """Non-parametric resampling methodology."""

    IID = "iid"                                 # Independent identically distributed resampling
    MOVING_BLOCK = "moving_block"               # Fixed-length contiguous blocks
    STATIONARY = "stationary"                   # Politis & Romano (1994) geometric block lengths


class RegimeState(str, Enum):
    """Observable market volatility regimes."""

    LOW_VOLATILITY = "LOW_VOLATILITY"
    NORMAL_VOLATILITY = "NORMAL_VOLATILITY"
    STRESS_VOLATILITY = "STRESS_VOLATILITY"

    # Backward compatibility aliases
    HIGH_VOLATILITY = "NORMAL_VOLATILITY"
    STRESS = "STRESS_VOLATILITY"

    @classmethod
    def _missing_(cls, value: object) -> RegimeState | None:
        if isinstance(value, str):
            v_upper = value.upper()
            if v_upper in cls._value2member_map_:
                return cls._value2member_map_[v_upper]
            if v_upper in ("HIGH_VOLATILITY", "HIGH"):
                return cls.NORMAL_VOLATILITY
            if v_upper in ("STRESS", "STRESS_VOLATILITY"):
                return cls.STRESS_VOLATILITY
            if v_upper in ("LOW", "LOW_VOLATILITY"):
                return cls.LOW_VOLATILITY
            if v_upper in ("NORMAL", "NORMAL_VOLATILITY"):
                return cls.NORMAL_VOLATILITY
        return None


class PITMode(str, Enum):
    """Point-in-time data availability policy modes."""

    STRICT_VERIFIED = "STRICT_VERIFIED"
    ESTIMATED_LAG = "ESTIMATED_LAG"
    RESEARCH_ONLY = "RESEARCH_ONLY"


# =============================================================================
# Market Factor Definitions & Panel
# =============================================================================


class MarketFactor(BaseModel):
    """Metadata specification for a single economic market factor."""

    model_config = ConfigDict(frozen=True)

    factor_id: str = Field(description="Unique factor identifier, e.g. 'FX_EUR_USD_LOGRET'")
    category: FactorCategory = Field(description="Economic category of the factor")
    asset_or_currency: str = Field(description="Currency pair or asset symbol, e.g. 'EUR/USD'")
    frequency: Frequency = Field(default=Frequency.DAILY, description="Observation frequency")
    original_unit: str = Field(description="Unit of raw source data, e.g. 'USD_per_EUR', 'percent'")
    normalized_unit: str = Field(description="Unit of transformed factor, e.g. 'log_return', 'basis_points'")
    source_id: str = Field(description="Primary data provider, e.g. 'frankfurter', 'ecb', 'us_treasury'")
    series_id: str | None = Field(default=None, description="Source indicator or series code")
    transformation: TransformationMethod = Field(description="Mathematical transformation applied")
    missing_data_treatment: MissingDataTreatment = Field(
        default=MissingDataTreatment.COMMON_DATES_ONLY,
        description="Missing data resolution strategy",
    )
    calibration_start: date | None = Field(default=None, description="Calibration start date")
    calibration_end: date | None = Field(default=None, description="Calibration end date")
    description: str = Field(default="", description="Human-readable description of factor semantics")


class FactorRowProvenance(BaseModel):
    """Row-level audit provenance for a factor observation."""

    model_config = ConfigDict(frozen=True)

    observation_date: date
    observation_timestamp: datetime | None = None
    publication_timestamp: datetime | None = None
    source_id: str
    series_id: str
    raw_value: float
    transformed_value: float
    data_classification: DataClassification = DataClassification.REAL_VERIFIED
    availability_evidence: str | None = None
    revision: int | None = None


class FactorObservation(BaseModel):
    """A single transformed factor observation."""

    model_config = ConfigDict(frozen=True)

    observation_date: date
    observation_timestamp: datetime
    availability_timestamp: datetime
    raw_value: float
    transformed_value: float
    data_classification: DataClassification = DataClassification.REAL_VERIFIED
    availability_evidence: str | None = None
    revision: int | None = None


class FactorPanel(BaseModel):
    """A synchronized, calendar-aligned panel of market factors."""

    factors: list[MarketFactor]
    dates: list[date]
    values: dict[str, list[float]] = Field(
        description="Factor ID -> transformed factor time series (length == len(dates))"
    )
    raw_levels: dict[str, list[float]] = Field(
        description="Factor ID -> raw level time series (length == len(dates))"
    )
    calendar_name: str = Field(default="TARGET2_USFED_JOINT", description="Name of alignment calendar")
    effective_sample_size: int = Field(description="Number of aligned observation dates")
    is_aligned: bool = Field(default=True, description="True if complete cases across all factors")
    alignment_audit: list[str] = Field(default_factory=list, description="Audit log of alignment operations")
    row_provenance: dict[str, list[FactorRowProvenance]] = Field(
        default_factory=dict,
        description="Factor ID -> row-level audit provenance for each transformed observation",
    )
    pit_mode: str = Field(
        default="ESTIMATED_LAG",
        description="Point-in-time availability policy mode used to construct the panel",
    )


# =============================================================================
# Simulation Configurations & Scenario Paths
# =============================================================================


class SimulationConfig(BaseModel):
    """Configuration for a Monte Carlo simulation run."""

    simulation_id: str = Field(default="", description="Unique identifier for the simulation")
    pit_mode: PITMode = Field(
        default=PITMode.ESTIMATED_LAG,
        description="Point-in-time data availability policy mode",
    )
    model_type: SimulationModelType = Field(
        default=SimulationModelType.HISTORICAL_BOOTSTRAP,
        description="Simulation generator type",
    )
    bootstrap_method: BootstrapMethod = Field(
        default=BootstrapMethod.MOVING_BLOCK,
        description="Bootstrap method if using bootstrap model",
    )
    block_size: int = Field(default=20, ge=1, description="Block length in steps (for moving block or stationary)")
    num_paths: int = Field(default=1000, ge=1, description="Number of independent simulation paths")
    horizon_steps: int = Field(default=252, ge=1, description="Number of simulation steps (e.g. 252 trading days)")
    random_seed: int = Field(default=42, description="Random seed for reproducible RNG streams")

    # Parametric distribution settings
    degrees_of_freedom: float | None = Field(
        default=None,
        description="Degrees of freedom for multivariate Student-t (fitted or specified)",
    )
    shrinkage_factor: float = Field(default=0.0, ge=0.0, le=1.0, description="Ledoit-Wolf covariance shrinkage")

    # Regime settings
    regime_method: str | None = Field(default=None, description="Regime classification method")
    regime_rolling_window: int = Field(default=63, ge=5, description="Window in days for volatility regimes")

    # Initial asset & rate states
    initial_fx_rate: float = Field(default=1.09, gt=0.0, description="Initial FX rate (provider quote currency per base)")
    initial_borrowing_rate: float = Field(default=0.04, ge=0.0, description="Initial annual borrowing rate")
    initial_investment_rate: float = Field(default=0.05, ge=0.0, description="Initial annual investment yield")

    # Calibration & Holdout windows
    calibration_start_date: date = Field(default=date(2020, 1, 1))
    calibration_end_date: date = Field(default=date(2023, 12, 31))
    holdout_start_date: date | None = Field(default=date(2024, 1, 1))
    holdout_end_date: date | None = Field(default=date(2024, 12, 31))


class ScenarioPath(BaseModel):
    """A single simulated market path across the simulation horizon."""

    path_id: int
    steps: int
    dates: list[date] | None = None
    fx_rates: list[float] = Field(description="Simulated FX exchange rates (strictly positive)")
    borrowing_rates: list[float] = Field(description="Simulated annual borrowing interest rates")
    investment_rates: list[float] = Field(description="Simulated annual investment yields")
    regimes: list[str] | None = None
    is_synthetic: bool = True
    classification: DataClassification = DataClassification.SIMULATED


# =============================================================================
# Deterministic Stress Scenarios
# =============================================================================


class StressScenario(BaseModel):
    """Specification of a deterministic macro-financial stress scenario."""

    name: str
    description: str
    category: str = Field(default="single_factor", description="'single_factor', 'compound', 'liquidity', 'correlation', 'jump'")
    fx_shock_pct: float = Field(default=0.0, description="Instantaneous fractional FX price change on investment currency B")
    borrowing_rate_shock_bps: float = Field(default=0.0, description="Borrowing rate change in basis points")
    investment_rate_shock_bps: float = Field(default=0.0, description="Investment yield change in basis points")
    spread_multiplier: float = Field(default=1.0, ge=0.1, description="Bid/ask spread expansion factor")
    slippage_multiplier: float = Field(default=1.0, ge=0.1, description="Execution slippage expansion factor")
    correlation_breakdown: bool = Field(default=False, description="True if stress decouples historical correlations")
    is_hypothetical: bool = Field(default=True, description="Always True; stress tests are hypothetical")

    # Shock timing contract
    shock_timing: str = Field(
        default="after_entry",
        description="Shock timing: 'pre_entry', 'after_entry', 'at_step', 'persistent'",
    )
    shock_step: int = Field(
        default=5,
        ge=0,
        description="Step index at which instantaneous or persistent shock takes effect",
    )
    is_persistent: bool = Field(
        default=True,
        description="True if shock persistently shifts subsequent path price levels",
    )
    reversal_step: int | None = Field(
        default=None,
        description="Optional step index at which the shock recovers to baseline",
    )


# =============================================================================
# Strategy Evaluation Results & Metrics
# =============================================================================


class PathEvaluationResult(BaseModel):
    """Evaluation of a financial strategy along a single scenario path."""

    path_id: int
    terminal_equity: float
    total_return: float
    annualized_return: float
    annualized_volatility: float
    max_drawdown: float
    sharpe_ratio: float | None = None

    # Return attribution decomposition (Double-entry cash ledger)
    pure_gross_gain_a: float = 0.0
    fx_translation_gain_a: float = 0.0
    investment_yield_gain_a: float = 0.0
    total_financing_costs_a: float = 0.0
    total_frictions_a: float = 0.0
    total_cash_interest_a: float = 0.0
    cumulative_net_profit_a: float = 0.0
    reconciliation_residual_a: float = 0.0
    reconciliation_exact: bool = True

    # Tail risk event flags
    is_loss: bool = False
    breached_drawdown_5pct: bool = False
    breached_drawdown_10pct: bool = False
    breached_drawdown_20pct: bool = False
    capital_utilization: float = 0.0
    peak_exposure_a: float = 0.0


class DistributionQuantiles(BaseModel):
    """Statistical quantiles of a simulation metric."""

    p01: float
    p05: float
    p10: float
    p25: float
    p50: float  # Median
    p75: float
    p90: float
    p95: float
    p99: float
    mean: float
    std: float
    skewness: float
    excess_kurtosis: float


class DistributionMetrics(BaseModel):
    """Aggregated distributional risk and performance metrics across all paths."""

    num_paths: int
    horizon_steps: int

    # Equity & Return Distributions
    terminal_equity: DistributionQuantiles
    total_return: DistributionQuantiles
    annualized_return: DistributionQuantiles
    max_drawdown: DistributionQuantiles
    annualized_volatility: DistributionQuantiles

    # Risk Metrics
    var_95: float = Field(description="Value at Risk (empirical 5th percentile of return)")
    cvar_95: float = Field(description="Conditional VaR / Expected Shortfall below 5th percentile")

    # Probabilities with Monte Carlo Standard Errors: SE = sqrt(p * (1 - p) / N)
    prob_loss: float
    prob_loss_se: float
    prob_loss_ci_lower: float
    prob_loss_ci_upper: float

    prob_drawdown_5pct: float
    prob_drawdown_5pct_se: float
    prob_drawdown_10pct: float
    prob_drawdown_10pct_se: float
    prob_drawdown_20pct: float
    prob_drawdown_20pct_se: float

    # Attribution Breakdown (Means across paths)
    mean_pure_gross_gain_a: float
    mean_fx_translation_gain_a: float
    mean_investment_yield_gain_a: float
    mean_financing_costs_a: float
    mean_frictions_a: float
    mean_cash_interest_a: float
    mean_net_profit_a: float
    mean_reconciliation_residual_a: float
    all_paths_reconciled: bool = True


class ConvergenceCheckpoint(BaseModel):
    """Convergence statistics at a specific path checkpoint count."""

    sample_size: int
    mean_return: float
    median_return: float
    prob_loss: float
    prob_loss_se: float
    var_95: float
    cvar_95: float
    std_return: float
    max_drawdown_median: float = 0.0
    prob_drawdown_10pct: float = 0.0
    tail_sample_size: int = 0
    var_95_se: float = 0.0
    cvar_95_se: float = 0.0


class ConvergenceReport(BaseModel):
    """Evaluation of Monte Carlo sampling stability across increasing path counts."""

    checkpoints: list[ConvergenceCheckpoint]
    is_converged: bool = True
    final_standard_error: float
    convergence_notes: str = ""
    is_converged_mean: bool = True
    is_converged_median: bool = True
    is_converged_prob_loss: bool = True
    is_converged_var_95: bool = True
    is_converged_cvar_95: bool = True
    is_converged_drawdown: bool = True
    tail_sample_size_final: int = 0
    stability_status: str = "CHECKPOINT_STABILITY"
    limitations: list[str] = Field(default_factory=list)


class CalibrationAvailabilitySummary(BaseModel):
    """Audited breakdown of historical calibration availability."""

    total_genuine_observations: int = 0
    exact_timestamp_verified_count: int = 0
    estimated_availability_count: int = 0
    retrospective_count: int = 0
    missing_evidence_count: int = 0
    unrecognized_evidence_count: int = 0
    excluded_synthetic_count: int = 0
    complete_aligned_factor_days: int = 0
    is_reconciled: bool = True
    data_classification_label: str = "SIMULATED_RESEARCH_PROXY"


class AvailabilityAuditReport(BaseModel):
    """Exhaustive point-in-time availability and data provenance reconciliation audit."""

    total_source_observations: int = 0
    genuine_observations_included: int = 0
    synthetic_observations_excluded: int = 0
    date_window_exclusions: int = 0
    classification_exclusions: int = 0
    factor_alignment_exclusions: int = 0
    exact_timestamp_verified_count: int = 0
    estimated_availability_count: int = 0
    retrospective_count: int = 0
    missing_evidence_count: int = 0
    unrecognized_evidence_count: int = 0
    is_reconciled: bool = True
    data_classification_label: str = "SIMULATED_RESEARCH_PROXY"
    pit_mode: str = "ESTIMATED_LAG"
    audit_scope_description: str = ""
    release_lag_policies: dict[str, str] = Field(default_factory=dict)
    factor_breakdown: dict[str, dict[str, Any]] = Field(default_factory=dict)


class FactorHoldoutDiagnostics(BaseModel):
    """Factor-level predictive validation against untouched 2024 holdout dataset."""

    holdout_year: int = 2024
    holdout_start: date
    holdout_end: date
    holdout_days: int
    num_predictive_paths: int
    actual_fx_cumulative_return: float
    actual_fx_realized_volatility: float
    actual_fx_max_drawdown: float
    simulated_fx_return_median: float
    simulated_fx_return_p025: float
    simulated_fx_return_p975: float
    simulated_fx_volatility_median: float
    simulated_fx_drawdown_median: float
    predictive_percentile_fx_return: float
    predictive_percentile_fx_return_mc_se: float
    predictive_percentile_fx_volatility: float
    predictive_percentile_fx_drawdown: float
    volatility_regime_classification: str
    low_vol_threshold: float = 0.0
    high_vol_threshold: float = 0.0
    fx_log_return_ks_stat: float
    fx_log_return_ks_pvalue: float
    fx_log_return_ks_caveat: str = ""
    correlation_shifts: dict[str, float] = Field(default_factory=dict)
    model_assumptions: list[str] = Field(default_factory=list)
    limitations_notes: list[str] = Field(default_factory=list)


class PortfolioHoldoutDiagnostics(BaseModel):
    """Strategy portfolio holdout comparison diagnostics (explicitly unavailable if unobserved)."""

    status: str = "UNAVAILABLE"
    is_available: bool = False
    reason: str = (
        "No genuine historical executable portfolio series exists for 2024 holdout; "
        "strategy remains SIMULATED_RESEARCH_PROXY without live execution evidence."
    )
    simulated_portfolio_median_return: float | None = None
    simulated_portfolio_median_drawdown: float | None = None
    notes: list[str] = Field(default_factory=list)


class CorrelationStressComparison(BaseModel):
    """Comparative distribution analysis between baseline and decorrelated stress structures."""

    baseline_model: str
    stressed_model: str
    num_paths: int
    method: str = "zero_off_diagonal_decoupling_with_common_random_numbers"
    baseline_mean_return: float
    stressed_mean_return: float
    mean_return_difference: float
    baseline_median_return: float
    stressed_median_return: float
    median_return_difference: float
    baseline_prob_loss: float
    stressed_prob_loss: float
    prob_loss_difference: float
    prob_loss_difference_se: float = 0.0
    baseline_var_95: float
    stressed_var_95: float
    var_95_difference: float
    baseline_cvar_95: float
    stressed_cvar_95: float
    cvar_95_difference: float
    baseline_median_drawdown: float
    stressed_median_drawdown: float
    median_drawdown_difference: float
    baseline_mean_financing_cost_a: float
    stressed_mean_financing_cost_a: float
    financing_cost_difference_a: float
    baseline_mean_fx_translation_a: float
    stressed_mean_fx_translation_a: float
    fx_translation_difference_a: float
    paired_return_difference_mean: float
    paired_return_difference_std: float
    paired_return_difference_p05: float
    paired_return_difference_p50: float
    paired_return_difference_p95: float
    marginal_means_preserved: bool = True
    marginal_variances_preserved: bool = True
    is_psd_repaired: bool = False
    psd_repair_frobenius_norm: float = 0.0
    empirical_correlation_matrix: list[list[float]] = Field(default_factory=list)
    stressed_correlation_matrix: list[list[float]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class CalendarValidationReport(BaseModel):
    """Validation report verifying simulated trading calendar and financing accrual mechanics."""

    calendar_implementation: str
    session_count: int
    initial_state_zero_interest: bool
    weekend_3day_accrual_verified: bool
    holiday_accrual_verified: bool
    tenor_30day_maturity_verified: bool
    independent_numerical_accrual_verified: bool
    transitions_n_levels_n_plus_1_verified: bool
    array_lengths_verified: bool
    notes: list[str] = Field(default_factory=list)


class FundingSensitivityReport(BaseModel):
    """Sensitivity study contrasting fixed-rate borrowing vs floating-rate reset funding."""

    baseline_borrowing_rate: float
    funding_conventions: list[str]
    shocks_bps: list[int]
    scenarios: list[dict[str, Any]]
    notes: list[str] = Field(default_factory=list)


class InitialMarketLevelsReport(BaseModel):
    """Provenance and grounding report for initial simulation market state."""

    as_of_decision_timestamp: datetime
    pit_mode: str
    initial_fx_rate: float
    initial_borrowing_rate: float
    initial_investment_rate: float
    fx_observation_date: date
    fx_availability_timestamp: datetime | None = None
    fx_source_id: str
    fx_entity_code: str
    fx_raw_value: float
    borrowing_observation_date: date
    borrowing_availability_timestamp: datetime | None = None
    borrowing_source_id: str
    borrowing_indicator_id: str
    borrowing_raw_value: float
    investment_observation_date: date
    investment_availability_timestamp: datetime | None = None
    investment_source_id: str
    investment_indicator_id: str
    investment_raw_value: float
    grounding_notes: list[str] = Field(default_factory=list)


class HoldoutDiagnosticReport(BaseModel):
    """Out-of-sample diagnostic validation against untouched holdout dataset."""

    holdout_year: int = 2024
    holdout_start: date
    holdout_end: date
    holdout_days: int
    realized_fx_volatility_annualized: float
    calibration_fx_volatility_annualized: float
    volatility_ratio: float
    volatility_regime_classification: str
    realized_cumulative_return: float
    predictive_quantile_return: float
    realized_max_drawdown: float
    predictive_quantile_drawdown: float
    rate_change_ks_stat: float | None = None
    rate_change_ks_pvalue: float | None = None
    fx_log_return_ks_stat: float | None = None
    fx_log_return_ks_pvalue: float | None = None
    correlation_shifts: dict[str, float] = Field(default_factory=dict)
    is_within_normal_distribution_bounds: bool = True
    diagnostic_summary: str = ""
    limitations_notes: list[str] = Field(default_factory=list)


class ModelComparisonEntry(BaseModel):
    """Summary metrics of a specific simulation model for comparative risk analysis."""

    model_name: str
    num_paths: int
    median_return: float
    mean_return: float
    std_return: float
    var_95: float
    cvar_95: float
    max_drawdown_median: float
    max_drawdown_p95: float
    prob_loss: float
    prob_loss_se: float
    prob_drawdown_10pct: float
    mean_fx_drag: float
    mean_financing_drag: float


class MonteCarloResult(BaseModel):
    """Complete root artifact of a Monte Carlo simulation experiment."""

    simulation_id: str
    config: SimulationConfig
    distribution_metrics: DistributionMetrics
    convergence_report: ConvergenceReport | None = None
    representative_paths: dict[str, ScenarioPath] = Field(
        default_factory=dict,
        description="'best', 'median', 'worst' representative scenario paths",
    )
    data_manifest_digest: str | None = None
    git_commit: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    data_classification: DataClassification = DataClassification.SIMULATED
    pit_mode: str = "ESTIMATED_LAG"
    is_executable_strategy: bool = False
    audit_notes: list[str] = Field(default_factory=list)
