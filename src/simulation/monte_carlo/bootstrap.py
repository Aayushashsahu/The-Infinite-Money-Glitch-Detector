"""Historical bootstrap simulation engine.

Implements IID, Moving-Block, and Stationary (Politis & Romano 1994) bootstrap
samplers. Performs joint multivariate factor resampling and reconstructs
strictly positive FX price paths and interest-rate trajectories.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from simulation.monte_carlo.schemas import (
    BootstrapMethod,
    FactorPanel,
    ScenarioPath,
    SimulationConfig,
)


class HistoricalBootstrapSampler:
    """Non-parametric historical bootstrap sampler for multivariate factor panels."""

    def __init__(
        self,
        panel: FactorPanel,
        method: BootstrapMethod = BootstrapMethod.MOVING_BLOCK,
        block_size: int = 20,
        random_seed: int = 42,
    ) -> None:
        self.panel = panel
        self.method = method
        self.block_size = max(1, block_size)
        self.rng = np.random.default_rng(random_seed)

        # Build joint factor matrix: shape (T, K)
        self.factor_names = list(panel.values.keys())
        matrix_cols = [np.array(panel.values[f], dtype=np.float64) for f in self.factor_names]
        self.data_matrix = np.column_stack(matrix_cols)  # (T, K)
        self.n_obs, self.n_factors = self.data_matrix.shape

        if self.n_obs < 10:
            raise ValueError(f"Insufficient observations for bootstrap: {self.n_obs} < 10")

    def sample_indices(self, horizon: int) -> np.ndarray:
        """Generate a series of observation indices of length horizon."""
        if horizon <= 0:
            return np.empty(0, dtype=np.int64)

        if self.method == BootstrapMethod.IID:
            return self.rng.integers(0, self.n_obs, size=horizon)

        elif self.method == BootstrapMethod.MOVING_BLOCK:
            indices: list[int] = []
            max_start = max(1, self.n_obs - self.block_size + 1)
            while len(indices) < horizon:
                start_idx = int(self.rng.integers(0, max_start))
                indices.extend(range(start_idx, min(start_idx + self.block_size, self.n_obs)))
            return np.array(indices[:horizon], dtype=np.int64)

        elif self.method == BootstrapMethod.STATIONARY:
            # Politis & Romano (1994) Stationary Bootstrap
            # Probability of starting a new block at each step: p = 1 / block_size
            p = 1.0 / self.block_size
            indices = np.empty(horizon, dtype=np.int64)
            current_idx = int(self.rng.integers(0, self.n_obs))
            indices[0] = current_idx

            for t in range(1, horizon):
                if self.rng.random() < p:
                    # Start a new block uniformly across all observations
                    current_idx = int(self.rng.integers(0, self.n_obs))
                else:
                    # Continue current block with circular wraparound
                    current_idx = (current_idx + 1) % self.n_obs
                indices[t] = current_idx

            return indices

        else:
            raise ValueError(f"Unsupported bootstrap method: {self.method}")

    def generate_path(
        self,
        path_id: int,
        horizon: int,
        initial_fx: float = 1.09,
        initial_borrowing_rate: float = 0.04,
        initial_investment_rate: float = 0.05,
    ) -> ScenarioPath:
        """Sample a joint multivariate factor sequence and reconstruct price & rate levels."""
        indices = self.sample_indices(horizon)
        sampled_factors = self.data_matrix[indices, :]  # shape: (horizon, K)

        # Factor indices
        fx_idx = self.factor_names.index("FX_EUR_USD_LOGRET")
        borrow_idx = self.factor_names.index("RATE_DIFF_EUR_BORROW_BPS")
        invest_idx = self.factor_names.index("YIELD_DIFF_USD_1M_BPS")

        fx_log_returns = sampled_factors[:, fx_idx]
        borrow_diffs_bps = sampled_factors[:, borrow_idx]
        invest_diffs_bps = sampled_factors[:, invest_idx]

        # Reconstruct strictly positive FX price levels
        # S_t = S_0 * exp(cumsum(r))
        cumulative_log_ret = np.cumsum(fx_log_returns)
        fx_rates = [initial_fx] + (initial_fx * np.exp(cumulative_log_ret)).tolist()

        # Reconstruct annual interest rates: Delta in bps / 10000 -> decimal annual rate
        cum_borrow_bps = np.cumsum(borrow_diffs_bps)
        cum_invest_bps = np.cumsum(invest_diffs_bps)

        borrowing_rates = [initial_borrowing_rate] + [
            max(0.0, initial_borrowing_rate + (b / 10000.0)) for b in cum_borrow_bps
        ]
        investment_rates = [initial_investment_rate] + [
            max(0.0, initial_investment_rate + (inv / 10000.0)) for inv in cum_invest_bps
        ]

        return ScenarioPath(
            path_id=path_id,
            steps=horizon,
            fx_rates=fx_rates,
            borrowing_rates=borrowing_rates,
            investment_rates=investment_rates,
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
        """Generate multiple independent bootstrap scenario paths."""
        paths: list[ScenarioPath] = []
        for p in range(num_paths):
            path = self.generate_path(
                path_id=p,
                horizon=horizon,
                initial_fx=initial_fx,
                initial_borrowing_rate=initial_borrowing_rate,
                initial_investment_rate=initial_investment_rate,
            )
            paths.append(path)
        return paths
