from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import replace
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
        }
        for interval in build_local_15min_grid(config.local_start, config.local_end)
    ]


def _seasonal_adapter_inputs() -> tuple[
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
    result = build_issue_snapshots(
        station_rows,
        [session],
        start_utc=config.utc_start,
        end_utc=config.utc_end,
        policy=SnapshotPolicy(tiers=config.tiers),
    )
    return config, station_rows, result


def _m4_mentions(value: object, path: tuple[str, ...] = ()) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, dict):
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
            payload,
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

    restored = pickle.loads(pickle.dumps(snapshot))
    assert gate1_data.verified_snapshot_provenance(restored) == (
        gate1_data.verified_snapshot_provenance(snapshot)
    )
    assert tuple(restored.artifact_sha256) == gate1_data.SEASONAL_ARTIFACT_ROOTS
    assert restored.m4_rows == restored.m4_by_issue_time == ()


def test_seasonal_result_and_snapshot_reject_dynamic_verifier_injection() -> None:
    config, station_rows, result = _seasonal_adapter_inputs()
    snapshot = gate1_data.build_seasonal_gate1_snapshot(result, station_rows, config=config)

    with pytest.raises(AttributeError):
        object.__setattr__(result, "verified_snapshot_sha256", lambda: "0" * 64)
    with pytest.raises(AttributeError):
        object.__setattr__(snapshot, "verified_snapshot_provenance", lambda: "0" * 64)


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
        with pytest.raises(ValueError, match="snapshot.*hash|SHA"):
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
    changed_qa = json.loads(json.dumps(result.qa))
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
