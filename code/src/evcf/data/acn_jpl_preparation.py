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
from .acn_jpl_month_config import (
    SEASONAL_MONTHS,
    JPLMonthConfig,
    is_canonical_jpl_month_config,
)

INVENTORY_DIGEST_ALGORITHM = (
    "sha256(ordinal-sorted UTF-8 relative_path<TAB>size<TAB>file_sha256<LF>; final LF)"
)
SEASONAL_INVENTORY_DIGEST_ALGORITHM = (
    "sha256(ordinal-sorted UTF-8 "
    "relative_path<NUL>file_sha256<NUL>byte_size<LF>; "
    "*.jsonl.gz and *.manifest.json only)"
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
SEASONAL_INVENTORY_SCHEMA_VERSION = "acn-jpl-seasonal-raw-inventory/v1"
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
    inventory_schema_version: str = INVENTORY_SCHEMA_VERSION
    inventory_algorithm: str = INVENTORY_DIGEST_ALGORITHM
    month_config: JPLMonthConfig | None = field(default=None, repr=False)
    dataset_id: str = FULL_MONTH_DATASET_ID
    carry_chunk_stems: tuple[str, ...] = ("carry_in",)

    @classmethod
    def for_month(
        cls,
        config: JPLMonthConfig,
        *,
        local_record_count: int,
        carry_in_record_count: int,
        inventory: InventorySnapshot,
    ) -> RawSnapshotContract:
        """Bind a seasonal month contract to its completed content inventory."""

        if not is_canonical_jpl_month_config(config) or config.month not in SEASONAL_MONTHS:
            raise ValueError("config must be an approved seasonal month contract")
        for name, value in (
            ("local_record_count", local_record_count),
            ("carry_in_record_count", carry_in_record_count),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if (
            inventory.schema_version != SEASONAL_INVENTORY_SCHEMA_VERSION
            or inventory.algorithm != SEASONAL_INVENTORY_DIGEST_ALGORITHM
        ):
            raise ValueError("inventory is not a canonical seasonal content inventory")
        if re.fullmatch(r"[0-9a-f]{64}", inventory.digest) is None:
            raise ValueError("seasonal inventory digest must be a lowercase SHA-256")
        carry_stems = tuple(
            f"carry-{ordinal:04d}" for ordinal in range(1, carry_in_record_count + 1)
        )
        return cls(
            file_count=inventory.file_count,
            manifest_count=config.day_count + carry_in_record_count,
            day_count=config.day_count,
            carry_count=carry_in_record_count,
            day_record_count=local_record_count,
            carry_record_count=carry_in_record_count,
            total_record_count=local_record_count + carry_in_record_count,
            total_bytes=inventory.total_bytes,
            inventory_sha256=inventory.digest,
            inventory_schema_version=SEASONAL_INVENTORY_SCHEMA_VERSION,
            inventory_algorithm=SEASONAL_INVENTORY_DIGEST_ALGORITHM,
            month_config=config,
            dataset_id=f"D0001-jpl-{config.month}-seasonal-ts",
            carry_chunk_stems=carry_stems,
        )


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
    schema_version: str = INVENTORY_SCHEMA_VERSION

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


def canonical_seasonal_inventory(root: str | Path) -> InventorySnapshot:
    """Hash immutable seasonal data/manifests using the acquisition framing.

    Mutable probe and progress state is deliberately excluded. Exact expected
    chunk paths are validated separately; this digest is not a layout check.
    """

    base = Path(root)
    if not base.is_dir():
        raise RawSnapshotError("inventory root is not a directory")
    paths: list[tuple[str, Path]] = []
    for path in base.rglob("*"):
        if path.is_symlink():
            raise RawSnapshotError("inventory root contains a symbolic link")
        if not path.is_file() or not (
            path.name.endswith(".jsonl.gz") or path.name.endswith(".manifest.json")
        ):
            continue
        relative_path = path.relative_to(base).as_posix()
        if "\0" in relative_path or "\r" in relative_path or "\n" in relative_path:
            raise RawSnapshotError("inventory path cannot be represented canonically")
        paths.append((relative_path, path))

    digest = hashlib.sha256()
    entries: list[InventoryEntry] = []
    for relative_path, path in sorted(paths, key=lambda item: item[0]):
        file_sha256 = _sha256_file(path)
        byte_size = path.stat().st_size
        digest.update(f"{relative_path}\0{file_sha256}\0{byte_size}\n".encode())
        entries.append(InventoryEntry(relative_path, byte_size, file_sha256))
    return InventorySnapshot(
        entries=tuple(entries),
        digest=digest.hexdigest(),
        total_bytes=sum(entry.size for entry in entries),
        algorithm=SEASONAL_INVENTORY_DIGEST_ALGORITHM,
        schema_version=SEASONAL_INVENTORY_SCHEMA_VERSION,
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


def _seasonal_carry_paths(raw_root: Path, stem: str) -> tuple[Path, Path]:
    return (
        raw_root / "timeseries" / "carry_in" / f"{stem}.jsonl.gz",
        raw_root / "manifests" / "carry_in" / f"{stem}.manifest.json",
    )


def _validate_seasonal_carry_chunk(
    raw_root: Path,
    *,
    config: JPLMonthConfig,
    dataset_id: str,
    stem: str,
    ordinal: int,
) -> int:
    data_path, manifest_path = _seasonal_carry_paths(raw_root, stem)
    if not data_path.is_file() or not manifest_path.is_file():
        raise RawSnapshotError("seasonal carry-in data or manifest is missing")
    manifest = _read_json_object(manifest_path, description="seasonal carry-in manifest")
    records = list(_iter_gzip_objects(data_path))
    if len(records) != 1:
        raise RawSnapshotError("seasonal carry-in must contain exactly one record")
    record = records[0]
    object_id = record.get("_id")
    session_id = record.get("sessionID")
    if not isinstance(object_id, str) or not object_id:
        raise RawSnapshotError("seasonal carry-in record has an invalid private identifier")
    if not isinstance(session_id, str) or not session_id:
        raise RawSnapshotError("seasonal carry-in record has an invalid private identifier")
    try:
        connection = parse_acn_datetime(record.get("connectionTime"))
        disconnect = parse_acn_datetime(record.get("disconnectTime"))
    except (TypeError, ValueError) as exc:
        raise RawSnapshotError("seasonal carry-in record has an invalid session boundary") from exc
    if connection is None or disconnect is None or not connection < config.utc_start < disconnect:
        raise RawSnapshotError("seasonal carry-in record does not cross the month boundary")

    query = ACNQuery(
        site="jpl",
        start=connection,
        end=config.local_start,
        timeseries=True,
        session_id=session_id,
    )
    expected_context = {
        "schema_version": "acn-jpl-seasonal-carry-in/v1",
        "dataset_id": dataset_id,
        "source": ACN_OFFICIAL_SOURCE,
        "endpoint": query.endpoint,
        "site": "jpl",
        "timezone": config.timezone_name,
        "month": config.month,
        "ordinal": ordinal,
        "local_month_start": config.local_start.isoformat(),
        "utc_start_inclusive": query.start_utc.isoformat(),
        "utc_end_exclusive": query.end_utc.isoformat(),
        "_id": object_id,
        "sessionID": session_id,
        "query_condition": query.condition,
        "output_file": data_path.name,
    }
    expected_keys = set(expected_context) | {
        "record_count",
        "remote_total_reported",
        "complete_for_query",
        "downloaded_at_utc",
        "sha256",
        "token_stored",
    }
    if set(manifest) != expected_keys or any(
        manifest.get(key) != value for key, value in expected_context.items()
    ):
        raise RawSnapshotError("seasonal carry-in manifest contract does not match")
    if manifest.get("record_count") != 1 or isinstance(manifest.get("record_count"), bool):
        raise RawSnapshotError("seasonal carry-in manifest record count does not match")
    if manifest.get("remote_total_reported") != 1 or isinstance(
        manifest.get("remote_total_reported"), bool
    ):
        raise RawSnapshotError("seasonal carry-in remote total does not match")
    if manifest.get("complete_for_query") is not True:
        raise RawSnapshotError("seasonal carry-in manifest is not complete for its query")
    if manifest.get("token_stored") is not False:
        raise RawSnapshotError("seasonal carry-in manifest contains an unsafe credential declaration")
    if not is_valid_utc_timestamp(manifest.get("downloaded_at_utc")):
        raise RawSnapshotError("seasonal carry-in manifest download timestamp is invalid")
    if manifest.get("sha256") != _sha256_file(data_path):
        raise RawSnapshotError("seasonal carry-in data hash does not match its manifest")
    return 1


def _assert_contract_value(name: str, observed: int | str, expected: int | str | None) -> None:
    if expected is not None and observed != expected:
        raise RawSnapshotError(f"raw snapshot {name} does not match the frozen contract")


def _contract_inventory(
    root: Path,
    contract: RawSnapshotContract,
) -> InventorySnapshot:
    binding = (contract.inventory_schema_version, contract.inventory_algorithm)
    if binding == (INVENTORY_SCHEMA_VERSION, INVENTORY_DIGEST_ALGORITHM):
        if contract.month_config is not None:
            raise RawSnapshotError("legacy inventory cannot be bound to a seasonal month")
        return canonical_inventory(root)
    if binding == (
        SEASONAL_INVENTORY_SCHEMA_VERSION,
        SEASONAL_INVENTORY_DIGEST_ALGORITHM,
    ):
        config = contract.month_config
        if config is None or not is_canonical_jpl_month_config(config):
            raise RawSnapshotError("seasonal inventory requires a canonical month contract")
        return canonical_seasonal_inventory(root)
    raise RawSnapshotError("raw snapshot inventory algorithm is not an approved closed contract")


def _seasonal_expected_paths(contract: RawSnapshotContract) -> set[str]:
    config = contract.month_config
    if config is None:
        return set()
    expected = {
        relative
        for window in config.day_windows
        for relative in (
            f"timeseries/{window.day_key}.jsonl.gz",
            f"manifests/timeseries/{window.day_key}.manifest.json",
        )
    }
    for stem in contract.carry_chunk_stems:
        expected.add(f"timeseries/carry_in/{stem}.jsonl.gz")
        expected.add(f"manifests/carry_in/{stem}.manifest.json")
    return expected


def _seasonal_layout_is_exact(root: Path, contract: RawSnapshotContract) -> bool:
    """Check the content allowlist while isolating mutable acquisition state."""

    expected_files = _seasonal_expected_paths(contract)
    expected_directories = {
        Path(relative).parent.as_posix() for relative in expected_files
    }
    expected_directories.update({"timeseries", "manifests", "state"})
    actual_content: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            return False
        if path.is_dir():
            if relative not in expected_directories:
                return False
            continue
        if not path.is_file():
            return False
        if relative in expected_files:
            actual_content.add(relative)
            continue
        # Probe references and progress are mutable orchestration state, not
        # immutable raw content. Only flat JSON files in state/ are isolated.
        if (
            relative.startswith("state/")
            and relative.count("/") == 1
            and path.suffix == ".json"
            and not path.name.endswith(".manifest.json")
        ):
            continue
        return False
    return actual_content == expected_files


def _validate_contract_shape(contract: RawSnapshotContract) -> None:
    config = contract.month_config
    if config is None:
        if (
            contract.inventory_schema_version != INVENTORY_SCHEMA_VERSION
            or contract.inventory_algorithm != INVENTORY_DIGEST_ALGORITHM
            or contract.dataset_id != FULL_MONTH_DATASET_ID
            or contract.day_count != FROZEN_RAW_CONTRACT.day_count
            or contract.carry_count != FROZEN_RAW_CONTRACT.carry_count
            or contract.carry_record_count != FROZEN_RAW_CONTRACT.carry_record_count
            or contract.carry_chunk_stems != FROZEN_RAW_CONTRACT.carry_chunk_stems
        ):
            raise RawSnapshotError("legacy May raw contract shape is invalid")
        return
    if not is_canonical_jpl_month_config(config) or config.month not in SEASONAL_MONTHS:
        raise RawSnapshotError("seasonal raw contract month is not canonical")
    count_fields = (
        contract.file_count,
        contract.manifest_count,
        contract.day_count,
        contract.carry_count,
        contract.day_record_count,
        contract.carry_record_count,
        contract.total_record_count,
    )
    if not all(_is_nonnegative_int(value) for value in count_fields):
        raise RawSnapshotError("seasonal raw contract counts must be nonnegative integers")
    expected_stems = tuple(
        f"carry-{ordinal:04d}" for ordinal in range(1, contract.carry_count + 1)
    )
    if contract.carry_chunk_stems != expected_stems:
        raise RawSnapshotError("seasonal carry-in ordinals are not canonical")
    if (
        contract.day_count != config.day_count
        or contract.manifest_count != contract.day_count + contract.carry_count
        or contract.file_count != 2 * contract.manifest_count
        or contract.carry_record_count != contract.carry_count
        or contract.total_record_count
        != contract.day_record_count + contract.carry_record_count
        or contract.dataset_id != f"D0001-jpl-{config.month}-seasonal-ts"
        or contract.total_bytes is None
        or not _is_nonnegative_int(contract.total_bytes)
        or contract.inventory_sha256 is None
        or re.fullmatch(r"[0-9a-f]{64}", contract.inventory_sha256) is None
    ):
        raise RawSnapshotError("seasonal raw contract aggregate fields are inconsistent")


def validate_raw_snapshot(
    raw_root: str | Path,
    *,
    contract: RawSnapshotContract = FROZEN_RAW_CONTRACT,
) -> RawSnapshotValidation:
    """Validate the complete raw snapshot before any downstream record is released."""

    root = Path(raw_root)
    _validate_contract_shape(contract)
    inventory = _contract_inventory(root, contract)
    _assert_contract_value("file count", inventory.file_count, contract.file_count)
    _assert_contract_value("byte count", inventory.total_bytes, contract.total_bytes)
    _assert_contract_value("inventory digest", inventory.digest, contract.inventory_sha256)

    manifest_pattern = "*.json" if contract.month_config is None else "*.manifest.json"
    manifest_count = sum(
        1 for path in (root / "manifests").rglob(manifest_pattern) if path.is_file()
    )
    _assert_contract_value("manifest count", manifest_count, contract.manifest_count)
    gzip_count = sum(1 for path in (root / "timeseries").rglob("*.jsonl.gz") if path.is_file())
    _assert_contract_value("gzip count", gzip_count, contract.day_count + contract.carry_count)

    day_record_count = 0
    config = contract.month_config
    windows = tuple(jpl_analysis_windows()) if config is None else config.day_windows
    _assert_contract_value("day count", len(windows), contract.day_count)
    if config is not None:
        actual_paths = {entry.relative_path for entry in inventory.entries}
        if actual_paths != _seasonal_expected_paths(contract):
            raise RawSnapshotError("seasonal raw content file set is not exact")
        if not _seasonal_layout_is_exact(root, contract):
            raise RawSnapshotError("seasonal raw layout is not exact")
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

    if config is None:
        carry_record_count = _validate_carry_chunk(root)
    else:
        carry_record_count = sum(
            _validate_seasonal_carry_chunk(
                root,
                config=config,
                dataset_id=contract.dataset_id,
                stem=stem,
                ordinal=ordinal,
            )
            for ordinal, stem in enumerate(contract.carry_chunk_stems, start=1)
        )
    total_record_count = day_record_count + carry_record_count
    _assert_contract_value("day record count", day_record_count, contract.day_record_count)
    _assert_contract_value("carry record count", carry_record_count, contract.carry_record_count)
    _assert_contract_value("object total", total_record_count, contract.total_record_count)
    validation = RawSnapshotValidation(
        inventory=inventory,
        manifest_count=manifest_count,
        day_count=len(windows),
        carry_count=contract.carry_count,
        day_record_count=day_record_count,
        carry_record_count=carry_record_count,
        total_record_count=total_record_count,
    )
    after = _contract_inventory(root, contract)
    assert_raw_snapshot_unchanged(inventory, after)
    return validation


def iter_validated_raw_records(
    raw_root: str | Path,
    *,
    contract: RawSnapshotContract = FROZEN_RAW_CONTRACT,
) -> Iterator[RawRecord]:
    """Yield carry-in first, then local-day records in ordinal date/file order."""

    root = Path(raw_root)
    validation = validate_raw_snapshot(root, contract=contract)
    config = contract.month_config
    windows = tuple(jpl_analysis_windows()) if config is None else config.day_windows
    if config is None:
        chunks: list[tuple[Literal["carry_in", "day"], str | None, Path]] = [
            (
                "carry_in",
                None,
                root / "timeseries" / "carry_in" / "carry_in.jsonl.gz",
            )
        ]
    else:
        chunks = [
            ("carry_in", None, _seasonal_carry_paths(root, stem)[0])
            for stem in contract.carry_chunk_stems
        ]
    chunks.extend(
        ("day", window.day_key, chunk_paths(root, "timeseries", window)[0])
        for window in windows
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
    assert_raw_snapshot_unchanged(
        validation.inventory,
        _contract_inventory(root, contract),
    )
