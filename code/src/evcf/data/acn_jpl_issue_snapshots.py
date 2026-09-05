"""Leakage-safe issue-time snapshots for JPL Gate 1 preparation.

All feature values are frozen at the issue time.  Retrospective session outcomes and
private identifiers have no accepted input path in this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import weakref
from bisect import bisect_right
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Self
from zoneinfo import ZoneInfo

import numpy as np

BIN_MINUTES = 15
BIN_SECONDS = BIN_MINUTES * 60
JPL_TIMEZONE = "America/Los_Angeles"
_FORBIDDEN_FIELDS = (
    "kWhDelivered",
    "disconnectTime",
    "doneChargingTime",
    "future_current",
    "future_pilot",
    "future_userInputs",
    "userID",
    "sessionID",
    "_id",
)
_FORBIDDEN_NORMALIZED_KEYS = {
    "kwhdelivered",
    "offlinekwhdelivered",
    "disconnecttime",
    "disconnectutcs",
    "donechargingtime",
    "retrospectivedoneutcs",
    "futurecurrent",
    "futurepilot",
    "futureuserinputs",
    "userid",
    "sessionid",
    "id",
}
_LOCAL_STRUCTURAL_FIELDS = {
    "issue_index",
    "anonymous_session_index",
    "user_input_modified_utc_s",
    "current_start_offset_inclusive",
    "current_end_offset_exclusive",
    "pilot_start_offset_inclusive",
    "pilot_end_offset_exclusive",
    "min_visible_timestamp_utc_s",
    "max_visible_timestamp_utc_s",
}
_TIER_ORDER = ("M1", "M2", "M3", "M4")


class _FrozenTuple(tuple[Any, ...]):
    """Immutable tuple retaining value equality with legacy JSON lists."""

    __slots__ = ()
    __hash__ = None

    def __new__(cls, values: Iterable[Any] = ()) -> Self:
        return super().__new__(cls, values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (list, tuple)):
            return tuple(self) == tuple(other)
        return False

    def __ne__(self, other: object) -> bool:
        return not self == other


class _FrozenMapping(Mapping[str, Any]):
    """Tuple-backed mapping with no mutable container reachable from the object."""

    __slots__ = ("__items",)

    def __init__(self, value: Mapping[str, Any]) -> None:
        items: list[tuple[str, Any]] = []
        keys: set[str] = set()
        for key, item in value.items():
            name = str(key)
            if name in keys:
                raise ValueError("frozen mapping keys collide after string normalization")
            keys.add(name)
            items.append((name, _deep_freeze(item)))
        object.__setattr__(self, "_FrozenMapping__items", tuple(items))

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

    def __repr__(self) -> str:
        return repr(dict(self.__items))

    def __copy__(self) -> _FrozenMapping:
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> _FrozenMapping:
        return self

    def __reduce__(self) -> tuple[Any, tuple[tuple[tuple[str, Any], ...]]]:
        return _frozen_mapping_from_items, (self.__items,)


def _frozen_mapping_from_items(items: tuple[tuple[str, Any], ...]) -> _FrozenMapping:
    return _FrozenMapping(dict(items))


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenMapping(value)
    if isinstance(value, (list, tuple)):
        return _FrozenTuple(_deep_freeze(item) for item in value)
    return value


def _deep_thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


def _validate_tiers(tiers: object) -> tuple[str, ...]:
    if not isinstance(tiers, tuple):
        raise TypeError("tiers must be a tuple")
    if not tiers or tiers != _TIER_ORDER[: len(tiers)]:
        raise ValueError("tiers must be a nonempty cumulative M1 through M4 prefix")
    return tiers


@dataclass(frozen=True)
class SnapshotPolicy:
    """Explicit issue-time, lookback, horizon, and observation policy."""

    lookback_minutes: int = 24 * 60
    horizons_minutes: tuple[int, ...] = (15, 30, 60, 120, 240)
    issue_step_minutes: int = 15
    max_hold_seconds: int = 12
    active_threshold_a: float = 0.1
    tiers: tuple[str, ...] = _TIER_ORDER

    def __post_init__(self) -> None:
        _validate_tiers(self.tiers)
        if self.lookback_minutes <= 0 or self.lookback_minutes % BIN_MINUTES:
            raise ValueError("lookback must be a positive multiple of 15 minutes")
        if self.issue_step_minutes != BIN_MINUTES:
            raise ValueError("the first preparation protocol requires 15-minute issue steps")
        if not self.horizons_minutes or any(
            horizon <= 0 or horizon % BIN_MINUTES for horizon in self.horizons_minutes
        ):
            raise ValueError("horizons must be positive multiples of 15 minutes")
        if tuple(sorted(set(self.horizons_minutes))) != self.horizons_minutes:
            raise ValueError("horizons must be unique and sorted")
        if self.max_hold_seconds <= 0:
            raise ValueError("max hold must be positive")
        if not math.isfinite(self.active_threshold_a):
            raise ValueError("active threshold must be finite")


@dataclass(frozen=True, slots=True, weakref_slot=True)
class IssueSnapshotResult:
    """Local, anonymous snapshot tables plus aggregate QA."""

    m1_rows: tuple[Mapping[str, Any], ...]
    m2_rows: tuple[Mapping[str, Any], ...]
    m3_rows: tuple[Mapping[str, Any], ...]
    m4_rows: tuple[Mapping[str, Any], ...]
    label_rows: tuple[Mapping[str, Any], ...]
    qa: Mapping[str, Any]
    snapshot_sha256: str
    _policy: SnapshotPolicy = field(default_factory=SnapshotPolicy, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self._policy) is not SnapshotPolicy:
            raise TypeError("issue snapshot policy must be a SnapshotPolicy")
        samples = self.qa.get("samples") if isinstance(self.qa, Mapping) else None
        if not isinstance(samples, Mapping) or tuple(samples) != self._policy.tiers:
            raise ValueError("issue snapshot samples do not match the requested tiers")
        if "M4" not in self._policy.tiers and self.m4_rows:
            raise ValueError("M4 rows are forbidden when M4 was not requested")
        for name in ("m1_rows", "m2_rows", "m3_rows", "m4_rows", "label_rows"):
            rows = getattr(self, name)
            if not isinstance(rows, tuple) or any(not isinstance(row, Mapping) for row in rows):
                raise TypeError(f"{name} must be a tuple of mappings")
            object.__setattr__(self, name, tuple(_deep_freeze(row) for row in rows))
        object.__setattr__(self, "qa", _deep_freeze(self.qa))

    @property
    def policy(self) -> SnapshotPolicy:
        """Return the immutable policy bound directly to the result."""

        return self._policy

    @property
    def tier_rows(self) -> Mapping[str, tuple[Mapping[str, Any], ...]]:
        """Return an immutable view containing only the requested tier tables."""

        all_rows = {
            "M1": self.m1_rows,
            "M2": self.m2_rows,
            "M3": self.m3_rows,
            "M4": self.m4_rows,
        }
        requested = self._policy.tiers
        return MappingProxyType({tier: all_rows[tier] for tier in requested})


@dataclass(frozen=True, slots=True)
class _IssueSnapshotRegistration:
    binding_sha256: str
    snapshot_sha256: str
    process_seal: object


_ISSUE_SNAPSHOT_REGISTRY: dict[
    int,
    tuple[weakref.ReferenceType[IssueSnapshotResult], _IssueSnapshotRegistration],
] = {}
_ISSUE_SNAPSHOT_PROCESS_SEAL = object()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("snapshot boundaries must be timezone-aware")
    return value.astimezone(timezone.utc)


def issue_time_grid(
    start: datetime,
    end: datetime,
    policy: SnapshotPolicy,
) -> tuple[datetime, ...]:
    """Return formal issue times after lookback and before the longest horizon."""

    start_utc = _utc(start)
    end_utc = _utc(end)
    first = start_utc + timedelta(minutes=policy.lookback_minutes)
    last = end_utc - timedelta(minutes=max(policy.horizons_minutes))
    if last < first:
        return ()
    step = timedelta(minutes=policy.issue_step_minutes)
    count = int((last - first).total_seconds() // step.total_seconds()) + 1
    return tuple(first + index * step for index in range(count))


def feature_whitelist_document(
    tiers: tuple[str, ...] = _TIER_ORDER,
) -> dict[str, Any]:
    """Machine-readable cumulative feature allowlist for requested tiers."""

    requested = _validate_tiers(tiers)

    m1 = (
        "issue_time_utc_s",
        "quarter_hour_index",
        "day_of_week",
        "is_weekend",
        "history_station_current_mean_a",
        "history_observed_mask",
    )
    m2 = m1 + (
        "connected_session_count",
        "active_charging_session_count",
        "station_current_a",
        "station_current_observed_ratio",
        "pilot_sum_a",
        "pilot_mean_a",
    )
    m3 = m2 + (
        "elapsed_connection_s",
        "elapsed_charging_time_proxy_s",
        "current_current_a",
        "recent_current_mean_a",
        "recent_current_peak_a",
        "recent_current_observed_ratio",
        "cumulative_current_ah",
        "cumulative_current_observed_ratio",
        "current_pilot_a",
        "requested_departure_minutes_from_issue",
        "known_kwh_requested",
    )
    m4 = m3 + (
        "partial_current_trajectory_ref",
        "partial_pilot_trajectory_ref",
    )
    notes = {
        "anonymous_indexes": "local storage references only; never model features or Git data",
        "issue_time_rule": "all observations and user-input modifications are at or before issue time",
    }
    if "M4" in requested:
        notes["trajectory_window"] = "M4 references at most the frozen 24-hour lookback"
    all_tiers = {"M1": m1, "M2": m2, "M3": m3, "M4": m4}
    return {
        "schema_version": "acn-jpl-feature-whitelist/v1",
        "tiers": {tier: list(all_tiers[tier]) for tier in requested},
        "notes": notes,
    }


def feature_blacklist_document() -> dict[str, Any]:
    """Public semantic denylist without spelling private raw schema keys."""

    return {
        "schema_version": "acn-jpl-feature-blacklist/v1",
        "enforced_private_field_count": len(_FORBIDDEN_FIELDS),
        "forbidden_field_categories": [
            "final_delivered_energy",
            "real_future_disconnect_time",
            "real_future_done_charging_time",
            "post_issue_current_observations",
            "post_issue_pilot_observations",
            "post_issue_user_input_revisions",
            "user_identity_fields",
            "session_identity_fields",
            "database_identity_fields",
        ],
        "literal_private_schema_names_published": False,
    }


def _member(value: object, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _integer_member(value: object, *names: str) -> int | None:
    for name in names:
        candidate = _member(value, name)
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            return candidate
    return None


def _series_arrays(session: object, field: str) -> tuple[np.ndarray, np.ndarray]:
    series = _member(session, field)
    if series is None:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float64)
    raw_times = _member(series, "timestamps_utc_s")
    raw_values = _member(series, "values")
    if not isinstance(raw_times, Sequence) or isinstance(raw_times, (str, bytes)):
        raise TypeError(f"{field} timestamps must be a sequence")
    if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
        raise TypeError(f"{field} values must be a sequence")
    if len(raw_times) != len(raw_values):
        raise ValueError(f"{field} timestamp/value lengths differ")
    if any(isinstance(value, bool) for value in raw_times):
        raise TypeError(f"{field} timestamp cannot be boolean")
    times = np.asarray(raw_times, dtype=np.int64)
    values = np.asarray(raw_values, dtype=np.float64)
    if times.ndim != 1 or values.ndim != 1:
        raise ValueError(f"{field} arrays must be one-dimensional")
    if not bool(np.isfinite(values).all()):
        raise ValueError(f"{field} values must be finite")
    if times.size > 1 and bool(np.any(np.diff(times) <= 0)):
        raise ValueError(f"{field} timestamps must be strictly increasing")
    return times, values


def _segment_end(times: np.ndarray, index: int, max_hold_seconds: int) -> int:
    end = int(times[index]) + max_hold_seconds
    if index + 1 < len(times):
        end = min(end, int(times[index + 1]))
    return end


def _held_value_at(
    times: np.ndarray,
    values: np.ndarray,
    issue_epoch: int,
    *,
    connection_epoch: int,
    disconnect_epoch: int,
    max_hold_seconds: int,
) -> float | None:
    if not (connection_epoch <= issue_epoch < disconnect_epoch):
        return None
    index = bisect_right(times, issue_epoch) - 1
    if index < 0:
        return None
    if issue_epoch >= min(_segment_end(times, index, max_hold_seconds), disconnect_epoch):
        return None
    return float(values[index])


def _window_statistics(
    times: np.ndarray,
    values: np.ndarray,
    start_epoch: int,
    end_epoch: int,
    *,
    connection_epoch: int,
    disconnect_epoch: int,
    max_hold_seconds: int,
    active_threshold_a: float,
) -> dict[str, float | int | None]:
    start = max(start_epoch, connection_epoch)
    end = min(end_epoch, disconnect_epoch)
    if end <= start:
        return {"area": 0.0, "covered_seconds": 0, "active_seconds": 0, "peak": None}
    area = 0.0
    covered_seconds = 0
    active_seconds = 0
    peak: float | None = None
    begin_index = max(0, bisect_right(times, start) - 1)
    for index in range(begin_index, len(times)):
        sample_start = int(times[index])
        if sample_start >= end:
            break
        sample_end = min(
            _segment_end(times, index, max_hold_seconds),
            disconnect_epoch,
            end,
        )
        left = max(sample_start, start)
        if sample_end <= left:
            continue
        seconds = sample_end - left
        value = float(values[index])
        area += value * seconds
        covered_seconds += seconds
        if value > active_threshold_a:
            active_seconds += seconds
        peak = value if peak is None else max(peak, value)
    return {
        "area": area,
        "covered_seconds": covered_seconds,
        "active_seconds": active_seconds,
        "peak": peak,
    }


def _bounded_prefix_arrays(
    times: np.ndarray,
    values: np.ndarray,
    *,
    disconnect_epoch: int,
    max_hold_seconds: int,
    active_threshold_a: float,
) -> dict[str, np.ndarray]:
    count = len(times)
    if count == 0:
        return {
            "segment_ends": np.array([], dtype=np.int64),
            "area": np.zeros(1, dtype=np.float64),
            "observed": np.zeros(1, dtype=np.int64),
            "active": np.zeros(1, dtype=np.int64),
        }
    next_times = np.empty(count, dtype=np.int64)
    next_times[:-1] = times[1:]
    next_times[-1] = disconnect_epoch
    segment_ends = np.minimum(times + max_hold_seconds, next_times)
    segment_ends = np.minimum(segment_ends, disconnect_epoch)
    durations = np.maximum(segment_ends - times, 0).astype(np.int64, copy=False)
    area = np.zeros(count + 1, dtype=np.float64)
    observed = np.zeros(count + 1, dtype=np.int64)
    active = np.zeros(count + 1, dtype=np.int64)
    np.cumsum(values.astype(np.float64, copy=False) * durations, out=area[1:])
    np.cumsum(durations, out=observed[1:])
    np.cumsum(durations * (values > active_threshold_a), out=active[1:])
    return {
        "segment_ends": segment_ends,
        "area": area,
        "observed": observed,
        "active": active,
    }


def _prefix_at(
    times: np.ndarray,
    values: np.ndarray,
    prefix: Mapping[str, np.ndarray],
    epoch: int,
) -> tuple[float, int, int]:
    count = int(np.searchsorted(times, epoch, side="left"))
    area = float(prefix["area"][count])
    observed = int(prefix["observed"][count])
    active = int(prefix["active"][count])
    if count:
        last = count - 1
        segment_end = int(prefix["segment_ends"][last])
        if segment_end > epoch:
            excess = segment_end - epoch
            value = float(values[last])
            area -= value * excess
            observed -= excess
            if value > 0:
                active_duration = int(prefix["active"][last + 1] - prefix["active"][last])
                if active_duration:
                    active -= excess
    return area, observed, active


def _prepared_window_statistics(
    session: Mapping[str, Any],
    start_epoch: int,
    end_epoch: int,
) -> dict[str, float | int | None]:
    times = session["current_times"]
    values = session["current_values"]
    prefix = session["current_prefix"]
    end_area, end_observed, end_active = _prefix_at(times, values, prefix, end_epoch)
    start_area, start_observed, start_active = _prefix_at(times, values, prefix, start_epoch)
    first = int(np.searchsorted(prefix["segment_ends"], start_epoch, side="right"))
    last = int(np.searchsorted(times, end_epoch, side="left"))
    peak = float(np.max(values[first:last])) if last > first else None
    return {
        "area": end_area - start_area,
        "covered_seconds": end_observed - start_observed,
        "active_seconds": end_active - start_active,
        "peak": peak,
    }


def _known_user_input(session: object, issue_epoch: int) -> object | None:
    raw_inputs = _member(session, "user_inputs")
    if not isinstance(raw_inputs, Sequence) or isinstance(raw_inputs, (str, bytes)):
        return None
    known: list[tuple[int, int, object]] = []
    for ordinal, item in enumerate(raw_inputs):
        modified = _integer_member(item, "modified_utc_s", "modified_at_utc_s")
        if modified is not None and modified <= issue_epoch:
            known.append((modified, ordinal, item))
    return max(known, default=(0, -1, None), key=lambda value: (value[0], value[1]))[2]


def _optional_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _station_value(row: Mapping[str, Any]) -> float | None:
    return _optional_number(row.get("station_current_mean_a"))


def _valid_history_value(row: Mapping[str, Any]) -> float | None:
    known_incomplete = row.get("known_incomplete_current", False)
    if type(known_incomplete) is not bool:
        raise TypeError("known_incomplete_current must be a boolean")
    return _station_value(row) if bool(row.get("valid_bin_90")) and not known_incomplete else None


def _find_forbidden_keys(value: object, found: set[str]) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = "".join(
                character for character in str(key).casefold() if character.isalnum()
            )
            if normalized in _FORBIDDEN_NORMALIZED_KEYS:
                found.add(str(key))
            _find_forbidden_keys(nested, found)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _find_forbidden_keys(item, found)


def _unexpected_feature_keys(
    rows: Sequence[Mapping[str, Any]],
    *,
    tier: str,
    tiers: tuple[str, ...] = _TIER_ORDER,
) -> set[str]:
    allowed = set(feature_whitelist_document(tiers)["tiers"][tier]) | _LOCAL_STRUCTURAL_FIELDS
    return {key for row in rows for key in row if key not in allowed}


def _parse_iso_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("station timestamp must be an ISO string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("station timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("station timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _trajectory_start_offset(
    times: np.ndarray,
    *,
    lookback_start_epoch: int,
    max_hold_seconds: int,
) -> int:
    offset = int(np.searchsorted(times, lookback_start_epoch, side="left"))
    if offset > 0 and int(times[offset - 1]) + max_hold_seconds > lookback_start_epoch:
        return offset - 1
    return offset


def _validate_station_grid(
    station_rows: Sequence[Mapping[str, Any]],
    *,
    start: datetime,
    expected_bins: int,
) -> None:
    if len(station_rows) != expected_bins:
        raise ValueError("station row count does not cover the exact analysis grid")
    for index, row in enumerate(station_rows):
        expected = start + timedelta(seconds=index * BIN_SECONDS)
        if _parse_iso_utc(row.get("timestamp_utc")) != expected:
            raise ValueError("station rows must be ordered on a continuous 15-minute UTC grid")


def _canonical_hash(*tables: Sequence[Mapping[str, Any]], policy: SnapshotPolicy) -> str:
    policy_payload: dict[str, Any] = {
        "lookback_minutes": policy.lookback_minutes,
        "horizons_minutes": policy.horizons_minutes,
        "issue_step_minutes": policy.issue_step_minutes,
        "max_hold_seconds": policy.max_hold_seconds,
        "active_threshold_a": policy.active_threshold_a,
    }
    if policy.tiers != _TIER_ORDER:
        policy_payload["tiers"] = policy.tiers
    payload = {
        "policy": policy_payload,
        "tables": _deep_thaw(tables),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _issue_snapshot_tables(
    result: IssueSnapshotResult,
) -> tuple[Sequence[Mapping[str, Any]], ...]:
    all_rows = {
        "M1": result.m1_rows,
        "M2": result.m2_rows,
        "M3": result.m3_rows,
        "M4": result.m4_rows,
    }
    return tuple(all_rows[tier] for tier in result._policy.tiers) + (result.label_rows,)


def _require_deeply_frozen(value: Any, context: str) -> None:
    if isinstance(value, Mapping):
        if type(value) is not _FrozenMapping:
            raise ValueError(f"{context} must use the sealed immutable mapping type")
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{context} mapping keys must be strings")
            _require_deeply_frozen(nested, context)
        return
    if isinstance(value, tuple):
        if type(value) is not _FrozenTuple:
            raise ValueError(f"{context} nested sequences must use the sealed tuple type")
        for nested in value:
            _require_deeply_frozen(nested, context)
        return
    if isinstance(value, (list, dict, set, np.ndarray)):
        raise TypeError(f"{context} contains mutable nested material")
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise TypeError(f"{context} contains unsupported nested material")


def _validate_issue_snapshot_object(result: IssueSnapshotResult) -> None:
    if type(result._policy) is not SnapshotPolicy:
        raise TypeError("issue snapshot policy must be an exact SnapshotPolicy")
    _validate_tiers(result._policy.tiers)
    for name in ("m1_rows", "m2_rows", "m3_rows", "m4_rows", "label_rows"):
        rows = getattr(result, name)
        if type(rows) is not tuple:
            raise ValueError(f"issue snapshot {name} must use an immutable outer tuple")
        for row in rows:
            _require_deeply_frozen(row, f"issue snapshot {name}")
    _require_deeply_frozen(result.qa, "issue snapshot QA")


def _issue_snapshot_binding_sha256(result: IssueSnapshotResult) -> str:
    policy = result._policy
    payload = {
        "schema_version": "acn-jpl-issue-snapshot-process-binding/v1",
        "policy": {
            "lookback_minutes": policy.lookback_minutes,
            "horizons_minutes": list(policy.horizons_minutes),
            "issue_step_minutes": policy.issue_step_minutes,
            "max_hold_seconds": policy.max_hold_seconds,
            "active_threshold_a": policy.active_threshold_a,
            "tiers": list(policy.tiers),
        },
        "m1_rows": _deep_thaw(result.m1_rows),
        "m2_rows": _deep_thaw(result.m2_rows),
        "m3_rows": _deep_thaw(result.m3_rows),
        "m4_rows": _deep_thaw(result.m4_rows),
        "label_rows": _deep_thaw(result.label_rows),
        "qa": _deep_thaw(result.qa),
        "snapshot_sha256": result.snapshot_sha256,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _register_issue_snapshot(result: IssueSnapshotResult) -> None:
    _validate_issue_snapshot_object(result)
    recomputed = _canonical_hash(*_issue_snapshot_tables(result), policy=result._policy)
    if recomputed != result.snapshot_sha256:
        raise ValueError("builder produced an inconsistent issue snapshot hash")
    identity = id(result)
    registration = _IssueSnapshotRegistration(
        binding_sha256=_issue_snapshot_binding_sha256(result),
        snapshot_sha256=result.snapshot_sha256,
        process_seal=_ISSUE_SNAPSHOT_PROCESS_SEAL,
    )

    def discard(reference: weakref.ReferenceType[IssueSnapshotResult]) -> None:
        current = _ISSUE_SNAPSHOT_REGISTRY.get(identity)
        if current is not None and current[0] is reference:
            _ISSUE_SNAPSHOT_REGISTRY.pop(identity, None)

    reference = weakref.ref(result, discard)
    _ISSUE_SNAPSHOT_REGISTRY[identity] = (reference, registration)


def verified_issue_snapshot_sha256(result: IssueSnapshotResult) -> str:
    """Verify one live builder-issued result against its process-local identity seal."""

    if type(result) is not IssueSnapshotResult:
        raise TypeError("snapshot hash verification requires an IssueSnapshotResult")
    entry = _ISSUE_SNAPSHOT_REGISTRY.get(id(result))
    if (
        entry is None
        or entry[0]() is not result
        or entry[1].process_seal is not _ISSUE_SNAPSHOT_PROCESS_SEAL
    ):
        raise ValueError("issue snapshot has no live builder process seal")
    _validate_issue_snapshot_object(result)
    if (
        not isinstance(result.snapshot_sha256, str)
        or len(result.snapshot_sha256) != 64
        or any(character not in "0123456789abcdef" for character in result.snapshot_sha256)
    ):
        raise ValueError("issue snapshot SHA-256 is invalid")
    recomputed = _canonical_hash(*_issue_snapshot_tables(result), policy=result._policy)
    if recomputed != result.snapshot_sha256:
        raise ValueError("issue snapshot hash differs from its canonical tables")
    registration = entry[1]
    if (
        registration.snapshot_sha256 != result.snapshot_sha256
        or registration.binding_sha256 != _issue_snapshot_binding_sha256(result)
    ):
        raise ValueError("issue snapshot content differs from its builder process seal")
    return recomputed


def _missing_rate(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    if not rows:
        return None
    return round(sum(row.get(field) is None for row in rows) / len(rows), 8)


def _integer_distribution(values: Sequence[int]) -> dict[str, int | float | None]:
    if not values:
        return {
            "count": 0,
            "zero_count": 0,
            "minimum": None,
            "median": None,
            "p95": None,
            "maximum": None,
        }
    ordered = np.asarray(sorted(values), dtype=np.int64)
    return {
        "count": len(values),
        "zero_count": sum(value == 0 for value in values),
        "minimum": int(ordered[0]),
        "median": float(np.quantile(ordered, 0.50)),
        "p95": float(np.quantile(ordered, 0.95)),
        "maximum": int(ordered[-1]),
    }


def build_issue_snapshots(
    station_rows: Sequence[Mapping[str, Any]],
    sessions: Iterable[object],
    *,
    start_utc: datetime,
    end_utc: datetime,
    policy: SnapshotPolicy,
    preserve_unobserved_trajectory_missingness: bool = False,
) -> IssueSnapshotResult:
    """Build snapshots with exact issue-time truncation and future labels.

    The default preserves the frozen May artifact bytes. Seasonal preparation
    explicitly enables unobserved cumulative-trajectory nulls and their QA rates.
    """

    if type(preserve_unobserved_trajectory_missingness) is not bool:
        raise TypeError("preserve_unobserved_trajectory_missingness must be a boolean")
    start = _utc(start_utc)
    end = _utc(end_utc)
    expected_bins = int((end - start).total_seconds() // BIN_SECONDS)
    _validate_station_grid(station_rows, start=start, expected_bins=expected_bins)
    issues = issue_time_grid(start, end, policy)
    start_epoch = int(start.timestamp())
    lookback_bins = policy.lookback_minutes // BIN_MINUTES
    local_zone = ZoneInfo(JPL_TIMEZONE)
    include_m2 = "M2" in policy.tiers
    include_m3 = "M3" in policy.tiers
    include_m4 = "M4" in policy.tiers

    prepared_sessions: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    for fallback_index, session in enumerate(sessions):
        anonymous_index = _integer_member(session, "anonymous_session_index", "session_index")
        if anonymous_index is None:
            anonymous_index = fallback_index
        if anonymous_index in seen_indexes:
            raise ValueError("anonymous session indexes must be unique")
        seen_indexes.add(anonymous_index)
        connection = _integer_member(session, "connection_utc_s")
        disconnect = _integer_member(session, "disconnect_utc_s")
        if connection is None or disconnect is None or disconnect <= connection:
            raise ValueError("cleaned session bounds are invalid")
        current_times, current_values = _series_arrays(session, "current")
        pilot_times, pilot_values = _series_arrays(session, "pilot")
        prepared_sessions.append(
            {
                "anonymous_index": anonymous_index,
                "connection": connection,
                "disconnect": disconnect,
                "current_times": current_times,
                "current_values": current_values,
                "current_prefix": _bounded_prefix_arrays(
                    current_times,
                    current_values,
                    disconnect_epoch=disconnect,
                    max_hold_seconds=policy.max_hold_seconds,
                    active_threshold_a=policy.active_threshold_a,
                ),
                "pilot_times": pilot_times,
                "pilot_values": pilot_values,
                "user_inputs": _member(session, "user_inputs"),
            }
        )
    prepared_sessions.sort(key=lambda item: item["anonymous_index"])

    m1_rows: list[dict[str, Any]] = []
    m2_rows: list[dict[str, Any]] = []
    m3_rows: list[dict[str, Any]] = []
    m4_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    valid_labels = {str(horizon): 0 for horizon in policy.horizons_minutes}
    incomplete_label_issue_times = 0
    known_user_input_rows = 0
    user_input_rows = 0

    for issue_index, issue in enumerate(issues):
        issue_epoch = int(issue.timestamp())
        bin_index = (issue_epoch - start_epoch) // BIN_SECONDS
        history = station_rows[bin_index - lookback_bins : bin_index]
        if len(history) != lookback_bins:
            raise ValueError("formal issue time is missing its complete lookback")
        labels: dict[str, float | None] = {}
        for horizon in policy.horizons_minutes:
            target_index = bin_index + horizon // BIN_MINUTES - 1
            target_row = station_rows[target_index]
            target = _valid_history_value(target_row)
            labels[str(horizon)] = target
            if target is not None:
                valid_labels[str(horizon)] += 1
        if any(value is None for value in labels.values()):
            incomplete_label_issue_times += 1
            continue
        label_rows.append(
            {"issue_index": issue_index, "issue_time_utc_s": issue_epoch, "labels": labels}
        )
        local = issue.astimezone(local_zone)
        m1 = {
            "issue_index": issue_index,
            "issue_time_utc_s": issue_epoch,
            "quarter_hour_index": local.hour * 4 + local.minute // 15,
            "day_of_week": local.weekday(),
            "is_weekend": local.weekday() >= 5,
            "history_station_current_mean_a": [_valid_history_value(row) for row in history],
            "history_observed_mask": [_valid_history_value(row) is not None for row in history],
        }
        m1_rows.append(m1)
        if not include_m2:
            continue

        connected_sessions = [
            session
            for session in prepared_sessions
            if session["connection"] <= issue_epoch < session["disconnect"]
        ]
        current_values: list[float] = []
        pilot_values: list[float] = []
        # Observed-active lower bound; unobserved current remains explicit in the
        # independent observed ratio and nullable M3 fields, never known inactive.
        active_count = 0
        session_current: dict[int, float | None] = {}
        for session in connected_sessions:
            current_value = _held_value_at(
                session["current_times"],
                session["current_values"],
                issue_epoch,
                connection_epoch=session["connection"],
                disconnect_epoch=session["disconnect"],
                max_hold_seconds=policy.max_hold_seconds,
            )
            pilot_value = _held_value_at(
                session["pilot_times"],
                session["pilot_values"],
                issue_epoch,
                connection_epoch=session["connection"],
                disconnect_epoch=session["disconnect"],
                max_hold_seconds=policy.max_hold_seconds,
            )
            session_current[session["anonymous_index"]] = current_value
            if current_value is not None:
                current_values.append(current_value)
                if current_value > policy.active_threshold_a:
                    active_count += 1
            if pilot_value is not None:
                pilot_values.append(pilot_value)

        connected_count = len(connected_sessions)
        current_complete = len(current_values) == connected_count
        pilot_complete = len(pilot_values) == connected_count
        m2 = {
            **m1,
            "connected_session_count": connected_count,
            "active_charging_session_count": active_count,
            "station_current_a": sum(current_values) if current_complete else None,
            "station_current_observed_ratio": (
                len(current_values) / connected_count if connected_count else 1.0
            ),
            "pilot_sum_a": sum(pilot_values) if pilot_complete else None,
            "pilot_mean_a": (
                sum(pilot_values) / connected_count
                if connected_count and pilot_complete
                else (0.0 if not connected_count else None)
            ),
        }
        m2_rows.append(m2)
        if not include_m3:
            continue

        for session in connected_sessions:
            recent = _prepared_window_statistics(
                session,
                issue_epoch - BIN_SECONDS,
                issue_epoch,
            )
            cumulative = _prepared_window_statistics(
                session,
                session["connection"],
                issue_epoch,
            )
            cumulative_observed_seconds = int(cumulative["covered_seconds"])
            cumulative_trajectory_missing = bool(
                preserve_unobserved_trajectory_missingness
                and not cumulative_observed_seconds
            )
            current_pilot = _held_value_at(
                session["pilot_times"],
                session["pilot_values"],
                issue_epoch,
                connection_epoch=session["connection"],
                disconnect_epoch=session["disconnect"],
                max_hold_seconds=policy.max_hold_seconds,
            )
            known_input = _known_user_input({"user_inputs": session["user_inputs"]}, issue_epoch)
            user_input_rows += 1
            modified: int | None = None
            requested_departure: int | None = None
            requested_kwh: float | None = None
            if known_input is not None:
                known_user_input_rows += 1
                modified = _integer_member(known_input, "modified_utc_s", "modified_at_utc_s")
                requested_departure = _integer_member(
                    known_input,
                    "requested_departure_utc_s",
                )
                requested_kwh = _optional_number(
                    _member(known_input, "kwh_requested")
                    if _member(known_input, "kwh_requested") is not None
                    else _member(known_input, "kWhRequested")
                )
            m3_rows.append(
                {
                    "issue_index": issue_index,
                    "issue_time_utc_s": issue_epoch,
                    "anonymous_session_index": session["anonymous_index"],
                    "elapsed_connection_s": issue_epoch - session["connection"],
                    "elapsed_charging_time_proxy_s": (
                        None
                        if cumulative_trajectory_missing
                        else cumulative["active_seconds"]
                    ),
                    "current_current_a": session_current[session["anonymous_index"]],
                    "recent_current_mean_a": (
                        float(recent["area"]) / int(recent["covered_seconds"])
                        if recent["covered_seconds"]
                        else None
                    ),
                    "recent_current_peak_a": recent["peak"],
                    "recent_current_observed_ratio": (int(recent["covered_seconds"]) / BIN_SECONDS),
                    "cumulative_current_ah": (
                        None
                        if cumulative_trajectory_missing
                        else float(cumulative["area"]) / 3600
                    ),
                    "cumulative_current_observed_ratio": (
                        cumulative_observed_seconds / (issue_epoch - session["connection"])
                        if issue_epoch > session["connection"]
                        else 0.0
                    ),
                    "current_pilot_a": current_pilot,
                    "user_input_modified_utc_s": modified,
                    "requested_departure_minutes_from_issue": (
                        (requested_departure - issue_epoch) / 60
                        if requested_departure is not None
                        else None
                    ),
                    "known_kwh_requested": requested_kwh,
                }
            )

            current_value = session_current[session["anonymous_index"]]
            if (
                include_m4
                and current_value is not None
                and current_value > policy.active_threshold_a
            ):
                lookback_start_epoch = issue_epoch - policy.lookback_minutes * 60
                current_start = _trajectory_start_offset(
                    session["current_times"],
                    lookback_start_epoch=lookback_start_epoch,
                    max_hold_seconds=policy.max_hold_seconds,
                )
                current_end = bisect_right(session["current_times"], issue_epoch)
                pilot_start = _trajectory_start_offset(
                    session["pilot_times"],
                    lookback_start_epoch=lookback_start_epoch,
                    max_hold_seconds=policy.max_hold_seconds,
                )
                pilot_end = bisect_right(session["pilot_times"], issue_epoch)
                first_current = (
                    int(session["current_times"][current_start])
                    if current_start < current_end
                    else None
                )
                first_pilot = (
                    int(session["pilot_times"][pilot_start]) if pilot_start < pilot_end else None
                )
                last_current = (
                    int(session["current_times"][current_end - 1])
                    if current_start < current_end
                    else None
                )
                last_pilot = (
                    int(session["pilot_times"][pilot_end - 1]) if pilot_start < pilot_end else None
                )
                visible = [value for value in (last_current, last_pilot) if value is not None]
                first_visible = [
                    value for value in (first_current, first_pilot) if value is not None
                ]
                m4_rows.append(
                    {
                        "issue_index": issue_index,
                        "issue_time_utc_s": issue_epoch,
                        "anonymous_session_index": session["anonymous_index"],
                        "current_start_offset_inclusive": current_start,
                        "current_end_offset_exclusive": current_end,
                        "pilot_start_offset_inclusive": pilot_start,
                        "pilot_end_offset_exclusive": pilot_end,
                        "min_visible_timestamp_utc_s": (
                            min(first_visible) if first_visible else None
                        ),
                        "max_visible_timestamp_utc_s": max(visible) if visible else None,
                        "partial_current_trajectory_ref": "cleaned_current_prefix",
                        "partial_pilot_trajectory_ref": "cleaned_pilot_prefix",
                    }
                )

    tier_tables: dict[str, list[dict[str, Any]]] = {
        "M1": m1_rows,
        "M2": m2_rows,
        "M3": m3_rows,
        "M4": m4_rows,
    }
    future_fields: set[str] = set()
    for tier in policy.tiers:
        _find_forbidden_keys(tier_tables[tier], future_fields)
    unexpected_feature_keys = set().union(
        *(
            _unexpected_feature_keys(
                tier_tables[tier],
                tier=tier,
                tiers=policy.tiers,
            )
            for tier in policy.tiers
        )
    )
    late_user_input_rows = sum(
        row["user_input_modified_utc_s"] is not None
        and row["user_input_modified_utc_s"] > row["issue_time_utc_s"]
        for row in m3_rows
    )
    future_trajectory_rows = sum(
        row["max_visible_timestamp_utc_s"] is not None
        and row["max_visible_timestamp_utc_s"] > row["issue_time_utc_s"]
        for row in m4_rows
    )
    overlong_trajectory_rows = sum(
        row["min_visible_timestamp_utc_s"] is not None
        and row["min_visible_timestamp_utc_s"]
        < row["issue_time_utc_s"] - policy.lookback_minutes * 60 - policy.max_hold_seconds
        for row in m4_rows
    )
    temporal_violations = late_user_input_rows
    if include_m4:
        temporal_violations += future_trajectory_rows + overlong_trajectory_rows
    leakage_status = (
        "PASS"
        if not future_fields and not unexpected_feature_keys and temporal_violations == 0
        else "FAIL"
    )
    history_values = [value for row in m1_rows for value in row["history_station_current_mean_a"]]
    history_missing = sum(value is None for value in history_values)
    ragged_rows: dict[str, int] = {}
    if include_m3:
        ragged_rows["M3"] = len(m3_rows)
    if include_m4:
        ragged_rows["M4"] = len(m4_rows)
    shapes: dict[str, Any] = {"M1_history": [len(m1_rows), lookback_bins]}
    if include_m2:
        shapes["M2_dense"] = [len(m2_rows), 6]
    if include_m3:
        shapes.update(
            {
                "M3_ragged_rows": len(m3_rows),
                "M3_session_feature_width": 11,
            }
        )
    if include_m4:
        shapes.update(
            {
                "M4_ragged_rows": len(m4_rows),
                "M4_reference_width": 2,
            }
        )
    shapes["labels"] = [len(label_rows), len(policy.horizons_minutes)]
    missing_rates: dict[str, float | None] = {
        "M1_history": round(history_missing / len(history_values), 8) if history_values else None
    }
    if include_m2:
        missing_rates.update(
            {
                "M2_station_current": (
                    round(
                        sum(row["station_current_a"] is None for row in m2_rows) / len(m2_rows),
                        8,
                    )
                    if m2_rows
                    else None
                ),
                "M2_pilot_sum": _missing_rate(m2_rows, "pilot_sum_a"),
                "M2_pilot_mean": _missing_rate(m2_rows, "pilot_mean_a"),
            }
        )
    if include_m3:
        missing_rates.update(
            {
                "M3_current_current": _missing_rate(m3_rows, "current_current_a"),
                "M3_recent_current_mean": _missing_rate(m3_rows, "recent_current_mean_a"),
                "M3_recent_current_peak": _missing_rate(m3_rows, "recent_current_peak_a"),
                "M3_current_pilot": _missing_rate(m3_rows, "current_pilot_a"),
                "M3_known_requested_departure": _missing_rate(
                    m3_rows, "requested_departure_minutes_from_issue"
                ),
                "M3_known_requested_energy": _missing_rate(m3_rows, "known_kwh_requested"),
            }
        )
        if preserve_unobserved_trajectory_missingness:
            missing_rates.update(
                {
                    "M3_elapsed_charging_time_proxy": _missing_rate(
                        m3_rows, "elapsed_charging_time_proxy_s"
                    ),
                    "M3_cumulative_current_ah": _missing_rate(
                        m3_rows, "cumulative_current_ah"
                    ),
                }
            )
    qa = {
        "schema_version": "acn-jpl-issue-snapshot-qa/v1",
        "lookback_minutes": policy.lookback_minutes,
        "horizons_minutes": list(policy.horizons_minutes),
        "issue_times": len(issues),
        "formal_issue_times": len(m1_rows),
        "incomplete_label_issue_times": incomplete_label_issue_times,
        "samples": {tier: len(m1_rows) for tier in policy.tiers},
        "ragged_rows": ragged_rows,
        "valid_labels_by_horizon": valid_labels,
        "shapes": shapes,
        "missing_rates": missing_rates,
        "leakage_audit": leakage_status,
        "future_fields_found": sorted(future_fields),
        "unexpected_feature_keys": sorted(unexpected_feature_keys),
        "temporal_violations": {"total": temporal_violations},
        "feature_whitelist_enforcement": {
            "status": "PASS" if not unexpected_feature_keys else "FAIL",
            "unexpected_key_count": len(unexpected_feature_keys),
        },
        "occupancy_rate": {
            "status": "NOT_CONSTRUCTED",
            "reason": "Issue #17 supplies no frozen JPL capacity denominator",
        },
    }
    if include_m3:
        qa["temporal_violations"]["late_user_input_rows"] = late_user_input_rows
        qa["user_inputs_issue_time_truncation"] = {
            "status": "PASS" if late_user_input_rows == 0 else "FAIL",
            "connected_session_rows": user_input_rows,
            "rows_with_known_input": known_user_input_rows,
            "rule": "last modifiedAt at or before issue time",
        }
    if include_m4:
        qa["M4_prefix_length_distribution"] = {
            "current": _integer_distribution(
                [
                    int(row["current_end_offset_exclusive"])
                    - int(row["current_start_offset_inclusive"])
                    for row in m4_rows
                ]
            ),
            "pilot": _integer_distribution(
                [
                    int(row["pilot_end_offset_exclusive"])
                    - int(row["pilot_start_offset_inclusive"])
                    for row in m4_rows
                ]
            ),
        }
        qa["temporal_violations"].update(
            {
                "future_trajectory_rows": future_trajectory_rows,
                "overlong_trajectory_rows": overlong_trajectory_rows,
            }
        )
    else:
        qa["m4_generated"] = False
    tables: tuple[Sequence[Mapping[str, Any]], ...] = tuple(
        tier_tables[tier] for tier in policy.tiers
    ) + (label_rows,)
    snapshot_hash = _canonical_hash(*tables, policy=policy)
    result = IssueSnapshotResult(
        m1_rows=tuple(m1_rows),
        m2_rows=tuple(m2_rows),
        m3_rows=tuple(m3_rows),
        m4_rows=tuple(m4_rows),
        label_rows=tuple(label_rows),
        qa=qa,
        snapshot_sha256=snapshot_hash,
        _policy=policy,
    )
    _register_issue_snapshot(result)
    return result
