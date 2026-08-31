"""Resumable, privacy-aware acquisition primitives for the JPL Gate 0 window."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import requests

from .acn_api import ACNClient, ACNDataError, ACNQuery, ACNSchemaError
from .acn_audit import parse_acn_datetime

JPL_TIMEZONE = "America/Los_Angeles"
_JPL_ZONE = ZoneInfo(JPL_TIMEZONE)
JPL_ACQUISITION_START = datetime.combine(date(2019, 4, 24), time.min, _JPL_ZONE)
JPL_ACQUISITION_END = datetime.combine(date(2019, 6, 1), time.min, _JPL_ZONE)
JPL_ANALYSIS_START = datetime.combine(date(2019, 5, 1), time.min, _JPL_ZONE)
JPL_ANALYSIS_END = JPL_ACQUISITION_END


@dataclass(frozen=True)
class LocalDayWindow:
    """One local calendar day represented as a half-open interval."""

    local_start: datetime
    local_end: datetime

    @property
    def utc_start(self) -> datetime:
        return self.local_start.astimezone(timezone.utc)

    @property
    def utc_end(self) -> datetime:
        return self.local_end.astimezone(timezone.utc)

    @property
    def day_key(self) -> str:
        return self.local_start.date().isoformat()


@dataclass(frozen=True)
class SessionRole:
    """Membership in the analysis month or its carry-in buffer."""

    analysis_session: bool
    carry_in: bool


@dataclass(frozen=True)
class DuplicateIdentifierCounts:
    """Privacy-safe repeated-record counts, excluding the first occurrence."""

    duplicate_id_records: int
    duplicate_session_id_records: int


@dataclass(frozen=True, repr=False)
class _ChunkIdentityInventory:
    """Identifier-bearing scan result retained only in private in-memory state."""

    identifier_pairs: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    invalid_identifier_records: int = 0
    duplicate_records: int = 0

    @property
    def record_count(self) -> int:
        return len(self.identifier_pairs) + self.invalid_identifier_records

    def __repr__(self) -> str:
        return (
            "_ChunkIdentityInventory(identifiers=<redacted>, "
            f"record_count={self.record_count}, "
            f"invalid_identifier_records={self.invalid_identifier_records}, "
            f"duplicate_records={self.duplicate_records})"
        )


@dataclass(frozen=True)
class ChunkValidation:
    """Result of validating one data/manifest pair."""

    valid: bool
    reason: str
    record_count: int = 0
    _identity_inventory: _ChunkIdentityInventory = field(
        default_factory=_ChunkIdentityInventory,
        repr=False,
        compare=False,
    )


@dataclass(frozen=True)
class ChunkDownloadResult:
    """Observable outcome of a daily download or safe resume skip."""

    data_path: Path
    manifest_path: Path
    status: Literal["downloaded", "skipped"]
    record_count: int
    remote_total_reported: int | None
    complete_for_query: bool
    sha256: str
    _identity_inventory: _ChunkIdentityInventory = field(
        default_factory=_ChunkIdentityInventory,
        repr=False,
        compare=False,
    )


class IncompleteChunkError(RuntimeError):
    """Raised internally when an API response cannot prove query completeness."""


def iter_local_day_windows(
    start: date,
    end_exclusive: date,
    *,
    timezone_name: str,
) -> Iterator[LocalDayWindow]:
    """Yield adjacent local-midnight windows without assuming 24-hour UTC days."""

    if start >= end_exclusive:
        raise ValueError("start must be earlier than end_exclusive")
    zone = ZoneInfo(timezone_name)
    current = start
    while current < end_exclusive:
        following = current + timedelta(days=1)
        yield LocalDayWindow(
            local_start=datetime.combine(current, time.min, zone),
            local_end=datetime.combine(following, time.min, zone),
        )
        current = following


def jpl_acquisition_windows() -> Iterator[LocalDayWindow]:
    """Yield the frozen 2019-04-24 through 2019-06-01 JPL acquisition days."""

    return iter_local_day_windows(
        JPL_ACQUISITION_START.date(),
        JPL_ACQUISITION_END.date(),
        timezone_name=JPL_TIMEZONE,
    )


def jpl_analysis_windows() -> Iterator[LocalDayWindow]:
    """Yield exactly the 31 half-open local days in the May analysis month."""

    return iter_local_day_windows(
        JPL_ANALYSIS_START.date(),
        JPL_ANALYSIS_END.date(),
        timezone_name=JPL_TIMEZONE,
    )


def classify_session(record: Mapping[str, object]) -> SessionRole:
    """Classify a raw session without modifying or copying its fields."""

    connection = parse_acn_datetime(record.get("connectionTime"))
    disconnect = parse_acn_datetime(record.get("disconnectTime"))
    if connection is None:
        return SessionRole(analysis_session=False, carry_in=False)

    acquisition_start = JPL_ACQUISITION_START.astimezone(timezone.utc)
    analysis_start = JPL_ANALYSIS_START.astimezone(timezone.utc)
    analysis_end = JPL_ANALYSIS_END.astimezone(timezone.utc)
    analysis_session = analysis_start <= connection < analysis_end
    carry_in = (
        acquisition_start <= connection < analysis_start
        and disconnect is not None
        and disconnect > analysis_start
    )
    return SessionRole(analysis_session=analysis_session, carry_in=carry_in)


def detect_duplicate_identifiers(
    records: Iterable[Mapping[str, object]],
) -> DuplicateIdentifierCounts:
    """Count repeated private identifiers without exposing their values."""

    object_ids: Counter[object] = Counter()
    session_ids: Counter[object] = Counter()
    for record in records:
        object_id = record.get("_id")
        session_id = record.get("sessionID")
        if object_id not in (None, ""):
            object_ids[object_id] += 1
        if session_id not in (None, ""):
            session_ids[session_id] += 1
    return DuplicateIdentifierCounts(
        duplicate_id_records=sum(count - 1 for count in object_ids.values() if count > 1),
        duplicate_session_id_records=sum(count - 1 for count in session_ids.values() if count > 1),
    )


def _validate_endpoint(endpoint: str) -> Literal["metadata", "timeseries"]:
    if endpoint not in {"metadata", "timeseries"}:
        raise ValueError("endpoint must be 'metadata' or 'timeseries'")
    return endpoint  # type: ignore[return-value]


def chunk_paths(
    root: str | Path,
    endpoint: str,
    window: LocalDayWindow,
) -> tuple[Path, Path]:
    """Return separate raw-data and manifest paths for a local day."""

    endpoint = _validate_endpoint(endpoint)
    base = Path(root)
    data_path = base / endpoint / f"{window.day_key}.jsonl.gz"
    manifest_path = base / "manifests" / endpoint / f"{window.day_key}.manifest.json"
    return data_path, manifest_path


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


def _identifier_pair(record: Mapping[str, Any]) -> tuple[str, str] | None:
    object_id = record.get("_id")
    session_id = record.get("sessionID")
    if not isinstance(object_id, str) or not object_id:
        return None
    if not isinstance(session_id, str) or not session_id:
        return None
    return object_id, session_id


def _identity_inventory(
    identifier_pairs: list[tuple[str, str]],
    invalid_identifier_records: int,
) -> _ChunkIdentityInventory:
    pair_counts = Counter(identifier_pairs)
    return _ChunkIdentityInventory(
        identifier_pairs=tuple(identifier_pairs),
        invalid_identifier_records=invalid_identifier_records,
        duplicate_records=sum(count - 1 for count in pair_counts.values() if count > 1),
    )


def validate_chunk(
    data_path: str | Path,
    manifest_path: str | Path,
    *,
    window: LocalDayWindow,
    endpoint: str,
) -> ChunkValidation:
    """Validate completeness, final-file hash, gzip JSONL, and record count."""

    endpoint = _validate_endpoint(endpoint)
    data = Path(data_path)
    manifest_file = Path(manifest_path)
    if not data.is_file():
        return ChunkValidation(False, "data file is missing")
    if not manifest_file.is_file():
        return ChunkValidation(False, "manifest file is missing")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ChunkValidation(False, "manifest is not valid JSON")
    if not isinstance(manifest, dict):
        return ChunkValidation(False, "manifest root is not an object")
    expected_query = ACNQuery(
        site="jpl",
        start=window.local_start,
        end=window.local_end,
        timeseries=endpoint == "timeseries",
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
    for field_name, expected_value in expected_context.items():
        if manifest.get(field_name) != expected_value:
            return ChunkValidation(
                False,
                f"manifest {field_name} does not match expected query",
            )
    if manifest.get("complete_for_query") is not True:
        return ChunkValidation(False, "manifest is not complete for query")
    if manifest.get("token_stored") is not False:
        return ChunkValidation(False, "manifest token declaration is unsafe")
    expected_hash = manifest.get("sha256")
    if not isinstance(expected_hash, str) or _sha256_file(data) != expected_hash:
        return ChunkValidation(False, "data hash does not match manifest")

    count = 0
    identifier_pairs: list[tuple[str, str]] = []
    invalid_identifier_records = 0
    try:
        with gzip.open(data, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                if not isinstance(item, dict):
                    return ChunkValidation(False, "JSONL record is not an object")
                count += 1
                pair = _identifier_pair(item)
                if pair is None:
                    invalid_identifier_records += 1
                else:
                    identifier_pairs.append(pair)
    except (OSError, EOFError, UnicodeError, json.JSONDecodeError):
        return ChunkValidation(False, "data file is not valid gzip JSONL")

    manifest_count = manifest.get("record_count")
    remote_total = manifest.get("remote_total_reported")
    if not isinstance(manifest_count, int) or isinstance(manifest_count, bool):
        return ChunkValidation(False, "manifest record count is invalid")
    if count != manifest_count:
        return ChunkValidation(False, "data record count does not match manifest", count)
    if (
        not isinstance(remote_total, int)
        or isinstance(remote_total, bool)
        or remote_total < 0
        or count != remote_total
    ):
        return ChunkValidation(False, "remote total is missing or does not match", count)
    return ChunkValidation(
        True,
        "valid",
        count,
        _identity_inventory(identifier_pairs, invalid_identifier_records),
    )


def _remote_total_from_page(page: Mapping[str, Any]) -> int | None:
    meta = page.get("_meta")
    if not isinstance(meta, Mapping):
        return None
    total = meta.get("total")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        return None
    return total


def download_day_chunk(
    client: ACNClient,
    root: str | Path,
    window: LocalDayWindow,
    *,
    endpoint: str,
    downloaded_at_utc: datetime | None = None,
    _existing_validation: ChunkValidation | None = None,
) -> ChunkDownloadResult:
    """Download one daily API query atomically, or skip a validated pair."""

    endpoint = _validate_endpoint(endpoint)
    data_path, manifest_path = chunk_paths(root, endpoint, window)
    existing = _existing_validation or validate_chunk(
        data_path,
        manifest_path,
        window=window,
        endpoint=endpoint,
    )
    if existing.valid:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return ChunkDownloadResult(
            data_path=data_path,
            manifest_path=manifest_path,
            status="skipped",
            record_count=existing.record_count,
            remote_total_reported=manifest["remote_total_reported"],
            complete_for_query=True,
            sha256=manifest["sha256"],
            _identity_inventory=existing._identity_inventory,
        )

    timestamp = downloaded_at_utc or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("downloaded_at_utc must be timezone-aware")
    query = ACNQuery(
        site="jpl",
        start=window.local_start,
        end=window.local_end,
        timeseries=endpoint == "timeseries",
    )
    data_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = data_path.with_suffix(data_path.suffix + ".partial")
    record_count = 0
    reported_totals: set[int] = set()
    try:
        with temporary.open("wb") as raw_handle:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw_handle,
                mtime=0,
            ) as gzip_handle:
                for page in client.iter_pages(query):
                    remote_total = _remote_total_from_page(page)
                    if remote_total is not None:
                        reported_totals.add(remote_total)
                    items = page.get("_items")
                    if not isinstance(items, list):
                        raise ACNSchemaError("ACN-Data page is missing list field '_items'")
                    for item in items:
                        if not isinstance(item, dict):
                            raise ACNSchemaError("ACN-Data session record must be an object")
                        encoded = (
                            json.dumps(
                                item,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            + "\n"
                        ).encode("utf-8")
                        gzip_handle.write(encoded)
                        record_count += 1
            raw_handle.flush()
            os.fsync(raw_handle.fileno())

        verified_count = 0
        identifier_pairs: list[tuple[str, str]] = []
        invalid_identifier_records = 0
        with gzip.open(temporary, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise ACNSchemaError("temporary JSONL record must be an object")
                verified_count += 1
                pair = _identifier_pair(item)
                if pair is None:
                    invalid_identifier_records += 1
                else:
                    identifier_pairs.append(pair)
        remote_total_reported = next(iter(reported_totals)) if len(reported_totals) == 1 else None
        if (
            remote_total_reported is None
            or record_count != remote_total_reported
            or verified_count != record_count
        ):
            raise IncompleteChunkError("remote total did not prove completeness")
        digest = _sha256_file(temporary)
        os.replace(temporary, data_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    manifest = {
        "schema_version": "acn-jpl-daily-chunk/v1",
        "dataset_id": "D0001",
        "source": "ACN-Data official REST API",
        "endpoint": query.endpoint,
        "site": "jpl",
        "timezone": JPL_TIMEZONE,
        "local_start_inclusive": window.local_start.isoformat(),
        "local_end_exclusive": window.local_end.isoformat(),
        "utc_start_inclusive": window.utc_start.isoformat(),
        "utc_end_exclusive": window.utc_end.isoformat(),
        "query_condition": query.condition,
        "record_count": record_count,
        "remote_total_reported": remote_total_reported,
        "complete_for_query": True,
        "downloaded_at_utc": timestamp.astimezone(timezone.utc).isoformat(),
        "sha256": digest,
        "token_stored": False,
        "output_file": data_path.name,
    }
    _atomic_write_json(manifest_path, manifest)
    return ChunkDownloadResult(
        data_path=data_path,
        manifest_path=manifest_path,
        status="downloaded",
        record_count=record_count,
        remote_total_reported=remote_total_reported,
        complete_for_query=True,
        sha256=digest,
        _identity_inventory=_identity_inventory(
            identifier_pairs,
            invalid_identifier_records,
        ),
    )


def _load_progress_document(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"endpoints": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"endpoints": {}}
    if not isinstance(payload, dict):
        return {"endpoints": {}}
    endpoints = payload.get("endpoints")
    if isinstance(endpoints, dict):
        return {
            "endpoints": {
                key: value
                for key, value in endpoints.items()
                if key in {"metadata", "timeseries"} and isinstance(value, dict)
            }
        }
    # Migrate the original single-endpoint v1 document without discarding a
    # resumable state created by an earlier revision.
    legacy_endpoint = payload.get("endpoint")
    if legacy_endpoint in {"metadata", "timeseries"}:
        return {"endpoints": {legacy_endpoint: payload}}
    return {"endpoints": {}}


def run_daily_chunks(
    client: ACNClient,
    root: str | Path,
    windows: Iterable[LocalDayWindow],
    *,
    endpoint: str,
    _private_validation_sink: MutableMapping[str, _ChunkIdentityInventory] | None = None,
) -> dict[str, Any]:
    """Run daily chunks serially and atomically checkpoint resumable state."""

    endpoint = _validate_endpoint(endpoint)
    ordered_windows = list(windows)
    day_order = [window.day_key for window in ordered_windows]
    if len(set(day_order)) != len(day_order):
        raise ValueError("windows must have unique local day keys")
    if _private_validation_sink is not None:
        for day in day_order:
            _private_validation_sink.pop(day, None)

    root_path = Path(root)
    progress_path = root_path / "state" / "progress.json"
    progress_document = _load_progress_document(progress_path)
    endpoint_states = dict(progress_document["endpoints"])
    previous = endpoint_states.get(endpoint, {})
    previous_retry_count = previous.get("retry_count", 0)
    retry_count = (
        previous_retry_count
        if isinstance(previous_retry_count, int)
        and not isinstance(previous_retry_count, bool)
        and previous_retry_count >= 0
        else 0
    )
    previous_failed = previous.get("failed_days", [])
    failed = (
        {day for day in previous_failed if isinstance(day, str) and day in set(day_order)}
        if isinstance(previous_failed, list)
        else set()
    )
    valid_failure_reasons = {
        "ACN_DATA_ERROR",
        "NETWORK_ERROR",
        "INCOMPLETE_RESPONSE",
        "UNEXPECTED_ERROR",
    }
    previous_failure_reasons = previous.get("failure_reasons", {})
    failure_reasons = (
        {
            day: reason
            for day, reason in previous_failure_reasons.items()
            if day in failed and reason in valid_failure_reasons
        }
        if isinstance(previous_failure_reasons, dict)
        else {}
    )
    completed: set[str] = set()
    pending = set(day_order) - failed
    previous_last_success = previous.get("last_success")
    last_success = previous_last_success if isinstance(previous_last_success, str) else None
    stop_reason: str | None = None

    def snapshot() -> dict[str, Any]:
        return {
            "schema_version": "acn-jpl-progress/v2",
            "endpoint": endpoint,
            "pending_days": [day for day in day_order if day in pending],
            "completed_days": [day for day in day_order if day in completed],
            "failed_days": [day for day in day_order if day in failed],
            "last_success": last_success,
            "retry_count": retry_count,
            "failure_reasons": {
                day: failure_reasons[day] for day in day_order if day in failure_reasons
            },
            "stop_reason": stop_reason,
        }

    def checkpoint() -> None:
        current = snapshot()
        endpoint_states[endpoint] = current
        document = dict(current)
        document["schema_version"] = "acn-jpl-progress/v3"
        document["endpoints"] = endpoint_states
        _atomic_write_json(progress_path, document)

    checkpoint()
    for window in ordered_windows:
        day = window.day_key
        if day in completed:
            continue
        if day in failed:
            failed.discard(day)
            failure_reasons.pop(day, None)
            pending.add(day)
        checkpoint()
        try:
            data_path, manifest_path = chunk_paths(root_path, endpoint, window)
            existing = validate_chunk(
                data_path,
                manifest_path,
                window=window,
                endpoint=endpoint,
            )
            identity_inventory = existing._identity_inventory
            if not existing.valid:
                result = download_day_chunk(
                    client,
                    root_path,
                    window,
                    endpoint=endpoint,
                    _existing_validation=existing,
                )
                identity_inventory = result._identity_inventory
                if not result.complete_for_query:
                    raise IncompleteChunkError("remote total did not prove completeness")

        except IncompleteChunkError:
            retry_count += 1
            completed.discard(day)
            failed.add(day)
            pending.discard(day)
            failure_reasons[day] = "INCOMPLETE_RESPONSE"
            stop_reason = "INCOMPLETE_RESPONSE"
            checkpoint()
            break
        except ACNDataError:
            retry_count += 1
            completed.discard(day)
            failed.add(day)
            pending.discard(day)
            failure_reasons[day] = "ACN_DATA_ERROR"
            stop_reason = "ACN_DATA_ERROR"
            checkpoint()
            break
        except requests.RequestException:
            retry_count += 1
            completed.discard(day)
            failed.add(day)
            pending.discard(day)
            failure_reasons[day] = "NETWORK_ERROR"
            stop_reason = "NETWORK_ERROR"
            checkpoint()
            break
        except Exception:
            retry_count += 1
            completed.discard(day)
            failed.add(day)
            pending.discard(day)
            failure_reasons[day] = "UNEXPECTED_ERROR"
            stop_reason = "UNEXPECTED_ERROR"
            checkpoint()
            raise
        else:
            if _private_validation_sink is not None:
                _private_validation_sink[day] = identity_inventory
            completed.add(day)
            failed.discard(day)
            failure_reasons.pop(day, None)
            pending.discard(day)
            last_success = day
        checkpoint()
    return snapshot()
