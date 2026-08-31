"""Streaming, deidentified QA for the frozen JPL May 2019 full-month ``/ts`` scope.

The module reads one JSONL record at a time.  Private identifier keys are retained
only in in-memory counters used for exact linkage; public artifacts contain aggregate
counts, rules, decisions, and daily dates only.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from .acn_api import ACNQuery
from .acn_audit import parse_acn_datetime
from .acn_jpl_full_month_ts import (
    EXPECTED_ANALYSIS_SESSION_COUNT,
    EXPECTED_CARRY_IN_SESSION_COUNT,
    EXPECTED_UTC_MONTH_SESSION_COUNT,
    FullMonthMetadataError,
    _carry_in_paths,
    _carry_in_query,
    _load_metadata_scope,
    _PrivateMetadataScope,
    _PrivateSession,
)
from .acn_jpl_gate0 import JPL_TIMEZONE, chunk_paths, jpl_analysis_windows

EXPECTED_TOTAL_SESSION_COUNT = EXPECTED_ANALYSIS_SESSION_COUNT + EXPECTED_CARRY_IN_SESSION_COUNT
INVALID_CHARGING_CURRENT_RATE_LIMIT = 0.10
INVALID_PILOT_SIGNAL_RATE_LIMIT = 0.10

PUBLIC_ARTIFACT_NAMES = (
    "qa_full_month_timeseries.json",
    "acquisition_summary.json",
    "acquisition_summary.md",
    "daily_chunk_summary.csv",
    "failed_or_incomplete_chunks.csv",
    "cleaning_rule_manifest.json",
    "SHA256SUMS",
)
_HASHED_ARTIFACT_NAMES = PUBLIC_ARTIFACT_NAMES[:-1]

_CURRENT_FIELD = "chargingCurrent"
_PILOT_FIELD = "pilotSignal"
_VALUE_KEYS = {_CURRENT_FIELD: "current", _PILOT_FIELD: "pilot"}
_FORBIDDEN_PUBLIC_KEYS = {
    "_id",
    "sessionid",
    "userid",
    "query_condition",
    "raw_root",
    "metadata_root",
    "output_root",
    "hostname",
    "username",
    "timestamps",
    "values",
}
_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?i)(?:\b[a-z]:[\\/]|\\\\|(?:^|[\s\"'(])/(?:home|users|tmp|var|etc|mnt)/)"
)


@dataclass(frozen=True)
class FullMonthQAResult:
    """Public aggregate QA plus private return metadata for the caller."""

    gate_status: str
    qa: dict[str, Any]
    artifact_names: tuple[str, ...] = PUBLIC_ARTIFACT_NAMES


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 8) if denominator > 0 else None


def _safe_datetime(value: Any) -> datetime | None:
    try:
        return parse_acn_datetime(value)
    except (TypeError, ValueError):
        return None


def _is_non_utc_encoding(value: Any) -> bool:
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = parsedate_to_datetime(value)
        else:
            return False
    except (TypeError, ValueError):
        return False
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return False
    return parsed.utcoffset() != timedelta(0)


def _complete_minute_window(
    connection: datetime | None,
    disconnect: datetime | None,
) -> tuple[datetime | None, datetime | None, int]:
    if connection is None or disconnect is None or disconnect <= connection:
        return None, None, 0
    start = connection.replace(second=0, microsecond=0)
    if start < connection:
        start += timedelta(minutes=1)
    end = disconnect.replace(second=0, microsecond=0)
    count = max(0, int((end - start).total_seconds() // 60))
    return start, end, count


@dataclass
class _SeriesAccumulator:
    field_name: str
    coverage: int = 0
    invalid_containers: int = 0
    length_mismatches: int = 0
    timestamp_parse_errors: int = 0
    non_utc_encodings: int = 0
    duplicate_extra: int = 0
    duplicate_sessions: int = 0
    conflicting_duplicate_timestamps: int = 0
    conflicting_duplicate_sessions: int = 0
    nonmonotonic_pairs: int = 0
    nonmonotonic_sessions: int = 0
    nonnumeric_values: int = 0
    negative_values: int = 0
    raw_samples: int = 0
    usable_samples: int = 0
    expected_minutes: int = 0
    sparse_minutes: int = 0
    boundary_positive_points: int = 0
    boundary_positive_sessions: int = 0
    boundary_unverifiable_sessions: int = 0

    def add(self, record: Mapping[str, Any]) -> None:
        series = record.get(self.field_name)
        if series is not None:
            self.coverage += 1
        timestamps = series.get("timestamps") if isinstance(series, Mapping) else None
        values = series.get(_VALUE_KEYS[self.field_name]) if isinstance(series, Mapping) else None
        timestamps_are_list = isinstance(timestamps, list)
        values_are_list = isinstance(values, list)
        if values_are_list:
            self.raw_samples += len(values)

        aligned = timestamps_are_list and values_are_list and len(timestamps) == len(values)
        if not aligned:
            self.invalid_containers += 1
            if timestamps_are_list and values_are_list:
                self.length_mismatches += 1

        parsed_timestamps: list[datetime | None] = []
        seen_timestamps: set[datetime] = set()
        previous: datetime | None = None
        record_duplicates = 0
        record_nonmonotonic = 0
        if timestamps_are_list:
            for raw_timestamp in timestamps:
                if _is_non_utc_encoding(raw_timestamp):
                    self.non_utc_encodings += 1
                parsed = _safe_datetime(raw_timestamp)
                parsed_timestamps.append(parsed)
                if parsed is None:
                    self.timestamp_parse_errors += 1
                    continue
                if parsed in seen_timestamps:
                    self.duplicate_extra += 1
                    record_duplicates += 1
                seen_timestamps.add(parsed)
                if previous is not None and parsed < previous:
                    self.nonmonotonic_pairs += 1
                    record_nonmonotonic += 1
                previous = parsed
        if record_duplicates:
            self.duplicate_sessions += 1
        if record_nonmonotonic:
            self.nonmonotonic_sessions += 1

        numeric_values: list[float | None] = []
        if values_are_list:
            for raw_value in values:
                numeric = (
                    isinstance(raw_value, (int, float))
                    and not isinstance(raw_value, bool)
                    and math.isfinite(float(raw_value))
                )
                if not numeric:
                    self.nonnumeric_values += 1
                    numeric_values.append(None)
                    continue
                number = float(raw_value)
                if self.field_name == _CURRENT_FIELD and number < 0:
                    self.negative_values += 1
                    numeric_values.append(None)
                    continue
                numeric_values.append(number)

        connection = _safe_datetime(record.get("connectionTime"))
        disconnect = _safe_datetime(record.get("disconnectTime"))
        valid_bounds = connection is not None and disconnect is not None and disconnect > connection
        minute_start, minute_end, complete_minutes = _complete_minute_window(connection, disconnect)
        self.expected_minutes += complete_minutes

        if self.field_name == _CURRENT_FIELD and aligned and not valid_bounds:
            self.boundary_unverifiable_sessions += 1

        conflicting: set[datetime] = set()
        if aligned:
            signatures: dict[datetime, set[str]] = {}
            assert isinstance(values, list)
            for parsed, raw_value in zip(parsed_timestamps, values):
                if parsed is None:
                    continue
                signatures.setdefault(parsed, set()).add(
                    json.dumps(raw_value, ensure_ascii=False, sort_keys=True, default=str)
                )
            conflicting = {
                timestamp for timestamp, observed in signatures.items() if len(observed) > 1
            }
            if conflicting:
                self.conflicting_duplicate_timestamps += len(conflicting)
                self.conflicting_duplicate_sessions += 1

        seen_usable: set[datetime] = set()
        usable_by_minute: Counter[datetime] = Counter()
        record_boundary_positive = False
        pairs = zip(parsed_timestamps, numeric_values) if aligned else ()
        for parsed, number in pairs:
            if parsed is None or number is None:
                continue
            inside = (
                valid_bounds
                and connection is not None
                and disconnect is not None
                and connection <= parsed < disconnect
            )
            if self.field_name == _CURRENT_FIELD and number > 0 and valid_bounds and not inside:
                self.boundary_positive_points += 1
                record_boundary_positive = True
            if not inside or parsed in seen_usable or parsed in conflicting:
                continue
            seen_usable.add(parsed)
            self.usable_samples += 1
            usable_by_minute[parsed.replace(second=0, microsecond=0)] += 1
        if record_boundary_positive:
            self.boundary_positive_sessions += 1

        if complete_minutes and minute_start is not None and minute_end is not None:
            dense_minutes = sum(
                count >= 10
                for minute, count in usable_by_minute.items()
                if minute_start <= minute < minute_end
            )
            self.sparse_minutes += complete_minutes - dense_minutes

    def merge(self, other: _SeriesAccumulator) -> None:
        if self.field_name != other.field_name:
            raise ValueError("cannot merge different series fields")
        for name in self.__dataclass_fields__:  # type: ignore[attr-defined]
            if name != "field_name":
                setattr(self, name, getattr(self, name) + getattr(other, name))

    def public_dict(self, denominator: int) -> dict[str, Any]:
        current = self.field_name == _CURRENT_FIELD
        return {
            "field_coverage": {
                "count": self.coverage,
                "denominator": denominator,
                "rate": _safe_rate(self.coverage, denominator),
            },
            "invalid_container_count": self.invalid_containers,
            "invalid_container_rate": _safe_rate(self.invalid_containers, denominator),
            "timestamp_value_length_mismatch_sessions": self.length_mismatches,
            "timestamp_parse_errors": self.timestamp_parse_errors,
            "non_utc_timestamp_encodings": self.non_utc_encodings,
            "duplicate_extra_timestamps": self.duplicate_extra,
            "duplicate_affected_sessions": self.duplicate_sessions,
            "duplicate_affected_session_rate": _safe_rate(self.duplicate_sessions, denominator),
            "conflicting_duplicate_timestamps": self.conflicting_duplicate_timestamps,
            "conflicting_duplicate_sessions": self.conflicting_duplicate_sessions,
            "conflicting_duplicate_session_rate": _safe_rate(
                self.conflicting_duplicate_sessions, denominator
            ),
            "nonmonotonic_pairs": self.nonmonotonic_pairs,
            "nonmonotonic_affected_sessions": self.nonmonotonic_sessions,
            "nonmonotonic_affected_session_rate": _safe_rate(
                self.nonmonotonic_sessions, denominator
            ),
            "nonnumeric_values": self.nonnumeric_values,
            "negative_values": self.negative_values if current else None,
            "raw_samples": self.raw_samples,
            "usable_samples": self.usable_samples,
            "retained_sample_rate": _safe_rate(self.usable_samples, self.raw_samples),
            "expected_complete_active_minutes": self.expected_minutes,
            "sparse_minutes_under_10_points": self.sparse_minutes,
            "sparse_minute_rate": _safe_rate(self.sparse_minutes, self.expected_minutes),
            "boundary_positive_points": self.boundary_positive_points if current else None,
            "boundary_positive_sessions": self.boundary_positive_sessions if current else None,
            "boundary_positive_session_rate": (
                _safe_rate(self.boundary_positive_sessions, denominator) if current else None
            ),
            "boundary_unverifiable_sessions": (
                self.boundary_unverifiable_sessions if current else None
            ),
        }


@dataclass
class _QualityAccumulator:
    record_count: int = 0
    current: _SeriesAccumulator = field(default_factory=lambda: _SeriesAccumulator(_CURRENT_FIELD))
    pilot: _SeriesAccumulator = field(default_factory=lambda: _SeriesAccumulator(_PILOT_FIELD))
    done_coverage: int = 0
    done_parse_errors: int = 0
    done_before_connection: int = 0
    done_after_disconnect: int = 0
    user_inputs_coverage: int = 0
    requested_departure_coverage: int = 0
    requested_energy_coverage: int = 0

    def add(self, record: Mapping[str, Any]) -> None:
        self.record_count += 1
        self.current.add(record)
        self.pilot.add(record)
        connection = _safe_datetime(record.get("connectionTime"))
        disconnect = _safe_datetime(record.get("disconnectTime"))
        raw_done = record.get("doneChargingTime")
        if raw_done not in (None, ""):
            self.done_coverage += 1
            done = _safe_datetime(raw_done)
            if done is None:
                self.done_parse_errors += 1
            else:
                self.done_before_connection += int(connection is not None and done < connection)
                self.done_after_disconnect += int(disconnect is not None and done > disconnect)

        inputs = record.get("userInputs")
        valid_inputs = inputs if isinstance(inputs, list) else []
        if valid_inputs:
            self.user_inputs_coverage += 1
        requested_departure = False
        requested_energy = False
        for item in valid_inputs:
            if not isinstance(item, Mapping):
                continue
            requested_departure |= item.get("requestedDeparture") not in (None, "")
            requested_energy |= item.get("kWhRequested") not in (None, "")
        self.requested_departure_coverage += int(requested_departure)
        self.requested_energy_coverage += int(requested_energy)

    def merge(self, other: _QualityAccumulator) -> None:
        self.record_count += other.record_count
        self.current.merge(other.current)
        self.pilot.merge(other.pilot)
        for name in (
            "done_coverage",
            "done_parse_errors",
            "done_before_connection",
            "done_after_disconnect",
            "user_inputs_coverage",
            "requested_departure_coverage",
            "requested_energy_coverage",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))

    @staticmethod
    def _coverage(count: int, denominator: int) -> dict[str, Any]:
        return {"count": count, "denominator": denominator, "rate": _safe_rate(count, denominator)}

    def public_dict(self, denominator: int) -> dict[str, Any]:
        return {
            "denominator_sessions": denominator,
            "observed_validated_sessions": self.record_count,
            "series": {
                _CURRENT_FIELD: self.current.public_dict(denominator),
                _PILOT_FIELD: self.pilot.public_dict(denominator),
            },
            "metadata_fields": {
                "done_charging_coverage": self._coverage(self.done_coverage, denominator),
                "done_charging_parse_errors": self.done_parse_errors,
                "done_charging_before_connection": self._coverage(
                    self.done_before_connection, denominator
                ),
                "done_charging_after_disconnect": self._coverage(
                    self.done_after_disconnect, denominator
                ),
                "user_inputs_coverage": self._coverage(self.user_inputs_coverage, denominator),
                "requested_departure_coverage": self._coverage(
                    self.requested_departure_coverage, denominator
                ),
                "kwh_requested_coverage": self._coverage(
                    self.requested_energy_coverage, denominator
                ),
            },
        }


def audit_quality_records(
    records: Iterable[Mapping[str, Any]],
    *,
    denominator: int,
) -> dict[str, Any]:
    """Audit an iterable without materializing it; intended for synthetic QA tests too."""

    if denominator < 0:
        raise ValueError("denominator must be nonnegative")
    accumulator = _QualityAccumulator()
    for record in records:
        accumulator.add(record)
    return accumulator.public_dict(denominator)


@dataclass
class _PrivateInventory:
    record_count: int = 0
    missing_object_keys: int = 0
    missing_session_keys: int = 0
    object_keys: Counter[str] = field(default_factory=Counter, repr=False)
    session_keys: Counter[str] = field(default_factory=Counter, repr=False)
    pairs: Counter[tuple[str, str]] = field(default_factory=Counter, repr=False)

    def add(self, record: Mapping[str, Any]) -> None:
        self.record_count += 1
        object_key = record.get("_id")
        session_key = record.get("sessionID")
        object_valid = isinstance(object_key, str) and bool(object_key)
        session_valid = isinstance(session_key, str) and bool(session_key)
        if object_valid:
            self.object_keys[object_key] += 1
        else:
            self.missing_object_keys += 1
        if session_valid:
            self.session_keys[session_key] += 1
        else:
            self.missing_session_keys += 1
        if object_valid and session_valid:
            self.pairs[(object_key, session_key)] += 1

    def merge(self, other: _PrivateInventory) -> None:
        self.record_count += other.record_count
        self.missing_object_keys += other.missing_object_keys
        self.missing_session_keys += other.missing_session_keys
        self.object_keys.update(other.object_keys)
        self.session_keys.update(other.session_keys)
        self.pairs.update(other.pairs)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class _ChunkScan:
    local_date: str
    data_present: bool
    manifest_present: bool
    manifest_contract_valid: bool
    sha256_verified: bool
    gzip_json_valid: bool
    record_count: int
    manifest_record_count: int | None
    remote_total_reported: int | None
    record_count_matches_manifest: bool
    record_count_matches_remote: bool
    status: str
    reason_code: str
    inventory: _PrivateInventory = field(repr=False)
    quality: _QualityAccumulator = field(repr=False)

    def daily_row(self) -> dict[str, Any]:
        return {
            "local_date": self.local_date,
            "status": self.status,
            "data_present": self.data_present,
            "manifest_present": self.manifest_present,
            "manifest_contract_valid": self.manifest_contract_valid,
            "sha256_verified": self.sha256_verified,
            "gzip_json_valid": self.gzip_json_valid,
            "record_count": self.record_count,
            "manifest_record_count": self.manifest_record_count,
            "remote_total_reported": self.remote_total_reported,
            "record_count_matches_manifest": self.record_count_matches_manifest,
            "record_count_matches_remote": self.record_count_matches_remote,
            "reason_code": self.reason_code,
        }


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _scan_daily_chunk(raw_root: Path, window: Any) -> _ChunkScan:
    data_path, manifest_path = chunk_paths(raw_root, "timeseries", window)
    data_present = data_path.is_file()
    manifest_present = manifest_path.is_file()
    manifest: dict[str, Any] | None = None
    if manifest_present:
        try:
            candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            candidate = None
        if isinstance(candidate, dict):
            manifest = candidate

    expected_query = ACNQuery(
        site="jpl",
        start=window.local_start,
        end=window.local_end,
        timeseries=True,
    )
    expected_context = {
        "schema_version": "acn-jpl-daily-chunk/v1",
        "site": "jpl",
        "timezone": JPL_TIMEZONE,
        "local_start_inclusive": window.local_start.isoformat(),
        "local_end_exclusive": window.local_end.isoformat(),
        "utc_start_inclusive": window.utc_start.isoformat(),
        "utc_end_exclusive": window.utc_end.isoformat(),
        "query_condition": expected_query.condition,
        "endpoint": expected_query.endpoint,
    }
    manifest_record_count = manifest.get("record_count") if manifest is not None else None
    remote_total = manifest.get("remote_total_reported") if manifest is not None else None
    manifest_contract_valid = bool(
        manifest is not None
        and all(manifest.get(key) == value for key, value in expected_context.items())
        and manifest.get("complete_for_query") is True
        and manifest.get("token_stored") is False
        and _is_nonnegative_int(manifest_record_count)
        and _is_nonnegative_int(remote_total)
    )
    sha_verified = bool(
        data_present
        and manifest is not None
        and isinstance(manifest.get("sha256"), str)
        and _sha256_file(data_path) == manifest.get("sha256")
    )

    inventory = _PrivateInventory()
    quality = _QualityAccumulator()
    gzip_json_valid = False
    if data_present:
        try:
            with gzip.open(data_path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise TypeError("record root is not an object")
                    inventory.add(record)
                    quality.add(record)
            gzip_json_valid = True
        except (OSError, EOFError, UnicodeError, json.JSONDecodeError, TypeError):
            gzip_json_valid = False

    record_matches_manifest = bool(
        gzip_json_valid
        and _is_nonnegative_int(manifest_record_count)
        and inventory.record_count == manifest_record_count
    )
    record_matches_remote = bool(
        gzip_json_valid
        and _is_nonnegative_int(remote_total)
        and inventory.record_count == remote_total
    )
    valid = all(
        (
            data_present,
            manifest_present,
            manifest_contract_valid,
            sha_verified,
            gzip_json_valid,
            record_matches_manifest,
            record_matches_remote,
        )
    )
    if not data_present:
        reason = "MISSING_DATA"
    elif not manifest_present:
        reason = "MISSING_MANIFEST"
    elif manifest is None:
        reason = "INVALID_MANIFEST_JSON"
    elif not manifest_contract_valid:
        reason = "MANIFEST_CONTRACT_MISMATCH"
    elif not sha_verified:
        reason = "SHA256_MISMATCH"
    elif not gzip_json_valid:
        reason = "INVALID_GZIP_JSONL"
    elif not record_matches_manifest:
        reason = "RECORD_COUNT_MISMATCH"
    elif not record_matches_remote:
        reason = "REMOTE_TOTAL_MISMATCH"
    else:
        reason = "NONE"
    return _ChunkScan(
        local_date=window.day_key,
        data_present=data_present,
        manifest_present=manifest_present,
        manifest_contract_valid=manifest_contract_valid,
        sha256_verified=sha_verified,
        gzip_json_valid=gzip_json_valid,
        record_count=inventory.record_count,
        manifest_record_count=(
            manifest_record_count if _is_nonnegative_int(manifest_record_count) else None
        ),
        remote_total_reported=(remote_total if _is_nonnegative_int(remote_total) else None),
        record_count_matches_manifest=record_matches_manifest,
        record_count_matches_remote=record_matches_remote,
        status="PASS" if valid else "FAIL",
        reason_code=reason,
        inventory=inventory,
        quality=quality,
    )


def _scan_carry_in(
    raw_root: Path,
    expected: _PrivateSession | None,
) -> tuple[dict[str, Any], _PrivateInventory, _QualityAccumulator, bool]:
    data_path, manifest_path = _carry_in_paths(raw_root)
    data_present = data_path.is_file()
    manifest_present = manifest_path.is_file()
    manifest: dict[str, Any] | None = None
    if manifest_present:
        try:
            candidate = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            candidate = None
        if isinstance(candidate, dict):
            manifest = candidate

    expected_context: dict[str, Any] = {}
    if expected is not None:
        query = _carry_in_query(expected)
        expected_context = {
            "schema_version": "acn-jpl-full-month-carry-in/v1",
            "endpoint": query.endpoint,
            "site": "jpl",
            "_id": expected.object_id,
            "sessionID": expected.session_id,
            "query_condition": query.condition,
        }
    manifest_count = manifest.get("record_count") if manifest is not None else None
    remote_total = manifest.get("remote_total_reported") if manifest is not None else None
    contract_valid = bool(
        expected is not None
        and manifest is not None
        and all(manifest.get(key) == value for key, value in expected_context.items())
        and manifest.get("complete_for_query") is True
        and manifest.get("token_stored") is False
        and _is_nonnegative_int(manifest_count)
        and manifest_count == 1
        and _is_nonnegative_int(remote_total)
        and remote_total == 1
    )
    sha_verified = bool(
        data_present
        and manifest is not None
        and isinstance(manifest.get("sha256"), str)
        and _sha256_file(data_path) == manifest.get("sha256")
    )
    inventory = _PrivateInventory()
    quality = _QualityAccumulator()
    gzip_json_valid = False
    if data_present:
        try:
            with gzip.open(data_path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise TypeError("record root is not an object")
                    inventory.add(record)
                    quality.add(record)
            gzip_json_valid = True
        except (OSError, EOFError, UnicodeError, json.JSONDecodeError, TypeError):
            gzip_json_valid = False

    expected_pair = (expected.object_id, expected.session_id) if expected is not None else None
    observed_pairs = set(inventory.pairs)
    pair_match = bool(
        expected_pair is not None
        and inventory.record_count == 1
        and observed_pairs == {expected_pair}
        and inventory.pairs[expected_pair] == 1
    )
    valid = all(
        (
            data_present,
            manifest_present,
            contract_valid,
            sha_verified,
            gzip_json_valid,
            inventory.record_count == 1,
            _is_nonnegative_int(manifest_count),
            manifest_count == 1,
            _is_nonnegative_int(remote_total),
            remote_total == 1,
            pair_match,
        )
    )
    public = {
        "status": "PASS" if valid else "FAIL",
        "expected_records": 1,
        "observed_records": inventory.record_count,
        "manifest_records": manifest_count if _is_nonnegative_int(manifest_count) else None,
        "remote_records": remote_total if _is_nonnegative_int(remote_total) else None,
        "data_present": data_present,
        "manifest_present": manifest_present,
        "manifest_contract_valid": contract_valid,
        "sha256_verified": sha_verified,
        "gzip_json_valid": gzip_json_valid,
        "exact_private_pair_match": pair_match,
    }
    return public, inventory, quality, valid


def _duplicate_extras(counter: Counter[Any]) -> int:
    return sum(count - 1 for count in counter.values() if count > 1)


def _local_integrity(
    inventory: _PrivateInventory,
    expected_pairs: set[tuple[str, str]],
    expected_count: int,
) -> dict[str, Any]:
    observed_pairs = set(inventory.pairs)
    matched = len(observed_pairs & expected_pairs)
    missing = len(expected_pairs - observed_pairs)
    orphan = len(observed_pairs - expected_pairs)
    return {
        "expected_records": expected_count,
        "observed_records": inventory.record_count,
        "expected_unique_object_keys": expected_count,
        "unique_object_keys": len(inventory.object_keys),
        "missing_object_key_records": inventory.missing_object_keys,
        "duplicate_object_key_records": _duplicate_extras(inventory.object_keys),
        "expected_unique_session_keys": expected_count,
        "unique_session_keys": len(inventory.session_keys),
        "missing_session_key_records": inventory.missing_session_keys,
        "duplicate_session_key_records": _duplicate_extras(inventory.session_keys),
        "expected_metadata_pairs": expected_count,
        "matched_metadata_pairs": matched,
        "missing_metadata_pairs": missing,
        "orphan_timeseries_pairs": orphan,
        "duplicate_pair_records": _duplicate_extras(inventory.pairs),
        "metadata_timeseries_match_rate": _safe_rate(matched, expected_count),
    }


def _power_semantics() -> dict[str, Any]:
    return {
        "charging_current": {
            "unit": "ampere",
            "interpretation": "measured current; not direct active power in kW",
        },
        "pilot_signal": {
            "interpretation": "control signal or limit; not measured active power",
        },
        "approved_15_min_representation": "CURRENT_PROXY_ONLY",
        "kw_conversion_requires": [
            "voltage",
            "phase",
            "topology",
            "power factor",
            "network context",
        ],
        "fixed_voltage_assumption": False,
    }


def _cleaning_manifest() -> dict[str, Any]:
    return {
        "schema_version": "acn-jpl-full-month-cleaning-rules/v1",
        "artifact_scope": "rules only; no cleaned or aggregated data",
        "rules": [
            {
                "code": "UTC_PARSE",
                "rule": "Parse timestamps as timezone-aware UTC instants and count parse failures.",
            },
            {
                "code": "PRESERVE_RAW_ORDER",
                "rule": "Preserve every raw value, raw timestamp string, and original ordering.",
            },
            {
                "code": "EXACT_DUPLICATE",
                "rule": "An exact duplicate timestamp-value pair may be deduplicated only with an explicit count.",
            },
            {
                "code": "CONFLICTING_DUPLICATE",
                "rule": "Conflicting values at one timestamp are flagged, never averaged, and excluded pending a documented decision.",
            },
            {
                "code": "ACTIVE_INTERVAL",
                "rule": "Analysis eligibility is connection time less than or equal to t and t strictly less than disconnect time.",
            },
            {
                "code": "BOUNDARY_POSITIVE",
                "rule": "Positive current outside the active interval remains in raw storage and is reported by QA.",
            },
            {
                "code": "INTERPOLATION_BOUND",
                "rule": "No unbounded interpolation is allowed.",
            },
            {
                "code": "DONE_TIME",
                "rule": "Preserve doneChargingTime as a retrospective field.",
            },
            {
                "code": "ISSUE_TIME_INPUTS",
                "rule": "userInputs are truncated using modifiedAt at or before the forecast issue time.",
            },
        ],
        "creates_cleaned_data": False,
        "creates_15_min_data": False,
    }


def _extract_acquisition_summary(result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {"status": "NOT_PROVIDED"}
    status = result.get("status")
    daily = result.get("daily") if isinstance(result.get("daily"), Mapping) else {}
    linkage = result.get("linkage") if isinstance(result.get("linkage"), Mapping) else {}
    carry = result.get("carry_in") if isinstance(result.get("carry_in"), Mapping) else {}

    def nonnegative(value: Any) -> int | None:
        return value if _is_nonnegative_int(value) else None

    return {
        "status": status if status in {"COMPLETE", "INCOMPLETE"} else "UNKNOWN",
        "daily_requested": nonnegative(daily.get("requested_days")),
        "daily_completed": nonnegative(daily.get("completed_days")),
        "daily_failed": nonnegative(daily.get("failed_days")),
        "linkage_status": (
            linkage.get("status")
            if linkage.get("status") in {"PASS", "FAIL", "NOT_RUN"}
            else "UNKNOWN"
        ),
        "carry_status": (
            carry.get("status")
            if carry.get("status") in {"DOWNLOADED", "SKIPPED", "FAILED", "NOT_RUN"}
            else "UNKNOWN"
        ),
    }


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _csv_bytes(rows: list[dict[str, Any]], fieldnames: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _summary_markdown(summary: Mapping[str, Any]) -> bytes:
    integrity = summary["integrity"]
    gate = summary["gate"]
    lines = [
        "# JPL May 2019 full-month time-series QA",
        "",
        f"- QA gate: {gate['status']}",
        f"- Valid local daily chunks: {integrity['valid_daily_chunks']}/31",
        f"- Local-month rows: {integrity['local_records']}",
        f"- Carry-in rows: {integrity['carry_records']}",
        f"- Combined quality denominator: {integrity['quality_denominator']}",
        f"- Ready for cleaning: {'YES' if gate['ready_for_cleaning'] else 'NO'}",
        f"- Ready for 15-minute use: {gate['ready_for_15_min']}",
        "- Gate 1 readiness: NO",
        "",
        "## Power semantics",
        "",
        "chargingCurrent is measured current in amperes and is not direct kW.",
        "pilotSignal is a control signal, not measured active power.",
        "The only approved 15-minute representation is a current proxy.",
        "Converting to kW requires voltage, phase, topology, power factor, and network context.",
        "No fixed voltage assumption is made.",
        "",
        "## Scope boundary",
        "",
        "This artifact authorizes cleaning only when the QA gate passes. It creates no cleaned data, no 15-minute data, and no Gate 1 evidence.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _validate_public_value(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).lower()
            if normalized in _FORBIDDEN_PUBLIC_KEYS:
                raise ValueError("public artifact contains a forbidden private field")
            _validate_public_value(nested)
    elif isinstance(value, list):
        for nested in value:
            _validate_public_value(nested)


def _validate_public_contents(
    payloads: Iterable[Mapping[str, Any]],
    contents: Mapping[str, bytes],
    sensitive_values: Iterable[str],
) -> None:
    for payload in payloads:
        _validate_public_value(payload)
    text = "\n".join(data.decode("utf-8") for data in contents.values())
    lowered = text.lower()
    for forbidden in ("sessionid", '"_id"', "userid", "query_condition"):
        if forbidden in lowered:
            raise ValueError("public artifact contains private schema material")
    if _ABSOLUTE_PATH_PATTERN.search(text):
        raise ValueError("public artifact contains an absolute local path")
    for sensitive in sensitive_values:
        if sensitive and sensitive in text:
            raise ValueError("public artifact contains a sensitive value")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def verify_public_artifact_hashes(output_root: str | Path) -> bool:
    """Verify that ``SHA256SUMS`` covers exactly the six public payload artifacts."""

    root = Path(output_root)
    checksum_path = root / "SHA256SUMS"
    if not checksum_path.is_file():
        return False
    expected: dict[str, str] = {}
    try:
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            digest, separator, name = line.partition("  ")
            if separator != "  " or not re.fullmatch(r"[0-9a-f]{64}", digest):
                return False
            if Path(name).name != name or name in expected:
                return False
            expected[name] = digest
    except (OSError, UnicodeError):
        return False
    if set(expected) != set(_HASHED_ARTIFACT_NAMES):
        return False
    return all(
        (root / name).is_file() and _sha256_file(root / name) == digest
        for name, digest in expected.items()
    )


def _publish_artifact_release(output: Path, contents: Mapping[str, bytes]) -> None:
    """Stage and verify a complete release before swapping the dedicated directory."""

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.partial-", dir=str(output.parent)))
    backup = stage.with_name(
        stage.name.replace(f".{output.name}.partial-", f".{output.name}.previous-", 1)
    )
    published = False
    previous_moved = False
    try:
        for name in PUBLIC_ARTIFACT_NAMES:
            _atomic_write_bytes(stage / name, contents[name])
        if not verify_public_artifact_hashes(stage):
            raise OSError("staged public artifact checksum verification failed")
        if output.exists():
            if not output.is_dir():
                raise OSError("public artifact destination is not a directory")
            os.replace(output, backup)
            previous_moved = True
        os.replace(stage, output)
        published = True
        if not verify_public_artifact_hashes(output):
            raise OSError("published public artifact checksum verification failed")
    except Exception:
        if published and output.is_dir():
            shutil.rmtree(output)
            published = False
        if previous_moved and backup.is_dir():
            os.replace(backup, output)
            previous_moved = False
        raise
    finally:
        if stage.is_dir():
            shutil.rmtree(stage)
        if published and previous_moved and backup.is_dir():
            shutil.rmtree(backup)


def generate_full_month_timeseries_qa(
    *,
    metadata_root: str | Path,
    raw_root: str | Path,
    output_root: str | Path = Path("outputs/acn_gate0/jpl_2019-05-full-ts"),
    acquisition_result: Mapping[str, Any] | None = None,
    expected_local_sessions: int = EXPECTED_ANALYSIS_SESSION_COUNT,
    expected_utc_sessions: int = EXPECTED_UTC_MONTH_SESSION_COUNT,
    expected_carry_sessions: int = EXPECTED_CARRY_IN_SESSION_COUNT,
    expected_total_sessions: int = EXPECTED_TOTAL_SESSION_COUNT,
    sensitive_values: Iterable[str] = (),
) -> FullMonthQAResult:
    """Stream raw chunks, fail closed, and atomically emit seven public artifacts."""

    for name, count in (
        ("expected_local_sessions", expected_local_sessions),
        ("expected_utc_sessions", expected_utc_sessions),
        ("expected_carry_sessions", expected_carry_sessions),
        ("expected_total_sessions", expected_total_sessions),
    ):
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError(f"{name} must be a nonnegative integer")

    metadata_status = "PASS"
    metadata_error_code: str | None = None
    scope: _PrivateMetadataScope | None
    try:
        scope = _load_metadata_scope(metadata_root)
    except FullMonthMetadataError:
        scope = None
        metadata_status = "FAIL"
        metadata_error_code = "METADATA_SCOPE_INVALID"

    expected_pairs: set[tuple[str, str]] = set()
    carry_expected: _PrivateSession | None = None
    metadata_local = 0
    metadata_utc = 0
    metadata_carry = 0
    if scope is not None:
        expected_pairs = {
            (session.object_id, session.session_id) for session in scope.analysis_sessions
        }
        carry_expected = scope.carry_in
        metadata_local = scope.provenance.analysis_session_count
        metadata_utc = scope.provenance.utc_month_session_count
        metadata_carry = scope.provenance.carry_in_session_count
        if (
            metadata_local != expected_local_sessions
            or metadata_utc != expected_utc_sessions
            or metadata_carry != expected_carry_sessions
            or len(expected_pairs) != expected_local_sessions
        ):
            metadata_status = "FAIL"
            metadata_error_code = "METADATA_SCOPE_COUNT_MISMATCH"

    windows = list(jpl_analysis_windows())
    scans = [_scan_daily_chunk(Path(raw_root), window) for window in windows]
    local_inventory = _PrivateInventory()
    quality = _QualityAccumulator()
    for scan in scans:
        if scan.gzip_json_valid:
            local_inventory.merge(scan.inventory)
        if scan.status == "PASS":
            quality.merge(scan.quality)

    carry_public, carry_inventory, carry_quality, carry_valid = _scan_carry_in(
        Path(raw_root), carry_expected
    )
    if carry_valid:
        quality.merge(carry_quality)

    local = _local_integrity(local_inventory, expected_pairs, expected_local_sessions)
    combined_inventory = _PrivateInventory()
    combined_inventory.merge(local_inventory)
    if carry_inventory.record_count:
        combined_inventory.merge(carry_inventory)
    combined = {
        "expected_records": expected_total_sessions,
        "observed_records": combined_inventory.record_count,
        "expected_unique_object_keys": expected_total_sessions,
        "unique_object_keys": len(combined_inventory.object_keys),
        "expected_unique_session_keys": expected_total_sessions,
        "unique_session_keys": len(combined_inventory.session_keys),
        "duplicate_object_key_records": _duplicate_extras(combined_inventory.object_keys),
        "duplicate_session_key_records": _duplicate_extras(combined_inventory.session_keys),
        "missing_private_key_records": (
            combined_inventory.missing_object_keys + combined_inventory.missing_session_keys
        ),
    }
    valid_daily = sum(scan.status == "PASS" for scan in scans)
    daily_integrity = {
        "expected": 31,
        "data_files_present": sum(scan.data_present for scan in scans),
        "manifests_present": sum(scan.manifest_present for scan in scans),
        "manifest_contracts_valid": sum(scan.manifest_contract_valid for scan in scans),
        "sha256_verified": sum(scan.sha256_verified for scan in scans),
        "gzip_json_valid": sum(scan.gzip_json_valid for scan in scans),
        "record_manifest_matches": sum(scan.record_count_matches_manifest for scan in scans),
        "record_remote_matches": sum(scan.record_count_matches_remote for scan in scans),
        "valid": valid_daily,
        "failed_or_incomplete": 31 - valid_daily,
    }
    quality_public = quality.public_dict(expected_total_sessions)
    current = quality_public["series"][_CURRENT_FIELD]
    pilot = quality_public["series"][_PILOT_FIELD]

    acquisition = _extract_acquisition_summary(acquisition_result)
    acquisition_check = acquisition["status"] in {"COMPLETE", "NOT_PROVIDED"}
    checks = {
        "metadata_scope_exact": metadata_status == "PASS",
        "daily_chunks_complete": valid_daily == 31,
        "local_record_count_exact": local["observed_records"] == expected_local_sessions,
        "local_object_keys_unique": (
            local["unique_object_keys"] == expected_local_sessions
            and local["missing_object_key_records"] == 0
            and local["duplicate_object_key_records"] == 0
        ),
        "local_session_keys_unique": (
            local["unique_session_keys"] == expected_local_sessions
            and local["missing_session_key_records"] == 0
            and local["duplicate_session_key_records"] == 0
        ),
        "metadata_timeseries_exact": (
            local["metadata_timeseries_match_rate"] == 1.0
            and local["missing_metadata_pairs"] == 0
            and local["orphan_timeseries_pairs"] == 0
            and local["duplicate_pair_records"] == 0
        ),
        "carry_in_exact": carry_valid and expected_carry_sessions == 1,
        "combined_count_exact": (
            combined["observed_records"] == expected_total_sessions
            and combined["unique_object_keys"] == expected_total_sessions
            and combined["unique_session_keys"] == expected_total_sessions
            and combined["missing_private_key_records"] == 0
            and combined["duplicate_object_key_records"] == 0
            and combined["duplicate_session_key_records"] == 0
        ),
        "current_invalid_rate_at_most_limit": (
            current["invalid_container_rate"] is not None
            and current["invalid_container_rate"] <= INVALID_CHARGING_CURRENT_RATE_LIMIT
        ),
        "pilot_invalid_rate_at_most_limit": (
            pilot["invalid_container_rate"] is not None
            and pilot["invalid_container_rate"] <= INVALID_PILOT_SIGNAL_RATE_LIMIT
        ),
        "zero_timestamp_parse_anomalies": (
            current["timestamp_parse_errors"] + pilot["timestamp_parse_errors"] == 0
        ),
        "zero_timestamp_nonmonotonic_anomalies": (
            current["nonmonotonic_pairs"] + pilot["nonmonotonic_pairs"] == 0
        ),
        "acquisition_complete_if_provided": acquisition_check,
    }
    gate_status = "PASS" if all(checks.values()) else "FAIL"
    warnings: list[str] = []
    if current["duplicate_extra_timestamps"] or pilot["duplicate_extra_timestamps"]:
        warnings.append("DUPLICATE_TIMESTAMPS")
    if current["conflicting_duplicate_timestamps"] or pilot["conflicting_duplicate_timestamps"]:
        warnings.append("CONFLICTING_DUPLICATE_TIMESTAMPS")
    if current["boundary_positive_points"]:
        warnings.append("BOUNDARY_POSITIVE_CURRENT")
    if current["non_utc_timestamp_encodings"] or pilot["non_utc_timestamp_encodings"]:
        warnings.append("NON_UTC_TIMESTAMP_ENCODING")
    if current["nonnumeric_values"] or pilot["nonnumeric_values"]:
        warnings.append("NONNUMERIC_SERIES_VALUES")
    if current["negative_values"]:
        warnings.append("NEGATIVE_CURRENT_VALUES")

    integrity_status = (
        "PASS"
        if all(
            checks[name]
            for name in (
                "metadata_scope_exact",
                "daily_chunks_complete",
                "local_record_count_exact",
                "local_object_keys_unique",
                "local_session_keys_unique",
                "metadata_timeseries_exact",
                "carry_in_exact",
                "combined_count_exact",
            )
        )
        else "FAIL"
    )
    qa: dict[str, Any] = {
        "schema_version": "acn-jpl-full-month-timeseries-qa/v1",
        "integrity": {
            "status": integrity_status,
            "metadata_scope": {
                "status": metadata_status,
                "failure_code": metadata_error_code,
                "analysis_records": metadata_local,
                "utc_month_records": metadata_utc,
                "carry_records": metadata_carry,
            },
            "daily_chunks": daily_integrity,
            "local_month": local,
            "carry_in": carry_public,
            "combined": combined,
            "month_boundary": {
                "timezone": JPL_TIMEZONE,
                "local_month_sessions": metadata_local,
                "utc_month_sessions": metadata_utc,
                "counts_are_not_interchangeable": True,
            },
        },
        "quality": quality_public,
        "gate": {
            "status": gate_status,
            "thresholds": {
                "charging_current_invalid_rate_max": INVALID_CHARGING_CURRENT_RATE_LIMIT,
                "pilot_signal_invalid_rate_max": INVALID_PILOT_SIGNAL_RATE_LIMIT,
                "metadata_timeseries_match_rate_required": 1.0,
                "orphan_timeseries_pairs_required": 0,
                "timestamp_parse_anomalies_required": 0,
                "timestamp_nonmonotonic_anomalies_required": 0,
            },
            "checks": checks,
            "warnings": warnings,
            "ready_for_cleaning": gate_status == "PASS",
            "ready_for_15_min": ("YES_CURRENT_PROXY_ONLY" if gate_status == "PASS" else "NO"),
            "gate1_ready": "NO",
        },
        "power_semantics": _power_semantics(),
        "privacy": {
            "aggregate_only": True,
            "private_keys_emitted": False,
            "credentials_emitted": False,
            "absolute_local_paths_emitted": False,
            "raw_trajectories_emitted": False,
        },
    }

    summary = {
        "schema_version": "acn-jpl-full-month-acquisition-summary/v1",
        "acquisition": acquisition,
        "integrity": {
            "status": integrity_status,
            "valid_daily_chunks": valid_daily,
            "local_records": local["observed_records"],
            "carry_records": carry_public["observed_records"],
            "combined_records": combined["observed_records"],
            "quality_denominator": expected_total_sessions,
        },
        "gate": {
            "status": gate_status,
            "ready_for_cleaning": gate_status == "PASS",
            "ready_for_15_min": ("YES_CURRENT_PROXY_ONLY" if gate_status == "PASS" else "NO"),
            "gate1_ready": "NO",
        },
        "power_semantics": _power_semantics(),
        "privacy": qa["privacy"],
    }
    cleaning = _cleaning_manifest()
    daily_rows = [scan.daily_row() for scan in scans]
    failed_rows = [
        {
            "local_date": scan.local_date,
            "status": scan.status,
            "reason_code": scan.reason_code,
            "observed_records": scan.record_count,
            "reported_records": scan.remote_total_reported,
        }
        for scan in scans
        if scan.status != "PASS"
    ]
    if not carry_valid:
        failed_rows.append(
            {
                "local_date": "CARRY_IN",
                "status": "FAIL",
                "reason_code": "CARRY_IN_INCOMPLETE",
                "observed_records": carry_public["observed_records"],
                "reported_records": carry_public["remote_records"],
            }
        )

    contents: dict[str, bytes] = {
        "qa_full_month_timeseries.json": _json_bytes(qa),
        "acquisition_summary.json": _json_bytes(summary),
        "acquisition_summary.md": _summary_markdown(summary),
        "daily_chunk_summary.csv": _csv_bytes(
            daily_rows,
            [
                "local_date",
                "status",
                "data_present",
                "manifest_present",
                "manifest_contract_valid",
                "sha256_verified",
                "gzip_json_valid",
                "record_count",
                "manifest_record_count",
                "remote_total_reported",
                "record_count_matches_manifest",
                "record_count_matches_remote",
                "reason_code",
            ],
        ),
        "failed_or_incomplete_chunks.csv": _csv_bytes(
            failed_rows,
            [
                "local_date",
                "status",
                "reason_code",
                "observed_records",
                "reported_records",
            ],
        ),
        "cleaning_rule_manifest.json": _json_bytes(cleaning),
    }
    _validate_public_contents((qa, summary, cleaning), contents, sensitive_values)

    checksum_content = "".join(
        f"{hashlib.sha256(contents[name]).hexdigest()}  {name}\n" for name in _HASHED_ARTIFACT_NAMES
    ).encode("utf-8")
    _validate_public_contents((), {"SHA256SUMS": checksum_content}, sensitive_values)
    contents["SHA256SUMS"] = checksum_content
    _publish_artifact_release(Path(output_root), contents)
    return FullMonthQAResult(gate_status=gate_status, qa=qa)
