"""Observable volatility and market-regime modeling.

Identifies empirical volatility regimes (low, high, stress), estimates the
discrete Markov transition probability matrix, and executes regime-conditioned
scenario resampling.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from simulation.monte_carlo.schemas import FactorPanel, RegimeState, ScenarioPath


class RegimeSummary(BaseModel):
    """Statistics for an empirical market volatility regime."""

    regime: RegimeState
    observation_count: int
    mean_annualized_volatility: float
    min_annualized_volatility: float
    max_annualized_volatility: float
    stationary_probability: float = 0.0


class RegimeModelReport(BaseModel):
    """Comprehensive diagnostic report for the calibrated regime model."""

    rolling_window_days: int
    regimes: list[RegimeState]
    regime_counts: dict[str, int]
    transition_matrix: dict[str, dict[str, float]]
    thresholds: dict[str, float]
    regime_summaries: dict[str, RegimeSummary]
    is_sufficient: bool = True
    audit_notes: list[str] = Field(default_factory=list)


class VolatilityRegimeClassifier:
    """Classifies historical observations into discrete volatility regimes."""

    def __init__(
        self,
        panel: FactorPanel,
        rolling_window: int = 63,
        low_vol_percentile: float = 35.0,
        high_vol_percentile: float = 80.0,
    ) -> None:
        self.panel = panel
        self.rolling_window = rolling_window
        self.low_pct = low_vol_percentile
        self.high_pct = high_vol_percentile

        fx_returns = panel.values.get("FX_EUR_USD_LOGRET")
        if not fx_returns or len(fx_returns) < rolling_window + 10:
            raise ValueError(f"Insufficient returns ({len(fx_returns) if fx_returns else 0}) for window {rolling_window}")

        # Compute rolling annualized volatility
        s = pd.Series(fx_returns)
        rolling_vol = s.rolling(window=rolling_window).std() * math.sqrt(252)

        # Drop warmup NaNs
        valid_vols = rolling_vol.dropna()
        self.threshold_low = float(np.percentile(valid_vols, self.low_pct))
        self.threshold_high = float(np.percentile(valid_vols, self.high_pct))

        # Classify all valid observations
        self.regimes: list[RegimeState] = []
        for v in rolling_vol:
            if math.isnan(v):
                self.regimes.append(RegimeState.LOW_VOLATILITY)
            elif v < self.threshold_low:
                self.regimes.append(RegimeState.LOW_VOLATILITY)
            elif v < self.threshold_high:
                self.regimes.append(RegimeState.HIGH_VOLATILITY)
            else:
                self.regimes.append(RegimeState.STRESS)

    def compute_transition_matrix(self) -> dict[str, dict[str, float]]:
        """Estimate Markov transition probabilities P(regime_t | regime_{t-1})."""
        states = [RegimeState.LOW_VOLATILITY.value, RegimeState.HIGH_VOLATILITY.value, RegimeState.STRESS.value]
        counts: dict[str, dict[str, int]] = {s1: {s2: 0 for s2 in states} for s1 in states}

        for i in range(1, len(self.regimes)):
            r_prev = self.regimes[i - 1].value
            r_curr = self.regimes[i].value
            counts[r_prev][r_curr] += 1

        probs: dict[str, dict[str, float]] = {}
        for s1 in states:
            total = sum(counts[s1].values())
            probs[s1] = {}
            for s2 in states:
                probs[s1][s2] = counts[s1][s2] / total if total > 0 else (1.0 / len(states))
        return probs

    def build_report(self) -> RegimeModelReport:
        """Construct full regime diagnostic report."""
        probs = self.compute_transition_matrix()
        counts: dict[str, int] = {}
        for r in self.regimes:
            counts[r.value] = counts.get(r.value, 0) + 1

        notes = []
        is_sufficient = True
        for s, c in counts.items():
            if c < 20:
                is_sufficient = False
                notes.append(f"Regime {s} has fewer than 20 observations ({c}); model may have high parameter uncertainty.")

        summaries = {
            s: RegimeSummary(
                regime=RegimeState(s),
                observation_count=counts.get(s, 0),
                mean_annualized_volatility=0.0,
                min_annualized_volatility=0.0,
                max_annualized_volatility=0.0,
            )
            for s in counts
        }

        return RegimeModelReport(
            rolling_window_days=self.rolling_window,
            regimes=[RegimeState.LOW_VOLATILITY, RegimeState.HIGH_VOLATILITY, RegimeState.STRESS],
            regime_counts=counts,
            transition_matrix=probs,
            thresholds={"low": self.threshold_low, "high": self.threshold_high},
            regime_summaries=summaries,
            is_sufficient=is_sufficient,
            audit_notes=notes,
        )


class RegimeConditionedSampler:
    """Simulates market factors conditioned on the prevailing volatility regime."""

    def __init__(
        self,
        panel: FactorPanel,
        classifier: VolatilityRegimeClassifier,
        random_seed: int = 42,
    ) -> None:
        self.panel = panel
        self.classifier = classifier
        self.rng = np.random.default_rng(random_seed)

        self.factor_names = list(panel.values.keys())
        matrix_cols = [np.array(panel.values[f], dtype=np.float64) for f in self.factor_names]
        self.data_matrix = np.column_stack(matrix_cols)  # (T, K)
        self.n_obs, self.n_factors = self.data_matrix.shape

        # Partition observation indices by regime
        self.regime_indices: dict[str, list[int]] = {
            RegimeState.LOW_VOLATILITY.value: [],
            RegimeState.HIGH_VOLATILITY.value: [],
            RegimeState.STRESS.value: [],
        }
        for i, r in enumerate(classifier.regimes):
            self.regime_indices[r.value].append(i)

        self.transition_matrix = classifier.compute_transition_matrix()
        self.states = [RegimeState.LOW_VOLATILITY.value, RegimeState.HIGH_VOLATILITY.value, RegimeState.STRESS.value]

    def sample_regime_sequence(self, horizon: int, initial_regime: str | None = None) -> list[str]:
        """Simulate a Markov chain of regime states."""
        if initial_regime is None:
            # Start at low volatility or sample from initial distribution
            initial_regime = RegimeState.LOW_VOLATILITY.value

        current = initial_regime
        sequence = [current]

        for _ in range(horizon - 1):
            next_probs = [self.transition_matrix[current][s] for s in self.states]
            current = self.rng.choice(self.states, p=next_probs)
            sequence.append(current)

        return sequence

    def generate_path(
        self,
        path_id: int,
        horizon: int,
        initial_fx: float = 1.09,
        initial_borrowing_rate: float = 0.04,
        initial_investment_rate: float = 0.05,
        initial_regime: str | None = None,
    ) -> ScenarioPath:
        """Generate a simulated path conditioned on simulated regime transitions."""
        regime_seq = self.sample_regime_sequence(horizon, initial_regime)

        # For each step, sample an innovation from the active regime's empirical pool
        sampled_rows: list[np.ndarray] = []
        for r_state in regime_seq:
            pool = self.regime_indices[r_state]
            if not pool:
                # Fallback to random draw from entire matrix if regime pool is empty
                idx = int(self.rng.integers(0, self.n_obs))
            else:
                idx = int(self.rng.choice(pool))
            sampled_rows.append(self.data_matrix[idx, :])

        sampled_factors = np.vstack(sampled_rows)

        fx_idx = self.factor_names.index("FX_EUR_USD_LOGRET")
        borrow_idx = self.factor_names.index("RATE_DIFF_EUR_BORROW_BPS")
        invest_idx = self.factor_names.index("YIELD_DIFF_USD_1M_BPS")

        fx_log_ret = sampled_factors[:, fx_idx]
        borrow_diffs = sampled_factors[:, borrow_idx]
        invest_diffs = sampled_factors[:, invest_idx]

        cumulative_log_ret = np.cumsum(fx_log_ret)
        fx_rates = [initial_fx] + (initial_fx * np.exp(cumulative_log_ret)).tolist()

        cum_borrow = np.cumsum(borrow_diffs)
        cum_invest = np.cumsum(invest_diffs)

        borrowing_rates = [initial_borrowing_rate] + [
            max(0.0, initial_borrowing_rate + (b / 10000.0)) for b in cum_borrow
        ]
        investment_rates = [initial_investment_rate] + [
            max(0.0, initial_investment_rate + (inv / 10000.0)) for inv in cum_invest
        ]

        return ScenarioPath(
            path_id=path_id,
            steps=horizon,
            fx_rates=fx_rates,
            borrowing_rates=borrowing_rates,
            investment_rates=investment_rates,
            regimes=regime_seq,
            is_synthetic=True,
        )

    def generate_paths(
        self,
        num_paths: int,
        horizon: int,
        initial_fx: float = 1.09,
        initial_borrowing_rate: float = 0.04,
        initial_investment_rate: float = 0.05,
    ) -> list[ScenarioPath]:
        """Generate multiple regime-conditioned scenario paths."""
        return [
            self.generate_path(
                path_id=p,
                horizon=horizon,
                initial_fx=initial_fx,
                initial_borrowing_rate=initial_borrowing_rate,
                initial_investment_rate=initial_investment_rate,
            )
            for p in range(num_paths)
        ]
