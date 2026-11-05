"""Walk-Forward and Out-of-Sample Framework with Purging and Embargo Rules.

Guarantees:
- Zero future-information leakage: strictly chronological splits.
- Never randomly shuffles financial time series.
- Supports expanding and rolling train windows.
- Purging: excludes trades near train boundaries whose holding tenors overlap into the test set.
- Embargo: inserts a buffer period between train and test windows to prevent autocorrelation leakage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Sequence

from schemas.backtest import (
    BacktestConfig,
    BacktestResult,
    PerformanceMetrics,
    WalkForwardConfig,
    WalkForwardSplit,
    WalkForwardWindowType,
)


@dataclass(frozen=True)
class WalkForwardFoldResult:
    """Outcome of one walk-forward train/test fold."""

    split: WalkForwardSplit
    in_sample_metrics: PerformanceMetrics
    out_of_sample_metrics: PerformanceMetrics
    in_sample_trades_count: int
    out_of_sample_trades_count: int
    purged_trades_count: int


@dataclass(frozen=True)
class WalkForwardSummary:
    """Aggregate report across all walk-forward evaluation splits."""

    config: WalkForwardConfig
    folds: list[WalkForwardFoldResult]
    total_folds: int
    mean_in_sample_sharpe: float | None
    mean_out_of_sample_sharpe: float | None
    mean_in_sample_return: float
    mean_out_of_sample_return: float
    robustness_ratio: float | None  # mean OOS return / mean IS return


def generate_walk_forward_splits(
    start_date: date,
    end_date: date,
    config: WalkForwardConfig,
) -> list[WalkForwardSplit]:
    """Generate chronological train/val/test splits with explicit purging and embargo bounds."""
    if start_date >= end_date:
        raise ValueError(f"start_date ({start_date}) must precede end_date ({end_date})")

    total_days = (end_date - start_date).days
    required_min_days = config.train_period_days + config.embargo_days + config.test_period_days
    if total_days < required_min_days:
        raise ValueError(
            f"Dataset length ({total_days} days) is shorter than required minimum for one split "
            f"({required_min_days} days)."
        )

    splits: list[WalkForwardSplit] = []
    current_train_start = start_date
    split_index = 0

    while True:
        if config.window_type == WalkForwardWindowType.ROLLING:
            train_start = current_train_start
        else:  # EXPANDING
            train_start = start_date

        train_end = current_train_start + timedelta(days=config.train_period_days)

        # Purge boundary: last N days of training where trade holding period spills over
        purge_start = max(train_start, train_end - timedelta(days=config.purge_overlap_days))
        purged_range = (purge_start, train_end) if config.purge_overlap_days > 0 else None

        # Embargo buffer
        embargo_start = train_end
        embargo_end = train_end + timedelta(days=config.embargo_days)
        embargo_range = (embargo_start, embargo_end) if config.embargo_days > 0 else None

        # Out-of-sample test window
        test_start = embargo_end
        test_end = test_start + timedelta(days=config.test_period_days)

        if test_end > end_date:
            break

        split = WalkForwardSplit(
            split_index=split_index,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            purged_range=purged_range,
            embargo_range=embargo_range,
        )
        splits.append(split)

        split_index += 1
        current_train_start += timedelta(days=config.step_days)

    return splits


class WalkForwardEngine:
    """Executes walk-forward evaluations using a backtest runner function."""

    def __init__(self, config: WalkForwardConfig):
        self.config = config

    def run_walk_forward(
        self,
        base_backtest_config: BacktestConfig,
        run_backtest_fn: Callable[[BacktestConfig], BacktestResult],
    ) -> WalkForwardSummary:
        """Run chronological in-sample training and out-of-sample evaluation across all splits."""
        splits = generate_walk_forward_splits(
            start_date=base_backtest_config.start_date,
            end_date=base_backtest_config.end_date,
            config=self.config,
        )

        folds: list[WalkForwardFoldResult] = []

        for split in splits:
            # 1. In-Sample Run (train)
            effective_train_end = split.train_end
            if split.purged_range is not None:
                effective_train_end = split.purged_range[0]

            is_config = base_backtest_config.model_copy(
                update={
                    "start_date": split.train_start,
                    "end_date": effective_train_end,
                }
            )
            is_result = run_backtest_fn(is_config)

            # Count purged trades that would have entered in purged range
            purged_count = 0
            if split.purged_range is not None:
                purged_cfg = base_backtest_config.model_copy(
                    update={
                        "start_date": split.purged_range[0],
                        "end_date": split.purged_range[1],
                    }
                )
                purged_res = run_backtest_fn(purged_cfg)
                purged_count = len(purged_res.trades)

            # 2. Out-of-Sample Run (test)
            oos_config = base_backtest_config.model_copy(
                update={
                    "start_date": split.test_start,
                    "end_date": split.test_end,
                }
            )
            oos_result = run_backtest_fn(oos_config)

            folds.append(
                WalkForwardFoldResult(
                    split=split,
                    in_sample_metrics=is_result.metrics,
                    out_of_sample_metrics=oos_result.metrics,
                    in_sample_trades_count=len(is_result.trades),
                    out_of_sample_trades_count=len(oos_result.trades),
                    purged_trades_count=purged_count,
                )
            )

        # Summary aggregates
        is_sharpes = [f.in_sample_metrics.sharpe_ratio for f in folds if f.in_sample_metrics.sharpe_ratio is not None]
        oos_sharpes = [f.out_of_sample_metrics.sharpe_ratio for f in folds if f.out_of_sample_metrics.sharpe_ratio is not None]

        is_returns = [f.in_sample_metrics.total_return for f in folds]
        oos_returns = [f.out_of_sample_metrics.total_return for f in folds]

        mean_is_sh = float(sum(is_sharpes) / len(is_sharpes)) if is_sharpes else None
        mean_oos_sh = float(sum(oos_sharpes) / len(oos_sharpes)) if oos_sharpes else None

        mean_is_ret = float(sum(is_returns) / len(is_returns)) if is_returns else 0.0
        mean_oos_ret = float(sum(oos_returns) / len(oos_returns)) if oos_returns else 0.0

        robustness = (mean_oos_ret / mean_is_ret) if mean_is_ret != 0 else None

        return WalkForwardSummary(
            config=self.config,
            folds=folds,
            total_folds=len(folds),
            mean_in_sample_sharpe=mean_is_sh,
            mean_out_of_sample_sharpe=mean_oos_sh,
            mean_in_sample_return=mean_is_ret,
            mean_out_of_sample_return=mean_oos_ret,
            robustness_ratio=robustness,
        )
