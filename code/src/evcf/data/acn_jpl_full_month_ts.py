"""Authorized, resumable acquisition of the frozen JPL May 2019 ``/ts`` scope.

The complete-history metadata loader retains identifiers only in private in-memory
structures.  Public results contain aggregate provenance, while the exact carry-in
query material is persisted only below the caller-provided raw root.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .acn_api import ACNClient, ACNQuery, ACNSchemaError
from .acn_audit import parse_acn_datetime
from .acn_jpl_gate0 import (
    JPL_ANALYSIS_END,
    JPL_ANALYSIS_START,
    LocalDayWindow,
    jpl_analysis_windows,
    run_daily_chunks,
)

EXPECTED_COMPLETE_METADATA_FILE_COUNT = 42
EXPECTED_COMPLETE_METADATA_RECORD_COUNT = 33_638
EXPECTED_ANALYSIS_SESSION_COUNT = 1_644
EXPECTED_UTC_MONTH_SESSION_COUNT = 1_645
EXPECTED_CARRY_IN_SESSION_COUNT = 1

_UTC_MONTH_START = datetime(2019, 5, 1, tzinfo=timezone.utc)
_UTC_MONTH_END = datetime(2019, 6, 1, tzinfo=timezone.utc)


class FullMonthAuthorizationError(PermissionError):
    """Raised when the expensive full-month acquisition is not explicitly allowed."""


class FullMonthMetadataError(ValueError):
    """Raised when complete-history metadata cannot prove the frozen private scope."""


@dataclass(frozen=True, repr=False)
class _PrivateSession:
    """Identifier-bearing query material; never place this object in public output."""

    object_id: str = field(repr=False)
    session_id: str = field(repr=False)
    connection: datetime = field(repr=False)
    disconnect: datetime = field(repr=False)

    def __repr__(self) -> str:
        return "_PrivateSession(<redacted>)"


@dataclass(frozen=True)
class _MetadataProvenance:
    file_count: int
    valid_manifest_count: int
    source_record_count: int
    analysis_session_count: int
    utc_month_session_count: int
    carry_in_session_count: int
    inventory_digest: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "file_count": self.file_count,
            "valid_manifest_count": self.valid_manifest_count,
            "source_record_count": self.source_record_count,
            "analysis_session_count": self.analysis_session_count,
            "utc_month_session_count": self.utc_month_session_count,
            "carry_in_session_count": self.carry_in_session_count,
            "inventory_digest": self.inventory_digest,
        }


@dataclass(frozen=True, repr=False)
class _PrivateMetadataScope:
    """Validated expected pairs and carry-in record, kept private by construction."""

    analysis_sessions: tuple[_PrivateSession, ...] = field(repr=False)
    carry_in: _PrivateSession = field(repr=False)
    provenance: _MetadataProvenance

    def __repr__(self) -> str:
        return f"_PrivateMetadataScope(provenance={self.provenance!r}, identifiers=<redacted>)"


@dataclass(frozen=True)
class _CarryInTransfer:
    status: Literal["DOWNLOADED", "SKIPPED", "FAILED"]
    record_count: int
    remote_total_reported: int | None
    complete_for_query: bool


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


def _private_pair(record: Mapping[str, Any]) -> tuple[str, str] | None:
    object_id = record.get("_id")
    session_id = record.get("sessionID")
    if not isinstance(object_id, str) or not object_id:
        return None
    if not isinstance(session_id, str) or not session_id:
        return None
    return object_id, session_id


def _metadata_datetime(record: Mapping[str, Any], field_name: str) -> datetime:
    try:
        parsed = parse_acn_datetime(record.get(field_name))
    except (TypeError, ValueError) as exc:
        raise FullMonthMetadataError("complete metadata contains an invalid session time") from exc
    if parsed is None:
        raise FullMonthMetadataError("complete metadata contains a missing session time")
    return parsed


def _legacy_manifest_valid(
    manifest: object,
    *,
    record_count: int,
    sha256: str,
) -> bool:
    return (
        isinstance(manifest, Mapping)
        and isinstance(manifest.get("schema_version"), int)
        and not isinstance(manifest.get("schema_version"), bool)
        and manifest.get("schema_version") == 1
        and manifest.get("endpoint") == "sessions/jpl"
        and manifest.get("site") == "jpl"
        and manifest.get("mode") == "metadata"
        and isinstance(manifest.get("record_count"), int)
        and not isinstance(manifest.get("record_count"), bool)
        and manifest.get("record_count") == record_count
        and isinstance(manifest.get("source_total"), int)
        and not isinstance(manifest.get("source_total"), bool)
        and manifest.get("source_total") == record_count
        and manifest.get("sha256") == sha256
    )


def _add_relevant_session(
    destination: dict[tuple[str, str], _PrivateSession],
    *,
    pair: tuple[str, str] | None,
    connection: datetime,
    disconnect: datetime,
    scope_name: str,
) -> None:
    if pair is None:
        raise FullMonthMetadataError(
            f"{scope_name} metadata session is missing a private identifier pair"
        )
    if pair in destination:
        raise FullMonthMetadataError(f"{scope_name} metadata contains a duplicate session pair")
    object_id, session_id = pair
    if any(item.object_id == object_id for item in destination.values()):
        raise FullMonthMetadataError(f"{scope_name} metadata contains a duplicate object id")
    if any(item.session_id == session_id for item in destination.values()):
        raise FullMonthMetadataError(f"{scope_name} metadata contains a duplicate session id")
    destination[pair] = _PrivateSession(
        object_id=object_id,
        session_id=session_id,
        connection=connection,
        disconnect=disconnect,
    )


def _load_metadata_scope(metadata_root: str | Path) -> _PrivateMetadataScope:
    """Stream and validate the frozen 42-file complete-history metadata inventory."""

    directory = Path(metadata_root)
    files = sorted(directory.glob("*.jsonl.gz")) if directory.is_dir() else []
    if len(files) != EXPECTED_COMPLETE_METADATA_FILE_COUNT:
        raise FullMonthMetadataError(
            "full metadata requires exactly 42 complete metadata files and manifests"
        )
    expected_manifests = {path.with_name(path.name + ".manifest.json").name for path in files}
    actual_manifests = {
        path.name for path in directory.glob("*.jsonl.gz.manifest.json") if path.is_file()
    }
    if actual_manifests != expected_manifests:
        raise FullMonthMetadataError(
            "full metadata requires exactly 42 complete metadata files and manifests"
        )

    analysis_start = JPL_ANALYSIS_START.astimezone(timezone.utc)
    analysis_end = JPL_ANALYSIS_END.astimezone(timezone.utc)
    analysis: dict[tuple[str, str], _PrivateSession] = {}
    utc_month: dict[tuple[str, str], _PrivateSession] = {}
    carry_in: dict[tuple[str, str], _PrivateSession] = {}
    inventory = hashlib.sha256()
    source_record_count = 0
    valid_manifest_count = 0

    for data_path in files:
        digest = _sha256_file(data_path)
        file_record_count = 0
        try:
            with gzip.open(data_path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise FullMonthMetadataError(
                            "complete metadata JSONL record is not an object"
                        )
                    file_record_count += 1
                    connection = _metadata_datetime(item, "connectionTime")
                    disconnect = _metadata_datetime(item, "disconnectTime")
                    if disconnect <= connection:
                        raise FullMonthMetadataError(
                            "complete metadata contains non-positive session bounds"
                        )
                    pair = _private_pair(item)
                    if analysis_start <= connection < analysis_end:
                        _add_relevant_session(
                            analysis,
                            pair=pair,
                            connection=connection,
                            disconnect=disconnect,
                            scope_name="local-month",
                        )
                    if _UTC_MONTH_START <= connection < _UTC_MONTH_END:
                        _add_relevant_session(
                            utc_month,
                            pair=pair,
                            connection=connection,
                            disconnect=disconnect,
                            scope_name="UTC-month",
                        )
                    if connection < analysis_start < disconnect:
                        _add_relevant_session(
                            carry_in,
                            pair=pair,
                            connection=connection,
                            disconnect=disconnect,
                            scope_name="carry-in",
                        )
        except FullMonthMetadataError:
            raise
        except (OSError, EOFError, UnicodeError, json.JSONDecodeError) as exc:
            raise FullMonthMetadataError("complete metadata gzip JSONL validation failed") from exc

        manifest_path = data_path.with_name(data_path.name + ".manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FullMonthMetadataError("legacy manifest JSON validation failed") from exc
        if not _legacy_manifest_valid(
            manifest,
            record_count=file_record_count,
            sha256=digest,
        ):
            raise FullMonthMetadataError("legacy manifest contract validation failed")
        valid_manifest_count += 1
        source_record_count += file_record_count
        inventory.update(f"{data_path.name}\0{digest}\0{file_record_count}\n".encode())

    if source_record_count != EXPECTED_COMPLETE_METADATA_RECORD_COUNT:
        raise FullMonthMetadataError("complete metadata must contain exactly 33638 source records")
    if len(analysis) != EXPECTED_ANALYSIS_SESSION_COUNT:
        raise FullMonthMetadataError(
            "local-month membership filtering must yield exactly 1644 sessions"
        )
    if len(utc_month) != EXPECTED_UTC_MONTH_SESSION_COUNT:
        raise FullMonthMetadataError(
            "UTC-month membership filtering must yield exactly 1645 sessions"
        )
    if len(carry_in) != EXPECTED_CARRY_IN_SESSION_COUNT:
        raise FullMonthMetadataError(
            "complete-history carry-in filtering must yield exactly 1 session"
        )

    ordered_analysis = tuple(
        sorted(analysis.values(), key=lambda item: (item.session_id, item.object_id))
    )
    carry = next(iter(carry_in.values()))
    provenance = _MetadataProvenance(
        file_count=len(files),
        valid_manifest_count=valid_manifest_count,
        source_record_count=source_record_count,
        analysis_session_count=len(ordered_analysis),
        utc_month_session_count=len(utc_month),
        carry_in_session_count=len(carry_in),
        inventory_digest=inventory.hexdigest(),
    )
    return _PrivateMetadataScope(
        analysis_sessions=ordered_analysis,
        carry_in=carry,
        provenance=provenance,
    )


def _carry_in_paths(root: Path) -> tuple[Path, Path]:
    return (
        root / "timeseries" / "carry_in" / "carry_in.jsonl.gz",
        root / "manifests" / "carry_in" / "carry_in.manifest.json",
    )


def _carry_in_query(session: _PrivateSession) -> ACNQuery:
    return ACNQuery(
        site="jpl",
        start=session.connection,
        end=JPL_ANALYSIS_END,
        timeseries=True,
        session_id=session.session_id,
    )


def _read_single_gzip_record(path: Path) -> tuple[int, tuple[str, str] | None]:
    count = 0
    pair: tuple[str, str] | None = None
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ACNSchemaError("carry-in JSONL record must be an object")
            count += 1
            if count == 1:
                pair = _private_pair(item)
    return count, pair


def _validated_carry_in(
    data_path: Path,
    manifest_path: Path,
    session: _PrivateSession,
) -> _CarryInTransfer | None:
    if not data_path.is_file() or not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        record_count, pair = _read_single_gzip_record(data_path)
    except (
        OSError,
        EOFError,
        UnicodeError,
        json.JSONDecodeError,
        ACNSchemaError,
    ):
        return None
    query = _carry_in_query(session)
    expected = {
        "schema_version": "acn-jpl-full-month-carry-in/v1",
        "endpoint": query.endpoint,
        "site": "jpl",
        "_id": session.object_id,
        "sessionID": session.session_id,
        "query_condition": query.condition,
    }
    if not isinstance(manifest, dict) or any(
        manifest.get(key) != value for key, value in expected.items()
    ):
        return None
    if (
        not isinstance(manifest.get("record_count"), int)
        or isinstance(manifest.get("record_count"), bool)
        or manifest.get("record_count") != 1
        or not isinstance(manifest.get("remote_total_reported"), int)
        or isinstance(manifest.get("remote_total_reported"), bool)
        or manifest.get("remote_total_reported") != 1
        or manifest.get("complete_for_query") is not True
        or manifest.get("token_stored") is not False
    ):
        return None
    if manifest.get("sha256") != _sha256_file(data_path):
        return None
    if record_count != 1 or pair != (session.object_id, session.session_id):
        return None
    return _CarryInTransfer(
        status="SKIPPED",
        record_count=1,
        remote_total_reported=1,
        complete_for_query=True,
    )


def _remote_total(page: Mapping[str, Any]) -> int | None:
    meta = page.get("_meta")
    total = meta.get("total") if isinstance(meta, Mapping) else None
    if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
        return total
    return None


def _download_carry_in(
    client: ACNClient,
    raw_root: Path,
    session: _PrivateSession,
    downloaded_at_utc: datetime,
) -> _CarryInTransfer:
    data_path, manifest_path = _carry_in_paths(raw_root)
    validated = _validated_carry_in(data_path, manifest_path, session)
    if validated is not None:
        return validated

    query = _carry_in_query(session)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = data_path.with_suffix(data_path.suffix + ".partial")
    record_count = 0
    returned_pair: tuple[str, str] | None = None
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
                        record_count += 1
                        if record_count == 1:
                            returned_pair = _private_pair(item)
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

    remote_total_reported = next(iter(totals)) if len(totals) == 1 else None
    exact_pair = returned_pair == (session.object_id, session.session_id)
    complete = remote_total_reported == 1 and record_count == 1 and exact_pair
    manifest = {
        "schema_version": "acn-jpl-full-month-carry-in/v1",
        "dataset_id": "D0001-jpl-2019-05-full-ts",
        "source": "ACN-Data official REST API",
        "endpoint": query.endpoint,
        "site": "jpl",
        "_id": session.object_id,
        "sessionID": session.session_id,
        "query_condition": query.condition,
        "record_count": record_count,
        "remote_total_reported": remote_total_reported,
        "complete_for_query": complete,
        "downloaded_at_utc": downloaded_at_utc.astimezone(timezone.utc).isoformat(),
        "sha256": _sha256_file(data_path),
        "token_stored": False,
        "output_file": data_path.name,
    }
    _atomic_write_json(manifest_path, manifest)
    return _CarryInTransfer(
        status="DOWNLOADED" if complete else "FAILED",
        record_count=record_count,
        remote_total_reported=remote_total_reported,
        complete_for_query=complete,
    )


def _daily_public_summary(
    progress: Mapping[str, Any],
    windows: Iterable[LocalDayWindow],
) -> tuple[dict[str, Any], bool]:
    expected_days = [window.day_key for window in windows]
    expected_set = set(expected_days)

    def clean_days(field_name: str) -> list[str]:
        value = progress.get(field_name)
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item in expected_set]

    completed = clean_days("completed_days")
    pending = clean_days("pending_days")
    failed = clean_days("failed_days")
    retry_count = progress.get("retry_count", 0)
    if not isinstance(retry_count, int) or isinstance(retry_count, bool) or retry_count < 0:
        retry_count = 0
    complete = (
        completed == expected_days
        and len(completed) == len(set(completed))
        and not pending
        and not failed
    )
    return (
        {
            "requested_days": len(expected_days),
            "completed_days": len(set(completed)),
            "pending_days": len(set(pending)),
            "failed_days": len(set(failed)),
            "retry_count": retry_count,
            "serial": True,
        },
        complete,
    )


def _not_run_carry_in() -> dict[str, Any]:
    return {
        "status": "NOT_RUN",
        "record_count": 0,
        "remote_total_reported": None,
        "complete_for_query": False,
    }


def _carry_public_summary(transfer: object) -> dict[str, Any]:
    def read(field_name: str) -> Any:
        if isinstance(transfer, Mapping):
            return transfer.get(field_name)
        return getattr(transfer, field_name, None)

    status = read("status")
    record_count = read("record_count")
    remote_total = read("remote_total_reported")
    complete = read("complete_for_query")
    status_valid = status in {"DOWNLOADED", "SKIPPED"}
    count_safe = (
        isinstance(record_count, int) and not isinstance(record_count, bool) and record_count >= 0
    )
    total_safe = (
        isinstance(remote_total, int) and not isinstance(remote_total, bool) and remote_total >= 0
    )
    safe_complete = (
        status_valid
        and count_safe
        and record_count == 1
        and total_safe
        and remote_total == 1
        and complete is True
    )
    return {
        "status": status if safe_complete else "FAILED",
        "record_count": record_count if count_safe else 0,
        "remote_total_reported": remote_total if total_safe else None,
        "complete_for_query": safe_complete,
    }


def _public_result(
    *,
    scope: _PrivateMetadataScope,
    daily: Mapping[str, Any],
    carry_in: Mapping[str, Any],
    complete: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "acn-jpl-full-month-ts-run/v1",
        "status": "COMPLETE" if complete else "INCOMPLETE",
        "metadata": scope.provenance.public_dict(),
        "daily": dict(daily),
        "carry_in": dict(carry_in),
        "privacy": {
            "aggregate_only": True,
            "identifiers_emitted": False,
            "token_emitted": False,
            "absolute_paths_emitted": False,
        },
    }


def run_full_month_timeseries(
    *,
    authorized: bool,
    metadata_root: str | Path,
    raw_root: str | Path,
    client_factory: Callable[[], ACNClient],
    daily_runner: Callable[..., dict[str, Any]] = run_daily_chunks,
    carry_downloader: Callable[[ACNClient, Path, _PrivateSession, datetime], Any] = (
        _download_carry_in
    ),
    downloaded_at_utc: datetime | None = None,
) -> dict[str, Any]:
    """Acquire or resume the frozen 31-day ``/ts`` scope plus exact carry-in.

    Literal ``True`` authorization and the frozen complete-metadata counts are
    required before constructing the client or creating any raw-state file.
    """

    if authorized is not True:
        raise FullMonthAuthorizationError(
            "full-month /ts acquisition requires explicit authorization"
        )

    scope = _load_metadata_scope(metadata_root)
    timestamp = downloaded_at_utc or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("downloaded_at_utc must be timezone-aware")

    client = client_factory()
    root = Path(raw_root)
    windows = list(jpl_analysis_windows())
    progress = daily_runner(
        client,
        root,
        windows,
        endpoint="timeseries",
    )
    daily, daily_complete = _daily_public_summary(progress, windows)
    if not daily_complete:
        return _public_result(
            scope=scope,
            daily=daily,
            carry_in=_not_run_carry_in(),
            complete=False,
        )

    try:
        carry_transfer = carry_downloader(client, root, scope.carry_in, timestamp)
    except Exception:  # noqa: BLE001 - never expose exception text that may hold secrets
        carry_public = {
            "status": "FAILED",
            "record_count": 0,
            "remote_total_reported": None,
            "complete_for_query": False,
        }
    else:
        carry_public = _carry_public_summary(carry_transfer)
    return _public_result(
        scope=scope,
        daily=daily,
        carry_in=carry_public,
        complete=carry_public["complete_for_query"] is True,
    )
