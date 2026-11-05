"""Historical risk statistics on plain sequences of returns or P/L.

Deterministic, array-based metrics. Conventions are explicit and fixed:

* **Volatility**: sample standard deviation (``ddof=1``) of period
  returns, annualized by ``sqrt(periods_per_year)``.
* **Maximum drawdown**: largest peak-to-trough decline of the
  *compounded* equity curve, returned as a negative fraction.
* **VaR**: historical (empirical) quantile of period returns at level
  ``1 - confidence``, using the *lower* method (worst observed value, no
  interpolation - conservative for short samples). Reported as a return
  fraction; the corresponding loss is its negation.
* **CVaR**: expected shortfall - mean of returns at or below the VaR
  threshold.
* **Sharpe**: ``(mean return − per-period risk-free rate) / std``,
  annualized by ``sqrt(periods_per_year)``. The caller MUST supply a
  defensible risk-free benchmark; there is no default.

Known limitations (documented, not hidden): all metrics are sample
statistics of the supplied history only. VaR/CVaR say nothing beyond the
observed tail; drawdown depends on the observation frequency; and small
samples make every number unstable.
"""

from __future__ import annotations

import numpy as np


def _as_observations(values, name: str = "returns") -> np.ndarray:
    """Coerce input to a clean 1-D float array with explicit rejection of bad data."""
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1 or arr.size < 2:
        raise ValueError(f"{name} must be a 1-D sequence with at least 2 observations, got shape {arr.shape}.")
    if np.isnan(arr).any() or np.isinf(arr).any():
        raise ValueError(
            f"{name} contains NaN/inf values. Missing financial data must be handled explicitly, never silently."
        )
    return arr


def _check_periods_per_year(periods_per_year: float) -> None:
    if periods_per_year is None or periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be positive, got {periods_per_year!r}.")


def historical_volatility(returns, periods_per_year: float = 1.0) -> float:
    """Annualized sample volatility of period returns.

    Args:
        returns: 1-D sequence of periodic returns as fractions.
        periods_per_year: Observation frequency (12 = monthly, 252 = daily), > 0.
    """
    r = _as_observations(returns)
    _check_periods_per_year(periods_per_year)
    return float(np.std(r, ddof=1) * np.sqrt(periods_per_year))


def max_drawdown(returns) -> float:
    """Largest peak-to-trough decline of the compounded equity curve.

    Args:
        returns: 1-D sequence of periodic returns as fractions, each > -1.

    Returns:
        Negative fraction (e.g. -0.02 = a 2 % drawdown).
    """
    r = _as_observations(returns)
    if np.any(r <= -1.0):
        raise ValueError(
            "max_drawdown expects period returns greater than -100%; a total loss cannot be compounded further."
        )
    wealth = np.insert(np.cumprod(1.0 + r), 0, 1.0)
    peak = np.maximum.accumulate(wealth)
    return float(np.min(wealth / peak - 1.0))


def historical_var(returns, confidence: float = 0.95) -> float:
    """Historical (empirical) Value at Risk of period returns.

    The alpha-quantile at ``1 - confidence`` using numpy's ``lower``
    method: i.e. the worst *observed* value inside the tail, with no
    interpolation (conservative for short samples).

    Args:
        returns: 1-D sequence of periodic returns as fractions.
        confidence: Confidence level in (0, 1); 0.95 = 95 % VaR.

    Returns:
        Return fraction; the loss is ``-result``.
    """
    r = _as_observations(returns)
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence!r}.")
    return float(np.quantile(r, 1.0 - confidence, method="lower"))


def historical_cvar(returns, confidence: float = 0.95) -> float:
    """Historical CVaR (expected shortfall): mean of returns at/below the VaR threshold."""
    r = _as_observations(returns)
    var = historical_var(r, confidence)
    tail = r[r <= var]
    return float(tail.mean())


def sharpe_ratio(returns, risk_free_rate_annual: float = 0.0, periods_per_year: float = 1.0) -> float:
    """Annualized Sharpe ratio of period returns.

    ``(mean(returns) - per-period risk-free) / std(returns) * sqrt(periods_per_year)``,
    where the per-period risk-free rate is ``risk_free_rate_annual /
    periods_per_year`` (simple allocation).

    The caller must supply a *defensible* benchmark for
    ``risk_free_rate_annual``; this module does not invent one.

    Raises:
        ValueError: if volatility is zero (Sharpe is undefined).
    """
    r = _as_observations(returns)
    _check_periods_per_year(periods_per_year)
    std = np.std(r, ddof=1)
    if std == 0:
        raise ValueError("Sharpe ratio is undefined for zero volatility.")
    per_period_rf = risk_free_rate_annual / periods_per_year
    excess = float(np.mean(r)) - per_period_rf
    return float(excess / std * np.sqrt(periods_per_year))


def break_even_probability(profit_scenarios) -> float:
    """Share of equally-weighted scenarios with profit >= 0.

    Args:
        profit_scenarios: 1-D sequence of scenario profits/losses in any currency.
    """
    p = _as_observations(profit_scenarios, "profit scenarios")
    return float(np.count_nonzero(p >= 0) / p.size)
