"""Frozen, leakage-safe M1--M4 feature encoders for the JPL Gate 1 pilot.

The canonical time vector is retained only as :class:`FeatureBlock` row index.
It is never concatenated into ``values``.  M4 is accumulated while the verified
loader exposes one bounded causal session prefix at a time; only the 36 numeric
session summaries are retained until their issue group is pooled.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any

import numpy as np

from evcf.forecasting.acn_jpl_gate1_data import (
    EXPECTED_ISSUE_COUNT,
    CausalSessionSeries,
    Gate1Snapshot,
)

FIXED_POOL_STAT_NAMES = (
    "count",
    "sum",
    "mean",
    "std",
    "minimum",
    "maximum",
    "p25",
    "p50",
    "p75",
    "missing_count",
)
M2_STATE_FEATURE_NAMES = (
    "connected_session_count",
    "active_charging_session_count",
    "station_current_a",
    "station_current_observed_ratio",
    "pilot_sum_a",
    "pilot_mean_a",
)
M3_SESSION_FIELDS = (
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
M4_WINDOWS_MINUTES = (5, 15, 30, 60)
M4_SESSION_STAT_NAMES = (
    "current_mean_a",
    "current_maximum_a",
    "current_minimum_a",
    "current_std_a",
    "current_slope_a_per_min",
    "current_nonzero_fraction",
    "current_observed_ratio",
    "pilot_minus_current_mean_a",
    "pilot_minus_current_maximum_a",
)

_POOL_NULLABLE = np.asarray(
    [False, False, True, True, True, True, True, True, True, False], dtype=np.bool_
)
_M2_NULLABLE = np.asarray([False, False, True, False, True, True], dtype=np.bool_)
_M1_RAW_DIMENSION = 195
_M2_RAW_DIMENSION = 201
_M3_RAW_DIMENSION = 311
_M4_RAW_DIMENSION = 671
_HOLD_CAP_SECONDS = 12
_ACTIVE_THRESHOLD_A = 0.1

_M1_FEATURE_NAMES = (
    tuple(f"history_station_current_mean_a_lag_{lag:03d}" for lag in range(96, 0, -1))
    + tuple(f"history_observed_mask_lag_{lag:03d}" for lag in range(96, 0, -1))
    + ("quarter_hour_index", "day_of_week", "is_weekend")
)
_M2_FEATURE_NAMES = _M1_FEATURE_NAMES + M2_STATE_FEATURE_NAMES
_M3_FEATURE_NAMES = _M2_FEATURE_NAMES + tuple(
    f"m3_{field}_{stat}" for field in M3_SESSION_FIELDS for stat in FIXED_POOL_STAT_NAMES
)
_M4_FEATURE_NAMES = _M3_FEATURE_NAMES + tuple(
    f"m4_window_{window:02d}m_{stat}_{pool}"
    for window in M4_WINDOWS_MINUTES
    for stat in M4_SESSION_STAT_NAMES
    for pool in FIXED_POOL_STAT_NAMES
)
_EXPECTED_FEATURE_NAMES: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "M1": _M1_FEATURE_NAMES,
        "M2": _M2_FEATURE_NAMES,
        "M3": _M3_FEATURE_NAMES,
        "M4": _M4_FEATURE_NAMES,
    }
)
_M1_NULLABLE_MASK = (False,) * _M1_RAW_DIMENSION
_M2_NULLABLE_MASK = _M1_NULLABLE_MASK + tuple(bool(value) for value in _M2_NULLABLE)
_M3_NULLABLE_MASK = _M2_NULLABLE_MASK + tuple(
    bool(value) for value in np.tile(_POOL_NULLABLE, len(M3_SESSION_FIELDS))
)
_M4_NULLABLE_MASK = _M3_NULLABLE_MASK + tuple(bool(value) for value in np.tile(_POOL_NULLABLE, 36))
_EXPECTED_NULLABLE_MASKS: Mapping[str, tuple[bool, ...]] = MappingProxyType(
    {
        "M1": _M1_NULLABLE_MASK,
        "M2": _M2_NULLABLE_MASK,
        "M3": _M3_NULLABLE_MASK,
        "M4": _M4_NULLABLE_MASK,
    }
)
_EXPECTED_RAW_DIMENSIONS: Mapping[str, int] = MappingProxyType(
    {
        "M1": _M1_RAW_DIMENSION,
        "M2": _M2_RAW_DIMENSION,
        "M3": _M3_RAW_DIMENSION,
        "M4": _M4_RAW_DIMENSION,
    }
)


def _immutable(array: np.ndarray, *, dtype: np.dtype[Any] | None = None) -> np.ndarray:
    contiguous = np.ascontiguousarray(array, dtype=dtype)
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype).reshape(
        contiguous.shape
    )


def _strict_integer(value: Any, context: str, *, nonnegative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{context} must be an integer")
    result = int(value)
    if nonnegative and result < 0:
        raise ValueError(f"{context} must be nonnegative")
    return result


def _strict_optional_number(value: Any, context: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{context} must be numeric or missing")
    result = float(value)
    if math.isnan(result):
        return None
    if not math.isfinite(result):
        raise ValueError(f"{context} must not contain infinite values")
    return result


def _validate_issue_times(value: Any, context: str) -> np.ndarray:
    times = np.asarray(value)
    if times.dtype != np.dtype(np.int64) or times.ndim != 1:
        raise ValueError(f"{context} index must be a one-dimensional int64 array")
    if not len(times) or np.any(np.diff(times) <= 0):
        raise ValueError(f"{context} index must be nonempty, strictly increasing, and unique")
    return times


@dataclass(frozen=True, slots=True)
class FeatureBlock:
    """Immutable raw matrix plus its non-feature row index and fixed indicator mask.

    ``nullable_mask`` identifies raw columns that receive an additional fixed
    missing-indicator column.  It does *not* identify every raw column that may
    contain NaN: M1 history columns already have their 96 explicit observation
    masks and therefore deliberately have ``nullable_mask=False``.
    """

    issue_times: np.ndarray
    values: np.ndarray
    feature_names: tuple[str, ...]
    nullable_mask: np.ndarray

    def __post_init__(self) -> None:
        issue_times = _validate_issue_times(self.issue_times, "feature block")
        values = np.asarray(self.values)
        nullable = np.asarray(self.nullable_mask)
        names = tuple(self.feature_names)
        if values.ndim != 2 or values.shape[0] != len(issue_times):
            raise ValueError("feature values must be a two-dimensional row-aligned matrix")
        if not np.issubdtype(values.dtype, np.number) or np.issubdtype(values.dtype, np.bool_):
            raise TypeError("feature values must be a numeric non-boolean matrix")
        if np.any(np.isinf(values)):
            raise ValueError("feature values must not contain infinite values")
        if len(names) != values.shape[1]:
            raise ValueError("feature_names length must equal the matrix width")
        if any(not isinstance(name, str) or not name for name in names):
            raise TypeError("feature_names must be nonempty strings")
        if len(set(names)) != len(names):
            raise ValueError("feature_names must be unique")
        if nullable.dtype != np.dtype(np.bool_) or nullable.shape != (values.shape[1],):
            raise ValueError("nullable_mask must be a boolean vector matching the matrix width")
        object.__setattr__(self, "issue_times", _immutable(issue_times))
        object.__setattr__(self, "values", _immutable(values, dtype=np.dtype(np.float64)))
        object.__setattr__(self, "feature_names", names)
        object.__setattr__(self, "nullable_mask", _immutable(nullable))


def fixed_pool(
    values: Sequence[float | None] | np.ndarray,
    *,
    total_count: int | None = None,
) -> np.ndarray:
    """Return the frozen ten-stat finite-only pool in declared order."""

    if isinstance(values, (str, bytes)):
        raise TypeError("pool values must be a one-dimensional numeric sequence")
    raw = list(values)
    if total_count is None:
        total = len(raw)
    else:
        total = _strict_integer(total_count, "total_count", nonnegative=True)
    if len(raw) != total:
        raise ValueError("pool values length must equal total_count")
    finite: list[float] = []
    for ordinal, value in enumerate(raw):
        parsed = _strict_optional_number(value, f"pool value {ordinal}")
        if parsed is not None:
            finite.append(parsed)
    observed = len(finite)
    missing = total - observed
    if not observed:
        return np.asarray(
            [0.0, 0.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, missing],
            dtype=np.float64,
        )
    array = np.asarray(finite, dtype=np.float64)
    quantiles = np.quantile(array, [0.25, 0.5, 0.75], method="linear")
    return np.asarray(
        [
            observed,
            float(np.sum(array)),
            float(np.mean(array)),
            float(np.std(array, ddof=0)),
            float(np.min(array)),
            float(np.max(array)),
            float(quantiles[0]),
            float(quantiles[1]),
            float(quantiles[2]),
            missing,
        ],
        dtype=np.float64,
    )


def _require_prefix(parent: FeatureBlock, child_times: np.ndarray, width: int) -> None:
    if parent.values.shape[1] != width:
        raise ValueError(f"parent feature block must have width {width}")
    if not np.array_equal(parent.issue_times, child_times):
        raise ValueError("feature block indexes do not match the canonical index")


def _require_exact_block(
    candidate: FeatureBlock,
    expected: FeatureBlock,
    context: str,
) -> None:
    if not isinstance(candidate, FeatureBlock):
        raise TypeError(f"{context} parent must be a FeatureBlock")
    if not np.array_equal(candidate.issue_times, expected.issue_times):
        raise ValueError(f"{context} parent index differs from the snapshot source")
    if candidate.feature_names != expected.feature_names:
        raise ValueError(f"{context} parent feature names differ from the snapshot source")
    if not np.array_equal(candidate.nullable_mask, expected.nullable_mask):
        raise ValueError(f"{context} parent nullable mask differs from the snapshot source")
    if not np.array_equal(candidate.values, expected.values, equal_nan=True):
        raise ValueError(f"{context} parent values differ from the snapshot source")


def encode_m1(snapshot: Gate1Snapshot) -> FeatureBlock:
    """Encode 96 oldest-to-newest history values, masks, and calendar fields."""

    times = _validate_issue_times(snapshot.issue_times, "M1")
    history = np.asarray(snapshot.m1_history)
    mask = np.asarray(snapshot.m1_history_mask)
    calendar = np.asarray(snapshot.m1_calendar)
    expected_history = (len(times), 96)
    if history.shape != expected_history or mask.shape != expected_history:
        raise ValueError("M1 history and mask must both have width 96")
    if not np.issubdtype(history.dtype, np.number) or np.issubdtype(history.dtype, np.bool_):
        raise TypeError("M1 history must be numeric")
    if mask.dtype != np.dtype(np.bool_):
        raise TypeError("M1 history mask must be boolean")
    if np.any(np.isinf(history)) or not np.array_equal(np.isnan(history), ~mask):
        raise ValueError("M1 history missing values must exactly match its observation mask")
    if calendar.shape != (len(times), 3) or not np.issubdtype(calendar.dtype, np.integer):
        raise ValueError("M1 calendar must be an integer matrix with width three")
    if np.any(calendar[:, 0] < 0) or np.any(calendar[:, 0] > 95):
        raise ValueError("quarter_hour_index must be between 0 and 95")
    if np.any(calendar[:, 1] < 0) or np.any(calendar[:, 1] > 6):
        raise ValueError("day_of_week must be between 0 and 6")
    if np.any((calendar[:, 2] != 0) & (calendar[:, 2] != 1)):
        raise ValueError("is_weekend must be zero or one")
    if not np.array_equal(calendar[:, 2].astype(np.bool_), calendar[:, 1] >= 5):
        raise ValueError("is_weekend must agree with day_of_week")
    values = np.concatenate(
        (history.astype(np.float64), mask.astype(np.float64), calendar.astype(np.float64)), axis=1
    )
    if values.shape[1] != _M1_RAW_DIMENSION:
        raise AssertionError("internal M1 dimension drift")
    return FeatureBlock(
        times,
        values,
        _M1_FEATURE_NAMES,
        np.asarray(_M1_NULLABLE_MASK, dtype=np.bool_),
    )


def _validate_m2_against_m3(snapshot: Gate1Snapshot, state: np.ndarray) -> None:
    groups = snapshot.m3_by_issue_time
    if len(groups) != len(snapshot.issue_times):
        raise ValueError("M3 groups do not align with the canonical index")
    for position, (issue, rows) in enumerate(zip(snapshot.issue_times, groups, strict=True)):
        connected = len(rows)
        currents: list[float] = []
        pilots: list[float] = []
        for row in rows:
            if int(row["issue_time_utc_s"]) != int(issue):
                raise ValueError("M3 group issue does not match the canonical index")
            current = _strict_optional_number(row["current_current_a"], "M3 current")
            pilot = _strict_optional_number(row["current_pilot_a"], "M3 pilot")
            if current is not None:
                currents.append(current)
            if pilot is not None:
                pilots.append(pilot)
        active = sum(value > _ACTIVE_THRESHOLD_A for value in currents)
        expected = np.asarray(
            [
                connected,
                active,
                sum(currents) if len(currents) == connected else np.nan,
                len(currents) / connected if connected else 1.0,
                sum(pilots) if len(pilots) == connected else np.nan,
                (
                    sum(pilots) / connected
                    if connected and len(pilots) == connected
                    else (0.0 if not connected else np.nan)
                ),
            ],
            dtype=np.float64,
        )
        if not np.allclose(state[position], expected, rtol=2e-5, atol=2e-6, equal_nan=True):
            field = (
                "active"
                if not np.isclose(state[position, 1], expected[1], equal_nan=True)
                else "aggregate"
            )
            raise ValueError(f"M2 {field} state does not match the M3 connected set")


def encode_m2(
    snapshot: Gate1Snapshot,
    m1: FeatureBlock | None = None,
    *,
    validate_against_m3: bool = False,
) -> FeatureBlock:
    """Append the six frozen aggregate state columns to M1."""

    canonical_m1 = encode_m1(snapshot)
    if m1 is not None:
        _require_exact_block(m1, canonical_m1, "M1")
    base = canonical_m1 if m1 is None else m1
    times = _validate_issue_times(snapshot.issue_times, "M2")
    _require_prefix(base, times, _M1_RAW_DIMENSION)
    state = np.asarray(snapshot.m2_current_state)
    if state.shape != (len(times), 6) or not np.issubdtype(state.dtype, np.number):
        raise ValueError("M2 current state must be a numeric matrix with width six")
    if np.issubdtype(state.dtype, np.bool_) or np.any(np.isinf(state)):
        raise ValueError("M2 current state must be non-boolean and contain no infinity")
    for column, name in ((0, "connected"), (1, "active")):
        values = state[:, column]
        if np.any(~np.isfinite(values)) or np.any(values < 0) or np.any(values != np.floor(values)):
            raise ValueError(f"M2 {name} session count must be finite nonnegative integers")
    if np.any(state[:, 1] > state[:, 0]):
        raise ValueError("M2 active session count cannot exceed connected count")
    ratio = state[:, 3]
    if np.any(~np.isfinite(ratio)) or np.any((ratio < 0) | (ratio > 1)):
        raise ValueError("M2 station current observed ratio must be finite in [0, 1]")
    empty = state[:, 0] == 0
    required_empty = np.asarray([0, 0, 0, 1, 0, 0], dtype=np.float64)
    if np.any(empty) and not np.allclose(
        state[empty], np.broadcast_to(required_empty, state[empty].shape), equal_nan=True
    ):
        raise ValueError("M2 disconnected rows must use the frozen zero/one semantics")
    if validate_against_m3:
        _validate_m2_against_m3(snapshot, state.astype(np.float64))
    values = np.concatenate((base.values, state.astype(np.float64)), axis=1)
    return FeatureBlock(
        times,
        values,
        _M2_FEATURE_NAMES,
        np.asarray(_M2_NULLABLE_MASK, dtype=np.bool_),
    )


def encode_m3(
    snapshot: Gate1Snapshot,
    m2: FeatureBlock | None = None,
) -> FeatureBlock:
    """Pool the eleven frozen online fields over every connected session."""

    canonical_m2 = encode_m2(snapshot, validate_against_m3=True)
    if m2 is not None:
        _require_exact_block(m2, canonical_m2, "M2")
    base = canonical_m2 if m2 is None else m2
    times = _validate_issue_times(snapshot.issue_times, "M3")
    _require_prefix(base, times, _M2_RAW_DIMENSION)
    groups = snapshot.m3_by_issue_time
    if len(groups) != len(times):
        raise ValueError("M3 groups do not align with the canonical index")
    extension = np.empty((len(times), len(M3_SESSION_FIELDS) * 10), dtype=np.float64)
    for position, (issue, rows) in enumerate(zip(times, groups, strict=True)):
        seen: set[int] = set()
        for row in rows:
            if int(row["issue_time_utc_s"]) != int(issue):
                raise ValueError("M3 group issue does not match the canonical index")
            session = _strict_integer(
                row["anonymous_session_index"], "M3 anonymous session", nonnegative=True
            )
            if session in seen:
                raise ValueError("M3 group contains a duplicate connected session")
            seen.add(session)
        for field_position, field in enumerate(M3_SESSION_FIELDS):
            values = [row[field] for row in rows]
            start = field_position * 10
            extension[position, start : start + 10] = fixed_pool(values, total_count=len(rows))
    values = np.concatenate((base.values, extension), axis=1)
    if values.shape[1] != _M3_RAW_DIMENSION:
        raise AssertionError("internal M3 dimension drift")
    return FeatureBlock(
        times,
        values,
        _M3_FEATURE_NAMES,
        np.asarray(_M3_NULLABLE_MASK, dtype=np.bool_),
    )


def _validate_signal(
    timestamps: Any,
    values: Any,
    *,
    issue: int,
    context: str,
) -> tuple[np.ndarray, np.ndarray]:
    times = np.asarray(timestamps)
    signal = np.asarray(values)
    if times.dtype != np.dtype(np.int64) or times.ndim != 1:
        raise TypeError(f"{context} timestamps must be a one-dimensional int64 array")
    if (
        signal.ndim != 1
        or not np.issubdtype(signal.dtype, np.number)
        or np.issubdtype(signal.dtype, np.bool_)
    ):
        raise TypeError(f"{context} values must be a one-dimensional numeric array")
    if len(times) != len(signal):
        raise ValueError(f"{context} timestamps and values length must match")
    if len(times) and np.any(np.diff(times) <= 0):
        raise ValueError(f"{context} timestamps must be strictly ordered and unique")
    if len(times) and int(times[-1]) > issue:
        raise ValueError(f"{context} timestamp is later than issue cutoff")
    signal64 = signal.astype(np.float64, copy=False)
    if not np.all(np.isfinite(signal64)):
        raise ValueError(f"{context} values must be finite")
    return times, signal64


def _held_segments(
    times: np.ndarray, values: np.ndarray, *, issue: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    visible = times < issue
    starts = times[visible]
    held_values = values[visible]
    if not len(starts):
        return starts, starts.copy(), held_values
    all_next = np.concatenate((times[1:], np.asarray([issue], dtype=np.int64)))
    next_times = all_next[visible]
    ends = np.minimum(np.minimum(starts + _HOLD_CAP_SECONDS, next_times), issue)
    positive = ends > starts
    return starts[positive], ends[positive], held_values[positive]


def _joint_segments(
    current: tuple[np.ndarray, np.ndarray, np.ndarray],
    pilot: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    current_starts, current_ends, current_values = current
    pilot_starts, pilot_ends, pilot_values = pilot
    starts: list[int] = []
    ends: list[int] = []
    gaps: list[float] = []
    left = 0
    right = 0
    while left < len(current_starts) and right < len(pilot_starts):
        start = max(int(current_starts[left]), int(pilot_starts[right]))
        end = min(int(current_ends[left]), int(pilot_ends[right]))
        if end > start:
            starts.append(start)
            ends.append(end)
            gaps.append(float(pilot_values[right] - current_values[left]))
        if int(current_ends[left]) <= int(pilot_ends[right]):
            left += 1
        else:
            right += 1
    return (
        np.asarray(starts, dtype=np.int64),
        np.asarray(ends, dtype=np.int64),
        np.asarray(gaps, dtype=np.float64),
    )


def _window_intersections(
    segments: tuple[np.ndarray, np.ndarray, np.ndarray],
    *,
    window_start: int,
    issue: int,
) -> tuple[np.ndarray, np.ndarray]:
    starts, ends, values = segments
    durations = np.minimum(ends, issue) - np.maximum(starts, window_start)
    positive = durations > 0
    return durations[positive].astype(np.float64), values[positive]


def _causal_session_multiwindow_statistics(
    series: CausalSessionSeries,
    issue_time_utc_s: int,
) -> np.ndarray:
    """Compute all four windows once for one connected-session prefix."""

    if not isinstance(series, CausalSessionSeries):
        raise TypeError("causal session must be a CausalSessionSeries")
    _strict_integer(series.anonymous_session_index, "anonymous session index", nonnegative=True)
    issue = _strict_integer(issue_time_utc_s, "issue cutoff")
    current_times, current_values = _validate_signal(
        series.current_timestamps_utc_s,
        series.current_values_a,
        issue=issue,
        context="current",
    )
    pilot_times, pilot_values = _validate_signal(
        series.pilot_timestamps_utc_s,
        series.pilot_values_a,
        issue=issue,
        context="pilot",
    )
    current = _held_segments(current_times, current_values, issue=issue)
    pilot = _held_segments(pilot_times, pilot_values, issue=issue)
    joint = _joint_segments(current, pilot)
    output = np.empty((len(M4_WINDOWS_MINUTES), len(M4_SESSION_STAT_NAMES)))
    for window_position, window_minutes in enumerate(M4_WINDOWS_MINUTES):
        window_seconds = window_minutes * 60
        window_start = issue - window_seconds
        durations, values = _window_intersections(current, window_start=window_start, issue=issue)
        covered = float(np.sum(durations))
        if covered:
            mean = float(np.sum(durations * values) / covered)
            variance = float(np.sum(durations * np.square(values - mean)) / covered)
            variance = max(variance, 0.0)
            current_starts, current_ends, current_raw_values = current
            overlaps = (
                np.minimum(current_ends, issue) - np.maximum(current_starts, window_start)
            ) > 0
            slope = np.nan
            visible_times = current_starts[overlaps]
            visible_values = current_raw_values[overlaps]
            if len(visible_times) >= 2 and int(visible_times[-1]) > int(visible_times[0]):
                slope = float(
                    (visible_values[-1] - visible_values[0])
                    * 60
                    / (int(visible_times[-1]) - int(visible_times[0]))
                )
            current_stats = (
                mean,
                float(np.max(values)),
                float(np.min(values)),
                math.sqrt(variance),
                slope,
                float(np.sum(durations[values != 0.0]) / covered),
                covered / window_seconds,
            )
        else:
            current_stats = (np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, 0.0)
        joint_durations, gap_values = _window_intersections(
            joint, window_start=window_start, issue=issue
        )
        joint_covered = float(np.sum(joint_durations))
        if joint_covered:
            gap_stats = (
                float(np.sum(joint_durations * gap_values) / joint_covered),
                float(np.max(gap_values)),
            )
        else:
            gap_stats = (np.nan, np.nan)
        output[window_position] = current_stats + gap_stats
    return output


def causal_session_trajectory_statistics(
    series: CausalSessionSeries,
    issue_time_utc_s: int,
) -> np.ndarray:
    """Return immutable ``4 windows x 9 statistics`` causal session summaries."""

    return _immutable(_causal_session_multiwindow_statistics(series, issue_time_utc_s))


def _session_digest(session_indexes: Sequence[int] | set[int]) -> str:
    payload = ",".join(str(value) for value in sorted(session_indexes)).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


class M4FeatureAccumulator:
    """Streaming loader consumer that retains only pooled trajectory summaries."""

    def __init__(self, *, issue_count: int = EXPECTED_ISSUE_COUNT) -> None:
        self._issue_count = _strict_integer(issue_count, "issue_count", nonnegative=True)
        if not self._issue_count:
            raise ValueError("issue_count must be positive")
        empty_extension = np.tile(fixed_pool([], total_count=0), 36)
        self._values = np.tile(empty_extension, (self._issue_count, 1))
        self._observed_counts = np.zeros(self._issue_count, dtype=np.int64)
        self._observed_digests: list[str | None] = [None] * self._issue_count
        self._observed_issues: list[int | None] = [None] * self._issue_count
        self._current_position: int | None = None
        self._current_issue: int | None = None
        self._current_ids: set[int] = set()
        self._current_statistics: list[np.ndarray] = []
        self._computed_pair_count = 0
        self._peak_temporary_session_count = 0
        self._sealed = False
        self._encoded: np.ndarray | None = None
        self._snapshot_provenance: tuple[str, tuple[tuple[str, str], ...]] | None = None

    @property
    def computed_pair_count(self) -> int:
        return self._computed_pair_count

    @property
    def peak_temporary_session_count(self) -> int:
        return self._peak_temporary_session_count

    def _start_group(self, position: int, issue: int) -> None:
        self._current_position = position
        self._current_issue = issue
        self._current_ids.clear()
        self._current_statistics.clear()

    def _finalize_group(self) -> None:
        if self._current_position is None or self._current_issue is None:
            return
        position = self._current_position
        count = len(self._current_statistics)
        self._observed_counts[position] = count
        self._observed_digests[position] = _session_digest(self._current_ids)
        self._observed_issues[position] = self._current_issue
        if count:
            session_matrix = np.vstack(self._current_statistics)
            for statistic_position in range(36):
                start = statistic_position * 10
                self._values[position, start : start + 10] = fixed_pool(
                    session_matrix[:, statistic_position], total_count=count
                )
        self._peak_temporary_session_count = max(self._peak_temporary_session_count, count)
        self._current_position = None
        self._current_issue = None
        self._current_ids.clear()
        self._current_statistics.clear()

    def __call__(
        self,
        canonical_position: int,
        issue_time_utc_s: int,
        series: CausalSessionSeries,
    ) -> None:
        if self._sealed:
            raise RuntimeError("M4 accumulator is already sealed")
        position = _strict_integer(canonical_position, "canonical position", nonnegative=True)
        issue = _strict_integer(issue_time_utc_s, "issue cutoff")
        if position >= self._issue_count:
            raise ValueError("canonical position is outside the frozen row universe")
        if self._current_position is None:
            self._start_group(position, issue)
        elif position == self._current_position:
            if issue != self._current_issue:
                raise ValueError("consumer issue changed within one canonical position")
        elif position < self._current_position:
            raise ValueError("consumer canonical position order is not monotonic")
        else:
            assert self._current_issue is not None
            if issue <= self._current_issue:
                raise ValueError("consumer issue order is not strictly increasing")
            self._finalize_group()
            self._start_group(position, issue)
        session = _strict_integer(
            series.anonymous_session_index,
            "anonymous session index",
            nonnegative=True,
        )
        if session in self._current_ids:
            raise ValueError("consumer supplied a duplicate connected-session pair")
        statistics = _causal_session_multiwindow_statistics(series, issue)
        self._current_ids.add(session)
        self._current_statistics.append(statistics.reshape(36))
        self._computed_pair_count += 1

    @staticmethod
    def _validate_legacy_active_refs(snapshot: Gate1Snapshot) -> None:
        if len(snapshot.m3_by_issue_time) != len(snapshot.m4_by_issue_time):
            raise ValueError("legacy M4 groups do not align with M3 groups")
        for issue, m3_rows, legacy_rows in zip(
            snapshot.issue_times,
            snapshot.m3_by_issue_time,
            snapshot.m4_by_issue_time,
            strict=True,
        ):
            expected: set[int] = set()
            for row in m3_rows:
                current = _strict_optional_number(
                    row["current_current_a"], "M3 current used by legacy audit"
                )
                if current is not None and current > _ACTIVE_THRESHOLD_A:
                    expected.add(int(row["anonymous_session_index"]))
            actual: set[int] = set()
            for row in legacy_rows:
                if int(row["issue_time_utc_s"]) != int(issue):
                    raise ValueError("legacy M4 issue does not match the canonical index")
                session = int(row["anonymous_session_index"])
                if session in actual:
                    raise ValueError("legacy active-only M4 references contain a duplicate")
                actual.add(session)
            if actual != expected:
                raise ValueError(
                    "legacy active-only M4 references do not equal the strict >0.1 A M3 subset"
                )

    @staticmethod
    def _provenance(
        snapshot: Gate1Snapshot,
    ) -> tuple[str, tuple[tuple[str, str], ...]]:
        data_snapshot = snapshot.data_snapshot_sha256
        if not isinstance(data_snapshot, str) or not data_snapshot:
            raise ValueError("M4 snapshot provenance is invalid")
        artifacts: list[tuple[str, str]] = []
        for name, digest in snapshot.artifact_sha256.items():
            if not isinstance(name, str) or not isinstance(digest, str):
                raise TypeError("M4 artifact provenance is invalid")
            artifacts.append((name, digest))
        return data_snapshot, tuple(sorted(artifacts))

    def _audit_snapshot(self, snapshot: Gate1Snapshot) -> None:
        provenance = self._provenance(snapshot)
        if self._snapshot_provenance is not None and provenance != self._snapshot_provenance:
            raise ValueError("M4 accumulator snapshot provenance differs from its first encoding")
        times = _validate_issue_times(snapshot.issue_times, "M4")
        if len(times) != self._issue_count or len(snapshot.m3_by_issue_time) != len(times):
            raise ValueError("M4 accumulator row universe does not match the snapshot")
        expected_pairs = 0
        for position, (issue, rows) in enumerate(
            zip(times, snapshot.m3_by_issue_time, strict=True)
        ):
            expected_ids: set[int] = set()
            for row in rows:
                if int(row["issue_time_utc_s"]) != int(issue):
                    raise ValueError("M3 connected group issue does not match canonical index")
                session = int(row["anonymous_session_index"])
                if session in expected_ids:
                    raise ValueError("M3 connected group contains a duplicate session")
                expected_ids.add(session)
            expected_pairs += len(expected_ids)
            if self._observed_issues[position] is not None and self._observed_issues[
                position
            ] != int(issue):
                raise ValueError("M4 consumer issue does not match canonical issue")
            if self._observed_counts[position] != len(expected_ids):
                raise ValueError("M4 consumer did not cover the complete M3 connected set")
            if expected_ids:
                if self._observed_digests[position] != _session_digest(expected_ids):
                    raise ValueError("M4 consumer connected set does not match M3")
            elif self._observed_issues[position] is not None:
                raise ValueError("M4 consumer supplied a session for an empty M3 group")
        if self._computed_pair_count != expected_pairs:
            raise ValueError("M4 consumer pair count does not match M3")
        self._validate_legacy_active_refs(snapshot)
        if self._snapshot_provenance is None:
            self._snapshot_provenance = provenance

    def encode(self, snapshot: Gate1Snapshot) -> np.ndarray:
        """Seal, audit against the returned snapshot, and return the 360 columns."""

        if self._encoded is None:
            self._finalize_group()
            self._sealed = True
        self._audit_snapshot(snapshot)
        if self._encoded is None:
            self._encoded = _immutable(self._values)
            self._values = np.empty((0, 0), dtype=np.float64)
        return self._encoded


def encode_m4(
    snapshot: Gate1Snapshot,
    accumulator: M4FeatureAccumulator,
    m3: FeatureBlock | None = None,
) -> FeatureBlock:
    """Append 360 pooled causal trajectory columns to M3."""

    if not isinstance(accumulator, M4FeatureAccumulator):
        raise TypeError("M4 encoding requires an M4FeatureAccumulator")
    canonical_m3 = encode_m3(snapshot)
    if m3 is not None:
        _require_exact_block(m3, canonical_m3, "M3")
    base = canonical_m3 if m3 is None else m3
    times = _validate_issue_times(snapshot.issue_times, "M4")
    _require_prefix(base, times, _M3_RAW_DIMENSION)
    extension = accumulator.encode(snapshot)
    if extension.shape != (len(times), 360):
        raise ValueError("M4 accumulator extension must have width 360")
    values = np.concatenate((base.values, extension), axis=1)
    if values.shape[1] != _M4_RAW_DIMENSION:
        raise AssertionError("internal M4 dimension drift")
    return FeatureBlock(
        times,
        values,
        _M4_FEATURE_NAMES,
        np.asarray(_M4_NULLABLE_MASK, dtype=np.bool_),
    )


def build_feature_blocks(
    snapshot: Gate1Snapshot,
    m4_accumulator: M4FeatureAccumulator,
) -> Mapping[str, FeatureBlock]:
    """Build the four cumulative tiers, validating every prefix and cohort."""

    m1 = encode_m1(snapshot)
    m2 = encode_m2(snapshot, m1, validate_against_m3=True)
    m3 = encode_m3(snapshot, m2)
    m4 = encode_m4(snapshot, m4_accumulator, m3)
    return MappingProxyType({"M1": m1, "M2": m2, "M3": m3, "M4": m4})


_BASE_UNITS = {
    "elapsed_connection_s": "s",
    "elapsed_charging_time_proxy_s": "s",
    "current_current_a": "A",
    "recent_current_mean_a": "A",
    "recent_current_peak_a": "A",
    "recent_current_observed_ratio": "1",
    "cumulative_current_ah": "Ah",
    "cumulative_current_observed_ratio": "1",
    "current_pilot_a": "A",
    "requested_departure_minutes_from_issue": "min",
    "known_kwh_requested": "kWh",
}
_M4_UNITS = {
    "current_mean_a": "A",
    "current_maximum_a": "A",
    "current_minimum_a": "A",
    "current_std_a": "A",
    "current_slope_a_per_min": "A/min",
    "current_nonzero_fraction": "1",
    "current_observed_ratio": "1",
    "pilot_minus_current_mean_a": "A",
    "pilot_minus_current_maximum_a": "A",
}


def _feature_description(name: str) -> tuple[str, str]:
    if name.startswith("history_station_current_mean_a_lag_"):
        lag = int(name.rsplit("_", 1)[1])
        return f"station current mean at frozen 15-minute lag {lag}", "A"
    if name.startswith("history_observed_mask_lag_"):
        lag = int(name.rsplit("_", 1)[1])
        return f"one when frozen 15-minute lag {lag} is observed", "1"
    simple = {
        "quarter_hour_index": ("local quarter-hour ordinal in day", "1"),
        "day_of_week": ("local weekday ordinal with Monday zero", "1"),
        "is_weekend": ("one for local Saturday or Sunday", "1"),
        "connected_session_count": ("count of currently connected sessions", "count"),
        "active_charging_session_count": (
            "count of connected sessions with current strictly above 0.1 A",
            "count",
        ),
        "station_current_a": ("sum of complete held connected-session current", "A"),
        "station_current_observed_ratio": (
            "fraction of connected sessions with held current",
            "1",
        ),
        "pilot_sum_a": ("sum of complete held connected-session pilot", "A"),
        "pilot_mean_a": ("mean of complete held connected-session pilot", "A"),
    }
    if name in simple:
        return simple[name]
    if name.startswith("m3_"):
        remainder = name[3:]
        for field in M3_SESSION_FIELDS:
            prefix = f"{field}_"
            if remainder.startswith(prefix):
                pool = remainder[len(prefix) :]
                unit = "count" if pool in {"count", "missing_count"} else _BASE_UNITS[field]
                return f"fixed-pool {pool} over connected sessions for {field}", unit
    if name.startswith("m4_window_"):
        for window in M4_WINDOWS_MINUTES:
            prefix = f"m4_window_{window:02d}m_"
            if name.startswith(prefix):
                remainder = name[len(prefix) :]
                for statistic in M4_SESSION_STAT_NAMES:
                    stat_prefix = f"{statistic}_"
                    if remainder.startswith(stat_prefix):
                        pool = remainder[len(stat_prefix) :]
                        unit = (
                            "count" if pool in {"count", "missing_count"} else _M4_UNITS[statistic]
                        )
                        formula = (
                            f"fixed-pool {pool} over connected sessions for {window}-minute "
                            f"causal 12-second bounded-hold {statistic}"
                        )
                        return formula, unit
    raise ValueError(f"feature metadata is missing for {name}")


def _validate_feature_blocks(blocks: Mapping[str, FeatureBlock]) -> None:
    tier_order = ("M1", "M2", "M3", "M4")
    if tuple(blocks) != tier_order:
        raise ValueError("feature blocks must use the declared M1 through M4 order")
    canonical_times: np.ndarray | None = None
    for tier in tier_order:
        block = blocks[tier]
        if not isinstance(block, FeatureBlock):
            raise TypeError(f"{tier} must be a FeatureBlock")
        expected_dimension = _EXPECTED_RAW_DIMENSIONS[tier]
        if block.values.shape[1] != expected_dimension:
            raise ValueError(f"{tier} raw dimension differs from the frozen contract")
        if block.feature_names != _EXPECTED_FEATURE_NAMES[tier]:
            raise ValueError(f"{tier} feature names or order differ from the frozen contract")
        expected_nullable = np.asarray(_EXPECTED_NULLABLE_MASKS[tier], dtype=np.bool_)
        if not np.array_equal(block.nullable_mask, expected_nullable):
            raise ValueError(f"{tier} nullable mask differs from the frozen contract")
        if canonical_times is None:
            canonical_times = block.issue_times
        elif not np.array_equal(block.issue_times, canonical_times):
            raise ValueError("feature tier indexes do not share one ordered canonical index")
    for parent_tier, child_tier in pairwise(tier_order):
        parent = blocks[parent_tier]
        child = blocks[child_tier]
        width = parent.values.shape[1]
        if child.feature_names[:width] != parent.feature_names:
            raise ValueError(f"{child_tier} feature-name prefix differs from {parent_tier}")
        if not np.array_equal(child.nullable_mask[:width], parent.nullable_mask):
            raise ValueError(f"{child_tier} nullable prefix differs from {parent_tier}")
        if not np.array_equal(child.values[:, :width], parent.values, equal_nan=True):
            raise ValueError(f"{child_tier} value prefix differs from {parent_tier}")


def feature_encoding_manifest(
    blocks: Mapping[str, FeatureBlock],
) -> dict[str, Any]:
    """Return a JSON-safe, path-free declaration of feature order and dimensions."""

    _validate_feature_blocks(blocks)
    tiers: dict[str, Any] = {}
    for tier, block in blocks.items():
        features: list[dict[str, Any]] = []
        for position, name in enumerate(block.feature_names):
            formula, unit = _feature_description(name)
            features.append(
                {
                    "position": position,
                    "name": name,
                    "formula": formula,
                    "unit": unit,
                    "nullable": bool(block.nullable_mask[position]),
                }
            )
        indicator_names = [
            name
            for name, nullable in zip(block.feature_names, block.nullable_mask, strict=True)
            if nullable
        ]
        indicators = [
            {
                "position": block.values.shape[1] + offset,
                "name": f"{source}__missing",
                "source_feature": source,
                "formula": "1 if source is missing else 0",
                "unit": "1",
            }
            for offset, source in enumerate(indicator_names)
        ]
        tiers[tier] = {
            "raw_dimension": block.values.shape[1],
            "missing_indicator_dimension": len(indicators),
            "encoded_dimension": block.values.shape[1] + len(indicators),
            "features": features,
            "missing_indicators": indicators,
            "missing_indicator_names": [item["name"] for item in indicators],
        }
    return {
        "schema_version": "acn-jpl-gate1-feature-encoding/v1",
        "tier_order": ["M1", "M2", "M3", "M4"],
        "pool_statistic_order": list(FIXED_POOL_STAT_NAMES),
        "m3_session_field_order": list(M3_SESSION_FIELDS),
        "m4_window_minutes_order": list(M4_WINDOWS_MINUTES),
        "m4_session_statistic_order": list(M4_SESSION_STAT_NAMES),
        "history_missingness_policy": (
            "history values use their existing 96 observation masks without duplicate indicators"
        ),
        "nullable_mask_policy": "fixed columns that receive appended missing indicators",
        "pooling_contract": {
            "statistic_order": list(FIXED_POOL_STAT_NAMES),
            "finite_values": "real finite values; null and NaN are missing; infinity is rejected",
            "count": {"formula": "number of finite values", "unit": "count"},
            "sum": {"formula": "sum of finite values", "empty_value": 0.0},
            "mean": {
                "formula": "sum of finite values divided by finite count",
                "empty_value": None,
            },
            "standard_deviation": {
                "formula": "population standard deviation of finite values",
                "ddof": 0,
                "empty_value": None,
            },
            "minimum_and_maximum": {
                "formula": "finite-value extrema",
                "empty_value": None,
            },
            "quantiles": {"probabilities": [0.25, 0.5, 0.75], "method": "linear"},
            "missing_count": {
                "formula": "total count minus finite count",
                "unit": "count",
            },
            "empty_or_all_missing": {
                "count": 0,
                "sum": 0.0,
                "mean_std_minimum_maximum_quantiles": None,
                "missing_count": "total count",
            },
        },
        "trajectory_contract": {
            "windows_minutes": list(M4_WINDOWS_MINUTES),
            "window_interval": "[origin - window, origin)",
            "hold": {
                "method": "left-continuous",
                "cap_seconds": 12,
                "next_sample_also_ends_hold": True,
            },
            "sample_at_origin": "excluded",
            "current_mean": {
                "formula": "time-weighted mean of held current",
                "denominator": "covered current seconds",
            },
            "current_maximum": {"formula": "maximum held current over covered current seconds"},
            "current_minimum": {"formula": "minimum held current over covered current seconds"},
            "current_standard_deviation": {
                "formula": "time-weighted population standard deviation of held current",
                "denominator": "covered current seconds",
                "ddof": 0,
            },
            "current_nonzero_fraction": {
                "formula": "covered seconds with nonzero held current divided by coverage",
                "condition": "held current != 0.0 A",
                "denominator": "covered current seconds",
            },
            "current_observed_ratio": {
                "formula": "covered current seconds divided by full window seconds",
                "denominator": "full window seconds",
            },
            "slope": {
                "formula": (
                    "(last current - first current) * 60 / (last timestamp - first timestamp)"
                ),
                "minimum_distinct_timestamps": 2,
                "unit": "A/min",
            },
            "gap": {
                "definition": "pilot - current",
                "coverage": "joint held coverage",
                "weighted_mean_denominator": "joint-covered seconds",
                "maximum": "maximum over joint-covered seconds",
                "negative_values_clipped": False,
            },
        },
        "ordering_contract": {
            "M1": "history oldest-to-newest, masks oldest-to-newest, calendar",
            "M2": "M1 then aggregate state",
            "M3": "M2 then field then pool statistic",
            "M4": "M3 then window then session statistic then pool statistic",
        },
        "privacy_audit": {
            "status": "PASS",
            "row_index_used_as_model_feature": False,
            "structural_join_keys_used_as_model_features": False,
            "single_session_values_published": False,
            "local_paths_published": False,
        },
        "legacy_active_reference_audit": {
            "role": "audit only",
            "threshold_a": 0.1,
            "comparison": "finite current strictly greater than threshold",
            "model_cohort": "all connected sessions",
            "identifiers_published": False,
        },
        "tiers": tiers,
    }
