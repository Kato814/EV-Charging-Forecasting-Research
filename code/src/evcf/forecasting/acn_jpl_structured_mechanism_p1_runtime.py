"""Runtime binding for P1 session features from accepted cleaned-session artifacts.

The frozen development snapshots persist aggregate M3 arrays, not a guaranteed ragged
``m3.jsonl.gz`` table. This module reconstructs the legal issue-time session rows from
the accepted ``cleaned_sessions.jsonl.gz`` artifact using the already-reviewed snapshot
semantics, then requires their pooled 110-column M3 extension to match the frozen
``M3.values.npy`` block before any P1 fit is allowed.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from evcf.data.acn_jpl_issue_snapshots import (
    _bounded_prefix_arrays,
    _held_value_at,
    _integer_member,
    _known_user_input,
    _optional_number,
    _prepared_window_statistics,
    _series_arrays,
)
from evcf.forecasting import acn_jpl_structured_mechanism_p1 as _p1
from evcf.forecasting.acn_jpl_gate1_features import M3_SESSION_FIELDS, fixed_pool

_ZONE = ZoneInfo(_p1.TIMEZONE_NAME)
_MAX_HOLD_SECONDS = 12
_ACTIVE_THRESHOLD_A = 0.1
_M2_RAW_DIMENSION = 201
_M3_EXTENSION_DIMENSION = len(M3_SESSION_FIELDS) * 10
_RUNTIME_PATH = "code/src/evcf/forecasting/acn_jpl_structured_mechanism_p1_runtime.py"


@dataclass(frozen=True, slots=True)
class _RuntimeIndexedSession:
    session_index: int
    connection_utc_s: int
    disconnect_utc_s: int
    current: _p1._CleanCurrentSession
    current_times: np.ndarray
    current_values: np.ndarray
    pilot_times: np.ndarray
    pilot_values: np.ndarray
    user_inputs: Any


def _load_indexed_sessions_runtime(
    path: Path,
    *,
    expected_count: int,
) -> tuple[_RuntimeIndexedSession, ...]:
    base_sessions = _p1._ORIGINAL_LOAD_INDEXED_SESSIONS(
        path,
        expected_count=expected_count,
    )
    base_lookup = {item.session_index: item for item in base_sessions}
    output: list[_RuntimeIndexedSession] = []
    seen: set[int] = set()
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for line in handle:
                if not line.strip():
                    raise _p1.MechanismP1Error("CLEANED_SESSION_INVALID")
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise _p1.MechanismP1Error("CLEANED_SESSION_INVALID")
                session_index = item.get("session_index")
                if (
                    isinstance(session_index, bool)
                    or not isinstance(session_index, int)
                    or session_index in seen
                    or session_index not in base_lookup
                ):
                    raise _p1.MechanismP1Error("CLEANED_SESSION_INVALID")
                base = base_lookup[session_index]
                current_times, current_values = _series_arrays(item, "current")
                pilot_times, pilot_values = _series_arrays(item, "pilot")
                output.append(
                    _RuntimeIndexedSession(
                        session_index=session_index,
                        connection_utc_s=base.connection_utc_s,
                        disconnect_utc_s=base.disconnect_utc_s,
                        current=base.current,
                        current_times=current_times.astype(np.int64, copy=False),
                        current_values=current_values.astype(np.float64, copy=False),
                        pilot_times=pilot_times.astype(np.int64, copy=False),
                        pilot_values=pilot_values.astype(np.float64, copy=False),
                        user_inputs=item.get("user_inputs"),
                    )
                )
                seen.add(session_index)
    except _p1.MechanismP1Error:
        raise
    except (OSError, UnicodeError, gzip.BadGzipFile, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise _p1.MechanismP1Error("CLEANED_SESSION_INVALID") from exc
    if len(output) != expected_count or seen != set(base_lookup):
        raise _p1.MechanismP1Error("CLEANED_SESSION_COUNT_INVALID")
    return tuple(sorted(output, key=lambda item: item.session_index))


def _session_feature_values(
    session: _RuntimeIndexedSession,
    issue_epoch: int,
    *,
    preserve_unobserved_trajectory_missingness: bool,
) -> list[float]:
    current_prefix = _bounded_prefix_arrays(
        session.current_times,
        session.current_values,
        disconnect_epoch=session.disconnect_utc_s,
        max_hold_seconds=_MAX_HOLD_SECONDS,
        active_threshold_a=_ACTIVE_THRESHOLD_A,
    )
    prepared = {
        "current_times": session.current_times,
        "current_values": session.current_values,
        "current_prefix": current_prefix,
    }
    current_current = _held_value_at(
        session.current_times,
        session.current_values,
        issue_epoch,
        connection_epoch=session.connection_utc_s,
        disconnect_epoch=session.disconnect_utc_s,
        max_hold_seconds=_MAX_HOLD_SECONDS,
    )
    recent = _prepared_window_statistics(
        prepared,
        issue_epoch - 900,
        issue_epoch,
    )
    cumulative = _prepared_window_statistics(
        prepared,
        session.connection_utc_s,
        issue_epoch,
    )
    cumulative_observed = int(cumulative["covered_seconds"])
    cumulative_missing = bool(
        preserve_unobserved_trajectory_missingness and not cumulative_observed
    )
    current_pilot = _held_value_at(
        session.pilot_times,
        session.pilot_values,
        issue_epoch,
        connection_epoch=session.connection_utc_s,
        disconnect_epoch=session.disconnect_utc_s,
        max_hold_seconds=_MAX_HOLD_SECONDS,
    )
    known_input = _known_user_input({"user_inputs": session.user_inputs}, issue_epoch)
    requested_departure: int | None = None
    requested_kwh: float | None = None
    if known_input is not None:
        requested_departure = _integer_member(
            known_input,
            "requested_departure_utc_s",
        )
        requested_kwh = _optional_number(
            known_input.get("kwh_requested")
            if isinstance(known_input, dict) and known_input.get("kwh_requested") is not None
            else (
                known_input.get("kWhRequested")
                if isinstance(known_input, dict)
                else None
            )
        )
    values: list[float | None] = [
        float(issue_epoch - session.connection_utc_s),
        None if cumulative_missing else float(cumulative["active_seconds"]),
        current_current,
        (
            float(recent["area"]) / int(recent["covered_seconds"])
            if recent["covered_seconds"]
            else None
        ),
        recent["peak"],
        float(recent["covered_seconds"]) / 900.0,
        None if cumulative_missing else float(cumulative["area"]) / 3600.0,
        (
            cumulative_observed / (issue_epoch - session.connection_utc_s)
            if issue_epoch > session.connection_utc_s
            else 0.0
        ),
        current_pilot,
        (
            (requested_departure - issue_epoch) / 60.0
            if requested_departure is not None
            else None
        ),
        requested_kwh,
    ]
    if len(values) != len(M3_SESSION_FIELDS):
        raise _p1.MechanismP1Error("SESSION_FEATURE_INVALID")
    return [float("nan") if value is None else float(value) for value in values]


def _build_candidate_table(
    *,
    issue_times: np.ndarray,
    sessions: tuple[_RuntimeIndexedSession, ...],
    preserve_unobserved_trajectory_missingness: bool,
) -> _p1._SessionFeatureTable:
    issue_indices: list[int] = []
    row_times: list[int] = []
    session_indices: list[int] = []
    raw_rows: list[list[float]] = []
    ordered_sessions = tuple(
        sorted(sessions, key=lambda item: (item.connection_utc_s, item.session_index))
    )
    for issue_index, issue_raw in enumerate(issue_times):
        issue = int(issue_raw)
        local = datetime.fromtimestamp(issue, timezone.utc).astimezone(_ZONE)
        calendar = [
            float(local.hour * 4 + local.minute // 15),
            float(local.weekday()),
            float(local.weekday() >= 5),
        ]
        for session in ordered_sessions:
            if session.connection_utc_s > issue:
                break
            if issue >= session.disconnect_utc_s:
                continue
            values = _session_feature_values(
                session,
                issue,
                preserve_unobserved_trajectory_missingness=(
                    preserve_unobserved_trajectory_missingness
                ),
            )
            issue_indices.append(issue_index)
            row_times.append(issue)
            session_indices.append(session.session_index)
            raw_rows.append(values + calendar)
    raw = np.asarray(raw_rows, dtype=np.float64)
    if raw.ndim != 2 or raw.shape[1] != _p1._E_RAW_DIMENSION:
        raise _p1.MechanismP1Error("SESSION_FEATURE_INVALID")
    return _p1._SessionFeatureTable(
        issue_indices=np.asarray(issue_indices, dtype=np.int64),
        issue_times=np.asarray(row_times, dtype=np.int64),
        session_indices=np.asarray(session_indices, dtype=np.int64),
        raw_features=raw,
    )


def _pooled_extension(
    table: _p1._SessionFeatureTable,
    *,
    issue_count: int,
) -> np.ndarray:
    extension = np.empty((issue_count, _M3_EXTENSION_DIMENSION), dtype=np.float64)
    rows_by_issue: dict[int, list[int]] = {}
    for row, issue_index in enumerate(table.issue_indices):
        rows_by_issue.setdefault(int(issue_index), []).append(row)
    for issue_index in range(issue_count):
        rows = rows_by_issue.get(issue_index, ())
        for field_index in range(len(M3_SESSION_FIELDS)):
            values = [
                (
                    None
                    if np.isnan(table.raw_features[row, field_index])
                    else float(table.raw_features[row, field_index])
                )
                for row in rows
            ]
            start = field_index * 10
            extension[issue_index, start : start + 10] = fixed_pool(
                values,
                total_count=len(rows),
            )
    return extension


def _load_m3_session_features_runtime(
    path: Path,
    *,
    issue_times: np.ndarray,
    sessions: tuple[_RuntimeIndexedSession, ...],
) -> _p1._SessionFeatureTable:
    month_root = path.parent
    m3_values_path = month_root / "M3.values.npy"
    m3_times_path = month_root / "M3.issue_times.npy"
    if (
        not m3_values_path.is_file()
        or m3_values_path.is_symlink()
        or not m3_times_path.is_file()
        or m3_times_path.is_symlink()
    ):
        raise _p1.MechanismP1Error("FEATURE_INVALID")
    try:
        frozen_values = np.asarray(np.load(m3_values_path, allow_pickle=False))
        frozen_times = np.asarray(np.load(m3_times_path, allow_pickle=False))
    except (OSError, ValueError) as exc:
        raise _p1.MechanismP1Error("FEATURE_INVALID") from exc
    if (
        frozen_values.shape != (len(issue_times), 311)
        or frozen_times.shape != issue_times.shape
        or not np.array_equal(frozen_times, issue_times)
    ):
        raise _p1.MechanismP1Error("FEATURE_INVALID")
    frozen_extension = frozen_values[:, _M2_RAW_DIMENSION:]

    matches: list[_p1._SessionFeatureTable] = []
    for preserve in (False, True):
        candidate = _build_candidate_table(
            issue_times=issue_times,
            sessions=sessions,
            preserve_unobserved_trajectory_missingness=preserve,
        )
        rebuilt = _pooled_extension(candidate, issue_count=len(issue_times))
        if np.allclose(
            rebuilt,
            frozen_extension,
            rtol=2e-5,
            atol=2e-6,
            equal_nan=True,
        ):
            matches.append(candidate)
    if len(matches) != 1:
        raise _p1.MechanismP1Error("SESSION_FEATURE_RECONSTRUCTION_INVALID")
    return matches[0]


if not hasattr(_p1, "_ORIGINAL_LOAD_INDEXED_SESSIONS"):
    _p1._ORIGINAL_LOAD_INDEXED_SESSIONS = _p1._load_indexed_sessions
_p1._load_indexed_sessions = _load_indexed_sessions_runtime
_p1._load_m3_session_features = _load_m3_session_features_runtime
if _RUNTIME_PATH not in _p1.IMPLEMENTATION_PATHS:
    _p1.IMPLEMENTATION_PATHS = (*_p1.IMPLEMENTATION_PATHS, _RUNTIME_PATH)

MechanismP1Error = _p1.MechanismP1Error
MechanismP1Protocol = _p1.MechanismP1Protocol
MechanismP1RunResult = _p1.MechanismP1RunResult
load_mechanism_p1_protocol = _p1.load_mechanism_p1_protocol
run_mechanism_p1 = _p1.run_mechanism_p1
verify_mechanism_p1_implementation_commit = _p1.verify_mechanism_p1_implementation_commit

__all__ = [
    "MechanismP1Error",
    "MechanismP1Protocol",
    "MechanismP1RunResult",
    "load_mechanism_p1_protocol",
    "run_mechanism_p1",
    "verify_mechanism_p1_implementation_commit",
]
