from __future__ import annotations

import copy
import gc
import gzip
import hashlib
import json
import math
import pickle
import shutil
import weakref
from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from evcf.data import acn_jpl_full_month_qa as full_qa_module
from evcf.data import acn_jpl_full_month_ts as full_ts_module
from evcf.data import acn_jpl_month_config as month_config_module
from evcf.data import acn_jpl_seasonal_acquisition as seasonal_acquisition_module
from evcf.data.acn_api import ACNClient, ACNQuery
from evcf.data.acn_jpl_full_month_qa import (
    PUBLIC_ARTIFACT_NAMES,
    _safe_rate,
    audit_quality_records,
    generate_full_month_timeseries_qa,
    generate_month_timeseries_qa,
    verify_public_artifact_hashes,
)
from evcf.data.acn_jpl_full_month_ts import run_full_month_timeseries
from evcf.data.acn_jpl_gate0 import chunk_paths, jpl_analysis_windows
from evcf.data.acn_jpl_month_config import (
    CompleteMetadataScope,
    jpl_month_config,
    load_verified_complete_metadata,
)
from evcf.data.acn_jpl_official_reference import probe_official_local_month_total
from evcf.data.acn_jpl_seasonal_acquisition import MonthAcquisitionResult, acquire_jpl_month

ZONE = ZoneInfo("America/Los_Angeles")


def _stamp(value: datetime) -> str:
    return format_datetime(value.astimezone(timezone.utc), usegmt=True)


def _samples(start: datetime, *, count: int = 20) -> list[str]:
    return [_stamp(start + timedelta(seconds=6 * index)) for index in range(count)]


def _record(index: int, connection: datetime) -> dict[str, Any]:
    timestamps = _samples(connection)
    return {
        "_id": f"private-object-{index}",
        "sessionID": f"private-session-{index}",
        "userID": f"private-user-{index}",
        "connectionTime": _stamp(connection),
        "disconnectTime": _stamp(connection + timedelta(minutes=2)),
        "doneChargingTime": _stamp(connection + timedelta(minutes=1)),
        "chargingCurrent": {"timestamps": timestamps, "current": [16.0] * len(timestamps)},
        "pilotSignal": {"timestamps": timestamps, "pilot": [16.0] * len(timestamps)},
        "userInputs": [
            {
                "requestedDeparture": _stamp(connection + timedelta(hours=2)),
                "kWhRequested": 12.0,
            }
        ],
    }


def _scope_records() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    first = _record(1, datetime(2019, 5, 2, 8, tzinfo=timezone.utc))
    second = _record(2, datetime(2019, 5, 3, 8, tzinfo=timezone.utc))
    carry = _record(3, datetime(2019, 5, 1, 0, 30, tzinfo=timezone.utc))
    carry["disconnectTime"] = "Wed, 01 May 2019 08:00:00 GMT"
    carry["doneChargingTime"] = "Wed, 01 May 2019 07:30:00 GMT"
    return [first, second, carry], carry


def _write_metadata(
    directory: Path,
    records: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory.mkdir(parents=True)
    data_path = directory / "history-000.jsonl.gz"
    with gzip.open(data_path, "wt", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
    manifest = {
        "schema_version": 1,
        "endpoint": "sessions/jpl",
        "site": "jpl",
        "mode": "metadata",
        "record_count": len(records),
        "source_total": len(records),
        "sha256": digest,
    }
    data_path.with_name(data_path.name + ".manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    inventory = hashlib.sha256()
    inventory.update(f"{data_path.name}\0{digest}\0{len(records)}\n".encode())
    monkeypatch.setattr(full_ts_module, "EXPECTED_COMPLETE_METADATA_FILE_COUNT", 1)
    monkeypatch.setattr(full_ts_module, "EXPECTED_COMPLETE_METADATA_RECORD_COUNT", 3)
    monkeypatch.setattr(full_ts_module, "EXPECTED_ANALYSIS_SESSION_COUNT", 2)
    monkeypatch.setattr(full_ts_module, "EXPECTED_UTC_MONTH_SESSION_COUNT", 3)
    monkeypatch.setattr(full_ts_module, "EXPECTED_CARRY_IN_SESSION_COUNT", 1)
    monkeypatch.setattr(
        full_ts_module,
        "EXPECTED_COMPLETE_METADATA_INVENTORY_DIGEST",
        inventory.hexdigest(),
    )


def _page(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"_items": items, "_links": {}, "_meta": {"total": len(items)}}


class _SyntheticClient:
    def __init__(self, local_records: list[dict[str, Any]], carry: dict[str, Any]) -> None:
        self.local_records = local_records
        self.carry = carry

    def iter_pages(self, query: ACNQuery):  # type: ignore[no-untyped-def]
        if query.session_id is not None:
            yield _page([self.carry])
            return
        day = query.start.astimezone(ZONE).date().isoformat()
        yield _page(
            [
                record
                for record in self.local_records
                if datetime.strptime(record["connectionTime"], "%a, %d %b %Y %H:%M:%S GMT")
                .replace(tzinfo=timezone.utc)
                .astimezone(ZONE)
                .date()
                .isoformat()
                == day
            ]
        )


def _pass_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path, dict[str, Any]]:
    records, carry = _scope_records()
    metadata_root = tmp_path / "metadata"
    raw_root = tmp_path / "raw"
    output_root = tmp_path / "public"
    _write_metadata(metadata_root, records, monkeypatch)
    client = _SyntheticClient(records[:-1], carry)
    acquisition = run_full_month_timeseries(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=raw_root,
        client_factory=lambda: client,
    )
    assert acquisition["status"] == "COMPLETE"
    return metadata_root, raw_root, output_root, acquisition


def _read_day_records(raw_root: Path, day: str) -> tuple[Path, Path, list[dict[str, Any]]]:
    window = next(window for window in jpl_analysis_windows() if window.day_key == day)
    data_path, manifest_path = chunk_paths(raw_root, "timeseries", window)
    with gzip.open(data_path, "rt", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    return data_path, manifest_path, records


def _rewrite_day(
    raw_root: Path,
    day: str,
    records: list[dict[str, Any]],
    *,
    remote_total: int | None = None,
) -> None:
    data_path, manifest_path, _ = _read_day_records(raw_root, day)
    with (
        data_path.open("wb") as raw_handle,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as handle,
    ):
        for record in records:
            handle.write((json.dumps(record, sort_keys=True) + "\n").encode())
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["record_count"] = len(records)
    manifest["remote_total_reported"] = len(records) if remote_total is None else remote_total
    manifest["sha256"] = hashlib.sha256(data_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _run_qa(
    metadata_root: Path,
    raw_root: Path,
    output_root: Path,
    acquisition: dict[str, Any],
):  # type: ignore[no-untyped-def]
    return generate_full_month_timeseries_qa(
        metadata_root=metadata_root,
        raw_root=raw_root,
        output_root=output_root,
        acquisition_result=acquisition,
        expected_local_sessions=2,
        expected_utc_sessions=3,
        expected_carry_sessions=1,
        expected_total_sessions=3,
    )


def _public_validation_bundle(
    output_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    contents = {
        name: (output_root / name).read_bytes() for name in full_qa_module._HASHED_ARTIFACT_NAMES
    }
    payloads = [
        json.loads(contents[name])
        for name in (
            "qa_full_month_timeseries.json",
            "acquisition_summary.json",
            "cleaning_rule_manifest.json",
        )
    ]
    return payloads, contents


def _release_snapshot(root: Path) -> dict[str, bytes]:
    return {name: (root / name).read_bytes() for name in full_qa_module.PUBLIC_ARTIFACT_NAMES}


def test_full_pass_emits_exact_verified_aggregate_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)

    result = _run_qa(metadata_root, raw_root, output_root, acquisition)

    assert result.gate_status == "PASS"
    assert {path.name for path in output_root.iterdir()} == set(PUBLIC_ARTIFACT_NAMES)
    assert verify_public_artifact_hashes(output_root)
    qa = json.loads((output_root / "qa_full_month_timeseries.json").read_text())
    assert qa["integrity"]["daily_chunks"]["valid"] == 31
    assert qa["integrity"]["local_month"]["observed_records"] == 2
    assert qa["integrity"]["local_month"]["unique_object_keys"] == 2
    assert qa["integrity"]["local_month"]["unique_session_keys"] == 2
    assert qa["integrity"]["local_month"]["matched_metadata_pairs"] == 2
    assert qa["integrity"]["local_month"]["missing_metadata_pairs"] == 0
    assert qa["integrity"]["local_month"]["orphan_timeseries_pairs"] == 0
    assert qa["integrity"]["carry_in"]["observed_records"] == 1
    assert qa["integrity"]["combined"]["observed_records"] == 3
    assert qa["integrity"]["month_boundary"]["local_month_sessions"] == 2
    assert qa["integrity"]["month_boundary"]["utc_month_sessions"] == 3
    assert qa["quality"]["denominator_sessions"] == 3
    assert qa["gate"]["ready_for_cleaning"] is True
    assert qa["gate"]["ready_for_15_min"] == "YES_CURRENT_PROXY_ONLY"
    assert qa["gate"]["gate1_ready"] == "NO"

    markdown = (output_root / "acquisition_summary.md").read_text(encoding="utf-8")
    assert "measured current in amperes" in markdown
    assert "not direct kW" in markdown
    assert "pilotSignal is a control signal" in markdown
    assert "voltage, phase, topology, power factor, and network context" in markdown


def test_quality_metrics_cover_structural_temporal_and_metadata_anomalies() -> None:
    connection = datetime(2019, 5, 2, 8, tzinfo=timezone.utc)
    first = _record(1, connection)
    first["doneChargingTime"] = _stamp(connection - timedelta(minutes=1))
    first["chargingCurrent"] = {
        "timestamps": [
            _stamp(connection),
            _stamp(connection),
            "Thu, 02 May 2019 09:00:06 +0100",
            _stamp(connection + timedelta(seconds=12)),
            "not-a-time",
            _stamp(connection + timedelta(minutes=2)),
        ],
        "current": [1.0, 1.0, "bad", -1.0, 1.0, 2.0],
    }
    second = _record(2, connection + timedelta(days=1))
    second["doneChargingTime"] = _stamp(connection + timedelta(days=1, minutes=3))
    second["pilotSignal"] = {"timestamps": [_stamp(connection)], "pilot": [1.0, 2.0]}
    second["userInputs"] = []

    quality = audit_quality_records([first, second], denominator=2)

    current = quality["series"]["chargingCurrent"]
    pilot = quality["series"]["pilotSignal"]
    assert current["field_coverage"] == {"count": 2, "denominator": 2, "rate": 1.0}
    assert current["duplicate_extra_timestamps"] == 1
    assert current["duplicate_affected_sessions"] == 1
    assert current["duplicate_affected_session_rate"] == 0.5
    assert current["timestamp_parse_errors"] == 1
    assert current["non_utc_timestamp_encodings"] == 1
    assert current["nonnumeric_values"] == 1
    assert current["negative_values"] == 1
    assert current["raw_samples"] == 26
    assert current["usable_samples"] < current["raw_samples"]
    assert current["retained_sample_rate"] is not None
    assert current["expected_complete_active_minutes"] == 4
    assert current["sparse_minutes_under_10_points"] > 0
    assert current["boundary_positive_points"] == 1
    assert current["boundary_positive_sessions"] == 1
    assert current["boundary_positive_session_rate"] == 0.5
    assert pilot["invalid_container_count"] == 1
    assert pilot["invalid_container_rate"] == 0.5
    assert pilot["timestamp_value_length_mismatch_sessions"] == 1
    metadata = quality["metadata_fields"]
    assert metadata["done_charging_before_connection"]["count"] == 1
    assert metadata["done_charging_after_disconnect"]["count"] == 1
    assert metadata["user_inputs_coverage"]["count"] == 1
    assert metadata["requested_departure_coverage"]["count"] == 1
    assert metadata["kwh_requested_coverage"]["count"] == 1


def test_zero_denominator_rates_are_null() -> None:
    assert _safe_rate(0, 0) is None
    assert _safe_rate(1, 0) is None
    quality = audit_quality_records([], denominator=0)
    assert quality["series"]["chargingCurrent"]["field_coverage"]["rate"] is None
    assert quality["series"]["chargingCurrent"]["invalid_container_rate"] is None


def test_duplicate_record_keys_fail_integrity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _, _, records = _read_day_records(raw_root, "2019-05-02")
    _rewrite_day(raw_root, "2019-05-02", records + [dict(records[0])])

    result = _run_qa(metadata_root, raw_root, output_root, acquisition)

    assert result.gate_status == "FAIL"
    qa = result.qa
    assert qa["integrity"]["local_month"]["duplicate_object_key_records"] == 1
    assert qa["integrity"]["local_month"]["duplicate_session_key_records"] == 1


def test_metadata_timeseries_missing_and_orphan_pairs_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _, _, records = _read_day_records(raw_root, "2019-05-02")
    records[0]["_id"] = "private-orphan-object"
    records[0]["sessionID"] = "private-orphan-session"
    _rewrite_day(raw_root, "2019-05-02", records)

    result = _run_qa(metadata_root, raw_root, output_root, acquisition)

    local = result.qa["integrity"]["local_month"]
    assert result.gate_status == "FAIL"
    assert local["matched_metadata_pairs"] == 1
    assert local["missing_metadata_pairs"] == 1
    assert local["orphan_timeseries_pairs"] == 1
    assert local["metadata_timeseries_match_rate"] == 0.5


def test_carry_in_mismatch_fails_and_still_writes_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    manifest_path = raw_root / "manifests" / "carry_in" / "carry_in.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["remote_total_reported"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = _run_qa(metadata_root, raw_root, output_root, acquisition)

    assert result.gate_status == "FAIL"
    assert result.qa["integrity"]["carry_in"]["status"] == "FAIL"
    assert set(PUBLIC_ARTIFACT_NAMES) == {path.name for path in output_root.iterdir()}
    assert verify_public_artifact_hashes(output_root)


@pytest.mark.parametrize("field", ["record_count", "remote_total_reported"])
def test_carry_in_boolean_count_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    manifest_path = raw_root / "manifests" / "carry_in" / "carry_in.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = _run_qa(metadata_root, raw_root, output_root, acquisition)

    assert result.gate_status == "FAIL"
    assert result.qa["integrity"]["carry_in"]["status"] == "FAIL"


def test_failed_staging_write_preserves_previous_public_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    output_root.mkdir()
    previous = b"previous-complete-release\n"
    previous_path = output_root / "qa_full_month_timeseries.json"
    previous_path.write_bytes(previous)
    original_write = full_qa_module._atomic_write_bytes
    calls = 0

    def fail_second_write(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic staged write failure")
        original_write(path, data)

    monkeypatch.setattr(full_qa_module, "_atomic_write_bytes", fail_second_write)

    with pytest.raises(OSError, match="synthetic staged write failure"):
        _run_qa(metadata_root, raw_root, output_root, acquisition)

    assert previous_path.read_bytes() == previous
    assert not list(output_root.parent.glob(f".{output_root.name}.partial-*"))


@pytest.mark.parametrize(
    "corruption",
    ["manifest", "hash", "json", "remote"],
)
def test_daily_manifest_hash_json_and_remote_mismatches_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    data_path, manifest_path, records = _read_day_records(raw_root, "2019-05-02")
    if corruption == "manifest":
        manifest_path.write_text("not-json", encoding="utf-8")
    elif corruption == "hash":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif corruption == "json":
        with gzip.open(data_path, "wt", encoding="utf-8") as handle:
            handle.write("not-json\n")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["sha256"] = hashlib.sha256(data_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        _rewrite_day(raw_root, "2019-05-02", records, remote_total=99)

    result = _run_qa(metadata_root, raw_root, output_root, acquisition)

    assert result.gate_status == "FAIL"
    assert result.qa["integrity"]["daily_chunks"]["valid"] == 30
    failed_csv = (output_root / "failed_or_incomplete_chunks.csv").read_text()
    assert "2019-05-02" in failed_csv


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("source", None),
        ("source", "untrusted mirror"),
        ("dataset_id", "D9999"),
        ("output_file", "forged.jsonl.gz"),
        ("downloaded_at_utc", None),
        ("downloaded_at_utc", "2026-01-01T00:00:00"),
        ("downloaded_at_utc", "2026-01-01T08:00:00+08:00"),
        ("downloaded_at_utc", "not-a-timestamp"),
        ("downloaded_at_utc", True),
    ],
)
def test_daily_provenance_manifest_mismatch_fails_full_qa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    tampered_value: object,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _, manifest_path, _ = _read_day_records(raw_root, "2019-05-02")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tampered_value is None:
        manifest.pop(field)
    else:
        manifest[field] = tampered_value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = _run_qa(metadata_root, raw_root, output_root, acquisition)

    assert result.gate_status == "FAIL"
    assert result.qa["integrity"]["daily_chunks"]["valid"] == 30


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("source", None),
        ("source", "untrusted mirror"),
        ("dataset_id", "D9999"),
        ("output_file", "forged.jsonl.gz"),
        ("timezone", "UTC"),
        ("local_start_inclusive", "2019-04-30T17:31:00-07:00"),
        ("local_end_exclusive", "2019-05-01T00:01:00-07:00"),
        ("utc_start_inclusive", "2019-05-01T00:31:00+00:00"),
        ("utc_end_exclusive", "2019-05-01T07:01:00+00:00"),
        ("downloaded_at_utc", None),
        ("downloaded_at_utc", "2026-01-01T00:00:00"),
        ("downloaded_at_utc", "2026-01-01T08:00:00+08:00"),
        ("downloaded_at_utc", "not-a-timestamp"),
        ("downloaded_at_utc", True),
    ],
)
def test_carry_in_manifest_contract_mismatch_fails_full_qa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    tampered_value: object,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    manifest_path = raw_root / "manifests" / "carry_in" / "carry_in.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tampered_value is None:
        manifest.pop(field)
    else:
        manifest[field] = tampered_value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = _run_qa(metadata_root, raw_root, output_root, acquisition)

    assert result.gate_status == "FAIL"
    assert result.qa["integrity"]["carry_in"]["status"] == "FAIL"


@pytest.mark.parametrize("field", ["chargingCurrent", "pilotSignal"])
def test_invalid_container_rate_above_limit_fails_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    data_path, _, records = _read_day_records(raw_root, "2019-05-02")
    del data_path
    records[0][field] = None
    _rewrite_day(raw_root, "2019-05-02", records)

    result = _run_qa(metadata_root, raw_root, output_root, acquisition)

    assert result.gate_status == "FAIL"
    assert result.qa["quality"]["series"][field]["invalid_container_rate"] == pytest.approx(
        1 / 3, abs=1e-8
    )


@pytest.mark.parametrize("anomaly", ["parse", "nonmonotonic"])
def test_severe_timestamp_anomalies_fail_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    anomaly: str,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _, _, records = _read_day_records(raw_root, "2019-05-02")
    timestamps = records[0]["chargingCurrent"]["timestamps"]
    if anomaly == "parse":
        timestamps[0] = "not-a-time"
    else:
        timestamps[1], timestamps[2] = timestamps[2], timestamps[1]
    _rewrite_day(raw_root, "2019-05-02", records)

    result = _run_qa(metadata_root, raw_root, output_root, acquisition)

    assert result.gate_status == "FAIL"
    assert result.qa["gate"]["checks"][f"zero_timestamp_{anomaly}_anomalies"] is False


def test_duplicate_timestamps_and_boundary_positive_points_warn_without_failing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _, _, records = _read_day_records(raw_root, "2019-05-02")
    current = records[0]["chargingCurrent"]
    current["timestamps"].insert(1, current["timestamps"][0])
    current["current"].insert(1, current["current"][0])
    current["timestamps"].append(records[0]["disconnectTime"])
    current["current"].append(2.0)
    _rewrite_day(raw_root, "2019-05-02", records)

    result = _run_qa(metadata_root, raw_root, output_root, acquisition)

    assert result.gate_status == "PASS"
    series = result.qa["quality"]["series"]["chargingCurrent"]
    assert series["duplicate_extra_timestamps"] == 1
    assert series["boundary_positive_points"] == 1
    assert "DUPLICATE_TIMESTAMPS" in result.qa["gate"]["warnings"]
    assert "BOUNDARY_POSITIVE_CURRENT" in result.qa["gate"]["warnings"]


def test_public_artifacts_exclude_identifiers_secrets_paths_and_trajectories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    sentinel = "fixture-secret-sentinel"
    data_path, _, records = _read_day_records(raw_root, "2019-05-02")
    del data_path
    records[0]["_id"] = f"object-{sentinel}"
    records[0]["sessionID"] = f"session-{sentinel}"
    records[0]["userID"] = f"user-{sentinel}"
    _rewrite_day(raw_root, "2019-05-02", records)

    _run_qa(metadata_root, raw_root, output_root, acquisition)

    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="strict") for path in output_root.iterdir()
    )
    for forbidden in (
        sentinel,
        "sessionID",
        '"_id"',
        "userID",
        "query_condition",
        "C:\\Users\\",
        "/home/",
        "/tmp/",
        '"timestamps"',
        '"values"',
    ):
        assert forbidden not in combined


def test_closed_json_schema_rejects_unknown_identifier_key_and_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _run_qa(metadata_root, raw_root, output_root, acquisition)
    payloads, contents = _public_validation_bundle(output_root)
    payloads[0]["record_ids"] = ["private-object-123"]
    contents["qa_full_month_timeseries.json"] = (
        json.dumps(payloads[0], sort_keys=True) + "\n"
    ).encode()

    with pytest.raises(ValueError, match="schema"):
        full_qa_module._validate_public_contents(payloads, contents, ())


def test_closed_json_schema_rejects_unknown_identifier_style_allowed_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _run_qa(metadata_root, raw_root, output_root, acquisition)
    payloads, contents = _public_validation_bundle(output_root)
    payloads[1]["acquisition"]["status"] = "private-object-123"
    contents["acquisition_summary.json"] = (json.dumps(payloads[1], sort_keys=True) + "\n").encode()

    with pytest.raises(ValueError, match="schema"):
        full_qa_module._validate_public_contents(payloads, contents, ())


@pytest.mark.parametrize("absolute_path", ["/opt/private/raw/session.json", "/data/raw/x"])
def test_text_privacy_rejects_generic_posix_absolute_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    absolute_path: str,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _run_qa(metadata_root, raw_root, output_root, acquisition)
    payloads, contents = _public_validation_bundle(output_root)
    contents["acquisition_summary.md"] += f"\ndiagnostic: {absolute_path}\n".encode()

    with pytest.raises(ValueError, match="absolute local path"):
        full_qa_module._validate_public_contents(payloads, contents, ())


@pytest.mark.parametrize(
    "csv_name",
    ["daily_chunk_summary.csv", "failed_or_incomplete_chunks.csv"],
)
def test_closed_csv_schema_rejects_extra_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    csv_name: str,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _run_qa(metadata_root, raw_root, output_root, acquisition)
    payloads, contents = _public_validation_bundle(output_root)
    lines = contents[csv_name].decode().splitlines()
    lines[0] += ",record_ids"
    contents[csv_name] = ("\n".join(lines) + "\n").encode()

    with pytest.raises(ValueError, match="CSV schema"):
        full_qa_module._validate_public_contents(payloads, contents, ())


def test_publish_rename_of_previous_release_failure_preserves_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _run_qa(metadata_root, raw_root, output_root, acquisition)
    contents = _release_snapshot(output_root)
    previous = copy.deepcopy(contents)
    original_replace = full_qa_module.os.replace

    def fail_previous_rename(source: Any, destination: Any) -> None:
        if Path(source) == output_root and ".previous-" in Path(destination).name:
            raise OSError("synthetic previous rename failure")
        original_replace(source, destination)

    monkeypatch.setattr(full_qa_module.os, "replace", fail_previous_rename)

    with pytest.raises(OSError, match="previous rename"):
        full_qa_module._publish_artifact_release(output_root, contents)

    assert _release_snapshot(output_root) == previous
    assert not list(output_root.parent.glob(f".{output_root.name}.previous-*"))


def test_publish_stage_rename_failure_restores_previous_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _run_qa(metadata_root, raw_root, output_root, acquisition)
    contents = _release_snapshot(output_root)
    previous = copy.deepcopy(contents)
    original_replace = full_qa_module.os.replace

    def fail_stage_rename(source: Any, destination: Any) -> None:
        source_path = Path(source)
        if source_path.is_dir() and ".partial-" in source_path.name:
            raise OSError("synthetic stage rename failure")
        original_replace(source, destination)

    monkeypatch.setattr(full_qa_module.os, "replace", fail_stage_rename)

    with pytest.raises(OSError, match="stage rename"):
        full_qa_module._publish_artifact_release(output_root, contents)

    assert _release_snapshot(output_root) == previous
    assert not list(output_root.parent.glob(f".{output_root.name}.previous-*"))


def test_post_publish_verification_failure_restores_previous_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _run_qa(metadata_root, raw_root, output_root, acquisition)
    contents = _release_snapshot(output_root)
    previous = copy.deepcopy(contents)
    verification_calls = 0

    def fail_post_publish_verification(root: Any) -> bool:
        nonlocal verification_calls
        verification_calls += 1
        return verification_calls == 1

    monkeypatch.setattr(
        full_qa_module,
        "verify_public_artifact_hashes",
        fail_post_publish_verification,
    )

    with pytest.raises(OSError, match="published public artifact"):
        full_qa_module._publish_artifact_release(output_root, contents)

    assert _release_snapshot(output_root) == previous
    assert not list(output_root.parent.glob(f".{output_root.name}.previous-*"))


def test_rollback_cleanup_failure_preserves_recoverable_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _run_qa(metadata_root, raw_root, output_root, acquisition)
    contents = _release_snapshot(output_root)
    previous = copy.deepcopy(contents)
    verification_calls = 0
    original_rmtree = full_qa_module.shutil.rmtree

    def fail_post_publish_verification(root: Any) -> bool:
        nonlocal verification_calls
        verification_calls += 1
        return verification_calls == 1

    def fail_new_release_cleanup(path: Any) -> None:
        if Path(path) == output_root:
            raise OSError("synthetic rollback cleanup failure")
        original_rmtree(path)

    monkeypatch.setattr(
        full_qa_module,
        "verify_public_artifact_hashes",
        fail_post_publish_verification,
    )
    monkeypatch.setattr(full_qa_module.shutil, "rmtree", fail_new_release_cleanup)

    with pytest.raises(OSError, match="rollback cleanup"):
        full_qa_module._publish_artifact_release(output_root, contents)

    backups = list(output_root.parent.glob(f".{output_root.name}.previous-*"))
    assert len(backups) == 1
    assert _release_snapshot(backups[0]) == previous


def test_rollback_restore_failure_preserves_recoverable_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _run_qa(metadata_root, raw_root, output_root, acquisition)
    contents = _release_snapshot(output_root)
    previous = copy.deepcopy(contents)
    verification_calls = 0
    original_replace = full_qa_module.os.replace

    def fail_post_publish_verification(root: Any) -> bool:
        nonlocal verification_calls
        verification_calls += 1
        return verification_calls == 1

    def fail_backup_restore(source: Any, destination: Any) -> None:
        if ".previous-" in Path(source).name and Path(destination) == output_root:
            raise OSError("synthetic backup restore failure")
        original_replace(source, destination)

    monkeypatch.setattr(
        full_qa_module,
        "verify_public_artifact_hashes",
        fail_post_publish_verification,
    )
    monkeypatch.setattr(full_qa_module.os, "replace", fail_backup_restore)

    with pytest.raises(OSError, match="backup restore"):
        full_qa_module._publish_artifact_release(output_root, contents)

    backups = list(output_root.parent.glob(f".{output_root.name}.previous-*"))
    assert not output_root.exists()
    assert len(backups) == 1
    assert _release_snapshot(backups[0]) == previous


def test_single_orphaned_previous_release_is_recovered_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _run_qa(metadata_root, raw_root, output_root, acquisition)
    contents = _release_snapshot(output_root)
    orphan = output_root.with_name(f".{output_root.name}.previous-orphan")
    output_root.rename(orphan)

    full_qa_module._publish_artifact_release(output_root, contents)

    assert full_qa_module.verify_public_artifact_hashes(output_root)
    assert not orphan.exists()
    assert not list(output_root.parent.glob(f".{output_root.name}.previous-*"))


@pytest.mark.parametrize("output_exists", [False, True])
def test_ambiguous_orphaned_previous_releases_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output_exists: bool,
) -> None:
    metadata_root, raw_root, output_root, acquisition = _pass_layout(tmp_path, monkeypatch)
    _run_qa(metadata_root, raw_root, output_root, acquisition)
    contents = _release_snapshot(output_root)
    first = output_root.with_name(f".{output_root.name}.previous-one")
    second = output_root.with_name(f".{output_root.name}.previous-two")
    shutil.copytree(output_root, first)
    if output_exists:
        shutil.copytree(output_root, second)
        previous = _release_snapshot(output_root)
    else:
        output_root.rename(second)
        previous = None

    with pytest.raises(OSError, match="orphaned previous"):
        full_qa_module._publish_artifact_release(output_root, contents)

    assert first.is_dir()
    assert second.is_dir()
    if output_exists:
        assert _release_snapshot(output_root) == previous
    else:
        assert not output_root.exists()


class _GenericProbeResponse:
    status_code = 200

    def __init__(self, total: int) -> None:
        self.total = total

    def json(self) -> dict[str, Any]:
        return {"_meta": {"total": self.total}}

    def raise_for_status(self) -> None:
        return None


class _GenericProbeSession:
    def __init__(self, total: int) -> None:
        self.total = total
        self.auth: tuple[str, str] | None = None
        self.headers: dict[str, str] = {}
        self.calls = 0

    def get(self, url: str, *, params: Any = None, timeout: Any = None) -> Any:
        del url, params, timeout
        self.calls += 1
        return _GenericProbeResponse(self.total)


class _GenericTimeseriesClient:
    def __init__(
        self,
        local_records: list[dict[str, Any]],
        carry_records: list[dict[str, Any]],
    ) -> None:
        self.local_records = tuple(local_records)
        self.carry_records = {record["sessionID"]: record for record in carry_records}

    def iter_pages(self, query: ACNQuery):  # type: ignore[no-untyped-def]
        if query.session_id is not None:
            items = [self.carry_records[query.session_id]]
        else:
            items = [
                record
                for record in self.local_records
                if query.start_utc
                <= datetime.strptime(record["connectionTime"], "%a, %d %b %Y %H:%M:%S GMT").replace(
                    tzinfo=timezone.utc
                )
                < query.end_utc
            ]
        yield _page(items)


def _generic_scope_and_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    month: str,
    carry_count: int,
    invalid_first: bool = False,
) -> tuple[Any, CompleteMetadataScope, Path, Any]:
    config = jpl_month_config(month)
    local_records = [
        _record(index + 200, config.utc_start + timedelta(days=index, minutes=1))
        for index in range(3)
    ]
    if invalid_first:
        local_records[0].pop("chargingCurrent")
        local_records[0].pop("pilotSignal")
    carry_records = [
        _record(index + 500, config.utc_start - timedelta(hours=index + 1))
        for index in range(carry_count)
    ]
    for index, record in enumerate(carry_records):
        record["disconnectTime"] = _stamp(config.utc_start + timedelta(minutes=index + 1))
        record["doneChargingTime"] = _stamp(config.utc_start)
    records = local_records + carry_records
    metadata_root = tmp_path / "metadata"
    metadata_root.mkdir(parents=True)
    data_path = metadata_root / "complete.jsonl.gz"
    with gzip.open(data_path, "wt", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
    data_path.with_name(data_path.name + ".manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "endpoint": "sessions/jpl",
                "site": "jpl",
                "mode": "metadata",
                "record_count": len(records),
                "source_total": len(records),
                "sha256": digest,
            }
        ),
        encoding="utf-8",
    )
    inventory = hashlib.sha256(f"{data_path.name}\0{digest}\0{len(records)}\n".encode()).hexdigest()
    monkeypatch.setattr(month_config_module, "EXPECTED_COMPLETE_METADATA_FILE_COUNT", 1)
    monkeypatch.setattr(
        month_config_module,
        "EXPECTED_COMPLETE_METADATA_RECORD_COUNT",
        len(records),
    )
    monkeypatch.setattr(
        month_config_module,
        "EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256",
        inventory,
    )
    scope = load_verified_complete_metadata(metadata_root, config)
    raw_root = tmp_path / "raw" / month
    reference = raw_root / "state" / "official.json"
    probe_session = _GenericProbeSession(scope.local_month_session_count)

    def live_probe(month_config: Any) -> Any:
        return probe_official_local_month_total(
            ACNClient("fixture-probe-token", session=probe_session),  # type: ignore[arg-type]
            reference,
            month=month_config,
        )

    acquisition = acquire_jpl_month(
        authorized=True,
        config=config,
        scope=scope,
        official_probe=live_probe,
        raw_root=raw_root,
        ts_client_factory=lambda: _GenericTimeseriesClient(
            local_records,
            carry_records,
        ),
        downloaded_at_utc=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    assert acquisition.status == "COMPLETE"
    assert probe_session.calls == 1
    return config, scope, raw_root, acquisition


@pytest.mark.parametrize(
    ("month", "carry_count"),
    [("2019-02", 0), ("2019-08", 1), ("2019-11", 2)],
)
def test_generic_month_qa_closes_dynamic_days_carry_linkage_and_raw_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    month: str,
    carry_count: int,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month=month,
        carry_count=carry_count,
    )

    result = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
    )

    integrity = result.qa["integrity"]
    assert result.gate_status == "PASS"
    assert result.artifact_names == ()
    assert integrity["daily_chunks"]["expected"] == config.day_count
    assert integrity["daily_chunks"]["valid"] == config.day_count
    assert integrity["local_month"]["observed_records"] == 3
    assert integrity["local_month"]["missing_metadata_pairs"] == 0
    assert integrity["local_month"]["orphan_timeseries_pairs"] == 0
    assert integrity["carry_in"]["observed_records"] == carry_count
    assert integrity["carry_in"]["missing_metadata_pairs"] == 0
    assert integrity["carry_in"]["orphan_timeseries_pairs"] == 0
    assert integrity["combined"]["observed_records"] == 3 + carry_count
    assert integrity["combined"]["unique_pair_count"] == 3 + carry_count
    assert integrity["raw_inventory"]["unchanged"] is True
    assert integrity["raw_inventory"]["sha256"] == acquisition.raw_inventory_sha256
    assert integrity["partial_file_count"] == 0
    for field in ("chargingCurrent", "pilotSignal"):
        rate = result.qa["quality"]["series"][field]["invalid_container_rate"]
        assert math.isfinite(rate)
        assert rate <= 0.10


def test_generic_month_qa_fails_when_both_invalid_container_rates_exceed_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
        invalid_first=True,
    )

    result = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
    )

    assert result.gate_status == "FAIL"
    checks = result.qa["gate"]["checks"]
    assert checks["current_invalid_rate_at_most_limit"] is False
    assert checks["pilot_invalid_rate_at_most_limit"] is False
    for field in ("chargingCurrent", "pilotSignal"):
        rate = result.qa["quality"]["series"][field]["invalid_container_rate"]
        assert rate == pytest.approx(1 / 3, abs=1e-8)
        assert math.isfinite(rate)


@pytest.mark.parametrize(
    "invalid_shape",
    ["absent", "non_mapping", "timestamps_non_list", "values_non_list", "length_mismatch"],
)
@pytest.mark.parametrize("field", ["chargingCurrent", "pilotSignal"])
def test_invalid_series_container_definition_is_closed(
    invalid_shape: str,
    field: str,
) -> None:
    record = _record(900, datetime(2019, 5, 2, 8, tzinfo=timezone.utc))
    value_key = "current" if field == "chargingCurrent" else "pilot"
    if invalid_shape == "absent":
        record.pop(field)
    elif invalid_shape == "non_mapping":
        record[field] = []
    elif invalid_shape == "timestamps_non_list":
        record[field]["timestamps"] = "not-a-list"
    elif invalid_shape == "values_non_list":
        record[field][value_key] = "not-a-list"
    else:
        record[field][value_key].pop()

    series = audit_quality_records([record], denominator=1)["series"][field]

    assert series["invalid_container_count"] == 1
    assert series["invalid_container_rate"] == 1.0


def test_generic_month_qa_detects_pair_orphans_even_with_valid_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=1,
    )
    data_path: Path | None = None
    for candidate in sorted((raw_root / "timeseries").glob("*.jsonl.gz")):
        with gzip.open(candidate, "rt", encoding="utf-8") as handle:
            if handle.read(1):
                data_path = candidate
                break
    assert data_path is not None
    with gzip.open(data_path, "rt", encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    records[0]["_id"] = "private-orphan-object"
    records[0]["sessionID"] = "private-orphan-session"
    with (
        data_path.open("wb") as raw_handle,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as handle,
    ):
        for record in records:
            handle.write((json.dumps(record, sort_keys=True) + "\n").encode())
    manifest_path = (
        raw_root
        / "manifests"
        / "timeseries"
        / data_path.name.replace(".jsonl.gz", ".manifest.json")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = hashlib.sha256(data_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
    )

    assert result.gate_status == "FAIL"
    assert result.qa["integrity"]["local_month"]["missing_metadata_pairs"] == 1
    assert result.qa["integrity"]["local_month"]["orphan_timeseries_pairs"] == 1


def test_generic_month_qa_rejects_extra_raw_and_partial_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
    )
    extra = raw_root / "timeseries" / "nested" / "extra.jsonl.gz"
    extra.parent.mkdir()
    extra.write_bytes(b"not-valid")
    partial = raw_root / "state" / "private.partial"
    partial.write_text("sentinel-partial-token", encoding="utf-8")

    result = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
        sensitive_values=("sentinel-partial-token",),
    )

    assert result.gate_status == "FAIL"
    assert "RAW_SNAPSHOT_INVALID" in result.qa["gate"]["reason_codes"]
    assert result.qa["integrity"]["partial_file_count"] == 1
    assert "sentinel-partial-token" not in repr(result)


@pytest.mark.parametrize("target", ["daily_manifest", "unrelated_state", "official"])
def test_generic_month_qa_requires_closed_raw_and_state_documents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=1,
    )
    sentinel = f"sentinel-{target}-token"
    if target == "daily_manifest":
        path = min((raw_root / "manifests" / "timeseries").glob("*.manifest.json"))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["token"] = sentinel
        path.write_text(json.dumps(payload), encoding="utf-8")
    elif target == "unrelated_state":
        (raw_root / "state" / "unrelated.json").write_text(
            json.dumps({"token": sentinel}), encoding="utf-8"
        )
    else:
        path = next(
            path for path in (raw_root / "state").glob("*.json") if path.name != "progress.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["token"] = sentinel
        path.write_text(json.dumps(payload), encoding="utf-8")

    result = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
        sensitive_values=(sentinel,),
    )

    assert result.gate_status == "FAIL"
    assert "RAW_SNAPSHOT_INVALID" in result.qa["gate"]["reason_codes"]
    assert sentinel not in repr(result)


@pytest.mark.parametrize(
    "first_record_count",
    [1, 999],
    ids=["same-value", "last-value-correct"],
)
def test_generic_month_qa_rejects_duplicate_key_carry_manifests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_record_count: int,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=1,
    )
    manifest = raw_root / "manifests" / "carry_in" / "carry-0001.manifest.json"
    original = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        original.replace(
            "{",
            f'{{\n  "record_count": {first_record_count},',
            1,
        ),
        encoding="utf-8",
    )
    acquisition_payload = acquisition.public_dict()
    acquisition_payload["raw_inventory_sha256"] = (
        full_qa_module.canonical_seasonal_inventory(raw_root).digest
    )

    result = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition_payload,
    )

    assert result.gate_status == "FAIL"
    assert result.qa["gate"]["checks"]["raw_snapshot_valid"] is False
    assert "RAW_SNAPSHOT_INVALID" in result.qa["gate"]["reason_codes"]


def test_generic_month_qa_detects_raw_mutation_during_read_only_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
    )
    data_path = min((raw_root / "timeseries").glob("*.jsonl.gz"))
    original = full_qa_module.iter_validated_raw_records

    def mutating_records(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        yield from original(*args, **kwargs)
        data_path.write_bytes(data_path.read_bytes() + b"changed")

    monkeypatch.setattr(full_qa_module, "iter_validated_raw_records", mutating_records)

    result = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
    )

    assert result.gate_status == "FAIL"
    assert result.qa["integrity"]["raw_inventory"]["unchanged"] is False
    assert "RAW_SNAPSHOT_CHANGED" in result.qa["gate"]["reason_codes"]


def _assert_seasonal_acquisition_rejected(
    *,
    config: Any,
    scope: CompleteMetadataScope,
    raw_root: Path,
    acquisition_result: object,
) -> None:
    result = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition_result,  # type: ignore[arg-type]
    )

    assert result.gate_status == "FAIL"
    assert result.qa["gate"]["checks"]["acquisition_complete_and_consistent"] is False
    assert "ACQUISITION_INCOMPLETE" in result.qa["gate"]["reason_codes"]


def test_generic_month_qa_accepts_only_the_internally_sealed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
    )
    manual = MonthAcquisitionResult(
        **{
            item.name: getattr(acquisition, item.name)
            for item in fields(MonthAcquisitionResult)
            if item.init
        }
    )
    forged = (
        acquisition.public_dict(),
        manual,
        replace(acquisition),
        copy.copy(acquisition),
        copy.deepcopy(acquisition),
        pickle.loads(pickle.dumps(acquisition)),
    )

    genuine = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
    )
    assert genuine.gate_status == "PASS"
    for candidate in forged:
        _assert_seasonal_acquisition_rejected(
            config=config,
            scope=scope,
            raw_root=raw_root,
            acquisition_result=candidate,
        )


def test_generic_month_qa_rejects_result_bound_to_another_verified_scope_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
    )
    other_scope = load_verified_complete_metadata(tmp_path / "metadata", config)
    assert other_scope.is_verified_for(config)
    assert other_scope is not scope

    _assert_seasonal_acquisition_rejected(
        config=config,
        scope=other_scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
    )


def test_generic_month_qa_rejects_result_after_valid_raw_inventory_is_rewritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
    )
    data_path = min((raw_root / "timeseries").glob("*.jsonl.gz"))
    with gzip.open(data_path, "ab"):
        pass
    manifest_path = (
        raw_root
        / "manifests"
        / "timeseries"
        / data_path.name.replace(".jsonl.gz", ".manifest.json")
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = hashlib.sha256(data_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
    )

    assert result.qa["gate"]["checks"]["raw_snapshot_valid"] is True
    assert result.qa["gate"]["checks"]["acquisition_complete_and_consistent"] is False
    assert result.gate_status == "FAIL"


def test_sealed_result_rejects_cross_month_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
    )
    inventory = full_qa_module.canonical_seasonal_inventory(raw_root)

    assert seasonal_acquisition_module.verify_month_acquisition_result(
        acquisition,
        config=config,
        scope=scope,
        inventory=inventory,
    )
    assert not seasonal_acquisition_module.verify_month_acquisition_result(
        acquisition,
        config=jpl_month_config("2019-08"),
        scope=scope,
        inventory=inventory,
    )


def test_seasonal_qa_rejects_replace_plus_instance_method_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
    )
    copied = replace(acquisition)
    with pytest.raises(AttributeError):
        object.__setattr__(copied, "is_verified_for", lambda **_kwargs: True)
    with pytest.raises(AttributeError):
        object.__setattr__(
            copied,
            "public_dict",
            lambda: MonthAcquisitionResult.public_dict(acquisition),
        )

    _assert_seasonal_acquisition_rejected(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=copied,
    )


def test_month_result_slots_reject_method_and_public_dict_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _config, _scope, _raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
    )

    with pytest.raises(AttributeError):
        object.__setattr__(acquisition, "is_verified_for", lambda **_kwargs: True)
    with pytest.raises(AttributeError):
        object.__setattr__(acquisition, "public_dict", dict)
    with pytest.raises(AttributeError):
        object.__setattr__(acquisition, "unexpected_attribute", True)


def test_seasonal_qa_rejects_genuine_result_field_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
    )
    object.__setattr__(acquisition, "valid_daily_chunks", 0)

    _assert_seasonal_acquisition_rejected(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
    )


@pytest.mark.parametrize("target", ["records", "source_evidence"])
def test_seasonal_qa_rejects_scope_mutation_even_with_instance_verifier_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
    )
    if target == "records":
        object.__setattr__(scope, "local_month_records", ())
    else:
        assert scope.source_evidence is not None
        object.__setattr__(scope.source_evidence, "source_inventory_sha256", "0" * 64)
    object.__setattr__(scope, "is_verified_for", lambda _config: True)

    result = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
    )

    assert result.gate_status == "FAIL"


def test_month_result_registry_discards_gc_entries_and_rejects_stale_id_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, scope, raw_root, acquisition = _generic_scope_and_acquisition(
        tmp_path,
        monkeypatch,
        month="2019-02",
        carry_count=0,
    )
    inventory = full_qa_module.canonical_seasonal_inventory(raw_root)
    result_id = id(acquisition)
    reference = weakref.ref(acquisition)
    stale_entry = seasonal_acquisition_module._VERIFIED_MONTH_RESULTS[result_id]
    init_values = {
        item.name: getattr(acquisition, item.name)
        for item in fields(MonthAcquisitionResult)
        if item.init
    }

    del acquisition
    gc.collect()
    assert reference() is None
    assert result_id not in seasonal_acquisition_module._VERIFIED_MONTH_RESULTS

    unsealed = MonthAcquisitionResult(**init_values)
    seasonal_acquisition_module._VERIFIED_MONTH_RESULTS[id(unsealed)] = stale_entry
    try:
        assert not seasonal_acquisition_module.verify_month_acquisition_result(
            unsealed,
            config=config,
            scope=scope,
            inventory=inventory,
        )
    finally:
        seasonal_acquisition_module._VERIFIED_MONTH_RESULTS.pop(id(unsealed), None)
