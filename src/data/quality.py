"""Data-quality engine.

Validates a batch of observations BEFORE persistence. Rules:

- Flags never delete data: questionable observations keep their original
  source values and carry ``QualityFlag`` markers for review.
- Missing/non-finite values are flagged; the caller decides what to do.
- Outliers are flagged via a robust median/MAD z-score, never dropped.
- Date, frequency, unit and currency checks are conventional and
  explicit; anything the engine cannot decide is left unflagged rather
  than guessed.

The engine is pure: no database, no network, fully deterministic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from data.schemas import DataObservation, Frequency, IndicatorInfo, ObservationKind, QualityFlag


@dataclass
class QualityReport:
    """Summary of one validation pass (nothing is mutated silently)."""

    total: int = 0
    flagged: int = 0
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, flag: QualityFlag) -> None:
        self.counts[flag.value] = self.counts.get(flag.value, 0) + 1

    @property
    def is_clean(self) -> bool:
        return self.flagged == 0


def _flag(obs: DataObservation, flag: QualityFlag, report: QualityReport) -> None:
    if flag not in obs.quality_flags:
        obs.quality_flags.append(flag)
        report.add(flag)
        report.flagged += 1


def validate_batch(
    observations: list[DataObservation],
    indicators: dict[tuple[str, str], IndicatorInfo] | None = None,
    today: date | None = None,
    fx_jump_log_threshold: float = math.log(1.5),
    outlier_mad_z: float = 6.0,
) -> tuple[list[DataObservation], QualityReport]:
    """Validate and flag a batch of observations.

    Args:
        observations: Batch as returned by an adapter (mutated: flags added).
        indicators: Catalog entries keyed by ``(source_id, indicator_id)``,
            used for unit and frequency cross-checks.
        today: Reference "current date" (dependency-injected for tests).
        fx_jump_log_threshold: For daily FX pairs: flag when
            ``|ln(r_t / r_{t-1})|`` exceeds this (default ~40.5 % move).
        outlier_mad_z: Robust z-score beyond which a point is a suspect
            outlier (applies to series with >= 8 observations).

    Returns:
        (same observation list, QualityReport).
    """
    if today is None:
        today = date.today()
    report = QualityReport(total=len(observations))
    seen_keys: set[tuple] = set()
    series: dict[tuple[str, str | None, Frequency], list[DataObservation]] = {}
    series_frequencies: dict[tuple[str, str | None], set[Frequency]] = {}

    for obs in observations:
        # --- missing / impossible values --------------------------------
        if obs.value is None or not math.isfinite(obs.value):
            _flag(obs, QualityFlag.MISSING_VALUE, report)
            continue  # value-level math below needs a finite value

        # --- dates -------------------------------------------------------
        if obs.observation_date > today:
            _flag(obs, QualityFlag.FUTURE_DATE, report)

        # --- quoted rates must be positive --------------------------------
        if obs.kind in (ObservationKind.EXCHANGE_RATE, ObservationKind.INTEREST_RATE) and obs.value <= 0:
            _flag(obs, QualityFlag.NEGATIVE_RATE, report)

        # --- currency validity for FX pairs -------------------------------
        if obs.kind == ObservationKind.EXCHANGE_RATE:
            parts = obs.entity_code.split("/")
            if len(parts) != 2 or not all(len(p) == 3 and p.isalpha() for p in parts):
                _flag(obs, QualityFlag.INVALID_CURRENCY, report)

        # --- declared-catalog (unit / frequency) cross-checks ---------------
        if indicators is not None and obs.indicator_id is not None:
            declared = indicators.get((obs.source_id, obs.indicator_id))
            if declared is not None:
                if declared.unit != obs.unit:
                    _flag(obs, QualityFlag.UNIT_MISMATCH, report)
                if declared.frequency != obs.frequency:
                    _flag(obs, QualityFlag.FREQUENCY_INCONSISTENT, report)

        # --- duplicates within the batch (same natural key) ------------------
        natural_key = (
            obs.source_id,
            obs.kind,
            obs.entity_code,
            obs.indicator_id,
            obs.frequency,
            obs.observation_date,
        )
        if natural_key in seen_keys:
            _flag(obs, QualityFlag.DUPLICATE_IN_BATCH, report)
        else:
            seen_keys.add(natural_key)

        # --- series bookkeeping (order, jumps, outliers, mixed frequency) ----
        series_key = (obs.entity_code, obs.indicator_id, obs.frequency)
        series.setdefault(series_key, []).append(obs)
        series_base = (obs.entity_code, obs.indicator_id)
        series_frequencies.setdefault(series_base, set()).add(obs.frequency)

    # --- frequency consistency: a (entity, indicator) series must not mix----
    for (entity, indicator), freqs in series_frequencies.items():
        if len(freqs) > 1:
            for f in freqs:
                for o in series.get((entity, indicator, f), []):
                    _flag(o, QualityFlag.FREQUENCY_INCONSISTENT, report)

    # --- order consistency: batch should arrive chronologically -------------
    for entries in series.values():
        dates = [o.observation_date for o in entries]
        if any(b < a for a, b in zip(dates, dates[1:])):
            for o in entries:
                _flag(o, QualityFlag.ORDER_INCONSISTENT, report)

    # --- FX jumps over consecutive observations -----------------------------
    for (entity, _indicator, _freq), entries in series.items():
        if "/" not in entity:
            continue  # jump rule applies to quoted FX pairs only
        prev_value: float | None = None
        prev_date: date | None = None
        for o in entries:
            if prev_value is not None and prev_date is not None and o.observation_date > prev_date:
                log_change = abs(math.log(o.value / prev_value))
                if log_change > fx_jump_log_threshold:
                    _flag(o, QualityFlag.SUSPICIOUS_JUMP, report)
            prev_value, prev_date = o.value, o.observation_date

    # --- outliers: robust median/MAD z-score (never removed) -----------------
    for entries in series.values():
        values = np.array([o.value for o in entries], dtype=float)
        if values.size >= 8:
            median = float(np.median(values))
            mad = float(np.median(np.abs(values - median)))
            if mad > 0:
                z_scores = 0.6745 * (values - median) / mad
                for o, z in zip(entries, z_scores):
                    if abs(z) > outlier_mad_z:
                        _flag(o, QualityFlag.OUTLIER_SUSPECT, report)

    return observations, report


def summarize(report: QualityReport) -> dict[str, Any]:
    """Compact dict summary for run logs."""
    return {"total": report.total, "flagged": report.flagged, "flags": dict(report.counts)}
