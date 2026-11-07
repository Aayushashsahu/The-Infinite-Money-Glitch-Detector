"""Monte Carlo Simulation Engine orchestrator.

Coordinates factor panel extraction, model calibration, scenario path generation,
strategy evaluation, distributional risk measurement, and convergence tracking.
"""

from __future__ import annotations

from datetime import date
import hashlib
from pathlib import Path
from typing import Any


from data.schemas import DataClassification, DataObservation
from simulation.monte_carlo.bootstrap import HistoricalBootstrapSampler
from simulation.monte_carlo.convergence import evaluate_convergence
from simulation.monte_carlo.distributions import (
    MultivariateGaussianModel,
    MultivariateStudentTModel,
)
from simulation.monte_carlo.factors import build_fx_carry_factor_panel
from simulation.monte_carlo.metrics import calculate_distribution_metrics
from simulation.monte_carlo.regimes import (
    RegimeConditionedSampler,
    VolatilityRegimeClassifier,
)
from simulation.monte_carlo.schemas import (
    FactorPanel,
    MonteCarloResult,
    PathEvaluationResult,
    ScenarioPath,
    SimulationConfig,
    SimulationModelType,
    StressScenario,
)
from simulation.monte_carlo.shocks import (
    apply_stress_scenario,
    build_standard_stress_scenarios,
    generate_correlation_breakdown_path,
)
from simulation.monte_carlo.strategy_adapter import (
    CarryTradeScenarioStrategy,
    ScenarioStrategy,
    generate_simulated_trading_sessions,
)


class MonteCarloEngine:
    """Core simulation engine for macro-financial market scenarios."""

    def __init__(
        self,
        config: SimulationConfig,
        observations: list[DataObservation] | None = None,
        strategy: ScenarioStrategy | None = None,
        panel: FactorPanel | None = None,
    ) -> None:
        self.config = config
        self.observations = observations or []
        self.strategy = strategy or CarryTradeScenarioStrategy(
            calendar_type="JOINT_TARGET2_FED",
            strict_calendar=False,
            rollover_mode="CONTRACTUAL_MATURITY",
        )

        # Inject pre-built factor panel OR construct with explicit PIT mode
        if panel is not None:
            self.panel = panel
        else:
            self.panel = build_fx_carry_factor_panel(
                observations=self.observations,
                start_date=config.calibration_start_date,
                end_date=config.calibration_end_date,
                pit_mode=config.pit_mode,
            )

    def _initialize_model(self) -> Any:
        """Instantiate the configured mathematical scenario model."""
        m_type = self.config.model_type

        if m_type == SimulationModelType.HISTORICAL_BOOTSTRAP:
            return HistoricalBootstrapSampler(
                panel=self.panel,
                method=self.config.bootstrap_method,
                block_size=self.config.block_size,
                random_seed=self.config.random_seed,
            )

        elif m_type == SimulationModelType.MULTIVARIATE_STUDENT_T:
            return MultivariateStudentTModel(
                panel=self.panel,
                degrees_of_freedom=self.config.degrees_of_freedom,
                random_seed=self.config.random_seed,
            )

        elif m_type == SimulationModelType.MULTIVARIATE_GAUSSIAN:
            return MultivariateGaussianModel(
                panel=self.panel,
                random_seed=self.config.random_seed,
            )

        elif m_type == SimulationModelType.REGIME_CONDITIONED_BOOTSTRAP:
            classifier = VolatilityRegimeClassifier(
                panel=self.panel,
                rolling_window=self.config.regime_rolling_window,
            )
            return RegimeConditionedSampler(
                panel=self.panel,
                classifier=classifier,
                random_seed=self.config.random_seed,
            )

        else:
            raise ValueError(f"Unsupported simulation model type: {m_type}")

    def run(self) -> MonteCarloResult:
        """Execute the full Monte Carlo simulation run."""
        audit_notes: list[str] = []

        # 1. Initialize model
        model = self._initialize_model()
        audit_notes.append(f"Initialized simulation model: {self.config.model_type.value}")

        # Generate joint settlement calendar trading sessions
        sim_start_date = self.config.holdout_start_date or date(2024, 1, 2)
        session_dates = generate_simulated_trading_sessions(
            start_date=sim_start_date,
            n_sessions=self.config.horizon_steps + 1,
            calendar_type="JOINT_TARGET2_FED",
        )

        # 2. Generate simulated scenario paths
        paths: list[ScenarioPath] = model.generate_paths(
            num_paths=self.config.num_paths,
            horizon=self.config.horizon_steps,
            initial_fx=self.config.initial_fx_rate,
            initial_borrowing_rate=self.config.initial_borrowing_rate,
            initial_investment_rate=self.config.initial_investment_rate,
            dates=session_dates,
        )
        audit_notes.append(f"Generated {len(paths)} independent paths over {self.config.horizon_steps} steps with JOINT_TARGET2_FED calendar.")

        # 3. Evaluate financial strategy along each path
        evaluations: list[PathEvaluationResult] = []
        for path in paths:
            res = self.strategy.evaluate_path(
                path=path,
                initial_capital_a=100_000.0,
            )
            evaluations.append(res)

        # 4. Compute distributional risk metrics
        dist_metrics = calculate_distribution_metrics(
            evaluations=evaluations,
            horizon_steps=self.config.horizon_steps,
        )
        audit_notes.append(
            f"Calculated distributional metrics: Median Return={dist_metrics.total_return.p50:+.2%}, "
            f"P(Loss)={dist_metrics.prob_loss:.1%} (+/- {dist_metrics.prob_loss_se:.2%}), VaR95={dist_metrics.var_95:+.2%}."
        )

        # 5. Evaluate convergence across sample checkpoints
        convergence = evaluate_convergence(evaluations)
        audit_notes.append(f"Evaluated convergence across {len(convergence.checkpoints)} checkpoints.")

        # 6. Extract representative paths: best, median, worst
        sorted_evals = sorted(evaluations, key=lambda e: e.total_return)
        worst_eval = sorted_evals[0]
        median_eval = sorted_evals[len(sorted_evals) // 2]
        best_eval = sorted_evals[-1]

        path_by_id = {p.path_id: p for p in paths}
        rep_paths = {
            "worst": path_by_id[worst_eval.path_id],
            "median": path_by_id[median_eval.path_id],
            "best": path_by_id[best_eval.path_id],
        }

        # 7. Compute data manifest digest if available
        manifest_digest: str | None = None
        manifest_path = Path("data/manifest.json")
        if manifest_path.exists():
            manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

        return MonteCarloResult(
            simulation_id=self.config.simulation_id or f"MC_{self.config.model_type.value}_{self.config.num_paths}",
            config=self.config,
            distribution_metrics=dist_metrics,
            convergence_report=convergence,
            representative_paths=rep_paths,
            data_manifest_digest=manifest_digest,
            data_classification=DataClassification.SIMULATED,
            pit_mode=self.panel.pit_mode,
            is_executable_strategy=False,
            audit_notes=audit_notes,
        )

    def run_deterministic_stress_tests(
        self,
        base_path: ScenarioPath | None = None,
        scenarios: list[StressScenario] | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate strategy response across deterministic macro-financial stress scenarios."""
        if scenarios is None:
            scenarios = build_standard_stress_scenarios()

        sim_start_date = self.config.holdout_start_date or date(2024, 1, 2)
        horizon = self.config.horizon_steps
        session_dates = generate_simulated_trading_sessions(
            start_date=sim_start_date,
            n_sessions=horizon + 1,
            calendar_type="JOINT_TARGET2_FED",
        )

        if base_path is None:
            # Construct a flat baseline path (constant FX and interest rates)
            base_path = ScenarioPath(
                path_id=0,
                steps=horizon,
                dates=session_dates,
                fx_rates=[self.config.initial_fx_rate] * (horizon + 1),
                borrowing_rates=[self.config.initial_borrowing_rate] * (horizon + 1),
                investment_rates=[self.config.initial_investment_rate] * (horizon + 1),
                is_synthetic=True,
            )
        elif base_path.dates is None:
            base_path = ScenarioPath(
                path_id=base_path.path_id,
                steps=base_path.steps,
                dates=session_dates,
                fx_rates=base_path.fx_rates,
                borrowing_rates=base_path.borrowing_rates,
                investment_rates=base_path.investment_rates,
                regimes=base_path.regimes,
                is_synthetic=base_path.is_synthetic,
            )

        results: list[dict[str, Any]] = []

        # Baseline evaluation (zero stress)
        base_eval = self.strategy.evaluate_path(base_path, initial_capital_a=100_000.0)
        results.append({
            "scenario_name": "Baseline (No Stress)",
            "category": "baseline",
            "fx_shock_pct": 0.0,
            "borrowing_rate_shock_bps": 0.0,
            "investment_rate_shock_bps": 0.0,
            "spread_multiplier": 1.0,
            "slippage_multiplier": 1.0,
            "total_return": base_eval.total_return,
            "net_profit_a": base_eval.cumulative_net_profit_a,
            "pure_gross_gain_a": base_eval.pure_gross_gain_a,
            "total_financing_costs_a": base_eval.total_financing_costs_a,
            "total_frictions_a": base_eval.total_frictions_a,
            "total_cash_interest_a": base_eval.total_cash_interest_a,
            "max_drawdown": base_eval.max_drawdown,
            "reconciliation_exact": base_eval.reconciliation_exact,
        })

        for sc in scenarios:
            if sc.correlation_breakdown:
                stressed_path, _ = generate_correlation_breakdown_path(
                    panel=self.panel,
                    random_seed=self.config.random_seed,
                    horizon=self.config.horizon_steps,
                    initial_fx=self.config.initial_fx_rate,
                    initial_borrowing_rate=self.config.initial_borrowing_rate,
                    initial_investment_rate=self.config.initial_investment_rate,
                )
            else:
                stressed_path = apply_stress_scenario(base_path, sc)

            ev = self.strategy.evaluate_path(
                path=stressed_path,
                initial_capital_a=100_000.0,
                stress_overlay=sc,
            )
            results.append({
                "scenario_name": sc.name,
                "category": sc.category,
                "description": sc.description,
                "fx_shock_pct": sc.fx_shock_pct,
                "borrowing_rate_shock_bps": sc.borrowing_rate_shock_bps,
                "investment_rate_shock_bps": sc.investment_rate_shock_bps,
                "spread_multiplier": sc.spread_multiplier,
                "slippage_multiplier": sc.slippage_multiplier,
                "correlation_breakdown": sc.correlation_breakdown,
                "total_return": ev.total_return,
                "net_profit_a": ev.cumulative_net_profit_a,
                "pure_gross_gain_a": ev.pure_gross_gain_a,
                "total_financing_costs_a": ev.total_financing_costs_a,
                "total_frictions_a": ev.total_frictions_a,
                "total_cash_interest_a": ev.total_cash_interest_a,
                "max_drawdown": ev.max_drawdown,
                "reconciliation_exact": ev.reconciliation_exact,
            })

        return results
