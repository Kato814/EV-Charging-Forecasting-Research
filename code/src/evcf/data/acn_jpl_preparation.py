"""Deterministic, fail-closed contracts for JPL Gate 1 data preparation."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml

from .acn_api import ACNQuery
from .acn_audit import parse_acn_datetime
from .acn_jpl_full_month_ts import FULL_MONTH_DATASET_ID
from .acn_jpl_gate0 import (
    ACN_OFFICIAL_SOURCE,
    JPL_ANALYSIS_END,
    JPL_ANALYSIS_START,
    JPL_TIMEZONE,
    chunk_paths,
    is_valid_utc_timestamp,
    jpl_analysis_windows,
    validate_chunk,
)

INVENTORY_DIGEST_ALGORITHM = (
    "sha256(ordinal-sorted UTF-8 relative_path<TAB>size<TAB>file_sha256<LF>; final LF)"
)
DEFAULT_RAW_ROOT = Path("data/raw/acn/jpl/gate0/2019-05-full-ts")
DEFAULT_INTERIM_ROOT = Path("data/interim/acn/jpl/2019-05")
DEFAULT_PROCESSED_ROOT = Path("data/processed/acn/jpl/2019-05")
DEFAULT_PUBLIC_ROOT = Path("outputs/acn_gate1_prep/jpl_2019-05")
ANALYSIS_START_LOCAL = JPL_ANALYSIS_START
ANALYSIS_END_LOCAL = JPL_ANALYSIS_END
ANALYSIS_START_UTC = JPL_ANALYSIS_START.astimezone(timezone.utc)
ANALYSIS_END_UTC = JPL_ANALYSIS_END.astimezone(timezone.utc)

INVENTORY_SCHEMA_VERSION = "acn-jpl-raw-inventory/v1"
DAILY_MANIFEST_SCHEMA_VERSION = "acn-jpl-daily-chunk/v1"
CARRY_MANIFEST_SCHEMA_VERSION = "acn-jpl-full-month-carry-in/v1"
PREPARATION_SCHEMA_VERSION = "acn-jpl-gate1-preparation/v1"

PUBLIC_ARTIFACT_NAMES = (
    "cleaning_qa.json",
    "cleaning_sensitivity.json",
    "boundary_current_audit.json",
    "power_semantics_audit.json",
    "power_semantics_decision.md",
    "station_15min_qa.json",
    "issue_snapshot_qa.json",
    "leakage_audit.json",
    "feature_whitelist.yaml",
    "feature_blacklist.yaml",
    "data_snapshot_manifest.json",
    "run_manifest.json",
    "SHA256SUMS",
)

EXPECTED_RAW_INVENTORY_SHA256 = "63e3f88fcbd4c0d8b87392267cdbe5ad383d89468f10ac3de5e181837b18dcac"


class RawSnapshotError(ValueError):
    """Raised when the frozen raw snapshot violates its closed contract."""


class RawSnapshotChangedError(RawSnapshotError):
    """Raised when a post-run raw inventory differs from its pre-run snapshot."""


class UnsafeWriteTargetError(PermissionError):
    """Raised before a local or public writer can target the raw tree."""


class PublicPrivacyError(ValueError):
    """Raised when a proposed public release violates the closed privacy contract."""


@dataclass(frozen=True)
class RawSnapshotContract:
    """Closed aggregate expectations for the frozen JPL raw snapshot."""

    file_count: int = 67
    manifest_count: int = 32
    day_count: int = 31
    carry_count: int = 1
    day_record_count: int = 1644
    carry_record_count: int = 1
    total_record_count: int = 1645
    total_bytes: int | None = 61_625_542
    inventory_sha256: str | None = EXPECTED_RAW_INVENTORY_SHA256


FROZEN_RAW_CONTRACT = RawSnapshotContract()


@dataclass(frozen=True)
class InventoryEntry:
    """One canonical, root-relative file inventory entry."""

    relative_path: str
    size: int
    sha256: str

    def canonical_bytes(self) -> bytes:
        return f"{self.relative_path}\t{self.size}\t{self.sha256}\n".encode()


@dataclass(frozen=True)
class InventorySnapshot:
    """Content-addressed inventory that contains no absolute path."""

    entries: tuple[InventoryEntry, ...]
    digest: str
    total_bytes: int
    algorithm: str = INVENTORY_DIGEST_ALGORITHM

    @property
    def file_count(self) -> int:
        return len(self.entries)


@dataclass(frozen=True)
class RawSnapshotValidation:
    """Aggregate-only evidence returned by complete raw validation."""

    inventory: InventorySnapshot
    manifest_count: int
    day_count: int
    carry_count: int
    day_record_count: int
    carry_record_count: int
    total_record_count: int


@dataclass(frozen=True, repr=False)
class RawRecord:
    """One raw object with deterministic, identifier-free ordering metadata."""

    ordinal: int
    chunk_kind: Literal["carry_in", "day"]
    local_date: str | None
    chunk_index: int
    payload: Mapping[str, Any] = field(repr=False)

    def __repr__(self) -> str:
        return (
            "RawRecord("
            f"ordinal={self.ordinal}, chunk_kind={self.chunk_kind!r}, "
            f"local_date={self.local_date!r}, chunk_index={self.chunk_index}, "
            "payload=<redacted>)"
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_inventory(root: str | Path) -> InventorySnapshot:
    """Hash every regular file below ``root`` using the closed canonical framing."""

    base = Path(root)
    if not base.is_dir():
        raise RawSnapshotError("inventory root is not a directory")

    paths: list[tuple[str, Path]] = []
    for path in base.rglob("*"):
        if path.is_symlink():
            raise RawSnapshotError("inventory root contains a symbolic link")
        if not path.is_file():
            continue
        relative_path = path.relative_to(base).as_posix()
        if "\t" in relative_path or "\r" in relative_path or "\n" in relative_path:
            raise RawSnapshotError("inventory path cannot be represented canonically")
        paths.append((relative_path, path))

    entries = tuple(
        InventoryEntry(relative_path, path.stat().st_size, _sha256_file(path))
        for relative_path, path in sorted(paths, key=lambda item: item[0])
    )
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry.canonical_bytes())
    return InventorySnapshot(
        entries=entries,
        digest=digest.hexdigest(),
        total_bytes=sum(entry.size for entry in entries),
    )


def assert_raw_snapshot_unchanged(
    before: InventorySnapshot,
    after: InventorySnapshot,
) -> None:
    """Fail closed unless every canonical raw inventory entry remains identical."""

    if before != after:
        raise RawSnapshotChangedError("raw snapshot changed between before and after inventories")


def guard_write_target(path: str | Path, *, raw_root: str | Path) -> Path:
    """Return a resolved write target only when it is outside the raw root."""

    target = Path(path).resolve(strict=False)
    protected = Path(raw_root).resolve(strict=False)
    if target == protected or protected in target.parents:
        raise UnsafeWriteTargetError("write target is inside the protected raw root")
    return target


def atomic_write_bytes(
    path: str | Path,
    data: bytes,
    *,
    raw_root: str | Path,
) -> None:
    """Atomically replace one non-raw file and clean up an interrupted temporary."""

    destination = guard_write_target(path, raw_root=raw_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.partial-",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_text(
    path: str | Path,
    text: str,
    *,
    raw_root: str | Path,
) -> None:
    """Encode UTF-8 text and atomically replace one non-raw file."""

    atomic_write_bytes(path, text.encode("utf-8"), raw_root=raw_root)


def atomic_write_json(
    path: str | Path,
    payload: Mapping[str, Any],
    *,
    raw_root: str | Path,
) -> None:
    """Serialize deterministic finite JSON and atomically replace one non-raw file."""

    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=True,
    )
    atomic_write_text(path, rendered + "\n", raw_root=raw_root)


_FORBIDDEN_PUBLIC_KEYS = {
    "_id",
    "sessionid",
    "userid",
    "querycondition",
    "rawroot",
    "interimroot",
    "processedroot",
    "outputroot",
    "hostname",
    "host",
    "username",
    "computername",
    "userprofile",
    "timestamps",
    "values",
}
_SAFE_FALSE_DECLARATION_KEYS = {
    "tokenemitted",
    "identifiersemitted",
    "privatevaluesemitted",
    "hostusernamesemitted",
    "absolutepathsemitted",
}
_CREDENTIAL_KEY_PARTS = ("token", "password", "secret", "apikey", "authorization")
_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?:\b[a-z]:[\\/]|\\\\[^\s\"'<>|]+|(?<![:/a-z0-9])/(?!/)(?:[^\s\"'<>|]*)?)",
    re.IGNORECASE | re.MULTILINE,
)
_PRIVATE_SENTINEL_PATTERN = re.compile(
    r"\bprivate[-_](?:object|session|user|identifier|id)(?:[-_][a-z0-9.-]+)+\b",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bbearer\s+[a-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|github_pat)[-_][a-z0-9_-]{8,}\b", re.IGNORECASE),
    re.compile(r"(?:access[_-]?token|api[_-]?key|password|secret)\s*[:=]\s*\S+", re.IGNORECASE),
)
_STRUCTURED_TEXT_FIELD_PATTERN = re.compile(
    r"^\s*(?:[-*]\s*)?[`\"']?([a-z_][a-z0-9_-]*)[`\"']?\s*[:=]\s*(.*?)\s*$",
    re.IGNORECASE,
)
_MARKDOWN_TABLE_DIVIDER = re.compile(r"^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")
_MAX_PUBLIC_ARTIFACT_BYTES = 2 * 1024 * 1024
_MAX_PUBLIC_COLLECTION_ITEMS = 1_000


def _normalized_public_key(key: object) -> str:
    return re.sub(r"[^a-z0-9_]", "", str(key).lower())


def _environment_private_values() -> tuple[str, ...]:
    values = {
        value.strip()
        for name in ("COMPUTERNAME", "HOSTNAME", "USERNAME", "USER", "USERPROFILE")
        if (value := os.environ.get(name)) and len(value.strip()) >= 4
    }
    return tuple(sorted(values))


def _validate_public_text(text: str, sensitive_values: Iterable[str]) -> None:
    if _ABSOLUTE_PATH_PATTERN.search(text):
        raise PublicPrivacyError("public artifact contains an absolute local path")
    if _PRIVATE_SENTINEL_PATTERN.search(text):
        raise PublicPrivacyError("public artifact contains an identifier sentinel")
    if any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS):
        raise PublicPrivacyError("public artifact contains credential material")
    lowered = text.casefold()
    for value in (*_environment_private_values(), *sensitive_values):
        candidate = str(value).strip()
        if candidate and candidate.casefold() in lowered:
            raise PublicPrivacyError("public artifact contains a sensitive host, user, or value")


def _validate_public_key(key: object, value: Any = None, *, value_known: bool = False) -> None:
    normalized = _normalized_public_key(key)
    compact = normalized.replace("_", "")
    if compact in _SAFE_FALSE_DECLARATION_KEYS:
        if value_known and value is not False and str(value).strip().casefold() != "false":
            raise PublicPrivacyError("public safety declaration must remain false")
        return
    if (
        normalized in _FORBIDDEN_PUBLIC_KEYS
        or compact in _FORBIDDEN_PUBLIC_KEYS
        or any(part in compact for part in _CREDENTIAL_KEY_PARTS)
    ):
        raise PublicPrivacyError("public artifact contains a forbidden private field")


def _validate_public_value(value: Any, sensitive_values: tuple[str, ...]) -> None:
    if isinstance(value, Mapping):
        if len(value) > _MAX_PUBLIC_COLLECTION_ITEMS:
            raise PublicPrivacyError("public artifact mapping is unexpectedly large")
        for key, nested in value.items():
            _validate_public_key(key, nested, value_known=True)
            _validate_public_value(nested, sensitive_values)
    elif isinstance(value, (list, tuple)):
        if len(value) > _MAX_PUBLIC_COLLECTION_ITEMS:
            raise PublicPrivacyError("public artifact collection is unexpectedly large")
        for nested in value:
            _validate_public_value(nested, sensitive_values)
    elif isinstance(value, str):
        _validate_public_text(value, sensitive_values)


def _validate_public_structured_text(text: str) -> None:
    lines = text.splitlines()
    for line in lines:
        match = _STRUCTURED_TEXT_FIELD_PATTERN.match(line)
        if match:
            _validate_public_key(match.group(1), match.group(2), value_known=True)
    for index, line in enumerate(lines[:-1]):
        if "|" not in line or not _MARKDOWN_TABLE_DIVIDER.match(lines[index + 1]):
            continue
        for key in (cell.strip() for cell in line.strip().strip("|").split("|")):
            _validate_public_key(key)


def validate_public_artifacts(
    contents: Mapping[str, bytes | str],
    *,
    sensitive_values: Iterable[str] = (),
) -> None:
    """Validate exact public filenames and reject private material in every payload."""

    expected = PUBLIC_ARTIFACT_NAMES
    if len(expected) != len(set(expected)) or set(contents) != set(expected):
        raise PublicPrivacyError("closed public artifact set contains unexpected files")
    if any(Path(name).name != name or not name for name in contents):
        raise PublicPrivacyError("closed public artifact set contains an unsafe filename")

    sensitive = tuple(str(value) for value in sensitive_values if str(value))
    for name, raw_content in contents.items():
        if isinstance(raw_content, bytes):
            if len(raw_content) > _MAX_PUBLIC_ARTIFACT_BYTES:
                raise PublicPrivacyError("public artifact exceeds the aggregate-only size limit")
            try:
                text = raw_content.decode("utf-8")
            except UnicodeError as exc:
                raise PublicPrivacyError("public artifact is not valid UTF-8 text") from exc
        elif isinstance(raw_content, str):
            if len(raw_content.encode("utf-8")) > _MAX_PUBLIC_ARTIFACT_BYTES:
                raise PublicPrivacyError("public artifact exceeds the aggregate-only size limit")
            text = raw_content
        else:
            raise PublicPrivacyError("public artifact content must be bytes or text")
        _validate_public_text(text, sensitive)
        lower_name = name.lower()
        if lower_name.endswith(".json"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise PublicPrivacyError("public JSON artifact is invalid") from exc
            _validate_public_value(payload, sensitive)
        elif lower_name.endswith((".yaml", ".yml")):
            try:
                payload = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                raise PublicPrivacyError("public YAML artifact is invalid") from exc
            _validate_public_value(payload, sensitive)
        elif lower_name.endswith(".md"):
            _validate_public_structured_text(text)


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _read_json_object(path: Path, *, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RawSnapshotError(f"{description} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise RawSnapshotError(f"{description} root is not an object")
    return payload


def _iter_gzip_objects(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise RawSnapshotError("gzip JSONL record root is not an object")
                yield payload
    except RawSnapshotError:
        raise
    except (OSError, EOFError, UnicodeError, json.JSONDecodeError) as exc:
        raise RawSnapshotError("data file is not valid gzip JSONL") from exc


def _validate_carry_chunk(raw_root: Path) -> int:
    data_path = raw_root / "timeseries" / "carry_in" / "carry_in.jsonl.gz"
    manifest_path = raw_root / "manifests" / "carry_in" / "carry_in.manifest.json"
    if not data_path.is_file() or not manifest_path.is_file():
        raise RawSnapshotError("carry-in data or manifest is missing")

    manifest = _read_json_object(manifest_path, description="carry-in manifest")
    records = list(_iter_gzip_objects(data_path))
    if len(records) != 1:
        raise RawSnapshotError("carry-in must contain exactly one record")
    record = records[0]
    object_id = record.get("_id")
    session_id = record.get("sessionID")
    if not isinstance(object_id, str) or not object_id:
        raise RawSnapshotError("carry-in record has an invalid private identifier")
    if not isinstance(session_id, str) or not session_id:
        raise RawSnapshotError("carry-in record has an invalid private identifier")
    try:
        connection = parse_acn_datetime(record.get("connectionTime"))
        disconnect = parse_acn_datetime(record.get("disconnectTime"))
    except (TypeError, ValueError) as exc:
        raise RawSnapshotError("carry-in record has an invalid session boundary") from exc
    if connection is None or disconnect is None or not connection < ANALYSIS_START_UTC < disconnect:
        raise RawSnapshotError("carry-in record does not cross the analysis boundary")

    query = ACNQuery(
        site="jpl",
        start=connection,
        end=ANALYSIS_START_LOCAL,
        timeseries=True,
        session_id=session_id,
    )
    local_zone = ZoneInfo(JPL_TIMEZONE)
    expected_context = {
        "schema_version": CARRY_MANIFEST_SCHEMA_VERSION,
        "dataset_id": FULL_MONTH_DATASET_ID,
        "source": ACN_OFFICIAL_SOURCE,
        "endpoint": query.endpoint,
        "site": "jpl",
        "timezone": JPL_TIMEZONE,
        "local_start_inclusive": query.start_utc.astimezone(local_zone).isoformat(),
        "local_end_exclusive": query.end_utc.astimezone(local_zone).isoformat(),
        "utc_start_inclusive": query.start_utc.isoformat(),
        "utc_end_exclusive": query.end_utc.isoformat(),
        "_id": object_id,
        "sessionID": session_id,
        "query_condition": query.condition,
        "output_file": data_path.name,
    }
    if any(manifest.get(key) != value for key, value in expected_context.items()):
        raise RawSnapshotError("carry-in manifest contract does not match the record query")
    manifest_count = manifest.get("record_count")
    remote_total = manifest.get("remote_total_reported")
    if not _is_nonnegative_int(manifest_count) or manifest_count != 1:
        raise RawSnapshotError("carry-in manifest record count does not match")
    if not _is_nonnegative_int(remote_total) or remote_total != 1:
        raise RawSnapshotError("carry-in remote total does not match")
    if manifest.get("complete_for_query") is not True:
        raise RawSnapshotError("carry-in manifest is not complete for its query")
    if manifest.get("token_stored") is not False:
        raise RawSnapshotError("carry-in manifest contains an unsafe credential declaration")
    if not is_valid_utc_timestamp(manifest.get("downloaded_at_utc")):
        raise RawSnapshotError("carry-in manifest download timestamp is invalid")
    if manifest.get("sha256") != _sha256_file(data_path):
        raise RawSnapshotError("carry-in data hash does not match its manifest")
    return len(records)


def _assert_contract_value(name: str, observed: int | str, expected: int | str | None) -> None:
    if expected is not None and observed != expected:
        raise RawSnapshotError(f"raw snapshot {name} does not match the frozen contract")


def validate_raw_snapshot(
    raw_root: str | Path,
    *,
    contract: RawSnapshotContract = FROZEN_RAW_CONTRACT,
) -> RawSnapshotValidation:
    """Validate the complete raw snapshot before any downstream record is released."""

    root = Path(raw_root)
    inventory = canonical_inventory(root)
    _assert_contract_value("file count", inventory.file_count, contract.file_count)
    _assert_contract_value("byte count", inventory.total_bytes, contract.total_bytes)
    _assert_contract_value("inventory digest", inventory.digest, contract.inventory_sha256)

    manifest_count = sum(1 for path in (root / "manifests").rglob("*.json") if path.is_file())
    _assert_contract_value("manifest count", manifest_count, contract.manifest_count)
    gzip_count = sum(1 for path in (root / "timeseries").rglob("*.jsonl.gz") if path.is_file())
    _assert_contract_value("gzip count", gzip_count, contract.day_count + contract.carry_count)

    day_record_count = 0
    windows = tuple(jpl_analysis_windows())
    _assert_contract_value("day count", len(windows), contract.day_count)
    for window in windows:
        data_path, manifest_path = chunk_paths(root, "timeseries", window)
        result = validate_chunk(
            data_path,
            manifest_path,
            window=window,
            endpoint="timeseries",
        )
        if not result.valid:
            raise RawSnapshotError(f"daily manifest/data validation failed: {result.reason}")
        day_record_count += result.record_count

    carry_record_count = _validate_carry_chunk(root)
    total_record_count = day_record_count + carry_record_count
    _assert_contract_value("day record count", day_record_count, contract.day_record_count)
    _assert_contract_value("carry record count", carry_record_count, contract.carry_record_count)
    _assert_contract_value("object total", total_record_count, contract.total_record_count)
    return RawSnapshotValidation(
        inventory=inventory,
        manifest_count=manifest_count,
        day_count=len(windows),
        carry_count=1,
        day_record_count=day_record_count,
        carry_record_count=carry_record_count,
        total_record_count=total_record_count,
    )


def iter_validated_raw_records(
    raw_root: str | Path,
    *,
    contract: RawSnapshotContract = FROZEN_RAW_CONTRACT,
) -> Iterator[RawRecord]:
    """Yield carry-in first, then local-day records in ordinal date/file order."""

    root = Path(raw_root)
    validation = validate_raw_snapshot(root, contract=contract)
    chunks: list[tuple[Literal["carry_in", "day"], str | None, Path]] = [
        (
            "carry_in",
            None,
            root / "timeseries" / "carry_in" / "carry_in.jsonl.gz",
        )
    ]
    chunks.extend(
        ("day", window.day_key, chunk_paths(root, "timeseries", window)[0])
        for window in jpl_analysis_windows()
    )
    ordinal = 0
    for chunk_kind, local_date, data_path in chunks:
        for chunk_index, payload in enumerate(_iter_gzip_objects(data_path)):
            yield RawRecord(
                ordinal=ordinal,
                chunk_kind=chunk_kind,
                local_date=local_date,
                chunk_index=chunk_index,
                payload=payload,
            )
            ordinal += 1
    if ordinal != validation.total_record_count:
        raise RawSnapshotError("raw snapshot changed during deterministic iteration")
