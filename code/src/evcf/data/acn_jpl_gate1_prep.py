"""Offline orchestrator for the frozen JPL May 2019 Gate 1 preparation task.

The module deliberately separates three trust zones:

* immutable official raw files;
* local, ignored anonymous session and tensor artifacts; and
* a closed, aggregate-only public release.

No network client, model trainer, or reconstructed-power feature path is present.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import math
import os
import platform
import shutil
import tempfile
import zipfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import yaml

from .acn_jpl_15min import AggregationPolicy, aggregate_station_15min
from .acn_jpl_cleaning import (
    BoundedIntegral,
    CleaningPolicy,
    CleanSeries,
    CleanSession,
    SamplingMode,
    SamplingModes,
    SeriesPoint,
    bounded_locf_integral,
    clean_session,
    cleaning_policy_from_sampling_modes,
    derive_sampling_modes,
    parse_timestamp_utc_s,
    write_cleaned_sessions,
)
from .acn_jpl_issue_snapshots import (
    IssueSnapshotResult,
    SnapshotPolicy,
    build_issue_snapshots,
    feature_blacklist_document,
    feature_whitelist_document,
)
from .acn_jpl_month_config import (
    SEASONAL_MONTHS,
    JPLMonthConfig,
    is_canonical_jpl_month_config,
)
from .acn_jpl_power_semantics import (
    CURRENT_PROXY_ONLY,
    KW_RECONSTRUCTION_CANDIDATE,
    POWER_SEMANTICS_FAIL,
    PowerAuditSession,
    audit_power_semantics,
)
from .acn_jpl_preparation import (
    ANALYSIS_END_UTC,
    ANALYSIS_START_UTC,
    DEFAULT_INTERIM_ROOT,
    DEFAULT_PROCESSED_ROOT,
    DEFAULT_PUBLIC_ROOT,
    DEFAULT_RAW_ROOT,
    FROZEN_RAW_CONTRACT,
    PREPARATION_SCHEMA_VERSION,
    PUBLIC_ARTIFACT_NAMES,
    InventorySnapshot,
    assert_raw_snapshot_unchanged,
    atomic_write_bytes,
    atomic_write_json,
    guard_write_target,
    iter_validated_raw_records,
    validate_public_artifacts,
    validate_raw_snapshot,
)

_LOCAL_ZONE = ZoneInfo("America/Los_Angeles")
_PUBLIC_PAYLOAD_NAMES = PUBLIC_ARTIFACT_NAMES[:-1]
_POWER_STATUSES = {
    KW_RECONSTRUCTION_CANDIDATE,
    CURRENT_PROXY_ONLY,
    POWER_SEMANTICS_FAIL,
}
DEFAULT_PROTOCOL_PATH = Path("code/configs/acn_jpl_gate1_prep_2019-05.yaml")


@dataclass(frozen=True)
class PreparationResult:
    """Aggregate completion evidence returned to the authorized CLI."""

    summary: dict[str, Any]
    cleaning_qa: dict[str, Any]
    power_audit: dict[str, Any]
    station_qa: dict[str, Any]
    issue_qa: dict[str, Any]
    raw_before: InventorySnapshot
    raw_after: InventorySnapshot


class PowerSemanticsGateError(RuntimeError):
    """Safe aggregate stop signal emitted after a severe power-semantics result."""

    def __init__(self, summary: Mapping[str, Any]) -> None:
        super().__init__("power semantics severe-failure gate triggered")
        self.summary = dict(summary)


def _ratio(numerator: float, denominator: float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    return {
        "count": len(values),
        "minimum": min(values) if values else None,
        "p05": _quantile(values, 0.05),
        "median": _quantile(values, 0.50),
        "p95": _quantile(values, 0.95),
        "maximum": max(values) if values else None,
    }


def _series_points(series: CleanSeries) -> tuple[SeriesPoint, ...]:
    return tuple(
        SeriesPoint(int(timestamp), float(value), int(ordinal))
        for timestamp, value, ordinal in zip(
            series.timestamps_utc_s,
            series.values,
            series.raw_ordinals,
            strict=True,
        )
    )


def _integral_summary(integral: BoundedIntegral) -> dict[str, Any]:
    return {
        "observed_seconds": integral.observed_seconds,
        "eligible_seconds": integral.eligible_seconds,
        "coverage": integral.coverage,
        "ampere_hours": integral.value_hours,
    }


class CleaningAccumulator:
    """Aggregate deterministic cleaning, sensitivity, and power-audit inputs."""

    def __init__(self, policy: CleaningPolicy) -> None:
        self.policy = policy
        self.sessions_processed = 0
        self._series: dict[str, dict[str, float | int]] = {
            name: {
                "raw_samples": 0,
                "retained_samples": 0,
                "invalid_timestamps": 0,
                "invalid_values": 0,
                "exact_duplicate_extras": 0,
                "conflicting_timestamps": 0,
            }
            for name in ("current", "pilot")
        }
        self._user_input_revisions = 0
        self._user_input_sanitized = 0
        self._user_input_unparseable_modified = 0
        self._done_present = 0
        self._done_parsed = 0
        self._done_unparseable = 0
        self._conflict_sessions: dict[str, set[int]] = {
            "current": set(),
            "pilot": set(),
        }
        self._boundary_positive_points = 0
        self._boundary_sessions: set[int] = set()
        self._boundary_distances: list[float] = []
        self._boundary_positive_value_seconds = 0.0
        self._raw_total_current_value_seconds = 0.0
        self._sensitivity: dict[str, dict[int, dict[str, float | int]]] = {
            name: {} for name in ("current", "pilot")
        }
        self._lww: dict[str, dict[str, float | int]] = {
            name: {"observed_seconds": 0, "eligible_seconds": 0, "value_hours": 0.0}
            for name in ("current", "pilot")
        }
        self._boundary_sensitivity: dict[str, dict[str, float | int]] = {
            name: {"observed_seconds": 0, "eligible_seconds": 0, "value_hours": 0.0}
            for name in ("current", "pilot")
        }
        self.power_sessions: list[PowerAuditSession] = []

    @staticmethod
    def _add_integral(target: dict[str, float | int], integral: BoundedIntegral) -> None:
        target["observed_seconds"] = int(target["observed_seconds"]) + integral.observed_seconds
        target["eligible_seconds"] = int(target["eligible_seconds"]) + integral.eligible_seconds
        target["value_hours"] = float(target["value_hours"]) + integral.value_hours

    def _add_series(
        self,
        name: str,
        series: CleanSeries,
        *,
        connection: int,
        disconnect: int,
    ) -> None:
        audit = series.audit
        aggregate = self._series[name]
        for field in (
            "raw_samples",
            "invalid_timestamps",
            "invalid_values",
            "exact_duplicate_extras",
            "conflicting_timestamps",
        ):
            aggregate[field] = int(aggregate[field]) + int(getattr(audit, field))
        points = _series_points(series)
        aggregate["retained_samples"] = int(aggregate["retained_samples"]) + len(points)

        thresholds = sorted(
            {
                self.policy.mode_for("chargingCurrent" if name == "current" else "pilotSignal"),
                self.policy.hold_cap_for("chargingCurrent" if name == "current" else "pilotSignal"),
                self.policy.locf_cap_s,
            }
        )
        for threshold in thresholds:
            integral = bounded_locf_integral(
                points,
                start_utc_s=connection,
                end_utc_s=disconnect,
                hold_cap_s=threshold,
            )
            target = self._sensitivity[name].setdefault(
                threshold,
                {"observed_seconds": 0, "eligible_seconds": 0, "value_hours": 0.0},
            )
            self._add_integral(target, integral)

        overrides = tuple(
            point
            for point in series.conflict_lww_overrides
            if connection <= point.timestamp_utc_s < disconnect
        )
        lww = bounded_locf_integral(
            (*points, *overrides),
            start_utc_s=connection,
            end_utc_s=disconnect,
            hold_cap_s=series.locf_cap_s,
        )
        self._add_integral(self._lww[name], lww)

        boundary_points = (*points, *series.boundary_sensitivity_points)
        boundary = bounded_locf_integral(
            boundary_points,
            start_utc_s=connection - self.policy.boundary_sensitivity_s,
            end_utc_s=disconnect + self.policy.boundary_sensitivity_s,
            hold_cap_s=series.locf_cap_s,
        )
        self._add_integral(self._boundary_sensitivity[name], boundary)

    def add(self, cleaned: CleanSession, raw: Mapping[str, Any]) -> None:
        """Consume one clean/raw pair without retaining a private raw record."""

        if cleaned.session_index != self.sessions_processed:
            raise ValueError("cleaned sessions must be added in contiguous anonymous order")
        self.sessions_processed += 1
        self._add_series(
            "current",
            cleaned.current,
            connection=cleaned.connection_utc_s,
            disconnect=cleaned.disconnect_utc_s,
        )
        if cleaned.current.audit.conflicting_timestamps:
            self._conflict_sessions["current"].add(cleaned.session_index)
        if cleaned.pilot.audit.conflicting_timestamps:
            self._conflict_sessions["pilot"].add(cleaned.session_index)
        self._add_series(
            "pilot",
            cleaned.pilot,
            connection=cleaned.connection_utc_s,
            disconnect=cleaned.disconnect_utc_s,
        )

        current_audit = cleaned.current.audit
        positive_count = len(cleaned.current.boundary_positive_points)
        self._boundary_positive_points += positive_count
        if positive_count:
            self._boundary_sessions.add(cleaned.session_index)
        self._boundary_distances.extend(
            float(value) for value in current_audit.boundary_distances_s
        )
        self._boundary_positive_value_seconds += current_audit.boundary_positive_value_seconds
        self._raw_total_current_value_seconds += current_audit.raw_total_value_seconds

        raw_inputs = raw.get("userInputs")
        if isinstance(raw_inputs, list):
            self._user_input_revisions += len(raw_inputs)
            for item in raw_inputs:
                if not isinstance(item, Mapping):
                    self._user_input_unparseable_modified += 1
                    continue
                try:
                    parse_timestamp_utc_s(item.get("modifiedAt"))
                except (TypeError, ValueError):
                    self._user_input_unparseable_modified += 1
        elif raw_inputs is not None:
            self._user_input_revisions += 1
            self._user_input_unparseable_modified += 1
        self._user_input_sanitized += len(cleaned.user_inputs)

        raw_done = raw.get("doneChargingTime")
        if raw_done not in (None, ""):
            self._done_present += 1
            try:
                parse_timestamp_utc_s(raw_done)
            except (TypeError, ValueError):
                self._done_unparseable += 1
            else:
                self._done_parsed += 1

        self.power_sessions.append(
            PowerAuditSession(
                space_id=cleaned.space_id,
                ampere_hours=cleaned.current.main_integral.value_hours,
                kwh_delivered=cleaned.offline_kwh_delivered,
                current_coverage=cleaned.current.main_integral.coverage,
                is_weekend=(
                    datetime.fromtimestamp(cleaned.connection_utc_s, timezone.utc)
                    .astimezone(_LOCAL_ZONE)
                    .weekday()
                    >= 5
                ),
                retained=cleaned.current.audit.conflicting_timestamps == 0,
            )
        )

    def _series_public(self, name: str) -> dict[str, Any]:
        values = self._series[name]
        raw = int(values["raw_samples"])
        retained = int(values["retained_samples"])
        field_name = "chargingCurrent" if name == "current" else "pilotSignal"
        main_integral = self._finalize_integral(
            self._sensitivity[name][self.policy.hold_cap_for(field_name)]
        )
        return {
            **values,
            "retained_sample_rate": _ratio(retained, raw),
            "conflict_affected_sessions": len(self._conflict_sessions[name]),
            "conflicts_isolated_as_missing": True,
            "bounded_observation_coverage": main_integral["coverage"],
            "bounded_value_hours": main_integral["value_hours"],
        }

    def cleaning_qa(self, *, expected_sessions: int) -> dict[str, Any]:
        ready = self._user_input_unparseable_modified == 0
        status = "PASS" if self.sessions_processed == expected_sessions and ready else "FAIL"
        return {
            "schema_version": "acn-jpl-cleaning-qa/v1",
            "status": status,
            "sessions_processed": self.sessions_processed,
            "expected_sessions": expected_sessions,
            "timezone_policy": {
                "internal": "UTC",
                "calendar_mapping": "America/Los_Angeles",
                "aware_only": True,
            },
            "interval_rule": "left_closed_right_open",
            "sampling_interval": {
                "derivation": "mode_of_positive_raw_timestamp_differences",
                "current_mode_seconds": self.policy.current_mode_s,
                "pilot_mode_seconds": self.policy.pilot_mode_s,
                "main_current_hold_seconds": self.policy.hold_cap_for("chargingCurrent"),
                "main_pilot_hold_seconds": self.policy.hold_cap_for("pilotSignal"),
                "unbounded_interpolation": False,
            },
            "duplicate_policy": {
                "exact": "retain_first_remove_extra",
                "conflict_main": "mark_timestamp_missing",
                "conflict_sensitivity": "last_write_wins",
            },
            "current": self._series_public("current"),
            "pilot": self._series_public("pilot"),
            "user_inputs": {
                "raw_revision_count": self._user_input_revisions,
                "sanitized_revision_count": self._user_input_sanitized,
                "unparseable_modified_count": self._user_input_unparseable_modified,
                "issue_time_truncation_ready": ready,
            },
            "retrospective_done_time": {
                "present_count": self._done_present,
                "parsed_count": self._done_parsed,
                "unparseable_count": self._done_unparseable,
                "online_feature_allowed": False,
                "original_value_retained_locally": True,
            },
            "raw_modified": False,
        }

    @staticmethod
    def _finalize_integral(values: Mapping[str, float | int]) -> dict[str, Any]:
        observed = int(values["observed_seconds"])
        eligible = int(values["eligible_seconds"])
        return {
            "observed_seconds": observed,
            "eligible_seconds": eligible,
            "coverage": _ratio(observed, eligible),
            "value_hours": float(values["value_hours"]),
        }

    def cleaning_sensitivity(self) -> dict[str, Any]:
        main_hold = self.policy.hold_cap_for("chargingCurrent")
        thresholds = sorted(self._sensitivity["current"])
        result: dict[str, Any] = {
            "schema_version": "acn-jpl-cleaning-sensitivity/v1",
            "main_hold_seconds": main_hold,
            "hold_thresholds_seconds": thresholds,
            "hold_thresholds": {},
            "last_write_wins": {},
            "boundary_plus_minus_60_seconds": {},
        }
        for name in ("current", "pilot"):
            result["hold_thresholds"][name] = {
                str(threshold): self._finalize_integral(values)
                for threshold, values in sorted(self._sensitivity[name].items())
            }
            main = self._sensitivity[name][
                self.policy.hold_cap_for("chargingCurrent" if name == "current" else "pilotSignal")
            ]
            lww = self._finalize_integral(self._lww[name])
            boundary = self._finalize_integral(self._boundary_sensitivity[name])
            main_hours = float(main["value_hours"])
            result["last_write_wins"][name] = {
                **lww,
                "relative_value_hours_change": (
                    (float(lww["value_hours"]) - main_hours) / main_hours if main_hours else None
                ),
            }
            result["boundary_plus_minus_60_seconds"][name] = {
                **boundary,
                "relative_value_hours_change": (
                    (float(boundary["value_hours"]) - main_hours) / main_hours
                    if main_hours
                    else None
                ),
            }
        return result

    def boundary_current_audit(self) -> dict[str, Any]:
        share = _ratio(
            self._boundary_positive_value_seconds,
            self._raw_total_current_value_seconds,
        )
        return {
            "schema_version": "acn-jpl-boundary-current-audit/v1",
            "status": "PASS",
            "positive_points_excluded": self._boundary_positive_points,
            "sessions_affected": len(self._boundary_sessions),
            "signed_distance_seconds": _distribution(self._boundary_distances),
            "before_connection_count": sum(value < 0 for value in self._boundary_distances),
            "at_or_after_disconnect_count": sum(value >= 0 for value in self._boundary_distances),
            "excluded_positive_ampere_seconds": self._boundary_positive_value_seconds,
            "raw_total_ampere_seconds": self._raw_total_current_value_seconds,
            "current_integral_share": 0.0 if share is None else share,
            "main_result_excludes_boundary_points": True,
            "sensitivity_window_seconds": self.policy.boundary_sensitivity_s,
        }


def build_cleaning_qa(
    accumulator: CleaningAccumulator,
    *,
    modes: SamplingModes,
    expected_sessions: int,
    analysis_window: Mapping[str, Any],
) -> dict[str, Any]:
    """Finalize aggregate cleaning QA without assuming a particular month."""

    cleaning_qa = accumulator.cleaning_qa(expected_sessions=expected_sessions)
    cleaning_qa["sampling_interval"].update(
        {
            "current_positive_delta_count": modes.current.positive_delta_count,
            "pilot_positive_delta_count": modes.pilot.positive_delta_count,
            "current_distinct_positive_delta_count": len(modes.current.delta_histogram),
            "pilot_distinct_positive_delta_count": len(modes.pilot.delta_histogram),
            "current_top_delta_counts": [
                list(item)
                for item in sorted(
                    modes.current.delta_histogram,
                    key=lambda item: (-item[1], item[0]),
                )[:20]
            ],
            "pilot_top_delta_counts": [
                list(item)
                for item in sorted(
                    modes.pilot.delta_histogram,
                    key=lambda item: (-item[1], item[0]),
                )[:20]
            ],
        }
    )
    cleaning_qa["analysis_window"] = dict(analysis_window)
    return cleaning_qa


def build_seasonal_cleaning_sensitivity(
    accumulator: CleaningAccumulator,
) -> dict[str, Any]:
    """Expose separate current/pilot hold grids without changing May output."""

    legacy = accumulator.cleaning_sensitivity()
    current_thresholds = sorted(int(value) for value in legacy["hold_thresholds"]["current"])
    pilot_thresholds = sorted(int(value) for value in legacy["hold_thresholds"]["pilot"])
    return {
        **legacy,
        "schema_version": "acn-jpl-seasonal-cleaning-sensitivity/v1",
        "main_hold_seconds": {
            "current": accumulator.policy.hold_cap_for("chargingCurrent"),
            "pilot": accumulator.policy.hold_cap_for("pilotSignal"),
        },
        "hold_thresholds_seconds": {
            "current": current_thresholds,
            "pilot": pilot_thresholds,
        },
    }


def _require_closed_shape(
    value: object,
    expected: Mapping[str, object],
    *,
    context: str,
) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be an object")
    actual_fields = set(value)
    expected_fields = set(expected)
    if actual_fields != expected_fields:
        unexpected = sorted(actual_fields - expected_fields)
        if unexpected:
            raise ValueError(f"{context} has unexpected fields: {unexpected}")
        missing = sorted(expected_fields - actual_fields)
        raise ValueError(f"{context} is missing required fields: {missing}")
    for name, nested_shape in expected.items():
        if isinstance(nested_shape, Mapping):
            _require_closed_shape(
                value[name],
                nested_shape,
                context=f"{context}.{name}",
            )


def _require_nonnegative_int(
    value: object,
    *,
    context: str,
    positive: bool = False,
) -> int:
    if type(value) is not int:
        raise TypeError(f"{context} must be an integer")
    if value < (1 if positive else 0):
        qualifier = "positive" if positive else "nonnegative"
        raise ValueError(f"{context} must be {qualifier}")
    return value


def _require_finite_number(
    value: object,
    *,
    context: str,
    nonnegative: bool = True,
) -> float:
    if type(value) not in (int, float):
        raise TypeError(f"{context} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{context} must be finite")
    if nonnegative and number < 0:
        raise ValueError(f"{context} must be nonnegative")
    return number


def _numbers_match(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _require_ratio(
    value: object,
    *,
    numerator: float,
    denominator: float,
    context: str,
    null_when_zero: bool,
) -> float | None:
    if denominator == 0:
        if null_when_zero:
            if value is not None:
                raise ValueError(f"{context} must be null for a zero denominator")
            return None
        number = _require_finite_number(value, context=context)
        if number != 0:
            raise ValueError(f"{context} must be zero for a zero denominator")
        return number
    number = _require_finite_number(value, context=context)
    expected = numerator / denominator
    if not _numbers_match(number, expected):
        raise ValueError(f"{context} does not match its numerator and denominator")
    return number


def _require_integral_report(
    report: Mapping[str, Any],
    *,
    context: str,
    value_hours_nonnegative: bool,
) -> tuple[int, int, float | None, float]:
    observed = _require_nonnegative_int(
        report["observed_seconds"],
        context=f"{context} observed seconds",
    )
    eligible = _require_nonnegative_int(
        report["eligible_seconds"],
        context=f"{context} eligible seconds",
    )
    if observed > eligible:
        raise ValueError(f"{context} observed seconds exceed eligible seconds")
    coverage = _require_ratio(
        report["coverage"],
        numerator=observed,
        denominator=eligible,
        context=f"{context} coverage",
        null_when_zero=True,
    )
    value_hours = _require_finite_number(
        report["value_hours"],
        context=f"{context} value hours",
        nonnegative=value_hours_nonnegative,
    )
    return observed, eligible, coverage, value_hours


def _require_sampling_mode(
    mode: SamplingMode,
    *,
    field_name: str,
) -> list[list[int]]:
    if not isinstance(mode, SamplingMode) or mode.field_name != field_name:
        raise ValueError(f"{field_name} sampling mode is not canonical")
    mode_seconds = _require_nonnegative_int(
        mode.mode_seconds,
        context=f"{field_name} mode seconds",
        positive=True,
    )
    positive_delta_count = _require_nonnegative_int(
        mode.positive_delta_count,
        context=f"{field_name} positive delta count",
        positive=True,
    )
    histogram: list[tuple[int, int]] = []
    if not isinstance(mode.delta_histogram, tuple) or not mode.delta_histogram:
        raise TypeError(f"{field_name} delta histogram must be a nonempty tuple")
    for item in mode.delta_histogram:
        if not isinstance(item, tuple) or len(item) != 2:
            raise TypeError(f"{field_name} delta histogram rows must be pairs")
        delta = _require_nonnegative_int(
            item[0], context=f"{field_name} delta", positive=True
        )
        count = _require_nonnegative_int(
            item[1], context=f"{field_name} delta count", positive=True
        )
        histogram.append((delta, count))
    if histogram != sorted(histogram) or len({delta for delta, _ in histogram}) != len(
        histogram
    ):
        raise ValueError(f"{field_name} delta histogram must be uniquely sorted")
    if sum(count for _, count in histogram) != positive_delta_count:
        raise ValueError(f"{field_name} delta histogram count is inconsistent")
    highest_count = max(count for _, count in histogram)
    expected_mode = min(delta for delta, count in histogram if count == highest_count)
    if mode_seconds != expected_mode:
        raise ValueError(f"{field_name} mode does not match its delta histogram")
    return [
        list(item)
        for item in sorted(histogram, key=lambda item: (-item[1], item[0]))[:20]
    ]


def _require_top_delta_rows(
    value: object,
    *,
    expected: list[list[int]],
    context: str,
) -> None:
    if not isinstance(value, list):
        raise TypeError(f"{context} must be a list")
    for row in value:
        if not isinstance(row, list) or len(row) != 2:
            raise TypeError(f"{context} rows must be two-item lists")
        _require_nonnegative_int(row[0], context=f"{context} delta", positive=True)
        _require_nonnegative_int(row[1], context=f"{context} count", positive=True)
    if value != expected:
        raise ValueError(f"{context} does not match the sampling histogram")


def validate_seasonal_cleaning_documents(
    *,
    cleaning_qa: Mapping[str, Any],
    cleaning_sensitivity: Mapping[str, Any],
    boundary_audit: Mapping[str, Any],
    config: JPLMonthConfig,
    modes: SamplingModes,
    policy: CleaningPolicy,
    expected_sessions: int,
) -> None:
    """Validate the exact aggregate seasonal cleaning document contract."""

    if not is_canonical_jpl_month_config(config) or config.month not in SEASONAL_MONTHS:
        raise ValueError("config must be a canonical seasonal month")
    if not isinstance(policy, CleaningPolicy):
        raise TypeError("policy must be a CleaningPolicy")
    if (
        policy.locf_mode_multiplier,
        policy.locf_cap_s,
        policy.boundary_sensitivity_s,
    ) != (3, 60, 60):
        raise ValueError("seasonal cleaning must use the fixed 3x/60s/60s policy")
    expected_sessions = _require_nonnegative_int(
        expected_sessions,
        context="expected sessions",
        positive=True,
    )
    if not isinstance(modes, SamplingModes):
        raise TypeError("modes must be SamplingModes")
    expected_top_deltas = {
        "current": _require_sampling_mode(
            modes.current,
            field_name="chargingCurrent",
        ),
        "pilot": _require_sampling_mode(
            modes.pilot,
            field_name="pilotSignal",
        ),
    }
    if (
        policy.current_mode_s != modes.current.mode_seconds
        or policy.pilot_mode_s != modes.pilot.mode_seconds
    ):
        raise ValueError("seasonal cleaning policy modes do not match observed modes")
    leaf = None
    series_shape = {
        name: leaf
        for name in (
            "raw_samples",
            "retained_samples",
            "invalid_timestamps",
            "invalid_values",
            "exact_duplicate_extras",
            "conflicting_timestamps",
            "retained_sample_rate",
            "conflict_affected_sessions",
            "conflicts_isolated_as_missing",
            "bounded_observation_coverage",
            "bounded_value_hours",
        )
    }
    _require_closed_shape(
        cleaning_qa,
        {
            "schema_version": leaf,
            "status": leaf,
            "sessions_processed": leaf,
            "expected_sessions": leaf,
            "timezone_policy": {
                "internal": leaf,
                "calendar_mapping": leaf,
                "aware_only": leaf,
            },
            "interval_rule": leaf,
            "sampling_interval": {
                name: leaf
                for name in (
                    "derivation",
                    "current_mode_seconds",
                    "pilot_mode_seconds",
                    "main_current_hold_seconds",
                    "main_pilot_hold_seconds",
                    "unbounded_interpolation",
                    "current_positive_delta_count",
                    "pilot_positive_delta_count",
                    "current_distinct_positive_delta_count",
                    "pilot_distinct_positive_delta_count",
                    "current_top_delta_counts",
                    "pilot_top_delta_counts",
                )
            },
            "duplicate_policy": {
                "exact": leaf,
                "conflict_main": leaf,
                "conflict_sensitivity": leaf,
            },
            "current": series_shape,
            "pilot": series_shape,
            "user_inputs": {
                "raw_revision_count": leaf,
                "sanitized_revision_count": leaf,
                "unparseable_modified_count": leaf,
                "issue_time_truncation_ready": leaf,
            },
            "retrospective_done_time": {
                "present_count": leaf,
                "parsed_count": leaf,
                "unparseable_count": leaf,
                "online_feature_allowed": leaf,
                "original_value_retained_locally": leaf,
            },
            "raw_modified": leaf,
            "analysis_window": {
                "month": leaf,
                "timezone": leaf,
                "local_start_inclusive": leaf,
                "local_end_exclusive": leaf,
                "utc_start_inclusive": leaf,
                "utc_end_exclusive": leaf,
            },
        },
        context="cleaning QA",
    )
    sessions_processed = _require_nonnegative_int(
        cleaning_qa["sessions_processed"],
        context="cleaning QA sessions processed",
    )
    declared_expected_sessions = _require_nonnegative_int(
        cleaning_qa["expected_sessions"],
        context="cleaning QA expected sessions",
        positive=True,
    )
    if (
        cleaning_qa["schema_version"] != "acn-jpl-cleaning-qa/v1"
        or cleaning_qa["status"] != "PASS"
        or sessions_processed != expected_sessions
        or declared_expected_sessions != expected_sessions
        or cleaning_qa["raw_modified"] is not False
    ):
        raise ValueError("cleaning QA status/count/raw contract is inconsistent")
    expected_analysis_window = {
        "month": config.month,
        "timezone": config.timezone_name,
        "local_start_inclusive": config.local_start.isoformat(),
        "local_end_exclusive": config.local_end.isoformat(),
        "utc_start_inclusive": config.utc_start.isoformat(),
        "utc_end_exclusive": config.utc_end.isoformat(),
    }
    if cleaning_qa["analysis_window"] != expected_analysis_window:
        raise ValueError("cleaning QA analysis window does not match the month config")
    timezone_policy = cleaning_qa["timezone_policy"]
    if (
        timezone_policy["internal"] != "UTC"
        or timezone_policy["calendar_mapping"] != "America/Los_Angeles"
        or timezone_policy["aware_only"] is not True
    ):
        raise ValueError("cleaning QA timezone policy is inconsistent")
    if cleaning_qa.get("interval_rule") != "left_closed_right_open":
        raise ValueError("cleaning QA interval rule is inconsistent")
    if cleaning_qa["duplicate_policy"] != {
        "exact": "retain_first_remove_extra",
        "conflict_main": "mark_timestamp_missing",
        "conflict_sensitivity": "last_write_wins",
    }:
        raise ValueError("cleaning QA duplicate policy is inconsistent")
    user_inputs = cleaning_qa["user_inputs"]
    raw_revisions = _require_nonnegative_int(
        user_inputs["raw_revision_count"],
        context="cleaning QA raw user-input revisions",
    )
    sanitized_revisions = _require_nonnegative_int(
        user_inputs["sanitized_revision_count"],
        context="cleaning QA sanitized user-input revisions",
    )
    unparseable_revisions = _require_nonnegative_int(
        user_inputs["unparseable_modified_count"],
        context="cleaning QA unparseable user-input revisions",
    )
    if (
        sanitized_revisions > raw_revisions
        or unparseable_revisions > raw_revisions
        or sanitized_revisions + unparseable_revisions != raw_revisions
        or unparseable_revisions != 0
        or user_inputs["issue_time_truncation_ready"] is not True
    ):
        raise ValueError("cleaning QA user-input truncation is not ready")
    retrospective = cleaning_qa["retrospective_done_time"]
    done_present = _require_nonnegative_int(
        retrospective["present_count"],
        context="cleaning QA done-time present count",
    )
    done_parsed = _require_nonnegative_int(
        retrospective["parsed_count"],
        context="cleaning QA done-time parsed count",
    )
    done_unparseable = _require_nonnegative_int(
        retrospective["unparseable_count"],
        context="cleaning QA done-time unparseable count",
    )
    if (
        done_present > sessions_processed
        or done_parsed + done_unparseable != done_present
        or retrospective["online_feature_allowed"] is not False
        or retrospective["original_value_retained_locally"] is not True
    ):
        raise ValueError("cleaning QA retrospective done-time policy is inconsistent")
    sampling = cleaning_qa["sampling_interval"]
    sampling_modes = {
        "current": _require_nonnegative_int(
            sampling["current_mode_seconds"],
            context="cleaning QA current mode seconds",
            positive=True,
        ),
        "pilot": _require_nonnegative_int(
            sampling["pilot_mode_seconds"],
            context="cleaning QA pilot mode seconds",
            positive=True,
        ),
    }
    sampling_holds = {
        "current": _require_nonnegative_int(
            sampling["main_current_hold_seconds"],
            context="cleaning QA current hold seconds",
            positive=True,
        ),
        "pilot": _require_nonnegative_int(
            sampling["main_pilot_hold_seconds"],
            context="cleaning QA pilot hold seconds",
            positive=True,
        ),
    }
    sampling_positive_counts = {
        "current": _require_nonnegative_int(
            sampling["current_positive_delta_count"],
            context="cleaning QA current positive delta count",
            positive=True,
        ),
        "pilot": _require_nonnegative_int(
            sampling["pilot_positive_delta_count"],
            context="cleaning QA pilot positive delta count",
            positive=True,
        ),
    }
    sampling_distinct_counts = {
        "current": _require_nonnegative_int(
            sampling["current_distinct_positive_delta_count"],
            context="cleaning QA current distinct delta count",
            positive=True,
        ),
        "pilot": _require_nonnegative_int(
            sampling["pilot_distinct_positive_delta_count"],
            context="cleaning QA pilot distinct delta count",
            positive=True,
        ),
    }
    _require_top_delta_rows(
        sampling["current_top_delta_counts"],
        expected=expected_top_deltas["current"],
        context="cleaning QA current top deltas",
    )
    _require_top_delta_rows(
        sampling["pilot_top_delta_counts"],
        expected=expected_top_deltas["pilot"],
        context="cleaning QA pilot top deltas",
    )
    if (
        sampling["derivation"]
        != "mode_of_positive_raw_timestamp_differences"
        or sampling_modes["current"] != modes.current.mode_seconds
        or sampling_modes["pilot"] != modes.pilot.mode_seconds
        or sampling_holds["current"] != policy.hold_cap_for("chargingCurrent")
        or sampling_holds["pilot"] != policy.hold_cap_for("pilotSignal")
        or sampling_positive_counts["current"] != modes.current.positive_delta_count
        or sampling_positive_counts["pilot"] != modes.pilot.positive_delta_count
        or sampling_distinct_counts["current"] != len(modes.current.delta_histogram)
        or sampling_distinct_counts["pilot"] != len(modes.pilot.delta_histogram)
        or sampling["unbounded_interpolation"] is not False
    ):
        raise ValueError("cleaning QA sampling policy is inconsistent")
    main_series: dict[str, tuple[float, float]] = {}
    for name in ("current", "pilot"):
        section = cleaning_qa[name]
        count_names = (
            "raw_samples",
            "retained_samples",
            "invalid_timestamps",
            "invalid_values",
            "exact_duplicate_extras",
            "conflicting_timestamps",
            "conflict_affected_sessions",
        )
        counts = {
            field: _require_nonnegative_int(
                section[field],
                context=f"cleaning QA {name} {field}",
            )
            for field in count_names
        }
        valid_observations = (
            counts["raw_samples"]
            - counts["invalid_timestamps"]
            - counts["invalid_values"]
        )
        producer_retained_upper_bound = (
            valid_observations
            - counts["exact_duplicate_extras"]
            - 2 * counts["conflicting_timestamps"]
        )
        if (
            counts["retained_samples"] > counts["raw_samples"]
            or valid_observations < 0
            or counts["exact_duplicate_extras"] > valid_observations
            or counts["conflicting_timestamps"] > valid_observations
            or counts["retained_samples"] > producer_retained_upper_bound
            or counts["conflict_affected_sessions"] > sessions_processed
            or counts["conflict_affected_sessions"]
            > counts["conflicting_timestamps"]
            or section["conflicts_isolated_as_missing"] is not True
        ):
            raise ValueError(f"cleaning QA {name} counts are inconsistent")
        _require_ratio(
            section["retained_sample_rate"],
            numerator=counts["retained_samples"],
            denominator=counts["raw_samples"],
            context=f"cleaning QA {name} retained rate",
            null_when_zero=True,
        )
        coverage = _require_finite_number(
            section["bounded_observation_coverage"],
            context=f"cleaning QA {name} bounded coverage",
        )
        if coverage > 1:
            raise ValueError(f"cleaning QA {name} bounded coverage exceeds one")
        value_hours = _require_finite_number(
            section["bounded_value_hours"],
            context=f"cleaning QA {name} bounded value hours",
            nonnegative=name == "current",
        )
        main_series[name] = (coverage, value_hours)

    expected_holds = {
        "current": policy.hold_cap_for("chargingCurrent"),
        "pilot": policy.hold_cap_for("pilotSignal"),
    }
    expected_thresholds = {
        "current": sorted(
            {
                policy.mode_for("chargingCurrent"),
                expected_holds["current"],
                policy.locf_cap_s,
            }
        ),
        "pilot": sorted(
            {
                policy.mode_for("pilotSignal"),
                expected_holds["pilot"],
                policy.locf_cap_s,
            }
        ),
    }
    integral_shape = {
        "observed_seconds": leaf,
        "eligible_seconds": leaf,
        "coverage": leaf,
        "value_hours": leaf,
    }
    comparison_shape = {**integral_shape, "relative_value_hours_change": leaf}
    _require_closed_shape(
        cleaning_sensitivity,
        {
            "schema_version": leaf,
            "main_hold_seconds": {"current": leaf, "pilot": leaf},
            "hold_thresholds_seconds": {"current": leaf, "pilot": leaf},
            "hold_thresholds": {
                name: {
                    str(threshold): integral_shape
                    for threshold in expected_thresholds[name]
                }
                for name in ("current", "pilot")
            },
            "last_write_wins": {
                "current": comparison_shape,
                "pilot": comparison_shape,
            },
            "boundary_plus_minus_60_seconds": {
                "current": comparison_shape,
                "pilot": comparison_shape,
            },
        },
        context="cleaning sensitivity",
    )
    if cleaning_sensitivity.get("schema_version") != (
        "acn-jpl-seasonal-cleaning-sensitivity/v1"
    ):
        raise ValueError("cleaning sensitivity schema is invalid")
    declared_holds = cleaning_sensitivity["main_hold_seconds"]
    for name in ("current", "pilot"):
        _require_nonnegative_int(
            declared_holds[name],
            context=f"cleaning sensitivity {name} main hold",
            positive=True,
        )
    if declared_holds != expected_holds:
        raise ValueError("cleaning sensitivity main holds are inconsistent")
    declared_thresholds = cleaning_sensitivity["hold_thresholds_seconds"]
    for name in ("current", "pilot"):
        if not isinstance(declared_thresholds[name], list):
            raise TypeError(f"cleaning sensitivity {name} thresholds must be a list")
        for threshold in declared_thresholds[name]:
            _require_nonnegative_int(
                threshold,
                context=f"cleaning sensitivity {name} threshold",
                positive=True,
            )
    if declared_thresholds != expected_thresholds:
        raise ValueError("cleaning sensitivity hold thresholds are inconsistent")
    threshold_integrals: dict[str, dict[int, tuple[int, int, float | None, float]]] = {
        "current": {},
        "pilot": {},
    }
    for name in ("current", "pilot"):
        previous_observed = -1
        expected_eligible: int | None = None
        for threshold in expected_thresholds[name]:
            report = cleaning_sensitivity["hold_thresholds"][name][str(threshold)]
            integral = _require_integral_report(
                report,
                context=f"cleaning sensitivity {name} hold {threshold}",
                value_hours_nonnegative=name == "current",
            )
            observed, eligible, _, _ = integral
            if observed < previous_observed:
                raise ValueError(
                    f"cleaning sensitivity {name} observation must increase with hold"
                )
            if expected_eligible is not None and eligible != expected_eligible:
                raise ValueError(
                    f"cleaning sensitivity {name} eligible seconds are inconsistent"
                )
            previous_observed = observed
            expected_eligible = eligible
            threshold_integrals[name][threshold] = integral

        main_integral = threshold_integrals[name][expected_holds[name]]
        main_coverage = main_integral[2]
        if main_coverage is None or not _numbers_match(
            main_coverage,
            main_series[name][0],
        ) or not _numbers_match(main_integral[3], main_series[name][1]):
            raise ValueError(
                f"cleaning sensitivity {name} main result differs from cleaning QA"
            )

        for comparison_name in (
            "last_write_wins",
            "boundary_plus_minus_60_seconds",
        ):
            report = cleaning_sensitivity[comparison_name][name]
            _, eligible, _, value_hours = _require_integral_report(
                report,
                context=f"cleaning sensitivity {comparison_name} {name}",
                value_hours_nonnegative=name == "current",
            )
            main_hours = main_integral[3]
            relative_change = report["relative_value_hours_change"]
            if main_hours == 0:
                if relative_change is not None:
                    raise ValueError(
                        f"cleaning sensitivity {comparison_name} {name} relative change "
                        "must be null for zero main value hours"
                    )
            else:
                relative_number = _require_finite_number(
                    relative_change,
                    context=(
                        f"cleaning sensitivity {comparison_name} {name} relative change"
                    ),
                    nonnegative=False,
                )
                expected_change = (value_hours - main_hours) / main_hours
                if not _numbers_match(relative_number, expected_change):
                    raise ValueError(
                        f"cleaning sensitivity {comparison_name} {name} relative change "
                        "is inconsistent"
                    )
            expected_comparison_eligible = main_integral[1]
            if comparison_name == "boundary_plus_minus_60_seconds":
                expected_comparison_eligible += (
                    2 * policy.boundary_sensitivity_s * sessions_processed
                )
            if eligible != expected_comparison_eligible:
                raise ValueError(
                    f"cleaning sensitivity {comparison_name} {name} eligible seconds "
                    "are inconsistent"
                )

    _require_closed_shape(
        boundary_audit,
        {
            "schema_version": leaf,
            "status": leaf,
            "positive_points_excluded": leaf,
            "sessions_affected": leaf,
            "signed_distance_seconds": {
                "count": leaf,
                "minimum": leaf,
                "p05": leaf,
                "median": leaf,
                "p95": leaf,
                "maximum": leaf,
            },
            "before_connection_count": leaf,
            "at_or_after_disconnect_count": leaf,
            "excluded_positive_ampere_seconds": leaf,
            "raw_total_ampere_seconds": leaf,
            "current_integral_share": leaf,
            "main_result_excludes_boundary_points": leaf,
            "sensitivity_window_seconds": leaf,
        },
        context="boundary current audit",
    )
    positive_points = _require_nonnegative_int(
        boundary_audit["positive_points_excluded"],
        context="boundary audit positive points excluded",
    )
    affected_sessions = _require_nonnegative_int(
        boundary_audit["sessions_affected"],
        context="boundary audit affected sessions",
    )
    before_connection = _require_nonnegative_int(
        boundary_audit["before_connection_count"],
        context="boundary audit before-connection count",
    )
    at_or_after_disconnect = _require_nonnegative_int(
        boundary_audit["at_or_after_disconnect_count"],
        context="boundary audit at-or-after-disconnect count",
    )
    distance = boundary_audit["signed_distance_seconds"]
    distance_count = _require_nonnegative_int(
        distance["count"],
        context="boundary audit distance count",
    )
    distance_statistics: list[float] = []
    for field in ("minimum", "p05", "median", "p95", "maximum"):
        value = distance[field]
        if distance_count == 0:
            if value is not None:
                raise ValueError(
                    f"boundary audit distance {field} must be null for zero count"
                )
        else:
            distance_statistics.append(
                _require_finite_number(
                    value,
                    context=f"boundary audit distance {field}",
                    nonnegative=False,
                )
            )
    if distance_statistics != sorted(distance_statistics):
        raise ValueError("boundary audit distance statistics are not ordered")
    excluded_ampere_seconds = _require_finite_number(
        boundary_audit["excluded_positive_ampere_seconds"],
        context="boundary audit excluded positive ampere seconds",
    )
    raw_ampere_seconds = _require_finite_number(
        boundary_audit["raw_total_ampere_seconds"],
        context="boundary audit raw total ampere seconds",
    )
    share = _require_ratio(
        boundary_audit["current_integral_share"],
        numerator=excluded_ampere_seconds,
        denominator=raw_ampere_seconds,
        context="boundary audit current integral share",
        null_when_zero=False,
    )
    sensitivity_window = _require_nonnegative_int(
        boundary_audit["sensitivity_window_seconds"],
        context="boundary audit sensitivity window",
        positive=True,
    )
    if (
        boundary_audit["schema_version"] != "acn-jpl-boundary-current-audit/v1"
        or boundary_audit["status"] != "PASS"
        or boundary_audit["main_result_excludes_boundary_points"] is not True
        or sensitivity_window != policy.boundary_sensitivity_s
        or positive_points != distance_count
        or before_connection + at_or_after_disconnect != distance_count
        or affected_sessions > sessions_processed
        or affected_sessions > distance_count
        or excluded_ampere_seconds > raw_ampere_seconds
        or share is None
        or share > 1
    ):
        raise ValueError("boundary current audit policy is inconsistent")


def json_safe_payload(payload: object) -> object:
    """Recursively copy immutable snapshot material into JSON-native containers."""

    if isinstance(payload, Mapping):
        return {key: json_safe_payload(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [json_safe_payload(value) for value in payload]
    return payload


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            json_safe_payload(payload),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _yaml_bytes(payload: object) -> bytes:
    return yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=True,
        default_flow_style=False,
    ).encode("utf-8")


def _deterministic_gzip_jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    """Serialize JSONL with a zero gzip timestamp and no source filename."""

    target = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
        for row in rows:
            line = json.dumps(
                json_safe_payload(row),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            compressed.write(line + b"\n")
    return target.getvalue()


def _deterministic_npz_bytes(arrays: Mapping[str, np.ndarray]) -> bytes:
    """Build a pickle-free NPZ whose ZIP metadata is stable across runs."""

    target = io.BytesIO()
    with zipfile.ZipFile(
        target,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for name in sorted(arrays):
            if not name or Path(name).name != name:
                raise ValueError("NPZ array names must be safe flat names")
            array = np.asarray(arrays[name])
            if array.dtype.hasobject:
                raise TypeError("NPZ arrays cannot require pickle")
            payload = io.BytesIO()
            np.lib.format.write_array(payload, array, allow_pickle=False)
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload.getvalue(), compress_type=zipfile.ZIP_DEFLATED)
    return target.getvalue()


def close_public_artifacts(contents: Mapping[str, bytes | str]) -> dict[str, bytes]:
    """Close twelve aggregate payloads with a deterministic thirteenth hash file."""

    if set(contents) != set(_PUBLIC_PAYLOAD_NAMES):
        raise ValueError("public payload set must contain exactly the twelve unhashed files")
    closed: dict[str, bytes] = {}
    for name in _PUBLIC_PAYLOAD_NAMES:
        value = contents[name]
        closed[name] = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    lines = [
        f"{hashlib.sha256(closed[name]).hexdigest()}  {name}" for name in _PUBLIC_PAYLOAD_NAMES
    ]
    closed["SHA256SUMS"] = ("\n".join(lines) + "\n").encode("utf-8")
    validate_public_artifacts(closed)
    return closed


def verify_public_release(output_root: str | Path) -> bool:
    """Verify exact filenames, public privacy, and every declared payload hash."""

    root = Path(output_root)
    if not root.is_dir():
        return False
    children = tuple(root.iterdir())
    if any(not path.is_file() for path in children):
        return False
    files = {path.name: path for path in children}
    if set(files) != set(PUBLIC_ARTIFACT_NAMES):
        return False
    try:
        contents = {name: files[name].read_bytes() for name in PUBLIC_ARTIFACT_NAMES}
        validate_public_artifacts(contents)
        declared: dict[str, str] = {}
        for line in contents["SHA256SUMS"].decode("utf-8").splitlines():
            digest, name = line.split("  ", 1)
            if name in declared:
                return False
            declared[name] = digest
    except (OSError, UnicodeError, ValueError):
        return False
    if set(declared) != set(_PUBLIC_PAYLOAD_NAMES):
        return False
    return all(
        declared[name] == hashlib.sha256(contents[name]).hexdigest()
        for name in _PUBLIC_PAYLOAD_NAMES
    )


def _safe_remove_generated_tree(path: Path, *, expected_parent: Path) -> None:
    resolved = path.resolve(strict=False)
    parent = expected_parent.resolve(strict=False)
    if resolved.parent != parent or not resolved.name.startswith("."):
        raise ValueError("refusing to remove an unexpected generated directory")
    if resolved.exists():
        shutil.rmtree(resolved)


def _assert_replaceable_public_destination(path: Path) -> None:
    if not path.exists():
        return
    if not path.is_dir():
        raise ValueError("public output destination must be a directory")
    children = tuple(path.iterdir())
    if any(not child.is_file() for child in children):
        raise ValueError("existing public output contains a non-file entry")
    names = {child.name for child in children}
    if not names <= set(PUBLIC_ARTIFACT_NAMES):
        raise ValueError("existing public output contains an unrelated file")


def publish_public_release(
    contents: Mapping[str, bytes],
    *,
    output_root: str | Path,
    raw_root: str | Path,
) -> None:
    """Validate and atomically replace the closed public output directory."""

    validate_public_artifacts(contents)
    destination = guard_write_target(output_root, raw_root=raw_root)
    _assert_replaceable_public_destination(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    backup: Path | None = None
    try:
        for name in PUBLIC_ARTIFACT_NAMES:
            payload = contents.get(name)
            if not isinstance(payload, bytes):
                raise TypeError("closed public artifacts must contain bytes")
            (staging / name).write_bytes(payload)
        if not verify_public_release(staging):
            raise ValueError("staged public release did not verify")
        if destination.exists():
            backup = destination.with_name(f".{destination.name}.backup-{os.getpid()}")
            _safe_remove_generated_tree(backup, expected_parent=destination.parent)
            os.replace(destination, backup)
        os.replace(staging, destination)
        if backup is not None:
            _safe_remove_generated_tree(backup, expected_parent=destination.parent)
    except BaseException:
        if staging.exists():
            _safe_remove_generated_tree(staging, expected_parent=destination.parent)
        if backup is not None and backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise


def _iter_cleaned(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("cleaned JSONL record must be an object")
                yield payload


def _checkpoint(
    path: Path,
    *,
    raw_root: Path,
    phase: str,
    source_inventory_sha256: str,
    details: Mapping[str, Any],
) -> None:
    atomic_write_json(
        path,
        {
            "schema_version": "acn-jpl-gate1-checkpoint/v1",
            "phase": phase,
            "source_inventory_sha256": source_inventory_sha256,
            "details": dict(details),
        },
        raw_root=raw_root,
    )


def _station_csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise ValueError("station rows cannot be empty")
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    target = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as compressed:
        compressed.write(text.getvalue().encode("utf-8"))
    return target.getvalue()


def _station_npz_arrays(rows: Sequence[Mapping[str, Any]]) -> dict[str, np.ndarray]:
    numeric_names = (
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

    def number(value: object) -> float:
        return math.nan if value is None else float(value)

    return {
        "timestamp_utc_s": np.asarray(
            [
                int(
                    datetime.fromisoformat(
                        str(row["timestamp_utc"]).replace("Z", "+00:00")
                    ).timestamp()
                )
                for row in rows
            ],
            dtype=np.int64,
        ),
        "calendar": np.asarray(
            [
                [
                    int(row["quarter_hour_index"]),
                    int(row["day_of_week"]),
                    int(bool(row["is_weekend"])),
                ]
                for row in rows
            ],
            dtype=np.int16,
        ),
        "numeric": np.asarray(
            [[number(row[name]) for name in numeric_names] for row in rows],
            dtype=np.float32,
        ),
        "validity": np.asarray(
            [
                [
                    bool(row["valid_bin_80"]),
                    bool(row["valid_bin_90"]),
                    bool(row["valid_bin_95"]),
                ]
                for row in rows
            ],
            dtype=np.bool_,
        ),
    }


def _snapshot_npz_payloads(result: IssueSnapshotResult) -> dict[str, bytes]:
    histories = np.asarray(
        [
            [
                math.nan if value is None else float(value)
                for value in row["history_station_current_mean_a"]
            ]
            for row in result.m1_rows
        ],
        dtype=np.float32,
    )
    masks = np.asarray([row["history_observed_mask"] for row in result.m1_rows], dtype=np.bool_)
    issue_times = np.asarray([row["issue_time_utc_s"] for row in result.m1_rows], dtype=np.int64)
    m1 = _deterministic_npz_bytes(
        {
            "issue_time_utc_s": issue_times,
            "history_station_current_mean_a": histories,
            "history_observed_mask": masks,
            "calendar": np.asarray(
                [
                    [
                        row["quarter_hour_index"],
                        row["day_of_week"],
                        int(row["is_weekend"]),
                    ]
                    for row in result.m1_rows
                ],
                dtype=np.int16,
            ),
        }
    )
    m2_names = (
        "connected_session_count",
        "active_charging_session_count",
        "station_current_a",
        "station_current_observed_ratio",
        "pilot_sum_a",
        "pilot_mean_a",
    )
    m2 = _deterministic_npz_bytes(
        {
            "issue_time_utc_s": issue_times,
            "history_station_current_mean_a": histories,
            "history_observed_mask": masks,
            "current_state": np.asarray(
                [
                    [math.nan if row[name] is None else float(row[name]) for name in m2_names]
                    for row in result.m2_rows
                ],
                dtype=np.float32,
            ),
        }
    )
    horizons = tuple(int(value) for value in result.qa["horizons_minutes"])
    labels = _deterministic_npz_bytes(
        {
            "issue_time_utc_s": np.asarray(
                [row["issue_time_utc_s"] for row in result.label_rows], dtype=np.int64
            ),
            "horizons_minutes": np.asarray(horizons, dtype=np.int16),
            "station_current_mean_a": np.asarray(
                [
                    [float(row["labels"][str(horizon)]) for horizon in horizons]
                    for row in result.label_rows
                ],
                dtype=np.float32,
            ),
        }
    )
    return {"m1.npz": m1, "m2.npz": m2, "labels.npz": labels}


def _artifact_entry(name: str, payload: bytes) -> dict[str, Any]:
    return {
        "artifact_name": name,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _artifact_file_entry(path: Path, *, known_sha256: str | None = None) -> dict[str, Any]:
    digest = hashlib.sha256()
    if known_sha256 is None:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        sha256 = digest.hexdigest()
    else:
        sha256 = known_sha256
    return {
        "artifact_name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256,
    }


def _environment_manifest() -> dict[str, Any]:
    torch_version = "unavailable"
    cuda_version = "unavailable"
    gpu = "unavailable"
    try:
        environment = json.loads(
            Path("outputs/environment/local_rtx5080.json").read_text(encoding="utf-8")
        )
        if isinstance(environment, Mapping):
            pytorch = environment.get("pytorch")
            gpu_section = environment.get("gpu")
            if isinstance(pytorch, Mapping):
                torch_version = str(pytorch.get("version", "unavailable"))
                cuda_version = str(pytorch.get("cuda_runtime", "unavailable"))
            if isinstance(gpu_section, Mapping):
                devices = gpu_section.get("devices")
                if isinstance(devices, list) and devices and isinstance(devices[0], Mapping):
                    gpu = str(devices[0].get("name", "unavailable"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    return {
        "python": platform.python_version(),
        "pytorch": torch_version,
        "pytorch_channel": "nightly" if ".dev" in torch_version else "unknown",
        "cuda": cuda_version,
        "gpu": gpu,
        "training_environment_frozen": "NO",
        "training_run": False,
        "driver_modified": False,
        "system_cuda_modified": False,
        "network_access_used": False,
    }


def _load_protocol(path: str | Path) -> tuple[dict[str, Any], str]:
    source = Path(path)
    raw = source.read_bytes()
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise TypeError("preparation protocol root must be a mapping")
    required = {
        "schema_version",
        "analysis",
        "cleaning",
        "aggregation",
        "snapshots",
        "continuity_gate",
        "power_audit",
    }
    if set(payload) != required:
        raise ValueError("preparation protocol has an unexpected top-level schema")
    if payload["schema_version"] != "acn-jpl-gate1-protocol/v1":
        raise ValueError("preparation protocol schema version is not supported")
    return payload, hashlib.sha256(raw).hexdigest()


def _validate_output_topology(raw_root: Path, outputs: Sequence[Path]) -> tuple[Path, ...]:
    raw = raw_root.resolve(strict=False)
    resolved = tuple(path.resolve(strict=False) for path in outputs)
    for output in resolved:
        if output == raw or raw in output.parents or output in raw.parents:
            raise ValueError("raw and output roots must not contain one another")
    for index, left in enumerate(resolved):
        for right in resolved[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise ValueError("output roots must be distinct non-overlapping directories")
    return resolved


def _power_decision_markdown(power_audit: Mapping[str, Any]) -> str:
    status = str(power_audit["status"])
    return (
        "# JPL power-semantics decision\n\n"
        f"Status: `{status}`\n\n"
        "The audited signal remains a station-current proxy. The pinned 208 V network "
        "default and offline energy comparison do not make it directly measured active "
        "power. No reconstructed-power column is authorized or published by this task.\n\n"
        "Static mirror: `NOT_USED`. Final authorization remains with main control.\n"
    )


def _public_payloads(
    *,
    cleaning_qa: Mapping[str, Any],
    cleaning_sensitivity: Mapping[str, Any],
    boundary_audit: Mapping[str, Any],
    power_audit: Mapping[str, Any],
    station_qa: Mapping[str, Any],
    issue_qa: Mapping[str, Any],
    snapshot_manifest: Mapping[str, Any],
    run_manifest: Mapping[str, Any],
) -> dict[str, bytes]:
    temporal = issue_qa["temporal_violations"]
    leakage = {
        "schema_version": "acn-jpl-leakage-audit/v1",
        "status": issue_qa["leakage_audit"],
        "future_field_count": len(issue_qa["future_fields_found"]),
        "unexpected_feature_key_count": len(issue_qa["unexpected_feature_keys"]),
        "temporal_violation_count": temporal["total"],
        "issue_time_user_input_status": issue_qa["user_inputs_issue_time_truncation"]["status"],
        "feature_whitelist_status": issue_qa["feature_whitelist_enforcement"]["status"],
        "identifiers_emitted": False,
        "future_outcome_fields_emitted": False,
    }
    return {
        "cleaning_qa.json": _json_bytes(cleaning_qa),
        "cleaning_sensitivity.json": _json_bytes(cleaning_sensitivity),
        "boundary_current_audit.json": _json_bytes(boundary_audit),
        "power_semantics_audit.json": _json_bytes(power_audit),
        "power_semantics_decision.md": _power_decision_markdown(power_audit).encode("utf-8"),
        "station_15min_qa.json": _json_bytes(station_qa),
        "issue_snapshot_qa.json": _json_bytes(issue_qa),
        "leakage_audit.json": _json_bytes(leakage),
        "feature_whitelist.yaml": _yaml_bytes(feature_whitelist_document()),
        "feature_blacklist.yaml": _yaml_bytes(feature_blacklist_document()),
        "data_snapshot_manifest.json": _json_bytes(snapshot_manifest),
        "run_manifest.json": _json_bytes(run_manifest),
    }


def _remove_known_partial(path: Path, *, raw_root: Path) -> None:
    guarded = guard_write_target(path, raw_root=raw_root)
    if guarded.is_file():
        guarded.unlink()


def prepare_jpl_gate1_data(
    *,
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    interim_root: str | Path = DEFAULT_INTERIM_ROOT,
    processed_root: str | Path = DEFAULT_PROCESSED_ROOT,
    public_root: str | Path = DEFAULT_PUBLIC_ROOT,
    protocol_path: str | Path = DEFAULT_PROTOCOL_PATH,
) -> PreparationResult:
    """Run the authorized CPU-only JPL preparation and publish aggregate QA."""

    raw = Path(raw_root).resolve(strict=False)
    interim, processed, public = _validate_output_topology(
        raw,
        (Path(interim_root), Path(processed_root), Path(public_root)),
    )
    protocol, protocol_sha256 = _load_protocol(protocol_path)
    before_validation = validate_raw_snapshot(raw)
    before = before_validation.inventory
    if before_validation.total_record_count != int(protocol["analysis"]["expected_raw_objects"]):
        raise ValueError("raw object count does not match the frozen protocol")
    interim.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    for checkpoint_path in (
        interim / "preparation_checkpoint.json",
        processed / "preparation_checkpoint.json",
    ):
        _checkpoint(
            checkpoint_path,
            raw_root=raw,
            phase="raw_validated",
            source_inventory_sha256=before.digest,
            details={"raw_object_count": before_validation.total_record_count},
        )
    modes = derive_sampling_modes(record.payload for record in iter_validated_raw_records(raw))
    expected_mode = int(protocol["cleaning"]["expected_sampling_mode_seconds"])
    policy = cleaning_policy_from_sampling_modes(
        modes,
        locf_mode_multiplier=int(protocol["cleaning"]["locf_mode_multiplier"]),
        locf_cap_seconds=int(protocol["cleaning"]["locf_cap_seconds"]),
        boundary_sensitivity_seconds=int(
            protocol["cleaning"]["boundary_sensitivity_seconds"]
        ),
        required_mode_seconds=expected_mode,
    )
    expected_hold = min(
        int(protocol["cleaning"]["locf_mode_multiplier"]) * expected_mode,
        int(protocol["cleaning"]["locf_cap_seconds"]),
    )
    if policy.hold_cap_for("chargingCurrent") != expected_hold:
        raise ValueError("frozen snapshot did not reproduce the audited 12-second hold cap")

    accumulator = CleaningAccumulator(policy)
    cleaned_path = interim / "cleaned_sessions.jsonl.gz"
    for partial in (
        cleaned_path.with_name(f"{cleaned_path.name}.partial"),
        cleaned_path.with_name(f"{cleaned_path.name}.manifest.json.partial"),
    ):
        _remove_known_partial(partial, raw_root=raw)

    def cleaned_sessions() -> Iterator[CleanSession]:
        for raw_record in iter_validated_raw_records(raw):
            cleaned = clean_session(
                raw_record.payload,
                session_index=raw_record.ordinal,
                policy=policy,
            )
            accumulator.add(cleaned, raw_record.payload)
            yield cleaned

    cleaned_store = write_cleaned_sessions(
        cleaned_sessions(),
        cleaned_path,
        policy=policy,
        source_inventory_sha256=before.digest,
        overwrite=True,
    )
    cleaning_qa = build_cleaning_qa(
        accumulator,
        modes=modes,
        expected_sessions=FROZEN_RAW_CONTRACT.total_record_count,
        analysis_window=protocol["analysis"],
    )
    if cleaning_qa["status"] != "PASS":
        raise ValueError("cleaning gate failed")
    cleaning_sensitivity = accumulator.cleaning_sensitivity()
    boundary_audit = accumulator.boundary_current_audit()
    _checkpoint(
        interim / "preparation_checkpoint.json",
        raw_root=raw,
        phase="cleaning_complete",
        source_inventory_sha256=before.digest,
        details={
            "sessions_processed": accumulator.sessions_processed,
            "cleaned_sha256": cleaned_store.sha256,
        },
    )

    power_audit = audit_power_semantics(accumulator.power_sessions)
    if power_audit["status"] not in _POWER_STATUSES:
        raise ValueError("power audit returned an invalid state")
    primary_thresholds = power_audit["cohorts"]["primary"]["thresholds"]
    if primary_thresholds["minimum_kwh_delivered"] != float(
        protocol["power_audit"]["primary_minimum_kwh"]
    ) or primary_thresholds["minimum_current_coverage"] != float(
        protocol["power_audit"]["primary_minimum_current_coverage"]
    ):
        raise ValueError("power audit primary cohort does not match the frozen protocol")
    reported_cohorts = {
        (
            report["thresholds"]["minimum_kwh_delivered"],
            report["thresholds"]["minimum_current_coverage"],
        )
        for report in (
            power_audit["cohorts"]["primary"],
            *power_audit["cohorts"]["sensitivity"],
        )
    }
    expected_cohorts = {
        (float(energy), float(coverage))
        for energy in protocol["power_audit"]["sensitivity_minimum_kwh"]
        for coverage in protocol["power_audit"]["sensitivity_minimum_current_coverage"]
    }
    if reported_cohorts != expected_cohorts:
        raise ValueError("power audit sensitivity cohorts do not match the frozen protocol")
    decision_thresholds = power_audit["decision"]["thresholds"]
    expected_decision_thresholds = {
        "mapping_rate_candidate": float(protocol["power_audit"]["candidate_mapping_rate"]),
        "mapping_rate_fail_below": float(protocol["power_audit"]["severe_mapping_rate_below"]),
        "primary_audit_coverage_minimum": float(
            protocol["power_audit"]["candidate_audit_coverage_minimum"]
        ),
        "retained_rate_minimum": float(protocol["power_audit"]["candidate_retained_rate_minimum"]),
        "median_absolute_percentage_error_maximum": float(
            protocol["power_audit"]["candidate_mdape_maximum"]
        ),
        "p90_absolute_percentage_error_maximum": float(
            protocol["power_audit"]["candidate_p90_ape_maximum"]
        ),
        "absolute_monthly_relative_energy_error_candidate_maximum": float(
            protocol["power_audit"]["candidate_monthly_absolute_relative_error_maximum"]
        ),
        "absolute_monthly_relative_energy_error_fail_above": float(
            protocol["power_audit"]["severe_monthly_absolute_relative_error_above"]
        ),
    }
    if decision_thresholds != expected_decision_thresholds:
        raise ValueError("power decision thresholds do not match the frozen protocol")
    atomic_write_bytes(
        interim / "power_semantics_audit.json",
        _json_bytes(power_audit),
        raw_root=raw,
    )
    atomic_write_bytes(
        interim / "power_semantics_decision.md",
        _power_decision_markdown(power_audit).encode("utf-8"),
        raw_root=raw,
    )
    _checkpoint(
        interim / "preparation_checkpoint.json",
        raw_root=raw,
        phase="power_audit_complete",
        source_inventory_sha256=before.digest,
        details={
            "power_semantics_status": power_audit["status"],
            "downstream_state": "NOT_RUN",
            "public_release_state": "NOT_CREATED",
        },
    )
    if power_audit["status"] == POWER_SEMANTICS_FAIL:
        stopped_after = validate_raw_snapshot(raw).inventory
        assert_raw_snapshot_unchanged(before, stopped_after)
        for checkpoint_path in (
            interim / "preparation_checkpoint.json",
            processed / "preparation_checkpoint.json",
        ):
            _checkpoint(
                checkpoint_path,
                raw_root=raw,
                phase="stopped_power_semantics_fail",
                source_inventory_sha256=before.digest,
                details={
                    "power_semantics_status": POWER_SEMANTICS_FAIL,
                    "downstream_state": "NOT_RUN",
                    "public_release_state": "NOT_CREATED",
                    "raw_unchanged": True,
                },
            )
        raise PowerSemanticsGateError(
            {
                "status": "FAIL",
                "raw_unchanged": True,
                "sessions_processed": accumulator.sessions_processed,
                "station_bins": 0,
                "scheduled_issue_times": 0,
                "formal_issue_times": 0,
                "power_semantics_status": POWER_SEMANTICS_FAIL,
                "training_environment_frozen": "NO",
            }
        )

    aggregation_policy = AggregationPolicy(
        max_hold_seconds=policy.hold_cap_for("chargingCurrent"),
        main_active_threshold_a=float(protocol["aggregation"]["main_active_threshold_a"]),
        comparison_active_threshold_a=float(
            protocol["aggregation"]["comparison_active_threshold_a"]
        ),
        coverage_thresholds=tuple(
            float(value) for value in protocol["aggregation"]["coverage_thresholds"]
        ),
    )
    station = aggregate_station_15min(
        _iter_cleaned(cleaned_path),
        start_utc=ANALYSIS_START_UTC,
        end_utc=ANALYSIS_END_UTC,
        policy=aggregation_policy,
    )
    expected_bins = int(protocol["analysis"]["expected_station_bins"])
    if station.qa["generated_bins"] != expected_bins:
        raise ValueError("station aggregation did not produce 2976 bins")
    valid_rate = station.qa["valid_bins_at_90"] / station.qa["generated_bins"]
    station_gate = {
        "status": (
            "PASS"
            if valid_rate >= float(protocol["continuity_gate"]["minimum_valid_bin_rate"])
            and station.qa["longest_missing_run"]
            <= int(protocol["continuity_gate"]["maximum_missing_run_bins"])
            else "FAIL"
        ),
        "minimum_valid_bin_rate": float(protocol["continuity_gate"]["minimum_valid_bin_rate"]),
        "maximum_missing_run_bins": int(protocol["continuity_gate"]["maximum_missing_run_bins"]),
        "observed_valid_bin_rate": valid_rate,
        "interpretation": protocol["continuity_gate"]["interpretation"],
    }
    station_qa = {
        **station.qa,
        "status": station_gate["status"],
        "analysis_window": dict(protocol["analysis"]),
        "continuity_gate": station_gate,
    }
    if station_gate["status"] != "PASS":
        raise ValueError("station trajectory has a large unrecoverable gap")

    station_payloads = {
        "station_15min.csv.gz": _station_csv_bytes(station.rows),
        "station_15min.npz": _deterministic_npz_bytes(_station_npz_arrays(station.rows)),
    }
    for name, payload in station_payloads.items():
        atomic_write_bytes(processed / name, payload, raw_root=raw)

    snapshot_policy = SnapshotPolicy(
        lookback_minutes=int(protocol["snapshots"]["lookback_minutes"]),
        horizons_minutes=tuple(int(value) for value in protocol["snapshots"]["horizons_minutes"]),
        issue_step_minutes=int(protocol["snapshots"]["issue_step_minutes"]),
        max_hold_seconds=aggregation_policy.max_hold_seconds,
        active_threshold_a=aggregation_policy.main_active_threshold_a,
    )
    snapshots = build_issue_snapshots(
        station.rows,
        _iter_cleaned(cleaned_path),
        start_utc=ANALYSIS_START_UTC,
        end_utc=ANALYSIS_END_UTC,
        policy=snapshot_policy,
    )
    issue_qa = {
        **snapshots.qa,
        "status": (
            "PASS"
            if snapshots.qa["formal_issue_times"] == snapshots.qa["issue_times"]
            else "CONDITIONAL_PASS"
        ),
        "expected_scheduled_issue_times": int(
            protocol["analysis"]["expected_scheduled_issue_times"]
        ),
        "target_type": "station_current_mean_a",
    }
    if issue_qa["issue_times"] != int(protocol["analysis"]["expected_scheduled_issue_times"]):
        raise ValueError("issue-time schedule does not match the frozen protocol")
    if issue_qa["leakage_audit"] != "PASS":
        raise ValueError("issue-time leakage gate failed")
    if issue_qa["formal_issue_times"] <= 0:
        raise ValueError("no complete issue-time samples were produced")

    snapshot_payloads = _snapshot_npz_payloads(snapshots)
    snapshot_payloads["m3.jsonl.gz"] = _deterministic_gzip_jsonl_bytes(snapshots.m3_rows)
    snapshot_payloads["m4.jsonl.gz"] = _deterministic_gzip_jsonl_bytes(snapshots.m4_rows)
    for name, payload in snapshot_payloads.items():
        atomic_write_bytes(processed / name, payload, raw_root=raw)

    local_entries = [
        _artifact_file_entry(cleaned_store.data_path, known_sha256=cleaned_store.sha256),
        _artifact_file_entry(cleaned_store.manifest_path),
        *(_artifact_entry(name, payload) for name, payload in station_payloads.items()),
        *(_artifact_entry(name, payload) for name, payload in snapshot_payloads.items()),
    ]
    canonical_local = _json_bytes({"protocol_sha256": protocol_sha256, "artifacts": local_entries})
    data_snapshot_sha256 = hashlib.sha256(canonical_local).hexdigest()
    local_manifest = {
        "schema_version": "acn-jpl-local-data-snapshot/v1",
        "source_inventory_sha256": before.digest,
        "data_snapshot_sha256": data_snapshot_sha256,
        "artifact_count": len(local_entries),
        "artifacts": local_entries,
        "cleaning_policy": policy.to_local_dict(),
        "protocol_sha256": protocol_sha256,
        "power_column_present": False,
        "power_label_type": "none",
        "snapshot_sha256": snapshots.snapshot_sha256,
    }
    atomic_write_json(processed / "data_snapshot_manifest.json", local_manifest, raw_root=raw)
    _checkpoint(
        processed / "preparation_checkpoint.json",
        raw_root=raw,
        phase="samples_complete",
        source_inventory_sha256=before.digest,
        details={
            "data_snapshot_sha256": data_snapshot_sha256,
            "station_bins": station.qa["generated_bins"],
            "formal_issue_times": issue_qa["formal_issue_times"],
        },
    )

    after = validate_raw_snapshot(raw).inventory
    assert_raw_snapshot_unchanged(before, after)

    public_snapshot_manifest = {
        "schema_version": "acn-jpl-public-data-snapshot/v1",
        "status": "PASS",
        "source_inventory_sha256": before.digest,
        "source_file_count": before.file_count,
        "source_total_bytes": before.total_bytes,
        "source_object_count": before_validation.total_record_count,
        "data_snapshot_sha256": data_snapshot_sha256,
        "protocol_sha256": protocol_sha256,
        "local_artifact_count": len(local_entries),
        "local_artifacts": local_entries,
        "large_arrays_published": False,
        "anonymous_local_indexes_published": False,
        "reproducible": True,
    }
    overall = (
        "PASS" if issue_qa["formal_issue_times"] == issue_qa["issue_times"] else "CONDITIONAL_PASS"
    )
    incomplete_issue_times = issue_qa["issue_times"] - issue_qa["formal_issue_times"]
    run_manifest = {
        "schema_version": PREPARATION_SCHEMA_VERSION,
        "status": overall,
        "protocol_sha256": protocol_sha256,
        "raw_unchanged": True,
        "sessions_processed": accumulator.sessions_processed,
        "station_bins": station.qa["generated_bins"],
        "scheduled_issue_times": issue_qa["issue_times"],
        "formal_issue_times": issue_qa["formal_issue_times"],
        "power_semantics_status": power_audit["status"],
        "reconstructed_power_column_published": False,
        "current_proxy_available": True,
        "ready_for_gate1_baseline": True,
        "permitted_target": "station_current_mean_a",
        "preparation_limitations": (
            []
            if incomplete_issue_times == 0
            else [
                {
                    "category": "incomplete_multi_horizon_labels",
                    "issue_time_count": incomplete_issue_times,
                }
            ]
        ),
        "static_mirror": "NOT_USED",
        "environment": _environment_manifest(),
        "privacy": {
            "aggregate_only": True,
            "private_values_emitted": False,
            "host_usernames_emitted": False,
            "absolute_paths_emitted": False,
            "model_weights_emitted": False,
        },
        "scope": {
            "training": False,
            "gate1_execution": False,
            "optimization": False,
            "other_month_acquisition": False,
        },
        "checkpoint_state": "samples_complete",
    }
    payloads = _public_payloads(
        cleaning_qa=cleaning_qa,
        cleaning_sensitivity=cleaning_sensitivity,
        boundary_audit=boundary_audit,
        power_audit=power_audit,
        station_qa=station_qa,
        issue_qa=issue_qa,
        snapshot_manifest=public_snapshot_manifest,
        run_manifest=run_manifest,
    )
    closed = close_public_artifacts(payloads)
    publish_public_release(closed, output_root=public, raw_root=raw)
    if not verify_public_release(public):
        raise ValueError("published aggregate release failed verification")

    _checkpoint(
        processed / "preparation_checkpoint.json",
        raw_root=raw,
        phase="public_release_complete",
        source_inventory_sha256=before.digest,
        details={
            "data_snapshot_sha256": data_snapshot_sha256,
            "public_artifact_count": len(PUBLIC_ARTIFACT_NAMES),
        },
    )
    summary = {
        "status": overall,
        "raw_unchanged": True,
        "sessions_processed": accumulator.sessions_processed,
        "station_bins": station.qa["generated_bins"],
        "scheduled_issue_times": issue_qa["issue_times"],
        "formal_issue_times": issue_qa["formal_issue_times"],
        "power_semantics_status": power_audit["status"],
        "training_environment_frozen": "NO",
    }
    return PreparationResult(
        summary=summary,
        cleaning_qa=cleaning_qa,
        power_audit=power_audit,
        station_qa=station_qa,
        issue_qa=issue_qa,
        raw_before=before,
        raw_after=after,
    )
