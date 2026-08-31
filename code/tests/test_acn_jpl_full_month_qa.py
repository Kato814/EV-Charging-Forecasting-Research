from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from evcf.data import acn_jpl_full_month_qa as full_qa_module
from evcf.data import acn_jpl_full_month_ts as full_ts_module
from evcf.data.acn_api import ACNQuery
from evcf.data.acn_jpl_full_month_qa import (
    PUBLIC_ARTIFACT_NAMES,
    _safe_rate,
    audit_quality_records,
    generate_full_month_timeseries_qa,
    verify_public_artifact_hashes,
)
from evcf.data.acn_jpl_full_month_ts import run_full_month_timeseries
from evcf.data.acn_jpl_gate0 import chunk_paths, jpl_analysis_windows

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
