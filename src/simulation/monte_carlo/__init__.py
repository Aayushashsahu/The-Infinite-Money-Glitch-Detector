"""Monte Carlo & Market Scenario Laboratory package.

Reusable quantitative simulation engine for macro-financial market scenarios,
empirical bootstrap, parametric distributions, regimes, stress testing, and
strategy risk evaluation.
"""

from __future__ import annotations

from simulation.monte_carlo.bootstrap import HistoricalBootstrapSampler
from simulation.monte_carlo.calibration import (
    CalibrationReport,
    FactorSummary,
    calibrate_factor_panel,
    split_calibration_holdout,
)
from simulation.monte_carlo.convergence import evaluate_convergence
from simulation.monte_carlo.distributions import (
    MultivariateGaussianModel,
    MultivariateStudentTModel,
    ensure_positive_semidefinite,
)
from simulation.monte_carlo.engine import MonteCarloEngine
from simulation.monte_carlo.factors import (
    build_fx_carry_factor_panel,
    compute_differences,
    compute_log_returns,
    reconstruct_price_levels,
    reconstruct_rate_levels,
)
from simulation.monte_carlo.metrics import calculate_distribution_metrics
from simulation.monte_carlo.regimes import (
    RegimeConditionedSampler,
    VolatilityRegimeClassifier,
)
from simulation.monte_carlo.reporting import export_json, generate_research_report
from simulation.monte_carlo.schemas import (
    BootstrapMethod,
    ConvergenceCheckpoint,
    ConvergenceReport,
    DistributionMetrics,
    DistributionQuantiles,
    FactorCategory,
    FactorObservation,
    FactorPanel,
    MarketFactor,
    ModelComparisonEntry,
    MonteCarloResult,
    PathEvaluationResult,
    RegimeState,
    ScenarioPath,
    SimulationConfig,
    SimulationModelType,
    StressScenario,
    TransformationMethod,
)
from simulation.monte_carlo.shocks import (
    apply_stress_scenario,
    build_standard_stress_scenarios,
)
from simulation.monte_carlo.strategy_adapter import (
    CarryTradeScenarioStrategy,
    ScenarioStrategy,
)

__all__ = [
    "BootstrapMethod",
    "CalibrationReport",
    "CarryTradeScenarioStrategy",
    "ConvergenceCheckpoint",
    "ConvergenceReport",
    "DistributionMetrics",
    "DistributionQuantiles",
    "FactorCategory",
    "FactorObservation",
    "FactorPanel",
    "FactorSummary",
    "HistoricalBootstrapSampler",
    "MarketFactor",
    "ModelComparisonEntry",
    "MonteCarloEngine",
    "MonteCarloResult",
    "MultivariateGaussianModel",
    "MultivariateStudentTModel",
    "PathEvaluationResult",
    "RegimeConditionedSampler",
    "RegimeState",
    "ScenarioPath",
    "ScenarioStrategy",
    "SimulationConfig",
    "SimulationModelType",
    "StressScenario",
    "TransformationMethod",
    "VolatilityRegimeClassifier",
    "apply_stress_scenario",
    "build_fx_carry_factor_panel",
    "build_standard_stress_scenarios",
    "calibrate_factor_panel",
    "calculate_distribution_metrics",
    "compute_differences",
    "compute_log_returns",
    "ensure_positive_semidefinite",
    "evaluate_convergence",
    "export_json",
    "generate_research_report",
    "reconstruct_price_levels",
    "reconstruct_rate_levels",
    "split_calibration_holdout",
]
