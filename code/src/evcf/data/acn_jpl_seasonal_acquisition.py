"""Fail-closed acquisition for approved JPL local-month time-series scopes.

Identifier-bearing metadata and query material never enter the public result.  A
literal authorization, a loader-sealed complete-metadata scope, and one live
official metadata probe must all succeed before a time-series client is created.
"""

from __future__ import annotations

import gzip
import hashlib
import inspect
import json
import os
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import requests

from .acn_api import ACNClient, ACNDataError, ACNQuery, ACNSchemaError
from .acn_audit import parse_acn_datetime
from .acn_jpl_gate0 import (
    ACN_OFFICIAL_SOURCE,
    IncompleteChunkError,
    _ChunkIdentityInventory,
    _PrivateChunkIdentityCapture,
    chunk_paths,
    is_valid_utc_timestamp,
    run_daily_chunks,
    validate_chunk,
)
from .acn_jpl_month_config import (
    SEASONAL_MONTHS,
    CompleteMetadataScope,
    JPLMonthConfig,
    is_canonical_jpl_month_config,
    jpl_month_config,
)
from .acn_jpl_official_reference import OfficialLocalMonthTotalResult

_CARRY_SCHEMA = "acn-jpl-seasonal-carry-in/v1"
_RUN_SCHEMA = "acn-jpl-seasonal-month-ts-run/v1"
_SEASONAL_SCHEMA = "acn-jpl-seasonal-ts-run/v1"
_SAFE_FAILURE_CODES = frozenset(
    {
        "SCOPE_NOT_VERIFIED",
        "OFFICIAL_PROBE_FAILED",
        "OFFICIAL_PROBE_NOT_LIVE",
        "OFFICIAL_TOTAL_MISMATCH",
        "DAILY_INCOMPLETE",
        "DAILY_LINKAGE_FAIL",
        "CARRY_INCOMPLETE",
        "COMBINED_LINKAGE_FAIL",
        "PARTIAL_FILES_PRESENT",
        "ACN_DATA_ERROR",
        "NETWORK_ERROR",
        "INCOMPLETE_RESPONSE",
        "UNEXPECTED_ERROR",
    }
)


class SeasonalAuthorizationError(PermissionError):
    """Raised before any read, client construction, or write without opt-in."""


@dataclass(frozen=True)
class MonthAcquisitionResult:
    """Aggregate-only result for one approved month."""

    month: str
    status: Literal["COMPLETE", "INCOMPLETE", "METADATA_GATE_FAIL", "FAILED"]
    local_session_count: int
    official_total: int | None
    carry_in_count: int
    valid_daily_chunks: int = 0
    failed_daily_chunks: int = 0
    daily_record_count: int = 0
    daily_unique_object_count: int = 0
    daily_unique_session_count: int = 0
    daily_unique_pair_count: int = 0
    carry_in_completed: int = 0
    carry_record_count: int = 0
    carry_unique_pair_count: int = 0
    combined_record_count: int = 0
    combined_unique_object_count: int = 0
    combined_unique_session_count: int = 0
    combined_unique_pair_count: int = 0
    missing_pairs: int = 0
    orphan_pairs: int = 0
    raw_file_count: int = 0
    partial_file_count: int = 0
    raw_inventory_sha256: str | None = None
    reason_codes: tuple[str, ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _RUN_SCHEMA,
            "month": self.month,
            "status": self.status,
            "local_session_count": self.local_session_count,
            "official_total": self.official_total,
            "carry_in_count": self.carry_in_count,
            "valid_daily_chunks": self.valid_daily_chunks,
            "failed_daily_chunks": self.failed_daily_chunks,
            "daily_record_count": self.daily_record_count,
            "daily_unique_object_count": self.daily_unique_object_count,
            "daily_unique_session_count": self.daily_unique_session_count,
            "daily_unique_pair_count": self.daily_unique_pair_count,
            "carry_in_completed": self.carry_in_completed,
            "carry_record_count": self.carry_record_count,
            "carry_unique_pair_count": self.carry_unique_pair_count,
            "combined_record_count": self.combined_record_count,
            "combined_unique_object_count": self.combined_unique_object_count,
            "combined_unique_session_count": self.combined_unique_session_count,
            "combined_unique_pair_count": self.combined_unique_pair_count,
            "missing_pairs": self.missing_pairs,
            "orphan_pairs": self.orphan_pairs,
            "raw_file_count": self.raw_file_count,
            "partial_file_count": self.partial_file_count,
            "raw_inventory_sha256": self.raw_inventory_sha256,
            "reason_codes": list(self.reason_codes),
            "privacy": {
                "aggregate_only": True,
                "identifiers_emitted": False,
                "queries_emitted": False,
                "token_emitted": False,
                "absolute_paths_emitted": False,
            },
        }


@dataclass(frozen=True)
class _CarryTransfer:
    status: Literal["DOWNLOADED", "SKIPPED"]
    pair: tuple[str, str]
    record_count: int


@dataclass(frozen=True)
class _Linkage:
    record_count: int
    unique_object_count: int
    unique_session_count: int
    unique_pair_count: int
    duplicate_object_records: int
    duplicate_session_records: int
    duplicate_pair_records: int
    invalid_identifier_records: int
    missing_pairs: int
    orphan_pairs: int

    @property
    def exact(self) -> bool:
        return all(
            value == 0
            for value in (
                self.duplicate_object_records,
                self.duplicate_session_records,
                self.duplicate_pair_records,
                self.invalid_identifier_records,
                self.missing_pairs,
                self.orphan_pairs,
            )
        )


def _nonnegative(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _safe_counts(scope: object) -> tuple[int, int]:
    return (
        _nonnegative(getattr(scope, "local_month_session_count", 0)),
        _nonnegative(getattr(scope, "carry_in_session_count", 0)),
    )


def _result(
    config: JPLMonthConfig,
    scope: object,
    *,
    status: Literal["COMPLETE", "INCOMPLETE", "METADATA_GATE_FAIL", "FAILED"],
    official_total: int | None = None,
    reason_codes: Iterable[str] = (),
    **counts: Any,
) -> MonthAcquisitionResult:
    local_count, carry_count = _safe_counts(scope)
    safe_reasons = tuple(code for code in reason_codes if code in _SAFE_FAILURE_CODES)
    return MonthAcquisitionResult(
        month=config.month,
        status=status,
        local_session_count=local_count,
        official_total=(official_total if _nonnegative(official_total) == official_total else None),
        carry_in_count=carry_count,
        reason_codes=safe_reasons,
        **counts,
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
    temporary.unlink(missing_ok=True)
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


def _pair(record: Mapping[str, Any]) -> tuple[str, str] | None:
    object_id = record.get("_id")
    session_id = record.get("sessionID")
    if not isinstance(object_id, str) or not object_id:
        return None
    if not isinstance(session_id, str) or not session_id:
        return None
    return object_id, session_id


def _expected_pairs(records: Iterable[Mapping[str, Any]]) -> set[tuple[str, str]]:
    pairs = {_pair(record) for record in records}
    if None in pairs:
        return set()
    return {pair for pair in pairs if pair is not None}


def _linkage(
    pairs: Iterable[tuple[str, str]],
    *,
    invalid_identifier_records: int,
    expected_pairs: set[tuple[str, str]],
) -> _Linkage:
    materialized = tuple(pairs)
    pair_counts = Counter(materialized)
    object_counts = Counter(pair[0] for pair in materialized)
    session_counts = Counter(pair[1] for pair in materialized)
    observed = set(materialized)
    return _Linkage(
        record_count=len(materialized) + invalid_identifier_records,
        unique_object_count=len(object_counts),
        unique_session_count=len(session_counts),
        unique_pair_count=len(pair_counts),
        duplicate_object_records=sum(count - 1 for count in object_counts.values()),
        duplicate_session_records=sum(count - 1 for count in session_counts.values()),
        duplicate_pair_records=sum(count - 1 for count in pair_counts.values()),
        invalid_identifier_records=invalid_identifier_records,
        missing_pairs=len(expected_pairs - observed),
        orphan_pairs=len(observed - expected_pairs),
    )


def _runner_supports_sink(runner: Callable[..., Any]) -> bool:
    try:
        parameter = inspect.signature(runner, follow_wrapped=False).parameters.get(
            "_private_validation_sink"
        )
    except (TypeError, ValueError):
        return False
    return parameter is not None and parameter.kind is not inspect.Parameter.POSITIONAL_ONLY


def _load_daily_sink(
    root: Path,
    config: JPLMonthConfig,
) -> dict[str, _ChunkIdentityInventory]:
    sink: dict[str, _ChunkIdentityInventory] = {}
    for window in config.day_windows:
        data_path, manifest_path = chunk_paths(root, "timeseries", window)
        capture = _PrivateChunkIdentityCapture()
        validation = validate_chunk(
            data_path,
            manifest_path,
            window=window,
            endpoint="timeseries",
            _private_identity_capture=capture,
        )
        if validation.valid and capture.inventory is not None:
            sink[window.day_key] = capture.inventory
    return sink


def _daily_summary(
    progress: object,
    config: JPLMonthConfig,
    sink: Mapping[str, _ChunkIdentityInventory],
    expected: set[tuple[str, str]],
) -> tuple[int, int, _Linkage, bool]:
    progress_map = progress if isinstance(progress, Mapping) else {}
    day_order = [window.day_key for window in config.day_windows]
    completed = progress_map.get("completed_days")
    failed = progress_map.get("failed_days")
    pending = progress_map.get("pending_days")
    progress_complete = completed == day_order and failed == [] and pending == []
    pairs: list[tuple[str, str]] = []
    invalid = 0
    valid_chunks = 0
    for day in day_order:
        inventory = sink.get(day)
        if not isinstance(inventory, _ChunkIdentityInventory):
            continue
        valid_chunks += 1
        pairs.extend(inventory.identifier_pairs)
        invalid += inventory.invalid_identifier_records
    linkage = _linkage(pairs, invalid_identifier_records=invalid, expected_pairs=expected)
    exact = (
        progress_complete
        and valid_chunks == config.day_count
        and linkage.exact
        and linkage.record_count == len(expected)
        and linkage.unique_object_count == len(expected)
        and linkage.unique_session_count == len(expected)
        and linkage.unique_pair_count == len(expected)
    )
    return valid_chunks, config.day_count - valid_chunks, linkage, exact


def _carry_paths(root: Path, ordinal: int) -> tuple[Path, Path]:
    stem = f"carry-{ordinal:04d}"
    return (
        root / "timeseries" / "carry_in" / f"{stem}.jsonl.gz",
        root / "manifests" / "carry_in" / f"{stem}.manifest.json",
    )


def _carry_query(record: Mapping[str, Any], config: JPLMonthConfig) -> ACNQuery:
    connection = parse_acn_datetime(record.get("connectionTime"))
    pair = _pair(record)
    if connection is None or pair is None or not connection < config.utc_start:
        raise ValueError("verified carry metadata is inconsistent")
    return ACNQuery(
        site="jpl",
        start=connection,
        end=config.local_start,
        timeseries=True,
        session_id=pair[1],
    )


def _carry_context(
    record: Mapping[str, Any],
    config: JPLMonthConfig,
    ordinal: int,
    data_path: Path,
) -> dict[str, Any]:
    pair = _pair(record)
    if pair is None:
        raise ValueError("verified carry metadata lacks identifiers")
    query = _carry_query(record, config)
    return {
        "schema_version": _CARRY_SCHEMA,
        "dataset_id": f"D0001-jpl-{config.month}-seasonal-ts",
        "source": ACN_OFFICIAL_SOURCE,
        "endpoint": query.endpoint,
        "site": "jpl",
        "timezone": config.timezone_name,
        "month": config.month,
        "ordinal": ordinal,
        "local_month_start": config.local_start.isoformat(),
        "utc_start_inclusive": query.start_utc.isoformat(),
        "utc_end_exclusive": query.end_utc.isoformat(),
        "_id": pair[0],
        "sessionID": pair[1],
        "query_condition": query.condition,
        "output_file": data_path.name,
    }


def _read_carry(path: Path) -> tuple[int, tuple[str, str] | None]:
    count = 0
    found: tuple[str, str] | None = None
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ACNSchemaError("carry record is not an object")
            count += 1
            if count == 1:
                found = _pair(record)
    return count, found


def _validated_carry(
    root: Path,
    record: Mapping[str, Any],
    config: JPLMonthConfig,
    ordinal: int,
) -> _CarryTransfer | None:
    data_path, manifest_path = _carry_paths(root, ordinal)
    partials = (
        data_path.with_suffix(data_path.suffix + ".partial"),
        manifest_path.with_suffix(manifest_path.suffix + ".partial"),
    )
    if (
        any(path.exists() for path in partials)
        or not data_path.is_file()
        or not manifest_path.is_file()
    ):
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        count, observed_pair = _read_carry(data_path)
    except (OSError, EOFError, UnicodeError, json.JSONDecodeError, ACNSchemaError):
        return None
    expected = _carry_context(record, config, ordinal, data_path)
    expected_keys = set(expected) | {
        "record_count",
        "remote_total_reported",
        "complete_for_query",
        "downloaded_at_utc",
        "sha256",
        "token_stored",
    }
    pair = _pair(record)
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        return None
    if any(manifest.get(key) != value for key, value in expected.items()):
        return None
    if not (
        manifest.get("record_count") == 1
        and not isinstance(manifest.get("record_count"), bool)
        and manifest.get("remote_total_reported") == 1
        and not isinstance(manifest.get("remote_total_reported"), bool)
        and manifest.get("complete_for_query") is True
        and manifest.get("token_stored") is False
        and is_valid_utc_timestamp(manifest.get("downloaded_at_utc"))
        and isinstance(manifest.get("sha256"), str)
        and manifest.get("sha256") == _sha256_file(data_path)
        and count == 1
        and observed_pair == pair
    ):
        return None
    assert pair is not None
    return _CarryTransfer("SKIPPED", pair, 1)


def _remote_total(page: Mapping[str, Any]) -> int | None:
    meta = page.get("_meta")
    total = meta.get("total") if isinstance(meta, Mapping) else None
    return total if isinstance(total, int) and not isinstance(total, bool) and total >= 0 else None


def _download_carry(
    client: ACNClient,
    root: Path,
    record: Mapping[str, Any],
    config: JPLMonthConfig,
    ordinal: int,
    timestamp: datetime,
) -> _CarryTransfer:
    existing = _validated_carry(root, record, config, ordinal)
    if existing is not None:
        return existing
    data_path, manifest_path = _carry_paths(root, ordinal)
    data_partial = data_path.with_suffix(data_path.suffix + ".partial")
    manifest_partial = manifest_path.with_suffix(manifest_path.suffix + ".partial")
    data_partial.unlink(missing_ok=True)
    manifest_partial.unlink(missing_ok=True)
    query = _carry_query(record, config)
    expected_pair = _pair(record)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    totals: set[int] = set()
    count = 0
    try:
        with data_partial.open("wb") as raw_handle:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as zipped:
                for page in client.iter_pages(query):
                    total = _remote_total(page)
                    if total is not None:
                        totals.add(total)
                    items = page.get("_items")
                    if not isinstance(items, list):
                        raise ACNSchemaError("ACN page lacks an item list")
                    for item in items:
                        if not isinstance(item, dict):
                            raise ACNSchemaError("ACN session is not an object")
                        count += 1
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
        verified_count, observed_pair = _read_carry(data_partial)
        remote_total = next(iter(totals)) if len(totals) == 1 else None
        if not (
            count == 1
            and verified_count == 1
            and remote_total == 1
            and observed_pair == expected_pair
        ):
            raise IncompleteChunkError("carry query completeness could not be proven")
        digest = _sha256_file(data_partial)
        os.replace(data_partial, data_path)
        manifest = {
            **_carry_context(record, config, ordinal, data_path),
            "record_count": 1,
            "remote_total_reported": 1,
            "complete_for_query": True,
            "downloaded_at_utc": timestamp.astimezone(timezone.utc).isoformat(),
            "sha256": digest,
            "token_stored": False,
        }
        _atomic_write_json(manifest_path, manifest)
    except Exception:
        data_partial.unlink(missing_ok=True)
        manifest_partial.unlink(missing_ok=True)
        raise
    assert expected_pair is not None
    return _CarryTransfer("DOWNLOADED", expected_pair, 1)


def _raw_inventory(root: Path) -> tuple[int, int, str | None]:
    if not root.is_dir():
        return 0, 0, None
    partial_count = sum(path.is_file() for path in root.rglob("*.partial"))
    files = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and (path.name.endswith(".jsonl.gz") or path.name.endswith(".manifest.json"))
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(f"{relative}\0{_sha256_file(path)}\0{path.stat().st_size}\n".encode())
    return len(files), partial_count, digest.hexdigest()


def _carry_layout_exact(root: Path, count: int) -> bool:
    expected_data = {f"carry-{ordinal:04d}.jsonl.gz" for ordinal in range(1, count + 1)}
    expected_manifests = {f"carry-{ordinal:04d}.manifest.json" for ordinal in range(1, count + 1)}
    data_root = root / "timeseries" / "carry_in"
    manifest_root = root / "manifests" / "carry_in"
    actual_data = {path.name for path in data_root.glob("*") if path.is_file()}
    actual_manifests = {path.name for path in manifest_root.glob("*") if path.is_file()}
    return actual_data == expected_data and actual_manifests == expected_manifests


def acquire_jpl_month(
    *,
    authorized: bool,
    config: JPLMonthConfig,
    scope: CompleteMetadataScope,
    official_probe: Callable[[JPLMonthConfig], OfficialLocalMonthTotalResult],
    raw_root: str | Path,
    ts_client_factory: Callable[[], ACNClient],
    daily_runner: Callable[..., dict[str, Any]] = run_daily_chunks,
    downloaded_at_utc: datetime | None = None,
    concurrency: int = 1,
) -> MonthAcquisitionResult:
    """Acquire one sealed local month after all metadata gates pass."""

    if authorized is not True:
        raise SeasonalAuthorizationError("seasonal acquisition requires explicit authorization")
    if (
        not isinstance(concurrency, int)
        or isinstance(concurrency, bool)
        or concurrency not in {1, 2}
    ):
        raise ValueError("concurrency must be 1 or 2")
    if not (
        isinstance(scope, CompleteMetadataScope)
        and is_canonical_jpl_month_config(config)
        and scope.is_verified_for(config)
    ):
        return _result(
            config,
            scope,
            status="METADATA_GATE_FAIL",
            reason_codes=("SCOPE_NOT_VERIFIED",),
        )
    timestamp = downloaded_at_utc or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("downloaded_at_utc must be timezone-aware")

    try:
        official = official_probe(config)
    except Exception:  # noqa: BLE001 - query/path material must not escape
        return _result(
            config,
            scope,
            status="METADATA_GATE_FAIL",
            reason_codes=("OFFICIAL_PROBE_FAILED",),
        )
    official_total = official.total if isinstance(official, OfficialLocalMonthTotalResult) else None
    if not (
        isinstance(official, OfficialLocalMonthTotalResult)
        and official.is_live_verified_for(config)
    ):
        return _result(
            config,
            scope,
            status="METADATA_GATE_FAIL",
            official_total=official_total,
            reason_codes=("OFFICIAL_PROBE_NOT_LIVE",),
        )
    if not scope.is_verified_for(config):
        return _result(
            config,
            scope,
            status="METADATA_GATE_FAIL",
            official_total=official.total,
            reason_codes=("SCOPE_NOT_VERIFIED",),
        )
    if official.total != scope.local_month_session_count:
        return _result(
            config,
            scope,
            status="METADATA_GATE_FAIL",
            official_total=official.total,
            reason_codes=("OFFICIAL_TOTAL_MISMATCH",),
        )

    try:
        client = ts_client_factory()
    except Exception:  # noqa: BLE001 - factory details may contain credentials or URLs
        return _result(
            config,
            scope,
            status="INCOMPLETE",
            official_total=official.total,
            failed_daily_chunks=config.day_count,
            reason_codes=("UNEXPECTED_ERROR",),
        )
    root = Path(raw_root)
    sink: dict[str, _ChunkIdentityInventory] = {}
    try:
        if _runner_supports_sink(daily_runner):
            progress = daily_runner(
                client,
                root,
                config.day_windows,
                endpoint="timeseries",
                _private_validation_sink=sink,
            )
        else:
            progress = daily_runner(client, root, config.day_windows, endpoint="timeseries")
            sink = _load_daily_sink(root, config)
    except ACNDataError:
        return _result(
            config,
            scope,
            status="INCOMPLETE",
            official_total=official.total,
            failed_daily_chunks=config.day_count,
            reason_codes=("ACN_DATA_ERROR",),
        )
    except requests.RequestException:
        return _result(
            config,
            scope,
            status="INCOMPLETE",
            official_total=official.total,
            failed_daily_chunks=config.day_count,
            reason_codes=("NETWORK_ERROR",),
        )
    except Exception:  # noqa: BLE001 - persist/report only a static reason code
        return _result(
            config,
            scope,
            status="INCOMPLETE",
            official_total=official.total,
            failed_daily_chunks=config.day_count,
            reason_codes=("UNEXPECTED_ERROR",),
        )

    expected_daily = _expected_pairs(scope.local_month_records)
    valid_days, failed_days, daily_linkage, daily_exact = _daily_summary(
        progress, config, sink, expected_daily
    )
    base_counts = {
        "valid_daily_chunks": valid_days,
        "failed_daily_chunks": failed_days,
        "daily_record_count": daily_linkage.record_count,
        "daily_unique_object_count": daily_linkage.unique_object_count,
        "daily_unique_session_count": daily_linkage.unique_session_count,
        "daily_unique_pair_count": daily_linkage.unique_pair_count,
        "missing_pairs": daily_linkage.missing_pairs,
        "orphan_pairs": daily_linkage.orphan_pairs,
    }
    if not daily_exact:
        reason = "DAILY_INCOMPLETE" if valid_days != config.day_count else "DAILY_LINKAGE_FAIL"
        return _result(
            config,
            scope,
            status="INCOMPLETE",
            official_total=official.total,
            reason_codes=(reason,),
            **base_counts,
        )

    ordered_carry = tuple(
        sorted(scope.carry_in_records, key=lambda record: (record["sessionID"], record["_id"]))
    )
    carry_pairs: list[tuple[str, str]] = []
    carry_completed = 0
    try:
        for ordinal, record in enumerate(ordered_carry, start=1):
            transfer = _download_carry(client, root, record, config, ordinal, timestamp)
            carry_pairs.append(transfer.pair)
            carry_completed += 1
    except IncompleteChunkError:
        reason = "INCOMPLETE_RESPONSE"
    except ACNDataError:
        reason = "ACN_DATA_ERROR"
    except requests.RequestException:
        reason = "NETWORK_ERROR"
    except Exception:  # noqa: BLE001 - never expose URL/query/path/identifier text
        reason = "UNEXPECTED_ERROR"
    else:
        reason = ""

    expected_carry = _expected_pairs(ordered_carry)
    carry_linkage = _linkage(
        carry_pairs,
        invalid_identifier_records=0,
        expected_pairs=expected_carry,
    )
    carry_counts = {
        **base_counts,
        "carry_in_completed": carry_completed,
        "carry_record_count": carry_linkage.record_count,
        "carry_unique_pair_count": carry_linkage.unique_pair_count,
    }
    if reason or not (
        carry_completed == len(ordered_carry)
        and carry_linkage.exact
        and carry_linkage.record_count == len(expected_carry)
        and _carry_layout_exact(root, len(ordered_carry))
    ):
        raw_files, partials, raw_digest = _raw_inventory(root)
        return _result(
            config,
            scope,
            status="INCOMPLETE",
            official_total=official.total,
            reason_codes=((reason or "CARRY_INCOMPLETE"),),
            raw_file_count=raw_files,
            partial_file_count=partials,
            raw_inventory_sha256=raw_digest,
            **carry_counts,
        )

    combined_pairs = tuple(expected_daily) + tuple(carry_pairs)
    combined_expected = expected_daily | expected_carry
    combined_linkage = _linkage(
        combined_pairs,
        invalid_identifier_records=0,
        expected_pairs=combined_expected,
    )
    combined_expected_count = scope.local_month_session_count + scope.carry_in_session_count
    combined_exact = (
        expected_daily.isdisjoint(expected_carry)
        and combined_linkage.exact
        and combined_linkage.record_count == combined_expected_count
        and combined_linkage.unique_object_count == combined_expected_count
        and combined_linkage.unique_session_count == combined_expected_count
        and combined_linkage.unique_pair_count == combined_expected_count
    )
    raw_files, partials, raw_digest = _raw_inventory(root)
    final_counts = {
        **carry_counts,
        "combined_record_count": combined_linkage.record_count,
        "combined_unique_object_count": combined_linkage.unique_object_count,
        "combined_unique_session_count": combined_linkage.unique_session_count,
        "combined_unique_pair_count": combined_linkage.unique_pair_count,
        "missing_pairs": daily_linkage.missing_pairs + carry_linkage.missing_pairs,
        "orphan_pairs": daily_linkage.orphan_pairs + carry_linkage.orphan_pairs,
        "raw_file_count": raw_files,
        "partial_file_count": partials,
        "raw_inventory_sha256": raw_digest,
    }
    if not combined_exact:
        return _result(
            config,
            scope,
            status="INCOMPLETE",
            official_total=official.total,
            reason_codes=("COMBINED_LINKAGE_FAIL",),
            **final_counts,
        )
    if partials:
        return _result(
            config,
            scope,
            status="INCOMPLETE",
            official_total=official.total,
            reason_codes=("PARTIAL_FILES_PRESENT",),
            **final_counts,
        )
    return _result(
        config,
        scope,
        status="COMPLETE",
        official_total=official.total,
        **final_counts,
    )


def _ordered_months(months: Sequence[JPLMonthConfig] | None) -> tuple[JPLMonthConfig, ...]:
    selected = (
        tuple(jpl_month_config(month) for month in SEASONAL_MONTHS)
        if months is None
        else tuple(months)
    )
    names = tuple(config.month for config in selected if isinstance(config, JPLMonthConfig))
    canonical = tuple(month for month in SEASONAL_MONTHS if month in names)
    if (
        len(names) != len(selected)
        or names != canonical
        or any(not is_canonical_jpl_month_config(config) for config in selected)
    ):
        raise ValueError("months must follow the fixed seasonal order without duplicates")
    return selected


def _sanitize_month_output(config: JPLMonthConfig, value: object) -> dict[str, Any]:
    if isinstance(value, MonthAcquisitionResult):
        payload = value.public_dict()
    elif isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {}
    status = payload.get("status")
    month = payload.get("month")
    reasons = payload.get("reason_codes")
    safe_status = status if status in {"COMPLETE", "INCOMPLETE", "METADATA_GATE_FAIL"} else "FAILED"
    safe_reasons = (
        [code for code in reasons if code in _SAFE_FAILURE_CODES]
        if isinstance(reasons, (list, tuple))
        else []
    )
    if month != config.month:
        safe_status = "FAILED"
        safe_reasons = ["UNEXPECTED_ERROR"]
    result: dict[str, Any] = {
        "month": config.month,
        "status": safe_status,
        "reason_codes": safe_reasons,
    }
    for name in (
        "local_session_count",
        "official_total",
        "carry_in_count",
        "valid_daily_chunks",
        "failed_daily_chunks",
        "daily_record_count",
        "carry_in_completed",
        "carry_record_count",
        "combined_record_count",
        "raw_file_count",
        "partial_file_count",
    ):
        value = payload.get(name)
        result[name] = value if _nonnegative(value) == value else None
    digest = payload.get("raw_inventory_sha256")
    result["raw_inventory_sha256"] = (
        digest
        if isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        else None
    )
    return result


def run_seasonal_acquisition(
    *,
    authorized: bool,
    month_runner: Callable[[JPLMonthConfig], object],
    months: Sequence[JPLMonthConfig] | None = None,
    concurrency: int = 1,
) -> dict[str, Any]:
    """Run approved months serially in fixed order and isolate month failures."""

    if authorized is not True:
        raise SeasonalAuthorizationError("seasonal acquisition requires explicit authorization")
    if (
        not isinstance(concurrency, int)
        or isinstance(concurrency, bool)
        or concurrency not in {1, 2}
    ):
        raise ValueError("concurrency must be 1 or 2")
    ordered = _ordered_months(months)
    results: list[dict[str, Any]] = []
    for config in ordered:
        try:
            value = month_runner(config)
        except Exception:  # noqa: BLE001 - external result contains only a static code
            value = {
                "month": config.month,
                "status": "FAILED",
                "reason_codes": ["UNEXPECTED_ERROR"],
            }
        results.append(_sanitize_month_output(config, value))
    return {
        "schema_version": _SEASONAL_SCHEMA,
        "status": "COMPLETE"
        if all(item["status"] == "COMPLETE" for item in results)
        else "INCOMPLETE",
        "months": results,
        "concurrency": concurrency,
        "serial_execution": True,
        "privacy": {
            "aggregate_only": True,
            "identifiers_emitted": False,
            "queries_emitted": False,
            "token_emitted": False,
            "absolute_paths_emitted": False,
        },
    }


__all__ = [
    "MonthAcquisitionResult",
    "SeasonalAuthorizationError",
    "acquire_jpl_month",
    "run_seasonal_acquisition",
]
