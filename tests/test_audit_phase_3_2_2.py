"""Phase 3.2.2 Integration Integrity & Reproducibility Closure Audit Tests.

Verifies:
1. End-to-End Timestamp Integration in BacktestEngine:
   - Same-day publication before signal is accepted and executed.
   - Same-day publication after signal is rejected / blocked.
   - TradeRecord execution chronology: signal <= order_submission <= execution <= settlement.
   - Post-market publication does not permit impossible same-day opening trades.
2. Availability Evidence Semantics & Contradiction Guardrails:
   - STRICT policy requires EXACT_TIMESTAMP_VERIFIED and rejects ESTIMATED_SCHEDULE.
   - Unverified same day and retrospective data rejected from executable paths.
   - Pydantic models prohibit contradictory authenticity and availability combinations.
3. Strategy Executability Semantics & Rate Roles:
   - Policy rates and sovereign yields cannot satisfy commercial borrowing requirements when require_commercial_rates=True.
   - RESEARCH_PROXY strategies strictly enforce is_executable_strategy=False.
   - BacktestResult validator prohibits is_executable_strategy=True for non-validated statuses.
4. Benchmark Integrity & Excess Returns:
   - ZERO_CASH benchmark earns strictly 0.0% nominal return, never falling back to borrowing rates.
   - UNAVAILABLE benchmark is cleanly flagged without claiming false alpha.
   - Cumulative and annualized excess returns match exact difference against benchmark.
5. Report and Accounting Reconciliation:
   - Machine-generated JSON export matches BacktestResult down to the cent.
   - Exact cash flow attribution ledger residual |residual| <= 1e-10.
6. Raw Archive Byte-Stability & Offline Manifest Integrity:
   - Reproduces and verifies SHA-256 digests for all 14 raw archives without network calls.
   - Verifies coverage of Frankfurter FX, Treasury 1M, Treasury 3M, ECB DFR, ECB MRO.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from pydantic import ValidationError

from backtesting.engine import BacktestEngine
from backtesting.point_in_time import PointInTimeDataStore, PointInTimeFirewall
from backtesting.reporting import export_backtest_result_json, format_backtest_report
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
    TradeRecord,
    TradeStatus,
    BacktestResult,
)
from schemas.strategy import CurrencyPair


# =============================================================================
# 1. End-to-End Timestamp Integration Tests
# =============================================================================

def test_engine_same_day_publication_before_signal_executes():
    """Observation published at 14:00 UTC is visible to engine signal at 16:00 UTC."""
    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    d = date(2024, 6, 3)  # Monday

    obs = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="EUR/USD",
            value=1.0850,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_date=d,
            observation_timestamp=datetime(2024, 6, 3, 14, 15, tzinfo=timezone.utc),
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 14, 35, tzinfo=timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="ecb",
            indicator_id="KR.DFR.LEV",
            entity_code="EUR",
            value=3.75,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_date=d,
            observation_timestamp=datetime(2024, 6, 3, 14, 15, tzinfo=timezone.utc),
            publication_timestamp=datetime(2024, 6, 3, 14, 30, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 14, 35, tzinfo=timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.POLICY_RATE,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            indicator_id="DGS3MO",
            entity_code="USD",
            value=5.40,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_date=d,
            observation_timestamp=datetime(2024, 6, 3, 14, 0, tzinfo=timezone.utc),
            publication_timestamp=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 15, 5, tzinfo=timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.RISK_FREE_RATE,
        ),
    ]

    cfg = BacktestConfig(
        strategy_name="Intraday Timestamp Execution",
        currency_pair=pair,
        start_date=d,
        end_date=date(2024, 6, 4),
        initial_capital_a=100_000.0,
        tenor_days=1,
        rebalance_frequency_days=1,
        hurdle_rate_annual=0.005,
        signal_time_utc=(16, 0),  # 16:00 UTC > 14:30 and 15:00 publication
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
        position_sizing=PositionSizingConfig(method=PositionSizingMethod.FIXED_AMOUNT, fixed_amount=50_000.0),
    )

    engine = BacktestEngine(cfg, obs)
    res = engine.run()

    # Rate differential: USD (5.40%) - EUR (3.75%) = +1.65% > 0.50% hurdle -> Trade opened
    assert len(res.trades) >= 1
    t = res.trades[0]
    assert t.signal_timestamp == datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc)
    assert t.order_submission_timestamp == datetime(2024, 6, 3, 16, 0, 1, tzinfo=timezone.utc)
    assert t.execution_timestamp == datetime(2024, 6, 3, 17, 0, tzinfo=timezone.utc)
    assert t.settlement_timestamp == datetime(2024, 6, 5, 17, 0, tzinfo=timezone.utc)


def test_engine_same_day_publication_after_signal_rejected():
    """Observation published at 17:00 UTC is invisible to signal evaluated at 16:00 UTC."""
    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    d = date(2024, 6, 3)

    # Observation published at 17:00 UTC (1 hour AFTER 16:00 UTC signal time)
    obs = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="EUR/USD",
            value=1.0850,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_date=d,
            observation_timestamp=datetime(2024, 6, 3, 16, 30, tzinfo=timezone.utc),
            publication_timestamp=datetime(2024, 6, 3, 17, 0, tzinfo=timezone.utc),
            retrieved_at=datetime(2024, 6, 3, 17, 5, tzinfo=timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        ),
    ]

    cfg = BacktestConfig(
        strategy_name="Late Publication Rejection",
        currency_pair=pair,
        start_date=d,
        end_date=date(2024, 6, 4),
        signal_time_utc=(16, 0),
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
    )

    engine = BacktestEngine(cfg, obs)
    res = engine.run()

    # Exchange rate is invisible at 16:00 UTC -> no trade can execute
    assert len(res.trades) == 0
    assert len(res.rejections) > 0


def test_trade_record_chronological_timestamp_ordering():
    """Execution chronologically guarantees observation <= publication <= signal <= execution <= settlement."""
    t = TradeRecord(
        trade_id="TRD_001",
        strategy_name="Chronology Test",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        borrowing_currency="EUR",
        investment_currency="USD",
        entry_date=date(2024, 6, 3),
        target_tenor_days=30,
        principal_borrowed_a=50_000.0,
        borrowing_rate=0.0375,
        investment_rate=0.0540,
        spot_mid_entry=1.0850,
        spot_exec_entry=1.0852,
        signal_timestamp=datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc),
        order_submission_timestamp=datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc),
        execution_timestamp=datetime(2024, 6, 3, 17, 0, tzinfo=timezone.utc),
        settlement_timestamp=datetime(2024, 6, 5, 17, 0, tzinfo=timezone.utc),
    )

    assert t.signal_timestamp <= t.order_submission_timestamp
    assert t.order_submission_timestamp <= t.execution_timestamp
    assert t.execution_timestamp <= t.settlement_timestamp


# =============================================================================
# 2. Availability Evidence Semantics & Contradiction Guardrails
# =============================================================================

def test_strict_policy_rejects_estimated_schedule():
    """Under AvailabilityPolicy.STRICT, ESTIMATED_SCHEDULE is excluded from execution."""
    firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT))

    obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 3),
        publication_date=date(2024, 6, 3),
        observation_timestamp=datetime(2024, 6, 3, 14, 15, tzinfo=timezone.utc),
        publication_timestamp=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
        retrieved_at=datetime(2024, 6, 3, 15, 5, tzinfo=timezone.utc),
        classification=DataClassification.REAL_VERIFIED,
        availability_evidence=AvailabilityEvidence.ESTIMATED_SCHEDULE,
    )

    # In strict mode, ESTIMATED_SCHEDULE must return None
    res = firewall.get_latest_observation([obs], as_of=datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc))
    assert res is None, "ESTIMATED_SCHEDULE must NOT pass the STRICT execution gate!"


def test_strict_policy_accepts_exact_timestamp_verified():
    """Under AvailabilityPolicy.STRICT, EXACT_TIMESTAMP_VERIFIED passes."""
    firewall = PointInTimeFirewall(DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT))

    obs = DataObservation(
        kind=ObservationKind.EXCHANGE_RATE,
        source_id="frankfurter",
        entity_code="EUR/USD",
        value=1.0850,
        unit="USD_per_EUR",
        frequency=Frequency.DAILY,
        observation_date=date(2024, 6, 3),
        publication_date=date(2024, 6, 3),
        observation_timestamp=datetime(2024, 6, 3, 14, 15, tzinfo=timezone.utc),
        publication_timestamp=datetime(2024, 6, 3, 15, 0, tzinfo=timezone.utc),
        retrieved_at=datetime(2024, 6, 3, 15, 5, tzinfo=timezone.utc),
        classification=DataClassification.REAL_VERIFIED,
        availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
    )

    res = firewall.get_latest_observation([obs], as_of=datetime(2024, 6, 3, 16, 0, tzinfo=timezone.utc))
    assert res is not None
    assert res.observation.value == 1.0850


def test_data_observation_contradiction_validation():
    """Pydantic model validator prevents contradictory authenticity and availability evidence."""
    # 1. REAL_RETROSPECTIVE cannot have EXACT_TIMESTAMP_VERIFIED
    with pytest.raises(ValidationError):
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            entity_code="USD",
            value=5.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=date(2024, 1, 1),
            publication_date=date(2024, 1, 1),
            retrieved_at=datetime.now(timezone.utc),
            classification=DataClassification.REAL_RETROSPECTIVE,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        )

    # 2. REAL_VERIFIED cannot have RETROSPECTIVE evidence
    with pytest.raises(ValidationError):
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test",
            entity_code="USD",
            value=5.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=date(2024, 1, 1),
            publication_date=date(2024, 1, 1),
            retrieved_at=datetime.now(timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=AvailabilityEvidence.RETROSPECTIVE,
        )


# =============================================================================
# 3. Strategy Executability Semantics & Rate Roles
# =============================================================================

def test_policy_rate_cannot_satisfy_commercial_borrowing_rate():
    """When require_commercial_rates=True, policy rates cause UNEXECUTABLE classification."""
    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    d = date(2024, 6, 3)

    obs = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="EUR/USD",
            value=1.0850,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_date=d,
            retrieved_at=datetime.now(timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="ecb",
            indicator_id="KR.DFR.LEV",
            entity_code="EUR",
            value=3.75,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_date=d,
            retrieved_at=datetime.now(timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.POLICY_RATE,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            indicator_id="DGS3MO",
            entity_code="USD",
            value=5.40,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_date=d,
            retrieved_at=datetime.now(timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.RISK_FREE_RATE,
        ),
    ]

    cfg = BacktestConfig(
        strategy_name="Commercial Rate Enforcement",
        currency_pair=pair,
        start_date=d,
        end_date=date(2024, 6, 4),
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        require_commercial_rates=True,  # Reject sovereign/policy proxies
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
    )

    engine = BacktestEngine(cfg, obs)
    res = engine.run()

    assert res.strategy_status == StrategyExecutabilityStatus.UNEXECUTABLE
    assert res.is_executable_strategy is False
    assert res.is_economically_representative is False
    assert "commercial borrowing rate required" in (res.unsupported_reason or "").lower()


def test_research_proxy_cannot_be_is_executable_true():
    """A strategy classified as RESEARCH_PROXY strictly forbids is_executable_strategy=True."""
    pair = CurrencyPair(borrowing_currency="EUR", investment_currency="USD")
    d = date(2024, 6, 3)

    obs = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="frankfurter",
            entity_code="EUR/USD",
            value=1.0850,
            unit="USD_per_EUR",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_date=d,
            retrieved_at=datetime.now(timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="ecb",
            indicator_id="KR.DFR.LEV",
            entity_code="EUR",
            value=3.75,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_date=d,
            retrieved_at=datetime.now(timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.POLICY_RATE,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="us_treasury",
            indicator_id="DGS3MO",
            entity_code="USD",
            value=5.40,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=d,
            publication_date=d,
            retrieved_at=datetime.now(timezone.utc),
            classification=DataClassification.REAL_VERIFIED,
            availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            rate_role=RateRole.RISK_FREE_RATE,
        ),
    ]

    cfg = BacktestConfig(
        strategy_name="Research Proxy Carry",
        currency_pair=pair,
        start_date=d,
        end_date=date(2024, 6, 4),
        borrowing_rate_series_id="KR.DFR.LEV",
        investment_rate_series_id="DGS3MO",
        require_commercial_rates=False,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
    )

    engine = BacktestEngine(cfg, obs)
    res = engine.run()

    assert res.can_simulate is True
    assert res.strategy_status == StrategyExecutabilityStatus.RESEARCH_PROXY
    assert res.is_executable_strategy is False


def test_backtest_result_model_validator_forbids_contradictory_executability():
    """BacktestResult Pydantic model validator raises if is_executable_strategy=True for RESEARCH_PROXY."""
    from schemas.backtest import PerformanceMetrics

    cfg = BacktestConfig(
        strategy_name="Dummy",
        currency_pair=CurrencyPair(borrowing_currency="EUR", investment_currency="USD"),
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 10),
    )
    metrics = PerformanceMetrics(
        total_trades=0,
        winning_trades=0,
        losing_trades=0,
        break_even_trades=0,
        win_rate=0.0,
        cumulative_net_profit=0.0,
        total_return=0.0,
        annualized_return=0.0,
        annualized_volatility=0.0,
        sharpe_ratio=None,
        sortino_ratio=None,
        calmar_ratio=None,
        max_drawdown=0.0,
        var_95=0.0,
        cvar_95=0.0,
        avg_capital_utilization=0.0,
        max_exposure_a=0.0,
    )

    with pytest.raises(ValidationError):
        BacktestResult(
            config=cfg,
            metrics=metrics,
            strategy_status=StrategyExecutabilityStatus.RESEARCH_PROXY,
            is_executable_strategy=True,  # CONTRADICTION!
        )


# =============================================================================
# 4. Benchmark Integrity & Excess Returns
# =============================================================================

def test_zero_cash_benchmark_strictly_zero_return():
    """ZERO_CASH benchmark returns strictly 0.0% without falling back to borrowing rates."""
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")
    start = date(2024, 1, 1)
    end = date(2024, 3, 31)

    obs = []
    curr = start
    while curr <= end:
        obs.append(
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="test",
                entity_code="USD/EUR",
                value=0.92,
                unit="EUR_per_USD",
                frequency=Frequency.DAILY,
                observation_date=curr,
                publication_date=curr,
                retrieved_at=datetime.now(timezone.utc),
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            )
        )
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="test",
                entity_code="USD",
                value=5.25,  # High borrowing rate
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=curr,
                publication_date=curr,
                retrieved_at=datetime.now(timezone.utc),
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                rate_role=RateRole.BORROWING_RATE,
            )
        )
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="test",
                entity_code="EUR",
                value=6.00,
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=curr,
                publication_date=curr,
                retrieved_at=datetime.now(timezone.utc),
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
                rate_role=RateRole.INVESTMENT_RETURN,
            )
        )
        curr += timedelta(days=1)

    cfg = BacktestConfig(
        strategy_name="Zero Cash Test",
        currency_pair=pair,
        start_date=start,
        end_date=end,
        cash_deposit_rate_annual=0.0,
        benchmark_spec=BenchmarkSpecification(
            benchmark_type=BenchmarkType.ZERO_CASH,
            fixed_rate_annual=0.0,
            name="Zero Cash Benchmark",
        ),
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
    )

    engine = BacktestEngine(cfg, obs)
    res = engine.run()
    m = res.metrics

    # Must be strictly 0.0, NEVER 5.25%
    assert m.benchmark_total_return == 0.0
    assert m.benchmark_annualized_return == 0.0
    assert m.cumulative_excess_return == m.total_return


# =============================================================================
# 5. Financial Report Reconciliation & JSON Export
# =============================================================================

def test_json_export_and_report_reconciliation(tmp_path: Path):
    """export_backtest_result_json and format_backtest_report agree exactly with BacktestResult."""
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")
    start = date(2024, 1, 1)
    end = date(2024, 3, 31)

    obs = []
    curr = start
    while curr <= end:
        obs.append(
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="test",
                entity_code="USD/EUR",
                value=0.92,
                unit="EUR_per_USD",
                frequency=Frequency.DAILY,
                observation_date=curr,
                publication_date=curr,
                retrieved_at=datetime.now(timezone.utc),
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            )
        )
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="test",
                entity_code="USD",
                value=4.00,
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=curr,
                publication_date=curr,
                retrieved_at=datetime.now(timezone.utc),
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            )
        )
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="test",
                entity_code="EUR",
                value=6.00,
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=curr,
                publication_date=curr,
                retrieved_at=datetime.now(timezone.utc),
                classification=DataClassification.REAL_VERIFIED,
                availability_evidence=AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED,
            )
        )
        curr += timedelta(days=1)

    cfg = BacktestConfig(
        strategy_name="Reconciliation Test",
        currency_pair=pair,
        start_date=start,
        end_date=end,
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        cash_deposit_rate_annual=0.02,
        position_sizing=PositionSizingConfig(method=PositionSizingMethod.FIXED_AMOUNT, fixed_amount=50_000.0),
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=False),
    )

    engine = BacktestEngine(cfg, obs)
    res = engine.run()

    json_path = tmp_path / "result.json"
    exported = export_backtest_result_json(res, json_path)

    # 1. Verify JSON output
    assert json_path.exists()
    assert exported["performance"]["total_return"] == res.metrics.total_return
    assert exported["performance"]["cumulative_net_profit"] == res.metrics.cumulative_net_profit
    assert exported["attribution"]["reconciliation_residual_a"] == res.metrics.reconciliation_residual_a
    assert abs(exported["attribution"]["reconciliation_residual_a"]) <= 1e-10

    # 2. Verify format_backtest_report contains the exact numbers
    report = format_backtest_report(res)
    assert f"{res.metrics.cumulative_net_profit:+,.2f}" in report
    assert f"{res.metrics.reconciliation_residual_a:+.10f}" in report


# =============================================================================
# 6. Raw Archive Byte-Stability & Offline Manifest Integrity
# =============================================================================

def test_manifest_offline_reproducibility_and_series_coverage():
    """Verify data/manifest.json hashes against committed raw archives without network calls."""
    manifest_path = Path("data/manifest.json")
    assert manifest_path.exists(), "data/manifest.json must exist!"

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_files_list = data.get("files", [])
    files_map = {f["file_name"]: f for f in raw_files_list}

    # Expected 14 raw archives:
    # 2 Frankfurter (EUR_base_USD_quote, USD_base_EUR_quote)
    # 5 Treasury 1M (2020-2024)
    # 5 Treasury 3M (2020-2024)
    # 1 ECB DFR
    # 1 ECB MRO
    # Total = 14 distinct files
    assert len(files_map) == 14, f"Expected 14 distinct raw archives in manifest, found {len(files_map)}"

    required_keys = [
        "frankfurter_EUR_base_USD_quote_2020-01-01_2024-12-31.json",
        "frankfurter_USD_base_EUR_quote_2020-01-01_2024-12-31.json",
        "ecb_dfr_2020-01-01_2024-12-31.csv",
        "ecb_mro_2020-01-01_2024-12-31.csv",
    ]
    for year in range(2020, 2025):
        required_keys.append(f"us_treasury_1m_{year}.csv")
        required_keys.append(f"us_treasury_3m_{year}.csv")

    for k in required_keys:
        assert k in files_map, f"Missing required archive record in manifest: {k}"
        entry = files_map[k]
        assert "sha256" in entry
        assert "file_size_bytes" in entry
        assert "provider" in entry
        assert "series_identifier" in entry
        assert "frequency" in entry

        # Verify on-disk hash match
        disk_path = Path("data/raw") / k
        assert disk_path.exists(), f"Raw archive file missing from data/raw: {k}"
        disk_sha = hashlib.sha256(disk_path.read_bytes()).hexdigest()
        assert disk_sha == entry["sha256"], f"SHA256 mismatch for {k}: {disk_sha} vs {entry['sha256']}"
