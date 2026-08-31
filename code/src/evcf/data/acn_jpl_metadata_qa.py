"""Privacy-safe Phase 1 metadata QA for the frozen JPL May 2019 gate."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
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
from .acn_jpl_ts_preflight import (
    PREFLIGHT_INVALID_CHARGING_CURRENT_RATE_LIMIT,
    PREFLIGHT_INVALID_PILOT_SIGNAL_RATE_LIMIT,
    PREFLIGHT_RANDOM_SEED,
    PREFLIGHT_SAMPLE_SIZE,
    PREFLIGHT_UNMATCHED_METADATA_RATE_LIMIT,
)

_SOURCE = "ACN-Data official REST API"
_INVENTORY_DIGEST_ALGORITHM = "sha256(sorted filename\\0raw_sha256\\0record_count\\n)"
_UTC_MONTH_START = datetime(2019, 5, 1, tzinfo=timezone.utc)
_UTC_MONTH_END = datetime(2019, 6, 1, tzinfo=timezone.utc)
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


def _official_month_total_contract(payload: Mapping[str, Any]) -> bool:
    query = ACNQuery(
        site="jpl",
        start=JPL_ANALYSIS_START,
        end=JPL_ANALYSIS_END,
        timeseries=False,
    )
    return (
        payload.get("schema_version") == "acn-jpl-official-local-month-total/v1"
        and payload.get("source") == _SOURCE
        and payload.get("endpoint") == query.endpoint
        and payload.get("site") == "jpl"
        and payload.get("timezone") == JPL_TIMEZONE
        and payload.get("interval_semantics") == "[start,end)"
        and payload.get("local_start_inclusive") == JPL_ANALYSIS_START.isoformat()
        and payload.get("local_end_exclusive") == JPL_ANALYSIS_END.isoformat()
        and payload.get("utc_start_inclusive")
        == JPL_ANALYSIS_START.astimezone(timezone.utc).isoformat()
        and payload.get("utc_end_exclusive")
        == JPL_ANALYSIS_END.astimezone(timezone.utc).isoformat()
        and payload.get("query_condition") == query.condition
        and payload.get("request_count") == 1
        and payload.get("response_fields_consumed") == ["_meta.total"]
        and payload.get("token_stored") is False
    )


def _read_official_local_month_total(raw_root: Path) -> dict[str, Any]:
    state_path = raw_root / "state" / "official_local_month_total.json"
    if not state_path.is_file():
        return {
            "status": "MISSING",
            "contract_valid": False,
            "total": None,
            "reason_code": "OFFICIAL_LOCAL_MONTH_TOTAL_MISSING",
        }
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict) or not _official_month_total_contract(payload):
        return {
            "status": "INVALID",
            "contract_valid": False,
            "total": None,
            "reason_code": "OFFICIAL_LOCAL_MONTH_TOTAL_CONTRACT_INVALID",
        }
    total = payload.get("official_meta_total")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        return {
            "status": "INVALID",
            "contract_valid": False,
            "total": None,
            "reason_code": "OFFICIAL_LOCAL_MONTH_TOTAL_CONTRACT_INVALID",
        }
    return {
        "status": "VALID",
        "contract_valid": True,
        "total": total,
        "reason_code": None,
        "source": _SOURCE,
        "scope": "single_official_local_month_meta_total_probe",
        "request_count": 1,
        "response_fields_consumed": ["_meta.total"],
    }


def _empty_complete_carry_in_audit(status: str, reason_code: str | None) -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": reason_code,
        "file_count": None,
        "valid_manifest_count": None,
        "record_count": None,
        "inventory_digest": None,
        "inventory_digest_algorithm": _INVENTORY_DIGEST_ALGORITHM,
        "carry_in_session_count": None,
    }


def _complete_carry_in_state_contract(payload: Mapping[str, Any]) -> bool:
    integer_fields = (
        "file_count",
        "valid_manifest_count",
        "record_count",
        "carry_in_session_count",
    )
    values_are_counts = all(
        isinstance(payload.get(field), int)
        and not isinstance(payload.get(field), bool)
        and payload[field] >= 0
        for field in integer_fields
    )
    digest = payload.get("inventory_digest")
    digest_valid = (
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )
    return (
        payload.get("schema_version") == "acn-jpl-complete-carry-in-audit/v1"
        and payload.get("source") == _SOURCE
        and payload.get("site") == "jpl"
        and payload.get("timezone") == JPL_TIMEZONE
        and payload.get("scope") == "full_official_history_before_analysis_start"
        and payload.get("analysis_start_utc")
        == JPL_ANALYSIS_START.astimezone(timezone.utc).isoformat()
        and payload.get("complete_input_validated") is True
        and payload.get("identifiers_emitted") is False
        and payload.get("token_stored") is False
        and values_are_counts
        and payload.get("valid_manifest_count") == payload.get("file_count")
        and payload.get("inventory_digest_algorithm") == _INVENTORY_DIGEST_ALGORITHM
        and digest_valid
    )


def _read_complete_carry_in_state(raw_root: Path) -> dict[str, Any]:
    state_path = raw_root / "state" / "complete_carry_in_audit.json"
    if not state_path.is_file():
        return _empty_complete_carry_in_audit("NOT_PROVIDED", None)
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict) or not _complete_carry_in_state_contract(payload):
        return _empty_complete_carry_in_audit(
            "INVALID_STATE",
            "COMPLETE_CARRY_IN_AUDIT_STATE_INVALID",
        )
    return {
        "status": "VALIDATED_STATE",
        "reason_code": None,
        "file_count": payload["file_count"],
        "valid_manifest_count": payload["valid_manifest_count"],
        "record_count": payload["record_count"],
        "inventory_digest": payload["inventory_digest"],
        "inventory_digest_algorithm": _INVENTORY_DIGEST_ALGORITHM,
        "carry_in_session_count": payload["carry_in_session_count"],
    }


def _legacy_full_manifest_valid(
    manifest: object,
    *,
    record_count: int,
    sha256: str,
) -> bool:
    return (
        isinstance(manifest, Mapping)
        and manifest.get("schema_version") == 1
        and manifest.get("endpoint") == "sessions/jpl"
        and manifest.get("site") == "jpl"
        and manifest.get("mode") == "metadata"
        and manifest.get("record_count") == record_count
        and manifest.get("source_total") == record_count
        and manifest.get("sha256") == sha256
    )


def _audit_complete_metadata_path(full_metadata_path: str | Path) -> dict[str, Any]:
    directory = Path(full_metadata_path)
    files = sorted(directory.glob("*.jsonl.gz")) if directory.is_dir() else []
    if not files:
        return _empty_complete_carry_in_audit(
            "INPUT_INVALID",
            "COMPLETE_CARRY_IN_INPUT_INVALID",
        )

    inventory = hashlib.sha256()
    record_count = 0
    valid_manifest_count = 0
    carry_in_session_keys: set[str] = set()
    analysis_start = JPL_ANALYSIS_START.astimezone(timezone.utc)
    input_valid = True
    for data_path in files:
        digest = _sha256_file(data_path)
        file_records: list[Mapping[str, Any]] = []
        try:
            with gzip.open(data_path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise TypeError("full metadata record must be an object")
                    file_records.append(item)
        except (
            OSError,
            EOFError,
            UnicodeError,
            json.JSONDecodeError,
            TypeError,
        ):
            input_valid = False
            file_records = []
        manifest_path = data_path.with_name(data_path.name + ".manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            manifest = None
        if _legacy_full_manifest_valid(
            manifest,
            record_count=len(file_records),
            sha256=digest,
        ):
            valid_manifest_count += 1
        else:
            input_valid = False
        inventory.update(
            f"{data_path.name}\0{digest}\0{len(file_records)}\n".encode()
        )
        record_count += len(file_records)
        for record in file_records:
            connection = _safe_datetime(record.get("connectionTime"))
            disconnect = _safe_datetime(record.get("disconnectTime"))
            session_id = record.get("sessionID")
            if (
                connection is not None
                and disconnect is not None
                and connection < analysis_start < disconnect
                and session_id not in (None, "")
            ):
                carry_in_session_keys.add(_private_key(session_id))

    if not input_valid or valid_manifest_count != len(files):
        status = "INPUT_INVALID"
        reason_code = "COMPLETE_CARRY_IN_INPUT_INVALID"
    else:
        status = "COMPLETE_INPUT_VALIDATED"
        reason_code = None
    return {
        "status": status,
        "reason_code": reason_code,
        "file_count": len(files),
        "valid_manifest_count": valid_manifest_count,
        "record_count": record_count,
        "inventory_digest": inventory.hexdigest(),
        "inventory_digest_algorithm": _INVENTORY_DIGEST_ALGORITHM,
        "carry_in_session_count": len(carry_in_session_keys),
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


def _month_slice_summary(
    records: list[Mapping[str, Any]],
    connections: list[datetime],
    *,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    object_ids = _identifier_counts([record.get("_id") for record in records])
    session_ids = _identifier_counts([record.get("sessionID") for record in records])
    return {
        "start_inclusive": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "record_count": len(records),
        "unique_object_ids": object_ids["unique"],
        "missing_object_ids": object_ids["missing"],
        "duplicate_object_id_records": object_ids["duplicate_records"],
        "unique_session_ids": session_ids["unique"],
        "missing_session_ids": session_ids["missing"],
        "duplicate_session_id_records": session_ids["duplicate_records"],
        "actual_connection_range_utc": _datetime_range(connections),
    }


def _session_key_set(records: list[Mapping[str, Any]]) -> set[str]:
    return {
        _private_key(record["sessionID"])
        for record in records
        if record.get("sessionID") not in (None, "")
    }


def evaluate_jpl_metadata(
    raw_root: str | Path,
    *,
    full_metadata_path: str | Path | None = None,
) -> dict[str, Any]:
    """Aggregate 38 raw daily chunks while emitting counts, never identifier values."""

    root = Path(raw_root)
    complete_carry_in_audit = (
        _audit_complete_metadata_path(full_metadata_path)
        if full_metadata_path is not None
        else _read_complete_carry_in_state(root)
    )
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
    utc_month_records: list[Mapping[str, Any]] = []
    utc_month_connections: list[datetime] = []
    left_slice_records: list[Mapping[str, Any]] = []
    left_slice_connections: list[datetime] = []
    right_slice_records: list[Mapping[str, Any]] = []
    right_slice_connections: list[datetime] = []
    acquisition_connections: list[datetime] = []
    buffer_connection_records: list[Mapping[str, Any]] = []
    carry_in_records: list[Mapping[str, Any]] = []
    connection_after_disconnect = 0
    done_before_connection = 0
    done_after_disconnect = 0
    for record, connection, disconnect, done in parsed_records:
        if connection is not None:
            acquisition_connections.append(connection)
        if connection is not None and _UTC_MONTH_START <= connection < _UTC_MONTH_END:
            utc_month_records.append(record)
            utc_month_connections.append(connection)
        if connection is not None and _UTC_MONTH_START <= connection < analysis_start_utc:
            left_slice_records.append(record)
            left_slice_connections.append(connection)
        if connection is not None and _UTC_MONTH_END <= connection < analysis_end_utc:
            right_slice_records.append(record)
            right_slice_connections.append(connection)
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
    utc_month_summary = _month_slice_summary(
        utc_month_records,
        utc_month_connections,
        start=_UTC_MONTH_START,
        end=_UTC_MONTH_END,
    )
    local_month_summary = _month_slice_summary(
        analysis_records,
        analysis_connections,
        start=JPL_ANALYSIS_START,
        end=JPL_ANALYSIS_END,
    )
    left_slice_summary = _month_slice_summary(
        left_slice_records,
        left_slice_connections,
        start=_UTC_MONTH_START,
        end=analysis_start_utc,
    )
    right_slice_summary = _month_slice_summary(
        right_slice_records,
        right_slice_connections,
        start=_UTC_MONTH_END,
        end=analysis_end_utc,
    )
    month_boundary_comparison = {
        "A_utc_month": utc_month_summary,
        "B_local_month": local_month_summary,
        "C_left_slice_utc_only": left_slice_summary,
        "D_right_slice_local_only": right_slice_summary,
        "set_identity": {
            "B_equals_A_minus_C_plus_D": (
                _session_key_set(analysis_records)
                == (_session_key_set(utc_month_records) - _session_key_set(left_slice_records))
                | _session_key_set(right_slice_records)
            )
        },
    }
    carry_in_ids = _identifier_counts(
        [record.get("sessionID") for record in carry_in_records]
    )
    carry_in = {
        "record_count": len(carry_in_records),
        "unique_session_ids": carry_in_ids["unique"],
        "observed_seven_day_session_count": carry_in_ids["unique"],
        "complete_audit_status": complete_carry_in_audit["status"],
        "complete_audit_session_count": complete_carry_in_audit[
            "carry_in_session_count"
        ],
        "completeness": (
            "PROVEN_BY_COMPLETE_AUDIT"
            if complete_carry_in_audit["status"]
            in {"COMPLETE_INPUT_VALIDATED", "VALIDATED_STATE"}
            else "NOT_PROVEN"
        ),
    }
    buffer = {
        "connection_session_count": len(buffer_connection_records),
        "carry_in_session_count": len(carry_in_records),
        "observed_start_inclusive": JPL_ACQUISITION_START.isoformat(),
        "observed_end_exclusive": JPL_ANALYSIS_START.isoformat(),
        "sufficiency": {
            "status": "PARTIAL_OBSERVATION_ONLY",
            "assessment_zh": (
                "七日缓冲只说明局部观测范围，不能证明更早连接且仍活跃的会话不存在；"
                "完整性只能由单独的全历史 carry-in 审计支持。"
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

    official_local_month_total = _read_official_local_month_total(root)
    official_contract_valid = official_local_month_total["contract_valid"] is True
    official_total_matches = (
        official_contract_valid
        and official_local_month_total["total"] == analysis["unique_session_ids"]
    )
    if not official_contract_valid:
        failures.add(
            (
                "official_local_month_total",
                official_local_month_total["reason_code"],
            )
        )
    elif not official_total_matches:
        failures.add(
            (
                "official_local_month_total",
                "OFFICIAL_LOCAL_MONTH_TOTAL_MISMATCH",
            )
        )
    all_chunks_valid = chunk_counts["valid"] == len(windows)
    all_remote_totals_match = chunk_counts["remote_total_match"] == len(windows)
    manifest_sha_json_integrity = all(
        chunk_counts[field] == len(windows)
        for field in (
            "manifest_valid_json",
            "manifest_contract_match",
            "manifest_boundary_match",
            "complete_for_query",
            "hash_match",
            "jsonl_valid",
            "record_count_match",
        )
    )
    integrity_passed = (
        all_chunks_valid
        and all_remote_totals_match
        and manifest_sha_json_integrity
        and identifier_integrity
    )
    gate_passed = integrity_passed and official_total_matches
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
        "official_local_month_total": official_local_month_total,
        "observed_analysis_unique_session_ids": analysis["unique_session_ids"],
        "observed_B_local_month_unique_session_ids": analysis["unique_session_ids"],
        "month_boundary_comparison": month_boundary_comparison,
        "complete_carry_in_audit": complete_carry_in_audit,
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
            "conditions": {
                "all_38_chunks_valid": all_chunks_valid,
                "all_38_remote_totals_match": all_remote_totals_match,
                "manifest_sha_json_integrity": manifest_sha_json_integrity,
                "identifier_integrity": identifier_integrity,
                "official_local_month_total_contract_valid": official_contract_valid,
                "official_local_month_total_equals_B": official_total_matches,
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


def _contains_private_identifier_key(value: object) -> bool:
    if isinstance(value, Mapping):
        if any(key in {"_id", "sessionID", "userID"} for key in value):
            return True
        return any(_contains_private_identifier_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_private_identifier_key(item) for item in value)
    return False


def _preflight_count(section: Mapping[str, Any], key: str) -> int:
    value = section.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"preflight_qa has invalid count: {key}")
    return value


def _preflight_rate(section: Mapping[str, Any], key: str) -> float:
    value = section.get(key)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
    ):
        raise ValueError(f"preflight_qa has invalid rate: {key}")
    return float(value)


def _preflight_nullable_rate(
    section: Mapping[str, Any],
    key: str,
    *,
    denominator: int,
) -> float | None:
    if denominator == 0:
        if section.get(key) is not None:
            raise ValueError(f"preflight_qa {key} must be null for a zero denominator")
        return None
    return _preflight_rate(section, key)


def _rate_consistent(
    value: float | None,
    numerator: int,
    denominator: int,
) -> bool:
    if denominator == 0:
        return value is None
    expected = round(numerator / denominator, 8)
    return value is not None and math.isclose(value, expected, abs_tol=1e-8)


def _validated_preflight_coverage(
    coverage: object,
    *,
    matched_sessions: int,
) -> dict[str, dict[str, int | float]]:
    if not isinstance(coverage, Mapping):
        raise TypeError("preflight_qa field_coverage must be an object")
    clean: dict[str, dict[str, int | float]] = {}
    for field in ("chargingCurrent", "pilotSignal", "userInputs"):
        item = coverage.get(field)
        if not isinstance(item, Mapping):
            raise TypeError(f"preflight_qa field_coverage is missing {field}")
        count = _preflight_count(item, "count")
        denominator = _preflight_count(item, "denominator")
        rate = _preflight_rate(item, "rate")
        if (
            denominator != PREFLIGHT_SAMPLE_SIZE
            or count > matched_sessions
            or not _rate_consistent(rate, count, denominator)
        ):
            raise ValueError(f"preflight_qa has inconsistent {field} coverage")
        clean[field] = {"count": count, "denominator": denominator, "rate": rate}
    return clean


_PREFLIGHT_SERIES_COUNT_KEYS = (
    "invalid_container_sessions",
    "length_mismatch_sessions",
    "duplicate_extra_timestamps",
    "nonmonotonic_pairs",
    "timestamp_parse_errors",
    "invalid_numeric_values",
    "negative_values",
    "raw_samples",
    "usable_samples",
    "expected_complete_active_minutes",
    "sparse_minutes_under_10_points",
)


def _validated_preflight_series(
    series: object,
    *,
    field: str,
) -> dict[str, Any]:
    if not isinstance(series, Mapping):
        raise TypeError(f"preflight_qa series is missing {field}")
    clean: dict[str, Any] = {
        key: _preflight_count(series, key) for key in _PREFLIGHT_SERIES_COUNT_KEYS
    }
    clean["invalid_container_rate"] = _preflight_rate(
        series, "invalid_container_rate"
    )
    clean["retained_sample_rate"] = _preflight_nullable_rate(
        series,
        "retained_sample_rate",
        denominator=clean["raw_samples"],
    )
    clean["sparse_minute_rate"] = _preflight_nullable_rate(
        series,
        "sparse_minute_rate",
        denominator=clean["expected_complete_active_minutes"],
    )
    if clean["usable_samples"] > clean["raw_samples"]:
        raise ValueError(f"preflight_qa {field} usable samples exceed raw samples")
    if clean["sparse_minutes_under_10_points"] > clean[
        "expected_complete_active_minutes"
    ]:
        raise ValueError(f"preflight_qa {field} sparse minutes exceed denominator")
    if not _rate_consistent(
        clean["invalid_container_rate"],
        clean["invalid_container_sessions"],
        PREFLIGHT_SAMPLE_SIZE,
    ):
        raise ValueError(f"preflight_qa {field} invalid-container rate is inconsistent")
    if not _rate_consistent(
        clean["retained_sample_rate"],
        clean["usable_samples"],
        clean["raw_samples"],
    ):
        raise ValueError(f"preflight_qa {field} retained rate is inconsistent")
    if not _rate_consistent(
        clean["sparse_minute_rate"],
        clean["sparse_minutes_under_10_points"],
        clean["expected_complete_active_minutes"],
    ):
        raise ValueError(f"preflight_qa {field} sparse rate is inconsistent")

    boundary_keys = (
        "boundary_positive_current_points",
        "boundary_positive_current_sessions",
        "boundary_unverifiable_sessions",
    )
    if field == "chargingCurrent":
        for key in boundary_keys:
            clean[key] = _preflight_count(series, key)
        if clean["boundary_positive_current_sessions"] > PREFLIGHT_SAMPLE_SIZE:
            raise ValueError("preflight_qa boundary-positive session count exceeds sample")
    else:
        if any(series.get(key) is not None for key in boundary_keys):
            raise ValueError("preflight_qa pilotSignal must not report current boundaries")
        clean.update({key: None for key in boundary_keys})
    return clean


def _validated_preflight_copy(preflight: Mapping[str, Any]) -> dict[str, Any]:
    if (
        preflight.get("schema_version") != "acn-jpl-ts-preflight-qa/v1"
        or _contains_private_identifier_key(preflight)
    ):
        raise ValueError("preflight_qa must be aggregate-only and free of identifiers")
    sample = preflight.get("sample")
    matching = preflight.get("matching")
    run = preflight.get("run")
    privacy = preflight.get("privacy")
    raw_series = preflight.get("series")
    declared_gate = preflight.get("gate")
    if not all(
        isinstance(section, Mapping)
        for section in (sample, matching, run, privacy, raw_series, declared_gate)
    ):
        raise ValueError("preflight_qa is missing required aggregate sections")
    assert isinstance(sample, Mapping)
    assert isinstance(matching, Mapping)
    assert isinstance(run, Mapping)
    assert isinstance(privacy, Mapping)
    assert isinstance(raw_series, Mapping)
    assert isinstance(declared_gate, Mapping)
    if (
        _preflight_count(sample, "requested_sessions") != PREFLIGHT_SAMPLE_SIZE
        or _preflight_count(sample, "selected_unique_sessions")
        != PREFLIGHT_SAMPLE_SIZE
        or sample.get("random_seed") != PREFLIGHT_RANDOM_SEED
    ):
        raise ValueError("preflight_qa sample contract is not fixed-seed 100-session")

    matched = _preflight_count(matching, "matched_sessions")
    missing = _preflight_count(matching, "missing_sessions")
    orphan = _preflight_count(matching, "orphan_sessions")
    metadata_sessions = _preflight_count(matching, "metadata_sessions")
    timeseries_records = _preflight_count(matching, "timeseries_records")
    match_rate = _preflight_rate(matching, "match_rate")
    if (
        metadata_sessions != PREFLIGHT_SAMPLE_SIZE
        or matched + missing != PREFLIGHT_SAMPLE_SIZE
        or timeseries_records != matched + orphan
        or not _rate_consistent(match_rate, matched, PREFLIGHT_SAMPLE_SIZE)
    ):
        raise ValueError("preflight_qa matching counts are inconsistent")

    downloaded = _preflight_count(run, "downloaded_sessions")
    skipped = _preflight_count(run, "skipped_sessions")
    failed = _preflight_count(run, "failed_sessions")
    if (
        run.get("serial") is not True
        or downloaded + skipped != matched
        or failed != missing
        or downloaded + skipped + failed != PREFLIGHT_SAMPLE_SIZE
    ):
        raise ValueError("preflight_qa run counts are inconsistent")

    current = _validated_preflight_series(
        raw_series.get("chargingCurrent"),
        field="chargingCurrent",
    )
    pilot = _validated_preflight_series(
        raw_series.get("pilotSignal"),
        field="pilotSignal",
    )
    coverage = _validated_preflight_coverage(
        preflight.get("field_coverage"),
        matched_sessions=matched,
    )
    for field, series_evidence in (
        ("chargingCurrent", current),
        ("pilotSignal", pilot),
    ):
        field_count = coverage[field]["count"]
        invalid_containers = series_evidence["invalid_container_sessions"]
        if (
            invalid_containers > matched
            or series_evidence["length_mismatch_sessions"] > invalid_containers
            or field_count < matched - invalid_containers
            or (field_count == 0 and series_evidence["raw_samples"] != 0)
            or (
                series_evidence["invalid_numeric_values"]
                + series_evidence["negative_values"]
                > series_evidence["raw_samples"]
            )
        ):
            raise ValueError(
                f"preflight_qa {field} coverage and series evidence are inconsistent"
            )
    if (
        current["boundary_positive_current_sessions"] > matched
        or current["boundary_positive_current_points"]
        < current["boundary_positive_current_sessions"]
    ):
        raise ValueError("preflight_qa boundary-positive counts are inconsistent")
    severe = (
        current["timestamp_parse_errors"]
        + current["nonmonotonic_pairs"]
        + pilot["timestamp_parse_errors"]
        + pilot["nonmonotonic_pairs"]
    )
    unmatched_rate = round(
        (PREFLIGHT_SAMPLE_SIZE - matched) / PREFLIGHT_SAMPLE_SIZE,
        8,
    )
    expected_status = (
        "PASS"
        if current["invalid_container_rate"]
        <= PREFLIGHT_INVALID_CHARGING_CURRENT_RATE_LIMIT
        and pilot["invalid_container_rate"]
        <= PREFLIGHT_INVALID_PILOT_SIGNAL_RATE_LIMIT
        and unmatched_rate <= PREFLIGHT_UNMATCHED_METADATA_RATE_LIMIT
        and orphan == 0
        and severe == 0
        else "FAIL"
    )
    if (
        declared_gate.get("invalid_charging_current_limit")
        != PREFLIGHT_INVALID_CHARGING_CURRENT_RATE_LIMIT
        or declared_gate.get("invalid_pilot_signal_limit")
        != PREFLIGHT_INVALID_PILOT_SIGNAL_RATE_LIMIT
        or declared_gate.get("unmatched_metadata_limit")
        != PREFLIGHT_UNMATCHED_METADATA_RATE_LIMIT
        or declared_gate.get("unmatched_metadata_rate") != unmatched_rate
        or declared_gate.get("severe_timestamp_anomalies") != severe
        or declared_gate.get("status") != expected_status
    ):
        raise ValueError("preflight_qa gate is inconsistent with aggregate evidence")
    if (
        privacy.get("aggregate_only") is not True
        or privacy.get("identifiers_emitted") is not False
        or privacy.get("token_emitted") is not False
    ):
        raise ValueError("preflight_qa privacy declaration is invalid")

    return {
        "schema_version": "acn-jpl-ts-preflight-qa/v1",
        "sample": {
            "requested_sessions": PREFLIGHT_SAMPLE_SIZE,
            "selected_unique_sessions": PREFLIGHT_SAMPLE_SIZE,
            "random_seed": PREFLIGHT_RANDOM_SEED,
        },
        "matching": {
            "metadata_sessions": metadata_sessions,
            "timeseries_records": timeseries_records,
            "matched_sessions": matched,
            "missing_sessions": missing,
            "orphan_sessions": orphan,
            "match_rate": match_rate,
        },
        "field_coverage": coverage,
        "series": {"chargingCurrent": current, "pilotSignal": pilot},
        "gate": {
            "status": expected_status,
            "invalid_charging_current_limit": (
                PREFLIGHT_INVALID_CHARGING_CURRENT_RATE_LIMIT
            ),
            "invalid_pilot_signal_limit": PREFLIGHT_INVALID_PILOT_SIGNAL_RATE_LIMIT,
            "unmatched_metadata_limit": PREFLIGHT_UNMATCHED_METADATA_RATE_LIMIT,
            "unmatched_metadata_rate": unmatched_rate,
            "severe_timestamp_anomalies": severe,
        },
        "run": {
            "downloaded_sessions": downloaded,
            "skipped_sessions": skipped,
            "failed_sessions": failed,
            "serial": True,
        },
        "privacy": {
            "aggregate_only": True,
            "identifiers_emitted": False,
            "token_emitted": False,
        },
    }


def _build_timeseries_preflight(
    metadata: Mapping[str, Any],
    preflight: Mapping[str, Any],
) -> dict[str, Any]:
    """Wrap an aggregate-only preflight result without implying full-month coverage."""

    clean = _validated_preflight_copy(preflight)
    matching = clean["matching"]
    coverage = clean["field_coverage"]
    series = clean["series"]
    gate = clean["gate"]
    preflight_status = str(gate["status"])
    return {
        "schema_version": "acn-jpl-timeseries-qa/v2",
        "dataset_id": "D0001",
        "site": "jpl",
        "status": f"PREFLIGHT_{preflight_status}",
        "scope": "FIXED_SEED_100_SESSION_PREFLIGHT_ONLY",
        "download_attempted": True,
        "reason_code": None if preflight_status == "PASS" else "PREFLIGHT_QA_FAILED",
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
        "field_coverage": dict(coverage),
        "quality": {
            "chargingCurrent": dict(series.get("chargingCurrent", {})),
            "pilotSignal": dict(series.get("pilotSignal", {})),
        },
        "session_linkage": dict(matching),
        "daily_timeseries_record_counts": dict(
            sorted(metadata["daily"]["timeseries_record_counts"].items())
        ),
        "preflight": clean,
        "full_month": {
            "status": "NOT_RUN",
            "download_attempted": False,
            "reason_code": "STOP_AFTER_100_SESSION_PREFLIGHT_FOR_CONTROLLER_REVIEW",
        },
        "privacy": _privacy_declaration(),
    }


def _summary_json(metadata: Mapping[str, Any], timeseries: Mapping[str, Any]) -> dict[str, Any]:
    preflight = timeseries.get("preflight")
    preflight_gate = "NOT_RUN"
    if (
        isinstance(preflight, Mapping)
        and preflight.get("schema_version") == "acn-jpl-ts-preflight-qa/v1"
    ):
        gate = preflight.get("gate")
        if isinstance(gate, Mapping) and gate.get("status") in {"PASS", "FAIL"}:
            preflight_gate = str(gate["status"])
    metadata_gate = str(metadata["gate"]["status"])
    overall_status = (
        "FAIL"
        if metadata_gate == "FAIL" or preflight_gate == "FAIL"
        else "PASS"
    )
    return {
        "schema_version": "acn-jpl-acquisition-summary/v1",
        "dataset_id": "D0001",
        "site": "jpl",
        "source": _SOURCE,
        "gate_status": overall_status,
        "overall_status": overall_status,
        "metadata_gate_status": metadata_gate,
        "official_local_month_total": metadata["official_local_month_total"],
        "observed_analysis_unique_session_ids": metadata[
            "observed_analysis_unique_session_ids"
        ],
        "month_boundary_comparison": metadata["month_boundary_comparison"],
        "complete_carry_in_audit": metadata["complete_carry_in_audit"],
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
            "preflight": preflight,
            "full_month": timeseries.get(
                "full_month",
                {"status": "NOT_RUN", "download_attempted": False},
            ),
            "daily_timeseries_record_counts": timeseries[
                "daily_timeseries_record_counts"
            ],
        },
        "gate_decision": {
            "metadata_gate": metadata_gate,
            "timeseries_preflight_gate": preflight_gate,
            "full_month_timeseries": "NOT_RUN",
            "ready_for_controller_review": (
                metadata_gate == "PASS" and preflight_gate == "PASS"
            ),
        },
        "privacy": _privacy_declaration(),
        "limitations": [
            "The 100-session preflight does not establish full-month time-series coverage.",
            "Charging current is not direct active power without voltage and phase metadata.",
        ],
    }


def _summary_markdown(metadata: Mapping[str, Any], timeseries: Mapping[str, Any]) -> str:
    observed = metadata["observed_analysis_unique_session_ids"]
    expected = metadata["official_local_month_total"]["total"]
    metadata_status = str(metadata["gate"]["status"])
    preflight_payload = timeseries.get("preflight")
    preflight_status = "NOT_RUN"
    if (
        isinstance(preflight_payload, Mapping)
        and preflight_payload.get("schema_version")
        == "acn-jpl-ts-preflight-qa/v1"
    ):
        preflight_gate = preflight_payload.get("gate")
        if isinstance(preflight_gate, Mapping):
            preflight_status = str(preflight_gate.get("status", "NOT_RUN"))
    overall_status = (
        "FAIL"
        if metadata_status == "FAIL" or preflight_status == "FAIL"
        else "PASS"
    )
    if expected is None:
        mismatch_note = "独立官方当地月 `_meta.total` 缺失或契约无效，不能通过门控。"
    elif observed != expected:
        mismatch_note = f"仅凭 {observed} 与 {expected} 的计数差异不能定位具体缺失会话。"
    else:
        mismatch_note = "当地月唯一会话数与独立官方 `_meta.total` 一致。"
    comparison = metadata["month_boundary_comparison"]
    lines = [
            "# JPL 2019-05 ACN-Data Gate 0 修订与预检",
            "",
            f"- 数据源：{_SOURCE}",
            f"- 总体状态：{overall_status}",
            f"- 元数据门控：{metadata_status}",
            f"- 100 会话预检：{preflight_status}",
            f"- 当地月唯一 sessionID：38 块观测 {observed}，独立官方 `_meta.total` {expected}",
            f"- 每日完整块：{metadata['chunks']['valid']}/{metadata['chunks']['expected']}",
            (
                "- 月份口径："
                f"A UTC={comparison['A_utc_month']['unique_session_ids']}，"
                f"B 当地={comparison['B_local_month']['unique_session_ids']}，"
                f"C 左切片={comparison['C_left_slice_utc_only']['unique_session_ids']}，"
                f"D 右切片={comparison['D_right_slice_local_only']['unique_session_ids']}"
            ),
            (
                "- 完整历史 carry-in："
                f"{metadata['complete_carry_in_audit']['carry_in_session_count']}"
                f"（{metadata['complete_carry_in_audit']['status']}）"
            ),
            "",
            mismatch_note,
            "",
    ]
    preflight = preflight_payload
    if (
        isinstance(preflight, Mapping)
        and preflight.get("schema_version") == "acn-jpl-ts-preflight-qa/v1"
    ):
        sample = preflight["sample"]
        matching = preflight["matching"]
        coverage = preflight["field_coverage"]
        current = preflight["series"]["chargingCurrent"]
        pilot = preflight["series"]["pilotSignal"]
        lines.extend(
            [
                "## 100 会话 `/ts` 预检",
                "",
                (
                    f"- 固定种子 {sample['random_seed']}；"
                    f"匹配 {matching['matched_sessions']}/{sample['requested_sessions']}；"
                    f"状态 {preflight['gate']['status']}"
                ),
                f"- chargingCurrent 覆盖率：{coverage['chargingCurrent']['rate']}",
                f"- pilotSignal 覆盖率：{coverage['pilotSignal']['rate']}",
                f"- userInputs 覆盖率：{coverage['userInputs']['rate']}",
                (
                    "- 无效容器："
                    f"current={current['invalid_container_sessions']}，"
                    f"pilot={pilot['invalid_container_sessions']}"
                ),
                (
                    "- 重复时间戳："
                    f"current={current['duplicate_extra_timestamps']}，"
                    f"pilot={pilot['duplicate_extra_timestamps']}；"
                    "非单调时间戳："
                    f"current={current['nonmonotonic_pairs']}，"
                    f"pilot={pilot['nonmonotonic_pairs']}"
                ),
                (
                    "- 稀疏分钟率："
                    f"current={current['sparse_minute_rate']}，"
                    f"pilot={pilot['sparse_minute_rate']}"
                ),
                (
                    "- 采样点保留率："
                    f"current={current['retained_sample_rate']}，"
                    f"pilot={pilot['retained_sample_rate']}"
                ),
                (
                    "- 会话边界外正电流："
                    f"{current['boundary_positive_current_points']} 点 / "
                    f"{current['boundary_positive_current_sessions']} 会话"
                ),
                "- 未下载完整月份 `/ts`；在100会话预检后停止，等待主控复核。",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"- `/ts` 状态：{timeseries['status']}，未启动；download_attempted=false",
                "",
            ]
        )
    lines.extend(
        [
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
    return "\n".join(lines)


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
    *,
    full_metadata_path: str | Path | None = None,
    preflight_qa: Mapping[str, Any] | None = None,
) -> Phase1MetadataQAResult:
    """Evaluate Phase 1 and atomically write a deterministic, deidentified delivery."""

    metadata = evaluate_jpl_metadata(
        raw_root,
        full_metadata_path=full_metadata_path,
    )
    if preflight_qa is None or metadata["gate"]["status"] != "PASS":
        timeseries = _build_timeseries_not_run(metadata)
    else:
        timeseries = _build_timeseries_preflight(metadata, preflight_qa)
        matching = preflight_qa["matching"]
        metadata["actual_scope"]["timeseries_status"] = "PREFLIGHT_100_ONLY"
        metadata["daily"]["timeseries_status"] = "PREFLIGHT_100_ONLY"
        metadata["timeseries_linkage"] = {
            "status": "PREFLIGHT_100_ONLY",
            "missing_timeseries_sessions": matching.get("missing_sessions"),
            "orphan_timeseries_sessions": matching.get("orphan_sessions"),
        }
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
        if failure["reason_code"] == "OFFICIAL_LOCAL_MONTH_TOTAL_MISMATCH":
            row["expected_count"] = metadata["official_local_month_total"]["total"]
            row["observed_count"] = metadata["observed_analysis_unique_session_ids"]
        else:
            row["expected_count"] = None
            row["observed_count"] = None
        csv_rows.append(row)
    if timeseries["status"] == "PREFLIGHT_FAIL":
        csv_rows.append(
            {
                "scope": "timeseries_preflight",
                "reason_code": "TIMESERIES_PREFLIGHT_QA_FAILED",
                "expected_count": PREFLIGHT_SAMPLE_SIZE,
                "observed_count": timeseries["session_linkage"]["matched_sessions"],
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
        gate_status=summary["overall_status"],
        qa_metadata=metadata,
        qa_timeseries=timeseries,
        output_paths=paths,
    )
