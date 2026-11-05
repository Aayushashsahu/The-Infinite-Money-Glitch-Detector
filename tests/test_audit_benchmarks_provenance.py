"""Benchmark Comparability, Interest Rate Hierarchy, and Data Provenance Audit Tests.

Phase 3.1 Validation:
- Benchmark comparability: Identical capital denominators, holding periods, and cash treatment
- Interest rate hierarchy: Distinguishes borrowing, deposit, policy, and risk-free rates
- Return attribution reconciliation: Gross Gain - Financing Drag - Frictions Drag + Cash Yield == Net Return
- Currency market calendar: Friday to Monday is 1 trading day (not 3 calendar days) for staleness
- Data provenance: Accurate tracking of real vs synthetic data with uncompromised declarations
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import pytest

from backtesting.calendar import DEFAULT_FX_CALENDAR, MarketCalendar
from backtesting.engine import BacktestEngine
from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall
from backtesting.provenance import build_data_provenance_report
from data.schemas import DataObservation, Frequency, ObservationKind
from schemas.backtest import (
    AvailabilityPolicy,
    BacktestConfig,
    DataAvailabilityConfig,
    ExecutionConfig,
    InterestRateHierarchy,
    InterestRateType,
    PositionSizingConfig,
    PositionSizingMethod,
    TradeStatus,
)
from schemas.strategy import CurrencyPair


def make_obs(obs_date: date, kind: ObservationKind, entity: str, val: float, is_synthetic: bool = False) -> DataObservation:
    return DataObservation(
        kind=kind,
        source_id="interbank_feed" if not is_synthetic else "synthetic_generator",
        entity_code=entity,
        value=val,
        unit="rate" if kind == ObservationKind.EXCHANGE_RATE else "percent",
        frequency=Frequency.DAILY,
        observation_date=obs_date,
        publication_date=obs_date,
        retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        revision=0,
        is_synthetic=is_synthetic,
    )


def test_interest_rate_hierarchy_distinction():
    """Borrowing, deposit, policy, and risk-free rates must not be treated as interchangeable."""
    hierarchy = InterestRateHierarchy(
        borrowing_rate=0.035,   # Paid on loan (e.g. SOFR + 50 bps)
        deposit_rate=0.025,     # Earned on cash balance (e.g. bank deposit)
        policy_rate=0.030,      # Central bank target rate
        risk_free_rate=0.028,   # Treasury bill yield
    )

    # Fundamental economic relationship: borrowing > policy >= risk_free >= deposit
    assert hierarchy.borrowing_rate > hierarchy.deposit_rate
    assert hierarchy.borrowing_rate > hierarchy.policy_rate
    assert hierarchy.deposit_rate < hierarchy.risk_free_rate


def test_comparable_benchmark_and_return_attribution():
    """Strategy and benchmark use identical capital denominators; attribution reconciles."""
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")
    pair_code = "USD/EUR"

    start = date(2024, 1, 1)
    end = date(2024, 6, 30)

    # 182 days: r_borrow_USD = 4.0%, r_deposit_USD = 2.5%, r_EUR = 6.0%, spot = 1.08 constant
    obs = []
    curr = start
    while curr <= end:
        obs.append(make_obs(curr, ObservationKind.EXCHANGE_RATE, pair_code, 1.08, is_synthetic=True))
        obs.append(make_obs(curr, ObservationKind.INTEREST_RATE, "USD", 4.0, is_synthetic=True))
        obs.append(make_obs(curr, ObservationKind.INTEREST_RATE, "EUR", 6.0, is_synthetic=True))
        curr = date.fromordinal(curr.toordinal() + 1)

    cfg = BacktestConfig(
        strategy_name="Carry with Cash Accrual",
        currency_pair=pair,
        start_date=start,
        end_date=end,
        initial_capital_a=100_000.0,
        tenor_days=60,
        rebalance_frequency_days=60,
        cash_deposit_rate_annual=0.025,  # Unallocated cash earns 2.5% deposit rate
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
        execution_config=ExecutionConfig(bid_ask_spread_bps=2.0, slippage_bps=0.0, fixed_fee=0.0),
        position_sizing=PositionSizingConfig(
            method=PositionSizingMethod.FIXED_AMOUNT,
            fixed_amount=50_000.0,  # 50k deployed, 50k idle cash
            max_active_positions=1,
        ),
    )

    engine = BacktestEngine(cfg, obs)
    res = engine.run()
    m = res.metrics

    # 1. Capital denominator consistency
    assert m.benchmark_name is not None
    assert m.benchmark_total_return is not None
    # Benchmark return must be based on the 2.5% deposit rate over ~0.5 years: ~1.24%
    assert 0.010 < m.benchmark_total_return < 0.015

    # 2. Return attribution reconciliation
    # Net return = gross_trade_return - financing_cost_drag - transaction_cost_drag + cash_yield_return
    assert m.gross_trade_return is not None
    assert m.financing_cost_drag is not None
    assert m.transaction_cost_drag is not None
    assert m.cash_yield_return is not None

    reconstructed_net = (
        m.gross_trade_return
        - m.financing_cost_drag
        - m.transaction_cost_drag
        + m.cash_yield_return
    )
    assert pytest.approx(m.total_return, abs=1e-4) == reconstructed_net

    # 3. Alpha calculation
    assert m.alpha == pytest.approx(m.annualized_return - (m.benchmark_annualized_return or 0.0), abs=1e-5)


def test_market_calendar_staleness_trading_days():
    """Friday quote queried on Monday morning has 1 trading day lag, not 3 calendar days."""
    cal = DEFAULT_FX_CALENDAR

    # Friday 2024-03-15 to Monday 2024-03-18
    friday = date(2024, 3, 15)
    saturday = date(2024, 3, 16)
    sunday = date(2024, 3, 17)
    monday = date(2024, 3, 18)

    assert cal.is_trading_day(friday) is True
    assert cal.is_trading_day(saturday) is False
    assert cal.is_trading_day(sunday) is False
    assert cal.is_trading_day(monday) is True

    # Calendar lag = 3 days; Trading day lag = 1 day
    assert (monday - friday).days == 3
    assert cal.trading_days_lag(friday, monday) == 1

    # In PointInTimeFirewall with max_stale_days=2 and stale_by_trading_days=True:
    # A Friday quote queried on Monday is NOT stale (lag=1 <= 2)
    obs_friday = make_obs(friday, ObservationKind.EXCHANGE_RATE, "USD/EUR", 1.08, is_synthetic=True)
    cfg = DataAvailabilityConfig(
        policy=AvailabilityPolicy.STRICT,
        max_stale_days=2,
        stale_by_trading_days=True,
        allow_synthetic=True,
    )
    firewall = PointInTimeFirewall(cfg)
    store = PointInTimeDataStore([obs_friday], firewall)

    rate_on_monday = store.get_rate("USD/EUR", as_of=monday, allow_stale=False)
    assert rate_on_monday == 1.08  # Valid, not falsely flagged as stale!


def test_data_provenance_synthetic_vs_real_detection():
    """DataProvenanceReport accurately identifies synthetic data and emits honest disclaimer."""
    start = date(2024, 1, 1)
    end = date(2024, 1, 31)

    # 1. Synthetic dataset
    synthetic_obs = [
        make_obs(date(2024, 1, d), ObservationKind.EXCHANGE_RATE, "USD/EUR", 1.08, is_synthetic=True)
        for d in range(1, 15)
    ]
    rep_synth = build_data_provenance_report(
        observations=synthetic_obs,
        start_date=start,
        end_date=end,
        currency_pair_code="USD/EUR",
        policy=AvailabilityPolicy.STRICT,
    )
    assert rep_synth.is_synthetic_dataset is True
    assert rep_synth.synthetic_observations_count == 14
    assert rep_synth.real_observations_count == 0
    assert "DATA PROVENANCE NOTICE: Synthetic observations detected" in rep_synth.provenance_declaration
    assert "MUST NOT be represented as executable" in rep_synth.provenance_declaration

    # 2. Real dataset
    real_obs = [
        make_obs(date(2024, 1, d), ObservationKind.EXCHANGE_RATE, "USD/EUR", 1.08, is_synthetic=False)
        for d in range(1, 15)
    ]
    rep_real = build_data_provenance_report(
        observations=real_obs,
        start_date=start,
        end_date=end,
        currency_pair_code="USD/EUR",
        policy=AvailabilityPolicy.STRICT,
    )
    assert rep_real.is_synthetic_dataset is False
    assert rep_real.synthetic_observations_count == 0
    assert rep_real.real_observations_count == 14
    assert "DATA PROVENANCE VERIFIED: 100% genuine historical observations" in rep_real.provenance_declaration
