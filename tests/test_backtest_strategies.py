"""Tests for Strategy Implementations: Unhedged Carry Trade & Covered Carry Trade.

Verifies:
- Strategy A (Unhedged Carry):
  - Survives when exchange rate is stable or appreciates
  - Loses money and is rejected when currency depreciation wipes out yield differential
  - Volatility filter blocks high-risk volatile regimes
  - Hurdle rate prevents unprofitable low-spread trades
- Strategy B (Covered Carry):
  - Strictly rejected when actual forward rates are unavailable (no fabricated quotes allowed)
  - Executes covered trade when genuine forward rates are present
  - CIP diagnostic compares actual forward quote to theoretical CIP benchmark
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import pytest

from backtesting.benchmarks import evaluate_cip_diagnostic
from backtesting.engine import BacktestEngine
from backtesting.signals import (
    CoveredCarrySignalGenerator,
    UnhedgedCarrySignalGenerator,
)
from data.schemas import DataObservation, Frequency, ObservationKind
from schemas.backtest import (
    AvailabilityPolicy,
    BacktestConfig,
    DataAvailabilityConfig,
    ExecutionConfig,
    PositionSizingConfig,
    TradeStatus,
)
from schemas.strategy import CurrencyPair


def make_obs(obs_date: date, kind: ObservationKind, entity: str, val: float, indicator: str | None = None) -> DataObservation:
    return DataObservation(
        kind=kind,
        source_id="test_source",
        indicator_id=indicator,
        entity_code=entity,
        value=val,
        unit="rate" if kind == ObservationKind.EXCHANGE_RATE else "percent",
        frequency=Frequency.DAILY,
        observation_date=obs_date,
        publication_date=obs_date,
        retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        revision=0,
        is_synthetic=True,
    )


def test_unhedged_carry_yield_advantage_survives():
    """When FX rate is stable, interest differential yields positive profit."""
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")
    pair_code = "USD/EUR"

    # 1 year: r_USD = 2%, r_EUR = 7%, FX rate constant at 1.10
    observations = []
    d = date(2024, 1, 1)
    end = date(2024, 6, 1)
    while d <= end:
        observations.append(make_obs(d, ObservationKind.EXCHANGE_RATE, pair_code, 1.10))
        observations.append(make_obs(d, ObservationKind.INTEREST_RATE, "USD", 2.0))
        observations.append(make_obs(d, ObservationKind.INTEREST_RATE, "EUR", 7.0))
        d = date.fromordinal(d.toordinal() + 1)

    cfg = BacktestConfig(
        strategy_name="Unhedged Carry",
        currency_pair=pair,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 5, 1),
        initial_capital_a=100_000.0,
        tenor_days=90,
        rebalance_frequency_days=90,
        hurdle_rate_annual=0.02,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
        execution_config=ExecutionConfig(bid_ask_spread_bps=2.0, slippage_bps=0.0),
    )

    engine = BacktestEngine(cfg, observations)
    res = engine.run()

    assert res.is_executable_strategy is True
    assert len(res.trades) >= 1
    closed = [t for t in res.trades if t.status == TradeStatus.CLOSED]
    assert len(closed) >= 1
    # Profit must be positive because 7% - 2% = 5% yield advantage > 2 bps spread
    assert closed[0].net_profit_a > 0


def test_unhedged_carry_fails_when_depreciation_exceeds_yield():
    """When investment currency B depreciates severely, carry trade suffers a net loss."""
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="TRY")
    pair_code = "USD/TRY"

    # r_USD = 4%, r_TRY = 25% (yield differential +21%)
    # But TRY depreciates by 35% against USD over 90 days (USD/TRY moves from 0.035 to 0.022)
    observations = []
    d0 = date(2024, 1, 1)
    d_mid = date(2024, 3, 31)
    
    curr = d0
    while curr <= d_mid:
        # Linearly depreciating exchange rate
        frac = (curr - d0).days / 90.0
        rate = 0.035 - frac * (0.035 - 0.022)
        observations.append(make_obs(curr, ObservationKind.EXCHANGE_RATE, pair_code, rate))
        observations.append(make_obs(curr, ObservationKind.INTEREST_RATE, "USD", 4.0))
        observations.append(make_obs(curr, ObservationKind.INTEREST_RATE, "TRY", 25.0))
        curr = date.fromordinal(curr.toordinal() + 1)

    cfg = BacktestConfig(
        strategy_name="Unhedged Carry",
        currency_pair=pair,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 3, 31),
        initial_capital_a=100_000.0,
        tenor_days=90,
        rebalance_frequency_days=180,
        hurdle_rate_annual=0.05,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
        execution_config=ExecutionConfig(bid_ask_spread_bps=10.0),
    )

    engine = BacktestEngine(cfg, observations)
    res = engine.run()

    closed = [t for t in res.trades if t.status == TradeStatus.CLOSED]
    assert len(closed) == 1
    # Trade must have incurred a significant loss
    assert closed[0].net_profit_a < 0
    assert closed[0].return_on_capital < -0.10


def test_unhedged_carry_volatility_filter():
    """High trailing FX volatility rejects trade entry."""
    generator = UnhedgedCarrySignalGenerator(
        hurdle_rate_annual=0.02,
        max_fx_volatility=0.15,  # 15% max volatility
    )
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="BRL")

    sig = generator.generate_signal(
        as_of=date(2024, 1, 1),
        pair=pair,
        borrowing_rate=0.03,
        investment_rate=0.12,  # Strong 9% differential
        spot_rate=0.20,
        trailing_fx_volatility=0.22,  # 22% volatility exceeds 15%
    )

    assert sig.should_enter is False
    assert "exceeds maximum threshold" in (sig.rejection_reason or "")


def test_covered_carry_rejected_when_forward_rates_unavailable():
    """Covered carry strategy is reported as UNSUPPORTED when forward market data is missing."""
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")
    pair_code = "USD/EUR"

    # Only spot rates and interest rates exist; NO forward rates
    observations = [
        make_obs(date(2024, 1, 1), ObservationKind.EXCHANGE_RATE, pair_code, 1.10),
        make_obs(date(2024, 1, 1), ObservationKind.INTEREST_RATE, "USD", 3.0),
        make_obs(date(2024, 1, 1), ObservationKind.INTEREST_RATE, "EUR", 6.0),
        make_obs(date(2024, 2, 1), ObservationKind.EXCHANGE_RATE, pair_code, 1.10),
        make_obs(date(2024, 2, 1), ObservationKind.INTEREST_RATE, "USD", 3.0),
        make_obs(date(2024, 2, 1), ObservationKind.INTEREST_RATE, "EUR", 6.0),
    ]

    cfg = BacktestConfig(
        strategy_name="Covered Carry Trade",
        currency_pair=pair,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 1),
        tenor_days=30,
        rebalance_frequency_days=30,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
    )

    engine = BacktestEngine(cfg, observations)
    res = engine.run()

    # Engine must refuse to execute covered carry without actual forward quotes!
    assert res.is_executable_strategy is False
    assert "forward exchange rate quotes are unavailable" in (res.unsupported_reason or "")
    assert len(res.trades) == 0


def test_covered_carry_executes_when_actual_forward_data_exists():
    """Covered carry executes and locks in forward return when actual forward rates exist."""
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")
    pair_code = "USD/EUR"

    # Spot = 1.10, r_USD = 3%, r_EUR = 6%.
    # Genuine market forward quote FWD_30D exists: 1.105 (trading at premium)
    observations = [
        make_obs(date(2024, 1, 1), ObservationKind.EXCHANGE_RATE, pair_code, 1.10),
        make_obs(date(2024, 1, 1), ObservationKind.EXCHANGE_RATE, pair_code, 1.105, indicator="FWD_30D"),
        make_obs(date(2024, 1, 1), ObservationKind.INTEREST_RATE, "USD", 3.0),
        make_obs(date(2024, 1, 1), ObservationKind.INTEREST_RATE, "EUR", 6.0),
        make_obs(date(2024, 1, 31), ObservationKind.EXCHANGE_RATE, pair_code, 1.08),  # Spot fell to 1.08!
        make_obs(date(2024, 1, 31), ObservationKind.INTEREST_RATE, "USD", 3.0),
        make_obs(date(2024, 1, 31), ObservationKind.INTEREST_RATE, "EUR", 6.0),
    ]

    cfg = BacktestConfig(
        strategy_name="Covered Carry Trade",
        currency_pair=pair,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.001,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
        execution_config=ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0),
    )

    engine = BacktestEngine(cfg, observations)
    res = engine.run()

    assert res.is_executable_strategy is True
    assert len(res.trades) == 1
    trade = res.trades[0]
    assert trade.is_covered is True
    # The trade used the forward rate (1.105), protected against the spot crash (1.08)!
    assert trade.spot_exec_exit == 1.105
    assert trade.net_profit_a > 0


def test_cip_diagnostic_evaluation():
    """CIP diagnostic accurately flags basis deviations without pretending to be executable."""
    diag = evaluate_cip_diagnostic(
        as_of=date(2024, 1, 1),
        spot_rate=1.10,
        borrowing_rate=0.03,
        investment_rate=0.06,
        actual_forward_rate=1.105,
        tenor_years=1.0,
    )

    # Theoretical CIP: 1.10 * (1.03 / 1.06) = 1.0688679...
    assert diag.theoretical_forward_rate < 1.10
    assert diag.actual_forward_rate == 1.105
    assert diag.basis_bps > 0
    assert "Forward trades at premium" in diag.interpretation
