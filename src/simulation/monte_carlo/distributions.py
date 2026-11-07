"""Parametric multivariate distribution models (Gaussian & Student-t).

Implements multivariate Gaussian and Student-t distribution fitting, positive-semidefinite
covariance repair via eigenvalue clipping, and joint factor scenario generation.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import scipy.stats as stats
from pydantic import BaseModel, Field

from simulation.monte_carlo.schemas import FactorPanel, ScenarioPath


class DistributionFitReport(BaseModel):
    """Diagnostics and parameter estimates for a parametric multivariate distribution."""

    model_type: str
    sample_size: int
    n_factors: int
    factor_names: list[str]
    mean_vector: list[float]
    covariance_matrix: list[list[float]]
    degrees_of_freedom: float | None = None
    was_psd_repaired: bool = False
    psd_repair_frobenius_norm: float = 0.0
    log_likelihood: float | None = None
    aic: float | None = None
    bic: float | None = None
    audit_notes: list[str] = Field(default_factory=list)


def ensure_positive_semidefinite(
    matrix: np.ndarray,
    min_eigenvalue: float = 1e-8,
) -> tuple[np.ndarray, bool, float]:
    """Ensure a square symmetric matrix is positive semi-definite (PSD).

    Uses eigenvalue decomposition and clips any eigenvalues below min_eigenvalue.
    Returns: (repaired_matrix, was_repaired, frobenius_norm_diff)
    """
    # Symmetrize
    sym = (matrix + matrix.T) / 2.0
    eigvals, eigvecs = np.linalg.eigh(sym)

    min_val = float(np.min(eigvals))
    if min_val >= min_eigenvalue:
        return sym, False, 0.0

    # Clip eigenvalues
    clipped_eigvals = np.maximum(eigvals, min_eigenvalue)
    repaired = eigvecs @ np.diag(clipped_eigvals) @ eigvecs.T
    # Resymmetrize after reconstruction
    repaired = (repaired + repaired.T) / 2.0

    diff = float(np.linalg.norm(repaired - sym, ord="fro"))
    return repaired, True, diff


class MultivariateGaussianModel:
    """Multivariate Gaussian factor generator."""

    def __init__(self, panel: FactorPanel, random_seed: int = 42) -> None:
        self.panel = panel
        self.factor_names = list(panel.values.keys())
        self.rng = np.random.default_rng(random_seed)

        # Build data matrix (T, K)
        cols = [np.array(panel.values[f], dtype=np.float64) for f in self.factor_names]
        self.data_matrix = np.column_stack(cols)
        self.n_obs, self.n_factors = self.data_matrix.shape

        # Sample mean and covariance
        self.mean_vec = np.mean(self.data_matrix, axis=0)
        raw_cov = np.cov(self.data_matrix, rowvar=False, ddof=1)
        if self.n_factors == 1:
            raw_cov = np.array([[raw_cov]])

        self.cov_matrix, self.was_repaired, self.repair_diff = ensure_positive_semidefinite(raw_cov)

    def sample(self, size: int) -> np.ndarray:
        """Sample (size, n_factors) innovations from the multivariate Gaussian."""
        return self.rng.multivariate_normal(self.mean_vec, self.cov_matrix, size=size)

    def generate_path(
        self,
        path_id: int,
        horizon: int,
        initial_fx: float = 1.09,
        initial_borrowing_rate: float = 0.04,
        initial_investment_rate: float = 0.05,
    ) -> ScenarioPath:
        """Generate a simulated path via Gaussian innovations."""
        sampled = self.sample(horizon)

        fx_idx = self.factor_names.index("FX_EUR_USD_LOGRET")
        borrow_idx = self.factor_names.index("RATE_DIFF_EUR_BORROW_BPS")
        invest_idx = self.factor_names.index("YIELD_DIFF_USD_1M_BPS")

        fx_log_ret = sampled[:, fx_idx]
        borrow_diffs = sampled[:, borrow_idx]
        invest_diffs = sampled[:, invest_idx]

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
        """Generate multiple Gaussian scenario paths."""
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


class MultivariateStudentTModel:
    """Multivariate Student-t factor generator with estimated degrees of freedom."""

    def __init__(
        self,
        panel: FactorPanel,
        degrees_of_freedom: float | None = None,
        random_seed: int = 42,
    ) -> None:
        self.panel = panel
        self.factor_names = list(panel.values.keys())
        self.rng = np.random.default_rng(random_seed)

        cols = [np.array(panel.values[f], dtype=np.float64) for f in self.factor_names]
        self.data_matrix = np.column_stack(cols)
        self.n_obs, self.n_factors = self.data_matrix.shape

        self.mean_vec = np.mean(self.data_matrix, axis=0)
        raw_cov = np.cov(self.data_matrix, rowvar=False, ddof=1)
        if self.n_factors == 1:
            raw_cov = np.array([[raw_cov]])

        self.cov_matrix, self.was_repaired, self.repair_diff = ensure_positive_semidefinite(raw_cov)

        # Estimate or validate degrees of freedom nu
        if degrees_of_freedom is not None:
            if degrees_of_freedom <= 2.0:
                raise ValueError("Degrees of freedom must be > 2.0 for finite variance.")
            self.nu = float(degrees_of_freedom)
        else:
            self.nu = self._estimate_degrees_of_freedom()

        # Scale matrix for Student-t: cov = nu / (nu - 2) * scale_matrix  (for nu > 2)
        # Therefore: scale_matrix = cov * (nu - 2) / nu
        self.scale_matrix = self.cov_matrix * ((self.nu - 2.0) / self.nu)

    def _estimate_degrees_of_freedom(self) -> float:
        """Estimate degrees of freedom from empirical excess kurtosis of factor returns."""
        # For univariate t: excess kurtosis = 6 / (nu - 4) for nu > 4
        # nu = 4 + 6 / kurtosis
        kurt_values = []
        for i in range(self.n_factors):
            k = stats.kurtosis(self.data_matrix[:, i])
            if k > 0.1:
                kurt_values.append(k)

        if not kurt_values:
            # Fallback to standard heavy-tail default if empirical kurtosis is Gaussian-like
            return 8.0

        median_kurt = float(np.median(kurt_values))
        nu_est = 4.0 + (6.0 / median_kurt)
        # Constrain nu to plausible financial range: [3.0, 30.0]
        return float(np.clip(nu_est, 3.5, 30.0))

    def sample(self, size: int) -> np.ndarray:
        """Sample from multivariate Student-t via normal-gamma mixture representation.

        If Z ~ N(0, Scale) and W ~ Chi2(nu), then X = mu + Z * sqrt(nu / W) ~ t_nu(mu, Scale).
        """
        # 1. Sample Z from N(0, scale_matrix)
        z = self.rng.multivariate_normal(np.zeros(self.n_factors), self.scale_matrix, size=size)
        # 2. Sample W from Chi-squared(nu)
        w = self.rng.chisquare(df=self.nu, size=size)
        # 3. Combine: shape (size, n_factors)
        scale_factors = np.sqrt(self.nu / w)[:, np.newaxis]
        return self.mean_vec + (z * scale_factors)

    def generate_path(
        self,
        path_id: int,
        horizon: int,
        initial_fx: float = 1.09,
        initial_borrowing_rate: float = 0.04,
        initial_investment_rate: float = 0.05,
    ) -> ScenarioPath:
        """Generate a simulated path via multivariate Student-t innovations."""
        sampled = self.sample(horizon)

        fx_idx = self.factor_names.index("FX_EUR_USD_LOGRET")
        borrow_idx = self.factor_names.index("RATE_DIFF_EUR_BORROW_BPS")
        invest_idx = self.factor_names.index("YIELD_DIFF_USD_1M_BPS")

        fx_log_ret = sampled[:, fx_idx]
        borrow_diffs = sampled[:, borrow_idx]
        invest_diffs = sampled[:, invest_idx]

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
        """Generate multiple Student-t scenario paths."""
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
