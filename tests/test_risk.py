"""Unit tests for risk metrics against hand-computed values.

Conventions under test:
- historical VaR uses the empirical quantile with method="lower"
  (worst observed value, no interpolation);
- CVaR is the mean of returns at or below the VaR threshold;
- volatility is the sample std (ddof=1), annualized by sqrt(periods/year).
"""

from math import isclose, sqrt

import pytest

from models.risk import (
    break_even_probability,
    historical_cvar,
    historical_var,
    historical_volatility,
    max_drawdown,
    sharpe_ratio,
)

# 10 observations with a known sorted order for the tail math below.
TEN_RETURNS = [0.01, -0.02, 0.03, -0.01, 0.005, -0.015, 0.02, 0.025, -0.005, 0.015]
# Sorted: [-0.02, -0.015, -0.01, -0.005, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03]


def test_historical_var_lower_method() -> None:
    # alpha = 0.05 -> index floor(0.05 * 9) = 0 -> worst observed: -0.02.
    assert isclose(historical_var(TEN_RETURNS, 0.95), -0.02)


def test_historical_cvar_is_tail_mean() -> None:
    # At 80 % confidence, alpha = 0.20 -> index floor(0.20 * 9) = 1 -> VaR = -0.015.
    # The tail is every observation <= VaR: (-0.02, -0.015); mean = -0.0175.
    assert isclose(historical_var(TEN_RETURNS, 0.80), -0.015)
    assert isclose(historical_cvar(TEN_RETURNS, 0.80), -0.0175)


def test_cvar_collapses_to_var_for_singleton_tail() -> None:
    # At 95 % confidence the threshold IS the single worst observation,
    # so the empirical tail mean equals the VaR value. Expected behavior,
    # documented convention, not a bug.
    assert isclose(historical_var(TEN_RETURNS, 0.95), -0.02)
    assert isclose(historical_cvar(TEN_RETURNS, 0.95), -0.02)


def test_var_cvar_confidence_validation() -> None:
    with pytest.raises(ValueError):
        historical_var(TEN_RETURNS, 0.0)
    with pytest.raises(ValueError):
        historical_var(TEN_RETURNS, 1.0)


def test_max_drawdown_compounded() -> None:
    # Equity: 1.01 -> 0.9898 (drawdown 0.9898/1.01 - 1 = -0.02) -> 1.009596 recovery.
    assert isclose(max_drawdown([0.01, -0.02, 0.02]), -0.02)


def test_max_drawdown_monotonic_series_is_zero() -> None:
    assert isclose(max_drawdown([0.01, 0.01, 0.01]), 0.0)


def test_max_drawdown_rejects_total_loss_input() -> None:
    with pytest.raises(ValueError):
        max_drawdown([-1.0, 0.1])


def test_historical_volatility_sample_std() -> None:
    returns = [0.01, -0.02, 0.03, -0.01]
    # mean = 0.0025; sample variance = 1.475e-3 / 3; std ≈ 0.0221736.
    expected_std = sqrt(1.475e-3 / 3)
    assert isclose(historical_volatility(returns, periods_per_year=1.0), expected_std, abs_tol=1e-8)
    assert isclose(historical_volatility(returns, periods_per_year=4.0), 2.0 * expected_std, abs_tol=1e-8)


def test_sharpe_ratio() -> None:
    returns = [0.01, -0.02, 0.03, -0.01]
    std = sqrt(1.475e-3 / 3)
    # mean 0.0025 - per-period rf (0.04 / 4 = 0.01) = -0.0075; annualized * sqrt(4).
    expected = (-0.0075 / std) * 2.0
    assert isclose(sharpe_ratio(returns, risk_free_rate_annual=0.04, periods_per_year=4.0), expected, abs_tol=1e-8)


def test_sharpe_undefined_for_zero_volatility() -> None:
    with pytest.raises(ValueError):
        sharpe_ratio([0.0, 0.0, 0.0, 0.0], risk_free_rate_annual=0.04)


def test_break_even_probability() -> None:
    # 3 of 5 scenarios non-negative.
    assert isclose(break_even_probability([10.0, -5.0, 20.0, -1.0, 3.0]), 0.6)


def test_missing_data_is_never_silently_accepted() -> None:
    with pytest.raises(ValueError):
        historical_volatility([0.01, float("nan"), 0.02])
    with pytest.raises(ValueError):
        historical_cvar([0.01, float("inf"), 0.02], 0.95)


def test_too_few_observations_rejected() -> None:
    with pytest.raises(ValueError):
        historical_volatility([0.01])
