from __future__ import annotations

import gzip
import hashlib
import importlib
import inspect
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from evcf.data.acn_api import ACNQuery

ZONE = ZoneInfo("America/Los_Angeles")
ACQUISITION_START = date(2019, 4, 24)
ACQUISITION_END = date(2019, 6, 1)


def _rfc1123(value: datetime) -> str:
    return format_datetime(value.astimezone(timezone.utc), usegmt=True)


def _record(index: int, *, connected: datetime | None = None) -> dict[str, Any]:
    connection = connected or datetime(2019, 5, 1, 8, 0, tzinfo=ZONE)
    return {
        "_id": f"private-object-{index}",
        "sessionID": f"private-session-{index}",
        "userID": f"private-user-{index}",
        "connectionTime": _rfc1123(connection),
        "disconnectTime": _rfc1123(connection + timedelta(hours=1)),
        "userInputs": [],
    }


def _write_raw_dataset(
    root: Path,
    records_by_day: dict[str, list[dict[str, Any]]],
) -> None:
    current = ACQUISITION_START
    while current < ACQUISITION_END:
        day_key = current.isoformat()
        local_start = datetime.combine(current, time.min, ZONE)
        local_end = datetime.combine(current + timedelta(days=1), time.min, ZONE)
        records = records_by_day.get(day_key, [])
        data_path = root / "metadata" / f"{day_key}.jsonl.gz"
        manifest_path = root / "manifests" / "metadata" / f"{day_key}.manifest.json"
        data_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(data_path, "wt", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
        manifest = {
            "schema_version": "acn-jpl-daily-chunk/v1",
            "source": "ACN-Data official REST API",
            "endpoint": "sessions/jpl",
            "site": "jpl",
            "timezone": "America/Los_Angeles",
            "local_start_inclusive": local_start.isoformat(),
            "local_end_exclusive": local_end.isoformat(),
            "utc_start_inclusive": local_start.astimezone(timezone.utc).isoformat(),
            "utc_end_exclusive": local_end.astimezone(timezone.utc).isoformat(),
            "query_condition": ACNQuery(
                site="jpl",
                start=local_start,
                end=local_end,
                timeseries=False,
            ).condition,
            "record_count": len(records),
            "remote_total_reported": len(records),
            "complete_for_query": True,
            "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
            "token_stored": False,
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        current += timedelta(days=1)


@pytest.mark.parametrize(
    ("count", "expected_status"),
    [(1644, "FAIL"), (1645, "PASS"), (1646, "FAIL")],
)
def test_only_exact_expected_analysis_unique_count_passes(
    tmp_path: Path,
    count: int,
    expected_status: str,
) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_metadata_qa")
    raw_root = tmp_path / "raw"
    _write_raw_dataset(raw_root, {"2019-05-01": [_record(i) for i in range(count)]})

    report = module.evaluate_jpl_metadata(raw_root)

    assert report["gate"]["status"] == expected_status
    assert report["analysis"]["record_count"] == count
    assert report["analysis"]["unique_session_ids"] == count
    assert report["chunks"]["valid"] == 38


def test_public_entry_points_freeze_the_1645_gate() -> None:
    module = importlib.import_module("evcf.data.acn_jpl_metadata_qa")

    evaluate_parameters = inspect.signature(module.evaluate_jpl_metadata).parameters
    run_parameters = inspect.signature(module.run_phase1_metadata_qa).parameters

    assert "expected_analysis_unique_sessions" not in evaluate_parameters
    assert "expected_analysis_unique_sessions" not in run_parameters
    assert module.EXPECTED_ANALYSIS_UNIQUE_SESSIONS == 1645


def test_aggregates_identifiers_coverage_carry_in_and_excludes_end_boundary(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_metadata_qa")
    raw_root = tmp_path / "raw"
    carry_in = _record(
        1,
        connected=datetime(2019, 4, 30, 23, 30, tzinfo=ZONE),
    )
    carry_in["disconnectTime"] = _rfc1123(datetime(2019, 5, 1, 0, 30, tzinfo=ZONE))
    first = _record(2)
    first["userInputs"] = [
        {
            "requestedDeparture": "Thu, 02 May 2019 01:00:00 GMT",
            "kWhRequested": 12.0,
        }
    ]
    duplicate_session = _record(3)
    duplicate_session["sessionID"] = first["sessionID"]
    duplicate_session["doneChargingTime"] = _rfc1123(
        datetime(2019, 5, 1, 10, 0, tzinfo=ZONE)
    )
    duplicate_object = _record(4)
    duplicate_object["_id"] = first["_id"]
    duplicate_object["disconnectTime"] = _rfc1123(
        datetime(2019, 5, 1, 7, 0, tzinfo=ZONE)
    )
    missing = _record(5)
    missing["_id"] = None
    missing["sessionID"] = ""
    missing["doneChargingTime"] = _rfc1123(
        datetime(2019, 5, 1, 7, 0, tzinfo=ZONE)
    )
    exact_end = _record(
        6,
        connected=datetime(2019, 6, 1, 0, 0, tzinfo=ZONE),
    )
    _write_raw_dataset(
        raw_root,
        {
            "2019-04-30": [carry_in],
            "2019-05-01": [first, duplicate_session, duplicate_object, missing],
            "2019-05-31": [exact_end],
        },
    )

    report = module.evaluate_jpl_metadata(raw_root)

    assert report["acquisition"]["record_count"] == 6
    assert report["analysis"]["record_count"] == 4
    assert report["carry_in"]["record_count"] == 1
    assert report["analysis"]["unique_session_ids"] == 2
    assert report["analysis"]["missing_session_ids"] == 1
    assert report["analysis"]["duplicate_session_id_records"] == 1
    assert report["analysis"]["unique_object_ids"] == 2
    assert report["analysis"]["missing_object_ids"] == 1
    assert report["analysis"]["duplicate_object_id_records"] == 1
    coverage = report["analysis"]["user_input_coverage"]
    assert coverage["sessions_with_user_inputs"] == 1
    assert coverage["sessions_with_requested_departure"] == 1
    assert coverage["sessions_with_kwh_requested"] == 1
    assert coverage["user_inputs_rate"] == 0.25
    assert report["chunks"]["time_boundary_errors"] == 1
    assert report["analysis"]["daily_record_counts"]["2019-05-01"] == 4
    assert report["buffer"]["connection_session_count"] == 1
    assert report["buffer"]["carry_in_session_count"] == 1
    assert report["buffer"]["sufficiency"]["status"] == "OBSERVED_SCOPE_ONLY"
    assert "不能证明" in report["buffer"]["sufficiency"]["assessment_zh"]
    temporal = report["metadata_temporal_quality"]
    assert temporal["connection_after_disconnect"] == 1
    assert temporal["done_before_connection"] == 1
    assert temporal["done_after_disconnect"] == 1
    assert temporal["actual_connection_range_utc"]["minimum"] == datetime(
        2019, 4, 30, 23, 30, tzinfo=ZONE
    ).astimezone(timezone.utc).isoformat()
    assert temporal["actual_connection_range_utc"]["maximum"] == datetime(
        2019, 6, 1, 0, 0, tzinfo=ZONE
    ).astimezone(timezone.utc).isoformat()
    histogram = temporal["boundary_deviation_histogram"]
    assert histogram["at_exclusive_end"] == 1
    assert histogram["within_half_open_window"] == 5
    assert report["gate"]["status"] == "FAIL"


def test_manifest_remote_total_failure_invalidates_gate_with_reason_code(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_metadata_qa")
    raw_root = tmp_path / "raw"
    _write_raw_dataset(raw_root, {"2019-05-01": [_record(i) for i in range(1645)]})
    manifest_path = (
        raw_root / "manifests" / "metadata" / "2019-05-01.manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["remote_total_reported"] = 1644
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = module.evaluate_jpl_metadata(raw_root)

    assert report["gate"]["status"] == "FAIL"
    assert report["chunks"]["valid"] == 37
    assert report["chunks"]["remote_total_match"] == 37
    assert {
        "scope": "2019-05-01",
        "reason_code": "REMOTE_TOTAL_MISMATCH",
    } in report["failures"]


@pytest.mark.parametrize(
    ("field_name", "tampered_value"),
    [
        ("schema_version", "acn-jpl-daily-chunk/v0"),
        ("query_condition", "connectionTime >= tampered"),
    ],
)
def test_manifest_schema_or_query_tampering_invalidates_contract_and_gate(
    tmp_path: Path,
    field_name: str,
    tampered_value: str,
) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_metadata_qa")
    raw_root = tmp_path / "raw"
    _write_raw_dataset(raw_root, {"2019-05-01": [_record(i) for i in range(1645)]})
    manifest_path = (
        raw_root / "manifests" / "metadata" / "2019-05-01.manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field_name] = tampered_value
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = module.evaluate_jpl_metadata(raw_root)

    assert report["gate"]["status"] == "FAIL"
    assert report["chunks"]["manifest_contract_match"] == 37
    assert report["chunks"]["valid_manifests"] == 37
    assert {
        "scope": "2019-05-01",
        "reason_code": "MANIFEST_CONTRACT_MISMATCH",
    } in report["failures"]


def test_unicode_corrupt_manifest_becomes_fail_report_instead_of_crashing(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_metadata_qa")
    raw_root = tmp_path / "raw"
    _write_raw_dataset(raw_root, {"2019-05-01": [_record(1)]})
    manifest_path = (
        raw_root / "manifests" / "metadata" / "2019-05-01.manifest.json"
    )
    manifest_path.write_bytes(b"\xff\xfe")

    report = module.evaluate_jpl_metadata(raw_root)

    assert report["gate"]["status"] == "FAIL"
    assert report["chunks"]["manifest_json_errors"] == 1
    assert report["chunks"]["invalid_manifests"] == 1
    assert {
        "scope": "2019-05-01",
        "reason_code": "MANIFEST_JSON_INVALID",
    } in report["failures"]


def test_unicode_corrupt_progress_degrades_retry_observation_without_crashing(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_metadata_qa")
    raw_root = tmp_path / "raw"
    _write_raw_dataset(raw_root, {"2019-05-01": [_record(1)]})
    state_dir = raw_root / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "progress.json").write_bytes(b"\xff\xfe")

    report = module.evaluate_jpl_metadata(raw_root)

    retry = report["api_retry_observation"]
    assert retry["chunk_failure_retry_count"] is None
    assert retry["chunk_failure_retry_count_status"] == "NOT_AVAILABLE"
    assert retry["http_internal_retry_count"] is None


def test_zero_denominator_coverage_rates_are_null(tmp_path: Path) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_metadata_qa")
    raw_root = tmp_path / "raw"
    _write_raw_dataset(raw_root, {})

    report = module.evaluate_jpl_metadata(raw_root)

    coverage = report["analysis"]["user_input_coverage"]
    assert coverage["user_inputs_rate"] is None
    assert coverage["requested_departure_rate"] is None
    assert coverage["kwh_requested_rate"] is None
    assert report["gate"]["status"] == "FAIL"


def test_explicit_metadata_and_timeseries_skeleton_records_unobserved_items(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_metadata_qa")
    raw_root = tmp_path / "raw"
    output_dir = tmp_path / "outputs"
    _write_raw_dataset(raw_root, {"2019-05-01": [_record(1)]})
    state_dir = raw_root / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "progress.json").write_text(
        json.dumps(
            {
                "schema_version": "acn-jpl-progress/v2",
                "endpoints": {"metadata": {"retry_count": 3}},
            }
        ),
        encoding="utf-8",
    )

    result = module.run_phase1_metadata_qa(raw_root, output_dir)
    metadata = result.qa_metadata
    timeseries = result.qa_timeseries

    assert metadata["actual_scope"]["connection_range_utc"]["minimum"] is not None
    assert len(metadata["daily"]["metadata_record_counts"]) == 38
    assert len(metadata["daily"]["timeseries_record_counts"]) == 38
    assert set(metadata["daily"]["timeseries_record_counts"].values()) == {None}
    assert metadata["timeseries_linkage"]["status"] == "NOT_RUN"
    assert metadata["timeseries_linkage"]["missing_timeseries_sessions"] is None
    assert metadata["timeseries_linkage"]["orphan_timeseries_sessions"] is None
    assert metadata["chunks"]["valid_manifests"] == 38
    assert metadata["chunks"]["invalid_manifests"] == 0
    assert metadata["chunks"]["sha256_mismatch"] == 0
    assert metadata["chunks"]["json_decode_errors"] == 0
    assert metadata["chunks"]["failure_dates"] == []
    retry = metadata["api_retry_observation"]
    assert retry["chunk_failure_retry_count"] == 3
    assert retry["http_internal_retry_count"] is None
    assert retry["http_internal_retry_count_status"] == "NOT_OBSERVABLE"
    assert retry["note"]

    assert timeseries["status"] == "NOT_RUN"
    assert timeseries["actual_scope"] == metadata["actual_scope"]
    assert timeseries["buffer"] == metadata["buffer"]
    assert timeseries["daily"]["metadata_record_counts"] == metadata["daily"][
        "metadata_record_counts"
    ]
    assert timeseries["daily"]["timeseries_record_counts"] == metadata["daily"][
        "timeseries_record_counts"
    ]
    assert timeseries["metadata_manifest_quality"] == {
        "valid_manifests": 38,
        "invalid_manifests": 0,
        "sha256_mismatch": 0,
        "json_errors_total": 0,
        "failure_dates": [],
    }
    assert timeseries["api_retry_observation"] == retry
    assert set(timeseries["field_coverage"]) == {
        "chargingCurrent",
        "pilotSignal",
        "userInputs",
        "requestedDeparture",
        "kWhRequested",
    }
    assert set(timeseries["field_coverage"].values()) == {None}
    assert set(timeseries["quality"]) == {
        "length_mismatch",
        "invalid_containers",
        "duplicate_timestamps",
        "nonmonotonic_timestamps",
        "invalid_values",
        "negative_current",
        "non_utc_timestamps",
        "sparse_rate",
        "raw_samples",
        "usable_samples",
        "retained_rate",
        "boundary_positive_points",
        "boundary_positive_sessions",
        "boundary_positive_session_rate",
        "severe_anomalies",
    }
    assert set(timeseries["quality"].values()) == {None}
    assert len(timeseries["daily_timeseries_record_counts"]) == 38
    assert set(timeseries["daily_timeseries_record_counts"].values()) == {None}
    assert timeseries["privacy"]["identifiers_emitted"] is False
    assert timeseries["privacy"]["token_emitted"] is False

    summary = json.loads(
        (output_dir / "acquisition_summary_jpl_2019-05.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["actual_scope"] == metadata["actual_scope"]
    assert summary["daily"] == metadata["daily"]
    assert summary["buffer"] == metadata["buffer"]
    assert summary["timeseries"]["quality"] == timeseries["quality"]
    assert summary["privacy"]["identifiers_emitted"] is False


def test_fail_delivery_is_deterministic_atomic_hashed_and_private(tmp_path: Path) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_metadata_qa")
    raw_root = tmp_path / "raw"
    output_dir = tmp_path / "outputs"
    records = [_record(i) for i in range(1644)]
    records[0]["_id"] = "fixture-private-object"
    records[0]["sessionID"] = "fixture-private-session"
    records[0]["userID"] = "fixture-private-user"
    records[0]["userInputs"] = [{"fixtureToken": "fixture-secret-token"}]
    _write_raw_dataset(raw_root, {"2019-05-01": records})

    result = module.run_phase1_metadata_qa(raw_root, output_dir)

    assert result.gate_status == "FAIL"
    expected_names = {
        "qa_metadata_jpl_2019-05.json",
        "qa_timeseries_jpl_2019-05.json",
        "acquisition_summary_jpl_2019-05.json",
        "acquisition_summary_jpl_2019-05.md",
        "failed_or_incomplete_chunks.csv",
        "SHA256SUMS",
    }
    assert {path.name for path in result.output_paths} == expected_names
    first_bytes = {path.name: path.read_bytes() for path in result.output_paths}
    assert not list(output_dir.glob("*.partial"))

    timeseries = json.loads(
        (output_dir / "qa_timeseries_jpl_2019-05.json").read_text(encoding="utf-8")
    )
    assert timeseries["status"] == "NOT_RUN"
    assert timeseries["download_attempted"] is False
    assert timeseries["reason_code"] == "METADATA_GATE_FAILED"
    assert set(timeseries["field_coverage"].values()) == {None}
    assert set(timeseries["quality"].values()) == {None}

    markdown = (output_dir / "acquisition_summary_jpl_2019-05.md").read_text(
        encoding="utf-8"
    )
    assert "ACN-Data official REST API" in markdown
    assert "1644" in markdown and "1645" in markdown
    assert "/ts" in markdown and "未启动" in markdown
    assert "不能定位具体缺失会话" in markdown
    assert "chargingCurrent 是实测电流，不是直接 kW" in markdown
    assert "pilotSignal 是导引或控制信号" in markdown
    assert "不得简单求和并称为站级有功功率" in markdown
    assert "电压、相别、功率因数和网络配置" in markdown

    csv_text = (output_dir / "failed_or_incomplete_chunks.csv").read_text(
        encoding="utf-8"
    )
    assert "ANALYSIS_UNIQUE_SESSION_COUNT_MISMATCH" in csv_text
    assert "1645,1644" in csv_text
    assert "fixture-private" not in csv_text
    assert "response" not in csv_text.lower()

    checksum_lines = (output_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert len(checksum_lines) == 5
    checksum_names = [line.split("  ", 1)[1] for line in checksum_lines]
    assert checksum_names == sorted(expected_names - {"SHA256SUMS"})
    for line in checksum_lines:
        expected_hash, filename = line.split("  ", 1)
        assert expected_hash == hashlib.sha256((output_dir / filename).read_bytes()).hexdigest()

    combined = b"\n".join(first_bytes.values()).decode("utf-8")
    for private_value in (
        "fixture-private-object",
        "fixture-private-session",
        "fixture-private-user",
        "fixture-secret-token",
    ):
        assert private_value not in combined
    assert result.qa_metadata["privacy"] == {
        "status": "PASS",
        "identifiers_emitted": False,
        "raw_response_emitted": False,
        "token_emitted": False,
    }

    os.utime(output_dir / "qa_metadata_jpl_2019-05.json", None)
    rerun = module.run_phase1_metadata_qa(raw_root, output_dir)
    assert {path.name: path.read_bytes() for path in rerun.output_paths} == first_bytes
