from __future__ import annotations

import gzip
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import numpy as np
import pytest
from evcf.data.acn_jpl_cleaning import CleaningPolicy, clean_session
from evcf.data.acn_jpl_gate1_prep import (
    CleaningAccumulator,
    _deterministic_gzip_jsonl_bytes,
    _deterministic_npz_bytes,
    _load_protocol,
    _public_payloads,
    _validate_output_topology,
    close_public_artifacts,
    publish_public_release,
    verify_public_release,
)
from evcf.data.acn_jpl_power_semantics import PowerAuditSession, audit_power_semantics
from evcf.data.acn_jpl_preparation import PUBLIC_ARTIFACT_NAMES

BASE = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)


def _stamp(seconds: int) -> str:
    return format_datetime(BASE + timedelta(seconds=seconds), usegmt=True)


def _raw_record() -> dict[str, object]:
    return {
        "_id": "private-object-sentinel",
        "sessionID": "private-session-sentinel",
        "userID": "private-user-sentinel",
        "spaceID": "AG-1F01",
        "connectionTime": _stamp(0),
        "disconnectTime": _stamp(20),
        "doneChargingTime": _stamp(16),
        "kWhDelivered": 0.624,
        "chargingCurrent": {
            "timestamps": [_stamp(-4), _stamp(0), _stamp(4), _stamp(20)],
            "current": [2.0, 3.0, 3.0, 1.0],
        },
        "pilotSignal": {
            "timestamps": [_stamp(0), _stamp(4)],
            "pilot": [8.0, 8.0],
        },
        "userInputs": [
            {
                "modifiedAt": _stamp(2),
                "requestedDeparture": _stamp(100),
                "kWhRequested": 10.0,
            }
        ],
    }


def test_cleaning_accumulator_reports_main_and_sensitivity_metrics() -> None:
    policy = CleaningPolicy(current_mode_s=4, pilot_mode_s=4)
    raw = _raw_record()
    cleaned = clean_session(raw, session_index=0, policy=policy)
    accumulator = CleaningAccumulator(policy)

    accumulator.add(cleaned, raw)

    cleaning = accumulator.cleaning_qa(expected_sessions=1)
    sensitivity = accumulator.cleaning_sensitivity()
    boundary = accumulator.boundary_current_audit()
    assert cleaning["status"] == "PASS"
    assert cleaning["sessions_processed"] == 1
    assert cleaning["current"]["retained_sample_rate"] == 0.5
    assert cleaning["user_inputs"]["issue_time_truncation_ready"] is True
    assert sensitivity["main_hold_seconds"] == 12
    assert set(sensitivity["hold_thresholds_seconds"]) == {4, 12, 60}
    assert boundary["positive_points_excluded"] == 2
    assert boundary["current_integral_share"] > 0
    assert len(accumulator.power_sessions) == 1


def test_cleaning_accumulator_fails_when_user_input_cannot_be_issue_time_truncated() -> None:
    policy = CleaningPolicy(current_mode_s=4, pilot_mode_s=4)
    raw = _raw_record()
    raw["userInputs"] = [{"modifiedAt": "not-a-time", "kWhRequested": 10.0}]
    cleaned = clean_session(raw, session_index=0, policy=policy)
    accumulator = CleaningAccumulator(policy)

    accumulator.add(cleaned, raw)

    qa = accumulator.cleaning_qa(expected_sessions=1)
    assert qa["status"] == "FAIL"
    assert qa["user_inputs"]["unparseable_modified_count"] == 1
    assert qa["user_inputs"]["issue_time_truncation_ready"] is False


def test_cleaning_accumulator_rejects_non_list_user_input_container() -> None:
    policy = CleaningPolicy(current_mode_s=4, pilot_mode_s=4)
    raw = _raw_record()
    raw["userInputs"] = {"modifiedAt": _stamp(2)}
    cleaned = clean_session(raw, session_index=0, policy=policy)
    accumulator = CleaningAccumulator(policy)

    accumulator.add(cleaned, raw)

    qa = accumulator.cleaning_qa(expected_sessions=1)
    assert qa["status"] == "FAIL"
    assert qa["user_inputs"]["unparseable_modified_count"] == 1


def test_deterministic_gzip_jsonl_is_repeatable_and_round_trips() -> None:
    rows = [{"b": 2, "a": 1}, {"a": 3}]

    first = _deterministic_gzip_jsonl_bytes(rows)
    second = _deterministic_gzip_jsonl_bytes(rows)

    assert first == second
    with gzip.open(io.BytesIO(first), "rt", encoding="utf-8") as handle:
        assert [json.loads(line) for line in handle] == rows


def test_deterministic_npz_has_no_pickle_and_repeatable_bytes() -> None:
    arrays = {
        "issue_time": np.array([1, 2], dtype=np.int64),
        "history": np.array([[1.0, np.nan]], dtype=np.float32),
    }

    first = _deterministic_npz_bytes(arrays)
    second = _deterministic_npz_bytes(arrays)

    assert first == second
    with np.load(io.BytesIO(first), allow_pickle=False) as stored:
        np.testing.assert_array_equal(stored["issue_time"], arrays["issue_time"])
        np.testing.assert_allclose(stored["history"], arrays["history"], equal_nan=True)


def _safe_unhashed_public_contents() -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for name in PUBLIC_ARTIFACT_NAMES[:-1]:
        if name.endswith(".json"):
            result[name] = b'{"status":"PASS"}\n'
        elif name.endswith(".yaml"):
            result[name] = b"status: PASS\n"
        else:
            result[name] = b"# Aggregate decision\n\nStatus: PASS\n"
    return result


def test_closed_public_release_hashes_exactly_twelve_payloads() -> None:
    contents = close_public_artifacts(_safe_unhashed_public_contents())

    assert set(contents) == set(PUBLIC_ARTIFACT_NAMES)
    lines = contents["SHA256SUMS"].decode("utf-8").splitlines()
    assert len(lines) == 12
    for line in lines:
        digest, name = line.split("  ", 1)
        assert digest == hashlib.sha256(contents[name]).hexdigest()


def test_real_public_payload_composition_passes_its_privacy_gate() -> None:
    issue_qa = {
        "leakage_audit": "PASS",
        "future_fields_found": [],
        "unexpected_feature_keys": [],
        "temporal_violations": {"total": 0},
        "user_inputs_issue_time_truncation": {"status": "PASS"},
        "feature_whitelist_enforcement": {"status": "PASS"},
    }
    power_audit = audit_power_semantics(
        [
            PowerAuditSession(
                space_id="AG-1F01",
                ampere_hours=3.0,
                kwh_delivered=0.624,
                current_coverage=1.0,
                is_weekend=False,
            )
        ]
    )
    payloads = _public_payloads(
        cleaning_qa={"status": "PASS"},
        cleaning_sensitivity={"status": "PASS"},
        boundary_audit={"status": "PASS"},
        power_audit=power_audit,
        station_qa={"status": "PASS"},
        issue_qa=issue_qa,
        snapshot_manifest={"status": "PASS"},
        run_manifest={"status": "PASS"},
    )

    closed = close_public_artifacts(payloads)
    assert set(closed) == set(PUBLIC_ARTIFACT_NAMES)


def test_public_release_is_atomic_and_verifiable(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    output_root = tmp_path / "public"
    raw_root.mkdir()
    contents = close_public_artifacts(_safe_unhashed_public_contents())

    publish_public_release(contents, output_root=output_root, raw_root=raw_root)

    assert verify_public_release(output_root)
    assert sorted(path.name for path in output_root.iterdir()) == sorted(PUBLIC_ARTIFACT_NAMES)

    unexpected = output_root / "unexpected"
    unexpected.mkdir()
    assert verify_public_release(output_root) is False


def test_public_release_refuses_to_replace_unrelated_existing_content(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    output_root = tmp_path / "chosen-output"
    raw_root.mkdir()
    output_root.mkdir()
    unrelated = output_root / "keep-me.txt"
    unrelated.write_text("user-owned", encoding="utf-8")
    contents = close_public_artifacts(_safe_unhashed_public_contents())

    with pytest.raises(ValueError, match="unrelated"):
        publish_public_release(contents, output_root=output_root, raw_root=raw_root)

    assert unrelated.read_text(encoding="utf-8") == "user-owned"


def test_output_topology_rejects_raw_ancestors_descendants_and_overlap(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "scope" / "raw"
    raw.mkdir(parents=True)
    with pytest.raises(ValueError, match="raw and output"):
        _validate_output_topology(raw, (raw / "interim", tmp_path / "p", tmp_path / "o"))
    with pytest.raises(ValueError, match="raw and output"):
        _validate_output_topology(raw, (tmp_path / "scope", tmp_path / "p", tmp_path / "o"))
    with pytest.raises(ValueError, match="non-overlapping"):
        _validate_output_topology(
            raw,
            (tmp_path / "interim", tmp_path / "interim" / "processed", tmp_path / "o"),
        )


def test_frozen_protocol_is_closed_and_content_addressed() -> None:
    protocol, digest = _load_protocol("code/configs/acn_jpl_gate1_prep_2019-05.yaml")

    assert protocol["cleaning"]["expected_sampling_mode_seconds"] == 4
    assert protocol["aggregation"]["coverage_thresholds"] == [0.8, 0.9, 0.95]
    assert protocol["snapshots"]["horizons_minutes"] == [15, 30, 60, 120, 240]
    assert len(digest) == 64
