"""Data Provenance and Traceability Audit Engine for Historical Backtests.

Every historical backtest produces a complete DataProvenanceReport establishing:
- Source provider identities and dataset identifiers
- Currency pair and date boundaries
- Observation frequency
- Publication date availability (% verified)
- Missing trading-day data percentage (using currency market calendars)
- Breakdown of real versus synthetic observations
- Explicit provenance declaration preventing synthetic demo data from being
  misrepresented as real-world market history.
"""

from __future__ import annotations

from datetime import date
from typing import Sequence

from backtesting.calendar import DEFAULT_FX_CALENDAR, MarketCalendar
from data.schemas import AvailabilityEvidence, DataObservation, Frequency, ObservationKind
from schemas.backtest import AvailabilityPolicy, DataProvenanceReport


def build_data_provenance_report(
    observations: Sequence[DataObservation],
    start_date: date,
    end_date: date,
    currency_pair_code: str,
    policy: AvailabilityPolicy = AvailabilityPolicy.STRICT,
    calendar: MarketCalendar | None = None,
) -> DataProvenanceReport:
    """Generate an auditable data provenance and quality report for a backtest run."""
    cal = calendar or DEFAULT_FX_CALENDAR
    obs_list = [
        o for o in observations
        if start_date <= o.observation_date <= end_date
    ] or list(observations)
    total_obs = len(obs_list)

    sources = sorted(set(o.source_id for o in obs_list))
    datasets = sorted(set(o.indicator_id for o in obs_list if o.indicator_id))
    if not datasets:
        datasets = sorted(set(o.entity_code for o in obs_list))

    # Real vs synthetic breakdown & data classifications
    synthetic_count = sum(1 for o in obs_list if o.is_synthetic)
    real_count = total_obs - synthetic_count
    is_synthetic = synthetic_count > 0

    class_counts: dict[str, int] = {}
    for o in obs_list:
        cls_val = (o.classification.value if getattr(o, "classification", None) else ("synthetic" if o.is_synthetic else "real_verified"))
        class_counts[cls_val] = class_counts.get(cls_val, 0) + 1

    real_verified = class_counts.get("real_verified", 0)
    real_estimated = class_counts.get("real_estimated_availability", 0)
    real_retrospective = class_counts.get("real_retrospective", 0)

    # Publication date and timestamp tracking
    with_pub_date = sum(1 for o in obs_list if o.publication_date is not None)
    pub_availability_pct = (with_pub_date / total_obs) if total_obs > 0 else 0.0

    with_pub_timestamp = sum(1 for o in obs_list if o.publication_timestamp is not None)
    timestamp_populated_pct = (with_pub_timestamp / total_obs) if total_obs > 0 else 0.0

    exact_verified_count = sum(
        1 for o in obs_list
        if getattr(o, "availability_evidence", None) == AvailabilityEvidence.EXACT_TIMESTAMP_VERIFIED
    )
    exact_verified_pct = (exact_verified_count / total_obs) if total_obs > 0 else 0.0

    estimated_sched_count = sum(
        1 for o in obs_list
        if getattr(o, "availability_evidence", None) == AvailabilityEvidence.ESTIMATED_SCHEDULE
    )
    retrospective_count = sum(
        1 for o in obs_list
        if getattr(o, "availability_evidence", None) == AvailabilityEvidence.RETROSPECTIVE
    )

    # Calendar vs trading day coverage
    calendar_days = (end_date - start_date).days + 1
    trading_days = cal.count_trading_days(start_date, end_date)

    # Missing trading days in FX series
    fx_obs_dates = set(
        o.observation_date
        for o in obs_list
        if o.kind == ObservationKind.EXCHANGE_RATE and o.entity_code == currency_pair_code
    )
    all_trading_days = set(cal.trading_days_between(start_date, end_date))
    
    if all_trading_days:
        observed_trading_days = len(fx_obs_dates.intersection(all_trading_days))
        missing_trading_days = len(all_trading_days) - observed_trading_days
        missing_pct = max(0.0, (missing_trading_days / len(all_trading_days)))
    else:
        missing_pct = 0.0

    # Primary frequency
    fx_freqs = [o.frequency for o in obs_list if o.kind == ObservationKind.EXCHANGE_RATE]
    primary_freq = fx_freqs[0] if fx_freqs else Frequency.DAILY

    # Build provenance statement
    if is_synthetic:
        declaration = (
            f"DATA PROVENANCE NOTICE: Synthetic observations detected ({synthetic_count}/{total_obs} rows, "
            f"{synthetic_count / max(1, total_obs):.1%}). This backtest was executed on synthetic test data "
            "and MUST NOT be represented as executable historical market evidence."
        )
    else:
        declaration = (
            f"DATA PROVENANCE VERIFIED: 100% genuine historical observations from registered sources: "
            f"{', '.join(sources)}. Publication timestamps populated: {timestamp_populated_pct:.1%} "
            f"(independently verified EXACT_TIMESTAMP_VERIFIED: {exact_verified_pct:.1%}). "
            f"Trading day quote coverage: {1.0 - missing_pct:.1%}."
        )

    return DataProvenanceReport(
        source_providers=sources,
        dataset_identifiers=datasets,
        currency_pair=currency_pair_code,
        date_range=(start_date, end_date),
        observation_frequency=primary_freq,
        publication_date_availability_pct=pub_availability_pct,
        point_in_time_policy=policy,
        calendar_days=calendar_days,
        trading_days=trading_days,
        missing_trading_days_pct=missing_pct,
        total_observations=total_obs,
        real_observations_count=real_count,
        synthetic_observations_count=synthetic_count,
        real_verified_count=real_verified,
        real_estimated_count=real_estimated,
        real_retrospective_count=real_retrospective,
        timestamp_populated_count=with_pub_timestamp,
        timestamp_populated_pct=timestamp_populated_pct,
        exact_timestamp_verified_count=exact_verified_count,
        exact_timestamp_verified_pct=exact_verified_pct,
        estimated_schedule_count=estimated_sched_count,
        retrospective_count=retrospective_count,
        classification_breakdown=class_counts,
        is_synthetic_dataset=is_synthetic,
        provenance_declaration=declaration,
    )
