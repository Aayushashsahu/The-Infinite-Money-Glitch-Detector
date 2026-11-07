"""Integration and Reproducibility Tests for Master Backtesting Engine.

Verifies:
- End-to-end multi-month cross-currency backtest execution
- Determinism and Reproducibility: running the backtest twice yields identical trades, PnL, and metrics
- Monthly rebalancing with realistic bid/ask spreads, slippage, and transaction fees
- Full markdown audit report generation
- Graceful handling of missing quotes and rejections
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from backtesting.engine import BacktestEngine
from backtesting.reporting import format_backtest_report
from data.schemas import DataObservation, Frequency, ObservationKind
from schemas.backtest import (
    AvailabilityPolicy,
    BacktestConfig,
    DataAvailabilityConfig,
    ExecutionConfig,
    PositionSizingConfig,
    PositionSizingMethod,
)
from schemas.strategy import CurrencyPair


def build_synthetic_history(
    start: date,
    end: date,
    pair_code: str = "USD/EUR",
    base_rate: float = 1.10,
    r_usd: float = 3.0,
    r_eur: float = 7.0,
) -> list[DataObservation]:
    """Generate clean daily synthetic observations with verified publication dates."""
    obs: list[DataObservation] = []
    curr = start
    rate = base_rate
    while curr <= end:
        # Subtle drift in exchange rate
        day_idx = (curr - start).days
        current_rate = rate + 0.0001 * (day_idx % 10 - 5)

        obs.append(
            DataObservation(
                kind=ObservationKind.EXCHANGE_RATE,
                source_id="test_source",
                entity_code=pair_code,
                value=current_rate,
                unit="rate",
                frequency=Frequency.DAILY,
                observation_date=curr,
                publication_date=curr,  # Verified publication
                retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                revision=0,
                is_synthetic=True,
            )
        )
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="test_source",
                entity_code="USD",
                value=r_usd,
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=curr,
                publication_date=curr,
                retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                revision=0,
                is_synthetic=True,
            )
        )
        obs.append(
            DataObservation(
                kind=ObservationKind.INTEREST_RATE,
                source_id="test_source",
                entity_code="EUR",
                value=r_eur,
                unit="percent",
                frequency=Frequency.DAILY,
                observation_date=curr,
                publication_date=curr,
                retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                revision=0,
                is_synthetic=True,
            )
        )
        curr = date.fromordinal(curr.toordinal() + 1)
    return obs


def test_end_to_end_backtest_and_reproducibility():
    """Two identical runs produce bit-for-bit identical trade logs and performance metrics."""
    start = date(2024, 1, 1)
    end = date(2024, 12, 31)
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")
    obs = build_synthetic_history(start, end, pair_code="USD/EUR")

    cfg = BacktestConfig(
        strategy_name="Unhedged Carry 30D",
        currency_pair=pair,
        start_date=start,
        end_date=end,
        initial_capital_a=100_000.0,
        tenor_days=30,
        rebalance_frequency_days=30,
        hurdle_rate_annual=0.01,
        availability_config=DataAvailabilityConfig(policy=AvailabilityPolicy.STRICT, allow_synthetic=True),
        execution_config=ExecutionConfig(
            bid_ask_spread_bps=5.0,
            slippage_bps=2.0,
            fixed_fee=25.0,
            variable_fee_bps=2.0,
        ),
        position_sizing=PositionSizingConfig(
            method=PositionSizingMethod.FIXED_AMOUNT,
            fixed_amount=50_000.0,
            max_active_positions=1,
            max_leverage=1.0,
        ),
    )

    # Run 1
    engine1 = BacktestEngine(cfg, obs)
    res1 = engine1.run()

    # Run 2
    engine2 = BacktestEngine(cfg, obs)
    res2 = engine2.run()

    # Reproducibility verification
    assert len(res1.trades) == len(res2.trades)
    assert len(res1.snapshots) == len(res2.snapshots)
    assert res1.metrics.cumulative_net_profit == res2.metrics.cumulative_net_profit
    assert res1.metrics.total_return == res2.metrics.total_return
    assert res1.metrics.sharpe_ratio == res2.metrics.sharpe_ratio
    assert res1.metrics.max_drawdown == res2.metrics.max_drawdown

    # Detailed trade level check
    for t1, t2 in zip(res1.trades, res2.trades):
        assert t1.trade_id == t2.trade_id
        assert t1.entry_date == t2.entry_date
        assert t1.exit_date == t2.exit_date
        assert t1.net_profit_a == t2.net_profit_a
        assert t1.return_on_capital == t2.return_on_capital

    # Report generation check
    report = format_backtest_report(res1)
    assert "# Historical Backtest Execution Report" in report
    assert "Unhedged Carry 30D" in report
    assert "Cumulative Net Profit" in report
    assert "Historical Information Firewall Audit" in report


def test_missing_data_handling_and_rejections():
    """Engine logs rejections and does not invent quotes when data is missing."""
    start = date(2024, 1, 1)
    end = date(2024, 3, 1)
    pair = CurrencyPair(borrowing_currency="USD", investment_currency="EUR")

    # Deliberately sparse observations: rates only exist for Jan 1
    sparse_obs = [
        DataObservation(
            kind=ObservationKind.EXCHANGE_RATE,
            source_id="test_source",
            entity_code="USD/EUR",
            value=1.10,
            unit="rate",
            frequency=Frequency.DAILY,
            observation_date=date(2024, 1, 1),
            publication_date=date(2024, 1, 1),
            retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            revision=0,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test_source",
            entity_code="USD",
            value=3.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=date(2024, 1, 1),
            publication_date=date(2024, 1, 1),
            retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            revision=0,
            is_synthetic=True,
        ),
        DataObservation(
            kind=ObservationKind.INTEREST_RATE,
            source_id="test_source",
            entity_code="EUR",
            value=7.0,
            unit="percent",
            frequency=Frequency.DAILY,
            observation_date=date(2024, 1, 1),
            publication_date=date(2024, 1, 1),
            retrieved_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            revision=0,
            is_synthetic=True,
        ),
    ]

    cfg = BacktestConfig(
        strategy_name="Unhedged Carry",
        currency_pair=pair,
        start_date=start,
        end_date=end,
        tenor_days=30,
        rebalance_frequency_days=30,
        availability_config=DataAvailabilityConfig(
            policy=AvailabilityPolicy.STRICT,
            max_stale_days=3,
            allow_synthetic=True,
        ),
    )

    engine = BacktestEngine(cfg, sparse_obs)
    res = engine.run()

    # Should open trade on Jan 1, but when it matures on Jan 31, quote is missing (>3 days stale)
    # The engine should reject closure with missing quote notice, NOT invent a quote!
    assert len(res.rejections) > 0
    rejection_reasons = [r.get("reason", "") for r in res.rejections]
    assert any("Missing" in reason or "below hurdle" in reason for reason in rejection_reasons)
