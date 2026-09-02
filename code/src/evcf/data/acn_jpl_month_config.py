"""Immutable local-month contracts for the JPL seasonal replication.

Scope classification is deliberately separate from frozen-source verification.
``summarize_complete_metadata`` is a deterministic in-memory classifier and does
not claim that its input came from the published complete metadata inventory.
Production callers must use ``load_verified_complete_metadata`` so the legacy
files, manifests, record count, and source inventory digest are all revalidated.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .acn_audit import parse_acn_datetime
from .acn_jpl_gate0 import JPL_TIMEZONE, LocalDayWindow, iter_local_day_windows

SEASONAL_MONTHS = ("2019-02", "2019-08", "2019-11")

EXPECTED_COMPLETE_METADATA_FILE_COUNT = 42
EXPECTED_COMPLETE_METADATA_RECORD_COUNT = 33_638
EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256 = (
    "bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a"
)
# Compatibility with the name used by the original May full-month loader.
EXPECTED_COMPLETE_METADATA_INVENTORY_DIGEST = EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256

SOURCE_INVENTORY_DIGEST_ALGORITHM = "sha256(sorted filename\\0raw_sha256\\0record_count\\n)"
CANONICAL_RECORD_INVENTORY_ALGORITHM = "sha256(sorted canonical-json(record)\\n)"

_GRID_SECONDS = 900
_SCHEDULED_ISSUE_EDGE_BINS = 111
_APPROVED_MONTHS = ("2019-02", "2019-05", "2019-08", "2019-11")
_VERIFIED_SOURCE_EVIDENCE_SEAL = object()


class CompleteMetadataError(ValueError):
    """Raised when complete metadata cannot prove a closed private scope."""


@dataclass(frozen=True)
class JPLMonthConfig:
    """A local calendar month mapped onto a continuous physical UTC grid."""

    month: str
    timezone_name: str
    local_start: datetime
    local_end: datetime
    utc_start: datetime
    utc_end: datetime
    day_count: int
    day_windows: tuple[LocalDayWindow, ...]
    expected_bins: int
    expected_scheduled_issue_times: int
    grid_policy: str = "continuous_physical_utc"
    tiers: tuple[str, ...] = ("M1", "M2", "M3")


@dataclass(frozen=True)
class CompleteMetadataSourceEvidence:
    """Aggregate proof recomputed from the complete metadata files on disk."""

    file_count: int
    valid_manifest_count: int
    record_count: int
    source_inventory_sha256: str
    inventory_algorithm: str = SOURCE_INVENTORY_DIGEST_ALGORITHM
    _verification_seal: object | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )


@dataclass(frozen=True)
class CompleteMetadataScope:
    """Private record selections plus privacy-safe counts and inventory evidence."""

    local_month_records: tuple[Mapping[str, Any], ...] = field(repr=False)
    carry_in_records: tuple[Mapping[str, Any], ...] = field(repr=False)
    local_month_session_count: int
    utc_month_session_count: int
    left_boundary_count: int
    right_boundary_count: int
    carry_in_session_count: int
    record_inventory_sha256: str
    source_evidence: CompleteMetadataSourceEvidence | None = None

    @property
    def inventory_sha256(self) -> str:
        """Compatibility alias for the canonical record-content hash."""

        return self.record_inventory_sha256

    @property
    def source_inventory_verified(self) -> bool:
        """Whether the source evidence matches the one frozen published inventory."""

        evidence = self.source_evidence
        return (
            evidence is not None
            and evidence._verification_seal is _VERIFIED_SOURCE_EVIDENCE_SEAL
            and evidence.file_count == EXPECTED_COMPLETE_METADATA_FILE_COUNT
            and evidence.valid_manifest_count == EXPECTED_COMPLETE_METADATA_FILE_COUNT
            and evidence.record_count == EXPECTED_COMPLETE_METADATA_RECORD_COUNT
            and evidence.source_inventory_sha256 == EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256
            and evidence.inventory_algorithm == SOURCE_INVENTORY_DIGEST_ALGORITHM
        )


def _parse_month(month: str) -> tuple[int, int]:
    if (
        not isinstance(month, str)
        or len(month) != 7
        or month[4] != "-"
        or not month[:4].isdigit()
        or not month[5:].isdigit()
    ):
        raise ValueError("month must use YYYY-MM format")
    year = int(month[:4])
    month_number = int(month[5:])
    if not 1 <= month_number <= 12:
        raise ValueError("month must use YYYY-MM format")
    return year, month_number


def _following_month(year: int, month_number: int) -> tuple[int, int]:
    if month_number == 12:
        return year + 1, 1
    return year, month_number + 1


def _make_month_config(month: str) -> JPLMonthConfig:
    year, month_number = _parse_month(month)
    next_year, next_month = _following_month(year, month_number)
    zone = ZoneInfo(JPL_TIMEZONE)
    start_date = date(year, month_number, 1)
    end_date = date(next_year, next_month, 1)
    local_start = datetime.combine(start_date, time.min, zone)
    local_end = datetime.combine(end_date, time.min, zone)
    utc_start = local_start.astimezone(timezone.utc)
    utc_end = local_end.astimezone(timezone.utc)

    windows = tuple(
        iter_local_day_windows(
            start_date,
            end_date,
            timezone_name=JPL_TIMEZONE,
        )
    )

    duration_seconds = int((utc_end - utc_start).total_seconds())
    if duration_seconds % _GRID_SECONDS:
        raise ValueError("JPL month does not align to the 900-second physical grid")
    expected_bins = duration_seconds // _GRID_SECONDS
    return JPLMonthConfig(
        month=month,
        timezone_name=JPL_TIMEZONE,
        local_start=local_start,
        local_end=local_end,
        utc_start=utc_start,
        utc_end=utc_end,
        day_count=len(windows),
        day_windows=windows,
        expected_bins=expected_bins,
        expected_scheduled_issue_times=expected_bins - _SCHEDULED_ISSUE_EDGE_BINS,
    )


FEB_2019 = _make_month_config("2019-02")
MAY_2019 = _make_month_config("2019-05")
AUG_2019 = _make_month_config("2019-08")
NOV_2019 = _make_month_config("2019-11")

_MONTH_CONFIGS = {config.month: config for config in (FEB_2019, MAY_2019, AUG_2019, NOV_2019)}


def jpl_month_config(month: str) -> JPLMonthConfig:
    """Return a frozen approved month, including May for legacy compatibility."""

    _parse_month(month)
    try:
        return _MONTH_CONFIGS[month]
    except KeyError as exc:
        approved = ", ".join(_APPROVED_MONTHS)
        raise ValueError(f"month is not an approved JPL month: {approved}") from exc


def _metadata_datetime(record: Mapping[str, Any], field_name: str) -> datetime:
    try:
        parsed = parse_acn_datetime(record.get(field_name))
    except (TypeError, ValueError) as exc:
        raise CompleteMetadataError(f"complete metadata contains an invalid {field_name}") from exc
    if parsed is None:
        raise CompleteMetadataError(f"complete metadata contains a missing {field_name}")
    return parsed


def _canonical_json_default(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise TypeError("canonical inventory cannot encode a naive datetime")
        return {"__datetime_utc__": value.astimezone(timezone.utc).isoformat()}
    raise TypeError(f"canonical inventory cannot encode {type(value).__name__}")


def _canonical_record_inventory_sha256(records: Iterable[Mapping[str, Any]]) -> str:
    encoded_records = sorted(
        json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=_canonical_json_default,
        ).encode("utf-8")
        for record in records
    )
    digest = hashlib.sha256()
    for encoded in encoded_records:
        digest.update(encoded)
        digest.update(b"\n")
    return digest.hexdigest()


def _utc_calendar_bounds(config: JPLMonthConfig) -> tuple[datetime, datetime]:
    year, month_number = _parse_month(config.month)
    next_year, next_month = _following_month(year, month_number)
    return (
        datetime(year, month_number, 1, tzinfo=timezone.utc),
        datetime(next_year, next_month, 1, tzinfo=timezone.utc),
    )


def summarize_complete_metadata(
    records: Iterable[Mapping[str, Any]],
    config: JPLMonthConfig,
) -> CompleteMetadataScope:
    """Classify complete metadata deterministically without asserting source trust.

    Identifier completeness and uniqueness are validated across the entire input,
    not only the records selected into the target month or carry-in scope.
    """

    materialized = tuple(records)
    object_ids: set[str] = set()
    session_ids: set[str] = set()
    validated: list[tuple[Mapping[str, Any], str, str, datetime, datetime]] = []
    for record in materialized:
        if not isinstance(record, Mapping):
            raise CompleteMetadataError("complete metadata record is not a mapping")
        object_id = record.get("_id")
        session_id = record.get("sessionID")
        if not isinstance(object_id, str) or not object_id:
            raise CompleteMetadataError("complete metadata contains a missing or invalid _id")
        if not isinstance(session_id, str) or not session_id:
            raise CompleteMetadataError("complete metadata contains a missing or invalid sessionID")
        if object_id in object_ids:
            raise CompleteMetadataError("complete metadata contains a duplicate _id")
        if session_id in session_ids:
            raise CompleteMetadataError("complete metadata contains a duplicate sessionID")
        object_ids.add(object_id)
        session_ids.add(session_id)
        connection = _metadata_datetime(record, "connectionTime")
        disconnect = _metadata_datetime(record, "disconnectTime")
        if disconnect <= connection:
            raise CompleteMetadataError("complete metadata contains non-positive session bounds")
        validated.append((record, object_id, session_id, connection, disconnect))

    utc_month_start, utc_month_end = _utc_calendar_bounds(config)
    local_records: list[tuple[Mapping[str, Any], str, str]] = []
    carry_records: list[tuple[Mapping[str, Any], str, str]] = []
    local_keys: set[str] = set()
    utc_keys: set[str] = set()
    for record, object_id, session_id, connection, disconnect in validated:
        if config.utc_start <= connection < config.utc_end:
            local_records.append((record, session_id, object_id))
            local_keys.add(session_id)
        if utc_month_start <= connection < utc_month_end:
            utc_keys.add(session_id)
        if connection < config.utc_start < disconnect:
            carry_records.append((record, session_id, object_id))

    ordered_local = tuple(
        record for record, _, _ in sorted(local_records, key=lambda item: (item[1], item[2]))
    )
    ordered_carry = tuple(
        record for record, _, _ in sorted(carry_records, key=lambda item: (item[1], item[2]))
    )
    return CompleteMetadataScope(
        local_month_records=ordered_local,
        carry_in_records=ordered_carry,
        local_month_session_count=len(local_keys),
        utc_month_session_count=len(utc_keys),
        left_boundary_count=len(utc_keys - local_keys),
        right_boundary_count=len(local_keys - utc_keys),
        carry_in_session_count=len(ordered_carry),
        record_inventory_sha256=_canonical_record_inventory_sha256(materialized),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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


def load_verified_complete_metadata(
    metadata_root: str | Path,
    config: JPLMonthConfig,
) -> CompleteMetadataScope:
    """Load only the frozen 42-file complete source and return a verified scope."""

    directory = Path(metadata_root)
    files = sorted(directory.glob("*.jsonl.gz")) if directory.is_dir() else []
    if len(files) != EXPECTED_COMPLETE_METADATA_FILE_COUNT:
        raise CompleteMetadataError(
            "full metadata requires exactly 42 complete metadata files and manifests"
        )
    expected_manifests = {path.with_name(path.name + ".manifest.json").name for path in files}
    actual_manifests = {
        path.name for path in directory.glob("*.jsonl.gz.manifest.json") if path.is_file()
    }
    if actual_manifests != expected_manifests:
        raise CompleteMetadataError(
            "full metadata requires exactly 42 complete metadata files and manifests"
        )

    inventory = hashlib.sha256()
    records: list[Mapping[str, Any]] = []
    valid_manifest_count = 0
    for data_path in files:
        raw_sha256 = _sha256_file(data_path)
        file_records: list[Mapping[str, Any]] = []
        try:
            with gzip.open(data_path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if not isinstance(item, Mapping):
                        raise CompleteMetadataError(
                            "complete metadata JSONL record is not an object"
                        )
                    file_records.append(item)
        except CompleteMetadataError:
            raise
        except (OSError, EOFError, UnicodeError, json.JSONDecodeError) as exc:
            raise CompleteMetadataError("complete metadata gzip JSONL validation failed") from exc

        manifest_path = data_path.with_name(data_path.name + ".manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CompleteMetadataError("complete metadata manifest validation failed") from exc
        if not _legacy_manifest_valid(
            manifest,
            record_count=len(file_records),
            sha256=raw_sha256,
        ):
            raise CompleteMetadataError("complete metadata manifest contract is invalid")
        valid_manifest_count += 1
        records.extend(file_records)
        inventory.update(f"{data_path.name}\0{raw_sha256}\0{len(file_records)}\n".encode())

    evidence = CompleteMetadataSourceEvidence(
        file_count=len(files),
        valid_manifest_count=valid_manifest_count,
        record_count=len(records),
        source_inventory_sha256=inventory.hexdigest(),
    )
    if evidence.record_count != EXPECTED_COMPLETE_METADATA_RECORD_COUNT:
        raise CompleteMetadataError("complete metadata must contain exactly 33638 source records")
    if evidence.source_inventory_sha256 != EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256:
        raise CompleteMetadataError(
            "complete metadata inventory digest does not match frozen input"
        )
    object.__setattr__(
        evidence,
        "_verification_seal",
        _VERIFIED_SOURCE_EVIDENCE_SEAL,
    )

    scope = summarize_complete_metadata(records, config)
    verified = replace(scope, source_evidence=evidence)
    if not verified.source_inventory_verified:
        raise CompleteMetadataError("complete metadata source evidence is not verified")
    return verified
