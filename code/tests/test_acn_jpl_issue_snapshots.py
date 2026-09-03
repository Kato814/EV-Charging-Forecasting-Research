from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

import pytest
from evcf.data.acn_jpl_cleaning import CleaningPolicy, clean_session
from evcf.data.acn_jpl_issue_snapshots import (
    SnapshotPolicy,
    build_issue_snapshots,
    feature_blacklist_document,
    feature_whitelist_document,
    issue_time_grid,
)


def _epoch(value: datetime) -> int:
    return int(value.timestamp())


def _station_rows(start: datetime, count: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(count):
        stamp = start + timedelta(minutes=15 * index)
        rows.append(
            {
                "timestamp_utc": stamp.isoformat().replace("+00:00", "Z"),
                "quarter_hour_index": (stamp.hour * 4 + stamp.minute // 15),
                "day_of_week": stamp.weekday(),
                "is_weekend": stamp.weekday() >= 5,
                "station_current_mean_a": float(index),
                "observed_coverage_ratio": 1.0,
                "valid_bin_90": True,
            }
        )
    return rows


def _session(start: datetime, end: datetime) -> dict[str, object]:
    issue = start + timedelta(hours=24)
    return {
        "anonymous_session_index": 7,
        "connection_utc_s": _epoch(start + timedelta(hours=23)),
        "disconnect_utc_s": _epoch(end),
        "current": {
            "timestamps_utc_s": [
                _epoch(issue - timedelta(seconds=10)),
                _epoch(issue + timedelta(seconds=1)),
            ],
            "values": [2.0, 999.0],
        },
        "pilot": {
            "timestamps_utc_s": [_epoch(issue - timedelta(seconds=10))],
            "values": [8.0],
        },
        "user_inputs": [
            {
                "modified_utc_s": _epoch(issue - timedelta(minutes=1)),
                "requested_departure_utc_s": _epoch(issue + timedelta(hours=2)),
                "kwh_requested": 10.0,
            },
            {
                "modified_utc_s": _epoch(issue + timedelta(seconds=1)),
                "requested_departure_utc_s": _epoch(issue + timedelta(hours=10)),
                "kwh_requested": 99.0,
            },
        ],
    }


def test_issue_grid_excludes_first_24_hours_and_last_4_hours() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = datetime(2019, 6, 1, 7, tzinfo=timezone.utc)

    issues = issue_time_grid(start, end, SnapshotPolicy())

    assert len(issues) == 2865
    assert issues[0] == start + timedelta(hours=24)
    assert issues[-1] == end - timedelta(hours=4)


def test_snapshot_policy_defaults_to_legacy_tiers_and_accepts_seasonal_prefix() -> None:
    assert SnapshotPolicy().tiers == ("M1", "M2", "M3", "M4")
    assert SnapshotPolicy(tiers=("M1", "M2", "M3")).tiers == ("M1", "M2", "M3")

    for invalid in ((), ("M1", "M3"), ("M1", "M2", "M3", "M3"), ("M2",)):
        with pytest.raises(ValueError, match="tiers"):
            SnapshotPolicy(tiers=invalid)
    with pytest.raises(TypeError, match="tiers"):
        SnapshotPolicy(tiers=["M1", "M2", "M3"])  # type: ignore[arg-type]


def test_future_samples_and_late_user_inputs_are_not_visible() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(hours=28)
    station_rows = _station_rows(start, 112)
    result = build_issue_snapshots(
        station_rows,
        [_session(start, end)],
        start_utc=start,
        end_utc=end,
        policy=SnapshotPolicy(max_hold_seconds=12),
    )

    assert len(result.m2_rows) == 1
    m2 = result.m2_rows[0]
    assert m2["station_current_a"] == 2.0
    assert m2["pilot_sum_a"] == 8.0
    assert len(result.m3_rows) == 1
    m3 = result.m3_rows[0]
    assert m3["current_current_a"] == 2.0
    assert m3["known_kwh_requested"] == 10.0
    assert m3["requested_departure_minutes_from_issue"] == 120.0
    assert m3["user_input_modified_utc_s"] <= m3["issue_time_utc_s"]
    assert m3["elapsed_charging_time_proxy_s"] == 10
    assert m3["cumulative_current_ah"] == pytest.approx(20 / 3600)
    assert 999.0 not in tuple(value for value in m3.values() if isinstance(value, float))


def test_active_threshold_preserves_float64_boundary_semantics() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(hours=28)
    session = _session(start, end)
    current = session["current"]
    assert isinstance(current, dict)
    current["values"] = [math.nextafter(0.1, 1.0), 999.0]

    result = build_issue_snapshots(
        _station_rows(start, 112),
        [session],
        start_utc=start,
        end_utc=end,
        policy=SnapshotPolicy(max_hold_seconds=12),
    )

    assert result.m2_rows[0]["active_charging_session_count"] == 1
    assert len(result.m4_rows) == 1


def test_m4_cutoffs_include_issue_time_but_never_future_samples() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    issue = start + timedelta(hours=24)
    end = start + timedelta(hours=28)
    session = _session(start, end)
    current = session["current"]
    assert isinstance(current, dict)
    current["timestamps_utc_s"] = [
        _epoch(issue - timedelta(seconds=1)),
        _epoch(issue),
        _epoch(issue + timedelta(seconds=1)),
    ]
    current["values"] = [1.0, 2.0, 999.0]

    result = build_issue_snapshots(
        _station_rows(start, 112),
        [session],
        start_utc=start,
        end_utc=end,
        policy=SnapshotPolicy(max_hold_seconds=12),
    )

    assert len(result.m4_rows) == 1
    row = result.m4_rows[0]
    assert row["current_start_offset_inclusive"] == 0
    assert row["current_end_offset_exclusive"] == 2
    assert row["pilot_start_offset_inclusive"] == 0
    assert row["pilot_end_offset_exclusive"] == 1
    assert row["max_visible_timestamp_utc_s"] == _epoch(issue)


def test_m4_prefix_references_are_bounded_to_the_24_hour_lookback() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    issue = start + timedelta(hours=24)
    end = start + timedelta(hours=28)
    session = _session(start, end)
    session["connection_utc_s"] = _epoch(issue - timedelta(hours=34))
    session["current"] = {
        "timestamps_utc_s": [
            _epoch(issue - timedelta(hours=33)),
            _epoch(issue - timedelta(hours=23)),
            _epoch(issue - timedelta(seconds=1)),
        ],
        "values": [2.0, 2.0, 2.0],
    }
    session["pilot"] = {
        "timestamps_utc_s": [
            _epoch(issue - timedelta(hours=33)),
            _epoch(issue - timedelta(hours=22)),
        ],
        "values": [8.0, 8.0],
    }

    result = build_issue_snapshots(
        _station_rows(start, 112),
        [session],
        start_utc=start,
        end_utc=end,
        policy=SnapshotPolicy(max_hold_seconds=12),
    )

    row = result.m4_rows[0]
    assert row["current_start_offset_inclusive"] == 1
    assert row["current_end_offset_exclusive"] == 3
    assert row["pilot_start_offset_inclusive"] == 1
    assert row["pilot_end_offset_exclusive"] == 2
    assert row["min_visible_timestamp_utc_s"] >= _epoch(issue - timedelta(hours=24))
    assert result.qa["temporal_violations"]["overlong_trajectory_rows"] == 0


def test_m1_history_and_horizon_labels_use_only_completed_bins() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(hours=28)
    rows = _station_rows(start, 112)
    rows[10]["valid_bin_90"] = False

    result = build_issue_snapshots(
        rows,
        [],
        start_utc=start,
        end_utc=end,
        policy=SnapshotPolicy(max_hold_seconds=12),
    )

    m1 = result.m1_rows[0]
    assert len(m1["history_station_current_mean_a"]) == 96
    assert m1["history_station_current_mean_a"][10] is None
    assert m1["history_station_current_mean_a"][-1] == 95.0
    labels = result.label_rows[0]["labels"]
    assert labels["15"] == 96.0
    assert labels["30"] == 97.0
    assert labels["60"] == 99.0
    assert labels["120"] == 103.0
    assert labels["240"] == 111.0


def test_feature_tiers_are_isolated_and_blacklisted_fields_are_absent() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(hours=28)
    result = build_issue_snapshots(
        _station_rows(start, 112),
        [_session(start, end)],
        start_utc=start,
        end_utc=end,
        policy=SnapshotPolicy(max_hold_seconds=12),
    )

    whitelist = feature_whitelist_document()
    blacklist = feature_blacklist_document()
    assert set(whitelist["tiers"]) == {"M1", "M2", "M3", "M4"}
    assert set(whitelist["tiers"]["M1"]) < set(whitelist["tiers"]["M2"])
    assert blacklist["enforced_private_field_count"] == 9
    assert "final_delivered_energy" in blacklist["forbidden_field_categories"]
    assert "session_identity_fields" in blacklist["forbidden_field_categories"]
    rendered_blacklist = json.dumps(blacklist, sort_keys=True)
    assert "sessionID" not in rendered_blacklist
    assert "userID" not in rendered_blacklist
    assert '"_id"' not in rendered_blacklist
    assert result.qa["leakage_audit"] == "PASS"
    assert result.qa["future_fields_found"] == []
    combined_keys = set().union(
        result.m1_rows[0],
        result.m2_rows[0],
        result.m3_rows[0],
        result.m4_rows[0],
    )
    assert not combined_keys.intersection(
        {
            "kWhDelivered",
            "disconnectTime",
            "doneChargingTime",
            "userID",
            "sessionID",
            "_id",
        }
    )


def test_snapshot_hash_and_shapes_are_reproducible() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(hours=28)
    args = (
        _station_rows(start, 112),
        [_session(start, end)],
    )
    first = build_issue_snapshots(
        *args,
        start_utc=start,
        end_utc=end,
        policy=SnapshotPolicy(max_hold_seconds=12),
    )
    second = build_issue_snapshots(
        *args,
        start_utc=start,
        end_utc=end,
        policy=SnapshotPolicy(max_hold_seconds=12),
    )

    assert first.snapshot_sha256 == second.snapshot_sha256
    assert (
        first.snapshot_sha256 == "c3d93f48ee8bbd3bb447cc15473d084ccef70da47677241bf1abbc29f1bc3be8"
    )
    assert tuple(first.tier_rows) == ("M1", "M2", "M3", "M4")
    assert first.qa["issue_times"] == 1
    assert first.qa["samples"] == {"M1": 1, "M2": 1, "M3": 1, "M4": 1}
    assert first.qa["ragged_rows"]["M3"] == 1
    assert first.qa["ragged_rows"]["M4"] == 1
    assert first.qa["shapes"]["labels"] == [1, 5]
    assert first.qa["missing_rates"]["M3_current_current"] == 0.0
    assert first.qa["M4_prefix_length_distribution"]["current"]["count"] == 1


def test_invalid_any_horizon_excludes_the_formal_m1_to_m4_sample() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(hours=28)
    rows = _station_rows(start, 112)
    rows[96]["valid_bin_90"] = False

    result = build_issue_snapshots(
        rows,
        [],
        start_utc=start,
        end_utc=end,
        policy=SnapshotPolicy(max_hold_seconds=12),
    )

    assert result.qa["issue_times"] == 1
    assert result.qa["formal_issue_times"] == 0
    assert result.qa["incomplete_label_issue_times"] == 1
    assert result.qa["samples"] == {"M1": 0, "M2": 0, "M3": 0, "M4": 0}
    assert result.m1_rows == ()
    assert result.label_rows == ()


def test_station_rows_must_be_exactly_ordered_on_the_utc_grid() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(hours=28)
    rows = list(reversed(_station_rows(start, 112)))

    with pytest.raises(ValueError, match="ordered"):
        build_issue_snapshots(
            rows,
            [],
            start_utc=start,
            end_utc=end,
            policy=SnapshotPolicy(max_hold_seconds=12),
        )


def test_clean_session_user_inputs_are_visible_through_the_real_interface() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    issue = start + timedelta(hours=24)
    end = start + timedelta(hours=28)
    raw = {
        "connectionTime": (start + timedelta(hours=23)).isoformat(),
        "disconnectTime": end.isoformat(),
        "chargingCurrent": {
            "timestamps": [(issue - timedelta(seconds=10)).isoformat()],
            "current": [2.0],
        },
        "pilotSignal": {
            "timestamps": [(issue - timedelta(seconds=10)).isoformat()],
            "pilot": [8.0],
        },
        "userInputs": [
            {
                "modifiedAt": (issue - timedelta(minutes=1)).isoformat(),
                "requestedDeparture": (issue + timedelta(hours=2)).isoformat(),
                "kWhRequested": 10.0,
            }
        ],
    }
    cleaned = clean_session(
        raw,
        session_index=0,
        policy=CleaningPolicy(current_mode_s=4, pilot_mode_s=4),
    )

    result = build_issue_snapshots(
        _station_rows(start, 112),
        [cleaned],
        start_utc=start,
        end_utc=end,
        policy=SnapshotPolicy(max_hold_seconds=12),
    )

    assert result.m3_rows[0]["known_kwh_requested"] == 10.0
    assert result.m3_rows[0]["requested_departure_minutes_from_issue"] == 120.0
