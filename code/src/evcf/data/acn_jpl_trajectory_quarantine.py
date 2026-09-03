"""Narrow, deterministic quarantine for synchronized raw-order UTC reversals.

The projection returned here is analysis-only.  It never mutates the acquired
record: valid structural metadata remains available while both affected
trajectories become empty (unobserved, not zero).  Any synchronized candidate
whose connection bounds are invalid is rejected from all analysis variables.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import Any, Final, Literal

from .acn_audit import parse_acn_datetime

NO_QUARANTINE: Final = "NONE"
TRAJECTORY_QUARANTINE: Final = "TRAJECTORY_QUARANTINE"
FULL_SESSION_QUARANTINE: Final = "FULL_SESSION_QUARANTINE"

QuarantineAction = Literal[
    "NONE",
    "TRAJECTORY_QUARANTINE",
    "FULL_SESSION_QUARANTINE",
]
_UNSPECIFIED_METADATA = object()


@dataclass(frozen=True, slots=True)
class TrajectoryQuarantineDecision:
    """Aggregate-safe decision for one private raw record."""

    action: QuarantineAction
    current_nonmonotonic_pairs: int
    pilot_nonmonotonic_pairs: int
    synchronized_transition_count: int
    synchronized_backward_seconds: tuple[float, ...]
    synchronized_raw_ordinals: tuple[int, ...]
    metadata_bounds_valid: bool


@dataclass(frozen=True, slots=True)
class TrajectoryQuarantineAudit:
    """Closed aggregate decision for one canonical seasonal month."""

    approved: bool
    denominator_sessions: int
    trajectory_quarantine_count: int
    full_session_quarantine_count: int
    quarantined_current_nonmonotonic_pairs: int
    quarantined_pilot_nonmonotonic_pairs: int

    def public_dict(self) -> dict[str, object]:
        denominator = self.denominator_sessions
        return {
            "denominator_sessions": denominator,
            "trajectory_quarantine_count": self.trajectory_quarantine_count,
            "trajectory_quarantine_rate": (
                self.trajectory_quarantine_count / denominator if denominator else None
            ),
            "full_session_quarantine_count": self.full_session_quarantine_count,
            "full_session_quarantine_rate": (
                self.full_session_quarantine_count / denominator if denominator else None
            ),
            "synchronized_utc_nonmonotonic_sessions": (
                self.trajectory_quarantine_count + self.full_session_quarantine_count
            ),
            "raw_trajectory_anomalies_retained": True,
            "raw_manifest_modified": False,
            "raw_timestamps_modified": False,
            "sort_repair_applied": False,
            "timestamp_shift_seconds": 0,
            "interpolation_applied": False,
            "whole_current_pilot_trajectory_unobservable": True,
            "coverage_denominator_includes_quarantined": True,
            "structural_metadata_retained_count": self.trajectory_quarantine_count,
            "connected_state_retained_count": self.trajectory_quarantine_count,
        }


def _parsed_timestamp(value: object) -> datetime | None:
    try:
        return parse_acn_datetime(value)
    except (TypeError, ValueError):
        return None


def _negative_transitions(
    record: Mapping[str, Any],
    *,
    field_name: str,
    value_name: str,
) -> tuple[tuple[int, datetime, datetime], ...] | None:
    series = record.get(field_name)
    if not isinstance(series, Mapping):
        return None
    timestamps = series.get("timestamps")
    values = series.get(value_name)
    if (
        not isinstance(timestamps, list)
        or not isinstance(values, list)
        or len(timestamps) != len(values)
    ):
        return None
    parsed = tuple(_parsed_timestamp(value) for value in timestamps)
    if any(value is None for value in parsed):
        return None
    aware = tuple(value for value in parsed if value is not None)
    return tuple(
        (index, previous, current)
        for index, (previous, current) in enumerate(pairwise(aware), start=1)
        if current < previous
    )


def _metadata_bounds_valid(
    record: Mapping[str, Any],
    expected_metadata: object,
) -> bool:
    connection = _parsed_timestamp(record.get("connectionTime"))
    disconnect = _parsed_timestamp(record.get("disconnectTime"))
    valid = bool(
        connection is not None
        and disconnect is not None
        and disconnect > connection
    )
    if not valid or expected_metadata is _UNSPECIFIED_METADATA:
        return valid
    if not isinstance(expected_metadata, Mapping):
        return False
    expected_connection = _parsed_timestamp(expected_metadata.get("connectionTime"))
    expected_disconnect = _parsed_timestamp(expected_metadata.get("disconnectTime"))
    return bool(
        expected_connection is not None
        and expected_disconnect is not None
        and expected_disconnect > expected_connection
        and connection == expected_connection
        and disconnect == expected_disconnect
    )


def quarantine_record_for_analysis(
    record: Mapping[str, Any],
    *,
    expected_metadata: object = _UNSPECIFIED_METADATA,
) -> tuple[TrajectoryQuarantineDecision, Mapping[str, Any] | None]:
    """Classify and project one record without repairing or changing raw bytes."""

    current = _negative_transitions(
        record,
        field_name="chargingCurrent",
        value_name="current",
    )
    pilot = _negative_transitions(
        record,
        field_name="pilotSignal",
        value_name="pilot",
    )
    current_count = len(current) if current is not None else 0
    pilot_count = len(pilot) if pilot is not None else 0
    synchronized = bool(current and pilot and current == pilot)
    bounds_valid = _metadata_bounds_valid(record, expected_metadata)
    if not synchronized:
        return (
            TrajectoryQuarantineDecision(
                action=NO_QUARANTINE,
                current_nonmonotonic_pairs=current_count,
                pilot_nonmonotonic_pairs=pilot_count,
                synchronized_transition_count=0,
                synchronized_backward_seconds=(),
                synchronized_raw_ordinals=(),
                metadata_bounds_valid=bounds_valid,
            ),
            record,
        )
    action: QuarantineAction = (
        TRAJECTORY_QUARANTINE if bounds_valid else FULL_SESSION_QUARANTINE
    )
    decision = TrajectoryQuarantineDecision(
        action=action,
        current_nonmonotonic_pairs=current_count,
        pilot_nonmonotonic_pairs=pilot_count,
        synchronized_transition_count=len(current),
        synchronized_backward_seconds=tuple(
            (previous - next_value).total_seconds()
            for _ordinal, previous, next_value in current
        ),
        synchronized_raw_ordinals=tuple(ordinal for ordinal, _previous, _next in current),
        metadata_bounds_valid=bounds_valid,
    )
    if action == FULL_SESSION_QUARANTINE:
        return decision, None
    projected = dict(record)
    projected["chargingCurrent"] = {"timestamps": [], "current": []}
    projected["pilotSignal"] = {"timestamps": [], "pilot": []}
    return decision, projected


def build_trajectory_quarantine_audit(
    config: object,
    decisions: tuple[TrajectoryQuarantineDecision, ...],
    *,
    denominator_sessions: int,
) -> TrajectoryQuarantineAudit:
    """Accept only the approved one-session, 3,596-second November signature."""

    month = getattr(config, "month", None)
    trajectory = tuple(
        decision for decision in decisions if decision.action == TRAJECTORY_QUARANTINE
    )
    full = tuple(
        decision for decision in decisions if decision.action == FULL_SESSION_QUARANTINE
    )
    expected_count = 1 if month == "2019-11" else 0
    exact_signatures = all(
        decision.current_nonmonotonic_pairs == 1
        and decision.pilot_nonmonotonic_pairs == 1
        and decision.synchronized_transition_count == 1
        and decision.synchronized_backward_seconds == (3596.0,)
        and decision.metadata_bounds_valid is True
        for decision in trajectory
    )
    approved = bool(
        month in {"2019-02", "2019-08", "2019-11"}
        and isinstance(denominator_sessions, int)
        and not isinstance(denominator_sessions, bool)
        and denominator_sessions > 0
        and len(trajectory) == expected_count
        and len(full) == 0
        and exact_signatures
    )
    return TrajectoryQuarantineAudit(
        approved=approved,
        denominator_sessions=denominator_sessions,
        trajectory_quarantine_count=len(trajectory),
        full_session_quarantine_count=len(full),
        quarantined_current_nonmonotonic_pairs=sum(
            decision.current_nonmonotonic_pairs for decision in (*trajectory, *full)
        ),
        quarantined_pilot_nonmonotonic_pairs=sum(
            decision.pilot_nonmonotonic_pairs for decision in (*trajectory, *full)
        ),
    )


__all__ = [
    "FULL_SESSION_QUARANTINE",
    "NO_QUARANTINE",
    "TRAJECTORY_QUARANTINE",
    "TrajectoryQuarantineAudit",
    "TrajectoryQuarantineDecision",
    "build_trajectory_quarantine_audit",
    "quarantine_record_for_analysis",
]
