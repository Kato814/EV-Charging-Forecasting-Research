"""Privacy-safe Phase 1 metadata QA for the frozen JPL May 2019 gate."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .acn_api import ACNQuery
from .acn_audit import parse_acn_datetime
from .acn_jpl_gate0 import (
    JPL_ACQUISITION_START,
    JPL_ANALYSIS_END,
    JPL_ANALYSIS_START,
    JPL_TIMEZONE,
    chunk_paths,
    jpl_acquisition_windows,
)

EXPECTED_ANALYSIS_UNIQUE_SESSIONS = 1645
_SOURCE = "ACN-Data official REST API"
_OUTPUT_FILENAMES = (
    "qa_metadata_jpl_2019-05.json",
    "qa_timeseries_jpl_2019-05.json",
    "acquisition_summary_jpl_2019-05.json",
    "acquisition_summary_jpl_2019-05.md",
    "failed_or_incomplete_chunks.csv",
)


@dataclass(frozen=True)
class Phase1MetadataQAResult:
    """In-memory result plus the six deterministic delivery paths."""

    gate_status: Literal["PASS", "FAIL"]
    qa_metadata: dict[str, Any]
    qa_timeseries: dict[str, Any]
    output_paths: tuple[Path, ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _private_key(value: object) -> str:
    """Create an in-memory comparison key that is never included in a report."""

    return f"{type(value).__name__}:{json.dumps(value, sort_keys=True, default=str)}"


def _identifier_counts(values: list[object]) -> dict[str, int]:
    present = [value for value in values if value not in (None, "")]
    counts = Counter(_private_key(value) for value in present)
    return {
        "unique": len(counts),
        "missing": len(values) - len(present),
        "duplicate_records": sum(count - 1 for count in counts.values() if count > 1),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _has_user_input_field(record: Mapping[str, Any], field_name: str) -> bool:
    inputs = record.get("userInputs")
    if not isinstance(inputs, list):
        return False
    return any(
        isinstance(entry, Mapping) and entry.get(field_name) not in (None, "")
        for entry in inputs
    )


def _summarize_records(
    records: list[Mapping[str, Any]],
    daily_record_counts: Mapping[str, int],
) -> dict[str, Any]:
    object_ids = _identifier_counts([record.get("_id") for record in records])
    session_ids = _identifier_counts([record.get("sessionID") for record in records])
    with_inputs = sum(
        isinstance(record.get("userInputs"), list) and bool(record.get("userInputs"))
        for record in records
    )
    with_departure = sum(
        _has_user_input_field(record, "requestedDeparture") for record in records
    )
    with_requested_energy = sum(
        _has_user_input_field(record, "kWhRequested") for record in records
    )
    denominator = len(records)
    return {
        "record_count": denominator,
        "unique_object_ids": object_ids["unique"],
        "missing_object_ids": object_ids["missing"],
        "duplicate_object_id_records": object_ids["duplicate_records"],
        "unique_session_ids": session_ids["unique"],
        "missing_session_ids": session_ids["missing"],
        "duplicate_session_id_records": session_ids["duplicate_records"],
        "daily_record_counts": dict(sorted(daily_record_counts.items())),
        "user_input_coverage": {
            "denominator_sessions": denominator,
            "sessions_with_user_inputs": with_inputs,
            "sessions_with_requested_departure": with_departure,
            "sessions_with_kwh_requested": with_requested_energy,
            "user_inputs_rate": _rate(with_inputs, denominator),
            "requested_departure_rate": _rate(with_departure, denominator),
            "kwh_requested_rate": _rate(with_requested_energy, denominator),
        },
    }


def _manifest_contract_matches(manifest: Mapping[str, Any], window: Any) -> bool:
    expected_query = ACNQuery(
        site="jpl",
        start=window.local_start,
        end=window.local_end,
        timeseries=False,
    )
    return (
        manifest.get("schema_version") == "acn-jpl-daily-chunk/v1"
        and manifest.get("source") == _SOURCE
        and manifest.get("endpoint") == expected_query.endpoint
        and manifest.get("query_condition") == expected_query.condition
        and manifest.get("site") == "jpl"
        and manifest.get("timezone") == JPL_TIMEZONE
        and manifest.get("token_stored") is False
    )


def _manifest_bounds_match(manifest: Mapping[str, Any], window: Any) -> bool:
    return (
        manifest.get("local_start_inclusive") == window.local_start.isoformat()
        and manifest.get("local_end_exclusive") == window.local_end.isoformat()
        and manifest.get("utc_start_inclusive") == window.utc_start.isoformat()
        and manifest.get("utc_end_exclusive") == window.utc_end.isoformat()
    )


def _safe_datetime(value: object) -> datetime | None:
    try:
        return parse_acn_datetime(value)
    except (TypeError, ValueError):
        return None


def _datetime_range(values: list[datetime]) -> dict[str, str | None]:
    if not values:
        return {"minimum": None, "maximum": None}
    return {
        "minimum": min(values).astimezone(timezone.utc).isoformat(),
        "maximum": max(values).astimezone(timezone.utc).isoformat(),
    }


def _privacy_declaration() -> dict[str, str | bool]:
    return {
        "status": "PASS",
        "identifiers_emitted": False,
        "raw_response_emitted": False,
        "token_emitted": False,
    }


def _read_retry_observation(raw_root: Path) -> dict[str, Any]:
    """Read observable chunk-level retries without claiming hidden HTTP retries."""

    retry_count: int | None = None
    progress_path = raw_root / "state" / "progress.json"
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict):
        endpoint_state: object = None
        endpoints = payload.get("endpoints")
        if isinstance(endpoints, dict):
            endpoint_state = endpoints.get("metadata")
        elif payload.get("endpoint") == "metadata":
            endpoint_state = payload
        if isinstance(endpoint_state, dict):
            candidate = endpoint_state.get("retry_count")
            if (
                isinstance(candidate, int)
                and not isinstance(candidate, bool)
                and candidate >= 0
            ):
                retry_count = candidate
    return {
        "chunk_failure_retry_count": retry_count,
        "chunk_failure_retry_count_status": (
            "OBSERVED_FROM_PROGRESS" if retry_count is not None else "NOT_AVAILABLE"
        ),
        "http_internal_retry_count": None,
        "http_internal_retry_count_status": "NOT_OBSERVABLE",
        "note": (
            "progress.json exposes failed chunk attempts only; retries internal to the HTTP "
            "adapter are not observable from saved acquisition state."
        ),
    }


def _empty_boundary_histogram() -> dict[str, int]:
    return {
        "within_half_open_window": 0,
        "at_exclusive_end": 0,
        "deviation_0_to_60_seconds": 0,
        "deviation_60_to_3600_seconds": 0,
        "deviation_over_3600_seconds": 0,
        "invalid_or_missing": 0,
    }


def _record_boundary_deviation(
    histogram: dict[str, int],
    connection: datetime | None,
    window: Any,
) -> None:
    if connection is None:
        histogram["invalid_or_missing"] += 1
        return
    if window.utc_start <= connection < window.utc_end:
        histogram["within_half_open_window"] += 1
        return
    if connection == window.utc_end:
        histogram["at_exclusive_end"] += 1
        return
    if connection < window.utc_start:
        deviation = (window.utc_start - connection).total_seconds()
    else:
        deviation = (connection - window.utc_end).total_seconds()
    if deviation <= 60:
        histogram["deviation_0_to_60_seconds"] += 1
    elif deviation <= 3600:
        histogram["deviation_60_to_3600_seconds"] += 1
    else:
        histogram["deviation_over_3600_seconds"] += 1


def evaluate_jpl_metadata(raw_root: str | Path) -> dict[str, Any]:
    """Aggregate 38 raw daily chunks while emitting counts, never identifier values."""

    root = Path(raw_root)
    windows = list(jpl_acquisition_windows())
    acquisition_daily = {window.day_key: 0 for window in windows}
    analysis_daily = {
        window.day_key: 0
        for window in windows
        if JPL_ANALYSIS_START.date() <= window.local_start.date() < JPL_ANALYSIS_END.date()
    }
    acquisition_records: list[Mapping[str, Any]] = []
    parsed_records: list[
        tuple[Mapping[str, Any], datetime | None, datetime | None, datetime | None]
    ] = []
    failures: set[tuple[str, str]] = set()
    chunk_counts: Counter[str] = Counter()
    remote_total_sum = 0
    boundary_histogram = _empty_boundary_histogram()

    for window in windows:
        day = window.day_key
        data_path, manifest_path = chunk_paths(root, "metadata", window)
        codes: set[str] = set()
        manifest: Mapping[str, Any] | None = None
        day_records: list[Mapping[str, Any]] = []

        if data_path.is_file():
            chunk_counts["data_files_found"] += 1
            try:
                with gzip.open(data_path, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        item = json.loads(line)
                        if not isinstance(item, dict):
                            raise TypeError("non-object JSONL record")
                        day_records.append(item)
            except (
                OSError,
                EOFError,
                UnicodeError,
                json.JSONDecodeError,
                TypeError,
            ):
                chunk_counts["json_decode_errors"] += 1
                codes.add("GZIP_JSONL_INVALID")
                day_records = []
            else:
                chunk_counts["jsonl_valid"] += 1
        else:
            codes.add("DATA_FILE_MISSING")

        if manifest_path.is_file():
            chunk_counts["manifest_files_found"] += 1
            try:
                loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                codes.add("MANIFEST_JSON_INVALID")
                chunk_counts["manifest_json_errors"] += 1
            else:
                if isinstance(loaded, dict):
                    manifest = loaded
                    chunk_counts["manifest_valid_json"] += 1
                else:
                    codes.add("MANIFEST_JSON_INVALID")
                    chunk_counts["manifest_json_errors"] += 1
        else:
            codes.add("MANIFEST_FILE_MISSING")

        if manifest is not None:
            if _manifest_contract_matches(manifest, window):
                chunk_counts["manifest_contract_match"] += 1
            else:
                codes.add("MANIFEST_CONTRACT_MISMATCH")

            if _manifest_bounds_match(manifest, window):
                chunk_counts["manifest_boundary_match"] += 1
            else:
                codes.add("MANIFEST_BOUNDARY_MISMATCH")

            if manifest.get("complete_for_query") is True:
                chunk_counts["complete_for_query"] += 1
            else:
                codes.add("MANIFEST_NOT_COMPLETE")

            expected_hash = manifest.get("sha256")
            if (
                data_path.is_file()
                and isinstance(expected_hash, str)
                and expected_hash == _sha256_file(data_path)
            ):
                chunk_counts["hash_match"] += 1
            else:
                codes.add("DATA_HASH_MISMATCH")

            manifest_count = manifest.get("record_count")
            if (
                isinstance(manifest_count, int)
                and not isinstance(manifest_count, bool)
                and manifest_count == len(day_records)
                and "GZIP_JSONL_INVALID" not in codes
            ):
                chunk_counts["record_count_match"] += 1
            else:
                codes.add("RECORD_COUNT_MISMATCH")

            remote_total = manifest.get("remote_total_reported")
            if isinstance(remote_total, int) and not isinstance(remote_total, bool):
                remote_total_sum += remote_total
            if (
                isinstance(remote_total, int)
                and not isinstance(remote_total, bool)
                and remote_total >= 0
                and remote_total == len(day_records)
                and "GZIP_JSONL_INVALID" not in codes
            ):
                chunk_counts["remote_total_match"] += 1
            else:
                codes.add("REMOTE_TOTAL_MISMATCH")

            if "DATA_HASH_MISMATCH" in codes:
                chunk_counts["sha256_mismatch"] += 1
            manifest_failure_codes = {
                "DATA_FILE_MISSING",
                "GZIP_JSONL_INVALID",
                "MANIFEST_JSON_INVALID",
                "MANIFEST_CONTRACT_MISMATCH",
                "MANIFEST_BOUNDARY_MISMATCH",
                "MANIFEST_NOT_COMPLETE",
                "DATA_HASH_MISMATCH",
                "RECORD_COUNT_MISMATCH",
                "REMOTE_TOTAL_MISMATCH",
            }
            if not codes.intersection(manifest_failure_codes):
                chunk_counts["valid_manifests"] += 1

        day_time_errors = 0
        for record in day_records:
            connection = _safe_datetime(record.get("connectionTime"))
            disconnect = _safe_datetime(record.get("disconnectTime"))
            done = _safe_datetime(record.get("doneChargingTime"))
            _record_boundary_deviation(boundary_histogram, connection, window)
            if connection is None:
                day_time_errors += 1
                codes.add("CONNECTION_TIME_INVALID")
            elif not (window.utc_start <= connection < window.utc_end):
                day_time_errors += 1
                codes.add("RECORD_OUTSIDE_CHUNK_BOUNDARY")
            parsed_records.append((record, connection, disconnect, done))
        chunk_counts["time_boundary_errors"] += day_time_errors
        acquisition_records.extend(day_records)
        acquisition_daily[day] = len(day_records)

        if not codes:
            chunk_counts["valid"] += 1
        for code in codes:
            failures.add((day, code))

    analysis_start_utc = JPL_ANALYSIS_START.astimezone(timezone.utc)
    analysis_end_utc = JPL_ANALYSIS_END.astimezone(timezone.utc)
    acquisition_start_utc = JPL_ACQUISITION_START.astimezone(timezone.utc)
    analysis_records: list[Mapping[str, Any]] = []
    analysis_connections: list[datetime] = []
    acquisition_connections: list[datetime] = []
    buffer_connection_records: list[Mapping[str, Any]] = []
    carry_in_records: list[Mapping[str, Any]] = []
    connection_after_disconnect = 0
    done_before_connection = 0
    done_after_disconnect = 0
    for record, connection, disconnect, done in parsed_records:
        if connection is not None:
            acquisition_connections.append(connection)
        if connection is not None and analysis_start_utc <= connection < analysis_end_utc:
            analysis_records.append(record)
            analysis_connections.append(connection)
            day_key = connection.astimezone(JPL_ANALYSIS_START.tzinfo).date().isoformat()
            if day_key in analysis_daily:
                analysis_daily[day_key] += 1
        if (
            connection is not None
            and acquisition_start_utc <= connection < analysis_start_utc
        ):
            buffer_connection_records.append(record)
        if (
            connection is not None
            and acquisition_start_utc <= connection < analysis_start_utc
            and disconnect is not None
            and disconnect > analysis_start_utc
        ):
            carry_in_records.append(record)
        if connection is not None and disconnect is not None and connection > disconnect:
            connection_after_disconnect += 1
        if connection is not None and done is not None and done < connection:
            done_before_connection += 1
        if disconnect is not None and done is not None and done > disconnect:
            done_after_disconnect += 1

    acquisition = _summarize_records(acquisition_records, acquisition_daily)
    analysis = _summarize_records(analysis_records, analysis_daily)
    carry_in_ids = _identifier_counts(
        [record.get("sessionID") for record in carry_in_records]
    )
    carry_in = {
        "record_count": len(carry_in_records),
        "unique_session_ids": carry_in_ids["unique"],
    }
    buffer = {
        "connection_session_count": len(buffer_connection_records),
        "carry_in_session_count": len(carry_in_records),
        "observed_start_inclusive": JPL_ACQUISITION_START.isoformat(),
        "observed_end_exclusive": JPL_ANALYSIS_START.isoformat(),
        "sufficiency": {
            "status": "OBSERVED_SCOPE_ONLY",
            "assessment_zh": (
                "该统计只说明已观测的七日缓冲范围；它不能证明更早连接且仍活跃的会话不存在。"
            ),
        },
    }
    actual_scope = {
        "metadata_record_count": len(acquisition_records),
        "connection_range_utc": _datetime_range(acquisition_connections),
        "analysis_connection_range_utc": _datetime_range(analysis_connections),
        "metadata_days_with_records": sum(value > 0 for value in acquisition_daily.values()),
        "timeseries_status": "NOT_RUN",
    }
    metadata_temporal_quality = {
        "connection_after_disconnect": connection_after_disconnect,
        "done_before_connection": done_before_connection,
        "done_after_disconnect": done_after_disconnect,
        "actual_connection_range_utc": _datetime_range(acquisition_connections),
        "boundary_deviation_histogram": boundary_histogram,
        "boundary_deviation_definition": (
            "Connection timestamps are compared with each owning local-day half-open query window."
        ),
        "timeseries_boundary_metrics": {
            "status": "NOT_RUN",
            "boundary_positive_points": None,
            "boundary_positive_sessions": None,
        },
    }

    identifier_integrity = all(
        section[field] == 0
        for section in (acquisition, analysis)
        for field in (
            "missing_object_ids",
            "duplicate_object_id_records",
            "missing_session_ids",
            "duplicate_session_id_records",
        )
    )
    if acquisition["missing_object_ids"]:
        failures.add(("acquisition_window", "MISSING_OBJECT_ID"))
    if acquisition["duplicate_object_id_records"]:
        failures.add(("acquisition_window", "DUPLICATE_OBJECT_ID"))
    if acquisition["missing_session_ids"]:
        failures.add(("acquisition_window", "MISSING_SESSION_ID"))
    if acquisition["duplicate_session_id_records"]:
        failures.add(("acquisition_window", "DUPLICATE_SESSION_ID"))

    exact_count = analysis["unique_session_ids"] == EXPECTED_ANALYSIS_UNIQUE_SESSIONS
    if not exact_count:
        failures.add(("analysis_window", "ANALYSIS_UNIQUE_SESSION_COUNT_MISMATCH"))
    all_chunks_valid = chunk_counts["valid"] == len(windows)
    integrity_passed = all_chunks_valid and identifier_integrity
    gate_passed = integrity_passed and exact_count
    ordered_failures = [
        {"scope": scope, "reason_code": reason_code}
        for scope, reason_code in sorted(failures)
    ]
    failure_dates = sorted(
        {
            item["scope"]
            for item in ordered_failures
            if len(item["scope"]) == 10 and item["scope"][4] == "-"
        }
    )
    timeseries_daily = {day: None for day in acquisition_daily}
    timeseries_linkage = {
        "status": "NOT_RUN",
        "missing_timeseries_sessions": None,
        "orphan_timeseries_sessions": None,
    }

    return {
        "schema_version": "acn-jpl-metadata-qa/v1",
        "dataset_id": "D0001",
        "site": "jpl",
        "source": _SOURCE,
        "timezone": JPL_TIMEZONE,
        "acquisition_window": {
            "start_inclusive": JPL_ACQUISITION_START.isoformat(),
            "end_exclusive": JPL_ANALYSIS_END.isoformat(),
        },
        "analysis_window": {
            "start_inclusive": JPL_ANALYSIS_START.isoformat(),
            "end_exclusive": JPL_ANALYSIS_END.isoformat(),
        },
        "expected_analysis_unique_session_ids": EXPECTED_ANALYSIS_UNIQUE_SESSIONS,
        "observed_analysis_unique_session_ids": analysis["unique_session_ids"],
        "actual_scope": actual_scope,
        "daily": {
            "metadata_record_counts": dict(sorted(acquisition_daily.items())),
            "timeseries_record_counts": dict(sorted(timeseries_daily.items())),
            "timeseries_status": "NOT_RUN",
        },
        "buffer": buffer,
        "metadata_temporal_quality": metadata_temporal_quality,
        "timeseries_linkage": timeseries_linkage,
        "api_retry_observation": _read_retry_observation(root),
        "chunks": {
            "expected": len(windows),
            "data_files_found": chunk_counts["data_files_found"],
            "manifest_files_found": chunk_counts["manifest_files_found"],
            "manifest_valid_json": chunk_counts["manifest_valid_json"],
            "manifest_contract_match": chunk_counts["manifest_contract_match"],
            "manifest_boundary_match": chunk_counts["manifest_boundary_match"],
            "complete_for_query": chunk_counts["complete_for_query"],
            "hash_match": chunk_counts["hash_match"],
            "sha256_mismatch": chunk_counts["sha256_mismatch"],
            "jsonl_valid": chunk_counts["jsonl_valid"],
            "record_count_match": chunk_counts["record_count_match"],
            "remote_total_match": chunk_counts["remote_total_match"],
            "remote_total_reported_sum": remote_total_sum,
            "json_decode_errors": chunk_counts["json_decode_errors"],
            "manifest_json_errors": chunk_counts["manifest_json_errors"],
            "json_errors_total": (
                chunk_counts["json_decode_errors"]
                + chunk_counts["manifest_json_errors"]
            ),
            "time_boundary_errors": chunk_counts["time_boundary_errors"],
            "valid_manifests": chunk_counts["valid_manifests"],
            "invalid_manifests": len(windows) - chunk_counts["valid_manifests"],
            "valid": chunk_counts["valid"],
            "failed_or_incomplete": len(windows) - chunk_counts["valid"],
            "failure_dates": failure_dates,
        },
        "acquisition": acquisition,
        "analysis": analysis,
        "carry_in": carry_in,
        "failures": ordered_failures,
        "privacy": _privacy_declaration(),
        "gate": {
            "status": "PASS" if gate_passed else "FAIL",
            "integrity_conditions_passed": integrity_passed,
            "exact_analysis_count_passed": exact_count,
            "conditions": {
                "all_38_chunks_valid": all_chunks_valid,
                "identifier_integrity": identifier_integrity,
                "analysis_unique_session_ids_equal_expected": exact_count,
            },
            "reason_codes": sorted({item["reason_code"] for item in ordered_failures}),
        },
    }


def _build_timeseries_not_run(metadata: Mapping[str, Any]) -> dict[str, Any]:
    gate_status = metadata["gate"]["status"]
    reason = (
        "METADATA_GATE_FAILED"
        if gate_status == "FAIL"
        else "PHASE1_ONLY_PREFLIGHT_NOT_STARTED"
    )
    return {
        "schema_version": "acn-jpl-timeseries-qa/v1",
        "dataset_id": "D0001",
        "site": "jpl",
        "status": "NOT_RUN",
        "download_attempted": False,
        "reason_code": reason,
        "actual_scope": metadata["actual_scope"],
        "buffer": metadata["buffer"],
        "daily": metadata["daily"],
        "metadata_manifest_quality": {
            "valid_manifests": metadata["chunks"]["valid_manifests"],
            "invalid_manifests": metadata["chunks"]["invalid_manifests"],
            "sha256_mismatch": metadata["chunks"]["sha256_mismatch"],
            "json_errors_total": metadata["chunks"]["json_errors_total"],
            "failure_dates": metadata["chunks"]["failure_dates"],
        },
        "api_retry_observation": metadata["api_retry_observation"],
        "field_coverage": {
            "chargingCurrent": None,
            "pilotSignal": None,
            "userInputs": None,
            "requestedDeparture": None,
            "kWhRequested": None,
        },
        "quality": {
            "length_mismatch": None,
            "invalid_containers": None,
            "duplicate_timestamps": None,
            "nonmonotonic_timestamps": None,
            "invalid_values": None,
            "negative_current": None,
            "non_utc_timestamps": None,
            "sparse_rate": None,
            "raw_samples": None,
            "usable_samples": None,
            "retained_rate": None,
            "boundary_positive_points": None,
            "boundary_positive_sessions": None,
            "boundary_positive_session_rate": None,
            "severe_anomalies": None,
        },
        "session_linkage": {
            "missing_timeseries_sessions": None,
            "orphan_timeseries_sessions": None,
        },
        "daily_timeseries_record_counts": dict(
            sorted(metadata["daily"]["timeseries_record_counts"].items())
        ),
        "preflight": {
            "status": "NOT_RUN",
            "preflight_sample_size": None,
            "downloaded_sessions": None,
            "overlapping_session_count": None,
            "station_aggregation_feasible": None,
        },
        "privacy": _privacy_declaration(),
    }


def _summary_json(metadata: Mapping[str, Any], timeseries: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "acn-jpl-acquisition-summary/v1",
        "dataset_id": "D0001",
        "site": "jpl",
        "source": _SOURCE,
        "gate_status": metadata["gate"]["status"],
        "expected_analysis_unique_session_ids": metadata[
            "expected_analysis_unique_session_ids"
        ],
        "observed_analysis_unique_session_ids": metadata[
            "observed_analysis_unique_session_ids"
        ],
        "acquisition_record_count": metadata["acquisition"]["record_count"],
        "analysis_record_count": metadata["analysis"]["record_count"],
        "carry_in_record_count": metadata["carry_in"]["record_count"],
        "actual_scope": metadata["actual_scope"],
        "daily": metadata["daily"],
        "buffer": metadata["buffer"],
        "metadata_temporal_quality": metadata["metadata_temporal_quality"],
        "manifest_quality": {
            "valid_manifests": metadata["chunks"]["valid_manifests"],
            "invalid_manifests": metadata["chunks"]["invalid_manifests"],
            "sha256_mismatch": metadata["chunks"]["sha256_mismatch"],
            "json_errors_total": metadata["chunks"]["json_errors_total"],
            "failure_dates": metadata["chunks"]["failure_dates"],
        },
        "api_retry_observation": metadata["api_retry_observation"],
        "valid_daily_chunks": metadata["chunks"]["valid"],
        "expected_daily_chunks": metadata["chunks"]["expected"],
        "timeseries_status": timeseries["status"],
        "timeseries_download_attempted": timeseries["download_attempted"],
        "timeseries": {
            "status": timeseries["status"],
            "download_attempted": timeseries["download_attempted"],
            "field_coverage": timeseries["field_coverage"],
            "quality": timeseries["quality"],
            "session_linkage": timeseries["session_linkage"],
            "daily_timeseries_record_counts": timeseries[
                "daily_timeseries_record_counts"
            ],
        },
        "privacy": _privacy_declaration(),
        "limitations": [
            "A count mismatch alone cannot identify a particular missing session.",
            "Charging current is not direct active power without voltage and phase metadata.",
        ],
    }


def _summary_markdown(metadata: Mapping[str, Any], timeseries: Mapping[str, Any]) -> str:
    observed = metadata["observed_analysis_unique_session_ids"]
    expected = metadata["expected_analysis_unique_session_ids"]
    status = metadata["gate"]["status"]
    mismatch_note = (
        f"仅凭 {observed} 与 {expected} 的计数差异不能定位具体缺失会话。"
        if observed != expected
        else "本次计数与冻结期望一致；会话身份值仍不会写入 QA 输出。"
    )
    return "\n".join(
        [
            "# JPL 2019-05 ACN-Data Phase 1 元数据门控",
            "",
            f"- 数据源：{_SOURCE}",
            f"- 门控状态：{status}",
            f"- 分析窗唯一 sessionID：观测 {observed}，期望 {expected}",
            f"- 每日完整块：{metadata['chunks']['valid']}/{metadata['chunks']['expected']}",
            f"- `/ts` 状态：{timeseries['status']}，未启动；download_attempted=false",
            "",
            mismatch_note,
            "",
            "## 功率与在线特征语义",
            "",
            "- 语义1：chargingCurrent 是实测电流，不是直接 kW。",
            "- 语义2：pilotSignal 是导引或控制信号，不是实测有功功率。",
            "- 语义3：不得简单求和并称为站级有功功率。",
            "- 语义4：由电流转换为功率需要电压、相别、功率因数和网络配置。",
            "",
            "disconnectTime、doneChargingTime 与最终 kWhDelivered 是回溯标签；userInputs 也必须按 issue time 截断。",
            "",
        ]
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def run_phase1_metadata_qa(
    raw_root: str | Path,
    output_dir: str | Path,
) -> Phase1MetadataQAResult:
    """Evaluate Phase 1 and atomically write a deterministic, deidentified delivery."""

    metadata = evaluate_jpl_metadata(raw_root)
    timeseries = _build_timeseries_not_run(metadata)
    summary = _summary_json(metadata, timeseries)
    output = Path(output_dir)

    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        csv_buffer,
        fieldnames=("scope", "reason_code", "expected_count", "observed_count"),
        lineterminator="\n",
    )
    writer.writeheader()
    csv_rows = []
    for failure in metadata["failures"]:
        row = dict(failure)
        if failure["reason_code"] == "ANALYSIS_UNIQUE_SESSION_COUNT_MISMATCH":
            row["expected_count"] = metadata["expected_analysis_unique_session_ids"]
            row["observed_count"] = metadata["observed_analysis_unique_session_ids"]
        else:
            row["expected_count"] = None
            row["observed_count"] = None
        csv_rows.append(row)
    csv_rows.append(
        {
            "scope": "analysis_window",
            "reason_code": "ANALYSIS_UNIQUE_SESSION_COUNT_GATE",
            "expected_count": metadata["expected_analysis_unique_session_ids"],
            "observed_count": metadata["observed_analysis_unique_session_ids"],
        }
    )
    writer.writerows(csv_rows)

    payloads = {
        "qa_metadata_jpl_2019-05.json": _json_bytes(metadata),
        "qa_timeseries_jpl_2019-05.json": _json_bytes(timeseries),
        "acquisition_summary_jpl_2019-05.json": _json_bytes(summary),
        "acquisition_summary_jpl_2019-05.md": _summary_markdown(
            metadata, timeseries
        ).encode("utf-8"),
        "failed_or_incomplete_chunks.csv": csv_buffer.getvalue().encode("utf-8"),
    }
    for filename in _OUTPUT_FILENAMES:
        _atomic_write(output / filename, payloads[filename])

    checksum_lines = [
        f"{hashlib.sha256(payloads[filename]).hexdigest()}  {filename}"
        for filename in sorted(_OUTPUT_FILENAMES)
    ]
    _atomic_write(
        output / "SHA256SUMS",
        ("\n".join(checksum_lines) + "\n").encode("utf-8"),
    )
    paths = tuple(output / filename for filename in (*_OUTPUT_FILENAMES, "SHA256SUMS"))
    return Phase1MetadataQAResult(
        gate_status=metadata["gate"]["status"],
        qa_metadata=metadata,
        qa_timeseries=timeseries,
        output_paths=paths,
    )
