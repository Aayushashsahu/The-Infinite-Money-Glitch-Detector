"""Unit tests for core currency conversion, with the fixed convention
X = units of A per unit of B.
"""

from math import isclose

import pytest

from core.currency import convert_to_a, convert_to_b, inverse_rate, validate_currency_code


def test_convert_borrowing_to_investment() -> None:
    # X0 = 1 A per B: 100,000 A -> 100,000 B.
    assert isclose(convert_to_b(100_000.0, 1.0), 100_000.0)


def test_convert_investment_back_to_borrowing() -> None:
    # X1 = 1.15 A per B: 105,000 B -> 120,750 A (milestone value).
    assert isclose(convert_to_a(105_000.0, 1.15), 120_750.0)


def test_round_trip_is_lossless() -> None:
    assert isclose(convert_to_a(convert_to_b(1_234.56, 1.23), 1.23), 1_234.56)


def test_inverse_rate() -> None:
    assert isclose(inverse_rate(4.0), 0.25)
    assert isclose(inverse_rate(inverse_rate(1.15)), 1.15)


@pytest.mark.parametrize("bad", ["us", "USDX", "12A", "", "USD "])
def test_currency_code_validation_rejects_garbage(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_currency_code(bad)


def test_currency_code_validation_uppercases() -> None:
    assert validate_currency_code("eur") == "EUR"


@pytest.mark.parametrize("bad_rate", [0.0, -1.0])
def test_conversions_reject_nonpositive_rates(bad_rate: float) -> None:
    with pytest.raises(ValueError):
        convert_to_b(100.0, bad_rate)
    with pytest.raises(ValueError):
        convert_to_a(100.0, bad_rate)
    with pytest.raises(ValueError):
        inverse_rate(bad_rate)
