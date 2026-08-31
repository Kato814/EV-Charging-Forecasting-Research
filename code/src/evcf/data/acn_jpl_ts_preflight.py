"""Deterministic, resumable 100-session JPL time-series preflight.

Raw identifiers are needed to issue exact ``/ts`` queries, but are confined to the
ignored raw/state tree.  The returned QA document contains aggregate counts only.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import random
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .acn_api import ACNClient, ACNQuery, ACNSchemaError
from .acn_audit import parse_acn_datetime
from .acn_jpl_gate0 import JPL_ANALYSIS_END, JPL_ANALYSIS_START

PREFLIGHT_RANDOM_SEED = 201905
PREFLIGHT_SAMPLE_SIZE = 100
PREFLIGHT_INVALID_CHARGING_CURRENT_RATE_LIMIT = 0.10
PREFLIGHT_INVALID_PILOT_SIGNAL_RATE_LIMIT = 0.10
PREFLIGHT_UNMATCHED_METADATA_RATE_LIMIT = 0.01
_CURRENT_VALUE_KEY = "current"
_PILOT_VALUE_KEY = "pilot"


@dataclass(frozen=True)
class PreflightSession:
    """Private query material that must remain under the ignored raw tree."""

    session_id: str
    object_id: str


@dataclass(frozen=True)
class PreflightRunResult:
    """Aggregate result of a serial preflight run."""

    qa: dict[str, Any]
    downloaded_sessions: int
    skipped_sessions: int
    failed_sessions: int


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 8) if denominator else None


def _private_pair(record: Mapping[str, Any] | PreflightSession) -> tuple[str, str] | None:
    if isinstance(record, PreflightSession):
        return record.object_id, record.session_id
    object_id = record.get("_id")
    session_id = record.get("sessionID")
    if not isinstance(object_id, str) or not object_id:
        return None
    if not isinstance(session_id, str) or not session_id:
        return None
    return object_id, session_id


def select_preflight_sessions(
    records: Iterable[Mapping[str, Any]],
    *,
    sample_size: int = PREFLIGHT_SAMPLE_SIZE,
    seed: int = PREFLIGHT_RANDOM_SEED,
) -> list[PreflightSession]:
    """Select an input-order-independent fixed-seed sample from the local May cohort."""

    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    analysis_start = JPL_ANALYSIS_START.astimezone(timezone.utc)
    analysis_end = JPL_ANALYSIS_END.astimezone(timezone.utc)
    candidates: dict[str, PreflightSession] = {}
    for record in records:
        try:
            connection = parse_acn_datetime(record.get("connectionTime"))
        except (TypeError, ValueError):
            continue
        if connection is None or not (analysis_start <= connection < analysis_end):
            continue
        pair = _private_pair(record)
        if pair is None:
            continue
        object_id, session_id = pair
        candidate = PreflightSession(session_id=session_id, object_id=object_id)
        previous = candidates.get(session_id)
        if previous is not None and previous.object_id != object_id:
            raise ValueError("conflicting _id values for one sessionID")
        candidates[session_id] = candidate

    ordered = sorted(candidates.values(), key=lambda item: (item.session_id, item.object_id))
    if len(ordered) < sample_size:
        raise ValueError(
            f"preflight requires {sample_size} unique analysis sessions; found {len(ordered)}"
        )
    return random.Random(seed).sample(ordered, sample_size)


def build_preflight_query(session: PreflightSession) -> ACNQuery:
    """Build one exact, bounded, opt-in time-series query."""

    return ACNQuery(
        site="jpl",
        start=JPL_ANALYSIS_START,
        end=JPL_ANALYSIS_END,
        timeseries=True,
        session_id=session.session_id,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _preflight_paths(root: Path, sample_index: int) -> tuple[Path, Path]:
    stem = f"sample_{sample_index:04d}"
    return (
        root / "timeseries" / "preflight" / f"{stem}.jsonl.gz",
        root / "manifests" / "preflight" / f"{stem}.manifest.json",
    )


def _read_gzip_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ACNSchemaError("preflight JSONL record must be an object")
            records.append(item)
    return records


def _validated_session_records(
    data_path: Path,
    manifest_path: Path,
    session: PreflightSession,
    sample_index: int,
    seed: int,
) -> list[dict[str, Any]] | None:
    if not data_path.is_file() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records = _read_gzip_records(data_path)
    except (OSError, EOFError, UnicodeError, json.JSONDecodeError, ACNSchemaError):
        return None
    query = build_preflight_query(session)
    expected = {
        "schema_version": "acn-jpl-ts-preflight-session/v1",
        "endpoint": query.endpoint,
        "site": "jpl",
        "sample_index": sample_index,
        "seed": seed,
        "sessionID": session.session_id,
        "_id": session.object_id,
        "query_condition": query.condition,
        "record_count": 1,
        "remote_total_reported": 1,
        "complete_for_query": True,
        "token_stored": False,
    }
    if not isinstance(manifest, dict) or any(
        manifest.get(key) != value for key, value in expected.items()
    ):
        return None
    if manifest.get("sha256") != _sha256_file(data_path) or len(records) != 1:
        return None
    return records if _private_pair(records[0]) == (session.object_id, session.session_id) else None


def _remote_total(page: Mapping[str, Any]) -> int | None:
    meta = page.get("_meta")
    total = meta.get("total") if isinstance(meta, Mapping) else None
    if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
        return total
    return None


def _download_session(
    client: ACNClient,
    root: Path,
    session: PreflightSession,
    sample_index: int,
    seed: int,
    downloaded_at_utc: datetime,
) -> tuple[bool, list[dict[str, Any]]]:
    query = build_preflight_query(session)
    data_path, manifest_path = _preflight_paths(root, sample_index)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = data_path.with_suffix(data_path.suffix + ".partial")
    records: list[dict[str, Any]] = []
    totals: set[int] = set()
    try:
        with temporary.open("wb") as raw_handle:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as zipped:
                for page in client.iter_pages(query):
                    total = _remote_total(page)
                    if total is not None:
                        totals.add(total)
                    items = page.get("_items")
                    if not isinstance(items, list):
                        raise ACNSchemaError("ACN-Data page is missing list field '_items'")
                    for item in items:
                        if not isinstance(item, dict):
                            raise ACNSchemaError("ACN-Data session record must be an object")
                        records.append(item)
                        zipped.write(
                            (
                                json.dumps(
                                    item,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                    separators=(",", ":"),
                                )
                                + "\n"
                            ).encode("utf-8")
                        )
            raw_handle.flush()
            os.fsync(raw_handle.fileno())
        os.replace(temporary, data_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    reported_total = next(iter(totals)) if len(totals) == 1 else None
    pair_matches = len(records) == 1 and _private_pair(records[0]) == (
        session.object_id,
        session.session_id,
    )
    complete = reported_total == 1 and pair_matches
    manifest = {
        "schema_version": "acn-jpl-ts-preflight-session/v1",
        "dataset_id": "D0001-jpl-2019-05-ts-preflight",
        "source": "ACN-Data official REST API",
        "endpoint": query.endpoint,
        "site": "jpl",
        "sample_index": sample_index,
        "seed": seed,
        "sessionID": session.session_id,
        "_id": session.object_id,
        "query_condition": query.condition,
        "record_count": len(records),
        "remote_total_reported": reported_total,
        "complete_for_query": complete,
        "downloaded_at_utc": downloaded_at_utc.astimezone(timezone.utc).isoformat(),
        "sha256": _sha256_file(data_path),
        "token_stored": False,
        "output_file": data_path.name,
    }
    _atomic_write_json(manifest_path, manifest)
    return complete, records


def _parse_bound(record: Mapping[str, Any], field: str) -> datetime | None:
    try:
        return parse_acn_datetime(record.get(field))
    except (TypeError, ValueError):
        return None


def _complete_minute_count(connection: datetime, disconnect: datetime) -> int:
    start = connection.replace(second=0, microsecond=0)
    if start < connection:
        start += timedelta(minutes=1)
    end = disconnect.replace(second=0, microsecond=0)
    return max(0, int((end - start).total_seconds() // 60))


def _inspect_series_records(
    records: Iterable[Mapping[str, Any]],
    *,
    field: str,
    value_key: str,
    denominator: int,
) -> dict[str, Any]:
    invalid_containers = 0
    length_mismatch = 0
    duplicate_extra = 0
    nonmonotonic_pairs = 0
    timestamp_parse_errors = 0
    invalid_values = 0
    negative_values = 0
    raw_samples = 0
    usable_samples = 0
    boundary_positive_points = 0
    boundary_positive_sessions = 0
    boundary_unverifiable_sessions = 0
    expected_minutes = 0
    sparse_minutes = 0

    for record in records:
        connection = _parse_bound(record, "connectionTime")
        disconnect = _parse_bound(record, "disconnectTime")
        valid_bounds = (
            connection is not None
            and disconnect is not None
            and disconnect > connection
        )
        series = record.get(field)
        timestamps = series.get("timestamps") if isinstance(series, Mapping) else None
        values = series.get(value_key) if isinstance(series, Mapping) else None
        timestamps_are_list = isinstance(timestamps, list)
        values_are_list = isinstance(values, list)
        if values_are_list:
            raw_samples += len(values)

        parsed_timestamps: list[datetime | None] = []
        seen_all: set[datetime] = set()
        previous: datetime | None = None
        if timestamps_are_list:
            for raw_timestamp in timestamps:
                try:
                    parsed = parse_acn_datetime(raw_timestamp)
                except (TypeError, ValueError):
                    parsed = None
                parsed_timestamps.append(parsed)
                if parsed is None:
                    timestamp_parse_errors += 1
                    continue
                if parsed in seen_all:
                    duplicate_extra += 1
                seen_all.add(parsed)
                if previous is not None and parsed < previous:
                    nonmonotonic_pairs += 1
                previous = parsed

        numeric_values: list[float | None] = []
        if values_are_list:
            for raw_value in values:
                numeric = (
                    isinstance(raw_value, (int, float))
                    and not isinstance(raw_value, bool)
                    and math.isfinite(float(raw_value))
                )
                if not numeric:
                    invalid_values += 1
                    numeric_values.append(None)
                    continue
                number = float(raw_value)
                if field == "chargingCurrent" and number < 0:
                    negative_values += 1
                    numeric_values.append(None)
                    continue
                numeric_values.append(number)

        aligned = (
            timestamps_are_list
            and values_are_list
            and len(timestamps) == len(values)
        )
        if not aligned:
            invalid_containers += 1
            if timestamps_are_list and values_are_list:
                length_mismatch += 1

        seen_usable: set[datetime] = set()
        usable_by_minute: Counter[datetime] = Counter()
        record_boundary_positive = False
        if field == "chargingCurrent" and aligned and not valid_bounds:
            boundary_unverifiable_sessions += 1
        if aligned:
            paired = zip(parsed_timestamps, numeric_values)
        else:
            paired = iter(())
        for parsed, number in paired:
            if parsed is None or number is None:
                continue
            inside_session = (
                valid_bounds
                and connection is not None
                and disconnect is not None
                and connection <= parsed < disconnect
            )
            if (
                field == "chargingCurrent"
                and number > 0
                and valid_bounds
                and not inside_session
            ):
                boundary_positive_points += 1
                record_boundary_positive = True
            if not inside_session or parsed in seen_usable:
                continue
            seen_usable.add(parsed)
            usable_samples += 1
            usable_by_minute[parsed.replace(second=0, microsecond=0)] += 1

        if record_boundary_positive:
            boundary_positive_sessions += 1
        if valid_bounds and connection is not None and disconnect is not None:
            complete_minutes = _complete_minute_count(connection, disconnect)
            expected_minutes += complete_minutes
            cursor = connection.replace(second=0, microsecond=0)
            if cursor < connection:
                cursor += timedelta(minutes=1)
            for _ in range(complete_minutes):
                if usable_by_minute[cursor] < 10:
                    sparse_minutes += 1
                cursor += timedelta(minutes=1)

    return {
        "invalid_container_sessions": invalid_containers,
        "invalid_container_rate": _safe_rate(invalid_containers, denominator),
        "length_mismatch_sessions": length_mismatch,
        "duplicate_extra_timestamps": duplicate_extra,
        "nonmonotonic_pairs": nonmonotonic_pairs,
        "timestamp_parse_errors": timestamp_parse_errors,
        "invalid_numeric_values": invalid_values,
        "negative_values": negative_values,
        "raw_samples": raw_samples,
        "usable_samples": usable_samples,
        "retained_sample_rate": _safe_rate(usable_samples, raw_samples),
        "expected_complete_active_minutes": expected_minutes,
        "sparse_minutes_under_10_points": sparse_minutes,
        "sparse_minute_rate": _safe_rate(sparse_minutes, expected_minutes),
        "boundary_positive_current_points": (
            boundary_positive_points if field == "chargingCurrent" else None
        ),
        "boundary_positive_current_sessions": (
            boundary_positive_sessions if field == "chargingCurrent" else None
        ),
        "boundary_unverifiable_sessions": (
            boundary_unverifiable_sessions if field == "chargingCurrent" else None
        ),
    }


def audit_ts_preflight(
    metadata_sample: Iterable[Mapping[str, Any] | PreflightSession],
    timeseries_records: Iterable[Mapping[str, Any]],
    *,
    requested_sample_size: int = PREFLIGHT_SAMPLE_SIZE,
    seed: int = PREFLIGHT_RANDOM_SEED,
) -> dict[str, Any]:
    """Return aggregate-only QA for a selected metadata cohort and its ``/ts`` rows."""

    metadata = list(metadata_sample)
    raw_timeseries = list(timeseries_records)
    expected_pairs = {pair for item in metadata if (pair := _private_pair(item)) is not None}
    timeseries_pairs = {
        pair for item in raw_timeseries if (pair := _private_pair(item)) is not None
    }
    matched_pairs = expected_pairs & timeseries_pairs
    matched_records: list[Mapping[str, Any]] = []
    used_pairs: set[tuple[str, str]] = set()
    for record in raw_timeseries:
        pair = _private_pair(record)
        if pair in matched_pairs and pair not in used_pairs:
            matched_records.append(record)
            used_pairs.add(pair)

    denominator = requested_sample_size

    def coverage(field: str, *, require_nonempty_list: bool = False) -> dict[str, Any]:
        count = 0
        for record in matched_records:
            value = record.get(field)
            if require_nonempty_list:
                count += int(isinstance(value, list) and bool(value))
            else:
                count += int(value is not None)
        return {"count": count, "denominator": denominator, "rate": _safe_rate(count, denominator)}

    current = _inspect_series_records(
        matched_records,
        field="chargingCurrent",
        value_key=_CURRENT_VALUE_KEY,
        denominator=denominator,
    )
    pilot = _inspect_series_records(
        matched_records,
        field="pilotSignal",
        value_key=_PILOT_VALUE_KEY,
        denominator=denominator,
    )
    matched_count = len(matched_pairs)
    missing_count = len(expected_pairs - timeseries_pairs)
    orphan_count = len(timeseries_pairs - expected_pairs)
    unmatched_rate = _safe_rate(denominator - matched_count, denominator)
    severe_timestamp_anomalies = (
        current["timestamp_parse_errors"]
        + current["nonmonotonic_pairs"]
        + pilot["timestamp_parse_errors"]
        + pilot["nonmonotonic_pairs"]
    )
    gate_pass = (
        (current["invalid_container_rate"] or 0.0)
        <= PREFLIGHT_INVALID_CHARGING_CURRENT_RATE_LIMIT
        and (pilot["invalid_container_rate"] or 0.0)
        <= PREFLIGHT_INVALID_PILOT_SIGNAL_RATE_LIMIT
        and (unmatched_rate or 0.0) <= PREFLIGHT_UNMATCHED_METADATA_RATE_LIMIT
        and orphan_count == 0
        and severe_timestamp_anomalies == 0
    )
    return {
        "schema_version": "acn-jpl-ts-preflight-qa/v1",
        "sample": {
            "requested_sessions": requested_sample_size,
            "selected_unique_sessions": len(expected_pairs),
            "random_seed": seed,
        },
        "matching": {
            "metadata_sessions": len(expected_pairs),
            "timeseries_records": len(raw_timeseries),
            "matched_sessions": matched_count,
            "missing_sessions": missing_count,
            "orphan_sessions": orphan_count,
            "match_rate": _safe_rate(matched_count, denominator),
        },
        "field_coverage": {
            "chargingCurrent": coverage("chargingCurrent"),
            "pilotSignal": coverage("pilotSignal"),
            "userInputs": coverage("userInputs", require_nonempty_list=True),
        },
        "series": {"chargingCurrent": current, "pilotSignal": pilot},
        "gate": {
            "status": "PASS" if gate_pass else "FAIL",
            "invalid_charging_current_limit": (
                PREFLIGHT_INVALID_CHARGING_CURRENT_RATE_LIMIT
            ),
            "invalid_pilot_signal_limit": PREFLIGHT_INVALID_PILOT_SIGNAL_RATE_LIMIT,
            "unmatched_metadata_limit": PREFLIGHT_UNMATCHED_METADATA_RATE_LIMIT,
            "unmatched_metadata_rate": unmatched_rate,
            "severe_timestamp_anomalies": severe_timestamp_anomalies,
        },
        "privacy": {
            "aggregate_only": True,
            "identifiers_emitted": False,
            "token_emitted": False,
        },
    }


def run_ts_preflight(
    client: ACNClient,
    metadata_records: Iterable[Mapping[str, Any]],
    raw_root: str | Path,
    *,
    sample_size: int = PREFLIGHT_SAMPLE_SIZE,
    seed: int = PREFLIGHT_RANDOM_SEED,
    downloaded_at_utc: datetime | None = None,
) -> PreflightRunResult:
    """Fetch the deterministic sample serially, skipping already valid session files."""

    timestamp = downloaded_at_utc or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("downloaded_at_utc must be timezone-aware")
    root = Path(raw_root)
    selection = select_preflight_sessions(
        metadata_records,
        sample_size=sample_size,
        seed=seed,
    )
    _atomic_write_json(
        root / "state" / "preflight_selection.json",
        {
            "schema_version": "acn-jpl-ts-preflight-selection/v1",
            "random_seed": seed,
            "sample_size": sample_size,
            "token_stored": False,
            "sessions": [
                {"sample_index": index, "sessionID": item.session_id, "_id": item.object_id}
                for index, item in enumerate(selection, start=1)
            ],
        },
    )

    downloaded = 0
    skipped = 0
    failed_indices: list[int] = []
    completed_indices: list[int] = []
    records: list[dict[str, Any]] = []

    def checkpoint() -> None:
        completed = set(completed_indices)
        failed = set(failed_indices)
        _atomic_write_json(
            root / "state" / "preflight_progress.json",
            {
                "schema_version": "acn-jpl-ts-preflight-progress/v1",
                "random_seed": seed,
                "requested_sessions": sample_size,
                "pending_indices": [
                    index
                    for index in range(1, sample_size + 1)
                    if index not in completed and index not in failed
                ],
                "completed_indices": sorted(completed),
                "failed_indices": sorted(failed),
            },
        )

    checkpoint()
    for sample_index, session in enumerate(selection, start=1):
        data_path, manifest_path = _preflight_paths(root, sample_index)
        validated = _validated_session_records(
            data_path,
            manifest_path,
            session,
            sample_index,
            seed,
        )
        if validated is not None:
            records.extend(validated)
            skipped += 1
            completed_indices.append(sample_index)
            checkpoint()
            continue
        try:
            complete, downloaded_records = _download_session(
                client,
                root,
                session,
                sample_index,
                seed,
                timestamp,
            )
        except Exception:  # noqa: BLE001 - persist only a secret-free failed index
            failed_indices.append(sample_index)
        else:
            if complete:
                downloaded += 1
                completed_indices.append(sample_index)
                records.extend(downloaded_records)
            else:
                failed_indices.append(sample_index)
        checkpoint()

    qa = audit_ts_preflight(
        selection,
        records,
        requested_sample_size=sample_size,
        seed=seed,
    )
    qa["run"] = {
        "downloaded_sessions": downloaded,
        "skipped_sessions": skipped,
        "failed_sessions": len(failed_indices),
        "serial": True,
    }
    _atomic_write_json(root / "state" / "preflight_qa.json", qa)
    return PreflightRunResult(
        qa=qa,
        downloaded_sessions=downloaded,
        skipped_sessions=skipped,
        failed_sessions=len(failed_indices),
    )
