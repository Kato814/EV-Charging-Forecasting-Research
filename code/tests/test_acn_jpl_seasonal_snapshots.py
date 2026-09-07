from __future__ import annotations

import copy
import hashlib
import json
import pickle
from collections.abc import Mapping
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from typing import Any

import evcf.forecasting.acn_jpl_gate1_data as gate1_data
import pytest
from evcf.data.acn_jpl_15min import build_local_15min_grid
from evcf.data.acn_jpl_issue_snapshots import (
    IssueSnapshotResult,
    SnapshotPolicy,
    build_issue_snapshots,
    feature_whitelist_document,
    verified_issue_snapshot_sha256,
)
from evcf.data.acn_jpl_month_config import JPLMonthConfig, jpl_month_config
from evcf.forecasting.acn_jpl_gate1_features import (
    build_feature_blocks,
    feature_encoding_manifest,
)


def _epoch(value: datetime) -> int:
    return int(value.timestamp())


def _station_rows(start: datetime, count: int) -> list[dict[str, object]]:
    return [
        {
            "timestamp_utc": (start + timedelta(minutes=15 * index))
            .isoformat()
            .replace("+00:00", "Z"),
            "station_current_mean_a": float(index),
            "valid_bin_90": True,
        }
        for index in range(count)
    ]


def _session(start: datetime, end: datetime) -> dict[str, object]:
    issue = start + timedelta(hours=24)
    return {
        "anonymous_session_index": 7,
        "connection_utc_s": _epoch(start + timedelta(hours=23)),
        "disconnect_utc_s": _epoch(end),
        "current": {
            "timestamps_utc_s": [_epoch(issue - timedelta(seconds=10))],
            "values": [2.0],
        },
        "pilot": {
            "timestamps_utc_s": [_epoch(issue - timedelta(seconds=10))],
            "values": [8.0],
        },
        "user_inputs": [],
    }


def _full_station_rows(config: JPLMonthConfig) -> list[dict[str, object]]:
    return [
        {
            "timestamp_utc": interval.start_utc.isoformat().replace("+00:00", "Z"),
            "timestamp_local": interval.timestamp_local.isoformat(),
            "local_date": interval.local_date,
            "quarter_hour_index": interval.quarter_hour_index,
            "day_of_week": interval.day_of_week,
            "is_weekend": interval.is_weekend,
            "station_current_mean_a": 0.0,
            "station_current_peak_a": 0.0,
            "connected_session_count": 0,
            "active_charging_session_count": 0,
            "active_charging_session_count_gt_1a": 0,
            "pilot_sum_a": 0.0,
            "pilot_mean_a": 0.0,
            "arrival_count": 0,
            "disconnect_count": 0,
            "observed_coverage_ratio": 1.0,
            "pilot_observed_coverage_ratio": 1.0,
            "valid_bin_80": True,
            "valid_bin_90": True,
            "valid_bin_95": True,
            "known_incomplete_current": False,
            "known_incomplete_pilot": False,
        }
        for interval in build_local_15min_grid(config.local_start, config.local_end)
    ]


def _seasonal_adapter_inputs(
    *, empty_trajectory: bool = False
) -> tuple[
    JPLMonthConfig,
    list[dict[str, object]],
    IssueSnapshotResult,
]:
    config = jpl_month_config("2019-02")
    station_rows = _full_station_rows(config)
    first_issue = config.utc_start + timedelta(hours=24)
    session = {
        "anonymous_session_index": 7,
        "connection_utc_s": _epoch(first_issue - timedelta(hours=1)),
        "disconnect_utc_s": _epoch(first_issue + timedelta(minutes=15)),
        "current": {
            "timestamps_utc_s": [_epoch(first_issue - timedelta(seconds=10))],
            "values": [2.0],
        },
        "pilot": {
            "timestamps_utc_s": [_epoch(first_issue - timedelta(seconds=10))],
            "values": [8.0],
        },
        "user_inputs": [],
    }
    if empty_trajectory:
        session["current"] = {"timestamps_utc_s": [], "values": []}
        session["pilot"] = {"timestamps_utc_s": [], "values": []}
    result = build_issue_snapshots(
        station_rows,
        [session],
        start_utc=config.utc_start,
        end_utc=config.utc_end,
        policy=SnapshotPolicy(tiers=config.tiers),
        preserve_unobserved_trajectory_missingness=True,
    )
    return config, station_rows, result


def _seasonal_subset_adapter_inputs() -> tuple[
    JPLMonthConfig,
    list[dict[str, object]],
    IssueSnapshotResult,
]:
    config = jpl_month_config("2019-02")
    station_rows = _full_station_rows(config)
    invalid_target_position = 96 + 10
    station_rows[invalid_target_position].update(
        {
            "station_current_mean_a": None,
            "station_current_peak_a": None,
            "observed_coverage_ratio": 0.0,
            "valid_bin_80": False,
            "valid_bin_90": False,
            "valid_bin_95": False,
        }
    )
    first_issue = config.utc_start + timedelta(hours=24)
    session = {
        "anonymous_session_index": 7,
        "connection_utc_s": _epoch(first_issue - timedelta(hours=1)),
        "disconnect_utc_s": _epoch(config.utc_end),
        "current": {
            "timestamps_utc_s": [_epoch(first_issue - timedelta(seconds=10))],
            "values": [2.0],
        },
        "pilot": {
            "timestamps_utc_s": [_epoch(first_issue - timedelta(seconds=10))],
            "values": [8.0],
        },
        "user_inputs": [],
    }
    result = build_issue_snapshots(
        station_rows,
        [session],
        start_utc=config.utc_start,
        end_utc=config.utc_end,
        policy=SnapshotPolicy(tiers=config.tiers),
        preserve_unobserved_trajectory_missingness=True,
    )
    return config, station_rows, result


def _m4_mentions(value: object, path: tuple[str, ...] = ()) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            child_path = (*path, str(key))
            if "m4" in str(key).lower():
                found.append((".".join(child_path), nested))
            found.extend(_m4_mentions(nested, child_path))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            found.extend(_m4_mentions(nested, (*path, str(index))))
    elif isinstance(value, str) and "m4" in value.lower():
        found.append((".".join(path), value))
    return found


def _mutable_tree(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _mutable_tree(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mutable_tree(nested) for nested in value]
    return value


def _unchecked_gate1_state(snapshot: gate1_data.Gate1Snapshot) -> tuple[object, ...]:
    return tuple(object.__getattribute__(snapshot, name) for name in snapshot.__slots__)


def test_seasonal_snapshots_emit_only_m1_to_m3_and_one_negative_m4_qa_flag() -> None:
    start = datetime(2019, 11, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(hours=28)
    policy = SnapshotPolicy(max_hold_seconds=12, tiers=("M1", "M2", "M3"))

    result = build_issue_snapshots(
        _station_rows(start, 112),
        [_session(start, end)],
        start_utc=start,
        end_utc=end,
        policy=policy,
    )

    assert result.m4_rows == ()
    assert tuple(result.tier_rows) == policy.tiers
    with pytest.raises(TypeError):
        result.tier_rows["M4"] = ()
    with pytest.raises(TypeError):
        result.m1_rows[0]["history_station_current_mean_a"][0] = 999.0
    with pytest.raises(TypeError):
        result.qa["samples"]["M4"] = 1
    assert result.qa["samples"] == {"M1": 1, "M2": 1, "M3": 1}
    assert result.qa["ragged_rows"] == {"M3": 1}
    assert result.qa["shapes"] == {
        "M1_history": [1, 96],
        "M2_dense": [1, 6],
        "M3_ragged_rows": 1,
        "M3_session_feature_width": 11,
        "labels": [1, 5],
    }
    assert result.qa["valid_labels_by_horizon"] == {
        "15": 1,
        "30": 1,
        "60": 1,
        "120": 1,
        "240": 1,
    }
    assert result.qa["temporal_violations"] == {
        "total": 0,
        "late_user_input_rows": 0,
    }
    assert result.qa["future_fields_found"] == []
    assert result.qa["unexpected_feature_keys"] == []
    assert result.qa["user_inputs_issue_time_truncation"]["status"] == "PASS"
    assert _m4_mentions(result.qa) == [("m4_generated", False)]
    whitelist = feature_whitelist_document(tiers=policy.tiers)
    assert tuple(whitelist["tiers"]) == policy.tiers
    assert "m4" not in json.dumps(whitelist, sort_keys=True).lower()


def test_seasonal_snapshot_hash_has_only_requested_tier_material() -> None:
    start = datetime(2019, 2, 1, 8, tzinfo=timezone.utc)
    end = start + timedelta(hours=28)
    policy = SnapshotPolicy(max_hold_seconds=12, tiers=("M1", "M2", "M3"))
    result = build_issue_snapshots(
        _station_rows(start, 112),
        [_session(start, end)],
        start_utc=start,
        end_utc=end,
        policy=policy,
    )
    payload = {
        "policy": {
            "lookback_minutes": policy.lookback_minutes,
            "horizons_minutes": policy.horizons_minutes,
            "issue_step_minutes": policy.issue_step_minutes,
            "max_hold_seconds": policy.max_hold_seconds,
            "active_threshold_a": policy.active_threshold_a,
            "tiers": policy.tiers,
        },
        "tables": (result.m1_rows, result.m2_rows, result.m3_rows, result.label_rows),
    }
    expected = hashlib.sha256(
        json.dumps(
            _mutable_tree(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert result.snapshot_sha256 == expected


def test_seasonal_adapter_builds_a_sealed_readonly_m1_to_m3_snapshot() -> None:
    config, station_rows, result = _seasonal_adapter_inputs()

    snapshot = gate1_data.build_seasonal_gate1_snapshot(
        result,
        station_rows,
        config=config,
    )
    blocks = build_feature_blocks(snapshot, tiers=config.tiers)
    manifest = feature_encoding_manifest(blocks)

    assert len(gate1_data.verified_snapshot_provenance(snapshot)) == 64
    assert tuple(snapshot.artifact_sha256) == gate1_data.SEASONAL_ARTIFACT_ROOTS
    assert "m4" not in json.dumps(dict(snapshot.artifact_sha256), sort_keys=True).lower()
    assert _m4_mentions(manifest) == []
    assert snapshot.m4_rows == ()
    assert snapshot.m4_by_issue_time == ()
    assert snapshot.issue_times.shape == (config.expected_scheduled_issue_times,)
    assert snapshot.m3_by_issue_time[0][0]["anonymous_session_index"] == 7
    assert all(
        not array.flags.writeable
        for array in (
            snapshot.issue_times,
            snapshot.horizons,
            snapshot.labels,
            snapshot.m1_history,
            snapshot.m1_history_mask,
            snapshot.m1_calendar,
            snapshot.m2_current_state,
            snapshot.station_times,
            snapshot.station_current_mean_a,
            snapshot.station_valid_90,
        )
    )
    assert {tier: block.values.shape[1] for tier, block in blocks.items()} == {
        "M1": 195,
        "M2": 201,
        "M3": 311,
    }
    assert {tier: spec["encoded_dimension"] for tier, spec in manifest["tiers"].items()} == {
        "M1": 195,
        "M2": 204,
        "M3": 391,
    }
    with pytest.raises(TypeError):
        snapshot.artifact_sha256["manual"] = "f" * 64
    with pytest.raises(TypeError):
        snapshot.m3_rows[0]["current_current_a"] = 10.0


def test_known_incomplete_current_excludes_targets_and_masks_history_even_if_flag_is_stale() -> (
    None
):
    config = jpl_month_config("2019-02")
    rows = _full_station_rows(config)
    rows[106]["known_incomplete_current"] = True
    rows[106]["observed_coverage_ratio"] = 10 / 11
    rows[106]["station_current_mean_a"] = 100.0
    result = build_issue_snapshots(
        rows,
        [],
        start_utc=config.utc_start,
        end_utc=config.utc_end,
        policy=SnapshotPolicy(tiers=config.tiers),
        preserve_unobserved_trajectory_missingness=True,
    )
    indexes = {row["issue_index"] for row in result.m1_rows}
    assert set(range(config.expected_scheduled_issue_times)) - indexes == {3, 7, 9, 10}
    later = next(row for row in result.m1_rows if row["issue_index"] == 11)
    assert later["history_station_current_mean_a"][-1] is None
    assert later["history_observed_mask"][-1] is False
    assert result.qa["future_fields_found"] == []


@pytest.mark.parametrize("branch", ["current", "pilot"])
def test_seasonal_station_loader_independently_enforces_branch_missingness(branch: str) -> None:
    config = jpl_month_config("2019-02")
    rows = _full_station_rows(config)
    row = rows[106]
    row[f"known_incomplete_{branch}"] = True
    row["connected_session_count"] = 11
    row["observed_coverage_ratio"] = 10 / 11 if branch == "current" else 1.0
    row["pilot_observed_coverage_ratio"] = 10 / 11 if branch == "pilot" else 1.0
    if branch == "current":
        for threshold in (80, 90, 95):
            row[f"valid_bin_{threshold}"] = False
        row["station_current_mean_a"] = None
        row["station_current_peak_a"] = None
    else:
        row["pilot_sum_a"] = None
        row["pilot_mean_a"] = None
    validated, _times, current, valid = gate1_data._validate_seasonal_station_rows(
        rows, config=config
    )
    assert validated[106][f"known_incomplete_{branch}"] is True
    assert bool(valid[106]) is (branch == "pilot")
    if branch == "current":
        assert current[106] != current[106]
        row["valid_bin_90"] = True
    else:
        row["pilot_sum_a"] = 100.0
    with pytest.raises(ValueError, match="known|validity"):
        gate1_data._validate_seasonal_station_rows(rows, config=config)


@pytest.mark.parametrize("branch", ["current", "pilot"])
@pytest.mark.parametrize("bad_value", [None, 0, "false"])
def test_seasonal_station_loader_rejects_nonboolean_known_state(
    branch: str, bad_value: object
) -> None:
    config = jpl_month_config("2019-02")
    rows = _full_station_rows(config)
    rows[0][f"known_incomplete_{branch}"] = bad_value
    with pytest.raises(TypeError, match="boolean"):
        gate1_data._validate_seasonal_station_rows(rows, config=config)


@pytest.mark.parametrize("branch", ["current", "pilot", "both", "zero"])
def test_m3_missing_branches_stay_independent_and_unknown_is_not_inactive(branch: str) -> None:
    config = jpl_month_config("2019-02")
    issue = config.utc_start + timedelta(hours=24)
    end = issue + timedelta(hours=4)
    station_rows = _station_rows(config.utc_start, 28 * 4)
    session = _session(config.utc_start, end)
    if branch in ("current", "both"):
        session["current"] = {"timestamps_utc_s": [], "values": []}
    if branch in ("pilot", "both"):
        session["pilot"] = {"timestamps_utc_s": [], "values": []}
    if branch == "zero":
        session["current"]["values"] = [0.0]
    result = build_issue_snapshots(
        station_rows,
        [session],
        start_utc=config.utc_start,
        end_utc=end,
        policy=SnapshotPolicy(tiers=config.tiers),
        preserve_unobserved_trajectory_missingness=True,
    )
    m2, m3 = result.m2_rows[0], result.m3_rows[0]
    missing_current = branch in ("current", "both")
    assert m2["connected_session_count"] == 1
    assert m2["station_current_observed_ratio"] == (0.0 if missing_current else 1.0)
    assert m2["active_charging_session_count"] == int(branch == "pilot")
    assert m3["elapsed_connection_s"] == 3600
    assert m3["current_current_a"] == (
        None if missing_current else 0.0 if branch == "zero" else 2.0
    )
    assert m3["current_pilot_a"] == (None if branch in ("pilot", "both") else 8.0)
    assert m2["pilot_sum_a"] == (None if branch in ("pilot", "both") else 8.0)
    for name in (
        "recent_current_mean_a",
        "recent_current_peak_a",
        "cumulative_current_ah",
        "elapsed_charging_time_proxy_s",
    ):
        assert (m3[name] is None) is missing_current
        if branch == "zero":
            assert m3[name] == 0.0
    assert result.qa["future_fields_found"] == []
    assert not any("reason" in key or "known_incomplete" in key for key in m3)


def test_future_trajectory_samples_cannot_fill_missing_issue_features() -> None:
    config = jpl_month_config("2019-02")
    issue = config.utc_start + timedelta(hours=24)
    end = issue + timedelta(hours=4)
    session = _session(config.utc_start, end)
    for branch in ("current", "pilot"):
        session[branch] = {
            "timestamps_utc_s": [_epoch(issue + timedelta(seconds=1))],
            "values": [999.0],
        }
    result = build_issue_snapshots(
        _station_rows(config.utc_start, 28 * 4),
        [session],
        start_utc=config.utc_start,
        end_utc=end,
        policy=SnapshotPolicy(tiers=config.tiers),
        preserve_unobserved_trajectory_missingness=True,
    )
    assert result.m2_rows[0]["station_current_observed_ratio"] == 0.0
    assert result.m2_rows[0]["active_charging_session_count"] == 0
    for field in (
        "current_current_a",
        "current_pilot_a",
        "cumulative_current_ah",
        "elapsed_charging_time_proxy_s",
        "recent_current_mean_a",
        "recent_current_peak_a",
    ):
        assert result.m3_rows[0][field] is None


def test_empty_connected_trajectory_stays_missing_through_gate1_pooling() -> None:
    config, station_rows, result = _seasonal_adapter_inputs(empty_trajectory=True)

    row = result.m3_rows[0]
    assert row["elapsed_charging_time_proxy_s"] is None
    assert row["cumulative_current_ah"] is None
    assert result.qa["missing_rates"]["M3_elapsed_charging_time_proxy"] > 0
    assert result.qa["missing_rates"]["M3_cumulative_current_ah"] > 0

    snapshot = gate1_data.build_seasonal_gate1_snapshot(result, station_rows, config=config)
    block = build_feature_blocks(snapshot, tiers=config.tiers)["M3"]
    for field in ("elapsed_charging_time_proxy_s", "cumulative_current_ah"):
        count = block.feature_names.index(f"m3_{field}_count")
        mean = block.feature_names.index(f"m3_{field}_mean")
        missing = block.feature_names.index(f"m3_{field}_missing_count")
        assert block.values[0, count] == 0.0
        assert block.values[0, missing] == 1.0
        assert block.values[0, mean] != block.values[0, mean]
        assert bool(block.nullable_mask[mean]) is True


@pytest.mark.parametrize(
    "mutation",
    ("legacy_zero", "missing_with_positive_ratio", "missing_ratio"),
)
def test_m3_validator_rejects_inconsistent_cumulative_observation_state(
    mutation: str,
) -> None:
    _config, _station_rows, result = _seasonal_adapter_inputs(empty_trajectory=True)
    row = dict(result.m3_rows[0])
    if mutation == "legacy_zero":
        row["elapsed_charging_time_proxy_s"] = 0
        row["cumulative_current_ah"] = 0.0
        legacy = gate1_data._validate_m3_row(row, 0)
        assert legacy["elapsed_charging_time_proxy_s"] == 0
        assert legacy["cumulative_current_ah"] == 0.0
    elif mutation == "missing_with_positive_ratio":
        row["cumulative_current_observed_ratio"] = 0.25
    else:
        row["cumulative_current_observed_ratio"] = None

    with pytest.raises(ValueError, match="cumulative.*observ"):
        gate1_data._validate_m3_row(
            row,
            0,
            require_unobserved_trajectory_missingness=True,
        )


def test_m3_validator_preserves_observed_zero_current() -> None:
    _config, _station_rows, result = _seasonal_adapter_inputs()
    row = dict(result.m3_rows[0])
    assert row["cumulative_current_observed_ratio"] > 0
    row["elapsed_charging_time_proxy_s"] = 0
    row["cumulative_current_ah"] = 0.0

    validated = gate1_data._validate_m3_row(
        row,
        0,
        require_unobserved_trajectory_missingness=True,
    )

    assert validated["elapsed_charging_time_proxy_s"] == 0
    assert validated["cumulative_current_ah"] == 0.0


def test_m3_legacy_validator_rejects_missing_cumulative_fields() -> None:
    _config, _station_rows, result = _seasonal_adapter_inputs(empty_trajectory=True)

    with pytest.raises(ValueError, match="legacy cumulative trajectory"):
        gate1_data._validate_m3_row(dict(result.m3_rows[0]), 0)


def test_seasonal_adapter_compacts_scheduled_incomplete_issue_rows() -> None:
    config, station_rows, result = _seasonal_subset_adapter_inputs()
    scheduled_count = config.expected_scheduled_issue_times
    scheduled_indexes = [int(row["issue_index"]) for row in result.m1_rows]

    assert result.qa["issue_times"] == scheduled_count
    assert result.qa["formal_issue_times"] == scheduled_count - 4
    assert result.qa["incomplete_label_issue_times"] == 4
    assert set(range(scheduled_count)) - set(scheduled_indexes) == {3, 7, 9, 10}
    assert result.qa["valid_labels_by_horizon"] == {
        "15": scheduled_count - 1,
        "30": scheduled_count - 1,
        "60": scheduled_count - 1,
        "120": scheduled_count - 1,
        "240": scheduled_count,
    }

    snapshot = gate1_data.build_seasonal_gate1_snapshot(
        result,
        station_rows,
        config=config,
    )
    blocks = build_feature_blocks(snapshot, tiers=config.tiers)
    expected_issue_times = [int(row["issue_time_utc_s"]) for row in result.m1_rows]

    assert len(gate1_data.verified_snapshot_provenance(snapshot)) == 64
    assert list(snapshot.issue_times) == expected_issue_times
    assert snapshot.labels.shape == (scheduled_count - 4, 5)
    assert {tier: block.values.shape[0] for tier, block in blocks.items()} == {
        "M1": scheduled_count - 4,
        "M2": scheduled_count - 4,
        "M3": scheduled_count - 4,
    }
    compact_position = scheduled_indexes.index(11)
    assert snapshot.m3_by_issue_time[compact_position][0]["issue_index"] == 11
    assert (
        snapshot.m3_by_issue_time[compact_position][0]["issue_time_utc_s"]
        == snapshot.issue_times[compact_position]
    )
    attacked_issue_times = snapshot.issue_times.copy()
    attacked_issue_times[1] = attacked_issue_times[0]
    attacked_issue_times.flags.writeable = False
    object.__setattr__(snapshot, "issue_times", attacked_issue_times)
    with pytest.raises(ValueError, match="strictly increasing"):
        gate1_data.verified_snapshot_provenance(snapshot)


def test_seasonal_dense_rows_reject_duplicate_scheduled_issue_indexes() -> None:
    config, station_rows, result = _seasonal_subset_adapter_inputs()
    _materialized, _times, station_current, station_valid = (
        gate1_data._validate_seasonal_station_rows(station_rows, config=config)
    )
    duplicate_position = next(
        position for position, row in enumerate(result.m1_rows) if int(row["issue_index"]) == 11
    )
    previous_index = int(result.m1_rows[duplicate_position - 1]["issue_index"])
    previous_time = int(result.m1_rows[duplicate_position - 1]["issue_time_utc_s"])
    replacements: dict[str, tuple[dict[str, object], ...]] = {}
    for table_name in ("m1_rows", "m2_rows", "label_rows"):
        rows = [dict(row) for row in getattr(result, table_name)]
        rows[duplicate_position]["issue_index"] = previous_index
        rows[duplicate_position]["issue_time_utc_s"] = previous_time
        replacements[table_name] = tuple(rows)

    with pytest.raises(ValueError, match="strictly increasing scheduled index"):
        gate1_data._validate_seasonal_dense_rows(
            replace(result, **replacements),
            config=config,
            station_current=station_current,
            station_valid=station_valid,
        )


def test_seasonal_m3_rows_reject_an_excluded_scheduled_issue_index() -> None:
    config, station_rows, result = _seasonal_subset_adapter_inputs()
    _materialized, _times, station_current, station_valid = (
        gate1_data._validate_seasonal_station_rows(station_rows, config=config)
    )
    (
        issue_times,
        scheduled_issue_indexes,
        _horizons,
        _labels,
        _history,
        _history_mask,
        _calendar,
        current_states,
    ) = gate1_data._validate_seasonal_dense_rows(
        result,
        config=config,
        station_current=station_current,
        station_valid=station_valid,
    )
    rows = [dict(row) for row in result.m3_rows]
    attacked_position = next(
        position for position, row in enumerate(rows) if int(row["issue_index"]) == 11
    )
    rows[attacked_position]["issue_index"] = 10
    rows[attacked_position]["issue_time_utc_s"] = (
        int(config.utc_start.timestamp()) + 86_400 + 10 * 900
    )

    with pytest.raises(ValueError, match="not aligned to its issue index"):
        gate1_data._validate_seasonal_m3_rows(
            replace(result, m3_rows=tuple(rows)),
            issue_times=issue_times,
            scheduled_issue_indexes=scheduled_issue_indexes,
            current_states=current_states,
        )


@pytest.mark.parametrize(
    "checkpoint_operation",
    (
        lambda snapshot: pickle.loads(pickle.dumps(snapshot)),
        copy.copy,
        copy.deepcopy,
    ),
    ids=("pickle", "copy", "deepcopy"),
)
def test_seasonal_gate1_snapshot_checkpointing_is_explicitly_unsupported(
    checkpoint_operation: Any,
) -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    snapshot = gate1_data.build_seasonal_gate1_snapshot(result, station_rows, config=config)

    with pytest.raises(
        ValueError,
        match="^seasonal Gate1 snapshots cannot be checkpointed$",
    ):
        checkpoint_operation(snapshot)


def test_seasonal_verification_has_no_restore_signing_entrypoint() -> None:
    assert not hasattr(gate1_data, "_restore_seasonal_snapshot_verification")


def test_seasonal_gate1_snapshot_rejects_direct_state_restore() -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    snapshot = gate1_data.build_seasonal_gate1_snapshot(result, station_rows, config=config)
    forged = object.__new__(gate1_data.Gate1Snapshot)

    with pytest.raises(
        ValueError,
        match="^snapshot checkpoint verification failed$",
    ):
        forged.__setstate__(_unchecked_gate1_state(snapshot))


def test_seasonal_verification_cannot_itself_be_pickled() -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    snapshot = gate1_data.build_seasonal_gate1_snapshot(result, station_rows, config=config)
    verification = object.__getattribute__(snapshot, "_verification")

    with pytest.raises(
        ValueError,
        match="^seasonal Gate1 snapshots cannot be checkpointed$",
    ):
        pickle.dumps(verification)


def test_seasonal_result_and_snapshot_reject_dynamic_verifier_injection() -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    snapshot = gate1_data.build_seasonal_gate1_snapshot(result, station_rows, config=config)

    with pytest.raises(AttributeError):
        object.__setattr__(result, "verified_snapshot_sha256", lambda: "0" * 64)
    with pytest.raises(AttributeError):
        object.__setattr__(snapshot, "verified_snapshot_provenance", lambda: "0" * 64)


def test_issue_snapshot_nested_material_has_no_base_mutator_escape_hatch() -> None:
    _config, _station_rows, result = _seasonal_adapter_inputs()
    row = result.m1_rows[0]
    history = row["history_station_current_mean_a"]
    samples = result.qa["samples"]

    assert isinstance(row, Mapping) and not isinstance(row, dict)
    assert isinstance(samples, Mapping) and not isinstance(samples, dict)
    assert isinstance(history, tuple) and not isinstance(history, list)
    with pytest.raises(TypeError):
        dict.__setitem__(row, "issue_index", 999)
    with pytest.raises(TypeError):
        list.__setitem__(history, 0, 999.0)
    with pytest.raises(TypeError):
        dict.__setitem__(samples, "M4", 1)


def test_only_builder_registered_issue_snapshot_identity_is_verified() -> None:
    _config, _station_rows, result = _seasonal_adapter_inputs()
    assert verified_issue_snapshot_sha256(result) == result.snapshot_sha256
    manual = IssueSnapshotResult(
        m1_rows=result.m1_rows,
        m2_rows=result.m2_rows,
        m3_rows=result.m3_rows,
        m4_rows=result.m4_rows,
        label_rows=result.label_rows,
        qa=result.qa,
        snapshot_sha256=result.snapshot_sha256,
        _policy=result.policy,
    )

    for unregistered in (
        manual,
        replace(result),
        copy.copy(result),
        copy.deepcopy(result),
        pickle.loads(pickle.dumps(result)),
    ):
        assert unregistered is not result
        with pytest.raises(ValueError, match="process|registered|seal"):
            verified_issue_snapshot_sha256(unregistered)


def test_seasonal_adapter_rejects_policy_subclass_with_malicious_equality() -> None:
    class AlwaysEqualPolicy(SnapshotPolicy):
        def __eq__(self, _other: object) -> bool:
            return True

    config, station_rows, result = _seasonal_adapter_inputs()
    object.__setattr__(result, "_policy", AlwaysEqualPolicy(tiers=config.tiers))

    with pytest.raises((TypeError, ValueError), match="policy|exact|seal"):
        gate1_data.build_seasonal_gate1_snapshot(result, station_rows, config=config)


@pytest.mark.parametrize(
    "attack",
    (
        "missing_rates_extra",
        "missing_rates_nan",
        "occupancy_missing",
        "occupancy_extra",
        "user_inputs_infinite",
        "user_inputs_extra",
    ),
)
def test_seasonal_adapter_rejects_recursive_qa_schema_attacks(attack: str) -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    qa = _mutable_tree(result.qa)
    assert isinstance(qa, dict)
    if attack == "missing_rates_extra":
        qa["missing_rates"]["extra"] = 0.0
    elif attack == "missing_rates_nan":
        qa["missing_rates"]["M1_history"] = float("nan")
    elif attack == "occupancy_missing":
        qa["occupancy_rate"].pop("reason")
    elif attack == "occupancy_extra":
        qa["occupancy_rate"]["extra"] = "ignored"
    elif attack == "user_inputs_infinite":
        qa["user_inputs_issue_time_truncation"]["connected_session_rows"] = float("inf")
    else:
        qa["user_inputs_issue_time_truncation"]["extra"] = 0
    object.__setattr__(result, "qa", qa)

    with pytest.raises(ValueError, match="QA|qa|finite|rate|schema|seal"):
        gate1_data.build_seasonal_gate1_snapshot(result, station_rows, config=config)


def test_seasonal_gate1_checkpoint_tamper_has_explicit_verification_error() -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    snapshot = gate1_data.build_seasonal_gate1_snapshot(result, station_rows, config=config)
    state = list(_unchecked_gate1_state(snapshot))
    artifact_position = snapshot.__slots__.index("artifact_sha256")
    state[artifact_position] = dict(snapshot.artifact_sha256)
    forged = object.__new__(gate1_data.Gate1Snapshot)

    with pytest.raises(ValueError, match="checkpoint verification failed"):
        forged.__setstate__(tuple(state))


@pytest.mark.parametrize(
    "verification_attack",
    ("none", "wrong_type", "subclass", "manual", "bad_seal"),
)
def test_gate1_checkpoint_requires_an_issued_exact_verification(
    verification_attack: str,
) -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    snapshot = gate1_data.build_seasonal_gate1_snapshot(result, station_rows, config=config)
    state = list(_unchecked_gate1_state(snapshot))
    verification_position = snapshot.__slots__.index("_verification")
    verification = state[verification_position]
    assert verification is not None
    values = {field.name: getattr(verification, field.name) for field in fields(verification)}

    if verification_attack == "none":
        attacked_verification: object = None
    elif verification_attack == "wrong_type":
        attacked_verification = object()
    elif verification_attack == "subclass":

        class VerificationSubclass(type(verification)):
            pass

        attacked_verification = VerificationSubclass(**values)
    elif verification_attack == "manual":
        attacked_verification = type(verification)(**values)
    else:
        attacked_verification = replace(verification, seal_sha256="0" * 64)
    state[verification_position] = attacked_verification
    forged = object.__new__(gate1_data.Gate1Snapshot)

    with pytest.raises(
        ValueError,
        match="^snapshot checkpoint verification failed$",
    ):
        forged.__setstate__(tuple(state))


def test_gate1_frozen_mapping_has_no_reachable_mutable_backing_dict() -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    snapshot = gate1_data.build_seasonal_gate1_snapshot(result, station_rows, config=config)

    assert not hasattr(snapshot.artifact_sha256, "_FrozenMapping__data")
    assert not hasattr(snapshot.m3_rows[0], "_FrozenMapping__data")


def test_seasonal_adapter_recomputes_and_rejects_snapshot_hash_tampering() -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    changed_rows = [dict(row) for row in result.m1_rows]
    changed_rows[0]["history_station_current_mean_a"] = list(
        changed_rows[0]["history_station_current_mean_a"]
    )
    changed_rows[0]["history_station_current_mean_a"][0] = 999.0

    for tampered in (
        replace(result, snapshot_sha256="0" * 64),
        replace(result, m1_rows=tuple(changed_rows)),
    ):
        with pytest.raises(ValueError, match="snapshot.*hash|SHA|process|registered|seal"):
            gate1_data.build_seasonal_gate1_snapshot(
                tampered,
                station_rows,
                config=config,
            )


@pytest.mark.parametrize(
    ("table", "mutation"),
    (
        ("m1_rows", "extra"),
        ("m2_rows", "missing"),
        ("m3_rows", "extra"),
        ("label_rows", "missing"),
    ),
)
def test_seasonal_adapter_rejects_extra_or_missing_snapshot_fields(
    table: str,
    mutation: str,
) -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    rows = [dict(row) for row in getattr(result, table)]
    assert rows
    if mutation == "extra":
        rows[0]["unexpected"] = 1
    else:
        rows[0].pop(next(iter(rows[0])))
    tampered = replace(result, **{table: tuple(rows)})

    with pytest.raises(ValueError, match="schema|fields|keys"):
        gate1_data.build_seasonal_gate1_snapshot(
            tampered,
            station_rows,
            config=config,
        )


def test_seasonal_adapter_rejects_wrong_config_and_any_m4_material() -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    noncanonical = replace(config)

    for wrong_config in (
        jpl_month_config("2019-05"),
        jpl_month_config("2019-08"),
        noncanonical,
    ):
        with pytest.raises(ValueError, match="seasonal|config|month|grid"):
            gate1_data.build_seasonal_gate1_snapshot(
                result,
                station_rows,
                config=wrong_config,
            )

    with pytest.raises(ValueError, match="M4"):
        gate1_data.build_seasonal_gate1_snapshot(
            replace(result, m4_rows=({"unexpected": 1},)),
            station_rows,
            config=config,
        )


def test_seasonal_adapter_rejects_station_grid_length_time_and_schema_drift() -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    wrong_time = [dict(row) for row in station_rows]
    wrong_time[0]["timestamp_utc"] = wrong_time[1]["timestamp_utc"]
    wrong_schema = [dict(row) for row in station_rows]
    wrong_schema[0]["unexpected"] = 1

    for malformed in (station_rows[:-1], wrong_time, wrong_schema):
        with pytest.raises(ValueError, match="station|grid|schema|length"):
            gate1_data.build_seasonal_gate1_snapshot(
                result,
                malformed,
                config=config,
            )


def test_seasonal_result_binds_requested_tiers_outside_mutable_qa() -> None:
    _config, _station_rows, result = _seasonal_adapter_inputs()
    changed_qa = _mutable_tree(result.qa)
    assert isinstance(changed_qa, dict)
    changed_qa["samples"]["M4"] = 1

    with pytest.raises(ValueError, match="tiers|samples"):
        replace(result, qa=changed_qa)


def test_seasonal_snapshot_artifact_provenance_rejects_mapping_tampering() -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    snapshot = gate1_data.build_seasonal_gate1_snapshot(
        result,
        station_rows,
        config=config,
    )
    changed = dict(snapshot.artifact_sha256)
    changed["manual"] = "f" * 64
    object.__setattr__(snapshot, "artifact_sha256", changed)

    with pytest.raises(ValueError, match="artifact|seal"):
        gate1_data.verified_snapshot_provenance(snapshot)
