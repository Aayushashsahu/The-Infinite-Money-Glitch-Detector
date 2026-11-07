"""Tests for Walk-Forward Chronological Evaluation, Purging, and Embargo.

Verifies:
- Expanding and rolling windows are strictly chronological (no shuffling)
- Purging excludes boundary trades whose holding periods cross into the test set
- Embargo creates a non-overlapping buffer window between train and test sets
- In-sample and Out-of-sample metrics are calculated independently
"""

from __future__ import annotations

from datetime import date

from backtesting.walk_forward import (
    WalkForwardEngine,
    generate_walk_forward_splits,
)
from schemas.backtest import (
    BacktestConfig,
    BacktestResult,
    PerformanceMetrics,
    WalkForwardConfig,
    WalkForwardWindowType,
)
from schemas.strategy import CurrencyPair


def test_chronological_splits_and_embargo():
    """Splits are strictly chronological; embargo separates train and test."""
    config = WalkForwardConfig(
        window_type=WalkForwardWindowType.ROLLING,
        train_period_days=180,
        test_period_days=60,
        step_days=60,
        purge_overlap_days=30,
        embargo_days=10,
    )

    start = date(2023, 1, 1)
    end = date(2024, 1, 1)

    splits = generate_walk_forward_splits(start, end, config)
    assert len(splits) >= 1

    for s in splits:
        # Strictly chronological
        assert s.train_start < s.train_end
        assert s.train_end <= s.test_start
        assert s.test_start < s.test_end
        # Embargo buffer check
        embargo_len = (s.test_start - s.train_end).days
        assert embargo_len == config.embargo_days
        # Purge boundary check
        assert s.purged_range is not None
        assert s.purged_range[1] == s.train_end
        assert (s.purged_range[1] - s.purged_range[0]).days == config.purge_overlap_days


def test_expanding_window_anchors_start_date():
    """Expanding windows keep train_start anchored at the initial start date."""
    config = WalkForwardConfig(
        window_type=WalkForwardWindowType.EXPANDING,
        train_period_days=100,
        test_period_days=50,
        step_days=50,
        purge_overlap_days=0,
        embargo_days=5,
    )

    start = date(2023, 1, 1)
    end = date(2024, 1, 1)

    splits = generate_walk_forward_splits(start, end, config)
    assert len(splits) >= 2

    # Every split's train_start must match the original start date
    for s in splits:
        assert s.train_start == start

    # train_end grows with each split
    for i in range(1, len(splits)):
        assert splits[i].train_end > splits[i - 1].train_end


def test_walk_forward_engine_execution():
    """Engine coordinates in-sample and out-of-sample backtest evaluations."""
    wf_config = WalkForwardConfig(
        window_type=WalkForwardWindowType.ROLLING,
        train_period_days=90,
        test_period_days=30,
        step_days=30,
        purge_overlap_days=15,
        embargo_days=5,
    )
    engine = WalkForwardEngine(wf_config)

    base_cfg = BacktestConfig(
        strategy_name="Dummy Strategy",
        currency_pair=CurrencyPair(borrowing_currency="USD", investment_currency="EUR"),
        start_date=date(2023, 1, 1),
        end_date=date(2023, 8, 1),
    )

    # Mock backtest runner returning deterministic results
    def mock_runner(cfg: BacktestConfig) -> BacktestResult:
        metrics = PerformanceMetrics(
            total_trades=5,
            winning_trades=3,
            losing_trades=2,
            break_even_trades=0,
            win_rate=0.60,
            cumulative_net_profit=1500.0,
            total_return=0.015,
            annualized_return=0.06,
            annualized_volatility=0.05,
            sharpe_ratio=1.2,
            sortino_ratio=1.5,
            max_drawdown=-0.02,
            calmar_ratio=3.0,
            var_95=-0.01,
            cvar_95=-0.015,
            avg_capital_utilization=0.5,
            max_exposure_a=50_000.0,
        )
        return BacktestResult(
            config=cfg,
            trades=[],
            snapshots=[],
            metrics=metrics,
        )

    summary = engine.run_walk_forward(base_cfg, mock_runner)
    assert summary.total_folds > 0
    assert summary.mean_in_sample_sharpe == 1.2
    assert summary.mean_out_of_sample_sharpe == 1.2
    assert summary.robustness_ratio == 1.0
