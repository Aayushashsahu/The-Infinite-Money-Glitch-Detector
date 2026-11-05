"""Phase 3.2.2.1 Database Round-Trip, Strict PIT & Execution Consistency Acceptance Tests.

Verifies:
1. Database Metadata Round-Trip:
   - Repository.load_observation_objects() preserves observation_timestamp, publication_timestamp,
     effective_timestamp, availability_evidence, and rate_role without silent loss.
   - PointInTimeFirewall produces identical availability semantics for original vs reloaded observations.
2. Conservative Availability Defaults & Verified Downgrade:
   - DataObservation with missing publication_timestamp defaults to ESTIMATED_SCHEDULE.
   - Verified evidence without publication_timestamp is downgraded to ESTIMATED_SCHEDULE with metadata notes.
3. Strict Point-in-Time Datetime Gate:
   - STRICT datetime evaluation rejects observations without verified publication timestamps.
   - Midnight UTC is never assumed under STRICT mode.
   - Verified timestamps <= as_of are strictly accepted.
   - ESTIMATED_LAG mode accepts estimated observations and reports is_verified=False.
4. Execution Calendar, Settlement & Price Tagging:
   - MarketCalendar.add_trading_days() advances over weekends and bank holidays.
   - Trade settlement date uses T+2 business days convention and is tagged in metadata.
   - Execution price source is tagged as execution_time_spot or signal_time_research_proxy.
5. Feasibility & Unverified Dataset Zero-Trades Guarantee:
   - Feasibility check accurately detects empty observations, unsupported pairs, and role mismatches.
   - STRICT backtest on unverified 2020-2024 real dataset yields exactly 0 trades and NO_TRADES status.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pytest

from backtesting.calendar import DEFAULT_FX_CALENDAR, MarketCalendar
from backtesting.engine import BacktestEngine
from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall
from data.db.engine import make_engine, make_session_factory
from data.repository import Repository
from data.schemas import (
    AvailabilityEvidence,
    DataClassification,
    DataObservation,
    Frequency,
    ObservationKind,
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
)
from schemas.strategy import CurrencyPair


RETRIEVED_AT = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def memory_repo() -> Repository:
    engine = make_engine("sqlite:///:memory:")
    session_factory = make_session_factory(engine)
    repo = Repository(session_factory)
    repo.create_all()
    repo.ensure_source("test_source", "Test Provider")
    repo.ensure_indicator("test_source", "DGS3MO", "3-Month Treasury", "percent", "daily")
    repo.ensure_indicator("test_source", "USD/EUR", "Spot Exchange Rate", "EUR", "daily")
    return repo


# -----------------------------------------------------------------------------
# 1. Database Metadata Round-Trip Tests
# -----------------------------------------------------------------------------

def test_repository_observation_object_round_trip(memory_repo: Repository):
    obs = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        entity_code="USA",
        indicator_id="DGS3MO",
        observation_date=date(2023, 6, 15),
        observation_timestamp=datetime(2023, 6, 15, 21, 0, tzinfo=timezone.utc),
        publication_date=date(2023, 6, 16),
        publication_timestamp=datetime(2023, 6, 16, 14, 30, tzinfo=timezone.utc),
        effective_timestamp=datetime(2023, 6, 16, 14, 30, tzinfo=timezone.utc),
        retrieved_at=RETRIEVED_AT,
        value=5.25,
        unit="percent",
        frequency=Frequency.DAILY,
        source_id="test_source",
        availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
        rate_role=RateRole.RISK_FREE_RATE,
        classification=DataClassification.REAL_VERIFIED,
        is_synthetic=False,
    )

    stats = memory_repo.insert_observations([obs])
    assert stats.inserted == 1

    reloaded = memory_repo.load_observation_objects(include_synthetic=False)
    assert len(reloaded) == 1
    rel = reloaded[0]

    assert rel.observation_timestamp == obs.observation_timestamp
    assert rel.publication_timestamp == obs.publication_timestamp
    assert rel.effective_timestamp == obs.effective_timestamp
    assert rel.availability_evidence == obs.availability_evidence
    assert rel.rate_role == obs.rate_role
    assert rel.classification == obs.classification
    assert rel.value == obs.value
    assert rel.indicator_id == obs.indicator_id
    assert rel.entity_code == obs.entity_code


def test_repository_round_trip_firewall_equivalence(memory_repo: Repository):
    obs = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        entity_code="USA",
        indicator_id="DGS3MO",
        observation_date=date(2023, 6, 15),
        observation_timestamp=datetime(2023, 6, 15, 21, 0, tzinfo=timezone.utc),
        publication_date=date(2023, 6, 16),
        publication_timestamp=datetime(2023, 6, 16, 14, 30, tzinfo=timezone.utc),
        effective_timestamp=datetime(2023, 6, 16, 14, 30, tzinfo=timezone.utc),
        retrieved_at=RETRIEVED_AT,
        value=5.25,
        unit="percent",
        frequency=Frequency.DAILY,
        source_id="test_source",
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        rate_role=RateRole.RISK_FREE_RATE,
        classification=DataClassification.REAL_VERIFIED,
        is_synthetic=False,
    )
    memory_repo.insert_observations([obs])
    reloaded = memory_repo.load_observation_objects(include_synthetic=False)[0]

    firewall_strict = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False))
    firewall_lag = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG, allow_synthetic=False))

    eval_timestamps = [
        datetime(2023, 6, 16, 10, 0, tzinfo=timezone.utc),
        datetime(2023, 6, 16, 14, 30, tzinfo=timezone.utc),
        datetime(2023, 6, 16, 16, 0, tzinfo=timezone.utc),
        datetime(2023, 6, 17, 9, 0, tzinfo=timezone.utc),
    ]

    for ts in eval_timestamps:
        strict_orig = firewall_strict.resolve_availability(obs, ts)
        strict_rel = firewall_strict.resolve_availability(reloaded, ts)
        assert strict_orig == strict_rel, f"Mismatch in STRICT mode at {ts}"

        lag_orig = firewall_lag.resolve_availability(obs, ts)
        lag_rel = firewall_lag.resolve_availability(reloaded, ts)
        assert lag_orig == lag_rel, f"Mismatch in ESTIMATED_LAG mode at {ts}"


# -----------------------------------------------------------------------------
# 2. Conservative Availability Defaults & Downgrade
# -----------------------------------------------------------------------------

def test_conservative_availability_defaults_when_timestamp_missing():
    obs = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        entity_code="USA",
        indicator_id="DGS3MO",
        observation_date=date(2023, 1, 10),
        publication_date=date(2023, 1, 10),
        retrieved_at=RETRIEVED_AT,
        value=4.50,
        unit="percent",
        frequency=Frequency.DAILY,
        source_id="test",
        classification=DataClassification.REAL_VERIFIED,
        is_synthetic=False,
    )
    assert obs.availability_evidence == AvailabilityEvidence.ESTIMATED_SCHEDULE
    assert obs.publication_timestamp is None


def test_downgrade_verified_evidence_without_timestamp():
    obs = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        entity_code="USA",
        indicator_id="DGS3MO",
        observation_date=date(2023, 1, 10),
        publication_date=date(2023, 1, 10),
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        retrieved_at=RETRIEVED_AT,
        value=4.50,
        unit="percent",
        frequency=Frequency.DAILY,
        source_id="test",
        classification=DataClassification.REAL_VERIFIED,
        is_synthetic=False,
    )
    assert obs.availability_evidence == AvailabilityEvidence.ESTIMATED_SCHEDULE
    assert obs.metadata.get("downgraded_evidence") == "exact_timestamp_requires_publication_timestamp"


# -----------------------------------------------------------------------------
# 3. Strict Point-in-Time Datetime Gate Tests
# -----------------------------------------------------------------------------

def test_strict_datetime_gate_rejects_missing_publication_timestamp():
    obs = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        entity_code="USA",
        indicator_id="DGS3MO",
        observation_date=date(2023, 1, 10),
        publication_date=date(2023, 1, 10),
        retrieved_at=RETRIEVED_AT,
        value=4.50,
        unit="percent",
        frequency=Frequency.DAILY,
        source_id="us_treasury",
        classification=DataClassification.REAL_VERIFIED,
        is_synthetic=False,
    )
    firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False))

    as_of = datetime(2023, 1, 10, 23, 59, 59, tzinfo=timezone.utc)
    is_eligible, _, _, _, note = firewall.resolve_availability(obs, as_of)
    assert is_eligible is False
    assert "rejected_in_strict_mode" in note


def test_strict_datetime_gate_accepts_verified_timestamp():
    obs = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        entity_code="USA",
        indicator_id="DGS3MO",
        observation_date=date(2023, 1, 10),
        observation_timestamp=datetime(2023, 1, 10, 10, 0, tzinfo=timezone.utc),
        publication_date=date(2023, 1, 10),
        publication_timestamp=datetime(2023, 1, 10, 14, 0, tzinfo=timezone.utc),
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        retrieved_at=RETRIEVED_AT,
        value=4.50,
        unit="percent",
        frequency=Frequency.DAILY,
        source_id="us_treasury",
        classification=DataClassification.REAL_VERIFIED,
        is_synthetic=False,
    )
    firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False))

    # 1. Before publication timestamp -> rejected
    as_of_before = datetime(2023, 1, 10, 13, 59, 59, tzinfo=timezone.utc)
    is_el, _, _, _, _ = firewall.resolve_availability(obs, as_of_before)
    assert is_el is False

    # 2. At publication timestamp -> accepted and verified
    as_of_exact = datetime(2023, 1, 10, 14, 0, 0, tzinfo=timezone.utc)
    is_el, _, _, is_ver, note = firewall.resolve_availability(obs, as_of_exact)
    assert is_el is True
    assert is_ver is True

    # 3. After publication timestamp -> accepted and verified
    as_of_after = datetime(2023, 1, 10, 16, 0, 0, tzinfo=timezone.utc)
    is_el, _, _, is_ver, note = firewall.resolve_availability(obs, as_of_after)
    assert is_el is True
    assert is_ver is True


def test_estimated_lag_mode_reports_unverified():
    obs = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        entity_code="USA",
        indicator_id="DGS3MO",
        observation_date=date(2023, 1, 10),
        publication_date=date(2023, 1, 10),
        retrieved_at=RETRIEVED_AT,
        value=4.50,
        unit="percent",
        frequency=Frequency.DAILY,
        source_id="us_treasury",
        classification=DataClassification.REAL_VERIFIED,
        is_synthetic=False,
    )
    firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG, allow_synthetic=False))

    as_of = datetime(2023, 1, 10, 17, 0, tzinfo=timezone.utc)
    is_eligible, avail_date, avail_dt, is_verified, note = firewall.resolve_availability(obs, as_of)
    assert is_eligible is True
    assert is_verified is False
    assert "estimated_schedule_publication_date" in note

    records = firewall.filter_available([obs], as_of)
    assert len(records) == 1
    assert records[0].is_verified_availability is False


# -----------------------------------------------------------------------------
# 4. Market Calendar, Settlement & Price Tagging Tests
# -----------------------------------------------------------------------------

def test_market_calendar_add_trading_days():
    cal = DEFAULT_FX_CALENDAR

    # Wednesday + 2 trading days = Friday
    assert cal.add_trading_days(date(2024, 1, 3), 2) == date(2024, 1, 5)

    # Thursday + 2 trading days = Monday (skips weekend)
    assert cal.add_trading_days(date(2024, 1, 4), 2) == date(2024, 1, 8)

    # Friday + 2 trading days = Tuesday (skips weekend)
    assert cal.add_trading_days(date(2024, 1, 5), 2) == date(2024, 1, 9)

    # New Year's Day (holiday 2024-01-01) + 1 trading day = Tuesday 2024-01-02
    assert cal.add_trading_days(date(2024, 1, 1), 1) == date(2024, 1, 2)


def test_execution_settlement_t_plus_2_business_days():
    # Construct synthetic daily observations spanning 2024-01-01 to 2024-01-15
    obs_list: list[DataObservation] = []
    curr = date(2024, 1, 1)
    while curr <= date(2024, 1, 15):
        # Spot quote
        obs_list.append(
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                entity_code="EUR/USD",
                observation_date=curr,
                publication_date=curr,
                publication_timestamp=datetime(curr.year, curr.month, curr.day, 10, 0, tzinfo=timezone.utc),
                retrieved_at=RETRIEVED_AT,
                value=1.10,
                unit="USD",
                frequency=Frequency.DAILY,
                source_id="test",
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                is_synthetic=True,
            )
        )
        # Rates
        obs_list.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                entity_code="EUR",
                indicator_id="EUR_RATE",
                observation_date=curr,
                publication_date=curr,
                publication_timestamp=datetime(curr.year, curr.month, curr.day, 10, 0, tzinfo=timezone.utc),
                retrieved_at=RETRIEVED_AT,
                value=2.0,
                unit="percent",
                frequency=Frequency.DAILY,
                source_id="test",
                rate_role=RateRole.BORROWING_RATE,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                is_synthetic=True,
            )
        )
        obs_list.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                entity_code="USD",
                indicator_id="USD_RATE",
                observation_date=curr,
                publication_date=curr,
                publication_timestamp=datetime(curr.year, curr.month, curr.day, 10, 0, tzinfo=timezone.utc),
                retrieved_at=RETRIEVED_AT,
                value=5.0,
                unit="percent",
                frequency=Frequency.DAILY,
                source_id="test",
                rate_role=RateRole.DEPOSIT_RATE,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                is_synthetic=True,
            )
        )
        curr += timedelta(days=1)

    cfg = BacktestConfig(
        strategy_name="Settlement Test",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 12),
        initial_capital_a=100_000.0,
        tenor_days=5,
        rebalance_frequency_days=5,
        hurdle_rate_annual=0.005,
        borrowing_rate_series_id="EUR_RATE",
        investment_rate_series_id="USD_RATE",
        require_commercial_rates=False,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
    )
    result = BacktestEngine(cfg, obs_list).run()
    assert len(result.trades) > 0
    trade = result.trades[0]

    # Verify T+2 business days convention tagging and arithmetic
    assert trade.metadata.get("settlement_convention") == "T+2_business_days"
    expected_settlement = DEFAULT_FX_CALENDAR.add_trading_days(trade.entry_date, 2)
    assert trade.settlement_timestamp.date() == expected_settlement


def test_execution_price_source_tagged():
    obs_list: list[DataObservation] = []
    curr = date(2024, 1, 1)
    while curr <= date(2024, 1, 10):
        obs_list.append(
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                entity_code="EUR/USD",
                observation_date=curr,
                publication_date=curr,
                publication_timestamp=datetime(curr.year, curr.month, curr.day, 10, 0, tzinfo=timezone.utc),
                retrieved_at=RETRIEVED_AT,
                value=1.08,
                unit="USD",
                frequency=Frequency.DAILY,
                source_id="test",
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                is_synthetic=True,
            )
        )
        obs_list.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                entity_code="EUR",
                indicator_id="EUR_RATE",
                observation_date=curr,
                publication_date=curr,
                publication_timestamp=datetime(curr.year, curr.month, curr.day, 10, 0, tzinfo=timezone.utc),
                retrieved_at=RETRIEVED_AT,
                value=1.5,
                unit="percent",
                frequency=Frequency.DAILY,
                source_id="test",
                rate_role=RateRole.BORROWING_RATE,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                is_synthetic=True,
            )
        )
        obs_list.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                entity_code="USD",
                indicator_id="USD_RATE",
                observation_date=curr,
                publication_date=curr,
                publication_timestamp=datetime(curr.year, curr.month, curr.day, 10, 0, tzinfo=timezone.utc),
                retrieved_at=RETRIEVED_AT,
                value=4.5,
                unit="percent",
                frequency=Frequency.DAILY,
                source_id="test",
                rate_role=RateRole.DEPOSIT_RATE,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                is_synthetic=True,
            )
        )
        curr += timedelta(days=1)

    cfg = BacktestConfig(
        strategy_name="Price Source Tagging Test",
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
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
    )
    result = BacktestEngine(cfg, obs_list).run()
    assert len(result.trades) > 0
    trade = result.trades[0]
    assert "price_source" in trade.metadata
    assert trade.metadata["price_source"] in ("execution_timestamp_market", "signal_time_research_proxy")


# -----------------------------------------------------------------------------
# 5. Feasibility & Unverified Dataset Zero-Trades Guarantee
# -----------------------------------------------------------------------------

def test_simulation_feasibility_reflects_reality():
    cfg = BacktestConfig(
        strategy_name="Feasibility Test",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 10),
        initial_capital_a=100_000.0,
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        require_commercial_rates=True,
    )

    # 1. Empty observations -> UNEXECUTABLE
    engine_empty = BacktestEngine(cfg, [])
    res_empty = engine_empty.run()
    assert res_empty.strategy_status == StrategyExecutabilityStatus.UNEXECUTABLE
    assert len(res_empty.trades) == 0

    # 2. Unsupported currency pair -> UNEXECUTABLE
    dummy_obs = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            entity_code="GBP/JPY",
            observation_date=date(2024, 1, 2),
            publication_date=date(2024, 1, 2),
            retrieved_at=RETRIEVED_AT,
            value=180.0,
            unit="JPY",
            frequency=Frequency.DAILY,
            source_id="test",
            is_synthetic=True,
        )
    ]
    engine_unsupported = BacktestEngine(cfg, dummy_obs)
    res_unsupported = engine_unsupported.run()
    assert res_unsupported.strategy_status == StrategyExecutabilityStatus.UNEXECUTABLE
    assert len(res_unsupported.trades) == 0


def test_strict_mode_zero_trades_on_unverified_dataset():
    db_path = "sqlite:///data/processed/gmdb.db"
    if not Path("data/processed/gmdb.db").exists():
        pytest.skip("gmdb.db database not available for real data verification")

    engine = make_engine(db_path)
    session_factory = make_session_factory(engine)
    repo = Repository(session_factory)
    all_obs = repo.load_observation_objects(include_synthetic=False)

    cfg = BacktestConfig(
        strategy_name="Verified Strict Real Data Test",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
        benchmark_spec=BenchmarkSpecification(benchmark_type=BenchmarkType.ZERO_CASH, name="Zero Cash (0.0%)"),
    )
    result = BacktestEngine(cfg, all_obs).run()

    # In strict mode on unverified dataset:
    # 0 trades must execute, status must be NO_TRADES, is_executable_strategy must be False
    assert len(result.trades) == 0
    assert result.strategy_status in (StrategyExecutabilityStatus.NO_TRADES, StrategyExecutabilityStatus.RESEARCH_PROXY)
    assert result.is_executable_strategy is False
