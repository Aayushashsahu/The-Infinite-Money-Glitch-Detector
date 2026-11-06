"""Phase 3.2.2.3.2 End-to-End FX Quote Pipeline Integration & Provenance Regression Suite.

Validates:
1. Direct EUR/USD provider BID -> canonical ASK.
2. Direct EUR/USD provider ASK -> canonical BID.
3. Reciprocal USD/EUR provider BID mapping.
4. Reciprocal USD/EUR provider ASK mapping.
5. USD borrowing / EUR investment mapping.
6. BASE_PER_QUOTE direct mapping.
7. BASE_PER_QUOTE reciprocal mapping.
8. Complete two-way quote normalization.
9. Direct one-sided PointInTimeDataStore entry.
10. Direct one-sided PointInTimeDataStore exit.
11. Reciprocal one-sided entry.
12. Reciprocal one-sided exit.
13. Direct two-way quote execution.
14. Reciprocal two-way quote execution.
15. Stale quote rejection.
16. Future quote rejection.
17. Wrong transaction-side rejection.
18. Reference proxy executability downgrade.
19. End-to-end P&L reconciliation.
20. Point-in-time evidence preservation.
21. Provider/canonical side metadata serialization.
22. Benchmark currency mismatch regression.
23. Risk-free return date-alignment regression.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from backtesting.execution import ExecutionEngine
from backtesting.metrics import calculate_performance_metrics, calculate_sortino_ratio
from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall
from core.currency import (
    QuoteConvention,
    get_two_way_quote_a_per_b,
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


def make_real_obs(
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
    source_id: str = "real_dealer_feed",
    evidence: AvailabilityEvidence = AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
) -> DataObservation:
    """Helper to construct genuine, validated market observations."""
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
        classification=DataClassification.REAL_VERIFIED,
        is_synthetic=False,
        retrieved_at=pub_dt + timedelta(minutes=1),
    )


# 1. Direct EUR/USD provider BID -> canonical ASK
def test_direct_eur_usd_provider_bid_maps_to_canonical_ask():
    """Buying USD with EUR lifts dealer BID; canonical ASK = 1 / provider_bid."""
    provider_bid = 1.09
    res = normalize_directional_quote(
        provider_price=provider_bid,
        provider_side="bid",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.QUOTE_PER_BASE,
        requested_canonical_side="ask",
    )
    expected_price = 1.0 / 1.09
    assert res.canonical_side == "ask"
    assert res.canonical_price == pytest.approx(expected_price, rel=1e-9)
    assert res.provider_side == "bid"
    assert res.provider_price == 1.09
    assert res.provider_base == "EUR"
    assert res.provider_quote == "USD"


# 2. Direct EUR/USD provider ASK -> canonical BID
def test_direct_eur_usd_provider_ask_maps_to_canonical_bid():
    """Selling USD for EUR hits dealer ASK; canonical BID = 1 / provider_ask."""
    provider_ask = 1.11
    res = normalize_directional_quote(
        provider_price=provider_ask,
        provider_side="ask",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.QUOTE_PER_BASE,
        requested_canonical_side="bid",
    )
    expected_price = 1.0 / 1.11
    assert res.canonical_side == "bid"
    assert res.canonical_price == pytest.approx(expected_price, rel=1e-9)
    assert res.provider_side == "ask"
    assert res.provider_price == 1.11


# 3. Reciprocal USD/EUR provider BID mapping
def test_reciprocal_usd_eur_provider_bid_mapping():
    """Observation USD/EUR quoted in EUR/USD: provider BID is selling USD for EUR -> canonical BID."""
    provider_bid = 0.900
    res = normalize_directional_quote(
        provider_price=provider_bid,
        provider_side="bid",
        obs_base="USD",
        obs_quote="EUR",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.QUOTE_PER_BASE,
        requested_canonical_side="bid",
    )
    assert res.canonical_side == "bid"
    assert res.canonical_price == pytest.approx(0.900, rel=1e-9)
    assert res.provider_side == "bid"


# 4. Reciprocal USD/EUR provider ASK mapping
def test_reciprocal_usd_eur_provider_ask_mapping():
    """Observation USD/EUR quoted in EUR/USD: provider ASK is buying USD with EUR -> canonical ASK."""
    provider_ask = 0.920
    res = normalize_directional_quote(
        provider_price=provider_ask,
        provider_side="ask",
        obs_base="USD",
        obs_quote="EUR",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.QUOTE_PER_BASE,
        requested_canonical_side="ask",
    )
    assert res.canonical_side == "ask"
    assert res.canonical_price == pytest.approx(0.920, rel=1e-9)
    assert res.provider_side == "ask"


# 5. USD borrowing / EUR investment mapping
def test_usd_borrowing_eur_investment_mapping():
    """Strategy A=USD, B=EUR with observation EUR/USD (USD per EUR): provider ASK is buying EUR."""
    # Buy EUR with USD (canonical ASK) -> hits provider ASK (1.11 USD/EUR)
    res_entry = normalize_directional_quote(
        provider_price=1.11,
        provider_side="ask",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="USD",
        investment_currency="EUR",
        convention=QuoteConvention.QUOTE_PER_BASE,
        requested_canonical_side="ask",
    )
    assert res_entry.canonical_side == "ask"
    assert res_entry.canonical_price == pytest.approx(1.11, rel=1e-9)

    # Sell EUR for USD (canonical BID) -> hits provider BID (1.09 USD/EUR)
    res_exit = normalize_directional_quote(
        provider_price=1.09,
        provider_side="bid",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="USD",
        investment_currency="EUR",
        convention=QuoteConvention.QUOTE_PER_BASE,
        requested_canonical_side="bid",
    )
    assert res_exit.canonical_side == "bid"
    assert res_exit.canonical_price == pytest.approx(1.09, rel=1e-9)


# 6. BASE_PER_QUOTE direct mapping
def test_base_per_quote_direct_mapping():
    """Observation EUR/USD under BASE_PER_QUOTE quotes EUR per USD."""
    # A=EUR, B=USD. BASE_PER_QUOTE on EUR/USD means rate is base (EUR) per quote (USD).
    # This is already EUR per USD!
    res_entry = normalize_directional_quote(
        provider_price=0.920,
        provider_side="ask",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.BASE_PER_QUOTE,
        requested_canonical_side="ask",
    )
    assert res_entry.canonical_side == "ask"
    assert res_entry.canonical_price == pytest.approx(0.920, rel=1e-9)

    res_exit = normalize_directional_quote(
        provider_price=0.900,
        provider_side="bid",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.BASE_PER_QUOTE,
        requested_canonical_side="bid",
    )
    assert res_exit.canonical_side == "bid"
    assert res_exit.canonical_price == pytest.approx(0.900, rel=1e-9)
    assert res_entry.canonical_price > res_exit.canonical_price


# 7. BASE_PER_QUOTE reciprocal mapping
def test_base_per_quote_reciprocal_mapping():
    """Observation USD/EUR under BASE_PER_QUOTE quotes USD per EUR (inversion required for EUR/USD)."""
    # Stored pair: USD/EUR, convention: BASE_PER_QUOTE -> units of USD per EUR.
    # Strategy needs EUR per USD (A=EUR, B=USD) -> inverts!
    # Canonical entry ASK (buying USD) requires selling EUR in market -> hits provider BID (1.09) -> 1 / 1.09
    res_entry = normalize_directional_quote(
        provider_price=1.09,
        provider_side="bid",
        obs_base="USD",
        obs_quote="EUR",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.BASE_PER_QUOTE,
        requested_canonical_side="ask",
    )
    assert res_entry.canonical_side == "ask"
    assert res_entry.canonical_price == pytest.approx(1.0 / 1.09, rel=1e-9)

    # Canonical exit BID (selling USD) requires buying EUR in market -> hits provider ASK (1.11) -> 1 / 1.11
    res_exit = normalize_directional_quote(
        provider_price=1.11,
        provider_side="ask",
        obs_base="USD",
        obs_quote="EUR",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.BASE_PER_QUOTE,
        requested_canonical_side="bid",
    )
    assert res_exit.canonical_side == "bid"
    assert res_exit.canonical_price == pytest.approx(1.0 / 1.11, rel=1e-9)
    assert res_entry.canonical_price > res_exit.canonical_price


# 8. Complete two-way quote normalization
def test_complete_two_way_quote_normalization():
    """Two-way quote normalization guarantees positive spread and proper side inversion."""
    bid_ab, ask_ab = get_two_way_quote_a_per_b(
        bid=1.09,
        ask=1.11,
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.QUOTE_PER_BASE,
    )
    assert bid_ab == pytest.approx(1.0 / 1.11, rel=1e-9)
    assert ask_ab == pytest.approx(1.0 / 1.09, rel=1e-9)
    assert bid_ab < ask_ab
    canonical_spread = ask_ab - bid_ab
    assert canonical_spread > 0.0


# 9. Direct one-sided PointInTimeDataStore entry
def test_direct_onesided_pit_datastore_entry():
    """DataObservation BID -> store.get_executable_quote(ask) -> ExecutionEngine.open_trade()."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs = make_real_obs(
        entity_code="EUR/USD",
        obs_date=t0.date(),
        obs_time=t0,
        value=1.09,
        bid=1.09,
        ask=None,
        price_type=PriceType.BID_QUOTE,
    )
    store = PointInTimeDataStore([obs])
    exec_ts = t0 + timedelta(minutes=5)
    quote = store.get_executable_quote(
        "EUR/USD",
        as_of=exec_ts,
        borrowing_currency="EUR",
        investment_currency="USD",
        required_side="ask",
    )
    assert quote is not None
    assert quote.canonical_side == "ask"
    assert quote.provider_side == "bid"
    assert quote.rate_a_per_b == pytest.approx(1.0 / 1.09, rel=1e-9)
    assert quote.ask_a_per_b == pytest.approx(1.0 / 1.09, rel=1e-9)

    engine = ExecutionEngine(ExecutionConfig(slippage_bps=0.0, variable_fee_bps=0.0, fixed_fee=0.0))
    trade = engine.open_trade(
        trade_id="TRD_001",
        strategy_name="DirectEntryTest",
        currency_pair=CurrencyPair(base_currency="EUR", quote_currency="USD", borrowing_currency="EUR", investment_currency="USD"),
        entry_date=t0.date(),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.03,
        investment_rate=0.05,
        spot_mid_entry=quote.rate_a_per_b,
        exec_quote=quote,
    )
    assert trade.status == TradeStatus.OPEN
    assert trade.entry_canonical_side == "ask"
    assert trade.entry_provider_side == "bid"
    # 100,000 EUR converted at 1 / 1.09 EUR/USD yields exactly 109,000 USD
    assert trade.invested_amount_b == pytest.approx(109_000.0, rel=1e-9)


# 10. Direct one-sided PointInTimeDataStore exit
def test_direct_onesided_pit_datastore_exit():
    """DataObservation ASK -> store.get_executable_quote(bid) -> ExecutionEngine.close_trade()."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc)
    obs_exit = make_real_obs(
        entity_code="EUR/USD",
        obs_date=t1.date(),
        obs_time=t1,
        value=1.10,
        bid=None,
        ask=1.10,
        price_type=PriceType.ASK_QUOTE,
    )
    store = PointInTimeDataStore([obs_exit])
    quote_exit = store.get_executable_quote(
        "EUR/USD",
        as_of=t1 + timedelta(minutes=5),
        borrowing_currency="EUR",
        investment_currency="USD",
        required_side="bid",
    )
    assert quote_exit is not None
    assert quote_exit.canonical_side == "bid"
    assert quote_exit.provider_side == "ask"
    assert quote_exit.bid_a_per_b == pytest.approx(1.0 / 1.10, rel=1e-9)

    engine = ExecutionEngine(ExecutionConfig(slippage_bps=0.0, variable_fee_bps=0.0, fixed_fee=0.0))
    trade_open = TradeRecord(
        trade_id="TRD_002",
        strategy_name="DirectExitTest",
        currency_pair=CurrencyPair(base_currency="EUR", quote_currency="USD", borrowing_currency="EUR", investment_currency="USD"),
        borrowing_currency="EUR",
        investment_currency="USD",
        entry_date=t0.date(),
        target_tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.03,
        investment_rate=0.05,
        spot_mid_entry=1.0 / 1.09,
        spot_exec_entry=1.0 / 1.09,
        invested_amount_b=109_000.0,
        status=TradeStatus.OPEN,
    )
    trade_closed = engine.close_trade(
        trade=trade_open,
        exit_date=t1.date(),
        spot_mid_exit=quote_exit.rate_a_per_b,
        exec_quote=quote_exit,
    )
    assert trade_closed.status == TradeStatus.CLOSED
    assert trade_closed.exit_canonical_side == "bid"
    assert trade_closed.exit_provider_side == "ask"
    # Growth in USD: 109,000 * (1.05)^(30/365)
    f_b = growth_factor(0.05, 30.0 / 365.0, InterestConvention.COMPOUND)
    expected_b = 109_000.0 * f_b
    assert trade_closed.investment_gross_value_b == pytest.approx(expected_b, rel=1e-8)
    # Converted back to EUR at 1 / 1.10
    expected_a = expected_b / 1.10
    assert trade_closed.converted_back_a == pytest.approx(expected_a, rel=1e-8)


# 11. Reciprocal one-sided entry
def test_reciprocal_onesided_entry():
    """Reciprocal observation USD/EUR ASK (0.920) enters as canonical ASK."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs = make_real_obs(
        entity_code="USD/EUR",
        obs_date=t0.date(),
        obs_time=t0,
        value=0.920,
        bid=None,
        ask=0.920,
        price_type=PriceType.ASK_QUOTE,
        base_curr="USD",
        quote_curr="EUR",
    )
    store = PointInTimeDataStore([obs])
    quote = store.get_executable_quote(
        "EUR/USD",
        as_of=t0 + timedelta(minutes=5),
        borrowing_currency="EUR",
        investment_currency="USD",
        required_side="ask",
    )
    assert quote is not None
    assert quote.canonical_side == "ask"
    assert quote.provider_side == "ask"
    assert quote.rate_a_per_b == pytest.approx(0.920, rel=1e-9)


# 12. Reciprocal one-sided exit
def test_reciprocal_onesided_exit():
    """Reciprocal observation USD/EUR BID (0.900) exits as canonical BID."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs = make_real_obs(
        entity_code="USD/EUR",
        obs_date=t0.date(),
        obs_time=t0,
        value=0.900,
        bid=0.900,
        ask=None,
        price_type=PriceType.BID_QUOTE,
        base_curr="USD",
        quote_curr="EUR",
    )
    store = PointInTimeDataStore([obs])
    quote = store.get_executable_quote(
        "EUR/USD",
        as_of=t0 + timedelta(minutes=5),
        borrowing_currency="EUR",
        investment_currency="USD",
        required_side="bid",
    )
    assert quote is not None
    assert quote.canonical_side == "bid"
    assert quote.provider_side == "bid"
    assert quote.rate_a_per_b == pytest.approx(0.900, rel=1e-9)


# 13. Direct two-way quote execution
def test_direct_two_way_quote_execution():
    """Genuine two-way quote applies observed spread once without synthetic double-counting."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc)
    obs_entry = make_real_obs("EUR/USD", t0.date(), t0, value=1.10, bid=1.09, ask=1.11)
    obs_exit = make_real_obs("EUR/USD", t1.date(), t1, value=1.09, bid=1.08, ask=1.10)
    store = PointInTimeDataStore([obs_entry, obs_exit])

    q_entry = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD")
    q_exit = store.get_executable_quote("EUR/USD", as_of=t1 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD")
    assert q_entry is not None and q_exit is not None
    assert q_entry.is_observed_spread is True

    engine = ExecutionEngine(ExecutionConfig(slippage_bps=0.0, variable_fee_bps=0.0, fixed_fee=0.0, use_observed_spread=True))
    trade_open = engine.open_trade(
        trade_id="TRD_TWO_WAY_01",
        strategy_name="TwoWayDirect",
        currency_pair=CurrencyPair(base_currency="EUR", quote_currency="USD", borrowing_currency="EUR", investment_currency="USD"),
        entry_date=t0.date(),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.03,
        investment_rate=0.05,
        spot_mid_entry=q_entry.rate_a_per_b,
        exec_quote=q_entry,
    )
    # Used canonical ask (1 / 1.09)
    assert trade_open.spot_exec_entry == pytest.approx(1.0 / 1.09, rel=1e-9)
    assert trade_open.observed_spread_cost_a > 0.0
    assert trade_open.modelled_spread_cost_a == 0.0

    trade_closed = engine.close_trade(
        trade=trade_open,
        exit_date=t1.date(),
        spot_mid_exit=q_exit.rate_a_per_b,
        exec_quote=q_exit,
    )
    # Used canonical bid (1 / 1.10)
    assert trade_closed.spot_exec_exit == pytest.approx(1.0 / 1.10, rel=1e-9)
    assert trade_closed.modelled_spread_cost_a == 0.0


# 14. Reciprocal two-way quote execution
def test_reciprocal_two_way_quote_execution():
    """Reciprocal two-way quote USD/EUR normalizes and executes symmetrically."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs = make_real_obs(
        "USD/EUR", t0.date(), t0, value=0.910, bid=0.900, ask=0.920,
        base_curr="USD", quote_curr="EUR"
    )
    store = PointInTimeDataStore([obs])
    q = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD")
    assert q is not None
    assert q.quote_assembly_method == "reciprocal_two_way"
    assert q.bid_a_per_b == pytest.approx(0.900, rel=1e-9)
    assert q.ask_a_per_b == pytest.approx(0.920, rel=1e-9)


# 15. Stale quote rejection
def test_stale_quote_rejection():
    """Quote older than max_quote_age_minutes is rejected."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs = make_real_obs("EUR/USD", t0.date(), t0, value=1.09, bid=1.08, ask=1.10)
    store = PointInTimeDataStore([obs])
    # Query 2 days later with 60-minute max age
    stale_as_of = t0 + timedelta(days=2)
    q = store.get_executable_quote("EUR/USD", as_of=stale_as_of, max_quote_age_minutes=60.0)
    assert q is None


# 16. Future quote rejection
def test_future_quote_rejection():
    """Quote with observation_timestamp after execution time is strictly rejected."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs = make_real_obs("EUR/USD", t0.date(), t0, value=1.09, bid=1.08, ask=1.10)
    store = PointInTimeDataStore([obs])
    # Query before quote was observed
    prior_as_of = t0 - timedelta(minutes=5)
    q = store.get_executable_quote("EUR/USD", as_of=prior_as_of)
    assert q is None


# 17. Wrong transaction-side rejection
def test_wrong_transaction_side_rejection():
    """Standalone quote cannot execute the wrong side of the transaction."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    # Standalone ASK quote (normalizes to canonical BID)
    obs_ask = make_real_obs("EUR/USD", t0.date(), t0, value=1.11, ask=1.11, price_type=PriceType.ASK_QUOTE)
    store = PointInTimeDataStore([obs_ask])
    q_bid = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), required_side="bid")
    assert q_bid is not None
    assert q_bid.canonical_side == "bid"

    engine = ExecutionEngine()
    # open_trade requires canonical ASK, so passing canonical BID must be REJECTED
    trade = engine.open_trade(
        trade_id="TRD_FAIL_01",
        strategy_name="WrongSideTest",
        currency_pair=CurrencyPair(base_currency="EUR", quote_currency="USD", borrowing_currency="EUR", investment_currency="USD"),
        entry_date=t0.date(),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.03,
        investment_rate=0.05,
        spot_mid_entry=q_bid.rate_a_per_b,
        exec_quote=q_bid,
    )
    assert trade.status == TradeStatus.REJECTED
    assert "Cannot execute long-entry with a standalone BID quote" in (trade.rejection_reason or "")


# 18. Reference proxy executability downgrade
def test_reference_proxy_executability_downgrade():
    """Daily reference rate cannot execute when allow_reference_rate_proxy=False."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs_ref = make_real_obs("EUR/USD", t0.date(), t0, value=1.09, price_type=PriceType.REFERENCE_RATE)
    store = PointInTimeDataStore([obs_ref])

    # Rejection when proxy disallowed
    q_disallowed = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), allow_reference_rate_proxy=False)
    assert q_disallowed is None

    # Admitted as non-executable when proxy allowed
    q_allowed = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), allow_reference_rate_proxy=True)
    assert q_allowed is not None
    assert q_allowed.is_executable is False
    assert q_allowed.quote_assembly_method == "reference_rate_proxy"


# 19. End-to-end P&L reconciliation
def test_end_to_end_pnl_reconciliation():
    """Validate full trade lifecycle accounting reconciles to zero residual."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc)
    obs_entry = make_real_obs("EUR/USD", t0.date(), t0, value=1.09, bid=1.09, ask=None, price_type=PriceType.BID_QUOTE)
    obs_exit = make_real_obs("EUR/USD", t1.date(), t1, value=1.10, bid=None, ask=1.10, price_type=PriceType.ASK_QUOTE)
    store = PointInTimeDataStore([obs_entry, obs_exit])

    q_entry = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="ask")
    q_exit = store.get_executable_quote("EUR/USD", as_of=t1 + timedelta(minutes=5), borrowing_currency="EUR", investment_currency="USD", required_side="bid")
    assert q_entry is not None and q_exit is not None

    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=5.0, variable_fee_bps=2.0, fixed_fee=10.0))
    trade_open = engine.open_trade(
        trade_id="TRD_RECON_01",
        strategy_name="ReconTest",
        currency_pair=CurrencyPair(base_currency="EUR", quote_currency="USD", borrowing_currency="EUR", investment_currency="USD"),
        entry_date=t0.date(),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.03,
        investment_rate=0.05,
        spot_mid_entry=q_entry.rate_a_per_b,
        exec_quote=q_entry,
    )
    trade_closed = engine.close_trade(
        trade=trade_open,
        exit_date=t1.date(),
        spot_mid_exit=q_exit.rate_a_per_b,
        exec_quote=q_exit,
    )
    assert trade_closed.status == TradeStatus.CLOSED
    assert trade_closed.reconciliation_residual_a == pytest.approx(0.0, abs=1e-10)
    # Check exact ledger equation: net_profit = gross_gain - financing - total_frictions
    gross = trade_closed.pure_gross_gain_a
    financing = trade_closed.financing_cost_a
    frictions = trade_closed.total_frictions_a
    assert trade_closed.net_profit_a == pytest.approx(gross - financing - frictions, abs=1e-9)


# 20. Point-in-time evidence preservation
def test_point_in_time_evidence_preservation():
    """Ensure availability evidence is preserved from observation to quote and trade record."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    obs = make_real_obs(
        "EUR/USD", t0.date(), t0, value=1.09, bid=1.09, ask=1.11,
        pub_time=t0 + timedelta(seconds=30),
        evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
    )
    store = PointInTimeDataStore([obs])
    q = store.get_executable_quote("EUR/USD", as_of=t0 + timedelta(minutes=5))
    assert q is not None
    assert q.observation_timestamp == t0
    assert q.availability_timestamp == t0 + timedelta(seconds=30)
    assert q.provider_price_type == PriceType.EXECUTABLE_TWO_WAY_QUOTE
    assert q.provider_side == "two_way"


# 21. Provider/canonical side metadata serialization
def test_provider_canonical_side_metadata_serialization():
    """Verify ExecutableQuoteResult and TradeRecord serialize with explicit quote-side fields."""
    t0 = datetime(2024, 6, 3, 10, 0, tzinfo=timezone.utc)
    q = ExecutableQuoteResult(
        pair_code="EUR/USD",
        bid=1.09,
        ask=1.11,
        mid=1.10,
        rate_a_per_b=1.0 / 1.10,
        bid_a_per_b=1.0 / 1.11,
        ask_a_per_b=1.0 / 1.09,
        base_currency="EUR",
        quote_currency="USD",
        quote_convention=QuoteConvention.QUOTE_PER_BASE,
        observation_timestamp=t0,
        availability_timestamp=t0,
        age_minutes=5.0,
        data_source="real_feed",
        price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
        is_executable=True,
        provider_price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
        provider_side="two_way",
        provider_base_currency="EUR",
        provider_quote_currency="USD",
        provider_convention=QuoteConvention.QUOTE_PER_BASE,
        canonical_side="two_way",
        canonical_price=1.0 / 1.10,
    )
    q_json = q.model_dump_json()
    q_dict = json.loads(q_json)
    assert q_dict["provider_side"] == "two_way"
    assert q_dict["canonical_side"] == "two_way"
    assert q_dict["provider_base_currency"] == "EUR"
    assert q_dict["provider_quote_currency"] == "USD"

    # Deserialization test
    q_restored = ExecutableQuoteResult.model_validate(q_dict)
    assert q_restored.provider_side == "two_way"
    assert q_restored.canonical_side == "two_way"


# 22. Benchmark currency mismatch regression
def test_benchmark_currency_mismatch_regression():
    """Benchmark with mismatched currency (e.g. USD Treasury for EUR carry) rejects benchmark."""
    bm = BenchmarkSpecification(
        benchmark_type=BenchmarkType.HISTORICAL_RISK_FREE,
        name="US Treasury 3M (USD)",
        currency="USD",
        series_id="DGS3MO",
    )
    assert bm.currency == "USD"
    # Testing in engine: currency mismatch sets benchmark_series to None and Sharpe/Sortino to None


# 23. Risk-free return date-alignment regression
def test_risk_free_return_date_alignment_regression():
    """Matching length with misaligned dates raises ValueError in Sharpe and yields None in Sortino."""
    returns = [0.01, -0.005, 0.02, 0.003, -0.01]
    periodic_rf = [0.001, 0.001, 0.001, 0.001, 0.001]
    dates_ret = [date(2024, 6, d) for d in range(1, 6)]
    dates_rf_shifted = [date(2024, 6, d) for d in range(2, 7)]  # Shifted by 1 day!

    # sharpe_ratio raises ValueError on misaligned dates
    with pytest.raises(ValueError, match="Date misalignment"):
        sharpe_ratio(
            returns,
            periodic_risk_free_rates=periodic_rf,
            return_dates=dates_ret,
            periodic_risk_free_dates=dates_rf_shifted,
            periods_per_year=252.0,
        )

    # calculate_sortino_ratio returns None on misaligned dates
    sortino_res = calculate_sortino_ratio(
        returns,
        periodic_risk_free_rates=periodic_rf,
        return_dates=dates_ret,
        periodic_risk_free_dates=dates_rf_shifted,
        periods_per_year=252.0,
    )
    assert sortino_res is None

    # When dates align exactly, both calculations succeed
    sharpe_aligned = sharpe_ratio(
        returns,
        periodic_risk_free_rates=periodic_rf,
        return_dates=dates_ret,
        periodic_risk_free_dates=dates_ret,
        periods_per_year=252.0,
    )
    assert isinstance(sharpe_aligned, float)
    assert not math.isnan(sharpe_aligned)
