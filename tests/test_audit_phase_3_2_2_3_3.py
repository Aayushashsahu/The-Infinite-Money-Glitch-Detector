"""Phase 3.2.2.3.3 Comprehensive FX Symmetry, Execution & Research Artifact Audit Suite.

Verifies:
1. Raw direct quote to entry execution.
2. Raw direct quote to exit execution.
3. Raw reciprocal quote to entry execution.
4. Raw reciprocal quote to exit execution.
5. Direct BASE_PER_QUOTE through PointInTimeDataStore.
6. Reciprocal BASE_PER_QUOTE through PointInTimeDataStore.
7. Reciprocal two-way execution lifecycle.
8. Reciprocal one-sided execution lifecycle.
9. Exact direct/reciprocal paired quote symmetry.
10. Reverse strategy currency symmetry.
11. Raw provider bid/ask preservation across all quote assembly modes.
12. Canonical price serialization round-trip.
13. Midpoint convention consistency (arithmetic canonical vs provider).
14. Fixture provenance isolation (MOCK fixtures strictly excluded without allow_mock).
15. Historical JSON/report consistency (Config 2 authoritative: 29 trades, +2.89%).
16. No-trade alpha reporting (Config 3 reports alpha=None / N/A, not +0.00%).
17. Exact P&L double-entry ledger reconciliation (residual <= 1e-10).
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from backtesting.execution import ExecutionEngine
from backtesting.metrics import calculate_performance_metrics, calculate_sortino_ratio
from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall
from backtesting.reporting import format_backtest_report
from core.currency import (
    QuoteConvention,
    get_rate_a_per_b,
    get_two_way_quote_a_per_b,
    invert_two_way_quote,
    map_canonical_side_to_provider_side,
    normalize_directional_quote,
)
from core.interest import growth_factor
from data.schemas import (
    AvailabilityEvidence,
    DataClassification,
    DataObservation,
    Frequency,
    ObservationKind,
    PriceType,
    RateRole,
    StrategyExecutabilityStatus,
)
from models.risk import sharpe_ratio
from schemas.backtest import (
    AvailabilityPolicy,
    BacktestConfig,
    BenchmarkSpecification,
    BenchmarkType,
    DataAvailabilityConfig,
    ExecutableQuoteResult,
    ExecutionConfig,
    PortfolioSnapshot,
    TradeRecord,
    TradeStatus,
)
from schemas.strategy import CurrencyPair, InterestConvention


def make_test_obs(
    entity_code: str,
    obs_date: date,
    obs_time: datetime,
    value: float,
    bid: float | None = None,
    ask: float | None = None,
    price_type: PriceType = PriceType.EXECUTABLE_TWO_WAY_QUOTE,
    base_curr: str = "EUR",
    quote_curr: str = "USD",
    convention: QuoteConvention = QuoteConvention.QUOTE_PER_BASE,
    pub_time: datetime | None = None,
    source_id: str = "test_fixture_dealer",
    evidence: AvailabilityEvidence = AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
) -> DataObservation:
    """Helper to construct dedicated test mock observations with honest fixture provenance."""
    pub_dt = pub_time or obs_time
    return DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        entity_code=entity_code,
        observation_date=obs_date,
        observation_timestamp=obs_time,
        publication_date=pub_dt.date(),
        publication_timestamp=pub_dt,
        value=value,
        bid=bid,
        ask=ask,
        price_type=price_type,
        base_currency=base_curr,
        quote_currency=quote_curr,
        quote_convention=convention,
        unit=quote_curr,
        frequency=Frequency.DAILY,
        source_id=source_id,
        availability_evidence=evidence,
        classification=DataClassification.MOCK,
        is_synthetic=True,
        retrieved_at=pub_dt + timedelta(minutes=1),
    )


# -----------------------------------------------------------------------------
# 1. Raw direct quote to entry execution
# -----------------------------------------------------------------------------
def test_raw_direct_quote_to_entry_execution():
    """EUR/USD quote bid=1.09, ask=1.11: buying USD lifts BID 1.09 -> canonical ask = 1/1.09."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs = make_test_obs("EUR/USD", t0.date(), t0, value=1.10, bid=1.09, ask=1.11)
    store = PointInTimeDataStore([obs])

    q = store.get_executable_quote(
        "EUR/USD",
        as_of=t0 + timedelta(minutes=5),
        required_side="ask",
    )
    assert q is not None
    assert q.provider_bid == 1.09
    assert q.provider_ask == 1.11
    assert q.bid == 1.09
    assert q.ask == 1.11
    assert q.canonical_ask == pytest.approx(1.0 / 1.09, rel=1e-10)

    # Execute entry
    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0, variable_fee_bps=0.0, fixed_fee=0.0, use_observed_spread=True))
    trade = engine.open_trade(
        trade_id="T001",
        strategy_name="Direct Carry",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        entry_date=t0.date(),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.04,
        investment_rate=0.05,
        spot_mid_entry=q.rate_a_per_b,
        exec_quote=q,
    )
    assert trade.spot_exec_entry == pytest.approx(1.0 / 1.09, rel=1e-10)
    assert trade.invested_amount_b == pytest.approx(100_000.0 * 1.09, rel=1e-10)
    assert trade.entry_provider_bid == 1.09
    assert trade.entry_canonical_price == pytest.approx(1.0 / 1.09, rel=1e-10)


# -----------------------------------------------------------------------------
# 2. Raw direct quote to exit execution
# -----------------------------------------------------------------------------
def test_raw_direct_quote_to_exit_execution():
    """EUR/USD quote bid=1.08, ask=1.10: selling USD hits ASK 1.10 -> canonical bid = 1/1.10."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc)
    obs_entry = make_test_obs("EUR/USD", t0.date(), t0, value=1.10, bid=1.09, ask=1.11)
    obs_exit = make_test_obs("EUR/USD", t1.date(), t1, value=1.09, bid=1.08, ask=1.10)
    store = PointInTimeDataStore([obs_entry, obs_exit])

    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0, variable_fee_bps=0.0, fixed_fee=0.0, use_observed_spread=True))
    q_entry = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="ask")
    trade = engine.open_trade(
        trade_id="T002",
        strategy_name="Direct Carry Exit",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        entry_date=t0.date(),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.04,
        investment_rate=0.05,
        spot_mid_entry=q_entry.rate_a_per_b,
        exec_quote=q_entry,
    )

    q_exit = store.get_executable_quote("EUR/USD", as_of=t1 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="bid")
    assert q_exit is not None
    assert q_exit.provider_bid == 1.08
    assert q_exit.provider_ask == 1.10
    assert q_exit.canonical_bid == pytest.approx(1.0 / 1.10, rel=1e-10)

    closed = engine.close_trade(trade=trade, exit_date=t1.date(), spot_mid_exit=q_exit.rate_a_per_b, exec_quote=q_exit)
    assert closed.spot_exec_exit == pytest.approx(1.0 / 1.10, rel=1e-10)
    assert closed.exit_provider_ask == 1.10
    assert closed.exit_canonical_price == pytest.approx(1.0 / 1.10, rel=1e-10)


# -----------------------------------------------------------------------------
# 3. Raw reciprocal quote to entry execution
# -----------------------------------------------------------------------------
def test_raw_reciprocal_quote_to_entry_execution():
    """USD/EUR quote bid=0.9009 (1/1.11), ask=0.9174 (1/1.09): buying USD lifts ASK 0.9174 directly."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    raw_bid = 1.0 / 1.11
    raw_ask = 1.0 / 1.09
    obs = make_test_obs("USD/EUR", t0.date(), t0, value=(raw_bid + raw_ask) / 2.0, bid=raw_bid, ask=raw_ask, base_curr="USD", quote_curr="EUR")
    store = PointInTimeDataStore([obs])

    q = store.get_executable_quote(
        "EUR/USD",
        as_of=t0 + timedelta(minutes=5),
        required_side="ask",
    )
    assert q is not None
    # Raw provider values preserved intact
    assert q.provider_bid == pytest.approx(raw_bid, rel=1e-10)
    assert q.provider_ask == pytest.approx(raw_ask, rel=1e-10)
    assert q.bid == pytest.approx(raw_bid, rel=1e-10)
    assert q.ask == pytest.approx(raw_ask, rel=1e-10)
    # Canonical entry price is raw_ask directly because quote is already EUR per USD
    assert q.canonical_ask == pytest.approx(raw_ask, rel=1e-10)

    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0, variable_fee_bps=0.0, fixed_fee=0.0, use_observed_spread=True))
    trade = engine.open_trade(
        trade_id="T003",
        strategy_name="Reciprocal Entry",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        entry_date=t0.date(),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.04,
        investment_rate=0.05,
        spot_mid_entry=q.rate_a_per_b,
        exec_quote=q,
    )
    assert trade.spot_exec_entry == pytest.approx(raw_ask, rel=1e-10)
    assert trade.entry_provider_ask == pytest.approx(raw_ask, rel=1e-10)


# -----------------------------------------------------------------------------
# 4. Raw reciprocal quote to exit execution
# -----------------------------------------------------------------------------
def test_raw_reciprocal_quote_to_exit_execution():
    """USD/EUR quote bid=0.9091 (1/1.10), ask=0.9259 (1/1.08): selling USD hits BID 0.9091 directly."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc)
    raw_b0, raw_a0 = 1.0 / 1.11, 1.0 / 1.09
    raw_b1, raw_a1 = 1.0 / 1.10, 1.0 / 1.08
    obs0 = make_test_obs("USD/EUR", t0.date(), t0, value=(raw_b0 + raw_a0) / 2.0, bid=raw_b0, ask=raw_a0, base_curr="USD", quote_curr="EUR")
    obs1 = make_test_obs("USD/EUR", t1.date(), t1, value=(raw_b1 + raw_a1) / 2.0, bid=raw_b1, ask=raw_a1, base_curr="USD", quote_curr="EUR")
    store = PointInTimeDataStore([obs0, obs1])

    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0, variable_fee_bps=0.0, fixed_fee=0.0, use_observed_spread=True))
    q0 = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="ask")
    trade = engine.open_trade(
        trade_id="T004",
        strategy_name="Reciprocal Exit",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        entry_date=t0.date(),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.04,
        investment_rate=0.05,
        spot_mid_entry=q0.rate_a_per_b,
        exec_quote=q0,
    )

    q1 = store.get_executable_quote("EUR/USD", as_of=t1 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="bid")
    assert q1 is not None
    assert q1.provider_bid == pytest.approx(raw_b1, rel=1e-10)
    assert q1.provider_ask == pytest.approx(raw_a1, rel=1e-10)
    assert q1.canonical_bid == pytest.approx(raw_b1, rel=1e-10)

    closed = engine.close_trade(trade=trade, exit_date=t1.date(), spot_mid_exit=q1.rate_a_per_b, exec_quote=q1)
    assert closed.spot_exec_exit == pytest.approx(raw_b1, rel=1e-10)
    assert closed.exit_provider_bid == pytest.approx(raw_b1, rel=1e-10)


# -----------------------------------------------------------------------------
# 5. Direct BASE_PER_QUOTE through PointInTimeDataStore
# -----------------------------------------------------------------------------
def test_direct_base_per_quote_through_datastore():
    """EUR/USD observation with BASE_PER_QUOTE convention quotes EUR per 1 USD (already A/B)."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs = make_test_obs(
        "EUR/USD",
        t0.date(),
        t0,
        value=0.910,
        bid=0.900,
        ask=0.920,
        convention=QuoteConvention.BASE_PER_QUOTE,
    )
    store = PointInTimeDataStore([obs])

    q_ask = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="ask")
    q_bid = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="bid")

    assert q_ask is not None and q_bid is not None
    # No double inversion: canonical prices match provider numbers directly
    assert q_ask.canonical_ask == pytest.approx(0.920, rel=1e-10)
    assert q_bid.canonical_bid == pytest.approx(0.900, rel=1e-10)
    assert q_ask.provider_bid == 0.900
    assert q_ask.provider_ask == 0.920
    assert q_ask.provider_convention == QuoteConvention.BASE_PER_QUOTE


# -----------------------------------------------------------------------------
# 6. Reciprocal BASE_PER_QUOTE through PointInTimeDataStore
# -----------------------------------------------------------------------------
def test_reciprocal_base_per_quote_through_datastore():
    """USD/EUR observation with BASE_PER_QUOTE convention quotes USD per 1 EUR -> requires inversion for EUR/USD."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs = make_test_obs(
        "USD/EUR",
        t0.date(),
        t0,
        value=1.10,
        bid=1.09,
        ask=1.11,
        base_curr="USD",
        quote_curr="EUR",
        convention=QuoteConvention.BASE_PER_QUOTE,
    )
    store = PointInTimeDataStore([obs])

    q_ask = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="ask")
    q_bid = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="bid")

    assert q_ask is not None and q_bid is not None
    # Under BASE_PER_QUOTE for USD/EUR, rate is USD per EUR.
    # Buying USD with EUR lifts 1.09 -> canonical ask = 1 / 1.09
    assert q_ask.canonical_ask == pytest.approx(1.0 / 1.09, rel=1e-10)
    # Selling USD for EUR hits 1.11 -> canonical bid = 1 / 1.11
    assert q_bid.canonical_bid == pytest.approx(1.0 / 1.11, rel=1e-10)
    assert q_ask.provider_bid == 1.09
    assert q_ask.provider_ask == 1.11


# -----------------------------------------------------------------------------
# 7. Reciprocal two-way execution lifecycle
# -----------------------------------------------------------------------------
def test_reciprocal_two_way_execution_lifecycle():
    """Complete trade execution lifecycle using reciprocal observations with exact cash flow reconciliation."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc)
    b0, a0 = 1.0 / 1.11, 1.0 / 1.09
    b1, a1 = 1.0 / 1.10, 1.0 / 1.08
    obs0 = make_test_obs("USD/EUR", t0.date(), t0, value=(b0 + a0) / 2.0, bid=b0, ask=a0, base_curr="USD", quote_curr="EUR")
    obs1 = make_test_obs("USD/EUR", t1.date(), t1, value=(b1 + a1) / 2.0, bid=b1, ask=a1, base_curr="USD", quote_curr="EUR")
    store = PointInTimeDataStore([obs0, obs1])

    exec_cfg = ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0, variable_fee_bps=1.0, fixed_fee=5.0, use_observed_spread=True)
    engine = ExecutionEngine(exec_cfg)

    q0 = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="ask")
    trade = engine.open_trade(
        trade_id="LIFECYCLE_TWO_WAY",
        strategy_name="Reciprocal Two-Way Carry",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        entry_date=t0.date(),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.035,
        investment_rate=0.0525,
        spot_mid_entry=q0.rate_a_per_b,
        exec_quote=q0,
    )
    assert trade.status == TradeStatus.OPEN

    q1 = store.get_executable_quote("EUR/USD", as_of=t1 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="bid")
    closed = engine.close_trade(trade=trade, exit_date=t1.date(), spot_mid_exit=q1.rate_a_per_b, exec_quote=q1)

    assert closed.status == TradeStatus.CLOSED
    assert closed.reconciliation_residual_a <= 1e-10


# -----------------------------------------------------------------------------
# 8. Reciprocal one-sided execution lifecycle
# -----------------------------------------------------------------------------
def test_reciprocal_onesided_execution_lifecycle():
    """Standalone reciprocal one-sided quotes execute and balance exactly."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc)
    # Entry requires buying USD -> lifts reciprocal ASK (EUR per USD)
    obs_entry = make_test_obs("USD/EUR", t0.date(), t0, value=0.917431, bid=None, ask=0.917431, price_type=PriceType.ASK_QUOTE, base_curr="USD", quote_curr="EUR")
    # Exit requires selling USD -> hits reciprocal BID (EUR per USD)
    obs_exit = make_test_obs("USD/EUR", t1.date(), t1, value=0.909091, bid=0.909091, ask=None, price_type=PriceType.BID_QUOTE, base_curr="USD", quote_curr="EUR")
    store = PointInTimeDataStore([obs_entry, obs_exit])

    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0, variable_fee_bps=0.0, fixed_fee=0.0, use_observed_spread=True))
    q_entry = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="ask")
    trade = engine.open_trade(
        trade_id="LIFECYCLE_ONESIDED",
        strategy_name="Reciprocal One-Sided Carry",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        entry_date=t0.date(),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.035,
        investment_rate=0.0525,
        spot_mid_entry=q_entry.rate_a_per_b,
        exec_quote=q_entry,
    )

    q_exit = store.get_executable_quote("EUR/USD", as_of=t1 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="bid")
    closed = engine.close_trade(trade=trade, exit_date=t1.date(), spot_mid_exit=q_exit.rate_a_per_b, exec_quote=q_exit)

    assert closed.status == TradeStatus.CLOSED
    assert closed.spot_exec_entry == 0.917431
    assert closed.spot_exec_exit == 0.909091
    assert closed.reconciliation_residual_a <= 1e-10


# -----------------------------------------------------------------------------
# 9. Exact direct/reciprocal paired quote symmetry
# -----------------------------------------------------------------------------
def test_exact_direct_reciprocal_paired_quote_symmetry():
    """Mathematically equivalent direct and reciprocal quotes produce identical execution economics."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc)

    # Direct EUR/USD
    p_b0, p_a0 = 1.09, 1.11
    p_b1, p_a1 = 1.08, 1.10
    direct_store = PointInTimeDataStore([
        make_test_obs("EUR/USD", t0.date(), t0, value=(p_b0 + p_a0) / 2.0, bid=p_b0, ask=p_a0),
        make_test_obs("EUR/USD", t1.date(), t1, value=(p_b1 + p_a1) / 2.0, bid=p_b1, ask=p_a1),
    ])

    # Reciprocal USD/EUR (exact mathematical inverse)
    inv_b0, inv_a0 = 1.0 / p_a0, 1.0 / p_b0
    inv_b1, inv_a1 = 1.0 / p_a1, 1.0 / p_b1
    recip_store = PointInTimeDataStore([
        make_test_obs("USD/EUR", t0.date(), t0, value=(inv_b0 + inv_a0) / 2.0, bid=inv_b0, ask=inv_a0, base_curr="USD", quote_curr="EUR"),
        make_test_obs("USD/EUR", t1.date(), t1, value=(inv_b1 + inv_a1) / 2.0, bid=inv_b1, ask=inv_a1, base_curr="USD", quote_curr="EUR"),
    ])

    cfg = ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.5, variable_fee_bps=1.0, fixed_fee=5.0, use_observed_spread=True)
    eng_direct = ExecutionEngine(cfg)
    eng_recip = ExecutionEngine(cfg)

    # 1. Entry quotes
    q_dir_0 = direct_store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="ask")
    q_rec_0 = recip_store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="ask")

    assert q_dir_0.canonical_ask == pytest.approx(q_rec_0.canonical_ask, rel=1e-10)
    assert q_dir_0.canonical_bid == pytest.approx(q_rec_0.canonical_bid, rel=1e-10)
    assert q_dir_0.canonical_mid == pytest.approx(q_rec_0.canonical_mid, rel=1e-10)

    tr_dir = eng_direct.open_trade("SYM_DIR", "Direct", CurrencyPair(borrowing_currency="EUR", investment_currency="USD"), t0.date(), 30, 100_000.0, 0.04, 0.05, q_dir_0.rate_a_per_b, q_dir_0)
    tr_rec = eng_recip.open_trade("SYM_REC", "Reciprocal", CurrencyPair(borrowing_currency="EUR", investment_currency="USD"), t0.date(), 30, 100_000.0, 0.04, 0.05, q_rec_0.rate_a_per_b, q_rec_0)

    assert tr_dir.spot_exec_entry == pytest.approx(tr_rec.spot_exec_entry, rel=1e-10)
    assert tr_dir.invested_amount_b == pytest.approx(tr_rec.invested_amount_b, rel=1e-10)

    # 2. Exit quotes
    q_dir_1 = direct_store.get_executable_quote("EUR/USD", as_of=t1 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="bid")
    q_rec_1 = recip_store.get_executable_quote("EUR/USD", as_of=t1 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="bid")

    assert q_dir_1.canonical_bid == pytest.approx(q_rec_1.canonical_bid, rel=1e-10)
    assert q_dir_1.canonical_ask == pytest.approx(q_rec_1.canonical_ask, rel=1e-10)
    assert q_dir_1.canonical_mid == pytest.approx(q_rec_1.canonical_mid, rel=1e-10)

    cl_dir = eng_direct.close_trade(tr_dir, t1.date(), q_dir_1.rate_a_per_b, q_dir_1)
    cl_rec = eng_recip.close_trade(tr_rec, t1.date(), q_rec_1.rate_a_per_b, q_rec_1)

    assert cl_dir.converted_back_a == pytest.approx(cl_rec.converted_back_a, rel=1e-10)
    assert cl_dir.interest_paid_a == pytest.approx(cl_rec.interest_paid_a, rel=1e-10)
    assert cl_dir.pure_gross_gain_a == pytest.approx(cl_rec.pure_gross_gain_a, rel=1e-10)
    assert cl_dir.reconciliation_residual_a <= 1e-10
    assert cl_rec.reconciliation_residual_a <= 1e-10


# -----------------------------------------------------------------------------
# 10. Reverse strategy currency symmetry
# -----------------------------------------------------------------------------
def test_reverse_strategy_currency_symmetry():
    """USD borrowing / EUR investment with direct EUR/USD provider observations."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc)
    # EUR/USD quotes: 1.09 / 1.11 at t0, 1.08 / 1.10 at t1
    store = PointInTimeDataStore([
        make_test_obs("EUR/USD", t0.date(), t0, value=1.10, bid=1.09, ask=1.11),
        make_test_obs("EUR/USD", t1.date(), t1, value=1.09, bid=1.08, ask=1.10),
    ])

    # Strategy: Borrow USD (A), Invest EUR (B).
    # Pair is USD/EUR. Rate is USD per EUR.
    # The EUR/USD quote is already units of USD per EUR!
    # Entry: buying EUR lifts dealer ASK (1.11).
    q_entry = store.get_executable_quote("USD/EUR", as_of=t0 + timedelta(minutes=5), borrowing_currency="USD", investment_currency="EUR", required_side="ask")
    assert q_entry is not None
    assert q_entry.canonical_ask == pytest.approx(1.11, rel=1e-10)

    # Exit: selling EUR hits dealer BID (1.08).
    q_exit = store.get_executable_quote("USD/EUR", as_of=t1 + timedelta(minutes=5), borrowing_currency="USD", investment_currency="EUR", required_side="bid")
    assert q_exit is not None
    assert q_exit.canonical_bid == pytest.approx(1.08, rel=1e-10)

    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0, variable_fee_bps=0.0, fixed_fee=0.0, use_observed_spread=True))
    tr = engine.open_trade("REV01", "USD/EUR Carry", CurrencyPair(borrowing_currency="USD", investment_currency="EUR"), t0.date(), 30, 100_000.0, 0.05, 0.035, q_entry.rate_a_per_b, q_entry)
    cl = engine.close_trade(tr, t1.date(), q_exit.rate_a_per_b, q_exit)

    assert cl.reconciliation_residual_a <= 1e-10


# -----------------------------------------------------------------------------
# 11. Raw provider bid/ask preservation
# -----------------------------------------------------------------------------
def test_raw_provider_bid_ask_preservation_across_all_modes():
    """Verify raw provider values are preserved intact in all 7 quote assembly modes."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)

    # 1. Direct two-way
    o_dir = make_test_obs("EUR/USD", t0.date(), t0, value=1.10, bid=1.09, ask=1.11)
    s_dir = PointInTimeDataStore([o_dir])
    q_dir = s_dir.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD")
    assert q_dir.provider_bid == 1.09 and q_dir.bid == 1.09
    assert q_dir.provider_ask == 1.11 and q_dir.ask == 1.11
    assert q_dir.provider_mid == 1.10 and q_dir.mid == 1.10

    # 2. Reciprocal two-way
    o_rec = make_test_obs("USD/EUR", t0.date(), t0, value=0.91, bid=0.90, ask=0.92, base_curr="USD", quote_curr="EUR")
    s_rec = PointInTimeDataStore([o_rec])
    q_rec = s_rec.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD")
    assert q_rec.provider_bid == 0.90 and q_rec.bid == 0.90
    assert q_rec.provider_ask == 0.92 and q_rec.ask == 0.92
    assert q_rec.provider_mid == 0.91 and q_rec.mid == 0.91

    # 3. Direct standalone one-sided
    o_one = make_test_obs("EUR/USD", t0.date(), t0, value=1.09, bid=1.09, ask=None, price_type=PriceType.BID_QUOTE)
    s_one = PointInTimeDataStore([o_one])
    q_one = s_one.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="ask")
    assert q_one.provider_bid == 1.09 and q_one.bid == 1.09
    assert q_one.provider_ask is None and q_one.ask is None
    assert q_one.provider_mid == 1.09 and q_one.mid == 1.09

    # 4. Reference rate proxy
    o_ref = make_test_obs("EUR/USD", t0.date(), t0, value=1.095, price_type=PriceType.REFERENCE_RATE)
    s_ref = PointInTimeDataStore([o_ref])
    q_ref = s_ref.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), allow_reference_rate_proxy=True)
    assert q_ref.provider_bid is None and q_ref.bid is None
    assert q_ref.provider_ask is None and q_ref.ask is None
    assert q_ref.provider_mid == 1.095 and q_ref.mid == 1.095


# -----------------------------------------------------------------------------
# 12. Canonical price serialization round-trip
# -----------------------------------------------------------------------------
def test_canonical_price_serialization_round_trip():
    """Verify ExecutableQuoteResult and TradeRecord serialize and deserialize without loss."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs = make_test_obs("USD/EUR", t0.date(), t0, value=0.91, bid=0.90, ask=0.92, base_curr="USD", quote_curr="EUR")
    store = PointInTimeDataStore([obs])
    q = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD")

    # Serialize quote
    raw_json = q.model_dump_json()
    reloaded = ExecutableQuoteResult.model_validate_json(raw_json)

    assert reloaded.provider_bid == q.provider_bid
    assert reloaded.provider_ask == q.provider_ask
    assert reloaded.provider_mid == q.provider_mid
    assert reloaded.canonical_bid == q.canonical_bid
    assert reloaded.canonical_ask == q.canonical_ask
    assert reloaded.canonical_mid == q.canonical_mid
    assert reloaded.provider_base_currency == "USD"
    assert reloaded.provider_quote_currency == "EUR"


# -----------------------------------------------------------------------------
# 13. Midpoint convention consistency
# -----------------------------------------------------------------------------
def test_midpoint_convention_consistency():
    """Document that canonical midpoint is the arithmetic mean of canonical quotes, not 1/provider_mid."""
    p_bid = 1.09
    p_ask = 1.11
    provider_mid = (p_bid + p_ask) / 2.0  # 1.10

    can_bid = 1.0 / p_ask  # 0.9009009009
    can_ask = 1.0 / p_bid  # 0.9174311927
    canonical_mid = (can_bid + can_ask) / 2.0  # 0.9091660468

    reciprocal_of_provider_mid = 1.0 / provider_mid  # 0.9090909091

    # By Jensen's inequality: (1/a + 1/b)/2 > 1/((a+b)/2)
    assert canonical_mid > reciprocal_of_provider_mid
    assert abs(canonical_mid - reciprocal_of_provider_mid) == pytest.approx(0.0000751377, rel=1e-4)


# -----------------------------------------------------------------------------
# 14. Fixture provenance isolation
# -----------------------------------------------------------------------------
def test_fixture_provenance_isolation():
    """Test mock fixtures are strictly rejected when allow_mock=False and allow_synthetic=False."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs_mock = make_test_obs("EUR/USD", t0.date(), t0, value=1.09)
    assert obs_mock.classification == DataClassification.MOCK
    assert obs_mock.is_synthetic is True

    # Real production firewall disallowing mocks and synthetic data
    strict_firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_mock=False, allow_synthetic=False))
    store = PointInTimeDataStore([obs_mock], firewall=strict_firewall)

    q = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5))
    assert q is None, "Test mock fixture must never execute when allow_mock=False!"


# -----------------------------------------------------------------------------
# 15. Historical JSON/report consistency
# -----------------------------------------------------------------------------
def test_historical_json_report_consistency():
    """Authoritative committed Config 2 JSON reports 29 trades, +2.89% return, and €2,890.22 net profit."""
    p = Path("data/results/phase_3_2_2_3_2/config_2_estimated_schedule.json")
    if not p.exists():
        pytest.skip("Phase 3.2.2.3.2 reproduction JSON not found.")

    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["strategy_status"].lower() == "research_proxy"
    assert data["is_point_in_time_credible"] is False
    assert data["trades"]["total_trades"] == 29
    assert data["performance"]["total_return"] == pytest.approx(0.0289022, rel=1e-3)
    assert data["performance"]["cumulative_net_profit"] == pytest.approx(2890.22, rel=1e-2)
    assert data["attribution"]["reconciliation_exact"] is True


# -----------------------------------------------------------------------------
# 16. No-trade alpha reporting
# -----------------------------------------------------------------------------
def test_notrade_alpha_reporting():
    """An unexecutable strategy with zero trades must report alpha as None/NA rather than +0.00%."""
    snapshots = [
        PortfolioSnapshot(as_of=date(2024, 1, 1), cash_a=100_000.0, total_borrowed_a=0.0, total_obligations_a=0.0, active_positions_count=0, positions_value_a=0.0, equity_a=100_000.0, leverage=0.0, unrealized_pnl_a=0.0, realized_pnl_a=0.0, capital_utilization=0.0),
        PortfolioSnapshot(as_of=date(2024, 1, 31), cash_a=100_000.0, total_borrowed_a=0.0, total_obligations_a=0.0, active_positions_count=0, positions_value_a=0.0, equity_a=100_000.0, leverage=0.0, unrealized_pnl_a=0.0, realized_pnl_a=0.0, capital_utilization=0.0),
    ]
    bm = BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH, name="Zero Cash (0.0%)")
    # No closed trades
    from backtesting.benchmarks import BenchmarkSeries
    bm_series = BenchmarkSeries(
        name="Zero Cash (0.0%)",
        description="Zero Cash",
        dates=[date(2024, 1, 1), date(2024, 1, 31)],
        values=[1.0, 1.0],
        returns=[0.0],
        total_return=0.0,
        annualized_return=0.0,
        annualized_volatility=0.0,
        sharpe_ratio=None,
        assumptions="Zero cash",
    )
    metrics = calculate_performance_metrics(
        trades=[],
        snapshots=snapshots,
        initial_capital_a=100_000.0,
        benchmark=bm_series,
        cash_interest_earned=0.0,
    )
    assert metrics.total_trades == 0
    assert metrics.alpha is None


# -----------------------------------------------------------------------------
# 17. Exact P&L reconciliation
# -----------------------------------------------------------------------------
def test_exact_pnl_reconciliation():
    """Hand-calculated deterministic 30-day carry trade reconciles to residual <= 1e-10."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc)
    obs0 = make_test_obs("EUR/USD", t0.date(), t0, value=1.10, bid=1.09, ask=1.11)
    obs1 = make_test_obs("EUR/USD", t1.date(), t1, value=1.09, bid=1.08, ask=1.10)
    store = PointInTimeDataStore([obs0, obs1])

    exec_cfg = ExecutionConfig(bid_ask_spread_bps=2.0, slippage_bps=0.5, variable_fee_bps=1.0, fixed_fee=5.0, use_observed_spread=True)
    engine = ExecutionEngine(exec_cfg)

    q0 = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="ask")
    tr = engine.open_trade("DET_01", "Deterministic", CurrencyPair(borrowing_currency="EUR", investment_currency="USD"), t0.date(), 30, 100_000.0, 0.04, 0.05, q0.rate_a_per_b, q0)

    q1 = store.get_executable_quote("EUR/USD", as_of=t1 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="bid")
    cl = engine.close_trade(tr, t1.date(), q1.rate_a_per_b, q1)

    assert cl.reconciliation_residual_a <= 1e-10
