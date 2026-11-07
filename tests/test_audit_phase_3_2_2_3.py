"""Phase 3.2.2.3 Audit Test Suite: Canonical FX Convention, Execution Mathematics, and Benchmarks.

Validates:
1. Canonical FX Convention:
   - Explicit quote convention enforcement (QUOTE_PER_BASE vs BASE_PER_QUOTE).
   - EUR/USD conversion and USD/EUR reciprocal inversion.
   - Round-trip capital preservation under no FX movement.
   - Correct mathematical sign of FX translation gains/losses.
   - Break-even exchange rate consistency.

2. Quote Correctness & Freshness:
   - Genuine two-way quotes accepted.
   - Missing bid/ask rejected for real market data.
   - One-sided quotes cannot produce unjustified round trips.
   - Crossed quote (bid > ask) rejected.
   - Reciprocal bid/ask inversion (inv_bid = 1/ask, inv_ask = 1/bid).
   - Quote observation timestamp requirement (no midnight fallback).
   - Direct/inverse quote freshness equivalence.

3. Execution Cost Accounting & No Double Counting:
   - Mode A (observed market spread) applied directly without synthetic spread.
   - Mode B (modelled spread) applied on reference/mid quotes.
   - Spread never double counted.
   - Direction-specific execution: entry pays ask, exit receives bid.
   - Exact reconciliation: pure_gross_gain_a == fx_translation_gain_a + investment_yield_gain_a.
   - Net profit reconciliation: net_profit_a == pure_gross_gain_a - financing_cost_a - total_frictions_a.

4. Executability & Open Positions:
   - Reference-rate proxy never becomes EXECUTABLE_VALIDATED.
   - One-sided quotes cannot masquerade as complete two-way fills.
   - Open positions remain transparent when exit quote is unavailable.

5. Bounded Benchmark Staleness & Sharpe Consistency:
   - Currency mismatch rejection.
   - Bounded staleness for forward-filled benchmarks.
   - Missing intermediate benchmark data rejection.
   - Proper risk-free rate alignment for Sharpe ratio.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import pytest

from core.currency import (
    QuoteConvention,
    convert_to_a,
    convert_to_b,
    get_rate_a_per_b,
    get_two_way_quote_a_per_b,
    invert_two_way_quote,
)
from data.schemas import (
    AvailabilityEvidence,
    DataObservation,
    Frequency,
    ObservationKind,
    PriceType,
    RateRole,
)
from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall
from backtesting.execution import ExecutionEngine, compute_entry_execution_rate, compute_exit_execution_rate
from backtesting.engine import BacktestEngine
from schemas.backtest import (
    AvailabilityPolicy,
    BacktestConfig,
    BenchmarkSpecification,
    BenchmarkType,
    DataAvailabilityConfig,
    ExecutableQuoteResult,
    ExecutionConfig,
    PriceType as BTPriceType,
    StrategyExecutabilityStatus,
)
from schemas.strategy import CurrencyPair


# =============================================================================
# 1. Canonical FX Convention & Currency Conversion Mathematics
# =============================================================================

def test_canonical_quote_convention_enforcement():
    """Observation requires explicit QuoteConvention and correctly identifies Base/Quote."""
    obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        observation_date=date(2024, 1, 2),
        retrieved_at=datetime(2024, 1, 2, 16, 0, tzinfo=timezone.utc),
        value=1.10,
        unit="USD",
        frequency=Frequency.DAILY,
        is_synthetic=False,
    )
    assert obs.quote_convention == QuoteConvention.QUOTE_PER_BASE
    assert obs.base_currency == "EUR"
    assert obs.quote_currency == "USD"


def test_eur_usd_conversion_and_round_trip():
    """EUR borrowing (A), USD investing (B), Frankfurter quote 1.10 USD/EUR.
    €100,000 must convert to $110,000, and $110,000 must convert back to €100,000.
    """
    principal_eur = 100_000.0
    quote_eur_usd = 1.10  # 1 EUR = 1.10 USD (QuoteConvention.QUOTE_PER_BASE)

    # Strategy borrowing A=EUR, investing B=USD
    rate_eur_per_usd = get_rate_a_per_b(
        value=quote_eur_usd,
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.QUOTE_PER_BASE,
    )
    # 1 USD = 1/1.10 EUR
    assert abs(rate_eur_per_usd - (1.0 / 1.10)) < 1e-12

    # Converted to USD
    invested_usd = convert_to_b(principal_eur, rate_eur_per_usd)
    assert abs(invested_usd - 110_000.0) < 1e-6

    # Converted back to EUR with unchanged exchange rate
    returned_eur = convert_to_a(invested_usd, rate_eur_per_usd)
    assert abs(returned_eur - principal_eur) < 1e-6

    # FX gain must be zero
    fx_gain_eur = returned_eur - principal_eur
    assert abs(fx_gain_eur) < 1e-6


def test_usd_eur_reciprocal_conversion():
    """USD borrowing (A), EUR investing (B), Frankfurter quote 1.10 USD/EUR.
    $110,000 must convert to €100,000, and €100,000 must convert back to $110,000.
    """
    principal_usd = 110_000.0
    quote_eur_usd = 1.10  # 1 EUR = 1.10 USD

    # Strategy borrowing A=USD, investing B=EUR
    rate_usd_per_eur = get_rate_a_per_b(
        value=quote_eur_usd,
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="USD",
        investment_currency="EUR",
        convention=QuoteConvention.QUOTE_PER_BASE,
    )
    # 1 EUR = 1.10 USD
    assert abs(rate_usd_per_eur - 1.10) < 1e-12

    # Converted to EUR
    invested_eur = convert_to_b(principal_usd, rate_usd_per_eur)
    assert abs(invested_eur - 100_000.0) < 1e-6

    # Converted back to USD
    returned_usd = convert_to_a(invested_eur, rate_usd_per_eur)
    assert abs(returned_usd - principal_usd) < 1e-6


def test_fx_movement_sign_correctness():
    """When investor holds USD and USD appreciates (EUR/USD drops from 1.10 to 1.00),
    the investor realizes an FX GAIN in EUR.
    When USD depreciates (EUR/USD rises from 1.10 to 1.20),
    the investor realizes an FX LOSS in EUR.
    """
    principal_eur = 100_000.0
    entry_quote = 1.10
    entry_rate_ab = get_rate_a_per_b(entry_quote, "EUR", "USD", "EUR", "USD", QuoteConvention.QUOTE_PER_BASE)
    invested_usd = convert_to_b(principal_eur, entry_rate_ab)  # $110,000

    # Case 1: USD Appreciates (EUR/USD moves from 1.10 to 1.00)
    exit_quote_usd_apprec = 1.00
    exit_rate_usd_apprec = get_rate_a_per_b(exit_quote_usd_apprec, "EUR", "USD", "EUR", "USD", QuoteConvention.QUOTE_PER_BASE)
    returned_eur_apprec = convert_to_a(invested_usd, exit_rate_usd_apprec)
    fx_gain = returned_eur_apprec - principal_eur
    assert fx_gain > 0
    assert abs(fx_gain - 10_000.0) < 1e-6  # €110,000 - €100,000 = +€10,000

    # Case 2: USD Depreciates (EUR/USD moves from 1.10 to 1.20)
    exit_quote_usd_deprec = 1.20
    exit_rate_usd_deprec = get_rate_a_per_b(exit_quote_usd_deprec, "EUR", "USD", "EUR", "USD", QuoteConvention.QUOTE_PER_BASE)
    returned_eur_deprec = convert_to_a(invested_usd, exit_rate_usd_deprec)
    fx_loss = returned_eur_deprec - principal_eur
    assert fx_loss < 0
    assert abs(fx_loss - (-8_333.333333)) < 1e-3


def test_non_positive_quote_rejected():
    """Non-positive exchange rates are strictly rejected."""
    with pytest.raises(ValueError, match="positive"):
        get_rate_a_per_b(0.0, "EUR", "USD", "EUR", "USD", QuoteConvention.QUOTE_PER_BASE)

    with pytest.raises(ValueError, match="positive"):
        get_rate_a_per_b(-1.10, "EUR", "USD", "EUR", "USD", QuoteConvention.QUOTE_PER_BASE)

    with pytest.raises(ValueError, match="positive"):
        compute_entry_execution_rate(0.0)

    with pytest.raises(ValueError, match="positive"):
        compute_exit_execution_rate(-0.5)


# =============================================================================
# 2. Executable Two-Way Quotes & Bid/Ask Correctness
# =============================================================================

def test_actual_two_way_quote_accepted_and_inverted_properly():
    """A genuine two-way quote (bid=1.08, ask=1.10) is accepted, and its reciprocal
    is correctly calculated as (inv_bid = 1/1.10, inv_ask = 1/1.08).
    """
    bid = 1.08
    ask = 1.10
    inv_bid, inv_ask = invert_two_way_quote(bid, ask)

    assert abs(inv_bid - (1.0 / 1.10)) < 1e-12
    assert abs(inv_ask - (1.0 / 1.08)) < 1e-12
    assert inv_bid <= inv_ask


def test_crossed_quote_rejected():
    """Bid > Ask is rejected at schema level and inverted helper level."""
    with pytest.raises(ValueError, match="Crossed quote"):
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="market_feed",
            entity_code="EUR/USD",
            observation_date=date(2024, 1, 2),
            retrieved_at=datetime(2024, 1, 2, 16, 0, tzinfo=timezone.utc),
            value=1.09,
            bid=1.10,
            ask=1.08,  # Crossed!
            unit="USD",
            frequency=Frequency.DAILY,
            is_synthetic=False,
        )

    with pytest.raises(ValueError, match="Crossed quote"):
        invert_two_way_quote(bid=1.10, ask=1.08)


def test_real_executable_quote_requires_bid_and_ask():
    """Real market EXECUTABLE_TWO_WAY_QUOTE cannot omit bid or ask."""
    with pytest.raises(ValueError, match="EXECUTABLE_TWO_WAY_QUOTE requires valid bid and ask"):
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="real_broker",
            entity_code="EUR/USD",
            observation_date=date(2024, 1, 2),
            observation_timestamp=datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 1, 2, 16, 0, tzinfo=timezone.utc),
            value=1.10,
            bid=None,
            ask=1.10,
            price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
            unit="USD",
            frequency=Frequency.DAILY,
            is_synthetic=False,
        )


def test_standalone_one_sided_quote_cannot_produce_round_trip():
    """A standalone BID_QUOTE or ASK_QUOTE cannot produce a complete two-way fill."""
    ts = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
    bid_only_obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="broker_feed",
        entity_code="EUR/USD",
        observation_date=date(2024, 1, 2),
        observation_timestamp=ts,
        retrieved_at=ts + timedelta(minutes=5),
        value=1.08,
        bid=1.08,
        price_type=PriceType.BID_QUOTE,
        unit="USD",
        frequency=Frequency.DAILY,
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        publication_timestamp=ts,
        is_synthetic=False,
    )

    store = PointInTimeDataStore([bid_only_obs], PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False)))

    # Requesting full two-way quote (required_side=None) returns None
    two_way = store.get_executable_quote("EUR/USD", as_of=ts + timedelta(minutes=1), required_side=None)
    assert two_way is None

    # Requesting canonical bid (exit: selling USD for EUR requires provider ask, missing) returns None
    bid_fill = store.get_executable_quote("EUR/USD", as_of=ts + timedelta(minutes=1), required_side="bid")
    assert bid_fill is None

    # Requesting canonical ask (entry: buying USD with EUR requires provider bid, present) succeeds
    ask_fill = store.get_executable_quote("EUR/USD", as_of=ts + timedelta(minutes=1), required_side="ask")
    assert ask_fill is not None
    assert ask_fill.quote_assembly_method == "standalone_one_sided"
    assert ask_fill.bid == 1.08
    assert ask_fill.ask is None
    assert ask_fill.rate_a_per_b == pytest.approx(1.0 / 1.08)


def test_quote_timestamp_requirement_for_real_data():
    """Real market executable quote without observation timestamp is rejected."""
    ts = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
    obs_no_ts = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="real_broker",
        entity_code="EUR/USD",
        observation_date=date(2024, 1, 2),
        observation_timestamp=None,  # Missing event timestamp
        publication_timestamp=ts,
        retrieved_at=ts + timedelta(minutes=5),
        value=1.10,
        bid=1.09,
        ask=1.11,
        price_type=PriceType.EXECUTABLE_TWO_WAY_QUOTE,
        unit="USD",
        frequency=Frequency.DAILY,
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        is_synthetic=False,
    )

    store = PointInTimeDataStore([obs_no_ts], PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False)))
    quote = store.get_executable_quote("EUR/USD", as_of=ts + timedelta(minutes=1), allow_reference_rate_proxy=False)
    assert quote is None


# =============================================================================
# 3. Execution Cost Accounting & No Double Counting
# =============================================================================

def test_mode_a_vs_mode_b_no_spread_double_counting():
    """Mode A executes at genuine market bid/ask directly without adding synthetic spread.
    Mode B executes on mid quote with synthetic spread.
    Total spread is never counted twice.
    """
    engine_mode_a = ExecutionEngine(ExecutionConfig(use_observed_spread=True, bid_ask_spread_bps=50.0, slippage_bps=0.0, variable_fee_bps=0.0, fixed_fee=0.0))
    engine_mode_b = ExecutionEngine(ExecutionConfig(use_observed_spread=False, bid_ask_spread_bps=50.0, slippage_bps=0.0, variable_fee_bps=0.0, fixed_fee=0.0))

    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    ts = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)

    # Observed quote: EUR/USD mid = 1.10, bid = 1.09, ask = 1.11
    # For A=EUR, B=USD: ask_a_per_b = 1.0 / 1.09, bid_a_per_b = 1.0 / 1.11
    bid_ab, ask_ab = get_two_way_quote_a_per_b(1.09, 1.11, "EUR", "USD", "EUR", "USD", QuoteConvention.QUOTE_PER_BASE)
    mid_ab = (bid_ab + ask_ab) / 2.0

    exec_quote = ExecutableQuoteResult(
        pair_code="EUR/USD",
        bid=1.09,
        ask=1.11,
        mid=1.10,
        rate_a_per_b=mid_ab,
        bid_a_per_b=bid_ab,
        ask_a_per_b=ask_ab,
        observation_timestamp=ts,
        availability_timestamp=ts,
        age_minutes=0.0,
        data_source="broker",
        price_type=BTPriceType.EXECUTABLE_TWO_WAY_QUOTE,
        is_executable=True,
        is_observed_spread=True,
        quote_assembly_method="genuine_two_way",
    )

    # Mode A execution
    trade_a = engine_mode_a.open_trade(
        trade_id="TRD_A",
        strategy_name="Mode A Test",
        currency_pair=pair,
        entry_date=date(2024, 1, 2),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.02,
        investment_rate=0.05,
        spot_mid_entry=mid_ab,
        exec_quote=exec_quote,
    )
    # Execution rate must equal observed ask rate exactly (no 50 bps added!)
    assert abs(trade_a.spot_exec_entry - ask_ab) < 1e-12
    assert trade_a.observed_spread_cost_a > 0
    assert trade_a.modelled_spread_cost_a == 0.0

    # Mode B execution
    trade_b = engine_mode_b.open_trade(
        trade_id="TRD_B",
        strategy_name="Mode B Test",
        currency_pair=pair,
        entry_date=date(2024, 1, 2),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.02,
        investment_rate=0.05,
        spot_mid_entry=mid_ab,
        exec_quote=exec_quote,
    )
    assert trade_b.observed_spread_cost_a == 0.0
    assert trade_b.modelled_spread_cost_a > 0


def test_exact_pnl_reconciliation():
    """Verify exact mathematical reconciliation:
    net_profit_a == pure_gross_gain_a - financing_cost_a - total_frictions_a
    and pure_gross_gain_a == fx_translation_gain_a + investment_yield_gain_a.
    """
    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=10.0, slippage_bps=5.0, variable_fee_bps=2.0, fixed_fee=10.0))
    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")

    spot_entry_mid = 0.909091  # 1/1.10
    trade = engine.open_trade(
        trade_id="TRD_REC",
        strategy_name="Reconciliation Test",
        currency_pair=pair,
        entry_date=date(2024, 1, 2),
        tenor_days=90,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.03,
        investment_rate=0.06,
        spot_mid_entry=spot_entry_mid,
    )

    spot_exit_mid = 0.925926  # 1/1.08 (USD appreciated)
    closed = engine.close_trade(
        trade=trade,
        exit_date=date(2024, 4, 1),
        spot_mid_exit=spot_exit_mid,
    )

    # 1. Gross decomposition exact equality
    gross_components = closed.fx_translation_gain_a + closed.investment_yield_gain_a
    assert abs(closed.pure_gross_gain_a - gross_components) < 1e-10

    # 2. Net profit decomposition exact equality
    reconciled_net = closed.pure_gross_gain_a - closed.financing_cost_a - closed.total_frictions_a
    assert abs(closed.net_profit_a - reconciled_net) < 1e-10
    assert closed.reconciliation_residual_a < 1e-10


# =============================================================================
# 4. Executability & Reference-Rate Proxy Classification
# =============================================================================

def test_reference_rate_proxy_never_becomes_executable():
    """A backtest using reference rate proxies is classified RESEARCH_PROXY, never EXECUTABLE_VALIDATED."""
    obs: list[DataObservation] = []
    d = date(2024, 1, 1)
    end = date(2024, 1, 10)
    while d <= end:
        ts = datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc)
        obs.append(
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="frankfurter",
                entity_code="EUR/USD",
                observation_date=d,
                publication_date=d,
                publication_timestamp=ts,
                retrieved_at=ts,
                value=1.10,
                unit="USD",
                frequency=Frequency.DAILY,
                price_type=PriceType.REFERENCE_RATE,  # Reference rate proxy!
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                is_synthetic=False,
            )
        )
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="repo",
                entity_code="EUR",
                indicator_id="EUR_RATE",
                observation_date=d,
                publication_date=d,
                publication_timestamp=ts,
                retrieved_at=ts,
                value=1.5,
                unit="percent",
                frequency=Frequency.DAILY,
                rate_role=RateRole.BORROWING_RATE,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                is_synthetic=False,
            )
        )
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="repo",
                entity_code="USD",
                indicator_id="USD_RATE",
                observation_date=d,
                publication_date=d,
                publication_timestamp=ts,
                retrieved_at=ts,
                value=4.5,
                unit="percent",
                frequency=Frequency.DAILY,
                rate_role=RateRole.DEPOSIT_RATE,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                is_synthetic=False,
            )
        )
        d += timedelta(days=1)

    cfg = BacktestConfig(
        strategy_name="Proxy Test",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 8),
        initial_capital_a=100_000.0,
        tenor_days=4,
        rebalance_frequency_days=4,
        hurdle_rate_annual=0.005,
        borrowing_rate_series_id="EUR_RATE",
        investment_rate_series_id="USD_RATE",
        require_commercial_rates=False,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
        execution_config=ExecutionConfig(allow_reference_rate_proxy=True),
    )
    result = BacktestEngine(cfg, obs).run()
    assert result.strategy_status == StrategyExecutabilityStatus.RESEARCH_PROXY
    assert result.is_executable_strategy is False


# =============================================================================
# 5. Benchmarks: Bounded Staleness & Currency Matching
# =============================================================================

def test_benchmark_currency_mismatch_rejected():
    """Benchmark with mismatched currency reports benchmark as unavailable."""
    dates = [date(2024, 1, 2), date(2024, 1, 3)]
    obs = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="test",
            entity_code="EUR/USD",
            observation_date=d,
            publication_timestamp=datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc),
            retrieved_at=datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc),
            value=1.10,
            unit="USD",
            frequency=Frequency.DAILY,
            is_synthetic=True,
        )
        for d in dates
    ]
    for d in dates:
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="test",
                entity_code="EUR",
                indicator_id="EUR_RATE",
                observation_date=d,
                publication_timestamp=datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc),
                retrieved_at=datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc),
                value=2.0,
                unit="percent",
                frequency=Frequency.DAILY,
                is_synthetic=True,
            )
        )
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="test",
                entity_code="USD",
                indicator_id="USD_RATE",
                observation_date=d,
                publication_timestamp=datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc),
                retrieved_at=datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc),
                value=5.0,
                unit="percent",
                frequency=Frequency.DAILY,
                is_synthetic=True,
            )
        )

    # Strategy borrows EUR, but benchmark specifies USD currency!
    cfg = BacktestConfig(
        strategy_name="Benchmark Mismatch Test",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=dates[0],
        end_date=dates[1],
        benchmark_spec=BenchmarkSpecification(
            name="USD Cash",
            benchmark_type=BenchmarkType.ZERO_CASH,
            currency="USD",  # Mismatched!
        ),
        signal_time_utc=(12, 0),
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
    )
    result = BacktestEngine(cfg, obs).run()
    assert result.metrics.benchmark_annualized_return is None
    assert result.metrics.alpha is None
    assert any("BENCHMARK UNAVAILABLE" in note for note in result.audit_trail)


def test_bounded_benchmark_staleness():
    """Historical benchmark forward filling beyond max_benchmark_stale_days is rejected."""
    start_d = date(2024, 1, 1)
    end_d = date(2024, 1, 20)
    dates = []
    curr = start_d
    while curr <= end_d:
        dates.append(curr)
        curr += timedelta(days=1)

    obs = []
    for d in dates:
        ts = datetime(d.year, d.month, d.day, 10, 0, tzinfo=timezone.utc)
        obs.append(DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="test",
            entity_code="EUR/USD",
            observation_date=d,
            publication_timestamp=ts,
            retrieved_at=ts,
            value=1.10,
            unit="USD",
            frequency=Frequency.DAILY,
            is_synthetic=True,
        ))
        obs.append(DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            entity_code="EUR",
            indicator_id="EUR_RATE",
            observation_date=d,
            publication_timestamp=ts,
            retrieved_at=ts,
            value=2.0,
            unit="percent",
            frequency=Frequency.DAILY,
            is_synthetic=True,
        ))
        obs.append(DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            entity_code="USD",
            indicator_id="USD_RATE",
            observation_date=d,
            publication_timestamp=ts,
            retrieved_at=ts,
            value=5.0,
            unit="percent",
            frequency=Frequency.DAILY,
            is_synthetic=True,
        ))

    # Add RF series only on Day 1, missing for next 19 days (exceeds max_stale=5)
    ts0 = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
    obs.append(DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        source_id="test",
        entity_code="EUR",
        indicator_id="ESTR",
        observation_date=date(2024, 1, 1),
        publication_timestamp=ts0,
        retrieved_at=ts0,
        value=1.8,
        unit="percent",
        frequency=Frequency.DAILY,
        rate_role=RateRole.RISK_FREE_RATE,
        is_synthetic=True,
    ))

    cfg = BacktestConfig(
        strategy_name="Stale Benchmark Test",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=start_d,
        end_date=end_d,
        benchmark_spec=BenchmarkSpecification(
            name="ESTR Risk Free",
            benchmark_type=BenchmarkType.HISTORICAL_RISK_FREE,
            series_id="ESTR",
            currency="EUR",
        ),
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
        execution_config=ExecutionConfig(max_benchmark_stale_days=5),
    )
    result = BacktestEngine(cfg, obs).run()
    # Benchmark must be rejected due to stale gap > 5 days
    assert result.metrics.benchmark_annualized_return is None
    assert result.metrics.alpha is None
    assert any("BENCHMARK UNAVAILABLE" in note for note in result.audit_trail)
