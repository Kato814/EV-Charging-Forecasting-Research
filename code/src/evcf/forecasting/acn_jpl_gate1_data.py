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
import weakref
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone
from numbers import Integral, Real
from pathlib import Path
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from evcf.data.acn_jpl_issue_snapshots import (
    IssueSnapshotResult,
    SnapshotPolicy,
    verified_issue_snapshot_sha256,
)
from evcf.data.acn_jpl_month_config import (
    SEASONAL_MONTHS,
    JPLMonthConfig,
    is_canonical_jpl_month_config,
    jpl_month_config,
)

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
_SEASONAL_SNAPSHOT_VERIFICATION_SCHEMA = "acn-jpl-seasonal-gate1-verified-snapshot/v1"
_SEASONAL_CHECKPOINT_ERROR = "seasonal Gate1 snapshots cannot be checkpointed"

SEASONAL_ARTIFACT_ROOTS = (
    "station_15min.jsonl.gz",
    "m1.jsonl.gz",
    "m2.jsonl.gz",
    "m3.jsonl.gz",
    "labels.jsonl.gz",
)

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

    __slots__ = ("__items",)

    def __init__(self, value: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_FrozenMapping__items", tuple(value.items()))

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise TypeError("frozen snapshot mappings cannot be modified")

    def __getitem__(self, key: str) -> Any:
        for name, value in self.__items:
            if name == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (name for name, _value in self.__items)

    def __len__(self) -> int:
        return len(self.__items)

    def __reduce__(self) -> tuple[Any, tuple[dict[str, Any]]]:
        return type(self), (dict(self.__items),)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _SnapshotVerification:
    schema_version: str
    data_snapshot_sha256: str
    artifact_sha256: tuple[tuple[str, str], ...]
    loader_implementation_sha256: str
    target_source_sha256: str
    feature_source_sha256: str
    causal_prefix_source_sha256: str | None
    seal_sha256: str

    def __copy__(self) -> _SnapshotVerification:
        return _SnapshotVerification(*_snapshot_verification_values(self))

    def __deepcopy__(self, _memo: dict[int, Any]) -> _SnapshotVerification:
        return _SnapshotVerification(*_snapshot_verification_values(self))

    def __reduce__(self) -> tuple[Any, tuple[tuple[Any, ...]]]:
        if not _is_issued_snapshot_verification(self):
            raise ValueError("unissued snapshot verification cannot be checkpointed")
        return _restore_snapshot_verification, (_snapshot_verification_values(self),)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class _SeasonalSnapshotVerification:
    schema_version: str
    month: str
    timezone_name: str
    utc_start_utc_s: int
    utc_end_utc_s: int
    expected_bins: int
    expected_issue_count: int
    tiers: tuple[str, ...]
    issue_snapshot_sha256: str
    data_snapshot_sha256: str
    artifact_sha256: tuple[tuple[str, str], ...]
    adapter_implementation_sha256: str
    target_source_sha256: str
    feature_source_sha256: str
    seal_sha256: str

    def __copy__(self) -> _SeasonalSnapshotVerification:
        raise ValueError(_SEASONAL_CHECKPOINT_ERROR)

    def __deepcopy__(self, _memo: dict[int, Any]) -> _SeasonalSnapshotVerification:
        raise ValueError(_SEASONAL_CHECKPOINT_ERROR)

    def __reduce__(self) -> tuple[Any, tuple[tuple[Any, ...]]]:
        raise ValueError(_SEASONAL_CHECKPOINT_ERROR)


_SnapshotVerificationType = _SnapshotVerification | _SeasonalSnapshotVerification
_SNAPSHOT_VERIFICATION_REGISTRY: dict[int, weakref.ReferenceType[Any]] = {}


def _snapshot_verification_values(value: _SnapshotVerification) -> tuple[Any, ...]:
    return (
        value.schema_version,
        value.data_snapshot_sha256,
        value.artifact_sha256,
        value.loader_implementation_sha256,
        value.target_source_sha256,
        value.feature_source_sha256,
        value.causal_prefix_source_sha256,
        value.seal_sha256,
    )


def _register_snapshot_verification(
    verification: _SnapshotVerificationType,
) -> _SnapshotVerificationType:
    if type(verification) not in (_SnapshotVerification, _SeasonalSnapshotVerification):
        raise TypeError("snapshot verification must use an exact internal type")
    identity = id(verification)

    def discard(reference: weakref.ReferenceType[Any]) -> None:
        if _SNAPSHOT_VERIFICATION_REGISTRY.get(identity) is reference:
            _SNAPSHOT_VERIFICATION_REGISTRY.pop(identity, None)

    _SNAPSHOT_VERIFICATION_REGISTRY[identity] = weakref.ref(verification, discard)
    return verification


def _is_issued_snapshot_verification(verification: object) -> bool:
    if type(verification) not in (_SnapshotVerification, _SeasonalSnapshotVerification):
        return False
    reference = _SNAPSHOT_VERIFICATION_REGISTRY.get(id(verification))
    return reference is not None and reference() is verification


def _restore_snapshot_verification(values: tuple[Any, ...]) -> _SnapshotVerification:
    if type(values) is not tuple or len(values) != 8:
        raise ValueError("snapshot checkpoint verification failed")
    restored = _SnapshotVerification(*values)
    _register_snapshot_verification(restored)
    return restored


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
_SEASONAL_M1_KEYS = {
    "issue_index",
    "issue_time_utc_s",
    "quarter_hour_index",
    "day_of_week",
    "is_weekend",
    "history_station_current_mean_a",
    "history_observed_mask",
}
_SEASONAL_M2_KEYS = _SEASONAL_M1_KEYS | {
    "connected_session_count",
    "active_charging_session_count",
    "station_current_a",
    "station_current_observed_ratio",
    "pilot_sum_a",
    "pilot_mean_a",
}
_SEASONAL_LABEL_KEYS = {"issue_index", "issue_time_utc_s", "labels"}
_SEASONAL_ISSUE_QA_KEYS = {
    "schema_version",
    "lookback_minutes",
    "horizons_minutes",
    "issue_times",
    "formal_issue_times",
    "incomplete_label_issue_times",
    "samples",
    "ragged_rows",
    "valid_labels_by_horizon",
    "shapes",
    "missing_rates",
    "leakage_audit",
    "future_fields_found",
    "unexpected_feature_keys",
    "temporal_violations",
    "feature_whitelist_enforcement",
    "occupancy_rate",
    "user_inputs_issue_time_truncation",
    "m4_generated",
}
_SEASONAL_MISSING_RATE_FIELDS = {
    "M2_station_current": ("m2_rows", "station_current_a"),
    "M2_pilot_sum": ("m2_rows", "pilot_sum_a"),
    "M2_pilot_mean": ("m2_rows", "pilot_mean_a"),
    "M3_current_current": ("m3_rows", "current_current_a"),
    "M3_recent_current_mean": ("m3_rows", "recent_current_mean_a"),
    "M3_recent_current_peak": ("m3_rows", "recent_current_peak_a"),
    "M3_current_pilot": ("m3_rows", "current_pilot_a"),
    "M3_known_requested_departure": (
        "m3_rows",
        "requested_departure_minutes_from_issue",
    ),
    "M3_known_requested_energy": ("m3_rows", "known_kwh_requested"),
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
    _verification: _SnapshotVerification | _SeasonalSnapshotVerification | None = dataclass_field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    def __getstate__(self) -> tuple[Any, ...]:
        if type(self._verification) is _SeasonalSnapshotVerification:
            raise ValueError(_SEASONAL_CHECKPOINT_ERROR)
        return tuple(getattr(self, name) for name in self.__slots__)

    def __setstate__(self, state: tuple[Any, ...]) -> None:
        if len(state) != len(self.__slots__):
            raise ValueError("snapshot checkpoint field count is invalid")
        verification_position = self.__slots__.index("_verification")
        if type(state[verification_position]) is _SeasonalSnapshotVerification:
            raise ValueError("snapshot checkpoint verification failed")
        for name, value in zip(self.__slots__, state, strict=True):
            restored = _readonly(np.asarray(value)) if isinstance(value, np.ndarray) else value
            object.__setattr__(self, name, restored)
        try:
            if not _is_issued_snapshot_verification(self._verification):
                raise ValueError("snapshot checkpoint has no issued verification")
            verified_snapshot_provenance(self)
        except (AttributeError, KeyError, OSError, TypeError, ValueError) as exc:
            object.__setattr__(self, "_verification", None)
            raise ValueError("snapshot checkpoint verification failed") from exc


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


def _seasonal_snapshot_feature_source_sha256(snapshot: Gate1Snapshot) -> str:
    """Hash only the M1--M3 seasonal feature sources, with no M4 material."""

    digest = hashlib.sha256()
    digest.update(b"acn-jpl-seasonal-m1-m3-feature-source/v1\0")
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
        ("m3_by_issue_time", snapshot.m3_by_issue_time),
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


def _canonical_json_sha256(value: Any) -> str:
    def materialize(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): materialize(nested) for key, nested in item.items()}
        if isinstance(item, (list, tuple)):
            return [materialize(nested) for nested in item]
        return item

    encoded = json.dumps(
        materialize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _seasonal_config_payload(config: JPLMonthConfig) -> dict[str, Any]:
    return {
        "month": config.month,
        "timezone_name": config.timezone_name,
        "utc_start_utc_s": int(config.utc_start.timestamp()),
        "utc_end_utc_s": int(config.utc_end.timestamp()),
        "expected_bins": config.expected_bins,
        "expected_issue_count": config.expected_scheduled_issue_times,
        "tiers": list(config.tiers),
    }


def _seasonal_data_snapshot_sha256(
    config: JPLMonthConfig,
    *,
    issue_snapshot_sha256: str,
    artifacts: tuple[tuple[str, str], ...],
) -> str:
    return _canonical_json_sha256(
        {
            "schema_version": "acn-jpl-seasonal-m1-m3-data-snapshot/v1",
            "month_config": _seasonal_config_payload(config),
            "issue_snapshot_sha256": issue_snapshot_sha256,
            "artifacts": [{"artifact_name": name, "sha256": digest} for name, digest in artifacts],
        }
    )


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
    verification = _SnapshotVerification(
        schema_version=_SNAPSHOT_VERIFICATION_SCHEMA,
        data_snapshot_sha256=snapshot.data_snapshot_sha256,
        artifact_sha256=artifacts,
        loader_implementation_sha256=loader_sha256,
        target_source_sha256=target_source_sha256,
        feature_source_sha256=feature_source_sha256,
        causal_prefix_source_sha256=causal_prefix_source_sha256,
        seal_sha256=hashlib.sha256(payload).hexdigest(),
    )
    object.__setattr__(
        snapshot,
        "_verification",
        _register_snapshot_verification(verification),
    )


def _seasonal_snapshot_verification_payload(
    *,
    config: JPLMonthConfig,
    issue_snapshot_sha256: str,
    data_snapshot_sha256: str,
    artifact_sha256: tuple[tuple[str, str], ...],
    adapter_implementation_sha256: str,
    target_source_sha256: str,
    feature_source_sha256: str,
) -> bytes:
    value = {
        "schema_version": _SEASONAL_SNAPSHOT_VERIFICATION_SCHEMA,
        "month_config": _seasonal_config_payload(config),
        "issue_snapshot_sha256": issue_snapshot_sha256,
        "data_snapshot_sha256": data_snapshot_sha256,
        "artifact_sha256": [
            {"artifact_name": name, "sha256": digest} for name, digest in artifact_sha256
        ],
        "adapter_implementation_sha256": adapter_implementation_sha256,
        "target_source_sha256": target_source_sha256,
        "feature_source_sha256": feature_source_sha256,
    }
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _issue_seasonal_snapshot_verification(
    snapshot: Gate1Snapshot,
    *,
    config: JPLMonthConfig,
    issue_snapshot_sha256: str,
) -> None:
    artifacts = tuple(
        (name, str(snapshot.artifact_sha256[name])) for name in SEASONAL_ARTIFACT_ROOTS
    )
    implementation = _file_sha256(Path(__file__))
    target_source = _snapshot_target_source_sha256(snapshot)
    feature_source = _seasonal_snapshot_feature_source_sha256(snapshot)
    payload = _seasonal_snapshot_verification_payload(
        config=config,
        issue_snapshot_sha256=issue_snapshot_sha256,
        data_snapshot_sha256=snapshot.data_snapshot_sha256,
        artifact_sha256=artifacts,
        adapter_implementation_sha256=implementation,
        target_source_sha256=target_source,
        feature_source_sha256=feature_source,
    )
    verification = _SeasonalSnapshotVerification(
        schema_version=_SEASONAL_SNAPSHOT_VERIFICATION_SCHEMA,
        month=config.month,
        timezone_name=config.timezone_name,
        utc_start_utc_s=int(config.utc_start.timestamp()),
        utc_end_utc_s=int(config.utc_end.timestamp()),
        expected_bins=config.expected_bins,
        expected_issue_count=config.expected_scheduled_issue_times,
        tiers=config.tiers,
        issue_snapshot_sha256=issue_snapshot_sha256,
        data_snapshot_sha256=snapshot.data_snapshot_sha256,
        artifact_sha256=artifacts,
        adapter_implementation_sha256=implementation,
        target_source_sha256=target_source,
        feature_source_sha256=feature_source,
        seal_sha256=hashlib.sha256(payload).hexdigest(),
    )
    object.__setattr__(
        snapshot,
        "_verification",
        _register_snapshot_verification(verification),
    )


def _validate_seasonal_snapshot_structure(
    snapshot: Gate1Snapshot,
    *,
    config: JPLMonthConfig,
) -> None:
    if type(snapshot) is not Gate1Snapshot:
        raise TypeError("seasonal verification requires an exact Gate1Snapshot")
    if type(snapshot.artifact_sha256) is not _FrozenMapping:
        raise ValueError("seasonal artifact hashes must use the sealed mapping type")
    if snapshot.feature_index_names != ("issue_time_utc_s",):
        raise ValueError("seasonal feature index schema is invalid")
    scheduled_issue_count = config.expected_scheduled_issue_times
    expected_issues = np.arange(
        int(config.utc_start.timestamp()) + 86_400,
        int(config.utc_start.timestamp()) + 86_400 + scheduled_issue_count * 900,
        900,
        dtype=np.int64,
    )
    expected_station = np.arange(
        int(config.utc_start.timestamp()),
        int(config.utc_end.timestamp()),
        900,
        dtype=np.int64,
    )
    arrays = {
        "issue_times": np.asarray(snapshot.issue_times),
        "horizons": np.asarray(snapshot.horizons),
        "labels": np.asarray(snapshot.labels),
        "m1_history": np.asarray(snapshot.m1_history),
        "m1_history_mask": np.asarray(snapshot.m1_history_mask),
        "m1_calendar": np.asarray(snapshot.m1_calendar),
        "m2_current_state": np.asarray(snapshot.m2_current_state),
        "station_times": np.asarray(snapshot.station_times),
        "station_current_mean_a": np.asarray(snapshot.station_current_mean_a),
        "station_valid_90": np.asarray(snapshot.station_valid_90),
    }
    issue_times = arrays["issue_times"]
    if issue_times.ndim != 1:
        raise ValueError("seasonal issue_times array schema is invalid")
    formal_issue_count = len(issue_times)
    if not 0 < formal_issue_count <= scheduled_issue_count:
        raise ValueError("seasonal formal issue count is outside the scheduled universe")
    expected_specs = {
        "issue_times": (np.dtype(np.int64), (formal_issue_count,)),
        "horizons": (np.dtype(np.int16), (len(EXPECTED_HORIZONS_MINUTES),)),
        "labels": (
            np.dtype(np.float32),
            (formal_issue_count, len(EXPECTED_HORIZONS_MINUTES)),
        ),
        "m1_history": (np.dtype(np.float32), (formal_issue_count, 96)),
        "m1_history_mask": (np.dtype(np.bool_), (formal_issue_count, 96)),
        "m1_calendar": (np.dtype(np.int16), (formal_issue_count, 3)),
        "m2_current_state": (np.dtype(np.float32), (formal_issue_count, 6)),
        "station_times": (np.dtype(np.int64), (config.expected_bins,)),
        "station_current_mean_a": (np.dtype(np.float32), (config.expected_bins,)),
        "station_valid_90": (np.dtype(np.bool_), (config.expected_bins,)),
    }
    for name, (dtype, shape) in expected_specs.items():
        if arrays[name].dtype != dtype or arrays[name].shape != shape:
            raise ValueError(f"seasonal {name} array schema is invalid")
    if np.any(np.diff(issue_times) <= 0):
        raise ValueError("seasonal formal issue times must be strictly increasing")
    scheduled_positions = np.searchsorted(expected_issues, issue_times)
    if np.any(scheduled_positions >= scheduled_issue_count) or not np.array_equal(
        expected_issues[scheduled_positions], issue_times
    ):
        raise ValueError("seasonal issue times are outside the canonical scheduled grid")
    if not np.array_equal(arrays["station_times"], expected_station):
        raise ValueError("seasonal station times do not match the continuous UTC grid")
    if not np.array_equal(
        arrays["horizons"], np.asarray(EXPECTED_HORIZONS_MINUTES, dtype=np.int16)
    ):
        raise ValueError("seasonal horizons do not match the canonical protocol")
    if not np.all(np.isfinite(arrays["labels"])):
        raise ValueError("seasonal labels must be finite")
    if np.any(np.isinf(arrays["m1_history"])) or not np.array_equal(
        np.isnan(arrays["m1_history"]), ~arrays["m1_history_mask"]
    ):
        raise ValueError("seasonal history values do not match their masks")
    if np.any(np.isinf(arrays["m2_current_state"])) or np.any(
        np.isinf(arrays["station_current_mean_a"])
    ):
        raise ValueError("seasonal numeric feature sources cannot contain infinity")
    if len(snapshot.m3_by_issue_time) != formal_issue_count:
        raise ValueError("seasonal M3 groups do not cover every formal issue time")
    if any(type(row) is not _FrozenMapping for row in snapshot.m3_rows) or any(
        type(row) is not _FrozenMapping for group in snapshot.m3_by_issue_time for row in group
    ):
        raise TypeError("seasonal M3 rows must use the sealed mapping type")


def _verified_seasonal_snapshot_provenance(
    snapshot: Gate1Snapshot,
    verification: _SeasonalSnapshotVerification,
) -> str:
    if verification.schema_version != _SEASONAL_SNAPSHOT_VERIFICATION_SCHEMA:
        raise ValueError("seasonal snapshot seal schema is invalid")
    if verification.month not in SEASONAL_MONTHS:
        raise ValueError("seasonal snapshot seal month is invalid")
    config = jpl_month_config(verification.month)
    if (
        verification.timezone_name != config.timezone_name
        or verification.utc_start_utc_s != int(config.utc_start.timestamp())
        or verification.utc_end_utc_s != int(config.utc_end.timestamp())
        or verification.expected_bins != config.expected_bins
        or verification.expected_issue_count != config.expected_scheduled_issue_times
        or verification.tiers != config.tiers
        or verification.tiers != ("M1", "M2", "M3")
    ):
        raise ValueError("seasonal snapshot seal is not bound to its canonical month config")
    if snapshot.m4_rows or snapshot.m4_by_issue_time:
        raise ValueError("seasonal snapshot must not contain M4 material")
    _validate_seasonal_snapshot_structure(snapshot, config=config)
    if set(snapshot.artifact_sha256) != set(SEASONAL_ARTIFACT_ROOTS):
        raise ValueError("seasonal snapshot artifact roots are invalid")
    artifacts = tuple(
        (name, str(snapshot.artifact_sha256[name])) for name in SEASONAL_ARTIFACT_ROOTS
    )
    if artifacts != verification.artifact_sha256 or any(
        not _valid_sha256(digest) for _name, digest in artifacts
    ):
        raise ValueError("seasonal snapshot artifact hashes differ from its seal")
    if not _valid_sha256(verification.issue_snapshot_sha256):
        raise ValueError("seasonal issue snapshot provenance is invalid")
    expected_data_snapshot = _seasonal_data_snapshot_sha256(
        config,
        issue_snapshot_sha256=verification.issue_snapshot_sha256,
        artifacts=artifacts,
    )
    if (
        snapshot.data_snapshot_sha256 != expected_data_snapshot
        or verification.data_snapshot_sha256 != expected_data_snapshot
    ):
        raise ValueError("seasonal data snapshot differs from its sealed artifacts")
    implementation = _file_sha256(Path(__file__))
    if verification.adapter_implementation_sha256 != implementation:
        raise ValueError("seasonal snapshot adapter provenance has changed")
    target_source = _snapshot_target_source_sha256(snapshot)
    if target_source != verification.target_source_sha256:
        raise ValueError("seasonal target arrays differ from their seal")
    feature_source = _seasonal_snapshot_feature_source_sha256(snapshot)
    if feature_source != verification.feature_source_sha256:
        raise ValueError("seasonal feature sources differ from their seal")
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
        raise ValueError("seasonal snapshot arrays must remain immutable")
    payload = _seasonal_snapshot_verification_payload(
        config=config,
        issue_snapshot_sha256=verification.issue_snapshot_sha256,
        data_snapshot_sha256=expected_data_snapshot,
        artifact_sha256=artifacts,
        adapter_implementation_sha256=implementation,
        target_source_sha256=target_source,
        feature_source_sha256=feature_source,
    )
    expected_seal = hashlib.sha256(payload).hexdigest()
    if verification.seal_sha256 != expected_seal:
        raise ValueError("seasonal snapshot seal is inconsistent")
    return expected_seal


def verified_snapshot_provenance(snapshot: Gate1Snapshot) -> str:
    """Return loader-issued provenance, rejecting synthetic or replaced snapshots."""

    if type(snapshot) is not Gate1Snapshot:
        raise TypeError("verified snapshot provenance requires a Gate1Snapshot")
    verification = snapshot._verification
    if not _is_issued_snapshot_verification(verification):
        raise ValueError("snapshot has no issued verified loader seal")
    if type(verification) is _SeasonalSnapshotVerification:
        return _verified_seasonal_snapshot_provenance(snapshot, verification)
    if type(verification) is not _SnapshotVerification:
        raise ValueError("snapshot has no verified loader seal")
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


def _strict_bool(value: Any, context: str) -> bool:
    if not isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{context} must be boolean")
    return bool(value)


def _seasonal_optional_float(value: Any, context: str) -> float:
    parsed = _as_optional_finite(value, context)
    return math.nan if parsed is None else parsed


def _validate_seasonal_station_rows(
    station_rows: Sequence[Mapping[str, Any]],
    *,
    config: JPLMonthConfig,
) -> tuple[tuple[dict[str, Any], ...], np.ndarray, np.ndarray, np.ndarray]:
    if isinstance(station_rows, (str, bytes)) or not isinstance(station_rows, Sequence):
        raise TypeError("seasonal station rows must be a sequence")
    if len(station_rows) != config.expected_bins:
        raise ValueError("seasonal station row length does not match the canonical grid")
    start_epoch = int(config.utc_start.timestamp())
    zone = ZoneInfo(config.timezone_name)
    materialized: list[dict[str, Any]] = []
    station_times: list[int] = []
    station_current: list[float] = []
    station_valid: list[bool] = []
    for ordinal, source in enumerate(station_rows):
        if not isinstance(source, Mapping):
            raise TypeError(f"seasonal station row {ordinal} must be a mapping")
        row = dict(source)
        context = f"seasonal station row {ordinal}"
        _require_exact_keys(row, set(_STATION_COLUMNS), context)
        expected_epoch = start_epoch + ordinal * 900
        if _parse_utc_epoch(row["timestamp_utc"], f"{context} timestamp_utc") != expected_epoch:
            raise ValueError("seasonal station rows must follow the continuous physical UTC grid")
        local = datetime.fromtimestamp(expected_epoch, tz=timezone.utc).astimezone(zone)
        if (
            row["timestamp_local"] != local.isoformat()
            or row["local_date"] != local.date().isoformat()
        ):
            raise ValueError(f"{context} local timestamp does not match the canonical config")
        quarter = _as_nonnegative_int(row["quarter_hour_index"], f"{context} quarter")
        day_of_week = _as_nonnegative_int(row["day_of_week"], f"{context} day_of_week")
        is_weekend = _strict_bool(row["is_weekend"], f"{context} is_weekend")
        if (
            quarter != local.hour * 4 + local.minute // 15
            or day_of_week != local.weekday()
            or is_weekend != (local.weekday() >= 5)
        ):
            raise ValueError(f"{context} calendar does not match its UTC timestamp")
        current = _seasonal_optional_float(
            row["station_current_mean_a"], f"{context} station current"
        )
        _seasonal_optional_float(row["station_current_peak_a"], f"{context} station peak")
        for name in (
            "connected_session_count",
            "active_charging_session_count",
            "active_charging_session_count_gt_1a",
            "arrival_count",
            "disconnect_count",
        ):
            _as_nonnegative_int(row[name], f"{context} {name}")
        _seasonal_optional_float(row["pilot_sum_a"], f"{context} pilot_sum_a")
        _seasonal_optional_float(row["pilot_mean_a"], f"{context} pilot_mean_a")
        coverage = _validate_optional_ratio(
            row["observed_coverage_ratio"], f"{context} observed coverage"
        )
        pilot_coverage = _validate_optional_ratio(
            row["pilot_observed_coverage_ratio"], f"{context} pilot coverage"
        )
        if coverage is None or pilot_coverage is None:
            raise ValueError(f"{context} coverage ratios cannot be missing")
        validity = tuple(
            _strict_bool(row[name], f"{context} {name}") for name in _STATION_VALIDITY_COLUMNS
        )
        expected_validity = tuple(coverage >= threshold for threshold in (0.80, 0.90, 0.95))
        if validity != expected_validity:
            raise ValueError(f"{context} validity flags do not match observed coverage")
        materialized.append(row)
        station_times.append(expected_epoch)
        station_current.append(current)
        station_valid.append(validity[1])
    expected_end = start_epoch + len(materialized) * 900
    if expected_end != int(config.utc_end.timestamp()):
        raise ValueError("seasonal station grid does not reach the canonical UTC boundary")
    return (
        tuple(materialized),
        np.asarray(station_times, dtype=np.int64),
        np.asarray(station_current, dtype=np.float32),
        np.asarray(station_valid, dtype=np.bool_),
    )


def _validate_seasonal_issue_qa(
    result: IssueSnapshotResult,
    *,
    config: JPLMonthConfig,
    m3_row_count: int,
    station_current: np.ndarray,
    station_valid: np.ndarray,
) -> None:
    qa = result.qa
    _require_exact_keys(qa, _SEASONAL_ISSUE_QA_KEYS, "seasonal issue snapshot QA")
    scheduled_issue_count = config.expected_scheduled_issue_times
    reported_issue_count = _as_nonnegative_int(
        qa["issue_times"], "seasonal issue snapshot QA issue_times"
    )
    formal_issue_count = _as_nonnegative_int(
        qa["formal_issue_times"], "seasonal issue snapshot QA formal_issue_times"
    )
    incomplete_issue_count = _as_nonnegative_int(
        qa["incomplete_label_issue_times"],
        "seasonal issue snapshot QA incomplete_label_issue_times",
    )
    if not 0 < formal_issue_count <= scheduled_issue_count:
        raise ValueError("seasonal formal issue count is outside the scheduled universe")
    expected_samples = {tier: formal_issue_count for tier in config.tiers}
    samples = qa["samples"]
    if not isinstance(samples, Mapping):
        raise TypeError("seasonal issue snapshot QA samples must be a mapping")
    _require_exact_keys(samples, set(config.tiers), "seasonal issue snapshot QA samples")
    for tier in config.tiers:
        _as_nonnegative_int(samples[tier], f"seasonal issue snapshot QA {tier} samples")
    expected_shapes = {
        "M1_history": [formal_issue_count, 96],
        "M2_dense": [formal_issue_count, 6],
        "M3_ragged_rows": m3_row_count,
        "M3_session_feature_width": 11,
        "labels": [formal_issue_count, len(result.policy.horizons_minutes)],
    }
    lookback_bins = result.policy.lookback_minutes // 15
    label_validity = {
        str(horizon): np.asarray(
            [
                bool(station_valid[lookback_bins + issue_index + horizon // 15 - 1])
                and math.isfinite(
                    float(station_current[lookback_bins + issue_index + horizon // 15 - 1])
                )
                for issue_index in range(scheduled_issue_count)
            ],
            dtype=np.bool_,
        )
        for horizon in result.policy.horizons_minutes
    }
    expected_labels = {
        horizon: int(np.count_nonzero(validity)) for horizon, validity in label_validity.items()
    }
    expected_formal_count = int(
        np.count_nonzero(np.logical_and.reduce(tuple(label_validity.values())))
    )
    ragged = qa["ragged_rows"]
    labels_by_horizon = qa["valid_labels_by_horizon"]
    shapes = qa["shapes"]
    temporal = qa["temporal_violations"]
    whitelist = qa["feature_whitelist_enforcement"]
    occupancy = qa["occupancy_rate"]
    user_inputs = qa["user_inputs_issue_time_truncation"]
    for name, value, keys in (
        ("ragged_rows", ragged, {"M3"}),
        ("valid_labels_by_horizon", labels_by_horizon, set(expected_labels)),
        ("shapes", shapes, set(expected_shapes)),
        ("temporal_violations", temporal, {"total", "late_user_input_rows"}),
        ("feature_whitelist_enforcement", whitelist, {"status", "unexpected_key_count"}),
        ("occupancy_rate", occupancy, {"status", "reason"}),
        (
            "user_inputs_issue_time_truncation",
            user_inputs,
            {"status", "connected_session_rows", "rows_with_known_input", "rule"},
        ),
    ):
        if not isinstance(value, Mapping):
            raise TypeError(f"seasonal issue snapshot QA {name} must be a mapping")
        _require_exact_keys(value, keys, f"seasonal issue snapshot QA {name}")
    for horizon in expected_labels:
        _as_nonnegative_int(
            labels_by_horizon[horizon],
            f"seasonal issue snapshot QA horizon {horizon}",
        )
    for name in ("M3",):
        _as_nonnegative_int(ragged[name], f"seasonal issue snapshot QA ragged {name}")
    for name in ("total", "late_user_input_rows"):
        _as_nonnegative_int(temporal[name], f"seasonal issue snapshot QA temporal {name}")
    _as_nonnegative_int(
        whitelist["unexpected_key_count"],
        "seasonal issue snapshot QA unexpected key count",
    )
    connected_rows = _as_nonnegative_int(
        user_inputs["connected_session_rows"],
        "seasonal issue snapshot QA connected user-input rows",
    )
    known_rows = _as_nonnegative_int(
        user_inputs["rows_with_known_input"],
        "seasonal issue snapshot QA known user-input rows",
    )
    if known_rows > connected_rows:
        raise ValueError("seasonal issue snapshot QA known-input count exceeds connected rows")
    for name in ("M1_history", "M2_dense", "labels"):
        shape = shapes[name]
        if not isinstance(shape, (list, tuple)) or len(shape) != 2:
            raise ValueError(f"seasonal issue snapshot QA {name} shape must have two integers")
        for value in shape:
            _as_nonnegative_int(value, f"seasonal issue snapshot QA {name} shape")
    for name in ("M3_ragged_rows", "M3_session_feature_width"):
        _as_nonnegative_int(shapes[name], f"seasonal issue snapshot QA {name}")
    horizons = qa["horizons_minutes"]
    if not isinstance(horizons, (list, tuple)):
        raise TypeError("seasonal issue snapshot QA horizons must be a sequence")
    for value in horizons:
        _as_nonnegative_int(value, "seasonal issue snapshot QA horizon")
    for name in ("future_fields_found", "unexpected_feature_keys"):
        value = qa[name]
        if not isinstance(value, (list, tuple)) or value:
            raise ValueError(f"seasonal issue snapshot QA {name} must be an empty sequence")

    missing_rates = qa["missing_rates"]
    if not isinstance(missing_rates, Mapping):
        raise TypeError("seasonal issue snapshot QA missing_rates must be a mapping")
    expected_missing_rate_keys = {"M1_history", *_SEASONAL_MISSING_RATE_FIELDS}
    _require_exact_keys(
        missing_rates,
        expected_missing_rate_keys,
        "seasonal issue snapshot QA missing_rates",
    )
    history_values = [
        value for row in result.m1_rows for value in row["history_station_current_mean_a"]
    ]
    expected_missing_rates: dict[str, float | None] = {
        "M1_history": (
            round(sum(value is None for value in history_values) / len(history_values), 8)
            if history_values
            else None
        )
    }
    for name, (rows_name, field_name) in _SEASONAL_MISSING_RATE_FIELDS.items():
        rows = getattr(result, rows_name)
        expected_missing_rates[name] = (
            round(sum(row[field_name] is None for row in rows) / len(rows), 8) if rows else None
        )
    for name, expected in expected_missing_rates.items():
        actual = missing_rates[name]
        if expected is None:
            if actual is not None:
                raise ValueError(f"seasonal issue snapshot QA {name} missing rate must be null")
            continue
        parsed = _as_finite(actual, f"seasonal issue snapshot QA {name} missing rate")
        if not 0.0 <= parsed <= 1.0 or not math.isclose(
            parsed, expected, rel_tol=0.0, abs_tol=1e-8
        ):
            raise ValueError(f"seasonal issue snapshot QA {name} missing rate is inconsistent")

    inferred_known_rows = sum(
        any(
            row[name] is not None
            for name in (
                "user_input_modified_utc_s",
                "requested_departure_minutes_from_issue",
                "known_kwh_requested",
            )
        )
        for row in result.m3_rows
    )
    if (
        qa["schema_version"] != "acn-jpl-issue-snapshot-qa/v1"
        or qa["lookback_minutes"] != result.policy.lookback_minutes
        or qa["horizons_minutes"] != list(result.policy.horizons_minutes)
        or reported_issue_count != scheduled_issue_count
        or formal_issue_count != expected_formal_count
        or incomplete_issue_count != scheduled_issue_count - formal_issue_count
        or qa["samples"] != expected_samples
        or qa["ragged_rows"] != {"M3": m3_row_count}
        or qa["valid_labels_by_horizon"] != expected_labels
        or qa["shapes"] != expected_shapes
        or qa["leakage_audit"] != "PASS"
        or qa["future_fields_found"] != []
        or qa["unexpected_feature_keys"] != []
        or temporal != {"total": 0, "late_user_input_rows": 0}
        or whitelist != {"status": "PASS", "unexpected_key_count": 0}
        or occupancy
        != {
            "status": "NOT_CONSTRUCTED",
            "reason": "Issue #17 supplies no frozen JPL capacity denominator",
        }
        or user_inputs["status"] != "PASS"
        or connected_rows != m3_row_count
        or not inferred_known_rows <= known_rows <= m3_row_count
        or user_inputs["rule"] != "last modifiedAt at or before issue time"
        or qa["m4_generated"] is not False
    ):
        raise ValueError("seasonal issue snapshot QA is inconsistent with its tables")


def _validate_seasonal_table_schemas(result: IssueSnapshotResult) -> None:
    for name, rows, keys in (
        ("M1", result.m1_rows, _SEASONAL_M1_KEYS),
        ("M2", result.m2_rows, _SEASONAL_M2_KEYS),
        ("M3", result.m3_rows, _M3_KEYS),
        ("label", result.label_rows, _SEASONAL_LABEL_KEYS),
    ):
        for ordinal, row in enumerate(rows):
            _require_exact_keys(row, keys, f"seasonal {name} row {ordinal}")
            if name == "label":
                labels = row["labels"]
                if not isinstance(labels, Mapping):
                    raise TypeError(f"seasonal label row {ordinal} labels must be a mapping")
                _require_exact_keys(
                    labels,
                    {str(value) for value in result.policy.horizons_minutes},
                    f"seasonal label row {ordinal} values",
                )


def _validate_seasonal_dense_rows(
    result: IssueSnapshotResult,
    *,
    config: JPLMonthConfig,
    station_current: np.ndarray,
    station_valid: np.ndarray,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    scheduled_issue_count = config.expected_scheduled_issue_times
    formal_issue_count = len(result.m1_rows)
    if not (
        formal_issue_count > 0
        and len(result.m2_rows) == formal_issue_count
        and len(result.label_rows) == formal_issue_count
    ):
        raise ValueError("seasonal M1, M2, and label rows must cover the formal issue subset")
    start_epoch = int(config.utc_start.timestamp())
    first_issue = start_epoch + result.policy.lookback_minutes * 60
    scheduled_issue_times = np.arange(
        first_issue,
        first_issue + scheduled_issue_count * result.policy.issue_step_minutes * 60,
        result.policy.issue_step_minutes * 60,
        dtype=np.int64,
    )
    expected_last = int(config.utc_end.timestamp()) - max(result.policy.horizons_minutes) * 60
    if (
        len(scheduled_issue_times) != scheduled_issue_count
        or int(scheduled_issue_times[-1]) != expected_last
    ):
        raise ValueError("canonical seasonal issue-time boundary is inconsistent")
    formal_issue_times: list[int] = []
    scheduled_issue_indexes: list[int] = []
    histories: list[list[float]] = []
    history_masks: list[list[bool]] = []
    calendars: list[list[int]] = []
    current_states: list[list[float]] = []
    labels: list[list[float]] = []
    horizon_keys = {str(value) for value in result.policy.horizons_minutes}
    m1_shared_keys = _SEASONAL_M1_KEYS
    zone = ZoneInfo(config.timezone_name)
    for position, (m1_source, m2_source, label_source) in enumerate(
        zip(result.m1_rows, result.m2_rows, result.label_rows, strict=True)
    ):
        m1 = dict(m1_source)
        m2 = dict(m2_source)
        label = dict(label_source)
        _require_exact_keys(m1, _SEASONAL_M1_KEYS, f"seasonal M1 row {position}")
        _require_exact_keys(m2, _SEASONAL_M2_KEYS, f"seasonal M2 row {position}")
        _require_exact_keys(label, _SEASONAL_LABEL_KEYS, f"seasonal label row {position}")
        row_issue_indexes = tuple(
            _as_nonnegative_int(row["issue_index"], f"{name} issue index")
            for name, row in (("M1", m1), ("M2", m2), ("label", label))
        )
        scheduled_issue_index = row_issue_indexes[0]
        if (
            any(value != scheduled_issue_index for value in row_issue_indexes[1:])
            or scheduled_issue_index >= scheduled_issue_count
            or (scheduled_issue_indexes and scheduled_issue_index <= scheduled_issue_indexes[-1])
        ):
            raise ValueError("seasonal dense rows must use one strictly increasing scheduled index")
        issue = int(scheduled_issue_times[scheduled_issue_index])
        for name, row in (("M1", m1), ("M2", m2), ("label", label)):
            if _as_int(row["issue_time_utc_s"], f"{name} issue time") != issue:
                raise ValueError(f"seasonal {name} row is not aligned to its issue time")
        scheduled_issue_indexes.append(scheduled_issue_index)
        formal_issue_times.append(issue)
        if any(m2[name] != m1[name] for name in m1_shared_keys):
            raise ValueError("seasonal M1 and M2 shared fields differ")
        local = datetime.fromtimestamp(issue, tz=timezone.utc).astimezone(zone)
        quarter = _as_nonnegative_int(m1["quarter_hour_index"], "M1 quarter_hour_index")
        day_of_week = _as_nonnegative_int(m1["day_of_week"], "M1 day_of_week")
        is_weekend = _strict_bool(m1["is_weekend"], "M1 is_weekend")
        if (
            quarter != local.hour * 4 + local.minute // 15
            or day_of_week != local.weekday()
            or is_weekend != (local.weekday() >= 5)
        ):
            raise ValueError("seasonal M1 calendar does not match issue time")
        history_raw = m1["history_station_current_mean_a"]
        mask_raw = m1["history_observed_mask"]
        if not isinstance(history_raw, (list, tuple)) or not isinstance(mask_raw, (list, tuple)):
            raise TypeError("seasonal M1 history and mask must be sequences")
        if len(history_raw) != 96 or len(mask_raw) != 96:
            raise ValueError("seasonal M1 history and mask must each have 96 values")
        history = [
            _seasonal_optional_float(value, f"M1 row {position} history") for value in history_raw
        ]
        mask = [_strict_bool(value, f"M1 row {position} history mask") for value in mask_raw]
        station_position = (issue - start_epoch) // 900
        expected_history = station_current[station_position - 96 : station_position]
        expected_mask = station_valid[station_position - 96 : station_position] & ~np.isnan(
            expected_history
        )
        if not np.array_equal(np.asarray(mask, dtype=np.bool_), expected_mask) or not np.allclose(
            np.asarray(history, dtype=np.float64),
            np.where(expected_mask, expected_history, np.nan),
            rtol=1e-6,
            atol=1e-6,
            equal_nan=True,
        ):
            raise ValueError("seasonal M1 history does not match the station grid")
        connected = _as_nonnegative_int(m2["connected_session_count"], "M2 connected count")
        active = _as_nonnegative_int(m2["active_charging_session_count"], "M2 active count")
        if active > connected:
            raise ValueError("seasonal M2 active count exceeds connected count")
        current_state = [
            float(connected),
            float(active),
            _seasonal_optional_float(m2["station_current_a"], "M2 station current"),
            _as_finite(m2["station_current_observed_ratio"], "M2 observed ratio"),
            _seasonal_optional_float(m2["pilot_sum_a"], "M2 pilot sum"),
            _seasonal_optional_float(m2["pilot_mean_a"], "M2 pilot mean"),
        ]
        if not 0.0 <= current_state[3] <= 1.0:
            raise ValueError("seasonal M2 observed ratio must be in [0, 1]")
        if connected == 0 and not np.array_equal(
            np.asarray(current_state), np.asarray([0.0, 0.0, 0.0, 1.0, 0.0, 0.0])
        ):
            raise ValueError("seasonal M2 empty rows must use canonical zero/one semantics")
        raw_labels = label["labels"]
        if not isinstance(raw_labels, Mapping):
            raise TypeError("seasonal labels must be a mapping")
        _require_exact_keys(raw_labels, horizon_keys, f"seasonal label values {position}")
        label_values: list[float] = []
        for horizon in result.policy.horizons_minutes:
            value = _as_finite(raw_labels[str(horizon)], f"label {position} horizon {horizon}")
            target_position = station_position + horizon // 15 - 1
            expected_value = float(station_current[target_position])
            if not station_valid[target_position] or not math.isfinite(expected_value):
                raise ValueError("seasonal labels require complete valid station targets")
            if not math.isclose(value, expected_value, rel_tol=1e-6, abs_tol=1e-6):
                raise ValueError("seasonal label does not match its station target")
            label_values.append(value)
        histories.append(history)
        history_masks.append(mask)
        calendars.append([quarter, day_of_week, int(is_weekend)])
        current_states.append(current_state)
        labels.append(label_values)
    return (
        np.asarray(formal_issue_times, dtype=np.int64),
        np.asarray(scheduled_issue_indexes, dtype=np.int64),
        np.asarray(result.policy.horizons_minutes, dtype=np.int16),
        np.asarray(labels, dtype=np.float32),
        np.asarray(histories, dtype=np.float32),
        np.asarray(history_masks, dtype=np.bool_),
        np.asarray(calendars, dtype=np.int16),
        np.asarray(current_states, dtype=np.float32),
    )


def _validate_seasonal_m3_rows(
    result: IssueSnapshotResult,
    *,
    issue_times: np.ndarray,
    scheduled_issue_indexes: np.ndarray,
    current_states: np.ndarray,
) -> tuple[tuple[Mapping[str, Any], ...], tuple[tuple[Mapping[str, Any], ...], ...]]:
    if scheduled_issue_indexes.dtype != np.dtype(np.int64) or scheduled_issue_indexes.shape != (
        len(issue_times),
    ):
        raise ValueError("seasonal scheduled issue-index mapping is invalid")
    compact_positions = {
        int(scheduled_index): position
        for position, scheduled_index in enumerate(scheduled_issue_indexes)
    }
    if len(compact_positions) != len(issue_times):
        raise ValueError("seasonal scheduled issue-index mapping contains duplicates")
    normalized: list[Mapping[str, Any]] = []
    previous: tuple[int, int] | None = None
    for ordinal, source in enumerate(result.m3_rows):
        row = _validate_m3_row(dict(source), ordinal)
        issue_index = int(row["issue_index"])
        compact_position = compact_positions.get(issue_index)
        if compact_position is None or int(row["issue_time_utc_s"]) != int(
            issue_times[compact_position]
        ):
            raise ValueError("seasonal M3 row is not aligned to its issue index")
        key = (issue_index, int(row["anonymous_session_index"]))
        if previous is not None and key <= previous:
            raise ValueError("seasonal M3 rows must use canonical issue/session order")
        previous = key
        normalized.append(_FrozenMapping(row))
    rows = tuple(normalized)
    groups = group_by_canonical_issue_time(issue_times, rows)
    for position, group in enumerate(groups):
        currents = [
            _as_optional_finite(row["current_current_a"], "seasonal M3 current") for row in group
        ]
        pilots = [_as_optional_finite(row["current_pilot_a"], "seasonal M3 pilot") for row in group]
        finite_current = [value for value in currents if value is not None]
        finite_pilot = [value for value in pilots if value is not None]
        connected = len(group)
        expected = np.asarray(
            [
                connected,
                sum(value > result.policy.active_threshold_a for value in finite_current),
                sum(finite_current) if len(finite_current) == connected else math.nan,
                len(finite_current) / connected if connected else 1.0,
                sum(finite_pilot) if len(finite_pilot) == connected else math.nan,
                (
                    sum(finite_pilot) / connected
                    if connected and len(finite_pilot) == connected
                    else (0.0 if not connected else math.nan)
                ),
            ],
            dtype=np.float32,
        )
        if not np.allclose(
            current_states[position], expected, rtol=2e-5, atol=2e-6, equal_nan=True
        ):
            raise ValueError("seasonal M2 state does not match the M3 connected set")
    return rows, groups


def _require_canonical_seasonal_policy(
    policy: object,
    *,
    config: JPLMonthConfig,
) -> SnapshotPolicy:
    if type(policy) is not SnapshotPolicy:
        raise TypeError("seasonal snapshot policy must be an exact SnapshotPolicy")
    if (
        type(policy.lookback_minutes) is not int
        or policy.lookback_minutes != 1_440
        or type(policy.horizons_minutes) is not tuple
        or policy.horizons_minutes != EXPECTED_HORIZONS_MINUTES
        or any(type(value) is not int for value in policy.horizons_minutes)
        or type(policy.issue_step_minutes) is not int
        or policy.issue_step_minutes != 15
        or type(policy.max_hold_seconds) is not int
        or policy.max_hold_seconds != 12
        or type(policy.active_threshold_a) is not float
        or policy.active_threshold_a != 0.1
        or type(policy.tiers) is not tuple
        or policy.tiers != ("M1", "M2", "M3")
        or policy.tiers != config.tiers
    ):
        raise ValueError("seasonal snapshot policy fields differ from the canonical protocol")
    return policy


def build_seasonal_gate1_snapshot(
    result: IssueSnapshotResult,
    station_rows: Sequence[Mapping[str, Any]],
    *,
    config: JPLMonthConfig,
) -> Gate1Snapshot:
    """Validate and seal one canonical seasonal M1--M3 in-memory snapshot."""

    if (
        type(config) is not JPLMonthConfig
        or not is_canonical_jpl_month_config(config)
        or config.month not in SEASONAL_MONTHS
        or config.tiers != ("M1", "M2", "M3")
    ):
        raise ValueError("seasonal snapshot requires a canonical seasonal month config")
    if type(result) is not IssueSnapshotResult:
        raise TypeError("seasonal snapshot requires an IssueSnapshotResult")
    _require_canonical_seasonal_policy(result.policy, config=config)
    if result.m4_rows:
        raise ValueError("seasonal snapshots cannot contain M4 material")
    _validate_seasonal_table_schemas(result)
    issue_snapshot_sha256 = verified_issue_snapshot_sha256(result)
    materialized_station, station_times, station_current, station_valid = (
        _validate_seasonal_station_rows(station_rows, config=config)
    )
    try:
        _validate_seasonal_issue_qa(
            result,
            config=config,
            m3_row_count=len(result.m3_rows),
            station_current=station_current,
            station_valid=station_valid,
        )
    except TypeError as exc:
        raise ValueError("seasonal issue snapshot QA schema is invalid") from exc
    (
        issue_times,
        scheduled_issue_indexes,
        horizons,
        labels,
        history,
        history_mask,
        calendar,
        current_state,
    ) = _validate_seasonal_dense_rows(
        result,
        config=config,
        station_current=station_current,
        station_valid=station_valid,
    )
    m3_rows, m3_groups = _validate_seasonal_m3_rows(
        result,
        issue_times=issue_times,
        scheduled_issue_indexes=scheduled_issue_indexes,
        current_states=current_state,
    )
    artifact_values: Mapping[str, Any] = {
        "station_15min.jsonl.gz": materialized_station,
        "m1.jsonl.gz": result.m1_rows,
        "m2.jsonl.gz": result.m2_rows,
        "m3.jsonl.gz": result.m3_rows,
        "labels.jsonl.gz": result.label_rows,
    }
    if tuple(artifact_values) != SEASONAL_ARTIFACT_ROOTS:
        raise AssertionError("internal seasonal artifact order drift")
    artifacts = tuple(
        (name, _canonical_json_sha256(artifact_values[name])) for name in SEASONAL_ARTIFACT_ROOTS
    )
    data_snapshot_sha256 = _seasonal_data_snapshot_sha256(
        config,
        issue_snapshot_sha256=issue_snapshot_sha256,
        artifacts=artifacts,
    )
    snapshot = Gate1Snapshot(
        data_snapshot_sha256=data_snapshot_sha256,
        artifact_sha256=_FrozenMapping(dict(artifacts)),
        issue_times=_readonly(issue_times),
        horizons=_readonly(horizons),
        labels=_readonly(labels),
        m1_history=_readonly(history),
        m1_history_mask=_readonly(history_mask),
        m1_calendar=_readonly(calendar),
        m2_current_state=_readonly(current_state),
        m3_rows=m3_rows,
        m4_rows=(),
        m3_by_issue_time=m3_groups,
        m4_by_issue_time=(),
        station_times=_readonly(station_times),
        station_current_mean_a=_readonly(station_current),
        station_valid_90=_readonly(station_valid),
    )
    _issue_seasonal_snapshot_verification(
        snapshot,
        config=config,
        issue_snapshot_sha256=issue_snapshot_sha256,
    )
    verified_snapshot_provenance(snapshot)
    return snapshot


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
