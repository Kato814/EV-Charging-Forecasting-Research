from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest
from evcf.data.acn_jpl_cleaning import (
    CleaningPolicy,
    bounded_locf_integral,
    clean_series,
    clean_session,
    derive_sampling_modes,
    parse_timestamp_utc_s,
    utc_s_to_local_iso,
    write_cleaned_sessions,
)

BASE = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)


def _stamp(seconds: int) -> str:
    return format_datetime(BASE + timedelta(seconds=seconds), usegmt=True)


def _policy() -> CleaningPolicy:
    return CleaningPolicy(current_mode_s=4, pilot_mode_s=4)


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _nested_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _nested_keys(item)}
    return set()


def test_timestamp_parsing_is_utc_and_maps_to_los_angeles() -> None:
    expected = int(datetime(2019, 5, 1, 7, tzinfo=timezone.utc).timestamp())

    assert parse_timestamp_utc_s("Wed, 01 May 2019 07:00:00 GMT") == expected
    assert parse_timestamp_utc_s("2019-05-01T00:00:00-07:00") == expected
    assert parse_timestamp_utc_s(datetime(2019, 5, 1, 7, tzinfo=timezone.utc)) == expected
    assert utc_s_to_local_iso(expected) == "2019-05-01T00:00:00-07:00"

    with pytest.raises(ValueError, match="timezone-aware"):
        parse_timestamp_utc_s(datetime(2019, 5, 1, 7, tzinfo=timezone.utc).replace(tzinfo=None))


def test_exact_duplicates_keep_the_first_raw_occurrence() -> None:
    start = parse_timestamp_utc_s(_stamp(0))
    result = clean_series(
        {
            "timestamps": [_stamp(0), _stamp(0), _stamp(4)],
            "current": [1.0, 1.0, 2.0],
        },
        field_name="chargingCurrent",
        connection_utc_s=start,
        disconnect_utc_s=start + 20,
        policy=_policy(),
    )

    assert result.timestamps_utc_s == (start, start + 4)
    assert result.values == (1.0, 2.0)
    assert result.raw_ordinals == (0, 2)
    assert result.audit.exact_duplicate_extras == 1
    assert result.audit.conflicting_timestamps == 0
    with pytest.raises(FrozenInstanceError):
        result.values = ()  # type: ignore[misc]


def test_negative_current_and_nonfinite_values_are_rejected() -> None:
    start = parse_timestamp_utc_s(_stamp(0))
    result = clean_series(
        {
            "timestamps": [_stamp(0), _stamp(4), _stamp(8), _stamp(12)],
            "current": [-1, float("nan"), float("inf"), True],
        },
        field_name="chargingCurrent",
        connection_utc_s=start,
        disconnect_utc_s=start + 20,
        policy=_policy(),
    )

    assert result.timestamps_utc_s == ()
    assert result.values == ()
    assert result.audit.invalid_values == 4


def test_conflicting_timestamp_is_excluded_from_main_and_lww_is_retained() -> None:
    start = parse_timestamp_utc_s(_stamp(0))
    result = clean_series(
        {
            "timestamps": [_stamp(0), _stamp(0), _stamp(4)],
            "current": [1.0, 2.0, 3.0],
        },
        field_name="chargingCurrent",
        connection_utc_s=start,
        disconnect_utc_s=start + 20,
        policy=_policy(),
    )

    assert result.timestamps_utc_s == (start + 4,)
    assert result.values == (3.0,)
    assert result.raw_ordinals == (2,)
    assert [
        (point.timestamp_utc_s, point.value, point.raw_ordinal)
        for point in result.conflict_lww_overrides
    ] == [(start, 2.0, 1)]
    assert [(point.timestamp_utc_s, point.value) for point in result.sensitivity_points()] == [
        (start, 2.0),
        (start + 4, 3.0),
    ]
    assert result.audit.conflicting_timestamps == 1


def test_main_and_boundary_sensitivity_use_frozen_half_open_intervals() -> None:
    start = parse_timestamp_utc_s(_stamp(0))
    disconnect = start + 20
    offsets = (-61, -60, 0, 19, 20, 79, 80)
    result = clean_series(
        {
            "timestamps": [_stamp(offset) for offset in offsets],
            "current": [float(index + 1) for index in range(len(offsets))],
        },
        field_name="chargingCurrent",
        connection_utc_s=start,
        disconnect_utc_s=disconnect,
        policy=_policy(),
    )

    assert result.timestamps_utc_s == (start, disconnect - 1)
    assert [point.timestamp_utc_s for point in result.boundary_sensitivity_points] == [
        start - 60,
        disconnect,
        disconnect + 59,
    ]
    assert [point.timestamp_utc_s for point in result.sensitivity_points()] == [
        start - 60,
        start,
        disconnect - 1,
        disconnect,
        disconnect + 59,
    ]
    assert result.audit.boundary_distances_s == (-61, -60, 0, 59, 60)


def test_boundary_positive_integral_share_uses_bounded_time_not_point_counts() -> None:
    start = parse_timestamp_utc_s(_stamp(0))
    result = clean_series(
        {
            "timestamps": [_stamp(-4), _stamp(0), _stamp(20), _stamp(24)],
            "current": [2.0, 4.0, 3.0, 0.0],
        },
        field_name="chargingCurrent",
        connection_utc_s=start,
        disconnect_utc_s=start + 20,
        policy=_policy(),
    )

    assert result.audit.boundary_positive_value_seconds == pytest.approx(20.0)
    assert result.audit.raw_total_value_seconds == pytest.approx(68.0)
    assert result.audit.to_local_dict()["boundary_current_integral_share"] == pytest.approx(20 / 68)


def test_all_positive_current_boundary_points_are_retained_for_audit() -> None:
    start = parse_timestamp_utc_s(_stamp(0))
    disconnect = start + 20
    offsets = (-120, -30, 0, 20, 80, 140)
    result = clean_series(
        {
            "timestamps": [_stamp(offset) for offset in offsets],
            "current": [2.0, 0.0, 1.0, 3.0, 4.0, 5.0],
        },
        field_name="chargingCurrent",
        connection_utc_s=start,
        disconnect_utc_s=disconnect,
        policy=_policy(),
    )

    assert [
        (point.timestamp_utc_s - start, point.value, point.raw_ordinal)
        for point in result.boundary_positive_points
    ] == [(-120, 2.0, 0), (20, 3.0, 3), (80, 4.0, 4), (140, 5.0, 5)]
    assert result.audit.boundary_distances_s == (-120, 0, 60, 120)
    assert [point.timestamp_utc_s - start for point in result.boundary_sensitivity_points] == [
        -30,
        20,
    ]


def test_sampling_modes_are_derived_independently_from_positive_raw_deltas() -> None:
    records = [
        {
            "chargingCurrent": {
                "timestamps": [_stamp(0), _stamp(4), _stamp(8), _stamp(8), _stamp(14)],
                "current": [1.0] * 5,
            },
            "pilotSignal": {
                "timestamps": [_stamp(0), _stamp(6), _stamp(12), _stamp(16)],
                "pilot": [2.0] * 4,
            },
        },
        {
            "chargingCurrent": {
                "timestamps": [_stamp(20), _stamp(26)],
                "current": [1.0, 1.0],
            },
            "pilotSignal": {
                "timestamps": [_stamp(20), _stamp(26)],
                "pilot": [2.0, 2.0],
            },
        },
    ]

    modes = derive_sampling_modes(records)

    assert modes.current.mode_seconds == 4
    assert modes.current.positive_delta_count == 4
    assert modes.current.delta_histogram == ((4, 2), (6, 2))
    assert modes.pilot.mode_seconds == 6
    assert modes.pilot.positive_delta_count == 4
    assert modes.pilot.delta_histogram == ((4, 1), (6, 3))


def test_bounded_locf_integrates_elapsed_time_and_leaves_long_gaps_uncovered() -> None:
    start = parse_timestamp_utc_s(_stamp(0))
    result = clean_series(
        {
            "timestamps": [_stamp(0), _stamp(4), _stamp(20)],
            "current": [2.0, 4.0, 8.0],
        },
        field_name="chargingCurrent",
        connection_utc_s=start,
        disconnect_utc_s=start + 40,
        policy=_policy(),
    )

    integral = result.main_integral
    assert result.locf_cap_s == 12
    assert integral.observed_seconds == 28
    assert integral.eligible_seconds == 40
    assert integral.coverage == pytest.approx(0.7)
    assert integral.value_seconds == pytest.approx(152.0)
    assert integral.value_hours == pytest.approx(152.0 / 3600.0)
    assert [
        (item.start_utc_s - start, item.end_utc_s - start, item.value)
        for item in integral.contributions
    ] == [(0, 4, 2.0), (4, 16, 4.0), (20, 32, 8.0)]

    one_mode = bounded_locf_integral(
        result.main_points(),
        start_utc_s=start,
        end_utc_s=start + 40,
        hold_cap_s=4,
    )
    assert one_mode.observed_seconds == 12
    assert one_mode.value_seconds == pytest.approx(56.0)


def test_raw_order_value_and_pair_digests_preserve_audit_linkage() -> None:
    start = parse_timestamp_utc_s(_stamp(0))
    forward = clean_series(
        {"timestamps": [_stamp(0), _stamp(4)], "current": [1, 2.0]},
        field_name="chargingCurrent",
        connection_utc_s=start,
        disconnect_utc_s=start + 20,
        policy=_policy(),
    )
    reversed_times = clean_series(
        {"timestamps": [_stamp(4), _stamp(0)], "current": [1, 2.0]},
        field_name="chargingCurrent",
        connection_utc_s=start,
        disconnect_utc_s=start + 20,
        policy=_policy(),
    )
    repeated = clean_series(
        {"timestamps": [_stamp(0), _stamp(4)], "current": [1, 2.0]},
        field_name="chargingCurrent",
        connection_utc_s=start,
        disconnect_utc_s=start + 20,
        policy=_policy(),
    )

    assert forward.audit.raw_order_sha256 == repeated.audit.raw_order_sha256
    assert forward.audit.raw_values_sha256 == repeated.audit.raw_values_sha256
    assert forward.audit.raw_pairs_sha256 == repeated.audit.raw_pairs_sha256
    assert forward.audit.raw_order_sha256 != reversed_times.audit.raw_order_sha256
    assert forward.audit.raw_values_sha256 == reversed_times.audit.raw_values_sha256
    assert forward.audit.raw_pairs_sha256 != reversed_times.audit.raw_pairs_sha256
    assert all(
        len(digest) == 64
        for digest in (
            forward.audit.raw_order_sha256,
            forward.audit.raw_values_sha256,
            forward.audit.raw_pairs_sha256,
        )
    )


def test_clean_session_is_anonymous_and_sanitizes_issue_time_user_inputs() -> None:
    start = parse_timestamp_utc_s(_stamp(0))
    raw = {
        "_id": "private-object-sentinel",
        "sessionID": "private-session-sentinel",
        "userID": "private-user-sentinel",
        "siteID": "jpl",
        "stationID": "station-1",
        "spaceID": "space-1",
        "clusterID": "cluster-1",
        "connectionTime": _stamp(0),
        "disconnectTime": _stamp(40),
        "doneChargingTime": _stamp(32),
        "kWhDelivered": 1.25,
        "chargingCurrent": {
            "timestamps": [_stamp(0), _stamp(4)],
            "current": [1.0, 2.0],
        },
        "pilotSignal": {
            "timestamps": [_stamp(0), _stamp(6)],
            "pilot": [8.0, 9.0],
        },
        "userInputs": [
            {
                "modifiedAt": _stamp(8),
                "requestedDeparture": _stamp(100),
                "kWhRequested": 12,
                "userID": "private-user-sentinel",
                "fixtureToken": "private-token-sentinel",
            },
            {"requestedDeparture": _stamp(120), "kWhRequested": 15.0},
            {
                "modifiedAt": _stamp(4),
                "requestedDeparture": _stamp(80),
                "kWhRequested": 10.0,
            },
        ],
    }

    cleaned = clean_session(raw, session_index=7, policy=_policy())

    assert cleaned.session_index == 7
    assert cleaned.connection_utc_s == start
    assert cleaned.disconnect_utc_s == start + 40
    assert cleaned.current.timestamps_utc_s == (start, start + 4)
    assert cleaned.pilot.timestamps_utc_s == (start, start + 6)
    assert cleaned.retrospective_done_raw == _stamp(32)
    assert cleaned.retrospective_done_utc_s == start + 32
    assert [item.modified_at_utc_s - start for item in cleaned.user_inputs] == [4, 8]
    assert [item.raw_ordinal for item in cleaned.user_inputs] == [2, 0]
    assert cleaned.offline_kwh_delivered == 1.25

    payload = cleaned.to_local_dict()
    assert payload["connection_utc_s"] == start
    assert payload["connection_local"] == "2019-05-01T00:00:00-07:00"
    assert payload["disconnect_local"] == "2019-05-01T00:00:40-07:00"
    assert payload["timezone"] == "America/Los_Angeles"
    assert payload["retrospective_done_raw"] == _stamp(32)
    assert payload["current"]["timestamps_utc_s"] == [start, start + 4]
    assert {"_id", "sessionID", "userID", "fixtureToken"}.isdisjoint(_nested_keys(payload))
    rendered = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "private-object-sentinel",
        "private-session-sentinel",
        "private-user-sentinel",
        "private-token-sentinel",
    ):
        assert forbidden not in rendered
    assert set(payload["user_inputs"][0]) == {
        "kwh_requested",
        "modified_at_utc_s",
        "raw_ordinal",
        "requested_departure_utc_s",
    }


def test_cleaned_store_is_deterministic_gzip_jsonl_with_hashed_manifest(
    tmp_path: Path,
) -> None:
    policy = _policy()
    raw = {
        "_id": "private-object-sentinel",
        "sessionID": "private-session-sentinel",
        "connectionTime": _stamp(0),
        "disconnectTime": _stamp(40),
        "chargingCurrent": {
            "timestamps": [_stamp(0), _stamp(4)],
            "current": [1.0, 2.0],
        },
        "pilotSignal": {
            "timestamps": [_stamp(0), _stamp(6)],
            "pilot": [8.0, 9.0],
        },
        "userInputs": [],
    }
    session = clean_session(raw, session_index=0, policy=policy)
    first_path = tmp_path / "first.jsonl.gz"
    second_path = tmp_path / "second.jsonl.gz"

    first = write_cleaned_sessions(
        [session],
        first_path,
        policy=policy,
        source_inventory_sha256="a" * 64,
    )
    second = write_cleaned_sessions(
        [session],
        second_path,
        policy=policy,
        source_inventory_sha256="a" * 64,
    )

    assert first_path.read_bytes() == second_path.read_bytes()
    assert first.record_count == 1
    assert first.sha256 == hashlib.sha256(first_path.read_bytes()).hexdigest()
    assert first.sha256 == second.sha256
    assert first.manifest_path == first_path.with_name("first.jsonl.gz.manifest.json")
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest == {
        "anonymous_session_indexes": True,
        "data_file": "first.jsonl.gz",
        "policy": policy.to_local_dict(),
        "private_identifiers_stored": False,
        "record_count": 1,
        "schema_version": "acn-jpl-cleaned-sessions/v1",
        "sha256": first.sha256,
        "source_inventory_sha256": "a" * 64,
    }
    assert first.manifest_path.read_bytes().endswith(b"\n")
    with gzip.open(first_path, "rt", encoding="utf-8") as handle:
        stored = json.loads(handle.readline())
        assert handle.readline() == ""
    assert stored["session_index"] == 0
    assert "contributions" not in stored["current"]["main_integral"]
    assert "contributions" not in stored["pilot"]["main_integral"]
    assert "private-object-sentinel" not in json.dumps(stored)
    assert "private-session-sentinel" not in json.dumps(stored)
