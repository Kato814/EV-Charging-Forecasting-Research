from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from evcf.data.acn_jpl_issue_snapshots import (
    SnapshotPolicy,
    build_issue_snapshots,
    feature_whitelist_document,
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
