"""Fail-closed loader for the frozen JPL May 2019 Gate 1 snapshot.

The prepared snapshot is local and ignored by Git.  This module verifies its
content-addressed contract before returning any feature input.  Full cleaned
session records remain behind a causal query surface: callers can request only
current/pilot prefixes at a canonical issue time, never retrospective outcomes,
identifiers, user inputs, or post-issue samples.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone
from numbers import Integral, Real
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

EXPECTED_DATA_SNAPSHOT_SHA256 = "7066ffc8ba42a98f73246acfbc62352fe55a1433a43cba80957c6034e3aeaa5d"
EXPECTED_SOURCE_INVENTORY_SHA256 = (
    "63e3f88fcbd4c0d8b87392267cdbe5ad383d89468f10ac3de5e181837b18dcac"
)
EXPECTED_PROTOCOL_SHA256 = "2b95e9b09d31fdd30c559be80f9db64b22e33822b08a25de3715e168f3697bf3"
EXPECTED_PREPARED_SNAPSHOT_SHA256 = (
    "d3ef2d6e5a4a1dee4f71c716714c29ed8e1624cdfcb070cd96c00155aca082c0"
)
EXPECTED_HORIZONS_MINUTES = (15, 30, 60, 120, 240)
EXPECTED_ISSUE_COUNT = 2_853
EXPECTED_STATION_BIN_COUNT = 2_976
CAUSAL_MAX_WINDOW_SECONDS = 60 * 60
CAUSAL_HOLD_CAP_SECONDS = 12
_SNAPSHOT_VERIFICATION_SCHEMA = "acn-jpl-gate1-verified-snapshot/v1"

ARTIFACT_ROOTS: Mapping[str, str] = MappingProxyType(
    {
        "station_15min.csv.gz": "processed",
        "station_15min.npz": "processed",
        "m1.npz": "processed",
        "m2.npz": "processed",
        "labels.npz": "processed",
        "m3.jsonl.gz": "processed",
        "m4.jsonl.gz": "processed",
        "cleaned_sessions.jsonl.gz": "interim",
        "cleaned_sessions.jsonl.gz.manifest.json": "interim",
    }
)


class _FrozenMapping(Mapping[str, Any]):
    """Small picklable read-only mapping used by cross-process snapshots."""

    __slots__ = ("__data",)

    def __init__(self, value: Mapping[str, Any]) -> None:
        self.__data = dict(value)

    def __getitem__(self, key: str) -> Any:
        return self.__data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.__data)

    def __len__(self) -> int:
        return len(self.__data)

    def __reduce__(self) -> tuple[Any, tuple[dict[str, Any]]]:
        return type(self), (dict(self.__data),)


@dataclass(frozen=True, slots=True)
class _SnapshotVerification:
    schema_version: str
    data_snapshot_sha256: str
    artifact_sha256: tuple[tuple[str, str], ...]
    loader_implementation_sha256: str
    target_source_sha256: str
    feature_source_sha256: str
    causal_prefix_source_sha256: str | None
    seal_sha256: str


_MANIFEST_KEYS = {
    "schema_version",
    "source_inventory_sha256",
    "data_snapshot_sha256",
    "artifact_count",
    "artifacts",
    "cleaning_policy",
    "protocol_sha256",
    "power_column_present",
    "power_label_type",
    "snapshot_sha256",
}
_CLEANING_POLICY = {
    "boundary_sensitivity_s": 60,
    "current_mode_s": 4,
    "locf_cap_s": 60,
    "locf_mode_multiplier": 3,
    "pilot_mode_s": 4,
}
_CLEANED_MANIFEST_KEYS = {
    "anonymous_session_indexes",
    "data_file",
    "policy",
    "private_identifiers_stored",
    "record_count",
    "schema_version",
    "sha256",
    "source_inventory_sha256",
}
_CLEAN_SESSION_KEYS = {
    "schema_version",
    "session_index",
    "timezone",
    "site_id",
    "station_id",
    "space_id",
    "cluster_id",
    "connection_utc_s",
    "disconnect_utc_s",
    "connection_local",
    "disconnect_local",
    "retrospective_done_raw",
    "retrospective_done_utc_s",
    "offline_kwh_delivered",
    "current",
    "pilot",
    "user_inputs",
}
_CLEAN_SERIES_KEYS = {
    "field_name",
    "timestamps_utc_s",
    "values",
    "raw_ordinals",
    "boundary_positive_points",
    "boundary_sensitivity_points",
    "conflict_lww_overrides",
    "audit",
    "locf_cap_s",
    "main_integral",
}
_M3_KEYS = {
    "issue_index",
    "issue_time_utc_s",
    "anonymous_session_index",
    "elapsed_connection_s",
    "elapsed_charging_time_proxy_s",
    "current_current_a",
    "recent_current_mean_a",
    "recent_current_peak_a",
    "recent_current_observed_ratio",
    "cumulative_current_ah",
    "cumulative_current_observed_ratio",
    "current_pilot_a",
    "user_input_modified_utc_s",
    "requested_departure_minutes_from_issue",
    "known_kwh_requested",
}
_M4_KEYS = {
    "issue_index",
    "issue_time_utc_s",
    "anonymous_session_index",
    "current_start_offset_inclusive",
    "current_end_offset_exclusive",
    "pilot_start_offset_inclusive",
    "pilot_end_offset_exclusive",
    "min_visible_timestamp_utc_s",
    "max_visible_timestamp_utc_s",
    "partial_current_trajectory_ref",
    "partial_pilot_trajectory_ref",
}
_STATION_COLUMNS = (
    "timestamp_utc",
    "timestamp_local",
    "local_date",
    "quarter_hour_index",
    "day_of_week",
    "is_weekend",
    "station_current_mean_a",
    "station_current_peak_a",
    "connected_session_count",
    "active_charging_session_count",
    "active_charging_session_count_gt_1a",
    "pilot_sum_a",
    "pilot_mean_a",
    "arrival_count",
    "disconnect_count",
    "observed_coverage_ratio",
    "pilot_observed_coverage_ratio",
    "valid_bin_80",
    "valid_bin_90",
    "valid_bin_95",
)
_STATION_NUMERIC_COLUMNS = (
    "quarter_hour_index",
    "day_of_week",
    "station_current_mean_a",
    "station_current_peak_a",
    "connected_session_count",
    "active_charging_session_count",
    "active_charging_session_count_gt_1a",
    "pilot_sum_a",
    "pilot_mean_a",
    "arrival_count",
    "disconnect_count",
    "observed_coverage_ratio",
    "pilot_observed_coverage_ratio",
)
_STATION_VALIDITY_COLUMNS = ("valid_bin_80", "valid_bin_90", "valid_bin_95")
_SHA256_LENGTH = 64


def _readonly(array: np.ndarray) -> np.ndarray:
    contiguous = np.ascontiguousarray(array)
    immutable_bytes = contiguous.tobytes(order="C")
    return np.frombuffer(immutable_bytes, dtype=contiguous.dtype).reshape(contiguous.shape)


def _bounded_causal_offsets(
    timestamps: np.ndarray,
    *,
    issue_time_utc_s: int,
    lookback_seconds: int,
) -> tuple[int, int]:
    lookback_start = issue_time_utc_s - lookback_seconds
    start = int(np.searchsorted(timestamps, lookback_start, side="left"))
    if start > 0 and int(timestamps[start - 1]) + CAUSAL_HOLD_CAP_SECONDS > lookback_start:
        start -= 1
    end = int(np.searchsorted(timestamps, issue_time_utc_s, side="right"))
    return start, end


@dataclass(frozen=True, slots=True)
class CausalSessionSeries:
    """Only the anonymous join key and current/pilot samples visible at a cutoff."""

    anonymous_session_index: int
    current_timestamps_utc_s: np.ndarray
    current_values_a: np.ndarray
    pilot_timestamps_utc_s: np.ndarray
    pilot_values_a: np.ndarray


def _update_causal_prefix_digest(
    digest: Any,
    canonical_position: int,
    issue_time_utc_s: int,
    series: CausalSessionSeries,
) -> None:
    """Bind one ordered loader delivery to a shared streaming digest."""

    digest.update(b"acn-jpl-gate1-causal-prefix/v1")
    digest.update(
        np.asarray(
            [canonical_position, issue_time_utc_s, series.anonymous_session_index],
            dtype=np.int64,
        ).tobytes()
    )
    for array in (
        series.current_timestamps_utc_s,
        series.current_values_a,
        series.pilot_timestamps_utc_s,
        series.pilot_values_a,
    ):
        value = np.ascontiguousarray(array)
        digest.update(value.dtype.str.encode("ascii"))
        digest.update(np.asarray(value.shape, dtype=np.int64).tobytes())
        digest.update(value.tobytes(order="C"))


@dataclass(frozen=True, slots=True)
class _FullSessionSeries:
    current_timestamps_utc_s: np.ndarray
    current_values_a: np.ndarray
    pilot_timestamps_utc_s: np.ndarray
    pilot_values_a: np.ndarray


class _CausalSessionStore:
    """Opaque full-series store whose sole data-returning method applies a cutoff."""

    __slots__ = ("__canonical_issue_times", "__series")

    def __init__(
        self,
        series: Mapping[int, _FullSessionSeries],
        canonical_issue_times: Sequence[int] | np.ndarray,
    ) -> None:
        self.__series = MappingProxyType(dict(series))
        self.__canonical_issue_times = frozenset(int(value) for value in canonical_issue_times)

    @property
    def session_count(self) -> int:
        return len(self.__series)

    def _has_session(self, anonymous_session_index: int) -> bool:
        return _as_int(anonymous_session_index, "anonymous session index") in self.__series

    def _prefix_at(
        self,
        issue_time_utc_s: int,
        anonymous_session_index: int,
    ) -> CausalSessionSeries:
        """Return the immutable maximum-window causal prefix ending at the cutoff.

        The fixed M4 grid needs at most 60 minutes. One predecessor is retained
        only when its bounded 12-second hold overlaps that window. Samples at
        issue time remain visible here for the PR #18 audit; the M4 encoder uses
        its frozen ``[window_start, issue_time)`` calculation boundary.
        """

        issue = _as_int(issue_time_utc_s, "issue_time_utc_s")
        if issue not in self.__canonical_issue_times:
            raise ValueError("causal cutoff must be a canonical issue_time_utc_s")
        session_index = _as_nonnegative_int(anonymous_session_index, "anonymous session index")
        try:
            full = self.__series[session_index]
        except KeyError as exc:
            raise ValueError("causal session reference does not exist") from exc

        current_start, current_end = _bounded_causal_offsets(
            full.current_timestamps_utc_s,
            issue_time_utc_s=issue,
            lookback_seconds=CAUSAL_MAX_WINDOW_SECONDS,
        )
        pilot_start, pilot_end = _bounded_causal_offsets(
            full.pilot_timestamps_utc_s,
            issue_time_utc_s=issue,
            lookback_seconds=CAUSAL_MAX_WINDOW_SECONDS,
        )
        return CausalSessionSeries(
            anonymous_session_index=session_index,
            current_timestamps_utc_s=_readonly(
                full.current_timestamps_utc_s[current_start:current_end]
            ),
            current_values_a=_readonly(full.current_values_a[current_start:current_end]),
            pilot_timestamps_utc_s=_readonly(full.pilot_timestamps_utc_s[pilot_start:pilot_end]),
            pilot_values_a=_readonly(full.pilot_values_a[pilot_start:pilot_end]),
        )

    def _audit_reference(self, row: Mapping[str, Any], ordinal: int) -> None:
        """Validate an M4 reference without returning an unbounded series."""

        session_index = int(row["anonymous_session_index"])
        issue = int(row["issue_time_utc_s"])
        try:
            full = self.__series[session_index]
        except KeyError as exc:
            raise ValueError("M4 reference session does not exist") from exc
        current_start = int(row["current_start_offset_inclusive"])
        current_end = int(row["current_end_offset_exclusive"])
        pilot_start = int(row["pilot_start_offset_inclusive"])
        pilot_end = int(row["pilot_end_offset_exclusive"])
        expected_current = _bounded_causal_offsets(
            full.current_timestamps_utc_s,
            issue_time_utc_s=issue,
            lookback_seconds=86_400,
        )
        expected_pilot = _bounded_causal_offsets(
            full.pilot_timestamps_utc_s,
            issue_time_utc_s=issue,
            lookback_seconds=86_400,
        )
        if (current_start, current_end) != expected_current:
            raise ValueError(f"M4 row {ordinal} current reference offsets are inconsistent")
        if (pilot_start, pilot_end) != expected_pilot:
            raise ValueError(f"M4 row {ordinal} pilot reference offsets are inconsistent")
        if current_end > len(full.current_timestamps_utc_s) or pilot_end > len(
            full.pilot_timestamps_utc_s
        ):
            raise ValueError(f"M4 row {ordinal} reference offsets exceed the cleaned session")
        current = full.current_timestamps_utc_s[current_start:current_end]
        pilot = full.pilot_timestamps_utc_s[pilot_start:pilot_end]
        if (len(current) and int(current[-1]) > issue) or (len(pilot) and int(pilot[-1]) > issue):
            raise ValueError(f"M4 row {ordinal} reference cutoff is later than issue time")
        visible = np.concatenate((current, pilot))
        expected_min = int(visible.min()) if len(visible) else None
        expected_max = int(visible.max()) if len(visible) else None
        if row["min_visible_timestamp_utc_s"] != expected_min:
            raise ValueError(f"M4 row {ordinal} minimum reference cutoff is inconsistent")
        if row["max_visible_timestamp_utc_s"] != expected_max:
            raise ValueError(f"M4 row {ordinal} maximum reference cutoff is inconsistent")


@dataclass(frozen=True, slots=True)
class Gate1Snapshot:
    """Immutable, verified inputs for the frozen Gate 1 pilot."""

    data_snapshot_sha256: str
    artifact_sha256: Mapping[str, str]
    issue_times: np.ndarray
    horizons: np.ndarray
    labels: np.ndarray
    m1_history: np.ndarray
    m1_history_mask: np.ndarray
    m1_calendar: np.ndarray
    m2_current_state: np.ndarray
    m3_rows: tuple[Mapping[str, Any], ...]
    m4_rows: tuple[Mapping[str, Any], ...]
    m3_by_issue_time: tuple[tuple[Mapping[str, Any], ...], ...]
    m4_by_issue_time: tuple[tuple[Mapping[str, Any], ...], ...]
    station_times: np.ndarray
    station_current_mean_a: np.ndarray
    station_valid_90: np.ndarray
    feature_index_names: tuple[str, ...] = ("issue_time_utc_s",)
    _verification: _SnapshotVerification | None = dataclass_field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def __getstate__(self) -> tuple[Any, ...]:
        return tuple(getattr(self, name) for name in self.__slots__)

    def __setstate__(self, state: tuple[Any, ...]) -> None:
        if len(state) != len(self.__slots__):
            raise ValueError("snapshot checkpoint field count is invalid")
        for name, value in zip(self.__slots__, state, strict=True):
            restored = _readonly(np.asarray(value)) if isinstance(value, np.ndarray) else value
            object.__setattr__(self, name, restored)
        if self._verification is not None:
            verified_snapshot_provenance(self)


CausalPrefixConsumer = Callable[[int, int, CausalSessionSeries], None]


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_json(text: str, context: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{context} contains invalid JSON") from exc


def _read_json_object(path: Path, context: str) -> dict[str, Any]:
    try:
        payload = _decode_json(path.read_text(encoding="utf-8"), context)
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read {context}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"{context} must be a JSON object")
    return payload


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{context} schema keys differ; missing={missing}, extra={extra}")


def _as_int(value: Any, context: str) -> int:
    if not isinstance(value, Integral) or isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{context} must be an integer")
    return int(value)


def _as_nonnegative_int(value: Any, context: str) -> int:
    result = _as_int(value, context)
    if result < 0:
        raise ValueError(f"{context} must be nonnegative")
    return result


def _as_optional_int(value: Any, context: str) -> int | None:
    return None if value is None else _as_int(value, context)


def _as_finite(value: Any, context: str) -> float:
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{context} must be finite")
    return result


def _as_optional_finite(value: Any, context: str) -> float | None:
    return None if value is None else _as_finite(value, context)


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _array_content_sha256(arrays: Sequence[np.ndarray]) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        value = np.ascontiguousarray(array)
        digest.update(value.dtype.str.encode("ascii"))
        digest.update(np.asarray(value.shape, dtype=np.int64).tobytes())
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def _snapshot_target_source_sha256(snapshot: Gate1Snapshot) -> str:
    return _array_content_sha256(
        (
            np.asarray(snapshot.issue_times),
            np.asarray(snapshot.horizons),
            np.asarray(snapshot.labels),
        )
    )


def _snapshot_feature_source_sha256(snapshot: Gate1Snapshot) -> str:
    digest = hashlib.sha256()
    digest.update(
        _array_content_sha256(
            (
                np.asarray(snapshot.m1_history),
                np.asarray(snapshot.m1_history_mask),
                np.asarray(snapshot.m1_calendar),
                np.asarray(snapshot.m2_current_state),
                np.asarray(snapshot.station_times),
                np.asarray(snapshot.station_current_mean_a),
                np.asarray(snapshot.station_valid_90),
            )
        ).encode("ascii")
    )
    digest.update(
        json.dumps(
            list(snapshot.feature_index_names),
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    )
    for name, groups in (
        ("m3_rows", (snapshot.m3_rows,)),
        ("m4_rows", (snapshot.m4_rows,)),
        ("m3_by_issue_time", snapshot.m3_by_issue_time),
        ("m4_by_issue_time", snapshot.m4_by_issue_time),
    ):
        digest.update(name.encode("ascii"))
        digest.update(np.asarray([len(groups)], dtype=np.int64).tobytes())
        for group in groups:
            digest.update(np.asarray([len(group)], dtype=np.int64).tobytes())
            for row in group:
                payload = json.dumps(
                    dict(row),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("ascii")
                digest.update(np.asarray([len(payload)], dtype=np.int64).tobytes())
                digest.update(payload)
    return digest.hexdigest()


def _snapshot_verification_payload(
    *,
    data_snapshot_sha256: str,
    artifact_sha256: tuple[tuple[str, str], ...],
    loader_implementation_sha256: str,
    target_source_sha256: str,
    feature_source_sha256: str,
    causal_prefix_source_sha256: str | None,
) -> bytes:
    value = {
        "schema_version": _SNAPSHOT_VERIFICATION_SCHEMA,
        "data_snapshot_sha256": data_snapshot_sha256,
        "artifact_sha256": [
            {"artifact_name": name, "sha256": digest} for name, digest in artifact_sha256
        ],
        "loader_implementation_sha256": loader_implementation_sha256,
        "target_source_sha256": target_source_sha256,
        "feature_source_sha256": feature_source_sha256,
        "causal_prefix_source_sha256": causal_prefix_source_sha256,
    }
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _issue_snapshot_verification(
    snapshot: Gate1Snapshot,
    *,
    causal_prefix_source_sha256: str | None,
) -> None:
    artifacts = tuple((name, str(snapshot.artifact_sha256[name])) for name in ARTIFACT_ROOTS)
    loader_sha256 = _file_sha256(Path(__file__))
    target_source_sha256 = _snapshot_target_source_sha256(snapshot)
    feature_source_sha256 = _snapshot_feature_source_sha256(snapshot)
    if causal_prefix_source_sha256 is not None and not _valid_sha256(causal_prefix_source_sha256):
        raise ValueError("causal prefix source digest is invalid")
    payload = _snapshot_verification_payload(
        data_snapshot_sha256=snapshot.data_snapshot_sha256,
        artifact_sha256=artifacts,
        loader_implementation_sha256=loader_sha256,
        target_source_sha256=target_source_sha256,
        feature_source_sha256=feature_source_sha256,
        causal_prefix_source_sha256=causal_prefix_source_sha256,
    )
    object.__setattr__(
        snapshot,
        "_verification",
        _SnapshotVerification(
            schema_version=_SNAPSHOT_VERIFICATION_SCHEMA,
            data_snapshot_sha256=snapshot.data_snapshot_sha256,
            artifact_sha256=artifacts,
            loader_implementation_sha256=loader_sha256,
            target_source_sha256=target_source_sha256,
            feature_source_sha256=feature_source_sha256,
            causal_prefix_source_sha256=causal_prefix_source_sha256,
            seal_sha256=hashlib.sha256(payload).hexdigest(),
        ),
    )


def verified_snapshot_provenance(snapshot: Gate1Snapshot) -> str:
    """Return loader-issued provenance, rejecting synthetic or replaced snapshots."""

    if not isinstance(snapshot, Gate1Snapshot):
        raise TypeError("verified snapshot provenance requires a Gate1Snapshot")
    verification = snapshot._verification
    if not isinstance(verification, _SnapshotVerification):
        raise ValueError("snapshot has no verified loader seal")  # noqa: TRY004
    if verification.schema_version != _SNAPSHOT_VERIFICATION_SCHEMA:
        raise ValueError("snapshot loader seal schema is invalid")
    if not _valid_sha256(snapshot.data_snapshot_sha256) or (
        verification.data_snapshot_sha256 != snapshot.data_snapshot_sha256
    ):
        raise ValueError("snapshot loader seal does not bind the frozen data snapshot")
    if set(snapshot.artifact_sha256) != set(ARTIFACT_ROOTS):
        raise ValueError("snapshot loader seal requires all nine artifact hashes")
    artifacts = tuple((name, str(snapshot.artifact_sha256[name])) for name in ARTIFACT_ROOTS)
    if artifacts != verification.artifact_sha256 or any(
        not _valid_sha256(digest) for _name, digest in artifacts
    ):
        raise ValueError("snapshot artifact hashes differ from the verified loader seal")
    loader_sha256 = _file_sha256(Path(__file__))
    if verification.loader_implementation_sha256 != loader_sha256:
        raise ValueError("snapshot loader implementation provenance has changed")
    target_source_sha256 = _snapshot_target_source_sha256(snapshot)
    if target_source_sha256 != verification.target_source_sha256:
        raise ValueError("snapshot target arrays differ from the verified loader seal")
    feature_source_sha256 = _snapshot_feature_source_sha256(snapshot)
    if feature_source_sha256 != verification.feature_source_sha256:
        raise ValueError("snapshot feature source content differs from the verified loader seal")
    causal_prefix_source_sha256 = verification.causal_prefix_source_sha256
    if causal_prefix_source_sha256 is not None and not _valid_sha256(causal_prefix_source_sha256):
        raise ValueError("snapshot causal prefix source provenance is invalid")
    array_fields = (
        "issue_times",
        "horizons",
        "labels",
        "m1_history",
        "m1_history_mask",
        "m1_calendar",
        "m2_current_state",
        "station_times",
        "station_current_mean_a",
        "station_valid_90",
    )
    if any(np.asarray(getattr(snapshot, name)).flags.writeable for name in array_fields):
        raise ValueError("verified snapshot arrays must remain immutable")
    payload = _snapshot_verification_payload(
        data_snapshot_sha256=snapshot.data_snapshot_sha256,
        artifact_sha256=artifacts,
        loader_implementation_sha256=loader_sha256,
        target_source_sha256=target_source_sha256,
        feature_source_sha256=feature_source_sha256,
        causal_prefix_source_sha256=causal_prefix_source_sha256,
    )
    expected_seal = hashlib.sha256(payload).hexdigest()
    if verification.seal_sha256 != expected_seal:
        raise ValueError("snapshot loader seal is inconsistent")
    return expected_seal


def verified_causal_prefix_provenance(snapshot: Gate1Snapshot) -> str:
    """Return the exact loader-delivered causal-stream digest for M4 encoding."""

    verified_snapshot_provenance(snapshot)
    assert snapshot._verification is not None
    value = snapshot._verification.causal_prefix_source_sha256
    if value is None:
        raise ValueError("verified snapshot has no causal prefix loader delivery")
    return value


def _validate_manifest(
    processed_root: Path,
    interim_root: Path,
) -> tuple[dict[str, Any], Mapping[str, str]]:
    manifest = _read_json_object(
        processed_root / "data_snapshot_manifest.json", "data snapshot manifest"
    )
    _require_exact_keys(manifest, _MANIFEST_KEYS, "data snapshot manifest")
    if manifest["schema_version"] != "acn-jpl-local-data-snapshot/v1":
        raise ValueError("data snapshot manifest schema_version is invalid")
    if manifest["artifact_count"] != len(ARTIFACT_ROOTS):
        raise ValueError("data snapshot artifact_count must equal nine")
    if manifest["cleaning_policy"] != _CLEANING_POLICY:
        raise ValueError("data snapshot cleaning policy has drifted")
    if manifest["power_column_present"] is not False or manifest["power_label_type"] != "none":
        raise ValueError("data snapshot power semantics have drifted")
    for field in ("source_inventory_sha256", "protocol_sha256", "snapshot_sha256"):
        if not _valid_sha256(manifest[field]):
            raise ValueError(f"data snapshot {field} is not a lowercase SHA-256")
    if manifest["source_inventory_sha256"] != EXPECTED_SOURCE_INVENTORY_SHA256:
        raise ValueError("data snapshot source inventory SHA-256 is not frozen")
    if manifest["protocol_sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("data snapshot protocol SHA-256 is not frozen")
    if manifest["snapshot_sha256"] != EXPECTED_PREPARED_SNAPSHOT_SHA256:
        raise ValueError("data snapshot prepared snapshot SHA-256 is not frozen")

    raw_entries = manifest["artifacts"]
    if not isinstance(raw_entries, list) or len(raw_entries) != len(ARTIFACT_ROOTS):
        raise ValueError("data snapshot artifacts must contain exactly nine entries")
    entries: dict[str, dict[str, Any]] = {}
    for ordinal, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict):
            raise TypeError(f"artifact entry {ordinal} must be an object")
        _require_exact_keys(raw_entry, {"artifact_name", "size_bytes", "sha256"}, "artifact entry")
        name = raw_entry["artifact_name"]
        if not isinstance(name, str) or name not in ARTIFACT_ROOTS:
            raise ValueError(f"unexpected snapshot artifact: {name!r}")
        if name in entries:
            raise ValueError(f"duplicate snapshot artifact: {name}")
        size = _as_nonnegative_int(raw_entry["size_bytes"], f"artifact {name} size")
        sha256 = raw_entry["sha256"]
        if not _valid_sha256(sha256):
            raise ValueError(f"artifact {name} SHA-256 is invalid")
        entries[name] = {"size_bytes": size, "sha256": sha256}
    if set(entries) != set(ARTIFACT_ROOTS):
        raise ValueError("snapshot artifact allowlist does not match exactly")

    canonical = (
        json.dumps(
            {
                "protocol_sha256": manifest["protocol_sha256"],
                "artifacts": raw_entries,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    recomputed_snapshot_sha256 = hashlib.sha256(canonical).hexdigest()
    if manifest["data_snapshot_sha256"] != recomputed_snapshot_sha256:
        raise ValueError("data snapshot SHA-256 does not match its canonical manifest entries")
    if recomputed_snapshot_sha256 != EXPECTED_DATA_SNAPSHOT_SHA256:
        raise ValueError("data snapshot SHA-256 does not match the frozen Gate 1 snapshot")

    observed: dict[str, str] = {}
    for name, root_name in ARTIFACT_ROOTS.items():
        root = processed_root if root_name == "processed" else interim_root
        path = root / name
        if not path.is_file():
            raise ValueError(f"required snapshot artifact is missing: {name}")
        actual_size = path.stat().st_size
        if actual_size != entries[name]["size_bytes"]:
            raise ValueError(f"artifact {name} size does not match its manifest")
        actual_sha256 = _file_sha256(path)
        if actual_sha256 != entries[name]["sha256"]:
            raise ValueError(f"artifact {name} SHA-256 does not match its manifest")
        observed[name] = actual_sha256
    return manifest, MappingProxyType(observed)


def _load_npz(
    path: Path,
    spec: Mapping[str, tuple[np.dtype[Any], tuple[int, ...]]],
) -> dict[str, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as stored:
            if set(stored.files) != set(spec):
                raise ValueError(f"{path.name} NPZ keys do not match its schema")
            arrays = {name: np.asarray(stored[name]) for name in spec}
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith(path.name):
            raise
        raise ValueError(f"{path.name} is not a valid pickle-free NPZ") from exc
    for name, (dtype, shape) in spec.items():
        array = arrays[name]
        if array.dtype != dtype:
            raise ValueError(f"{path.name}:{name} dtype does not match its schema")
        if array.shape != shape:
            raise ValueError(f"{path.name}:{name} shape does not match its schema")
    return arrays


def _validate_ordered_times(times: np.ndarray, context: str) -> None:
    if times.ndim != 1 or len(times) == 0:
        raise ValueError(f"{context} issue_time must be a nonempty vector")
    differences = np.diff(times)
    if np.any(differences <= 0):
        raise ValueError(f"{context} issue_time must be strictly ordered and unique")
    if np.any(differences % 900 != 0):
        raise ValueError(f"{context} issue_time must remain on the 15-minute grid")


def _load_dense(processed_root: Path) -> dict[str, np.ndarray]:
    labels = _load_npz(
        processed_root / "labels.npz",
        {
            "issue_time_utc_s": (np.dtype(np.int64), (EXPECTED_ISSUE_COUNT,)),
            "horizons_minutes": (np.dtype(np.int16), (5,)),
            "station_current_mean_a": (
                np.dtype(np.float32),
                (EXPECTED_ISSUE_COUNT, 5),
            ),
        },
    )
    issue_times = labels["issue_time_utc_s"]
    _validate_ordered_times(issue_times, "labels")
    if not np.array_equal(
        labels["horizons_minutes"], np.asarray(EXPECTED_HORIZONS_MINUTES, dtype=np.int16)
    ):
        raise ValueError("labels horizons do not match the frozen protocol")
    if not np.all(np.isfinite(labels["station_current_mean_a"])):
        raise ValueError("labels must be finite")

    m1 = _load_npz(
        processed_root / "m1.npz",
        {
            "issue_time_utc_s": (np.dtype(np.int64), (EXPECTED_ISSUE_COUNT,)),
            "history_station_current_mean_a": (
                np.dtype(np.float32),
                (EXPECTED_ISSUE_COUNT, 96),
            ),
            "history_observed_mask": (
                np.dtype(np.bool_),
                (EXPECTED_ISSUE_COUNT, 96),
            ),
            "calendar": (np.dtype(np.int16), (EXPECTED_ISSUE_COUNT, 3)),
        },
    )
    m2 = _load_npz(
        processed_root / "m2.npz",
        {
            "issue_time_utc_s": (np.dtype(np.int64), (EXPECTED_ISSUE_COUNT,)),
            "history_station_current_mean_a": (
                np.dtype(np.float32),
                (EXPECTED_ISSUE_COUNT, 96),
            ),
            "history_observed_mask": (
                np.dtype(np.bool_),
                (EXPECTED_ISSUE_COUNT, 96),
            ),
            "current_state": (np.dtype(np.float32), (EXPECTED_ISSUE_COUNT, 6)),
        },
    )
    for name, dense in (("M1", m1), ("M2", m2)):
        _validate_ordered_times(dense["issue_time_utc_s"], name)
        if not np.array_equal(dense["issue_time_utc_s"], issue_times):
            raise ValueError(f"{name} issue_time does not equal labels in canonical order")
    if not np.array_equal(
        m1["history_station_current_mean_a"],
        m2["history_station_current_mean_a"],
        equal_nan=True,
    ) or not np.array_equal(m1["history_observed_mask"], m2["history_observed_mask"]):
        raise ValueError("M1 and M2 history arrays differ")
    history = m1["history_station_current_mean_a"]
    if np.any(np.isinf(history)):
        raise ValueError("M1 history contains infinite values")
    if not np.array_equal(np.isnan(history), ~m1["history_observed_mask"]):
        raise ValueError("M1 history NaN values do not match its observed mask")
    if np.any(np.isinf(m2["current_state"])):
        raise ValueError("M2 current_state contains infinite values")
    return {
        "issue_times": issue_times,
        "horizons": labels["horizons_minutes"],
        "labels": labels["station_current_mean_a"],
        "m1_history": history,
        "m1_history_mask": m1["history_observed_mask"],
        "m1_calendar": m1["calendar"],
        "m2_current_state": m2["current_state"],
    }


def _parse_utc_epoch(value: str, context: str) -> int:
    if not isinstance(value, str):
        raise TypeError(f"{context} must be an ISO timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{context} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{context} must be timezone-aware")
    parsed = parsed.astimezone(timezone.utc)
    if parsed.microsecond:
        raise ValueError(f"{context} must use whole seconds")
    return int(parsed.timestamp())


def _csv_float(value: str, context: str) -> float:
    if value == "":
        return math.nan
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{context} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{context} cannot be infinite")
    return number


def _csv_bool(value: str, context: str) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    raise ValueError(f"{context} must be True or False")


def _load_station(processed_root: Path) -> dict[str, np.ndarray]:
    station = _load_npz(
        processed_root / "station_15min.npz",
        {
            "timestamp_utc_s": (np.dtype(np.int64), (EXPECTED_STATION_BIN_COUNT,)),
            "calendar": (np.dtype(np.int16), (EXPECTED_STATION_BIN_COUNT, 3)),
            "numeric": (np.dtype(np.float32), (EXPECTED_STATION_BIN_COUNT, 13)),
            "validity": (np.dtype(np.bool_), (EXPECTED_STATION_BIN_COUNT, 3)),
        },
    )
    station_times = station["timestamp_utc_s"]
    if np.any(np.diff(station_times) != 900):
        raise ValueError("station timestamps must be unique ordered continuous 15-minute bins")
    if np.any(np.isinf(station["numeric"])):
        raise ValueError("station numeric data contains infinite values")

    csv_times: list[int] = []
    csv_calendar: list[list[int]] = []
    csv_numeric: list[list[float]] = []
    csv_validity: list[list[bool]] = []
    try:
        with gzip.open(
            processed_root / "station_15min.csv.gz", "rt", encoding="utf-8", newline=""
        ) as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != _STATION_COLUMNS:
                raise ValueError("station CSV schema columns do not match")
            for row_number, row in enumerate(reader, start=2):
                if None in row:
                    raise ValueError("station CSV row has extra columns")
                csv_times.append(
                    _parse_utc_epoch(row["timestamp_utc"], f"station CSV row {row_number}")
                )
                calendar = [
                    int(_csv_float(row["quarter_hour_index"], "quarter_hour_index")),
                    int(_csv_float(row["day_of_week"], "day_of_week")),
                    int(_csv_bool(row["is_weekend"], "is_weekend")),
                ]
                csv_calendar.append(calendar)
                csv_numeric.append(
                    [
                        _csv_float(row[name], f"station CSV {name}")
                        for name in _STATION_NUMERIC_COLUMNS
                    ]
                )
                csv_validity.append(
                    [
                        _csv_bool(row[name], f"station CSV {name}")
                        for name in _STATION_VALIDITY_COLUMNS
                    ]
                )
    except (OSError, UnicodeError, gzip.BadGzipFile) as exc:
        raise ValueError("station CSV cannot be read") from exc
    if len(csv_times) != EXPECTED_STATION_BIN_COUNT:
        raise ValueError("station CSV row count does not match the frozen snapshot")
    if not np.array_equal(np.asarray(csv_times, dtype=np.int64), station_times):
        raise ValueError("station CSV and NPZ timestamps differ")
    if not np.array_equal(np.asarray(csv_calendar, dtype=np.int16), station["calendar"]):
        raise ValueError("station CSV and NPZ calendar values differ")
    if not np.allclose(
        np.asarray(csv_numeric, dtype=np.float32),
        station["numeric"],
        rtol=1e-6,
        atol=1e-6,
        equal_nan=True,
    ):
        raise ValueError("station CSV and NPZ numeric values differ")
    if not np.array_equal(np.asarray(csv_validity, dtype=np.bool_), station["validity"]):
        raise ValueError("station CSV and NPZ validity values differ")
    return {
        "station_times": station_times,
        "station_current_mean_a": station["numeric"][:, 2],
        "station_valid_90": station["validity"][:, 1],
    }


def _iter_jsonl(path: Path, context: str) -> Iterator[dict[str, Any]]:
    """Yield strict gzip JSONL objects without retaining the complete file."""

    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise ValueError(f"{context} contains a blank line at {line_number}")
                row = _decode_json(line, f"{context} line {line_number}")
                if not isinstance(row, dict):
                    raise TypeError(f"{context} line {line_number} must be an object")
                yield row
    except (OSError, UnicodeError, gzip.BadGzipFile) as exc:
        raise ValueError(f"cannot read {context}") from exc


def _read_jsonl(path: Path, context: str) -> list[dict[str, Any]]:
    """Materialize a small strict JSONL table (M3/M4 only)."""

    return list(_iter_jsonl(path, context))


def _validate_optional_ratio(value: Any, context: str) -> float | None:
    result = _as_optional_finite(value, context)
    if result is not None and not 0.0 <= result <= 1.0:
        raise ValueError(f"{context} must be between zero and one")
    return result


def _validate_m3_row(raw: dict[str, Any], ordinal: int) -> dict[str, Any]:
    context = f"M3 row {ordinal}"
    _require_exact_keys(raw, _M3_KEYS, context)
    row = dict(raw)
    row["issue_index"] = _as_nonnegative_int(row["issue_index"], f"{context} issue_index")
    row["issue_time_utc_s"] = _as_int(row["issue_time_utc_s"], f"{context} issue_time")
    row["anonymous_session_index"] = _as_nonnegative_int(
        row["anonymous_session_index"], f"{context} anonymous session"
    )
    for name in ("elapsed_connection_s", "elapsed_charging_time_proxy_s"):
        row[name] = _as_nonnegative_int(row[name], f"{context} {name}")
    for name in (
        "current_current_a",
        "recent_current_mean_a",
        "recent_current_peak_a",
        "current_pilot_a",
        "requested_departure_minutes_from_issue",
        "known_kwh_requested",
    ):
        row[name] = _as_optional_finite(row[name], f"{context} {name}")
    row["cumulative_current_ah"] = _as_finite(
        row["cumulative_current_ah"], f"{context} cumulative_current_ah"
    )
    for name in ("recent_current_observed_ratio", "cumulative_current_observed_ratio"):
        row[name] = _validate_optional_ratio(row[name], f"{context} {name}")
    modified = _as_optional_int(row["user_input_modified_utc_s"], f"{context} user input cutoff")
    if modified is not None and modified > row["issue_time_utc_s"]:
        raise ValueError(f"{context} user input is later than the issue time")
    row["user_input_modified_utc_s"] = modified
    return row


def _validate_m4_row(raw: dict[str, Any], ordinal: int) -> dict[str, Any]:
    context = f"M4 row {ordinal}"
    _require_exact_keys(raw, _M4_KEYS, context)
    row = dict(raw)
    for name in ("issue_index", "anonymous_session_index"):
        row[name] = _as_nonnegative_int(row[name], f"{context} {name}")
    row["issue_time_utc_s"] = _as_int(row["issue_time_utc_s"], f"{context} issue_time")
    for prefix in ("current", "pilot"):
        start_name = f"{prefix}_start_offset_inclusive"
        end_name = f"{prefix}_end_offset_exclusive"
        row[start_name] = _as_nonnegative_int(row[start_name], f"{context} {start_name}")
        row[end_name] = _as_nonnegative_int(row[end_name], f"{context} {end_name}")
        if row[start_name] > row[end_name]:
            raise ValueError(f"{context} reference offsets are reversed")
    for name in ("min_visible_timestamp_utc_s", "max_visible_timestamp_utc_s"):
        row[name] = _as_optional_int(row[name], f"{context} {name}")
    minimum = row["min_visible_timestamp_utc_s"]
    maximum = row["max_visible_timestamp_utc_s"]
    if (minimum is None) != (maximum is None):
        raise ValueError(f"{context} visible cutoff bounds must both be null or integers")
    if minimum is not None and maximum is not None:
        if minimum > maximum:
            raise ValueError(f"{context} visible cutoff bounds are reversed")
        if maximum > row["issue_time_utc_s"]:
            raise ValueError(f"{context} cutoff is later than the issue time")
        if minimum < row["issue_time_utc_s"] - 86_400 - 12:
            raise ValueError(f"{context} cutoff exceeds the 24-hour causal lookback")
    if row["partial_current_trajectory_ref"] != "cleaned_current_prefix":
        raise ValueError(f"{context} current reference is invalid")
    if row["partial_pilot_trajectory_ref"] != "cleaned_pilot_prefix":
        raise ValueError(f"{context} pilot reference is invalid")
    return row


def group_by_canonical_issue_time(
    canonical_issue_times: Sequence[int] | np.ndarray,
    rows: Iterable[Mapping[str, Any]],
) -> tuple[tuple[Mapping[str, Any], ...], ...]:
    """Group ragged rows in canonical order while retaining empty issue-time groups."""

    times = np.asarray(canonical_issue_times)
    if times.dtype != np.dtype(np.int64):
        raise ValueError("canonical issue_time dtype must be int64")
    _validate_ordered_times(times, "canonical")
    positions = {int(value): index for index, value in enumerate(times)}
    grouped: list[list[Mapping[str, Any]]] = [[] for _ in range(len(times))]
    seen: set[tuple[int, int]] = set()
    for ordinal, source in enumerate(rows):
        if not isinstance(source, Mapping):
            raise TypeError(f"ragged row {ordinal} must be a mapping")
        issue = _as_int(source.get("issue_time_utc_s"), f"ragged row {ordinal} issue_time")
        session = _as_nonnegative_int(
            source.get("anonymous_session_index"),
            f"ragged row {ordinal} anonymous session index",
        )
        try:
            position = positions[issue]
        except KeyError as exc:
            raise ValueError("ragged row issue_time is outside the canonical universe") from exc
        pair = (issue, session)
        if pair in seen:
            raise ValueError("duplicate (issue_time, anonymous_session_index) ragged row")
        seen.add(pair)
        grouped[position].append(_FrozenMapping(source))
    return tuple(tuple(group) for group in grouped)


def _parse_clean_series(
    raw: Any,
    *,
    field_name: str,
    session_index: int,
) -> tuple[np.ndarray, np.ndarray]:
    context = f"cleaned session {session_index} {field_name}"
    if not isinstance(raw, dict):
        raise TypeError(f"{context} schema must be an object")
    _require_exact_keys(raw, _CLEAN_SERIES_KEYS, context)
    if raw["field_name"] != field_name:
        raise ValueError(f"{context} field_name schema is invalid")
    if raw["locf_cap_s"] != 12:
        raise ValueError(f"{context} LOCF cap schema is invalid")
    for name in (
        "boundary_positive_points",
        "boundary_sensitivity_points",
        "conflict_lww_overrides",
    ):
        if not isinstance(raw[name], list):
            raise TypeError(f"{context} {name} must be a list")
    if not isinstance(raw["audit"], dict) or not isinstance(raw["main_integral"], dict):
        raise TypeError(f"{context} audit/integral schema is invalid")
    timestamps_raw = raw["timestamps_utc_s"]
    values_raw = raw["values"]
    ordinals_raw = raw["raw_ordinals"]
    if not all(isinstance(value, list) for value in (timestamps_raw, values_raw, ordinals_raw)):
        raise ValueError(f"{context} series arrays must be lists")
    if not (len(timestamps_raw) == len(values_raw) == len(ordinals_raw)):
        raise ValueError(f"{context} series arrays must have equal lengths")
    timestamps = np.asarray(
        [_as_int(value, f"{context} timestamp") for value in timestamps_raw],
        dtype=np.int64,
    )
    values = np.asarray(
        [_as_finite(value, f"{context} value") for value in values_raw],
        dtype=np.float64,
    )
    for value in ordinals_raw:
        _as_nonnegative_int(value, f"{context} raw ordinal")
    if len(timestamps) and np.any(np.diff(timestamps) <= 0):
        raise ValueError(f"{context} timestamps must be strictly ordered and unique")
    return _readonly(timestamps), _readonly(values)


def _load_cleaned_store(
    interim_root: Path,
    *,
    canonical_issue_times: np.ndarray,
    source_inventory_sha256: str,
) -> _CausalSessionStore:
    manifest = _read_json_object(
        interim_root / "cleaned_sessions.jsonl.gz.manifest.json",
        "cleaned-session manifest",
    )
    _require_exact_keys(manifest, _CLEANED_MANIFEST_KEYS, "cleaned-session manifest")
    if manifest["schema_version"] != "acn-jpl-cleaned-sessions/v1":
        raise ValueError("cleaned-session manifest schema_version is invalid")
    if manifest["data_file"] != "cleaned_sessions.jsonl.gz":
        raise ValueError("cleaned-session manifest data_file is invalid")
    if manifest["anonymous_session_indexes"] is not True:
        raise ValueError("cleaned-session manifest must use anonymous indexes")
    if manifest["private_identifiers_stored"] is not False:
        raise ValueError("cleaned-session manifest private identifier flag is invalid")
    if manifest["policy"] != _CLEANING_POLICY:
        raise ValueError("cleaned-session manifest cleaning policy has drifted")
    if manifest["source_inventory_sha256"] != source_inventory_sha256:
        raise ValueError("cleaned-session source inventory does not match snapshot")
    record_count = _as_nonnegative_int(manifest["record_count"], "cleaned-session record_count")
    data_path = interim_root / "cleaned_sessions.jsonl.gz"
    if manifest["sha256"] != _file_sha256(data_path):
        raise ValueError("cleaned-session data SHA-256 does not match its own manifest")

    parsed: dict[int, _FullSessionSeries] = {}
    observed_count = 0
    for expected_index, raw in enumerate(_iter_jsonl(data_path, "cleaned-session store")):
        observed_count = expected_index + 1
        _require_exact_keys(raw, _CLEAN_SESSION_KEYS, f"cleaned session {expected_index}")
        if raw["schema_version"] != "acn-jpl-clean-session/v1":
            raise ValueError(f"cleaned session {expected_index} schema_version is invalid")
        session_index = _as_nonnegative_int(
            raw["session_index"], f"cleaned session {expected_index} session index"
        )
        if session_index != expected_index or session_index in parsed:
            raise ValueError("cleaned session indexes must be unique contiguous ordinals")
        if raw["timezone"] != "America/Los_Angeles":
            raise ValueError(f"cleaned session {session_index} timezone schema is invalid")
        connection = _as_int(raw["connection_utc_s"], f"cleaned session {session_index} connection")
        disconnect = _as_int(raw["disconnect_utc_s"], f"cleaned session {session_index} disconnect")
        if disconnect <= connection:
            raise ValueError(f"cleaned session {session_index} bounds are invalid")
        for name in ("site_id", "station_id", "space_id", "cluster_id"):
            if raw[name] is not None and not isinstance(raw[name], str):
                raise ValueError(f"cleaned session {session_index} identifier schema is invalid")
        for name in ("connection_local", "disconnect_local"):
            if not isinstance(raw[name], str):
                raise TypeError(f"cleaned session {session_index} local time schema is invalid")
        if raw["retrospective_done_raw"] is not None and not isinstance(
            raw["retrospective_done_raw"], str
        ):
            raise ValueError(f"cleaned session {session_index} retrospective schema is invalid")
        if raw["retrospective_done_utc_s"] is not None:
            _as_int(
                raw["retrospective_done_utc_s"],
                f"cleaned session {session_index} retrospective timestamp",
            )
        if raw["offline_kwh_delivered"] is not None:
            _as_finite(
                raw["offline_kwh_delivered"],
                f"cleaned session {session_index} offline energy",
            )
        if not isinstance(raw["user_inputs"], list):
            raise TypeError(f"cleaned session {session_index} user_inputs schema is invalid")
        current_times, current_values = _parse_clean_series(
            raw["current"], field_name="chargingCurrent", session_index=session_index
        )
        pilot_times, pilot_values = _parse_clean_series(
            raw["pilot"], field_name="pilotSignal", session_index=session_index
        )
        parsed[session_index] = _FullSessionSeries(
            current_timestamps_utc_s=current_times,
            current_values_a=current_values,
            pilot_timestamps_utc_s=pilot_times,
            pilot_values_a=pilot_values,
        )
    if observed_count != record_count:
        raise ValueError("cleaned-session record_count does not match the data")
    return _CausalSessionStore(parsed, canonical_issue_times)


def _audit_m4_references(
    rows: Sequence[Mapping[str, Any]],
    *,
    m3_pairs: set[tuple[int, int]],
    store: _CausalSessionStore,
) -> None:
    for ordinal, row in enumerate(rows):
        issue = int(row["issue_time_utc_s"])
        session_index = int(row["anonymous_session_index"])
        if (issue, session_index) not in m3_pairs:
            raise ValueError(f"M4 row {ordinal} session is not in the M3 connected set")
        store._audit_reference(row, ordinal)


def verify_and_load_snapshot(
    processed_root: str | Path,
    interim_root: str | Path,
    *,
    causal_prefix_consumer: CausalPrefixConsumer | None = None,
) -> Gate1Snapshot:
    """Verify all nine frozen artifacts and return leakage-safe model inputs."""

    processed = Path(processed_root)
    interim = Path(interim_root)
    if causal_prefix_consumer is not None and not callable(causal_prefix_consumer):
        raise TypeError("causal_prefix_consumer must be callable")
    if not processed.is_dir() or not interim.is_dir():
        raise ValueError("processed_root and interim_root must be existing directories")
    manifest, artifact_sha256 = _validate_manifest(processed, interim)
    dense = _load_dense(processed)
    station = _load_station(processed)
    canonical = dense["issue_times"]
    store = _load_cleaned_store(
        interim,
        canonical_issue_times=canonical,
        source_inventory_sha256=manifest["source_inventory_sha256"],
    )

    m3_rows = tuple(
        _FrozenMapping(_validate_m3_row(raw, ordinal))
        for ordinal, raw in enumerate(_read_jsonl(processed / "m3.jsonl.gz", "M3"))
    )
    m4_rows = tuple(
        _FrozenMapping(_validate_m4_row(raw, ordinal))
        for ordinal, raw in enumerate(_read_jsonl(processed / "m4.jsonl.gz", "M4"))
    )
    m3_by_issue = group_by_canonical_issue_time(canonical, m3_rows)
    m4_by_issue = group_by_canonical_issue_time(canonical, m4_rows)
    m3_pairs = {
        (int(row["issue_time_utc_s"]), int(row["anonymous_session_index"])) for row in m3_rows
    }
    missing_m3_sessions = {
        int(row["anonymous_session_index"])
        for row in m3_rows
        if not store._has_session(int(row["anonymous_session_index"]))
    }
    if missing_m3_sessions:
        raise ValueError("M3 references a cleaned session that does not exist")
    _audit_m4_references(m4_rows, m3_pairs=m3_pairs, store=store)

    snapshot = Gate1Snapshot(
        data_snapshot_sha256=manifest["data_snapshot_sha256"],
        artifact_sha256=_FrozenMapping(artifact_sha256),
        issue_times=_readonly(dense["issue_times"]),
        horizons=_readonly(dense["horizons"]),
        labels=_readonly(dense["labels"]),
        m1_history=_readonly(dense["m1_history"]),
        m1_history_mask=_readonly(dense["m1_history_mask"]),
        m1_calendar=_readonly(dense["m1_calendar"]),
        m2_current_state=_readonly(dense["m2_current_state"]),
        m3_rows=m3_rows,
        m4_rows=m4_rows,
        m3_by_issue_time=m3_by_issue,
        m4_by_issue_time=m4_by_issue,
        station_times=_readonly(station["station_times"]),
        station_current_mean_a=_readonly(station["station_current_mean_a"]),
        station_valid_90=_readonly(station["station_valid_90"]),
    )
    causal_prefix_digest = hashlib.sha256() if causal_prefix_consumer is not None else None
    if causal_prefix_consumer is not None:
        assert causal_prefix_digest is not None
        for canonical_position, (issue_time, rows) in enumerate(
            zip(snapshot.issue_times, snapshot.m3_by_issue_time, strict=True)
        ):
            issue = int(issue_time)
            for row in rows:
                series = store._prefix_at(issue, int(row["anonymous_session_index"]))
                _update_causal_prefix_digest(
                    causal_prefix_digest,
                    canonical_position,
                    issue,
                    series,
                )
                causal_prefix_consumer(canonical_position, issue, series)
    _issue_snapshot_verification(
        snapshot,
        causal_prefix_source_sha256=(
            causal_prefix_digest.hexdigest() if causal_prefix_digest is not None else None
        ),
    )
    return snapshot
