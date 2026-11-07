"""Parametric multivariate distribution models (Gaussian & Student-t).

Implements multivariate Gaussian and Student-t distribution fitting, positive-semidefinite
covariance repair via eigenvalue clipping, profile maximum likelihood estimation of
degrees of freedom, and joint factor scenario generation.
"""

from __future__ import annotations

from datetime import date
import math
from typing import Any

import numpy as np
import scipy.optimize as optimize
import scipy.special as special
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
    raw_covariance_matrix: list[list[float]] = Field(default_factory=list)
    covariance_matrix: list[list[float]]
    scale_matrix: list[list[float]] = Field(default_factory=list)
    degrees_of_freedom: float | None = None
    estimation_method: str = "empirical_moment"
    is_converged: bool = True
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
    sym = (matrix + matrix.T) / 2.0
    eigvals, eigvecs = np.linalg.eigh(sym)

    min_val = float(np.min(eigvals))
    if min_val >= min_eigenvalue:
        return sym, False, 0.0

    clipped_eigvals = np.maximum(eigvals, min_eigenvalue)
    repaired = eigvecs @ np.diag(clipped_eigvals) @ eigvecs.T
    repaired = (repaired + repaired.T) / 2.0

    diff = float(np.linalg.norm(repaired - sym, ord="fro"))
    return repaired, True, diff


class MultivariateGaussianModel:
    """Multivariate Gaussian factor generator."""

    def __init__(self, panel: FactorPanel, random_seed: int = 42) -> None:
        self.panel = panel
        self.factor_names = list(panel.values.keys())
        self.rng = np.random.default_rng(random_seed)

        cols = [np.array(panel.values[f], dtype=np.float64) for f in self.factor_names]
        self.data_matrix = np.column_stack(cols)
        self.n_obs, self.n_factors = self.data_matrix.shape

        self.mean_vec = np.mean(self.data_matrix, axis=0)
        self.raw_cov = np.cov(self.data_matrix, rowvar=False, ddof=1)
        if self.n_factors == 1:
            self.raw_cov = np.array([[self.raw_cov]])

        self.cov_matrix, self.was_repaired, self.repair_diff = ensure_positive_semidefinite(self.raw_cov)

    def sample(self, size: int) -> np.ndarray:
        """Sample (size, n_factors) innovations from the multivariate Gaussian."""
        return self.rng.multivariate_normal(self.mean_vec, self.cov_matrix, size=size)

    def build_fit_report(self) -> DistributionFitReport:
        """Generate parameter estimation and goodness-of-fit report."""
        diff = self.data_matrix - self.mean_vec
        sign, logdet = np.linalg.slogdet(self.cov_matrix)
        inv_cov = np.linalg.pinv(self.cov_matrix)
        quad = np.sum((diff @ inv_cov) * diff, axis=1)

        p = self.n_factors
        ll = float(-0.5 * (self.n_obs * (p * np.log(2.0 * np.pi) + logdet) + np.sum(quad)))
        k_params = p + (p * (p + 1)) // 2
        aic = float(2 * k_params - 2 * ll)
        bic = float(k_params * np.log(self.n_obs) - 2 * ll)

        notes = []
        if self.was_repaired:
            notes.append(f"Empirical covariance repaired to PSD cone (Frobenius diff: {self.repair_diff:.4e}).")

        return DistributionFitReport(
            model_type="multivariate_gaussian",
            sample_size=self.n_obs,
            n_factors=self.n_factors,
            factor_names=self.factor_names,
            mean_vector=self.mean_vec.tolist(),
            raw_covariance_matrix=self.raw_cov.tolist(),
            covariance_matrix=self.cov_matrix.tolist(),
            scale_matrix=self.cov_matrix.tolist(),
            degrees_of_freedom=None,
            estimation_method="maximum_likelihood",
            is_converged=True,
            was_psd_repaired=self.was_repaired,
            psd_repair_frobenius_norm=self.repair_diff,
            log_likelihood=ll,
            aic=aic,
            bic=bic,
            audit_notes=notes,
        )

    def generate_path(
        self,
        path_id: int,
        horizon: int,
        initial_fx: float = 1.09,
        initial_borrowing_rate: float = 0.04,
        initial_investment_rate: float = 0.05,
        dates: list[date] | None = None,
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
            dates=dates,
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
        dates: list[date] | None = None,
    ) -> list[ScenarioPath]:
        """Generate multiple Gaussian scenario paths."""
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


class MultivariateStudentTModel:
    """Multivariate Student-t factor generator with estimated degrees of freedom.

    Estimation Method:
    - If degrees_of_freedom is specified, uses that value.
    - Otherwise, estimates degrees of freedom nu via profile maximum likelihood estimation
      on the multivariate Student-t log-likelihood.
    - Scale matrix Sigma is adjusted such that Cov(X) = nu / (nu - 2) * Sigma = Cov_empirical.
    """

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
        self.raw_cov = np.cov(self.data_matrix, rowvar=False, ddof=1)
        if self.n_factors == 1:
            self.raw_cov = np.array([[self.raw_cov]])

        self.cov_matrix, self.was_repaired, self.repair_diff = ensure_positive_semidefinite(self.raw_cov)

        # Mahalanobis distances under empirical covariance
        inv_cov = np.linalg.pinv(self.cov_matrix)
        diff = self.data_matrix - self.mean_vec
        self.d_sq = np.sum((diff @ inv_cov) * diff, axis=1)

        # Estimate degrees of freedom
        if degrees_of_freedom is not None:
            if degrees_of_freedom <= 2.0:
                raise ValueError("Degrees of freedom must be > 2.0 for finite variance.")
            self.nu = float(degrees_of_freedom)
            self.estimation_method = "user_specified"
            self.is_converged = True
        else:
            self.nu, self.is_converged = self._fit_profile_mle_nu()
            self.estimation_method = "multivariate_profile_mle"

        # Scale matrix for Student-t: cov = nu / (nu - 2) * scale_matrix  (for nu > 2)
        # Therefore: scale_matrix = cov * (nu - 2) / nu
        self.scale_matrix = self.cov_matrix * ((self.nu - 2.0) / self.nu)

    def _fit_profile_mle_nu(self) -> tuple[float, bool]:
        """Fit degrees of freedom nu maximizing multivariate Student-t profile log-likelihood."""
        N = self.n_obs
        p = self.n_factors
        sign, logdet_cov = np.linalg.slogdet(self.cov_matrix)

        def neg_log_lik(nu: float) -> float:
            if nu <= 2.01:
                return 1e12
            # For scale matrix S = Cov * (nu - 2) / nu:
            # logdet(S) = logdet(Cov) + p * ln((nu - 2) / nu)
            term_gamma = special.gammaln((nu + p) / 2.0) - special.gammaln(nu / 2.0)
            term_const = -0.5 * p * np.log(np.pi * (nu - 2.0)) - 0.5 * logdet_cov
            delta_sq = self.d_sq * (nu / (nu - 2.0))
            term_sum = -0.5 * (nu + p) * np.sum(np.log(1.0 + delta_sq / nu))
            total_ll = N * (term_gamma + term_const) + term_sum
            return -float(total_ll)

        res = optimize.minimize_scalar(neg_log_lik, bounds=(2.1, 40.0), method="bounded")
        if res.success:
            return float(np.clip(res.x, 2.5, 30.0)), True

        # Fallback to robust excess kurtosis estimator if optimization fails
        k_vals = [stats.kurtosis(self.data_matrix[:, i]) for i in range(p)]
        median_k = float(np.median([k for k in k_vals if k > 0.1] or [1.0]))
        nu_fb = float(np.clip(4.0 + (6.0 / median_k), 3.0, 30.0))
        return nu_fb, False

    def sample(self, size: int) -> np.ndarray:
        """Sample from multivariate Student-t via normal-gamma mixture representation.

        If Z ~ N(0, Scale) and W ~ Chi2(nu), then X = mu + Z * sqrt(nu / W) ~ t_nu(mu, Scale).
        """
        z = self.rng.multivariate_normal(np.zeros(self.n_factors), self.scale_matrix, size=size)
        w = self.rng.chisquare(df=self.nu, size=size)
        scale_factors = np.sqrt(self.nu / w)[:, np.newaxis]
        return self.mean_vec + (z * scale_factors)

    def build_fit_report(self) -> DistributionFitReport:
        """Generate comprehensive diagnostics for the fitted multivariate Student-t distribution."""
        N = self.n_obs
        p = self.n_factors
        sign, logdet_cov = np.linalg.slogdet(self.cov_matrix)

        term_gamma = special.gammaln((self.nu + p) / 2.0) - special.gammaln(self.nu / 2.0)
        term_const = -0.5 * p * np.log(np.pi * (self.nu - 2.0)) - 0.5 * logdet_cov
        delta_sq = self.d_sq * (self.nu / (self.nu - 2.0))
        term_sum = -0.5 * (self.nu + p) * np.sum(np.log(1.0 + delta_sq / self.nu))
        ll = float(N * (term_gamma + term_const) + term_sum)

        k_params = p + (p * (p + 1)) // 2 + 1  # Mean vector + Cov matrix + nu
        aic = float(2 * k_params - 2 * ll)
        bic = float(k_params * np.log(N) - 2 * ll)

        notes = [
            f"Fitted multivariate degrees of freedom: nu = {self.nu:.4f} via {self.estimation_method}.",
            f"Log-likelihood: {ll:.2f}, AIC: {aic:.2f}, BIC: {bic:.2f}.",
        ]
        if self.was_repaired:
            notes.append(f"Covariance matrix repaired to PSD cone (Frobenius diff: {self.repair_diff:.4e}).")

        return DistributionFitReport(
            model_type="multivariate_student_t",
            sample_size=N,
            n_factors=p,
            factor_names=self.factor_names,
            mean_vector=self.mean_vec.tolist(),
            raw_covariance_matrix=self.raw_cov.tolist(),
            covariance_matrix=self.cov_matrix.tolist(),
            scale_matrix=self.scale_matrix.tolist(),
            degrees_of_freedom=self.nu,
            estimation_method=self.estimation_method,
            is_converged=self.is_converged,
            was_psd_repaired=self.was_repaired,
            psd_repair_frobenius_norm=self.repair_diff,
            log_likelihood=ll,
            aic=aic,
            bic=bic,
            audit_notes=notes,
        )

    def generate_path(
        self,
        path_id: int,
        horizon: int,
        initial_fx: float = 1.09,
        initial_borrowing_rate: float = 0.04,
        initial_investment_rate: float = 0.05,
        dates: list[date] | None = None,
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
            dates=dates,
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
        dates: list[date] | None = None,
    ) -> list[ScenarioPath]:
        """Generate multiple multivariate Student-t scenario paths."""
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
