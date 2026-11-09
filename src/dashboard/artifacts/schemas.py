"""Pydantic Validation Schemas for Authoritative Research Artifacts.

Provides strongly typed data contracts for all 23 authoritative JSON artifacts
from Phase 4 (simulation & holdout) and Phase 3 (backtesting).
Enforces structural validity, preserves full IEEE 754 precision, and explicitly
models unavailable research states.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class StrictArtifactBase(BaseModel):
    """Base model for all research artifact schemas with forward compatibility."""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=False)


# ==============================================================================
# Phase 4.1.2.2.3 Calibration & Factor Panel Schemas
# ==============================================================================


class CalibrationReportSchema(StrictArtifactBase):
    """Schema for calibration_report.json."""

    calibration_start: str
    calibration_end: str
    calibration_sample_size: int
    calibration_level_count: int
    calibration_transition_count: int
    first_calibration_level_date: str
    last_calibration_level_date: str
    first_calibration_transition_date: str
    last_calibration_transition_date: str
    holdout_start: str
    holdout_end: str
    holdout_sample_size: int
    holdout_level_count: int
    holdout_transition_count: int
    first_holdout_level_date: str
    last_holdout_level_date: str
    first_holdout_transition_date: str
    last_holdout_transition_date: str
    factor_names: List[str]
    covariance_matrix: List[List[float]]
    correlation_matrix: List[List[float]]
    factor_summaries: Dict[str, Any]
    is_sufficient: bool
    sufficiency_notes: List[str]
    availability_summary: Dict[str, Any]


class FactorPanelManifestSchema(StrictArtifactBase):
    """Schema for factor_panel_manifest.json (3 MB factor panel)."""

    factors: List[Union[str, Dict[str, Any]]]
    dates: List[str]
    level_dates: List[str]
    aligned_level_count: int
    transition_count: int
    values: Dict[str, List[float]]
    raw_levels: Dict[str, List[float]]
    canonical_levels: Optional[Dict[str, List[float]]] = None


# ==============================================================================
# Phase 4.1.2.2.3 Monte Carlo Model Comparison & Results
# ==============================================================================


class ModelComparisonItemSchema(StrictArtifactBase):
    """Single model record in model_comparison.json."""

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


class RepresentativePathSchema(StrictArtifactBase):
    """Representative path record (worst, median, best)."""

    path_id: Optional[int] = None
    steps: Optional[int] = None
    dates: Optional[List[str]] = None
    fx_rates: Optional[List[float]] = None
    borrowing_rates: Optional[List[float]] = None
    investment_rates: Optional[List[float]] = None
    regimes: Optional[List[str]] = None


class MonteCarloResultSchema(StrictArtifactBase):
    """Schema for gaussian_results, bootstrap_results, student_t_results, regime_results."""

    simulation_id: str
    config: Dict[str, Any]
    distribution_metrics: Dict[str, Any]
    convergence_report: Dict[str, Any]
    representative_paths: Dict[str, Any]
    data_manifest_digest: str
    created_at: str
    data_classification: str
    pit_mode: str
    is_executable_strategy: bool
    audit_notes: List[str]


class ConvergenceCheckpointSchema(StrictArtifactBase):
    """Single checkpoint in convergence_report.json."""

    num_paths: int
    mean_return: float
    median_return: float
    prob_loss: float
    var_95: float
    cvar_95: float
    max_drawdown_median: float
    standard_error: float


class ConvergenceReportSchema(StrictArtifactBase):
    """Schema for convergence_report.json."""

    checkpoints: List[Dict[str, Any]]
    is_converged: bool
    final_standard_error: float
    convergence_notes: str
    is_converged_mean: bool
    is_converged_median: bool
    is_converged_prob_loss: bool
    is_converged_var_95: bool
    is_converged_cvar_95: bool
    is_converged_drawdown: bool


# ==============================================================================
# Phase 4.1.2.2.3 Stress Testing & Sensitivity
# ==============================================================================


class StressScenarioItemSchema(StrictArtifactBase):
    """Single scenario record in stress_test_results.json."""

    scenario_name: str
    category: str
    fx_shock_pct: float
    borrowing_rate_shock_bps: float
    investment_rate_shock_bps: float
    spread_multiplier: float
    slippage_multiplier: float
    total_return: float
    net_profit_a: float
    pure_gross_gain_a: float
    total_financing_costs_a: float
    total_frictions_a: float
    total_cash_interest_a: float
    max_drawdown: float
    reconciliation_exact: bool


class CorrelationStressComparisonSchema(StrictArtifactBase):
    """Schema for correlation_stress_comparison.json."""

    baseline_model: str
    stressed_model: str
    num_paths: int
    method: str
    baseline_mean_return: float
    stressed_mean_return: float
    mean_return_difference: float
    baseline_median_return: float
    stressed_median_return: float
    median_return_difference: float


class FundingScenarioItemSchema(StrictArtifactBase):
    """Single funding rate scenario item in funding_sensitivity.json."""

    scenario_name: str
    shock_bps: int
    fixed_total_return: float
    floating_total_return: float
    return_difference: float
    fixed_financing_cost_a: float
    floating_financing_cost_a: float
    financing_cost_difference_a: float
    fixed_net_profit_a: float
    floating_net_profit_a: float
    net_profit_difference_a: float


class FundingSensitivitySchema(StrictArtifactBase):
    """Schema for funding_sensitivity.json."""

    baseline_borrowing_rate: float
    funding_conventions: List[str]
    shocks_bps: List[int]
    scenarios: List[FundingScenarioItemSchema]
    notes: List[str]


# ==============================================================================
# Phase 4.1.2.2.3 Holdout Diagnostics
# ==============================================================================


class HoldoutDiagnosticsSchema(StrictArtifactBase):
    """Schema for holdout_diagnostics.json (2024 out-of-sample FX diagnostics)."""

    holdout_year: int
    holdout_start: str
    holdout_end: str
    holdout_days: int
    realized_fx_volatility_annualized: float
    calibration_fx_volatility_annualized: float
    volatility_ratio: float
    volatility_regime_classification: str
    realized_cumulative_return: float
    predictive_quantile_return: float
    realized_max_drawdown: float
    predictive_quantile_drawdown: float
    rate_change_ks_stat: float
    rate_change_ks_pvalue: float
    fx_log_return_ks_stat: float
    fx_log_return_ks_pvalue: float
    correlation_shifts: Dict[str, float]
    is_within_normal_distribution_bounds: bool
    diagnostic_summary: str
    limitations_notes: List[str]


class FactorHoldoutDiagnosticsSchema(StrictArtifactBase):
    """Schema for factor_holdout_diagnostics.json."""

    holdout_year: int
    holdout_start: str
    holdout_end: str
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
    predictive_percentile_fx_volatility: float
    predictive_percentile_fx_drawdown: float
    volatility_regime_classification: str
    correlation_shifts: Dict[str, float]


class PortfolioHoldoutDiagnosticsSchema(StrictArtifactBase):
    """Schema for portfolio_holdout_diagnostics.json (explicit UNAVAILABLE status)."""

    status: str = Field(description="Must be UNAVAILABLE for 2024 strategy holdout")
    is_available: bool = Field(description="Must be False")
    reason: str
    simulated_portfolio_median_return: Optional[float] = None
    simulated_portfolio_median_drawdown: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


# ==============================================================================
# Phase 4.1.2.2.3 Data Infrastructure & Provenance
# ==============================================================================


class AvailabilityAuditSchema(StrictArtifactBase):
    """Schema for availability_audit.json."""

    total_source_observations: int
    genuine_observations_included: int
    synthetic_observations_excluded: int
    exact_timestamp_verified_count: int
    estimated_availability_count: int
    retrospective_count: int
    missing_evidence_count: int
    is_reconciled: bool
    data_classification_label: str
    pit_mode: str
    audit_scope_description: str
    release_lag_policies: Dict[str, str]
    factor_breakdown: Dict[str, Any]


class CalendarValidationSchema(StrictArtifactBase):
    """Schema for calendar_validation.json."""

    calendar_implementation: str
    session_count: int
    initial_state_zero_interest: bool
    weekend_3day_accrual_verified: bool
    holiday_accrual_verified: bool
    tenor_30day_maturity_verified: bool
    independent_numerical_accrual_verified: bool
    transitions_n_levels_n_plus_1_verified: bool
    array_lengths_verified: bool
    notes: List[str]


class SimulationManifestSchema(StrictArtifactBase):
    """Schema for simulation_manifest.json."""

    git_commit: str
    simulation_code_commit: str
    simulation_source_commit: str
    documentation_commit: str
    source_tree_digest: str
    database_sha256: str
    git_working_tree_clean: bool
    rng_bit_generator: str
    random_seed: int


# ==============================================================================
# Phase 3.2.2.3.3 Historical Backtest Configuration Schemas
# ==============================================================================


class BacktestPerformanceSchema(StrictArtifactBase):
    """Performance metrics sub-dictionary in backtest config."""

    cumulative_net_profit: float
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    max_drawdown: float
    calmar_ratio: Optional[float] = None
    var_95: Optional[float] = None
    cvar_95: Optional[float] = None
    avg_capital_utilization: Optional[float] = None
    max_exposure_a: Optional[float] = None


class BacktestAttributionSchema(StrictArtifactBase):
    """P&L attribution sub-dictionary in backtest config."""

    pure_gross_profit_a: float
    gross_trade_return: float
    fx_translation_gain_a: float
    pure_fx_return: float
    investment_yield_gain_a: float
    investment_yield_return: float
    total_financing_costs_a: float
    financing_cost_drag: float
    total_frictions_a: float
    transaction_cost_drag: float
    observed_spread_cost_a: float
    modelled_spread_cost_a: float
    slippage_cost_a: float
    total_cash_interest_a: float
    cash_yield_return: float
    reconciliation_residual_a: float
    reconciliation_exact: bool


class BacktestBenchmarkSchema(StrictArtifactBase):
    """Benchmark metrics sub-dictionary in backtest config."""

    benchmark_name: Optional[str] = None
    benchmark_total_return: Optional[float] = None
    benchmark_annualized_return: Optional[float] = None
    benchmark_sharpe_ratio: Optional[float] = None
    alpha: Optional[float] = None
    cumulative_excess_return: Optional[float] = None
    annualized_excess_return: Optional[float] = None


class BacktestTradesSchema(StrictArtifactBase):
    """Trade statistics sub-dictionary in backtest config."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_winning_trade: float
    avg_losing_trade: float
    profit_factor: Optional[float] = None
    rejected_trades_count: int


class BacktestConfigSchema(StrictArtifactBase):
    """Schema for Phase 3 backtest configs (config_1 through config_6)."""

    strategy_name: str
    currency_pair: str
    start_date: str
    end_date: str
    initial_capital_a: float
    strategy_status: str
    can_simulate: bool
    is_point_in_time_credible: bool
    pit_availability_status: str
    is_economically_representative: bool
    is_executable_strategy: bool
    unsupported_reason: Optional[str] = None
    manifest_digest: Optional[str] = None
    performance: Optional[BacktestPerformanceSchema] = None
    attribution: Optional[BacktestAttributionSchema] = None
    benchmark: Optional[BacktestBenchmarkSchema] = None
    trades: Optional[BacktestTradesSchema] = None
