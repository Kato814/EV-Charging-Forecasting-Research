"""Deterministic, time-weighted JPL station-current aggregation.

The implementation consumes deidentified cleaned-session mappings.  It treats every
sample as a bounded left-continuous hold, never fills beyond the configured cap, and
keeps missing observation coverage distinct from a measured zero.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

JPL_TIMEZONE = "America/Los_Angeles"
BIN_SECONDS = 15 * 60


@dataclass(frozen=True)
class AggregationPolicy:
    """Explicit aggregation choices; none are inferred from the output data."""

    max_hold_seconds: int
    main_active_threshold_a: float = 0.1
    comparison_active_threshold_a: float = 1.0
    coverage_thresholds: tuple[float, float, float] = (0.80, 0.90, 0.95)
    pilot_max_hold_seconds: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.max_hold_seconds, bool) or self.max_hold_seconds <= 0:
            raise ValueError("max_hold_seconds must be a positive integer")
        if self.pilot_max_hold_seconds is not None and (
            isinstance(self.pilot_max_hold_seconds, bool)
            or not isinstance(self.pilot_max_hold_seconds, int)
            or self.pilot_max_hold_seconds <= 0
        ):
            raise ValueError("pilot_max_hold_seconds must be a positive integer")
        if not math.isfinite(self.main_active_threshold_a):
            raise ValueError("main active threshold must be finite")
        if not math.isfinite(self.comparison_active_threshold_a):
            raise ValueError("comparison active threshold must be finite")
        if tuple(sorted(self.coverage_thresholds)) != self.coverage_thresholds:
            raise ValueError("coverage thresholds must be sorted")
        if any(not 0 <= threshold <= 1 for threshold in self.coverage_thresholds):
            raise ValueError("coverage thresholds must lie in [0, 1]")
        if self.coverage_thresholds != (0.80, 0.90, 0.95):
            raise ValueError("Issue #17 fixes coverage thresholds at 0.80, 0.90, and 0.95")


@dataclass(frozen=True)
class IntervalBin:
    """One left-closed, right-open UTC bin with its LA calendar mapping."""

    start_utc: datetime
    end_utc: datetime
    timestamp_local: datetime
    local_date: str
    quarter_hour_index: int
    day_of_week: int
    is_weekend: bool


@dataclass(frozen=True)
class Station15MinResult:
    """In-memory aggregate table and deidentified QA summary."""

    rows: tuple[dict[str, Any], ...]
    qa: dict[str, Any]


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("grid boundaries must be timezone-aware")
    return value.astimezone(timezone.utc)


def build_local_15min_grid(start: datetime, end: datetime) -> tuple[IntervalBin, ...]:
    """Build a DST-safe grid by stepping in UTC and mapping each edge to LA."""

    start_utc = _aware_utc(start)
    end_utc = _aware_utc(end)
    seconds = (end_utc - start_utc).total_seconds()
    if seconds <= 0 or seconds % BIN_SECONDS:
        raise ValueError("analysis interval must be a positive multiple of 15 minutes")
    local_zone = ZoneInfo(JPL_TIMEZONE)
    bins: list[IntervalBin] = []
    for index in range(int(seconds // BIN_SECONDS)):
        bin_start = start_utc + timedelta(seconds=index * BIN_SECONDS)
        bin_end = bin_start + timedelta(seconds=BIN_SECONDS)
        local = bin_start.astimezone(local_zone)
        bins.append(
            IntervalBin(
                start_utc=bin_start,
                end_utc=bin_end,
                timestamp_local=local,
                local_date=local.date().isoformat(),
                quarter_hour_index=local.hour * 4 + local.minute // 15,
                day_of_week=local.weekday(),
                is_weekend=local.weekday() >= 5,
            )
        )
    return tuple(bins)


def _member(value: object, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _integer_member(value: object, name: str) -> int:
    result = _member(value, name)
    if isinstance(result, bool) or not isinstance(result, (int, np.integer)):
        raise TypeError(f"cleaned session {name} must be an integer epoch second")
    return int(result)


def _series_arrays(session: object, name: str) -> tuple[np.ndarray, np.ndarray]:
    series = _member(session, name)
    if series is None:
        return np.array([], dtype=np.int64), np.array([], dtype=np.float64)
    raw_times = _member(series, "timestamps_utc_s")
    raw_values = _member(series, "values")
    if raw_times is None or raw_values is None:
        raise ValueError(f"cleaned {name} series is missing timestamps or values")
    if not isinstance(raw_times, Sequence) or isinstance(raw_times, (str, bytes)):
        raise TypeError(f"cleaned {name} timestamps must be a sequence")
    if not isinstance(raw_values, Sequence) or isinstance(raw_values, (str, bytes)):
        raise TypeError(f"cleaned {name} values must be a sequence")
    if len(raw_times) != len(raw_values):
        raise ValueError(f"cleaned {name} timestamp/value lengths differ")
    times = np.asarray(raw_times, dtype=np.int64)
    values = np.asarray(raw_values, dtype=np.float64)
    if times.ndim != 1 or values.ndim != 1:
        raise ValueError(f"cleaned {name} arrays must be one-dimensional")
    if values.size and not bool(np.isfinite(values).all()):
        raise ValueError(f"cleaned {name} contains non-finite values")
    if times.size > 1 and bool(np.any(np.diff(times) <= 0)):
        raise ValueError(f"cleaned {name} timestamps must be strictly increasing")
    return times, values


def _add_interval(
    difference: np.ndarray,
    start_epoch: int,
    end_epoch: int,
    analysis_start_epoch: int,
    analysis_end_epoch: int,
    value: float,
) -> None:
    clipped_start = max(start_epoch, analysis_start_epoch)
    clipped_end = min(end_epoch, analysis_end_epoch)
    if clipped_end <= clipped_start:
        return
    left = clipped_start - analysis_start_epoch
    right = clipped_end - analysis_start_epoch
    difference[left] += value
    difference[right] -= value


def _add_held_series(
    times: np.ndarray,
    values: np.ndarray,
    *,
    connection_epoch: int,
    disconnect_epoch: int,
    analysis_start_epoch: int,
    analysis_end_epoch: int,
    max_hold_seconds: int,
    value_difference: np.ndarray,
    observed_difference: np.ndarray,
    active_differences: tuple[tuple[float, np.ndarray], ...] = (),
) -> None:
    for index, raw_start in enumerate(times):
        sample_start = int(raw_start)
        next_sample = int(times[index + 1]) if index + 1 < len(times) else None
        sample_end = sample_start + max_hold_seconds
        if next_sample is not None:
            sample_end = min(sample_end, next_sample)
        sample_start = max(sample_start, connection_epoch)
        sample_end = min(sample_end, disconnect_epoch)
        if sample_end <= sample_start:
            continue
        value = float(values[index])
        _add_interval(
            value_difference,
            sample_start,
            sample_end,
            analysis_start_epoch,
            analysis_end_epoch,
            value,
        )
        _add_interval(
            observed_difference,
            sample_start,
            sample_end,
            analysis_start_epoch,
            analysis_end_epoch,
            1,
        )
        for threshold, difference in active_differences:
            if value > threshold:
                _add_interval(
                    difference,
                    sample_start,
                    sample_end,
                    analysis_start_epoch,
                    analysis_end_epoch,
                    1,
                )


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _longest_false_run(values: Iterable[bool]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value:
            current = 0
        else:
            current += 1
            longest = max(longest, current)
    return longest


def _distribution(rows: Sequence[Mapping[str, Any]], weekend: bool) -> dict[str, Any]:
    selected = [row for row in rows if row["is_weekend"] is weekend]
    valid = [
        float(row["station_current_mean_a"])
        for row in selected
        if row["valid_bin_90"] and row["station_current_mean_a"] is not None
    ]
    return {
        "bin_count": len(selected),
        "valid_bin_count": len(valid),
        "mean_current_a": round(float(np.mean(valid)), 8) if valid else None,
        "median_current_a": round(float(np.median(valid)), 8) if valid else None,
    }


def aggregate_station_15min(
    sessions: Iterable[object],
    *,
    start_utc: datetime,
    end_utc: datetime,
    policy: AggregationPolicy,
    grid_policy: str | None = None,
) -> Station15MinResult:
    """Aggregate cleaned session trajectories on an exact one-second time base."""

    start = _aware_utc(start_utc)
    end = _aware_utc(end_utc)
    if grid_policy not in (None, "continuous_physical_utc"):
        raise ValueError("grid_policy must be continuous_physical_utc when provided")
    grid = build_local_15min_grid(start, end)
    total_seconds = int((end - start).total_seconds())
    if total_seconds <= 0:
        raise ValueError("analysis interval must be positive")
    start_epoch = int(start.timestamp())
    end_epoch = int(end.timestamp())

    current_difference = np.zeros(total_seconds + 1, dtype=np.float64)
    pilot_difference = np.zeros(total_seconds + 1, dtype=np.float64)
    current_observed_difference = np.zeros(total_seconds + 1, dtype=np.int32)
    pilot_observed_difference = np.zeros(total_seconds + 1, dtype=np.int32)
    connected_difference = np.zeros(total_seconds + 1, dtype=np.int32)
    active_main_difference = np.zeros(total_seconds + 1, dtype=np.int32)
    active_comparison_difference = np.zeros(total_seconds + 1, dtype=np.int32)
    arrival_counts = np.zeros(len(grid), dtype=np.int32)
    disconnect_counts = np.zeros(len(grid), dtype=np.int32)

    session_count = 0
    for session in sessions:
        session_count += 1
        connection = _integer_member(session, "connection_utc_s")
        disconnect = _integer_member(session, "disconnect_utc_s")
        if disconnect <= connection:
            raise ValueError("cleaned session has non-positive connection interval")
        _add_interval(
            connected_difference,
            connection,
            disconnect,
            start_epoch,
            end_epoch,
            1,
        )
        if start_epoch <= connection < end_epoch:
            arrival_counts[(connection - start_epoch) // BIN_SECONDS] += 1
        if start_epoch <= disconnect < end_epoch:
            disconnect_counts[(disconnect - start_epoch) // BIN_SECONDS] += 1

        current_times, current_values = _series_arrays(session, "current")
        pilot_times, pilot_values = _series_arrays(session, "pilot")
        _add_held_series(
            current_times,
            current_values,
            connection_epoch=connection,
            disconnect_epoch=disconnect,
            analysis_start_epoch=start_epoch,
            analysis_end_epoch=end_epoch,
            max_hold_seconds=policy.max_hold_seconds,
            value_difference=current_difference,
            observed_difference=current_observed_difference,
            active_differences=(
                (policy.main_active_threshold_a, active_main_difference),
                (policy.comparison_active_threshold_a, active_comparison_difference),
            ),
        )
        _add_held_series(
            pilot_times,
            pilot_values,
            connection_epoch=connection,
            disconnect_epoch=disconnect,
            analysis_start_epoch=start_epoch,
            analysis_end_epoch=end_epoch,
            max_hold_seconds=(
                policy.pilot_max_hold_seconds
                if policy.pilot_max_hold_seconds is not None
                else policy.max_hold_seconds
            ),
            value_difference=pilot_difference,
            observed_difference=pilot_observed_difference,
        )

    current = np.cumsum(current_difference[:-1])
    pilot = np.cumsum(pilot_difference[:-1])
    current_observed = np.cumsum(current_observed_difference[:-1])
    pilot_observed = np.cumsum(pilot_observed_difference[:-1])
    connected = np.cumsum(connected_difference[:-1])
    active_main = np.cumsum(active_main_difference[:-1])
    active_comparison = np.cumsum(active_comparison_difference[:-1])

    rows: list[dict[str, Any]] = []
    for index, interval in enumerate(grid):
        left = index * BIN_SECONDS
        right = left + BIN_SECONDS
        connected_seconds = int(np.sum(connected[left:right], dtype=np.int64))
        observed_seconds = int(np.sum(current_observed[left:right], dtype=np.int64))
        pilot_observed_seconds = int(np.sum(pilot_observed[left:right], dtype=np.int64))
        coverage = observed_seconds / connected_seconds if connected_seconds else 1.0
        pilot_coverage = pilot_observed_seconds / connected_seconds if connected_seconds else 1.0
        current_area = float(np.sum(current[left:right], dtype=np.float64))
        pilot_area = float(np.sum(pilot[left:right], dtype=np.float64))
        has_current = observed_seconds > 0 or connected_seconds == 0
        has_pilot = pilot_observed_seconds > 0 or connected_seconds == 0
        current_mean = current_area / BIN_SECONDS if has_current and coverage >= 0.90 else None
        current_peak = (
            float(np.max(current[left:right])) if has_current and coverage >= 0.90 else None
        )
        pilot_sum = pilot_area / BIN_SECONDS if has_pilot and pilot_coverage >= 0.90 else None
        pilot_mean = (
            pilot_area / pilot_observed_seconds
            if pilot_observed_seconds and pilot_coverage >= 0.90
            else (0.0 if connected_seconds == 0 else None)
        )
        edge_index = right - 1
        rows.append(
            {
                "timestamp_utc": _iso_utc(interval.start_utc),
                "timestamp_local": interval.timestamp_local.isoformat(),
                "local_date": interval.local_date,
                "quarter_hour_index": interval.quarter_hour_index,
                "day_of_week": interval.day_of_week,
                "is_weekend": interval.is_weekend,
                "station_current_mean_a": (
                    round(current_mean, 8) if current_mean is not None else None
                ),
                "station_current_peak_a": (
                    round(current_peak, 8) if current_peak is not None else None
                ),
                "connected_session_count": int(connected[edge_index]),
                "active_charging_session_count": int(active_main[edge_index]),
                "active_charging_session_count_gt_1a": int(active_comparison[edge_index]),
                "pilot_sum_a": round(pilot_sum, 8) if pilot_sum is not None else None,
                "pilot_mean_a": round(pilot_mean, 8) if pilot_mean is not None else None,
                "arrival_count": int(arrival_counts[index]),
                "disconnect_count": int(disconnect_counts[index]),
                "observed_coverage_ratio": round(coverage, 8),
                "pilot_observed_coverage_ratio": round(pilot_coverage, 8),
                "valid_bin_80": coverage >= 0.80,
                "valid_bin_90": coverage >= 0.90,
                "valid_bin_95": coverage >= 0.95,
            }
        )

    valid_90 = [bool(row["valid_bin_90"]) for row in rows]
    peaks = [
        float(row["station_current_peak_a"])
        for row in rows
        if row["valid_bin_90"] and row["station_current_peak_a"] is not None
    ]
    ramps = [
        abs(float(right["station_current_mean_a"]) - float(left["station_current_mean_a"]))
        for left, right in pairwise(rows)
        if left["valid_bin_90"]
        and right["valid_bin_90"]
        and left["station_current_mean_a"] is not None
        and right["station_current_mean_a"] is not None
    ]
    qa = {
        "schema_version": "acn-jpl-station-15min-qa/v1",
        "session_count": session_count,
        "expected_bins": len(grid),
        "generated_bins": len(rows),
        "valid_bins_at_80": sum(bool(row["valid_bin_80"]) for row in rows),
        "valid_bins_at_90": sum(valid_90),
        "valid_bins_at_95": sum(bool(row["valid_bin_95"]) for row in rows),
        "pilot_valid_bins_at_80": sum(
            float(row["pilot_observed_coverage_ratio"]) >= 0.80 for row in rows
        ),
        "pilot_valid_bins_at_90": sum(
            float(row["pilot_observed_coverage_ratio"]) >= 0.90 for row in rows
        ),
        "pilot_valid_bins_at_95": sum(
            float(row["pilot_observed_coverage_ratio"]) >= 0.95 for row in rows
        ),
        "missing_bin_rate": round(1 - (sum(valid_90) / len(rows)), 8) if rows else None,
        "longest_missing_run": _longest_false_run(valid_90),
        "peak_current_proxy_a": round(max(peaks), 8) if peaks else None,
        "max_absolute_ramp_a": round(max(ramps), 8) if ramps else 0.0,
        "weekday_distribution": _distribution(rows, False),
        "weekend_distribution": _distribution(rows, True),
        "coverage_sensitivity": {
            "threshold_80_valid_bins": sum(bool(row["valid_bin_80"]) for row in rows),
            "threshold_90_valid_bins": sum(valid_90),
            "threshold_95_valid_bins": sum(bool(row["valid_bin_95"]) for row in rows),
        },
        "active_threshold_sensitivity": {
            "main_threshold_a": policy.main_active_threshold_a,
            "comparison_threshold_a": policy.comparison_active_threshold_a,
            "main_end_bin_count_sum": int(
                sum(int(row["active_charging_session_count"]) for row in rows)
            ),
            "comparison_end_bin_count_sum": int(
                sum(int(row["active_charging_session_count_gt_1a"]) for row in rows)
            ),
        },
        "aggregation_semantics": {
            "bin_rule": "left_closed_right_open",
            "mean_rule": "observed_ampere_seconds_divided_by_900_seconds",
            "peak_rule": "maximum_bounded_piecewise_constant_current_proxy",
            "connected_active_count_rule": "state_at_bin_right_edge_minus_one_second",
            "coverage_rule": "observed_current_session_seconds_divided_by_connected_session_seconds",
            "pilot_coverage_rule": (
                "observed_pilot_session_seconds_divided_by_connected_session_seconds"
            ),
            "pilot_publication_gate": "coverage_at_least_0.90",
            "missing_is_zero": False,
            "max_hold_seconds": policy.max_hold_seconds,
            "power_label_type": "none",
        },
    }
    if grid_policy is not None:
        local_quarters = [(interval.local_date, interval.quarter_hour_index) for interval in grid]
        repeated_local_quarters = len(local_quarters) - len(set(local_quarters))
        local_day_count = len({interval.local_date for interval in grid})
        for threshold in (80, 90, 95):
            valid_count = int(qa[f"valid_bins_at_{threshold}"])
            valid_rate = valid_count / len(rows)
            qa[f"valid_bin_rate_at_{threshold}"] = round(valid_rate, 8)
            qa[f"missing_bin_rate_at_{threshold}"] = round(1 - valid_rate, 8)
        qa.update(
            {
                "grid_policy": grid_policy,
                "dst_fold_extra_bins": max(0, len(grid) - local_day_count * 96),
                "repeated_local_quarter_count": repeated_local_quarters,
                "time_weighted_integral_status": "PASS",
            }
        )
    return Station15MinResult(rows=tuple(rows), qa=qa)
