"""Phase 3.2.2.3.1 Audit Test Suite: Directional Quote, Evidence & Risk-Metric Integrity.

Covers 20 comprehensive regression tests:
1. test_directional_quote_provider_bid_to_canonical_ask_eur_usd
2. test_directional_quote_provider_ask_to_canonical_bid_eur_usd
3. test_directional_quote_reciprocal_usd_eur
4. test_standalone_quote_only_allows_long_entry_when_ask_available
5. test_standalone_quote_only_allows_exit_when_bid_available
6. test_standalone_bid_rejected_for_open_trade
7. test_standalone_ask_rejected_for_close_trade
8. test_frictions_applied_to_correct_executable_side_direct
9. test_frictions_applied_to_correct_executable_side_reciprocal
10. test_point_in_time_availability_status_enum
11. test_pit_credible_false_under_estimated_lag
12. test_pit_credible_false_under_research_only
13. test_pit_credible_true_under_strict_with_all_verified
14. test_pit_credible_validator_rejects_invalid_combination
15. test_data_provenance_separates_populated_vs_verified_counts
16. test_sharpe_and_sortino_none_when_benchmark_unavailable
17. test_sharpe_and_sortino_none_when_benchmark_mismatched
18. test_sharpe_and_sortino_zero_cash_explicit
19. test_sharpe_time_varying_periodic_risk_free
20. test_backtest_report_formatting_consistency
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math
import numpy as np
import pytest
from pydantic import ValidationError

from core.currency import (
    QuoteConvention,
    map_canonical_side_to_provider_side,
    normalize_directional_quote,
)
from models.risk import sharpe_ratio
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
from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall
from backtesting.execution import ExecutionEngine
from backtesting.engine import BacktestEngine
from backtesting.metrics import calculate_performance_metrics, calculate_sortino_ratio
from backtesting.provenance import build_data_provenance_report
from backtesting.reporting import export_backtest_result_json, format_backtest_report
from schemas.backtest import (
    AvailabilityPolicy,
    BacktestConfig,
    BacktestResult,
    BenchmarkSpecification,
    BenchmarkType,
    DataAvailabilityConfig,
    ExecutableQuoteResult,
    ExecutionConfig,
    PointInTimeAvailabilityStatus,
    PortfolioSnapshot,
    TradeRecord,
    TradeStatus,
)
from schemas.strategy import CurrencyPair, InterestConvention


def make_test_observations(
    start: date,
    end: date,
    evidence: AvailabilityEvidence = AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
    is_synth: bool = False,
    quote_values: list[float] | None = None,
) -> list[DataObservation]:
    obs = []
    curr = start
    idx = 0
    while curr <= end:
        ts = datetime.combine(curr, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=8)
        ret_ts = ts + timedelta(minutes=5)
        fx_val = quote_values[idx % len(quote_values)] if quote_values else 1.08 + (0.002 if idx % 2 == 0 else -0.002)
        idx += 1
        # FX observation
        obs.append(
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="test_feed",
                entity_code="EUR/USD",
                observation_date=curr,
                publication_date=curr,
                observation_timestamp=ts,
                publication_timestamp=ts,
                retrieved_at=ret_ts,
                value=fx_val,
                price_type=PriceType.REFERENCE_RATE,
                unit="USD",
                frequency=Frequency.DAILY,
                availability_evidence=evidence,
                is_synthetic=is_synth,
            )
        )
        # EUR borrowing rate
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="test_feed",
                entity_code="EUR",
                indicator_id="EUR_RATE",
                observation_date=curr,
                publication_date=curr,
                publication_timestamp=ts,
                retrieved_at=ret_ts,
                value=1.5,
                unit="percent",
                frequency=Frequency.DAILY,
                rate_role=RateRole.BORROWING_RATE,
                availability_evidence=evidence,
                is_synthetic=is_synth,
            )
        )
        # USD investment rate
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="test_feed",
                entity_code="USD",
                indicator_id="USD_RATE",
                observation_date=curr,
                publication_date=curr,
                publication_timestamp=ts,
                retrieved_at=ret_ts,
                value=4.5,
                unit="percent",
                frequency=Frequency.DAILY,
                rate_role=RateRole.DEPOSIT_RATE,
                availability_evidence=evidence,
                is_synthetic=is_synth,
            )
        )
        curr += timedelta(days=1)
    return obs


# =============================================================================
# 1. Directional One-Sided Quote Mapping & Inversion
# =============================================================================

def test_directional_quote_provider_bid_to_canonical_ask_eur_usd():
    """For EUR/USD with A=EUR, B=USD (rate=EUR/USD), provider BID normalizes to canonical ASK."""
    needed_provider_side = map_canonical_side_to_provider_side(
        requested_canonical_side="ask",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.QUOTE_PER_BASE,
    )
    assert needed_provider_side == "bid"

    res = normalize_directional_quote(
        provider_price=1.09,
        provider_side="bid",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.QUOTE_PER_BASE,
        requested_canonical_side="ask",
    )
    assert res.canonical_side == "ask"
    assert res.canonical_price == pytest.approx(1.0 / 1.09)


def test_directional_quote_provider_ask_to_canonical_bid_eur_usd():
    """For EUR/USD with A=EUR, B=USD (rate=EUR/USD), provider ASK normalizes to canonical BID."""
    needed_provider_side = map_canonical_side_to_provider_side(
        requested_canonical_side="bid",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.QUOTE_PER_BASE,
    )
    assert needed_provider_side == "ask"

    res = normalize_directional_quote(
        provider_price=1.11,
        provider_side="ask",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="EUR",
        investment_currency="USD",
        convention=QuoteConvention.QUOTE_PER_BASE,
        requested_canonical_side="bid",
    )
    assert res.canonical_side == "bid"
    assert res.canonical_price == pytest.approx(1.0 / 1.11)


def test_directional_quote_reciprocal_usd_eur():
    """For EUR/USD quote (USD per EUR) where strategy is A=USD, B=EUR (rate=USD/EUR):

    Canonical ASK (buying EUR with USD) maps directly to provider ASK.
    Canonical BID (selling EUR for USD) maps directly to provider BID.
    """
    needed_ask = map_canonical_side_to_provider_side(
        requested_canonical_side="ask",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="USD",
        investment_currency="EUR",
        convention=QuoteConvention.QUOTE_PER_BASE,
    )
    assert needed_ask == "ask"

    needed_bid = map_canonical_side_to_provider_side(
        requested_canonical_side="bid",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="USD",
        investment_currency="EUR",
        convention=QuoteConvention.QUOTE_PER_BASE,
    )
    assert needed_bid == "bid"

    res_ask = normalize_directional_quote(
        provider_price=1.11,
        provider_side="ask",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="USD",
        investment_currency="EUR",
        convention=QuoteConvention.QUOTE_PER_BASE,
        requested_canonical_side="ask",
    )
    assert res_ask.canonical_side == "ask"
    assert res_ask.canonical_price == 1.11

    res_bid = normalize_directional_quote(
        provider_price=1.09,
        provider_side="bid",
        obs_base="EUR",
        obs_quote="USD",
        borrowing_currency="USD",
        investment_currency="EUR",
        convention=QuoteConvention.QUOTE_PER_BASE,
        requested_canonical_side="bid",
    )
    assert res_bid.canonical_side == "bid"
    assert res_bid.canonical_price == 1.09


# =============================================================================
# 2. Standalone Quote Execution Restrictions
# =============================================================================

def test_standalone_quote_only_allows_long_entry_when_ask_available():
    """An ExecutableQuoteResult with only ask_a_per_b allows open_trade, but close_trade raises."""
    ts = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0, use_observed_spread=True))

    ask_only_quote = ExecutableQuoteResult(
        pair_code="EUR/USD",
        bid=None,
        ask=1.09,
        mid=1.09,
        rate_a_per_b=0.917431,
        bid_a_per_b=None,
        ask_a_per_b=0.917431,
        base_currency="EUR",
        quote_currency="USD",
        quote_convention=QuoteConvention.QUOTE_PER_BASE,
        observation_timestamp=ts,
        availability_timestamp=ts,
        age_minutes=5.0,
        data_source="broker",
        price_type=PriceType.ASK_QUOTE,
        is_executable=True,
        is_observed_spread=True,
        quote_assembly_method="standalone_one_sided",
    )

    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    trade = engine.open_trade(
        trade_id="T1",
        strategy_name="Carry",
        currency_pair=pair,
        entry_date=date(2024, 1, 2),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.03,
        investment_rate=0.05,
        spot_mid_entry=0.917431,
        exec_quote=ask_only_quote,
    )
    assert trade.status == TradeStatus.OPEN
    assert trade.spot_exec_entry == pytest.approx(0.917431)

    # Attempting to close trade using the same ask_only_quote raises ValueError
    with pytest.raises(ValueError, match="Cannot execute exit with a standalone ASK quote"):
        engine.close_trade(
            trade=trade,
            exit_date=date(2024, 2, 1),
            spot_mid_exit=0.917431,
            exec_quote=ask_only_quote,
        )


def test_standalone_quote_only_allows_exit_when_bid_available():
    """An ExecutableQuoteResult with only bid_a_per_b rejects open_trade, but allows close_trade."""
    ts = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=0.0, use_observed_spread=True))

    bid_only_quote = ExecutableQuoteResult(
        pair_code="EUR/USD",
        bid=1.11,
        ask=None,
        mid=1.11,
        rate_a_per_b=0.900901,
        bid_a_per_b=0.900901,
        ask_a_per_b=None,
        base_currency="EUR",
        quote_currency="USD",
        quote_convention=QuoteConvention.QUOTE_PER_BASE,
        observation_timestamp=ts,
        availability_timestamp=ts,
        age_minutes=5.0,
        data_source="broker",
        price_type=PriceType.BID_QUOTE,
        is_executable=True,
        is_observed_spread=True,
        quote_assembly_method="standalone_one_sided",
    )

    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    rejected_trade = engine.open_trade(
        trade_id="T2",
        strategy_name="Carry",
        currency_pair=pair,
        entry_date=date(2024, 1, 2),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.03,
        investment_rate=0.05,
        spot_mid_entry=0.900901,
        exec_quote=bid_only_quote,
    )
    assert rejected_trade.status == TradeStatus.REJECTED
    assert "standalone BID quote" in rejected_trade.rejection_reason

    # If trade was legitimately open, closing with bid_only_quote succeeds
    open_trade = TradeRecord(
        trade_id="T3",
        strategy_name="Carry",
        currency_pair=pair,
        borrowing_currency="EUR",
        investment_currency="USD",
        entry_date=date(2024, 1, 2),
        target_tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.03,
        investment_rate=0.05,
        spot_mid_entry=0.917431,
        spot_exec_entry=0.917431,
        invested_amount_b=100_000.0 / 0.917431,
        status=TradeStatus.OPEN,
    )
    closed = engine.close_trade(
        trade=open_trade,
        exit_date=date(2024, 2, 1),
        spot_mid_exit=0.900901,
        exec_quote=bid_only_quote,
    )
    assert closed.status == TradeStatus.CLOSED
    assert closed.spot_mid_exit == pytest.approx(0.900901)


def test_standalone_bid_rejected_for_open_trade():
    """Direct verification of standalone BID quote rejection in open_trade."""
    ts = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
    engine = ExecutionEngine(ExecutionConfig())
    bid_quote = ExecutableQuoteResult(
        pair_code="EUR/USD",
        bid=1.09,
        rate_a_per_b=0.9174,
        bid_a_per_b=0.9174,
        ask_a_per_b=None,
        observation_timestamp=ts,
        availability_timestamp=ts,
        age_minutes=2.0,
        data_source="feed",
        price_type=PriceType.BID_QUOTE,
        is_executable=True,
        quote_assembly_method="standalone_one_sided",
    )
    trade = engine.open_trade(
        trade_id="REJ_BID",
        strategy_name="Carry",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        entry_date=date(2024, 1, 2),
        tenor_days=30,
        principal_borrowed_a=50_000.0,
        borrowing_rate=0.03,
        investment_rate=0.05,
        spot_mid_entry=0.9174,
        exec_quote=bid_quote,
    )
    assert trade.status == TradeStatus.REJECTED
    assert "Cannot execute long-entry with a standalone BID quote" in trade.rejection_reason


def test_standalone_ask_rejected_for_close_trade():
    """Direct verification of standalone ASK quote rejection in close_trade."""
    ts = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
    engine = ExecutionEngine(ExecutionConfig())
    ask_quote = ExecutableQuoteResult(
        pair_code="EUR/USD",
        ask=1.11,
        rate_a_per_b=0.9009,
        bid_a_per_b=None,
        ask_a_per_b=0.9009,
        observation_timestamp=ts,
        availability_timestamp=ts,
        age_minutes=2.0,
        data_source="feed",
        price_type=PriceType.ASK_QUOTE,
        is_executable=True,
        quote_assembly_method="standalone_one_sided",
    )
    dummy_trade = TradeRecord(
        trade_id="OPEN_1",
        strategy_name="Carry",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        borrowing_currency="EUR",
        investment_currency="USD",
        entry_date=date(2024, 1, 2),
        target_tenor_days=30,
        principal_borrowed_a=50_000.0,
        borrowing_rate=0.03,
        investment_rate=0.05,
        spot_mid_entry=0.91,
        spot_exec_entry=0.91,
        invested_amount_b=54945.0,
        status=TradeStatus.OPEN,
    )
    with pytest.raises(ValueError, match="Cannot execute exit with a standalone ASK quote"):
        engine.close_trade(
            trade=dummy_trade,
            exit_date=date(2024, 2, 1),
            spot_mid_exit=0.9009,
            exec_quote=ask_quote,
        )


def test_frictions_applied_to_correct_executable_side_direct():
    """Frictions correctly applied to ask on entry and bid on exit for direct pair."""
    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=10.0, variable_fee_bps=5.0, use_observed_spread=True))
    ts = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")

    # Ask = 0.9174 EUR per USD. Adverse slippage +10 bps increases effective purchase price
    ask_quote = ExecutableQuoteResult(
        pair_code="EUR/USD",
        rate_a_per_b=0.9174,
        ask_a_per_b=0.9174,
        bid_a_per_b=None,
        observation_timestamp=ts,
        availability_timestamp=ts,
        age_minutes=1.0,
        data_source="feed",
        price_type=PriceType.ASK_QUOTE,
        is_executable=True,
        is_observed_spread=True,
        quote_assembly_method="standalone_one_sided",
    )
    trade = engine.open_trade(
        trade_id="T_FRIC",
        strategy_name="Carry",
        currency_pair=pair,
        entry_date=date(2024, 1, 2),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.02,
        investment_rate=0.04,
        spot_mid_entry=0.9174,
        exec_quote=ask_quote,
    )
    expected_rate = 0.9174 * (1.0 + 10.0 / 10_000.0)
    assert trade.spot_exec_entry == pytest.approx(expected_rate)
    assert trade.transaction_costs_a == pytest.approx(100_000.0 * 5.0 / 10_000.0)

    # Bid = 0.9009 EUR per USD. Adverse slippage -10 bps reduces effective sell price
    bid_quote = ExecutableQuoteResult(
        pair_code="EUR/USD",
        rate_a_per_b=0.9009,
        bid_a_per_b=0.9009,
        ask_a_per_b=None,
        observation_timestamp=ts,
        availability_timestamp=ts,
        age_minutes=1.0,
        data_source="feed",
        price_type=PriceType.BID_QUOTE,
        is_executable=True,
        is_observed_spread=True,
        quote_assembly_method="standalone_one_sided",
    )
    closed = engine.close_trade(
        trade=trade,
        exit_date=date(2024, 2, 1),
        spot_mid_exit=0.9009,
        exec_quote=bid_quote,
    )
    expected_exit = 0.9009 * (1.0 - 10.0 / 10_000.0)
    assert closed.spot_exec_exit == pytest.approx(expected_exit)
    assert (closed.reconciliation_residual_a or 0.0) <= 1e-10


def test_frictions_applied_to_correct_executable_side_reciprocal():
    """Frictions correctly applied to reciprocal pair USD/EUR."""
    engine = ExecutionEngine(ExecutionConfig(bid_ask_spread_bps=0.0, slippage_bps=20.0, variable_fee_bps=10.0, use_observed_spread=True))
    ts = datetime(2024, 1, 2, 10, 0, tzinfo=timezone.utc)
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")

    ask_quote = ExecutableQuoteResult(
        pair_code="USD/EUR",
        rate_a_per_b=1.10,
        ask_a_per_b=1.10,
        bid_a_per_b=None,
        observation_timestamp=ts,
        availability_timestamp=ts,
        age_minutes=1.0,
        data_source="feed",
        price_type=PriceType.ASK_QUOTE,
        is_executable=True,
        is_observed_spread=True,
        quote_assembly_method="standalone_one_sided",
    )
    trade = engine.open_trade(
        trade_id="T_RECIP",
        strategy_name="Carry",
        currency_pair=pair,
        entry_date=date(2024, 1, 2),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.05,
        investment_rate=0.03,
        spot_mid_entry=1.10,
        exec_quote=ask_quote,
    )
    assert trade.spot_exec_entry == pytest.approx(1.10 * (1.0 + 20.0 / 10_000.0))

    bid_quote = ExecutableQuoteResult(
        pair_code="USD/EUR",
        rate_a_per_b=1.08,
        bid_a_per_b=1.08,
        ask_a_per_b=None,
        observation_timestamp=ts,
        availability_timestamp=ts,
        age_minutes=1.0,
        data_source="feed",
        price_type=PriceType.BID_QUOTE,
        is_executable=True,
        is_observed_spread=True,
        quote_assembly_method="standalone_one_sided",
    )
    closed = engine.close_trade(
        trade=trade,
        exit_date=date(2024, 2, 1),
        spot_mid_exit=1.08,
        exec_quote=bid_quote,
    )
    assert closed.spot_exec_exit == pytest.approx(1.08 * (1.0 - 20.0 / 10_000.0))
    assert (closed.reconciliation_residual_a or 0.0) <= 1e-10


# =============================================================================
# 3. Point-in-Time Availability Status & Credibility
# =============================================================================

def test_point_in_time_availability_status_enum():
    """PointInTimeAvailabilityStatus enum values match requirements."""
    assert PointInTimeAvailabilityStatus.STRICT_VERIFIED == "strict_verified"
    assert PointInTimeAvailabilityStatus.ESTIMATED_AVAILABILITY == "estimated_availability"
    assert PointInTimeAvailabilityStatus.RETROSPECTIVE == "retrospective"
    assert PointInTimeAvailabilityStatus.INSUFFICIENT_EVIDENCE == "insufficient_evidence"


def test_pit_credible_false_under_estimated_lag():
    """An execution run under ESTIMATED_LAG policy produces is_point_in_time_credible = False."""
    start = date(2024, 1, 1)
    end = date(2024, 1, 15)
    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    cfg = BacktestConfig(
        strategy_name="TestEst",
        currency_pair=pair,
        start_date=start,
        end_date=end,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG, allow_synthetic=True),
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH),
        borrowing_rate_series_id="EUR_RATE",
        investment_rate_series_id="USD_RATE",
        require_commercial_rates=False,
    )
    obs = make_test_observations(start, end, evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE, is_synth=True)
    engine = BacktestEngine(config=cfg, observations=obs)
    res = engine.run()
    assert res.is_point_in_time_credible is False
    assert res.pit_availability_status == PointInTimeAvailabilityStatus.ESTIMATED_AVAILABILITY


def test_pit_credible_false_under_research_only():
    """An execution run under RESEARCH_ONLY policy produces is_point_in_time_credible = False."""
    start = date(2024, 1, 1)
    end = date(2024, 1, 15)
    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    cfg = BacktestConfig(
        strategy_name="TestRes",
        currency_pair=pair,
        start_date=start,
        end_date=end,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.RESEARCH_ONLY, allow_synthetic=True),
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH),
        borrowing_rate_series_id="EUR_RATE",
        investment_rate_series_id="USD_RATE",
        require_commercial_rates=False,
    )
    obs = make_test_observations(start, end, evidence=AvailabilityEvidence.RETROSPECTIVE, is_synth=True)
    engine = BacktestEngine(config=cfg, observations=obs)
    res = engine.run()
    assert res.is_point_in_time_credible is False
    assert res.pit_availability_status == PointInTimeAvailabilityStatus.RETROSPECTIVE


def test_pit_credible_true_under_strict_with_all_verified():
    """Strict run with 100% verified timestamps produces is_point_in_time_credible = True."""
    start = date(2024, 1, 1)
    end = date(2024, 1, 15)
    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    cfg = BacktestConfig(
        strategy_name="TestStrict",
        currency_pair=pair,
        start_date=start,
        end_date=end,
        signal_time_utc=(10, 0),
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH),
        borrowing_rate_series_id="EUR_RATE",
        investment_rate_series_id="USD_RATE",
        require_commercial_rates=False,
    )
    obs = make_test_observations(start, end, evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED, is_synth=False)
    engine = BacktestEngine(config=cfg, observations=obs)
    res = engine.run()
    assert res.is_point_in_time_credible is True
    assert res.pit_availability_status == PointInTimeAvailabilityStatus.STRICT_VERIFIED


def test_pit_credible_validator_rejects_invalid_combination():
    """Pydantic model validator raises ValidationError if is_point_in_time_credible = True with ESTIMATED_LAG."""
    cfg = BacktestConfig(
        strategy_name="TestVal",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG),
    )
    dummy_metrics = calculate_performance_metrics([], [], 100_000.0)

    with pytest.raises(ValidationError, match="cannot be True for ESTIMATED_LAG"):
        BacktestResult(
            config=cfg,
            trades=[],
            open_trades=[],
            snapshots=[],
            metrics=dummy_metrics,
            is_point_in_time_credible=True,  # Forbidden under ESTIMATED_LAG
            pit_availability_status=PointInTimeAvailabilityStatus.ESTIMATED_AVAILABILITY,
        )


def test_data_provenance_separates_populated_vs_verified_counts():
    """DataProvenanceReport clearly separates populated publication timestamps from verified counts."""
    start = date(2024, 1, 1)
    end = date(2024, 1, 31)

    obs = []
    # 10 observations with publication timestamp but ESTIMATED_SCHEDULE
    for d in range(1, 11):
        ts = datetime(2024, 1, d, 16, 0, tzinfo=timezone.utc)
        obs.append(
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="src1",
                entity_code="EUR/USD",
                observation_date=date(2024, 1, d),
                value=1.08,
                price_type=PriceType.REFERENCE_RATE,
                unit="USD",
                frequency=Frequency.DAILY,
                availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
                publication_timestamp=ts,
                retrieved_at=ts + timedelta(minutes=5),
                is_synthetic=False,
            )
        )
    # 5 observations with EXACT_TIMESTAMP_VERIFIED
    for d in range(11, 16):
        ts = datetime(2024, 1, d, 8, 0, tzinfo=timezone.utc)
        obs.append(
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="src2",
                entity_code="EUR/USD",
                observation_date=date(2024, 1, d),
                value=1.08,
                price_type=PriceType.REFERENCE_RATE,
                unit="USD",
                frequency=Frequency.DAILY,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                publication_timestamp=ts,
                retrieved_at=ts + timedelta(minutes=5),
                is_synthetic=False,
            )
        )

    report = build_data_provenance_report(
        observations=obs,
        start_date=start,
        end_date=end,
        currency_pair_code="EUR/USD",
        policy=AvailabilityPolicy.STRICT,
    )
    assert report.total_observations == 15
    assert report.timestamp_populated_count == 15
    assert report.timestamp_populated_pct == 1.0
    assert report.exact_timestamp_verified_count == 5
    assert report.exact_timestamp_verified_pct == pytest.approx(5.0 / 15.0)
    assert report.estimated_schedule_count == 10


# =============================================================================
# 4. Risk-Free Benchmark & Metric Non-Fallback
# =============================================================================

def test_sharpe_and_sortino_none_when_benchmark_unavailable():
    """When benchmark is None and risk_free_rate_annual is None, Sharpe and Sortino are None."""
    returns = [0.01, -0.005, 0.02, 0.003, -0.01, 0.015]
    snapshots = [
        PortfolioSnapshot(
            as_of=date(2024, 1, i + 1),
            cash_a=100_000.0,
            total_borrowed_a=0.0,
            total_obligations_a=0.0,
            active_positions_count=0,
            positions_value_a=0.0,
            equity_a=100_000.0 * (1.0 + sum(returns[: i + 1])),
            leverage=0.0,
            unrealized_pnl_a=0.0,
            realized_pnl_a=0.0,
            capital_utilization=0.0,
        )
        for i in range(len(returns))
    ]

    metrics = calculate_performance_metrics(
        trades=[],
        snapshots=snapshots,
        initial_capital_a=100_000.0,
        risk_free_rate_annual=None,
        benchmark=None,
    )
    assert metrics.sharpe_ratio is None
    assert metrics.sortino_ratio is None
    assert metrics.alpha is None
    assert metrics.annualized_excess_return is None
    assert metrics.cumulative_excess_return is None


def test_sharpe_and_sortino_none_when_benchmark_mismatched():
    """In BacktestEngine, when benchmark currency is mismatched (USD Treasury vs EUR), Sharpe is None."""
    start = date(2024, 1, 1)
    end = date(2024, 1, 15)
    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    cfg = BacktestConfig(
        strategy_name="MismatchBench",
        currency_pair=pair,
        start_date=start,
        end_date=end,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.RESEARCH_ONLY, allow_synthetic=True),
        # Intentional mismatch: USD sovereign yield requested for EUR liability
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.HISTORICAL_RISK_FREE,
            series_id="DGS1MO",
            currency="USD",
            reporting_currency="USD",
            name="Mismatched USD Treasury",
        ),
        borrowing_rate_series_id="EUR_RATE",
        investment_rate_series_id="USD_RATE",
        require_commercial_rates=False,
    )
    obs = make_test_observations(start, end, is_synth=True)
    engine = BacktestEngine(config=cfg, observations=obs)
    res = engine.run()
    # Currency mismatch forces benchmark_series = None and risk_free_ref = None
    assert res.metrics.sharpe_ratio is None
    assert res.metrics.sortino_ratio is None
    assert res.metrics.alpha is None


def test_sharpe_and_sortino_zero_cash_explicit():
    """Explicit ZERO_CASH benchmark evaluates Sharpe and Sortino against 0.0."""
    start = date(2024, 1, 1)
    end = date(2024, 1, 15)
    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    cfg = BacktestConfig(
        strategy_name="ZeroCashBench",
        currency_pair=pair,
        start_date=start,
        end_date=end,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.RESEARCH_ONLY, allow_synthetic=True),
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH),
        borrowing_rate_series_id="EUR_RATE",
        investment_rate_series_id="USD_RATE",
        require_commercial_rates=False,
    )
    obs = make_test_observations(start, end, is_synth=True)
    engine = BacktestEngine(config=cfg, observations=obs)
    res = engine.run()
    assert res.metrics.sharpe_ratio is not None
    assert res.metrics.sortino_ratio is not None


def test_sharpe_time_varying_periodic_risk_free():
    """Periodic risk-free rates compute mean(excess) / std(excess) * sqrt(periods)."""
    returns = np.array([0.01, 0.02, -0.005, 0.015, -0.002])
    rf_periodic = np.array([0.002, 0.002, 0.003, 0.002, 0.003])

    sh = sharpe_ratio(returns, periodic_risk_free_rates=rf_periodic, periods_per_year=252.0)

    excess = returns - rf_periodic
    expected_sh = float(np.mean(excess) / np.std(excess, ddof=1) * math.sqrt(252.0))
    assert sh == pytest.approx(expected_sh)

    # Sortino with periodic risk free
    so = calculate_sortino_ratio(returns, periodic_risk_free_rates=rf_periodic, periods_per_year=252.0)
    assert so is not None


def test_backtest_report_formatting_consistency():
    """Text and JSON backtest reports format pit_availability_status and separated timestamp percentages."""
    cfg = BacktestConfig(
        strategy_name="FormatTest",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG),
    )
    dummy_metrics = calculate_performance_metrics([], [], 100_000.0)
    provenance = build_data_provenance_report(
        observations=[],
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
        currency_pair_code="EUR/USD",
        policy=AvailabilityPolicy.ESTIMATED_LAG,
    )
    res = BacktestResult(
        config=cfg,
        trades=[],
        open_trades=[],
        snapshots=[],
        metrics=dummy_metrics,
        provenance=provenance,
        is_point_in_time_credible=False,
        pit_availability_status=PointInTimeAvailabilityStatus.ESTIMATED_AVAILABILITY,
    )

    # JSON export
    data = export_backtest_result_json(res)
    assert data["is_point_in_time_credible"] is False
    assert data["pit_availability_status"] == "estimated_availability"

    # Text report formatting
    report = format_backtest_report(res)
    assert "**PIT Availability Status**: `ESTIMATED_AVAILABILITY`" in report
    assert "**PIT Credible**: `NO`" in report
    assert "Publication Timestamps Populated" in report
    assert "Exact Publication Timestamps Verified" in report
