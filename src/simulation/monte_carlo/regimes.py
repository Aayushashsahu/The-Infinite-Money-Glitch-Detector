"""Observable volatility and market-regime modeling.

Identifies empirical volatility regimes (low, high, stress), estimates the
discrete Markov transition probability matrix without warm-up contamination,
and executes regime-conditioned scenario resampling.
"""

from __future__ import annotations

from datetime import date
import math

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
    """Classifies historical observations into discrete volatility regimes.

    Enforces strict warm-up exclusion:
    - Observations in the initial rolling window (t < rolling_window) are excluded
      from transition count estimation, state frequency calculation, and regime statistics.
    - Percentiles are computed exclusively on valid rolling standard deviations.
    """

    def __init__(
        self,
        panel: FactorPanel,
        rolling_window: int = 63,
        low_vol_percentile: float = 20.0,
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
        self.rolling_vol_series = rolling_vol

        # Identify valid non-NaN indices
        self.valid_indices: list[int] = [i for i, v in enumerate(rolling_vol) if not math.isnan(v)]
        if len(self.valid_indices) < 20:
            raise ValueError(f"Insufficient valid volatility observations: {len(self.valid_indices)}")

        valid_vols = [float(rolling_vol[i]) for i in self.valid_indices]
        self.threshold_low = float(np.percentile(valid_vols, self.low_pct))
        self.threshold_high = float(np.percentile(valid_vols, self.high_pct))

        # Map each valid observation to a RegimeState
        self.regime_by_index: dict[int, RegimeState] = {}
        for i in self.valid_indices:
            v = float(rolling_vol[i])
            if v < self.threshold_low:
                self.regime_by_index[i] = RegimeState.LOW_VOLATILITY
            elif v < self.threshold_high:
                self.regime_by_index[i] = RegimeState.NORMAL_VOLATILITY
            else:
                self.regime_by_index[i] = RegimeState.STRESS_VOLATILITY

        # Full regimes array matching panel length (warm-up entries set to None)
        self.regimes: list[RegimeState | None] = [
            self.regime_by_index.get(i) for i in range(len(fx_returns))
        ]

        # Valid counts
        self.regime_counts: dict[str, int] = {
            RegimeState.LOW_VOLATILITY.value: sum(1 for r in self.regime_by_index.values() if r == RegimeState.LOW_VOLATILITY),
            RegimeState.NORMAL_VOLATILITY.value: sum(1 for r in self.regime_by_index.values() if r == RegimeState.NORMAL_VOLATILITY),
            RegimeState.STRESS_VOLATILITY.value: sum(1 for r in self.regime_by_index.values() if r == RegimeState.STRESS_VOLATILITY),
        }
        self.total_valid_obs = len(self.valid_indices)

    def compute_transition_matrix(self) -> dict[str, dict[str, float]]:
        """Estimate Markov transition probabilities P(regime_t | regime_{t-1}).

        Excludes warm-up observations strictly: transitions are counted only across
        consecutive valid trading days where both t-1 and t have calculated volatility.
        """
        states = [RegimeState.LOW_VOLATILITY.value, RegimeState.NORMAL_VOLATILITY.value, RegimeState.STRESS_VOLATILITY.value]
        counts: dict[str, dict[str, int]] = {s1: {s2: 0 for s2 in states} for s1 in states}

        for idx in range(1, len(self.valid_indices)):
            prev_idx = self.valid_indices[idx - 1]
            curr_idx = self.valid_indices[idx]
            # Ensure consecutive sequence
            if curr_idx == prev_idx + 1:
                r_prev = self.regime_by_index[prev_idx].value
                r_curr = self.regime_by_index[curr_idx].value
                counts[r_prev][r_curr] += 1

        probs: dict[str, dict[str, float]] = {}
        for s1 in states:
            total = sum(counts[s1].values())
            probs[s1] = {}
            for s2 in states:
                probs[s1][s2] = counts[s1][s2] / total if total > 0 else (1.0 / len(states))
        return probs

    def build_report(self) -> RegimeModelReport:
        """Construct full regime diagnostic report with genuine per-regime summary statistics."""
        probs = self.compute_transition_matrix()
        notes: list[str] = [
            f"Excluded {self.rolling_window - 1} warm-up observations from regime classification and transition estimation.",
            f"Calibrated on {self.total_valid_obs} valid rolling-window observations.",
        ]

        is_sufficient = True
        for s, c in self.regime_counts.items():
            if c < 20:
                is_sufficient = False
                notes.append(f"Regime {s} has fewer than 20 observations ({c}); model may have high parameter uncertainty.")

        summaries: dict[str, RegimeSummary] = {}
        for s_val in [RegimeState.LOW_VOLATILITY.value, RegimeState.NORMAL_VOLATILITY.value, RegimeState.STRESS_VOLATILITY.value]:
            vols_s = [
                float(self.rolling_vol_series[i])
                for i in self.valid_indices
                if self.regime_by_index[i].value == s_val
            ]
            c = len(vols_s)
            mean_v = float(np.mean(vols_s)) if c > 0 else 0.0
            min_v = float(np.min(vols_s)) if c > 0 else 0.0
            max_v = float(np.max(vols_s)) if c > 0 else 0.0
            stat_prob = c / self.total_valid_obs if self.total_valid_obs > 0 else 0.0

            summaries[s_val] = RegimeSummary(
                regime=RegimeState(s_val),
                observation_count=c,
                mean_annualized_volatility=mean_v,
                min_annualized_volatility=min_v,
                max_annualized_volatility=max_v,
                stationary_probability=stat_prob,
            )

        return RegimeModelReport(
            rolling_window_days=self.rolling_window,
            regimes=[RegimeState.LOW_VOLATILITY, RegimeState.NORMAL_VOLATILITY, RegimeState.STRESS_VOLATILITY],
            regime_counts=self.regime_counts,
            transition_matrix=probs,
            thresholds={"low": self.threshold_low, "high": self.threshold_high},
            regime_summaries=summaries,
            is_sufficient=is_sufficient,
            audit_notes=notes,
        )


class RegimeConditionedSampler:
    """Simulates market factors conditioned on the prevailing volatility regime.

    Rejects empty regime pools and samples initial states from empirical distribution.
    """

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

        # Partition valid observation indices by regime
        self.regime_indices: dict[str, list[int]] = {
            RegimeState.LOW_VOLATILITY.value: [],
            RegimeState.NORMAL_VOLATILITY.value: [],
            RegimeState.STRESS_VOLATILITY.value: [],
        }
        for i in classifier.valid_indices:
            r = classifier.regime_by_index[i]
            self.regime_indices[r.value].append(i)

        # Ensure no regime pool is empty
        for s, pool in self.regime_indices.items():
            if not pool:
                raise ValueError(
                    f"Regime pool for '{s}' has 0 valid observations. Data support is inadequate."
                )

        self.transition_matrix = classifier.compute_transition_matrix()
        self.states = [RegimeState.LOW_VOLATILITY.value, RegimeState.NORMAL_VOLATILITY.value, RegimeState.STRESS_VOLATILITY.value]

    def sample_regime_sequence(self, horizon: int, initial_regime: str | None = None) -> list[str]:
        """Simulate a Markov chain of regime states.

        If initial_regime is None, samples from the empirical stationary distribution.
        """
        if initial_regime is None:
            # Sample from historical regime frequencies
            init_probs = [
                self.classifier.regime_counts[s] / self.classifier.total_valid_obs
                for s in self.states
            ]
            current = str(self.rng.choice(self.states, p=init_probs))
        else:
            current = initial_regime

        sequence = [current]
        for _ in range(horizon - 1):
            next_probs = [self.transition_matrix[current][s] for s in self.states]
            current = str(self.rng.choice(self.states, p=next_probs))
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
        dates: list[date] | None = None,
    ) -> ScenarioPath:
        """Generate a simulated path conditioned on simulated regime transitions."""
        regime_seq = self.sample_regime_sequence(horizon, initial_regime)

        # For each step, sample an innovation from the active regime's empirical pool
        sampled_rows: list[np.ndarray] = []
        for r_state in regime_seq:
            pool = self.regime_indices[r_state]
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
            dates=dates,
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
        dates: list[date] | None = None,
    ) -> list[ScenarioPath]:
        """Generate multiple regime-conditioned scenario paths."""
        return [
            self.generate_path(
                path_id=p,
                horizon=horizon,
                initial_fx=initial_fx,
                initial_borrowing_rate=initial_borrowing_rate,
                initial_investment_rate=initial_investment_rate,
                dates=dates,
            )
            for p in range(num_paths)
        ]
