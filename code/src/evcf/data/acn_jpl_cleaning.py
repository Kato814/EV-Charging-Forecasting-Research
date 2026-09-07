"""Deterministic, offline cleaning primitives for the JPL May 2019 snapshot."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .acn_audit import parse_acn_datetime

JPL_TIMEZONE = "America/Los_Angeles"
_VALUE_KEYS = {"chargingCurrent": "current", "pilotSignal": "pilot"}


@dataclass(frozen=True)
class CleaningPolicy:
    """Frozen choices needed to turn raw series into deterministic local data."""

    current_mode_s: int
    pilot_mode_s: int
    locf_mode_multiplier: int = 3
    locf_cap_s: int = 60
    boundary_sensitivity_s: int = 60

    def __post_init__(self) -> None:
        for name in ("current_mode_s", "pilot_mode_s", "locf_mode_multiplier", "locf_cap_s"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            not isinstance(self.boundary_sensitivity_s, int)
            or isinstance(self.boundary_sensitivity_s, bool)
            or self.boundary_sensitivity_s < 0
        ):
            raise ValueError("boundary_sensitivity_s must be a nonnegative integer")

    def mode_for(self, field_name: str) -> int:
        _validate_field_name(field_name)
        return self.current_mode_s if field_name == "chargingCurrent" else self.pilot_mode_s

    def hold_cap_for(self, field_name: str) -> int:
        return min(self.locf_mode_multiplier * self.mode_for(field_name), self.locf_cap_s)

    def to_local_dict(self) -> dict[str, int]:
        return {
            "current_mode_s": self.current_mode_s,
            "pilot_mode_s": self.pilot_mode_s,
            "locf_mode_multiplier": self.locf_mode_multiplier,
            "locf_cap_s": self.locf_cap_s,
            "boundary_sensitivity_s": self.boundary_sensitivity_s,
        }


@dataclass(frozen=True)
class SeriesPoint:
    timestamp_utc_s: int
    value: float
    raw_ordinal: int

    def to_local_dict(self) -> dict[str, int | float]:
        return {
            "timestamp_utc_s": self.timestamp_utc_s,
            "value": self.value,
            "raw_ordinal": self.raw_ordinal,
        }


@dataclass(frozen=True)
class SamplingMode:
    field_name: str
    mode_seconds: int
    positive_delta_count: int
    delta_histogram: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class SamplingModes:
    current: SamplingMode
    pilot: SamplingMode


def cleaning_policy_from_sampling_modes(
    modes: SamplingModes,
    *,
    locf_mode_multiplier: int = 3,
    locf_cap_seconds: int = 60,
    boundary_sensitivity_seconds: int = 60,
    required_mode_seconds: int | None = None,
) -> CleaningPolicy:
    """Build one policy from the two modes observed in the current month."""

    policy = CleaningPolicy(
        current_mode_s=modes.current.mode_seconds,
        pilot_mode_s=modes.pilot.mode_seconds,
        locf_mode_multiplier=locf_mode_multiplier,
        locf_cap_s=locf_cap_seconds,
        boundary_sensitivity_s=boundary_sensitivity_seconds,
    )
    if required_mode_seconds is not None:
        if (
            not isinstance(required_mode_seconds, int)
            or isinstance(required_mode_seconds, bool)
            or required_mode_seconds <= 0
        ):
            raise ValueError("required_mode_seconds must be a positive integer")
        if (
            policy.current_mode_s != required_mode_seconds
            or policy.pilot_mode_s != required_mode_seconds
        ):
            raise ValueError("frozen snapshot did not reproduce the audited 4-second modes")
    return policy


@dataclass(frozen=True)
class SeriesCleaningAudit:
    raw_samples: int
    invalid_timestamps: int
    invalid_values: int
    exact_duplicate_extras: int
    conflicting_timestamps: int
    boundary_distances_s: tuple[int, ...]
    boundary_positive_value_seconds: float
    raw_total_value_seconds: float
    raw_order_sha256: str
    raw_values_sha256: str
    raw_pairs_sha256: str

    def to_local_dict(self) -> dict[str, Any]:
        return {
            "raw_samples": self.raw_samples,
            "invalid_timestamps": self.invalid_timestamps,
            "invalid_values": self.invalid_values,
            "exact_duplicate_extras": self.exact_duplicate_extras,
            "conflicting_timestamps": self.conflicting_timestamps,
            "boundary_distances_s": list(self.boundary_distances_s),
            "boundary_positive_value_seconds": self.boundary_positive_value_seconds,
            "raw_total_value_seconds": self.raw_total_value_seconds,
            "boundary_current_integral_share": (
                self.boundary_positive_value_seconds / self.raw_total_value_seconds
                if self.raw_total_value_seconds > 0
                else 0.0
            ),
            "raw_order_sha256": self.raw_order_sha256,
            "raw_values_sha256": self.raw_values_sha256,
            "raw_pairs_sha256": self.raw_pairs_sha256,
        }


@dataclass(frozen=True)
class IntegralContribution:
    start_utc_s: int
    end_utc_s: int
    value: float
    raw_ordinal: int

    def to_local_dict(self) -> dict[str, int | float]:
        return {
            "start_utc_s": self.start_utc_s,
            "end_utc_s": self.end_utc_s,
            "value": self.value,
            "raw_ordinal": self.raw_ordinal,
        }


@dataclass(frozen=True)
class BoundedIntegral:
    start_utc_s: int
    end_utc_s: int
    hold_cap_s: int
    observed_seconds: int
    eligible_seconds: int
    value_seconds: float
    value_hours: float
    coverage: float
    contributions: tuple[IntegralContribution, ...]

    def to_local_dict(self) -> dict[str, Any]:
        return {
            "start_utc_s": self.start_utc_s,
            "end_utc_s": self.end_utc_s,
            "hold_cap_s": self.hold_cap_s,
            "observed_seconds": self.observed_seconds,
            "eligible_seconds": self.eligible_seconds,
            "value_seconds": self.value_seconds,
            "value_hours": self.value_hours,
            "coverage": self.coverage,
        }


@dataclass(frozen=True)
class CleanSeries:
    """Immutable main series plus only the points needed by frozen sensitivities."""

    field_name: str
    timestamps_utc_s: tuple[int, ...]
    values: tuple[float, ...]
    raw_ordinals: tuple[int, ...]
    boundary_positive_points: tuple[SeriesPoint, ...]
    boundary_sensitivity_points: tuple[SeriesPoint, ...]
    conflict_lww_overrides: tuple[SeriesPoint, ...]
    audit: SeriesCleaningAudit
    locf_cap_s: int
    main_integral: BoundedIntegral

    def main_points(self) -> tuple[SeriesPoint, ...]:
        return tuple(
            SeriesPoint(timestamp, value, ordinal)
            for timestamp, value, ordinal in zip(
                self.timestamps_utc_s,
                self.values,
                self.raw_ordinals,
                strict=True,
            )
        )

    def sensitivity_points(self) -> tuple[SeriesPoint, ...]:
        return tuple(
            sorted(
                (
                    *self.main_points(),
                    *self.boundary_sensitivity_points,
                    *self.conflict_lww_overrides,
                ),
                key=lambda point: (point.timestamp_utc_s, point.raw_ordinal),
            )
        )

    def to_local_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "timestamps_utc_s": list(self.timestamps_utc_s),
            "values": list(self.values),
            "raw_ordinals": list(self.raw_ordinals),
            "boundary_positive_points": [
                point.to_local_dict() for point in self.boundary_positive_points
            ],
            "boundary_sensitivity_points": [
                point.to_local_dict() for point in self.boundary_sensitivity_points
            ],
            "conflict_lww_overrides": [
                point.to_local_dict() for point in self.conflict_lww_overrides
            ],
            "audit": self.audit.to_local_dict(),
            "locf_cap_s": self.locf_cap_s,
            "main_integral": self.main_integral.to_local_dict(),
        }


@dataclass(frozen=True)
class SanitizedUserInput:
    modified_at_utc_s: int
    requested_departure_utc_s: int | None
    kwh_requested: float | None
    raw_ordinal: int

    def to_local_dict(self) -> dict[str, int | float | None]:
        return {
            "modified_at_utc_s": self.modified_at_utc_s,
            "requested_departure_utc_s": self.requested_departure_utc_s,
            "kwh_requested": self.kwh_requested,
            "raw_ordinal": self.raw_ordinal,
        }


@dataclass(frozen=True)
class CleanSession:
    """Anonymous local session record; retrospective energy remains explicitly offline-only."""

    session_index: int
    site_id: str | None
    station_id: str | None
    space_id: str | None
    cluster_id: str | None
    connection_utc_s: int
    disconnect_utc_s: int
    retrospective_done_raw: str | None
    retrospective_done_utc_s: int | None
    offline_kwh_delivered: float | None
    current: CleanSeries
    pilot: CleanSeries
    user_inputs: tuple[SanitizedUserInput, ...]

    def to_local_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "acn-jpl-clean-session/v1",
            "session_index": self.session_index,
            "timezone": JPL_TIMEZONE,
            "site_id": self.site_id,
            "station_id": self.station_id,
            "space_id": self.space_id,
            "cluster_id": self.cluster_id,
            "connection_utc_s": self.connection_utc_s,
            "disconnect_utc_s": self.disconnect_utc_s,
            "connection_local": utc_s_to_local_iso(self.connection_utc_s),
            "disconnect_local": utc_s_to_local_iso(self.disconnect_utc_s),
            "retrospective_done_raw": self.retrospective_done_raw,
            "retrospective_done_utc_s": self.retrospective_done_utc_s,
            "offline_kwh_delivered": self.offline_kwh_delivered,
            "current": self.current.to_local_dict(),
            "pilot": self.pilot.to_local_dict(),
            "user_inputs": [item.to_local_dict() for item in self.user_inputs],
        }


@dataclass(frozen=True)
class CleanedSessionStore:
    """Paths and content digest for one deterministic cleaned-session store."""

    data_path: Path
    manifest_path: Path
    record_count: int
    sha256: str


def _validate_field_name(field_name: str) -> None:
    if field_name not in _VALUE_KEYS:
        raise ValueError("field_name must be 'chargingCurrent' or 'pilotSignal'")


def _update_delta_counter(
    counter: Counter[int],
    series: Any,
) -> None:
    if not isinstance(series, Mapping) or not isinstance(series.get("timestamps"), list):
        return
    previous: int | None = None
    for raw_timestamp in series["timestamps"]:
        try:
            timestamp = parse_timestamp_utc_s(raw_timestamp)
        except (TypeError, ValueError):
            previous = None
            continue
        if previous is not None:
            delta = timestamp - previous
            if delta > 0:
                counter[delta] += 1
        previous = timestamp


def _sampling_mode(field_name: str, counter: Counter[int]) -> SamplingMode:
    if not counter:
        raise ValueError(f"{field_name} has no positive timestamp deltas")
    highest_count = max(counter.values())
    mode_seconds = min(delta for delta, count in counter.items() if count == highest_count)
    return SamplingMode(
        field_name=field_name,
        mode_seconds=mode_seconds,
        positive_delta_count=sum(counter.values()),
        delta_histogram=tuple(sorted(counter.items())),
    )


def derive_sampling_modes(records: Any) -> SamplingModes:
    """Derive current and pilot positive-delta modes in one pre-clean streaming pass."""

    current_deltas: Counter[int] = Counter()
    pilot_deltas: Counter[int] = Counter()
    for record in records:
        if not isinstance(record, Mapping):
            raise TypeError("raw record must be a mapping")
        _update_delta_counter(current_deltas, record.get("chargingCurrent"))
        _update_delta_counter(pilot_deltas, record.get("pilotSignal"))
    return SamplingModes(
        current=_sampling_mode("chargingCurrent", current_deltas),
        pilot=_sampling_mode("pilotSignal", pilot_deltas),
    )


def _parse_aware_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = parse_acn_datetime(value)
        except ValueError:
            normalized = value.strip()
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError(f"invalid timestamp: {value!r}") from exc
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timestamp must be timezone-aware")
    else:
        raise TypeError(f"timestamp must be a string or datetime, got {type(value).__name__}")

    if parsed is None:
        raise ValueError("timestamp is required")
    return parsed.astimezone(timezone.utc)


def parse_timestamp_utc_s(value: Any) -> int:
    """Parse an aware ACN/ISO timestamp into an integer UTC epoch second."""

    parsed = _parse_aware_datetime(value)
    if parsed.microsecond:
        raise ValueError("timestamp must have whole-second precision")
    return int(parsed.timestamp())


def utc_s_to_local_iso(
    timestamp_utc_s: int,
    *,
    timezone_name: str = JPL_TIMEZONE,
) -> str:
    """Render one integer UTC epoch second in a named local timezone."""

    if not isinstance(timestamp_utc_s, int) or isinstance(timestamp_utc_s, bool):
        raise TypeError("timestamp_utc_s must be an integer")
    return (
        datetime.fromtimestamp(timestamp_utc_s, timezone.utc)
        .astimezone(ZoneInfo(timezone_name))
        .isoformat()
    )


def _finite_number(value: Any, *, nonnegative: bool) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    if not math.isfinite(number) or (nonnegative and number < 0):
        return None
    return number


def _canonical_audit_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, float):
        return {"type": "float", "value": value.hex()}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_audit_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_audit_value(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return {"type": type(value).__name__, "value": str(value)}


def _audit_digest(rows: Iterable[Any]) -> str:
    digest = hashlib.sha256()
    for ordinal, row in enumerate(rows):
        encoded = json.dumps(
            [ordinal, _canonical_audit_value(row)],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(encoded + b"\n")
    return digest.hexdigest()


def bounded_locf_integral(
    points: Iterable[SeriesPoint],
    *,
    start_utc_s: int,
    end_utc_s: int,
    hold_cap_s: int,
) -> BoundedIntegral:
    """Integrate a piecewise-constant series without holding past ``hold_cap_s``."""

    if end_utc_s <= start_utc_s:
        raise ValueError("end_utc_s must be greater than start_utc_s")
    if not isinstance(hold_cap_s, int) or isinstance(hold_cap_s, bool) or hold_cap_s <= 0:
        raise ValueError("hold_cap_s must be a positive integer")
    ordered = tuple(sorted(points, key=lambda point: (point.timestamp_utc_s, point.raw_ordinal)))
    if any(
        current.timestamp_utc_s == previous.timestamp_utc_s
        for previous, current in pairwise(ordered)
    ):
        raise ValueError("bounded LOCF points must have unique timestamps")

    contributions: list[IntegralContribution] = []
    for index, point in enumerate(ordered):
        next_timestamp = (
            ordered[index + 1].timestamp_utc_s if index + 1 < len(ordered) else end_utc_s
        )
        contribution_start = max(start_utc_s, point.timestamp_utc_s)
        contribution_end = min(
            end_utc_s,
            next_timestamp,
            point.timestamp_utc_s + hold_cap_s,
        )
        if contribution_end <= contribution_start:
            continue
        contributions.append(
            IntegralContribution(
                start_utc_s=contribution_start,
                end_utc_s=contribution_end,
                value=point.value,
                raw_ordinal=point.raw_ordinal,
            )
        )

    observed_seconds = sum(item.end_utc_s - item.start_utc_s for item in contributions)
    eligible_seconds = end_utc_s - start_utc_s
    value_seconds = math.fsum(
        item.value * (item.end_utc_s - item.start_utc_s) for item in contributions
    )
    return BoundedIntegral(
        start_utc_s=start_utc_s,
        end_utc_s=end_utc_s,
        hold_cap_s=hold_cap_s,
        observed_seconds=observed_seconds,
        eligible_seconds=eligible_seconds,
        value_seconds=value_seconds,
        value_hours=value_seconds / 3600.0,
        coverage=observed_seconds / eligible_seconds,
        contributions=tuple(contributions),
    )


def clean_series(
    series: Mapping[str, Any],
    *,
    field_name: str,
    connection_utc_s: int,
    disconnect_utc_s: int,
    policy: CleaningPolicy,
) -> CleanSeries:
    """Clean one current or pilot series without mutating the raw mapping."""

    _validate_field_name(field_name)
    if disconnect_utc_s <= connection_utc_s:
        raise ValueError("disconnect_utc_s must be greater than connection_utc_s")
    timestamps = series.get("timestamps")
    values = series.get(_VALUE_KEYS[field_name])
    if not isinstance(timestamps, list) or not isinstance(values, list):
        raise TypeError(f"{field_name} timestamps and values must be lists")
    if len(timestamps) != len(values):
        raise ValueError(f"{field_name} timestamps and values must have equal length")

    raw_pairs = tuple(zip(timestamps, values, strict=True))
    raw_order_sha256 = _audit_digest(timestamps)
    raw_values_sha256 = _audit_digest(values)
    raw_pairs_sha256 = _audit_digest(raw_pairs)

    grouped: dict[int, list[SeriesPoint]] = {}
    invalid_timestamps = 0
    invalid_values = 0
    boundary_distances: list[int] = []
    boundary_positive_points: list[SeriesPoint] = []
    for ordinal, (raw_timestamp, raw_value) in enumerate(zip(timestamps, values, strict=True)):
        try:
            timestamp = parse_timestamp_utc_s(raw_timestamp)
        except (TypeError, ValueError):
            invalid_timestamps += 1
            continue
        number = _finite_number(raw_value, nonnegative=field_name == "chargingCurrent")
        if number is None:
            invalid_values += 1
            continue
        point = SeriesPoint(timestamp, number, ordinal)
        if field_name == "chargingCurrent" and number > 0:
            if timestamp < connection_utc_s:
                boundary_distances.append(timestamp - connection_utc_s)
                boundary_positive_points.append(point)
            elif timestamp >= disconnect_utc_s:
                boundary_distances.append(timestamp - disconnect_utc_s)
                boundary_positive_points.append(point)
        grouped.setdefault(timestamp, []).append(point)

    exact_duplicate_extras = 0
    conflicting_timestamps = 0
    main: list[SeriesPoint] = []
    boundary: list[SeriesPoint] = []
    conflicts: list[SeriesPoint] = []
    all_main_rule_points: list[SeriesPoint] = []
    expanded_start = connection_utc_s - policy.boundary_sensitivity_s
    expanded_end = disconnect_utc_s + policy.boundary_sensitivity_s
    for timestamp in sorted(grouped):
        observations = grouped[timestamp]
        first_by_value: dict[str, SeriesPoint] = {}
        for observation in observations:
            signature = observation.value.hex()
            if signature in first_by_value:
                exact_duplicate_extras += 1
            else:
                first_by_value[signature] = observation

        if len(first_by_value) > 1:
            conflicting_timestamps += 1
            if expanded_start <= timestamp < expanded_end:
                conflicts.append(observations[-1])
            continue

        point = observations[0]
        all_main_rule_points.append(point)
        if connection_utc_s <= timestamp < disconnect_utc_s:
            main.append(point)
        elif expanded_start <= timestamp < expanded_end:
            boundary.append(point)

    main_points = tuple(main)
    hold_cap_s = policy.hold_cap_for(field_name)
    main_integral = bounded_locf_integral(
        main_points,
        start_utc_s=connection_utc_s,
        end_utc_s=disconnect_utc_s,
        hold_cap_s=hold_cap_s,
    )
    boundary_positive_value_seconds = 0.0
    raw_total_value_seconds = 0.0
    if field_name == "chargingCurrent" and all_main_rule_points:
        audit_start = min(connection_utc_s, all_main_rule_points[0].timestamp_utc_s)
        audit_end = max(
            disconnect_utc_s,
            all_main_rule_points[-1].timestamp_utc_s + hold_cap_s,
        )
        raw_integral = bounded_locf_integral(
            all_main_rule_points,
            start_utc_s=audit_start,
            end_utc_s=audit_end,
            hold_cap_s=hold_cap_s,
        )
        raw_total_value_seconds = raw_integral.value_seconds
        point_by_ordinal = {point.raw_ordinal: point for point in all_main_rule_points}
        outside_contributions: list[float] = []
        for contribution in raw_integral.contributions:
            source = point_by_ordinal[contribution.raw_ordinal]
            if source.value <= 0 or connection_utc_s <= source.timestamp_utc_s < disconnect_utc_s:
                continue
            if source.timestamp_utc_s < connection_utc_s:
                outside_seconds = max(
                    0,
                    min(contribution.end_utc_s, connection_utc_s) - contribution.start_utc_s,
                )
            else:
                outside_seconds = max(
                    0,
                    contribution.end_utc_s - max(contribution.start_utc_s, disconnect_utc_s),
                )
            outside_contributions.append(source.value * outside_seconds)
        boundary_positive_value_seconds = math.fsum(outside_contributions)
    return CleanSeries(
        field_name=field_name,
        timestamps_utc_s=tuple(point.timestamp_utc_s for point in main_points),
        values=tuple(point.value for point in main_points),
        raw_ordinals=tuple(point.raw_ordinal for point in main_points),
        boundary_positive_points=tuple(boundary_positive_points),
        boundary_sensitivity_points=tuple(boundary),
        conflict_lww_overrides=tuple(conflicts),
        audit=SeriesCleaningAudit(
            raw_samples=len(values),
            invalid_timestamps=invalid_timestamps,
            invalid_values=invalid_values,
            exact_duplicate_extras=exact_duplicate_extras,
            conflicting_timestamps=conflicting_timestamps,
            boundary_distances_s=tuple(boundary_distances),
            boundary_positive_value_seconds=boundary_positive_value_seconds,
            raw_total_value_seconds=raw_total_value_seconds,
            raw_order_sha256=raw_order_sha256,
            raw_values_sha256=raw_values_sha256,
            raw_pairs_sha256=raw_pairs_sha256,
        ),
        locf_cap_s=hold_cap_s,
        main_integral=main_integral,
    )


def _optional_timestamp_utc_s(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return parse_timestamp_utc_s(value)
    except (TypeError, ValueError):
        return None


def sanitize_user_inputs(value: Any) -> tuple[SanitizedUserInput, ...]:
    """Keep only issue-time-selectable request fields from raw user-input revisions."""

    if not isinstance(value, list):
        return ()
    sanitized: list[SanitizedUserInput] = []
    for raw_ordinal, item in enumerate(value):
        if not isinstance(item, Mapping):
            continue
        modified = _optional_timestamp_utc_s(item.get("modifiedAt"))
        if modified is None:
            continue
        sanitized.append(
            SanitizedUserInput(
                modified_at_utc_s=modified,
                requested_departure_utc_s=_optional_timestamp_utc_s(item.get("requestedDeparture")),
                kwh_requested=_finite_number(item.get("kWhRequested"), nonnegative=True),
                raw_ordinal=raw_ordinal,
            )
        )
    return tuple(sorted(sanitized, key=lambda item: (item.modified_at_utc_s, item.raw_ordinal)))


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_original_timestamp(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def clean_session(
    record: Mapping[str, Any],
    *,
    session_index: int,
    policy: CleaningPolicy,
) -> CleanSession:
    """Create one immutable anonymous clean session from a raw ACN record."""

    if not isinstance(session_index, int) or isinstance(session_index, bool) or session_index < 0:
        raise ValueError("session_index must be a nonnegative integer")
    connection = parse_timestamp_utc_s(record.get("connectionTime"))
    disconnect = parse_timestamp_utc_s(record.get("disconnectTime"))
    if disconnect <= connection:
        raise ValueError("disconnectTime must be later than connectionTime")

    current_raw = record.get("chargingCurrent")
    pilot_raw = record.get("pilotSignal")
    if not isinstance(current_raw, Mapping) or not isinstance(pilot_raw, Mapping):
        raise TypeError("chargingCurrent and pilotSignal must be mappings")

    return CleanSession(
        session_index=session_index,
        site_id=_optional_text(record.get("siteID")),
        station_id=_optional_text(record.get("stationID")),
        space_id=_optional_text(record.get("spaceID")),
        cluster_id=_optional_text(record.get("clusterID")),
        connection_utc_s=connection,
        disconnect_utc_s=disconnect,
        retrospective_done_raw=_optional_original_timestamp(record.get("doneChargingTime")),
        retrospective_done_utc_s=_optional_timestamp_utc_s(record.get("doneChargingTime")),
        offline_kwh_delivered=_finite_number(record.get("kWhDelivered"), nonnegative=True),
        current=clean_series(
            current_raw,
            field_name="chargingCurrent",
            connection_utc_s=connection,
            disconnect_utc_s=disconnect,
            policy=policy,
        ),
        pilot=clean_series(
            pilot_raw,
            field_name="pilotSignal",
            connection_utc_s=connection,
            disconnect_utc_s=disconnect,
            policy=policy,
        ),
        user_inputs=sanitize_user_inputs(record.get("userInputs")),
    )


def clean_quarantined_session(
    record: Mapping[str, Any],
    *,
    session_index: int,
    policy: CleaningPolicy,
) -> CleanSession:
    """Retain structural state while making both raw trajectories unobservable."""

    from .acn_jpl_trajectory_quarantine import (
        TRAJECTORY_QUARANTINE,
        quarantine_record_for_analysis,
    )

    decision, projected = quarantine_record_for_analysis(record)
    if decision.action != TRAJECTORY_QUARANTINE or projected is None:
        raise ValueError("record is not an approved trajectory-quarantine candidate")
    cleaned = clean_session(projected, session_index=session_index, policy=policy)

    def retain_raw_denominator(
        clean: CleanSeries,
        *,
        field_name: str,
        value_name: str,
    ) -> CleanSeries:
        raw_series = record.get(field_name)
        if not isinstance(raw_series, Mapping):
            raise TypeError("quarantined raw series must be a mapping")
        timestamps = raw_series.get("timestamps")
        values = raw_series.get(value_name)
        if not isinstance(timestamps, list) or not isinstance(values, list):
            raise TypeError("quarantined raw series arrays must be lists")
        pairs = tuple(zip(timestamps, values, strict=True))
        seen_pairs: set[str] = set()
        duplicate_extras = 0
        values_by_timestamp: dict[int, set[str]] = {}
        invalid_timestamps = 0
        invalid_values = 0
        for raw_timestamp, raw_value in pairs:
            signature = json.dumps(
                [raw_timestamp, raw_value],
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if signature in seen_pairs:
                duplicate_extras += 1
            else:
                seen_pairs.add(signature)
            try:
                timestamp = parse_timestamp_utc_s(raw_timestamp)
            except (TypeError, ValueError):
                invalid_timestamps += 1
                continue
            number = _finite_number(raw_value, nonnegative=field_name == "chargingCurrent")
            if number is None:
                invalid_values += 1
                continue
            values_by_timestamp.setdefault(timestamp, set()).add(number.hex())
        conflicting_timestamps = sum(
            len(signatures) > 1 for signatures in values_by_timestamp.values()
        )
        audit = replace(
            clean.audit,
            raw_samples=len(values),
            invalid_timestamps=invalid_timestamps,
            invalid_values=invalid_values,
            exact_duplicate_extras=duplicate_extras,
            conflicting_timestamps=conflicting_timestamps,
            raw_order_sha256=_audit_digest(timestamps),
            raw_values_sha256=_audit_digest(values),
            raw_pairs_sha256=_audit_digest(pairs),
        )
        return replace(clean, audit=audit)

    return replace(
        cleaned,
        current=retain_raw_denominator(
            cleaned.current,
            field_name="chargingCurrent",
            value_name="current",
        ),
        pilot=retain_raw_denominator(
            cleaned.pilot,
            field_name="pilotSignal",
            value_name="pilot",
        ),
    )


def _write_bytes_durably(path: Path, payload: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_cleaned_sessions(
    sessions: Iterable[CleanSession],
    output_path: str | os.PathLike[str],
    *,
    policy: CleaningPolicy,
    source_inventory_sha256: str,
    overwrite: bool = False,
) -> CleanedSessionStore:
    """Write anonymous sessions as reproducible gzip JSONL plus a hash manifest."""

    if re.fullmatch(r"[0-9a-f]{64}", source_inventory_sha256) is None:
        raise ValueError("source_inventory_sha256 must be a lowercase SHA-256 digest")
    data_path = Path(output_path)
    if data_path.name in ("", ".", ".."):
        raise ValueError("output_path must name a file")
    manifest_path = data_path.with_name(f"{data_path.name}.manifest.json")
    data_partial = data_path.with_name(f"{data_path.name}.partial")
    manifest_partial = manifest_path.with_name(f"{manifest_path.name}.partial")

    if not overwrite and (data_path.exists() or manifest_path.exists()):
        raise FileExistsError("cleaned-session data or manifest already exists")
    if data_partial.exists() or manifest_partial.exists():
        raise FileExistsError("cleaned-session partial output already exists")

    record_count = 0
    try:
        with data_partial.open("xb") as raw_handle:
            with gzip.GzipFile(
                filename="",
                mode="wb",
                fileobj=raw_handle,
                mtime=0,
            ) as gzip_handle:
                for expected_index, session in enumerate(sessions):
                    if not isinstance(session, CleanSession):
                        raise TypeError("sessions must contain CleanSession values")
                    if session.session_index != expected_index:
                        raise ValueError(
                            "session indexes must be anonymous contiguous ordinals starting at zero"
                        )
                    line = json.dumps(
                        session.to_local_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                    gzip_handle.write(line + b"\n")
                    record_count += 1
            raw_handle.flush()
            os.fsync(raw_handle.fileno())

        sha256 = _file_sha256(data_partial)
        manifest = {
            "anonymous_session_indexes": True,
            "data_file": data_path.name,
            "policy": policy.to_local_dict(),
            "private_identifiers_stored": False,
            "record_count": record_count,
            "schema_version": "acn-jpl-cleaned-sessions/v1",
            "sha256": sha256,
            "source_inventory_sha256": source_inventory_sha256,
        }
        manifest_bytes = (
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        _write_bytes_durably(manifest_partial, manifest_bytes)

        os.replace(data_partial, data_path)
        os.replace(manifest_partial, manifest_path)
    except BaseException:
        data_partial.unlink(missing_ok=True)
        manifest_partial.unlink(missing_ok=True)
        raise

    return CleanedSessionStore(
        data_path=data_path,
        manifest_path=manifest_path,
        record_count=record_count,
        sha256=sha256,
    )
