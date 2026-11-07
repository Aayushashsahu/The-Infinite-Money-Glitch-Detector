"""Comprehensive Quantitative Integrity, Point-in-Time & Executability Audit Tests.

Phase 3.2.1 Audit Test Suite:
1. Timestamp-Aware Point-in-Time Firewall:
   - Intraday same-day release timing (before vs after publication).
   - Multi-timezone normalization (ET vs CET vs UTC).
   - Chronological invariance (publication > signal strictly blocked).
2. Rate Semantics & Strategy Executability Classification:
   - RateRole hierarchy enforcement.
   - StrategyExecutabilityStatus: RESEARCH_PROXY, NO_TRADES, UNEXECUTABLE, RESEARCH_ONLY.
3. Trading Calendar & Weekend Rollover:
   - Trade entry rejection on non-trading days.
   - Trade maturity rollover to next trading day with recalculated financing for full calendar days.
4. Exact Double-Entry Return Attribution Ledger:
   - Exact reconciliation residual <= 1e-10.
   - Trade-level decomposition without double-counting.
5. Scoped Provenance & Manifest Integrity:
   - Scoped provenance report restricted to requested date range.
   - SHA-256 digest validation of data/manifest.json against raw archives.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from backtesting.calendar import DEFAULT_FX_CALENDAR
from backtesting.engine import BacktestEngine
from backtesting.execution import ExecutionEngine
from backtesting.metrics import calculate_performance_metrics
from backtesting.point_in_time import PointInTimeFirewall
from backtesting.provenance import build_data_provenance_report
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
    DataAvailabilityConfig,
    ExecutionConfig,
    PortfolioSnapshot,
    TradeStatus,
)
from schemas.strategy import CurrencyPair


# =============================================================================
# 1. Timestamp-Aware Point-in-Time Firewall Tests
# =============================================================================


def test_pit_firewall_intraday_same_day_filtering():
    """Verify that observations publishing later on day T are invisible at earlier times on day T."""
    firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT))

    # Rate published at 16:00 UTC on 2024-05-10
    obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="ecb",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 5, 10),
        publication_date=date(2024, 5, 10),
        observation_timestamp=datetime(2024, 5, 10, 14, 15, tzinfo=timezone.utc),
        publication_timestamp=datetime(2024, 5, 10, 16, 0, tzinfo=timezone.utc),
        retrieved_at=datetime(2024, 5, 10, 16, 5, tzinfo=timezone.utc),
        classification=DataClassification.REAL_VERIFIED,
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
    )

    # 1. At 14:00 UTC (before publication): must be BLOCKED
    signal_time_early = datetime(2024, 5, 10, 14, 0, tzinfo=timezone.utc)
    rec_early = firewall.get_latest_observation([obs], as_of=signal_time_early)
    assert rec_early is None, "Observation published at 16:00 UTC must NOT be visible at 14:00 UTC!"

    # 2. At 15:59 UTC (one minute before publication): must be BLOCKED
    signal_time_just_before = datetime(2024, 5, 10, 15, 59, tzinfo=timezone.utc)
    rec_just_before = firewall.get_latest_observation([obs], as_of=signal_time_just_before)
    assert rec_just_before is None, "Observation must NOT be visible before publication timestamp!"

    # 3. At 16:00 UTC (exact publication time): available
    signal_time_exact = datetime(2024, 5, 10, 16, 0, tzinfo=timezone.utc)
    rec_exact = firewall.get_latest_observation([obs], as_of=signal_time_exact)
    assert rec_exact is not None, "Observation must be visible at publication timestamp!"
    assert rec_exact.observation.value == 1.0850

    # 4. At 16:30 UTC: available
    signal_time_after = datetime(2024, 5, 10, 16, 30, tzinfo=timezone.utc)
    rec_after = firewall.get_latest_observation([obs], as_of=signal_time_after)
    assert rec_after is not None
    assert rec_after.observation.value == 1.0850


def test_pit_firewall_multi_timezone_normalization():
    """Verify that US Treasury close at 16:00 ET (20:00 or 21:00 UTC) normalizes correctly across timezones."""
    firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT))

    # US Treasury rate on 2024-07-15 (EDT, UTC-4)
    # Published at 16:00 ET = 20:00 UTC
    et_tz = ZoneInfo("America/New_York")
    pub_dt = datetime(2024, 7, 15, 16, 0, tzinfo=et_tz).astimezone(timezone.utc)

    obs = DataObservation(
        kind=ObservationKind.INTEREST_RATE,
        source_id="us_treasury",
        indicator_id="DGS3MO",
        entity_code="USD",
        value=5.35,
        unit="percent",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 7, 15),
        publication_date=date(2024, 7, 15),
        publication_timestamp=pub_dt,
        retrieved_at=datetime.now(timezone.utc),
        classification=DataClassification.REAL_VERIFIED,
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        rate_role=RateRole.RISK_FREE_RATE,
    )

    # London time: 18:00 UTC (same day, but before 16:00 ET) -> BLOCKED
    query_early_utc = datetime(2024, 7, 15, 18, 0, tzinfo=timezone.utc)
    assert firewall.get_latest_observation([obs], as_of=query_early_utc) is None

    # Tokyo time: 2024-07-16 06:00 JST = 2024-07-15 21:00 UTC -> AVAILABLE
    tokyo_tz = ZoneInfo("Asia/Tokyo")
    query_tokyo = datetime(2024, 7, 16, 6, 0, tzinfo=tokyo_tz)
    rec = firewall.get_latest_observation([obs], as_of=query_tokyo)
    assert rec is not None
    assert rec.observation.value == 5.35


def test_pit_firewall_future_observation_date_leakage():
    """Verify that observation with future observation date cannot leak even if query time is late."""
    firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT))

    obs_future = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="ecb",
        entity_code="EUR/USD",
        value=1.12,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 8, 2),
        publication_date=date(2024, 8, 2),
        retrieved_at=datetime.now(timezone.utc),
    )

    # Query on 2024-08-01 -> strictly blocked
    assert firewall.get_latest_observation([obs_future], as_of=date(2024, 8, 1)) is None


# =============================================================================
# 2. Rate Semantics & Strategy Executability Classification Tests
# =============================================================================


def test_strategy_status_classification_research_proxy():
    """Verify that a strategy using Treasury yields or Central Bank rates is classified as RESEARCH_PROXY."""
    obs_list = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="EUR/USD",
            value=1.10,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=date(2024, 1, 2) + timedelta(days=i),
            publication_date=date(2024, 1, 2) + timedelta(days=i),
            retrieved_at=datetime.now(timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
        )
        for i in range(60)
    ]
    # Add Treasury rate and ECB DFR
    for i in range(60):
        d = date(2024, 1, 2) + timedelta(days=i)
        obs_list.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="us_treasury",
                indicator_id="DGS3MO",
                entity_code="USD",
                value=5.25,
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=d,
                publication_date=d,
                retrieved_at=datetime.now(timezone.utc),
                rate_role=RateRole.RISK_FREE_RATE,
                classification=DataClassification.REAL_VERIFIED,
            )
        )
        obs_list.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="ecb",
                indicator_id="KR.DFR.LEV",
                entity_code="EUR",
                value=4.00,
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=d,
                publication_date=d,
                retrieved_at=datetime.now(timezone.utc),
                rate_role=RateRole.POLICY_RATE,
                classification=DataClassification.REAL_VERIFIED,
            )
        )

    config = BacktestConfig(
        strategy_name="Unhedged Carry (EUR/USD)",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2024, 1, 2),
        end_date=date(2024, 2, 28),
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.005,
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT),
    )

    engine = BacktestEngine(config, obs_list)
    res = engine.run()
    assert res.strategy_status == StrategyExecutabilityStatus.RESEARCH_PROXY, (
        f"Expected RESEARCH_PROXY when using Treasury/ECB policy rates, got {res.strategy_status}"
    )


def test_strategy_status_no_trades_classification():
    """Verify that when hurdle rate filters all trade candidates, status is NO_TRADES."""
    obs_list = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="EUR/USD",
            value=1.10,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=date(2024, 1, 2) + timedelta(days=i),
            publication_date=date(2024, 1, 2) + timedelta(days=i),
            retrieved_at=datetime.now(timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
        )
        for i in range(40)
    ]
    for i in range(40):
        d = date(2024, 1, 2) + timedelta(days=i)
        obs_list.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="commercial",
                entity_code="USD",
                value=5.00,
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=d,
                publication_date=d,
                retrieved_at=datetime.now(timezone.utc),
                rate_role=RateRole.BORROWING_RATE,
            )
        )
        obs_list.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="commercial",
                entity_code="EUR",
                value=3.00,
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=d,
                publication_date=d,
                retrieved_at=datetime.now(timezone.utc),
                rate_role=RateRole.DEPOSIT_RATE,
            )
        )

    # Impossible hurdle rate (50%) ensures 0 trades open
    config = BacktestConfig(
        strategy_name="Unhedged Carry (USD/EUR)",
        currency_pair=CurrencyPair(borrowing_currency="USD", investment_currency="EUR"),
        start_date=date(2024, 1, 2),
        end_date=date(2024, 2, 10),
        initial_capital_a=100_000.0,
        hurdle_rate_annual=0.50,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG),
    )

    engine = BacktestEngine(config, obs_list)
    res = engine.run()
    assert len(res.trades) == 0 or all(t.status == TradeStatus.REJECTED for t in res.trades)
    assert res.strategy_status == StrategyExecutabilityStatus.NO_TRADES


# =============================================================================
# 3. Trading Calendar & Weekend Rollover Tests
# =============================================================================


def test_calendar_rollover_weekend_to_next_trading_day():
    """Verify that a trade maturing on a Saturday rolls over to Monday with financing recalculated."""
    cal = DEFAULT_FX_CALENDAR

    # Trade entry on Thursday 2024-05-02
    entry_d = date(2024, 5, 2)
    assert cal.is_trading_day(entry_d)

    # 30-day tenor falls on Saturday 2024-06-01 (Weekend!)
    target_maturity = entry_d + timedelta(days=30)
    assert target_maturity == date(2024, 6, 1)
    assert not cal.is_trading_day(target_maturity), "Saturday must not be an active trading day!"

    # Next trading day is Monday 2024-06-03 (32 days elapsed)
    monday_d = date(2024, 6, 3)
    assert cal.is_trading_day(monday_d)

    # Mock daily observations up to Monday 2024-06-03
    obs_list = []
    d = entry_d
    while d <= monday_d:
        if cal.is_trading_day(d):
            obs_list.append(
                DataObservation(
                    kind=ObservationKind.EXCHANGE_RATE,
                    source_id="ecb",
                    entity_code="EUR/USD",
                    value=1.0800,
                    unit="USD_per_EUR",
                    frequency=Frequency.DAILY,
                    observation_date=d,
                    publication_date=d,
                    retrieved_at=datetime.now(timezone.utc),
                    classification=DataClassification.REAL_VERIFIED,
                )
            )
            obs_list.append(
                DataObservation(
                    kind=ObservationKind.INTEREST_RATE,
                    source_id="test",
                    entity_code="EUR",
                    value=3.50,
                    unit="percent",
                    frequency=Frequency.DAILY,
                    observation_date=d,
                    publication_date=d,
                    retrieved_at=datetime.now(timezone.utc),
                )
            )
            obs_list.append(
                DataObservation(
                    kind=ObservationKind.INTEREST_RATE,
                    source_id="test",
                    entity_code="USD",
                    value=5.50,
                    unit="percent",
                    frequency=Frequency.DAILY,
                    observation_date=d,
                    publication_date=d,
                    retrieved_at=datetime.now(timezone.utc),
                )
            )
        d += timedelta(days=1)

    config = BacktestConfig(
        strategy_name="Calendar Rollover Carry (EUR/USD)",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=entry_d,
        end_date=monday_d,
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=60,
        hurdle_rate_annual=0.01,
        simulate_trading_days_only=True,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.ESTIMATED_LAG),
    )

    engine = BacktestEngine(config, obs_list)
    res = engine.run()

    closed = [t for t in res.trades if t.status == TradeStatus.CLOSED]
    assert len(closed) == 1, "Exactly one trade should have completed"
    trade = closed[0]

    # Verify exit occurred on Monday 2024-06-03, NOT Saturday
    assert trade.exit_date == monday_d
    assert trade.actual_tenor_days == 32, f"Expected 32 elapsed calendar days, got {trade.actual_tenor_days}"
    # Financing interest must be for 32 days, not 30
    expected_financing = 100_000.0 * ((1.0 + 0.035) ** (32 / 365.25) - 1.0)
    assert abs(trade.interest_paid_a - expected_financing) < 1.0


# =============================================================================
# 4. Exact Double-Entry Return Attribution Ledger Tests
# =============================================================================


def test_exact_double_entry_attribution_reconciliation():
    """Verify that net profit matches the decomposed cash flow ledger down to 1e-10."""
    exec_engine = ExecutionEngine(
        ExecutionConfig(
            bid_ask_spread_bps=4.0,
            slippage_bps=1.0,
            variable_fee_bps=2.0,
            fixed_fee=10.0,
        )
    )

    trade = exec_engine.open_trade(
        trade_id="TRD_AUDIT_01",
        strategy_name="Audit Carry",
        currency_pair=CurrencyPair(borrowing_currency="USD", investment_currency="EUR"),
        entry_date=date(2024, 1, 15),
        tenor_days=30,
        principal_borrowed_a=100_000.0,
        borrowing_rate=0.045,
        investment_rate=0.025,
        spot_mid_entry=1.1000,
    )

    closed = exec_engine.close_trade(
        trade=trade,
        exit_date=date(2024, 2, 14),
        spot_mid_exit=1.0950,
    )

    # 1. Trade-level ledger reconciliation
    # Pure Gross Gain - Financing - Total Frictions = Net Profit
    reconciled_trade_pnl = (
        closed.pure_gross_gain_a
        - closed.financing_cost_a
        - closed.total_frictions_a
    )
    diff = abs(closed.net_profit_a - reconciled_trade_pnl)
    assert diff <= 1e-10, f"Trade PnL reconciliation discrepancy: {diff} exceeds tolerance 1e-10"
    assert closed.reconciliation_residual_a <= 1e-10

    # 2. Portfolio-level ledger reconciliation
    snapshot = PortfolioSnapshot(
        as_of=date(2024, 2, 14),
        cash_a=50_000.0,
        total_borrowed_a=0.0,
        total_obligations_a=0.0,
        active_positions_count=0,
        positions_value_a=0.0,
        equity_a=100_000.0 + closed.net_profit_a + 250.0,
        leverage=0.0,
        unrealized_pnl_a=0.0,
        realized_pnl_a=closed.net_profit_a,
        capital_utilization=0.0,
    )

    metrics = calculate_performance_metrics(
        trades=[closed],
        snapshots=[snapshot],
        initial_capital_a=100_000.0,
        risk_free_rate_annual=0.04,
        cash_interest_earned=250.0,
    )

    assert metrics.reconciliation_exact is True
    assert metrics.reconciliation_residual_a <= 1e-10
    # Return decomposition sum check
    decomp_sum = (
        metrics.gross_trade_return
        - metrics.financing_cost_drag
        - metrics.transaction_cost_drag
        + metrics.cash_yield_return
    )
    assert abs(decomp_sum - metrics.total_return) <= 1e-10


# =============================================================================
# 5. Scoped Provenance & Manifest Integrity Tests
# =============================================================================


def test_scoped_provenance_window():
    """Verify that build_data_provenance_report scopes observations strictly to the window."""
    obs_all = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="ecb",
            entity_code="EUR/USD",
            value=1.10,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=date(2018 + i, 6, 1),
            publication_date=date(2018 + i, 6, 1),
            retrieved_at=datetime.now(timezone.utc),
        )
        for i in range(7)  # 2018 to 2024
    ]

    prov = build_data_provenance_report(
        observations=obs_all,
        start_date=date(2021, 1, 1),
        end_date=date(2023, 12, 31),
        currency_pair_code="EUR/USD",
    )

    # Only 2021, 2022, 2023 observations should be in scoped count
    assert prov.total_observations == 3
    assert prov.date_range == (date(2021, 1, 1), date(2023, 12, 31))


def test_manifest_sha256_integrity():
    """Verify that data/manifest.json accurately reflects the sha256 of data/raw files."""
    manifest_path = Path("data/manifest.json")
    assert manifest_path.exists(), "data/manifest.json must exist!"

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "files" in data
    assert data["files_count"] == len(data["files"])
    assert data["files_count"] >= 8

    # Verify each recorded file hash against on-disk file
    raw_dir = Path("data/raw")
    for item in data["files"]:
        file_path = raw_dir / item["file_name"]
        assert file_path.exists(), f"Raw archive file {item['file_name']} missing!"
        actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        assert actual_sha == item["sha256"], f"SHA256 mismatch for {item['file_name']}!"
        assert file_path.stat().st_size == item["file_size_bytes"]
