from __future__ import annotations

import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from evcf.data.acn_jpl_15min import AggregationPolicy, aggregate_station_15min
from evcf.data.acn_jpl_cleaning import (
    CleaningPolicy,
    clean_quarantined_session,
    clean_session,
)
from evcf.data.acn_jpl_issue_snapshots import SnapshotPolicy, build_issue_snapshots
from evcf.data.acn_jpl_month_config import jpl_month_config
from evcf.data.acn_jpl_trajectory_quarantine import (
    FULL_SESSION_QUARANTINE,
    NO_QUARANTINE,
    TRAJECTORY_QUARANTINE,
    build_trajectory_quarantine_audit,
    quarantine_record_for_analysis,
)


def _stamp(value: datetime) -> str:
    return format_datetime(value.astimezone(timezone.utc), usegmt=True)


def _record(*, synchronized: bool = True, invalid_bounds: bool = False) -> dict[str, object]:
    start = datetime(2019, 11, 3, 8, 30, tzinfo=timezone.utc)
    current_times = [start, start + timedelta(hours=1), start + timedelta(seconds=4)]
    pilot_times = list(current_times)
    if not synchronized:
        pilot_times = [start, start + timedelta(seconds=4), start + timedelta(seconds=8)]
    return {
        "_id": "private-object",
        "sessionID": "private-session",
        "connectionTime": _stamp(start - timedelta(minutes=5)),
        "disconnectTime": _stamp(
            start - timedelta(minutes=10)
            if invalid_bounds
            else start + timedelta(hours=2)
        ),
        "doneChargingTime": _stamp(start + timedelta(hours=1, minutes=30)),
        "siteID": "jpl",
        "stationID": "private-station",
        "userInputs": [
            {
                "modifiedAt": _stamp(start - timedelta(minutes=1)),
                "requestedDeparture": _stamp(start + timedelta(hours=3)),
                "kWhRequested": 8.0,
            }
        ],
        "chargingCurrent": {
            "timestamps": [_stamp(value) for value in current_times],
            "current": [16.0, 16.0, 16.0],
        },
        "pilotSignal": {
            "timestamps": [_stamp(value) for value in pilot_times],
            "pilot": [16.0, 16.0, 16.0],
        },
    }


def test_synchronized_utc_nonmonotonic_trajectory_is_quarantined_without_raw_repair() -> None:
    raw = _record()
    before = copy.deepcopy(raw)

    decision, projected = quarantine_record_for_analysis(raw)

    assert decision.action == TRAJECTORY_QUARANTINE
    assert decision.current_nonmonotonic_pairs == 1
    assert decision.pilot_nonmonotonic_pairs == 1
    assert decision.synchronized_transition_count == 1
    assert decision.synchronized_backward_seconds == (3596,)
    assert decision.synchronized_raw_ordinals == (2,)
    assert decision.metadata_bounds_valid is True
    assert projected is not None
    assert projected["connectionTime"] == raw["connectionTime"]
    assert projected["disconnectTime"] == raw["disconnectTime"]
    assert projected["userInputs"] == raw["userInputs"]
    assert projected["chargingCurrent"] == {"timestamps": [], "current": []}
    assert projected["pilotSignal"] == {"timestamps": [], "pilot": []}
    assert raw == before


def test_unsynchronized_nonmonotonicity_is_not_silently_quarantined() -> None:
    raw = _record(synchronized=False)

    decision, projected = quarantine_record_for_analysis(raw)

    assert decision.action == NO_QUARANTINE
    assert decision.current_nonmonotonic_pairs == 1
    assert decision.pilot_nonmonotonic_pairs == 0
    assert projected is raw


def test_synchronized_anomaly_with_invalid_bounds_requires_full_session_quarantine() -> None:
    raw = _record(invalid_bounds=True)

    decision, projected = quarantine_record_for_analysis(raw)

    assert decision.action == FULL_SESSION_QUARANTINE
    assert decision.metadata_bounds_valid is False
    assert projected is None


def test_synchronized_anomaly_with_metadata_bound_mismatch_requires_full_quarantine() -> None:
    raw = _record()
    metadata = copy.deepcopy(raw)
    metadata["disconnectTime"] = _stamp(
        datetime(2019, 11, 3, 11, 0, tzinfo=timezone.utc)
    )

    decision, projected = quarantine_record_for_analysis(
        raw,
        expected_metadata=metadata,
    )

    assert decision.action == FULL_SESSION_QUARANTINE
    assert decision.metadata_bounds_valid is False
    assert projected is None

    missing_decision, missing_projection = quarantine_record_for_analysis(
        raw,
        expected_metadata=None,
    )
    assert missing_decision.action == FULL_SESSION_QUARANTINE
    assert missing_projection is None


def test_legal_dst_fold_is_monotonic_in_utc_and_is_not_quarantined() -> None:
    raw = _record()
    utc_times = [
        datetime(2019, 11, 3, 8, 59, 56, tzinfo=timezone.utc),
        datetime(2019, 11, 3, 9, 0, tzinfo=timezone.utc),
        datetime(2019, 11, 3, 9, 0, 4, tzinfo=timezone.utc),
    ]
    raw["chargingCurrent"] = {
        "timestamps": [_stamp(value) for value in utc_times],
        "current": [16.0] * 3,
    }
    raw["pilotSignal"] = {
        "timestamps": [_stamp(value) for value in utc_times],
        "pilot": [16.0] * 3,
    }

    decision, projected = quarantine_record_for_analysis(raw)

    assert decision.action == NO_QUARANTINE
    assert projected is raw


def test_quarantined_trajectory_retains_connected_denominator_but_never_becomes_zero() -> None:
    start = datetime(2019, 11, 3, 8, 30, tzinfo=timezone.utc)
    raw = _record()
    decision, projected = quarantine_record_for_analysis(raw)
    assert decision.action == TRAJECTORY_QUARANTINE
    assert projected is not None

    normal = copy.deepcopy(raw)
    normal["chargingCurrent"] = {"timestamps": [_stamp(start)], "current": [16.0]}
    normal["pilotSignal"] = {"timestamps": [_stamp(start)], "pilot": [16.0]}
    policy = CleaningPolicy(current_mode_s=300, pilot_mode_s=300, locf_cap_s=900)
    quarantined = clean_quarantined_session(raw, session_index=0, policy=policy)
    observed = clean_session(normal, session_index=1, policy=policy)

    result = aggregate_station_15min(
        (quarantined, observed),
        start_utc=start,
        end_utc=start + timedelta(minutes=15),
        policy=AggregationPolicy(
            max_hold_seconds=900,
            pilot_max_hold_seconds=900,
        ),
        grid_policy="continuous_physical_utc",
    )

    row = result.rows[0]
    assert row["connected_session_count"] == 2
    assert row["observed_coverage_ratio"] == 0.5
    assert row["pilot_observed_coverage_ratio"] == 0.5
    assert row["station_current_mean_a"] is None
    assert row["pilot_sum_a"] is None
    assert quarantined.current.timestamps_utc_s == ()
    assert quarantined.pilot.timestamps_utc_s == ()
    assert quarantined.connection_utc_s < quarantined.disconnect_utc_s
    assert len(quarantined.user_inputs) == 1
    assert quarantined.current.audit.raw_samples == 3
    assert quarantined.pilot.audit.raw_samples == 3
    assert quarantined.current.main_integral.eligible_seconds == 7500
    assert quarantined.current.main_integral.observed_seconds == 0
    assert quarantined.pilot.main_integral.observed_seconds == 0


def test_month_audit_accepts_only_the_one_frozen_november_signature() -> None:
    decision, _ = quarantine_record_for_analysis(_record())
    november = jpl_month_config("2019-11")

    accepted = build_trajectory_quarantine_audit(
        november,
        (decision,),
        denominator_sessions=1354,
    )

    assert accepted.approved is True
    assert accepted.trajectory_quarantine_count == 1
    assert accepted.full_session_quarantine_count == 0
    assert accepted.quarantined_current_nonmonotonic_pairs == 1
    assert accepted.quarantined_pilot_nonmonotonic_pairs == 1
    assert accepted.public_dict()["trajectory_quarantine_rate"] == 1 / 1354

    assert not build_trajectory_quarantine_audit(
        jpl_month_config("2019-02"),
        (decision,),
        denominator_sessions=1354,
    ).approved
    assert not build_trajectory_quarantine_audit(
        november,
        (decision, decision),
        denominator_sessions=1354,
    ).approved
    assert not build_trajectory_quarantine_audit(
        november,
        (replace(decision, synchronized_transition_count=2),),
        denominator_sessions=1354,
    ).approved
    assert not build_trajectory_quarantine_audit(
        november,
        (replace(decision, synchronized_backward_seconds=(3600,)),),
        denominator_sessions=1354,
    ).approved


def test_quarantine_keeps_raw_sample_and_duplicate_audit_denominators() -> None:
    raw = _record()
    for field_name, value_name in (
        ("chargingCurrent", "current"),
        ("pilotSignal", "pilot"),
    ):
        series = raw[field_name]
        assert isinstance(series, dict)
        series["timestamps"].append(series["timestamps"][-1])
        series[value_name].append(series[value_name][-1])

    cleaned = clean_quarantined_session(
        raw,
        session_index=0,
        policy=CleaningPolicy(current_mode_s=4, pilot_mode_s=4),
    )

    assert cleaned.current.audit.raw_samples == 4
    assert cleaned.pilot.audit.raw_samples == 4
    assert cleaned.current.audit.exact_duplicate_extras == 1
    assert cleaned.pilot.audit.exact_duplicate_extras == 1
    assert cleaned.current.main_integral.observed_seconds == 0
    assert cleaned.pilot.main_integral.observed_seconds == 0


def test_m3_retains_connected_quarantine_row_with_missing_trajectory_features() -> None:
    raw = _record()
    policy = CleaningPolicy(current_mode_s=4, pilot_mode_s=4)
    cleaned = clean_quarantined_session(raw, session_index=0, policy=policy)
    start = datetime.fromtimestamp(cleaned.connection_utc_s, timezone.utc) - timedelta(
        minutes=30
    )
    end = datetime.fromtimestamp(cleaned.disconnect_utc_s, timezone.utc) + timedelta(
        minutes=30
    )
    bin_count = int((end - start).total_seconds() // 900)
    station_rows = [
        {
            "timestamp_utc": (start + timedelta(minutes=15 * index)).isoformat(),
            "station_current_mean_a": 1.0,
            "valid_bin_90": True,
        }
        for index in range(bin_count)
    ]

    snapshots = build_issue_snapshots(
        station_rows,
        (cleaned,),
        start_utc=start,
        end_utc=end,
        policy=SnapshotPolicy(
            lookback_minutes=15,
            horizons_minutes=(15,),
            issue_step_minutes=15,
            max_hold_seconds=12,
            tiers=("M1", "M2", "M3"),
        ),
    )

    assert snapshots.m3_rows
    row = snapshots.m3_rows[0]
    assert row["current_current_a"] is None
    assert row["recent_current_mean_a"] is None
    assert row["recent_current_peak_a"] is None
    assert row["recent_current_observed_ratio"] == 0.0
    assert row["cumulative_current_ah"] == 0.0
    assert row["cumulative_current_observed_ratio"] == 0.0
    assert row["current_pilot_a"] is None
