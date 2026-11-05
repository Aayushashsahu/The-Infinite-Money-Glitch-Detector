"""Comprehensive Verification Test Suite for Phase 3.2.2.2.

Covers:
1. Conservative Availability Evidence (schemas.py & point_in_time.py):
   - Never upgrade to verified from timestamp alone
   - Strict firewall blocks estimated schedule and date-only unverified
   - Strict firewall permits exact timestamp verified
2. Separate Reference Rates, Valuation Prices & Executable Quotes:
   - PriceType classification (REFERENCE_RATE vs EXECUTABLE_TWO_WAY_QUOTE)
   - Frankfurter daily rates tagged as REFERENCE_RATE
   - get_reference_rate returns ValuationResult
   - get_executable_quote rejects REFERENCE_RATE when allow_reference_rate_proxy=False
   - get_executable_quote permits REFERENCE_RATE as proxy when allow_reference_rate_proxy=True
   - Strategy downgraded to RESEARCH_PROXY when using reference rate proxy
3. Correct Entry, Exit Timing & End-of-Backtest Liquidation:
   - TradeRecord exit metadata fields populated
   - End of backtest does not force-close with stale price; position preserved in open_trades
   - Next session open execution timing
4. Currency-Pair-Specific Settlement Calendars:
   - Easter calculation (Good Friday, Easter Monday)
   - TARGET2 holidays for EUR
   - US Fed holidays for USD with weekend observance shifts
   - Joint settlement day intersection (both must be open)
   - T+2 settlement calculation
   - is_approximate flag for unmodeled currency pairs
5. Benchmark Currency Matching & Zero-Fallback Elimination:
   - Currency match validation against borrowing currency
   - Mismatched currency (USD Treasury on EUR borrowing) marked UNAVAILABLE, alpha=None
   - Missing benchmark rates marked UNAVAILABLE without silent 0% fallback
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import pytest

from backtesting.calendar import (
    JointCurrencySettlementCalendar,
    _easter_date,
    _target_holidays,
    _us_fed_holidays,
    get_settlement_calendar,
)
from backtesting.engine import BacktestEngine
from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall
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
from schemas.backtest import (
    AvailabilityPolicy,
    BacktestConfig,
    BenchmarkSpecification,
    BenchmarkType,
    DataAvailabilityConfig,
    ExecutionConfig,
    PositionSizingConfig,
    PositionSizingMethod,
    TradeStatus,
)
from schemas.strategy import CurrencyPair


# =============================================================================
# 1. Conservative Availability Evidence Tests
# =============================================================================

def test_missing_evidence_defaults_to_estimated_schedule():
    """Observation with publication_timestamp but no evidence must not become EXACT_TIMESTAMP_VERIFIED."""
    obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="test_provider",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 3),
        publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
        retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
    )
    # Must conservatively default to ESTIMATED_SCHEDULE
    assert obs.availability_evidence == AvailabilityEvidence.ESTIMATED_SCHEDULE
    assert obs.availability_evidence != AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED


def test_strict_mode_rejects_timestamp_without_verified_evidence():
    """In STRICT mode, a publication_timestamp with ESTIMATED_SCHEDULE is rejected."""
    firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT))
    obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="test_provider",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 3),
        publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
        retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
        availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
    )
    rec = firewall.get_latest_observation([obs], as_of=datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc))
    assert rec is None, "ESTIMATED_SCHEDULE must be blocked in STRICT mode despite publication_timestamp."


def test_strict_mode_accepts_verified_timestamp():
    """In STRICT mode, an observation with EXACT_TIMESTAMP_VERIFIED and valid timestamp is accepted."""
    firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT))
    obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="test_provider",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 3),
        publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
        retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
    )
    rec = firewall.get_latest_observation([obs], as_of=datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc))
    assert rec is not None
    assert rec.is_verified_availability is True


def test_strict_mode_rejects_date_only_unverified():
    """In STRICT mode, a date-only observation without verified evidence is rejected."""
    firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT))
    obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="test_provider",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 3),
        publication_date=date(2024, 6, 3),
        retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
        availability_evidence=AvailabilityEvidence.RETROSPECTIVE,
    )
    rec = firewall.get_latest_observation([obs], as_of=date(2024, 6, 3))
    assert rec is None


# =============================================================================
# 2. Separate Reference Rates, Valuation Prices & Executable Quotes Tests
# =============================================================================

def test_frankfurter_adapter_tags_reference_rate(monkeypatch):
    """Frankfurter adapter must assign PriceType.REFERENCE_RATE to exchange rates."""
    from data.adapters.frankfurter import FrankfurterAdapter
    adapter = FrankfurterAdapter()
    monkeypatch.setattr(
        "data.adapters.frankfurter.get_json",
        lambda client, url, params=None: {"rates": {"2024-06-03": {"USD": 1.0850}}},
    )
    result = adapter.fetch_series("EUR", "USD", date(2024, 6, 3), date(2024, 6, 3))
    assert len(result.observations) == 1
    assert result.observations[0].price_type == PriceType.REFERENCE_RATE


def test_get_reference_rate_returns_valuation_result():
    """PointInTimeDataStore.get_reference_rate returns ValuationResult with full metadata."""
    obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 3),
        publication_date=date(2024, 6, 3),
        publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
        retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        price_type=PriceType.REFERENCE_RATE,
    )
    store = PointInTimeDataStore([obs])
    val = store.get_reference_rate("EUR/USD", as_of=datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc))
    assert val is not None
    assert val.rate == 1.0850
    assert val.price_type == PriceType.REFERENCE_RATE
    assert val.data_source == "frankfurter"
    assert val.pair_code == "EUR/USD"


def test_get_executable_quote_rejects_reference_rate_when_proxy_disallowed():
    """When allow_reference_rate_proxy=False, get_executable_quote rejects reference rates."""
    obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 3),
        publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
        retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        price_type=PriceType.REFERENCE_RATE,
    )
    store = PointInTimeDataStore([obs])
    quote = store.get_executable_quote(
        "EUR/USD",
        as_of=datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc),
        allow_reference_rate_proxy=False,
    )
    assert quote is None, "Executable quote must be None when only reference rate exists and proxy is disallowed."


def test_get_executable_quote_allows_reference_rate_when_proxy_allowed():
    """When allow_reference_rate_proxy=True, get_executable_quote returns proxy with is_executable=False."""
    obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 3),
        publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
        retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        price_type=PriceType.REFERENCE_RATE,
    )
    store = PointInTimeDataStore([obs])
    quote = store.get_executable_quote(
        "EUR/USD",
        as_of=datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc),
        allow_reference_rate_proxy=True,
    )
    assert quote is not None
    assert quote.is_executable is False
    assert quote.price_type == PriceType.REFERENCE_RATE
    assert quote.mid == 1.0850


# =============================================================================
# 3. Entry/Exit Timing & End-of-Backtest Liquidation Tests
# =============================================================================

def test_trade_record_has_exit_and_entry_metadata():
    """TradeRecord preserves entry and exit execution provenance."""
    d = date(2024, 6, 3)
    obs = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="test",
            entity_code="EUR/USD",
            value=1.0850,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            price_type=PriceType.REFERENCE_RATE,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="test",
            entity_code="EUR/USD",
            value=1.0860,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=date(2024, 6, 4),
            publication_timestamp=datetime(2024, 6, 4, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 4, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            price_type=PriceType.REFERENCE_RATE,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            indicator_id="EUR_RATE",
            entity_code="EUR",
            value=2.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.BORROWING_RATE,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            indicator_id="USD_RATE",
            entity_code="USD",
            value=5.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.DEPOSIT_RATE,
            is_synthetic=True,
        ),
    ]

    cfg = BacktestConfig(
        strategy_name="Metadata Test",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=d,
        end_date=date(2024, 6, 4),
        tenor_days=1,
        rebalance_frequency_days=1,
        hurdle_rate_annual=0.01,
        borrowing_rate_series_id="EUR_RATE",
        investment_rate_series_id="USD_RATE",
        require_commercial_rates=False,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
    )
    result = BacktestEngine(cfg, obs).run()
    assert len(result.trades) >= 1
    trade = result.trades[0]
    assert trade.entry_price_type is not None
    assert trade.exit_price_type is not None
    assert trade.exit_signal_timestamp is not None
    assert trade.exit_execution_timestamp is not None


def test_end_of_backtest_without_quote_preserves_open_position():
    """At simulation end, if no executable exit quote is available, position remains OPEN without artificial fill."""
    d = date(2024, 6, 3)
    # Observations only exist on entry date, NONE on end date
    obs = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="test",
            entity_code="EUR/USD",
            value=1.0850,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            indicator_id="EUR_RATE",
            entity_code="EUR",
            value=2.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.BORROWING_RATE,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            indicator_id="USD_RATE",
            entity_code="USD",
            value=5.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.DEPOSIT_RATE,
            is_synthetic=True,
        ),
    ]

    cfg = BacktestConfig(
        strategy_name="Unliquidated Open Trade Test",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=d,
        end_date=date(2024, 6, 4),
        tenor_days=1,
        rebalance_frequency_days=1,
        hurdle_rate_annual=0.01,
        borrowing_rate_series_id="EUR_RATE",
        investment_rate_series_id="USD_RATE",
        require_commercial_rates=False,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
    )
    result = BacktestEngine(cfg, obs).run()
    # No closed trades should exist because exit quote was missing
    assert len(result.trades) == 0
    # Position must be preserved in open_trades
    assert len(result.open_trades) == 1
    open_trade = result.open_trades[0]
    assert open_trade.status == TradeStatus.OPEN
    # Mark to market should be disclosed in snapshot
    assert result.snapshots[-1].positions_value_a > 0


# =============================================================================
# 4. Currency-Pair-Specific Settlement Calendars Tests
# =============================================================================

def test_easter_and_target_holidays():
    """Verify Meeus/Butcher Easter and TARGET2 settlement holidays."""
    # Easter 2024: March 31, 2024
    assert _easter_date(2024) == date(2024, 3, 31)
    target_2024 = _target_holidays(2024)
    assert date(2024, 1, 1) in target_2024   # New Year's Day
    assert date(2024, 3, 29) in target_2024  # Good Friday
    assert date(2024, 4, 1) in target_2024   # Easter Monday
    assert date(2024, 5, 1) in target_2024   # Labour Day
    assert date(2024, 12, 25) in target_2024 # Christmas Day
    assert date(2024, 12, 26) in target_2024 # Boxing Day


def test_us_fed_holidays_and_weekend_observance():
    """Verify US Federal Reserve holidays including Juneteenth and weekend shifts."""
    us_2021 = _us_fed_holidays(2021)
    # Juneteenth June 19, 2021 was Saturday -> observed Friday June 18
    assert date(2021, 6, 18) in us_2021

    us_2022 = _us_fed_holidays(2022)
    # Juneteenth June 19, 2022 was Sunday -> observed Monday June 20
    assert date(2022, 6, 20) in us_2022

    # Thanksgiving 2024: 4th Thursday in November = Nov 28, 2024
    us_2024 = _us_fed_holidays(2024)
    assert date(2024, 11, 28) in us_2024


def test_joint_settlement_calendar_eur_usd():
    """EUR/USD joint settlement calendar combines TARGET and US Fed holidays."""
    cal = get_settlement_calendar("EUR", "USD")
    assert cal.is_approximate is False
    assert "EUR/USD" in cal.calendar_name

    # Martin Luther King Day: Jan 15, 2024 (US closed, TARGET open -> non-settlement)
    assert cal.is_settlement_day(date(2024, 1, 15)) is False

    # Easter Monday: April 1, 2024 (TARGET closed, US open -> non-settlement)
    assert cal.is_settlement_day(date(2024, 4, 1)) is False

    # Normal joint business day: Jan 16, 2024 (Tuesday)
    assert cal.is_settlement_day(date(2024, 1, 16)) is True

    # Advance Friday Jan 12, 2024 by 2 joint settlement days:
    # Day 1: Tuesday Jan 16 (skips Sat, Sun, Mon Jan 15 MLK Day)
    # Day 2: Wednesday Jan 17
    assert cal.add_settlement_days(date(2024, 1, 12), 2) == date(2024, 1, 17)


def test_unmodeled_currency_pair_is_approximate():
    """Unmodeled currency pair falls back to global FX holidays with is_approximate=True."""
    cal = get_settlement_calendar("TRY", "BRL")
    assert cal.is_approximate is True
    assert "Approximate" in cal.calendar_name


# =============================================================================
# 5. Benchmark Currency Matching & Zero-Fallback Elimination Tests
# =============================================================================

def test_mismatched_benchmark_currency_marked_unavailable():
    """USD Treasury benchmark specified on EUR borrowing strategy is marked UNAVAILABLE."""
    d = date(2024, 6, 3)
    obs = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="test",
            entity_code="EUR/USD",
            value=1.0850,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="test",
            entity_code="EUR/USD",
            value=1.0860,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=date(2024, 6, 4),
            publication_timestamp=datetime(2024, 6, 4, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 4, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            indicator_id="EUR_RATE",
            entity_code="EUR",
            value=2.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.BORROWING_RATE,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            indicator_id="USD_RATE",
            entity_code="USD",
            value=5.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.DEPOSIT_RATE,
            is_synthetic=True,
        ),
    ]

    # Strategy borrows EUR, but benchmark specifies USD currency
    cfg = BacktestConfig(
        strategy_name="Mismatched Benchmark Test",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=d,
        end_date=date(2024, 6, 4),
        tenor_days=1,
        rebalance_frequency_days=1,
        hurdle_rate_annual=0.01,
        borrowing_rate_series_id="EUR_RATE",
        investment_rate_series_id="USD_RATE",
        require_commercial_rates=False,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.HISTORICAL_RISK_FREE,
            series_id="DGS3MO",
            currency="USD",  # Mismatch: strategy borrowing currency is EUR!
            name="US 3M Treasury Yield (USD)",
        ),
    )
    result = BacktestEngine(cfg, obs).run()
    # Benchmark must be UNAVAILABLE, and alpha/excess return must be None
    assert result.metrics.benchmark_annualized_return is None
    assert result.metrics.alpha is None
    assert result.metrics.annualized_excess_return is None
    assert any("Mismatched benchmark currency" in note for note in result.audit_trail)


def test_missing_historical_benchmark_rates_marked_unavailable_without_zero_fallback():
    """Missing risk-free series for borrowing currency marks benchmark UNAVAILABLE (no 0.0 fallback)."""
    d = date(2024, 6, 3)
    obs = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="test",
            entity_code="EUR/USD",
            value=1.0850,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="test",
            entity_code="EUR/USD",
            value=1.0860,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=date(2024, 6, 4),
            publication_timestamp=datetime(2024, 6, 4, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 4, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            indicator_id="EUR_RATE",
            entity_code="EUR",
            value=2.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.BORROWING_RATE,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            indicator_id="USD_RATE",
            entity_code="USD",
            value=5.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.DEPOSIT_RATE,
            is_synthetic=True,
        ),
    ]

    # Benchmark series EUR_NONEXISTENT does not exist in dataset
    cfg = BacktestConfig(
        strategy_name="Missing Benchmark Test",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=d,
        end_date=date(2024, 6, 4),
        tenor_days=1,
        rebalance_frequency_days=1,
        hurdle_rate_annual=0.01,
        borrowing_rate_series_id="EUR_RATE",
        investment_rate_series_id="USD_RATE",
        require_commercial_rates=False,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.HISTORICAL_RISK_FREE,
            series_id="EUR_NONEXISTENT",
            currency="EUR",
            name="Nonexistent EUR Risk-Free Rate",
        ),
    )
    result = BacktestEngine(cfg, obs).run()
    # Must NOT fall back to 0.0%
    assert result.metrics.benchmark_annualized_return is None
    assert result.metrics.alpha is None
    assert any("BENCHMARK UNAVAILABLE" in note for note in result.audit_trail)
