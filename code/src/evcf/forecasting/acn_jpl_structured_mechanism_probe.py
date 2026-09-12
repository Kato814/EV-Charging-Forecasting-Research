"""Frozen low-complexity P1 mechanism probe for JPL structured load forecasting.

P1 follows docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md. It keeps
all final-holdout months sealed and uses future session information only as
supervised labels. Prediction-time features are restricted to the accepted M3
issue-time session rows (Probe E) and the accepted M2 feature block (Probe A).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import GammaRegressor, LogisticRegression, PoissonRegressor
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from evcf.forecasting.acn_jpl_development_experts import MonthData
from evcf.forecasting.acn_jpl_development_experts_compat import (
    DevelopmentExpertError,
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_gate1_data import (
    _validate_m3_row,
    group_by_canonical_issue_time,
)
from evcf.forecasting.acn_jpl_gate1_features import M3_SESSION_FIELDS
from evcf.forecasting.acn_jpl_structured_baseline import load_structured_protocol

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
TIMEZONE_NAME = "America/Los_Angeles"
_ZONE = ZoneInfo(TIMEZONE_NAME)

EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256 = (
    "2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd"
)
EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256 = (
    "562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1"
)
EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256 = (
    "02c7809f1113aeaf20723030c96006ee0831b20ff219106da7d6968df535d71a"
)
EXPECTED_STRUCTURED_PROTOCOL_SHA256 = (
    "74af85044d12f3c68fe4156e6ad1ae67b6e5486b47aecd5637cd67d6539c1902"
)
_RECONSTRUCTION_TOLERANCE_A = 1e-6
_ZERO_TOLERANCE = 1e-12

IMPLEMENTATION_PATHS = (
    "docs/JPL_STRUCTURED_MECHANISM_PROBE_PROTOCOL_20260911.md",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_data.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_structured_baseline.py",
    "code/src/evcf/forecasting/acn_jpl_structured_mechanism_probe.py",
    "scripts/run_jpl_structured_mechanism_probe.py",
)

_SESSION_PREDICTORS = tuple(M3_SESSION_FIELDS)
_CALENDAR_NAMES = ("quarter_hour_index", "day_of_week", "is_weekend")
_EXPECTED_E_RAW_WIDTH = 14
_EXPECTED_E_ENCODED_WIDTH = 25
_EXPECTED_M2_RAW_WIDTH = 201
_EXPECTED_M2_ENCODED_WIDTH = 204


class MechanismProbeError(RuntimeError):
    """Static failure code safe for public aggregate status output."""

    def __init__(self, reason_code: str) -> None:
        if (
            not isinstance(reason_code, str)
            or not reason_code
            or not reason_code.replace("_", "").isalnum()
        ):
            reason_code = "UNEXPECTED_ERROR"
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class _CurrentSession:
    session_index: int
    connection_utc_s: int
    disconnect_utc_s: int
    starts: np.ndarray
    ends: np.ndarray
    values: np.ndarray


@dataclass(frozen=True, slots=True)
class _TaskPrediction:
    issue_times: np.ndarray
    day_starts: np.ndarray
    existing_truth: np.ndarray
    arrival_truth: np.ndarray
    e_predictions: np.ndarray
    a_predictions: np.ndarray
    continuation_truth: np.ndarray
    continuation_probability: np.ndarray
    continuation_mark_truth: np.ndarray
    continuation_mark_prediction: np.ndarray
    arrival_count_truth: np.ndarray
    arrival_count_prediction: np.ndarray
    arrival_mark_truth: np.ndarray
    arrival_mark_prediction: np.ndarray
    e_fit_count: int
    a_fit_count: int
    e_constant_probability_folds: int
    e_constant_mark_folds: int
    a_constant_count_folds: int
    a_constant_mark_folds: int


@dataclass(frozen=True, slots=True)
class MechanismProbeRunResult:
    status: str
    code_commit: str
    fit_count: int
    private_cache_file_count: int
    private_manifest_sha256: str
    branch_decisions: Mapping[str, str]
    decision: str
    pooled_overall: Mapping[str, Any]
    pooled_by_horizon: tuple[Mapping[str, Any], ...]
    pooled_by_month: tuple[Mapping[str, Any], ...]
    month_summaries: tuple[Mapping[str, Any], ...]
    holdout_accessed: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "evcf-jpl-structured-mechanism-p1-summary/v1",
            "status": self.status,
            "code_commit": self.code_commit,
            "fit_count": self.fit_count,
            "private_cache_file_count": self.private_cache_file_count,
            "private_manifest_sha256": self.private_manifest_sha256,
            "branch_decisions": dict(self.branch_decisions),
            "decision": self.decision,
            "pooled_overall": dict(self.pooled_overall),
            "pooled_by_horizon": [dict(item) for item in self.pooled_by_horizon],
            "pooled_by_month": [dict(item) for item in self.pooled_by_month],
            "months": [dict(item) for item in self.month_summaries],
            "holdout_accessed": self.holdout_accessed,
            "hyperparameter_search": False,
            "prediction_clipping": False,
            "prediction_calibration": False,
            "realized_composition_predictor": False,
            "neural_survival_trained": False,
            "neural_tpp_trained": False,
            "gate_trained": False,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise MechanismProbeError("PUBLICATION_INVALID") from exc


def _git_semantic_verify(code_commit: str, *, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise MechanismProbeError("IMPLEMENTATION_DRIFT")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
        encoding="ascii",
        errors="ignore",
    )
    if head.returncode != 0 or head.stdout.strip() != code_commit:
        raise MechanismProbeError("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise MechanismProbeError("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode != 0:
            raise MechanismProbeError("IMPLEMENTATION_DRIFT")
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            "--no-ext-diff",
            code_commit,
            "--",
            *IMPLEMENTATION_PATHS,
        ],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if diff.returncode != 0:
        raise MechanismProbeError("IMPLEMENTATION_DRIFT")


def _expected_cache_names() -> set[str]:
    return {
        f"{month}_h{horizon:03d}.npz"
        for month in DEVELOPMENT_MONTHS
        for horizon in HORIZONS_MINUTES
    }


def _verify_private_manifest(
    root: Path,
    *,
    expected_sha256: str,
    schema_version: str,
    entries_key: str,
) -> Mapping[str, Any]:
    manifest_path = root / "private_manifest.json"
    if (
        not root.is_dir()
        or root.is_symlink()
        or not manifest_path.is_file()
        or manifest_path.is_symlink()
        or _sha256_file(manifest_path) != expected_sha256
    ):
        raise MechanismProbeError("PRIVATE_CACHE_IDENTITY_INVALID")
    try:
        document = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MechanismProbeError("PRIVATE_CACHE_IDENTITY_INVALID") from exc
    entries = document.get(entries_key)
    if document.get("schema_version") != schema_version or not isinstance(entries, list):
        raise MechanismProbeError("PRIVATE_CACHE_IDENTITY_INVALID")
    expected = _expected_cache_names()
    seen: set[str] = set()
    for item in entries:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"name", "sha256"}
            or not isinstance(item["name"], str)
            or not isinstance(item["sha256"], str)
        ):
            raise MechanismProbeError("PRIVATE_CACHE_IDENTITY_INVALID")
        name = item["name"]
        path = root / name
        if (
            name in seen
            or name not in expected
            or not path.is_file()
            or path.is_symlink()
            or _sha256_file(path) != item["sha256"]
        ):
            raise MechanismProbeError("PRIVATE_CACHE_IDENTITY_INVALID")
        seen.add(name)
    if seen != expected:
        raise MechanismProbeError("PRIVATE_CACHE_IDENTITY_INVALID")
    return MappingProxyType(dict(document))


def _load_npz(path: Path, required: set[str]) -> dict[str, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != required:
                raise MechanismProbeError("PRIVATE_CACHE_SCHEMA_INVALID")
            return {name: np.asarray(archive[name]) for name in required}
    except MechanismProbeError:
        raise
    except (OSError, ValueError) as exc:
        raise MechanismProbeError("PRIVATE_CACHE_SCHEMA_INVALID") from exc


def _load_reference_pair(
    *,
    baseline_root: Path,
    structured_root: Path,
    month: str,
    horizon: int,
) -> dict[str, np.ndarray]:
    baseline = _load_npz(
        baseline_root / f"{month}_h{horizon:03d}.npz",
        {
            "issue_times",
            "day_start_utc_s",
            "y_true",
            "m2_predictions",
            "m3_predictions",
            "equal_predictions",
        },
    )
    structured = _load_npz(
        structured_root / f"{month}_h{horizon:03d}.npz",
        {
            "issue_times",
            "day_start_utc_s",
            "y_true",
            "existing_truth",
            "arrival_truth",
            "existing_predictions",
            "arrival_predictions",
            "structured_predictions",
        },
    )
    n = len(structured["issue_times"])
    if n == 0 or any(array.shape != (n,) for array in structured.values()):
        raise MechanismProbeError("PRIVATE_CACHE_SCHEMA_INVALID")
    if any(array.shape != (n,) for array in baseline.values()):
        raise MechanismProbeError("PRIVATE_CACHE_SCHEMA_INVALID")
    if not (
        np.array_equal(baseline["issue_times"], structured["issue_times"])
        and np.array_equal(
            baseline["day_start_utc_s"], structured["day_start_utc_s"]
        )
        and np.allclose(
            baseline["y_true"],
            structured["y_true"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
        and np.allclose(
            structured["existing_truth"] + structured["arrival_truth"],
            structured["y_true"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
        and np.allclose(
            structured["existing_predictions"] + structured["arrival_predictions"],
            structured["structured_predictions"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise MechanismProbeError("COMMON_ROW_IDENTITY_INVALID")
    numeric = [
        array
        for key, array in {**baseline, **structured}.items()
        if key not in {"issue_times", "day_start_utc_s"}
    ]
    if not all(np.isfinite(array).all() for array in numeric):
        raise MechanismProbeError("PRIVATE_CACHE_SCHEMA_INVALID")
    return {**baseline, **structured}


def _local_midnight_epoch(epoch_seconds: int) -> int:
    local = datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(_ZONE)
    return int(datetime.combine(local.date(), time.min, tzinfo=_ZONE).timestamp())


def _test_day_starts(
    issue_times: np.ndarray, test_start_day: int
) -> tuple[np.ndarray, np.ndarray]:
    all_day_starts = np.asarray(
        [_local_midnight_epoch(int(value)) for value in issue_times], dtype=np.int64
    )
    local_days = np.asarray(
        [
            datetime.fromtimestamp(int(value), timezone.utc).astimezone(_ZONE).day
            for value in issue_times
        ],
        dtype=np.int16,
    )
    test_rows = np.flatnonzero(local_days >= test_start_day).astype(np.int64)
    if not len(test_rows):
        raise MechanismProbeError("ROLLING_SPLIT_INVALID")
    return all_day_starts, np.unique(all_day_starts[test_rows])


def _parse_current_session(
    raw: Mapping[str, Any], expected_index: int
) -> _CurrentSession:
    if raw.get("schema_version") != "acn-jpl-clean-session/v1":
        raise MechanismProbeError("CLEANED_SESSION_INVALID")
    session_index = raw.get("session_index")
    connection = raw.get("connection_utc_s")
    disconnect = raw.get("disconnect_utc_s")
    current = raw.get("current")
    if (
        isinstance(session_index, bool)
        or not isinstance(session_index, int)
        or session_index != expected_index
        or isinstance(connection, bool)
        or not isinstance(connection, int)
        or isinstance(disconnect, bool)
        or not isinstance(disconnect, int)
        or disconnect <= connection
        or not isinstance(current, Mapping)
        or current.get("field_name") != "chargingCurrent"
    ):
        raise MechanismProbeError("CLEANED_SESSION_INVALID")
    times = current.get("timestamps_utc_s")
    values = current.get("values")
    ordinals = current.get("raw_ordinals")
    hold_cap = current.get("locf_cap_s")
    if (
        not isinstance(times, list)
        or not isinstance(values, list)
        or not isinstance(ordinals, list)
        or len(times) != len(values)
        or len(values) != len(ordinals)
        or isinstance(hold_cap, bool)
        or not isinstance(hold_cap, int)
        or hold_cap <= 0
    ):
        raise MechanismProbeError("CLEANED_SESSION_INVALID")
    starts_list: list[int] = []
    values_list: list[float] = []
    previous: int | None = None
    for timestamp, value, ordinal in zip(times, values, ordinals, strict=True):
        if (
            isinstance(timestamp, bool)
            or not isinstance(timestamp, int)
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
        ):
            raise MechanismProbeError("CLEANED_SESSION_INVALID")
        parsed = float(value)
        if (
            timestamp < connection
            or timestamp >= disconnect
            or not math.isfinite(parsed)
            or parsed < 0
            or (previous is not None and timestamp <= previous)
        ):
            raise MechanismProbeError("CLEANED_SESSION_INVALID")
        starts_list.append(timestamp)
        values_list.append(parsed)
        previous = timestamp
    starts = np.asarray(starts_list, dtype=np.int64)
    signal_values = np.asarray(values_list, dtype=np.float64)
    ends = np.empty_like(starts)
    for index, timestamp in enumerate(starts):
        next_timestamp = (
            int(starts[index + 1]) if index + 1 < len(starts) else disconnect
        )
        ends[index] = min(next_timestamp, int(timestamp) + hold_cap, disconnect)
    keep = ends > starts
    return _CurrentSession(
        session_index=session_index,
        connection_utc_s=connection,
        disconnect_utc_s=disconnect,
        starts=starts[keep],
        ends=ends[keep],
        values=signal_values[keep],
    )


def _load_current_sessions(
    path: Path, *, expected_count: int
) -> tuple[_CurrentSession, ...]:
    sessions: list[_CurrentSession] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for index, line in enumerate(handle):
                if not line.strip():
                    raise MechanismProbeError("CLEANED_SESSION_INVALID")
                raw = json.loads(line)
                if not isinstance(raw, Mapping):
                    raise MechanismProbeError("CLEANED_SESSION_INVALID")
                sessions.append(_parse_current_session(raw, index))
    except MechanismProbeError:
        raise
    except (OSError, UnicodeError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise MechanismProbeError("CLEANED_SESSION_INVALID") from exc
    if len(sessions) != expected_count:
        raise MechanismProbeError("CLEANED_SESSION_COUNT_INVALID")
    return tuple(sessions)


def _session_integral(
    session: _CurrentSession, start_utc_s: int, end_utc_s: int
) -> float:
    if end_utc_s <= start_utc_s or session.starts.size == 0:
        return 0.0
    index = max(0, int(np.searchsorted(session.ends, start_utc_s, side="right")))
    terms: list[float] = []
    for position in range(index, len(session.starts)):
        segment_start = int(session.starts[position])
        if segment_start >= end_utc_s:
            break
        left = max(start_utc_s, segment_start)
        right = min(end_utc_s, int(session.ends[position]))
        if right > left:
            terms.append(float(session.values[position]) * (right - left))
    return math.fsum(terms)


def _build_contributions(
    sessions: tuple[_CurrentSession, ...], issue_times: np.ndarray
) -> Mapping[int, tuple[tuple[int, int, float], ...]]:
    target_starts = {
        int(issue) + horizon * 60 - 900
        for issue in issue_times
        for horizon in HORIZONS_MINUTES
    }
    output: dict[int, list[tuple[int, int, float]]] = {}
    if not target_starts:
        return MappingProxyType({})
    low = min(target_starts)
    high = max(target_starts)
    for session in sessions:
        if session.starts.size == 0:
            continue
        first = max(
            low,
            int(math.floor(int(session.starts[0]) / 900.0) * 900),
        )
        last = min(
            high,
            int(math.floor((int(session.ends[-1]) - 1e-9) / 900.0) * 900),
        )
        if last < first:
            continue
        for start in range(first, last + 1, 900):
            if start not in target_starts:
                continue
            eligible_start = max(start, session.connection_utc_s)
            eligible_end = min(start + 900, session.disconnect_utc_s)
            if eligible_end <= eligible_start:
                continue
            contribution = (
                _session_integral(session, eligible_start, eligible_end) / 900.0
            )
            if contribution > 0:
                output.setdefault(start, []).append(
                    (session.session_index, session.connection_utc_s, contribution)
                )
    return MappingProxyType(
        {
            start: tuple(sorted(rows, key=lambda item: (item[1], item[0])))
            for start, rows in output.items()
        }
    )


def _component_labels(
    *,
    issue_times: np.ndarray,
    total_labels: np.ndarray,
    contributions: Mapping[int, tuple[tuple[int, int, float], ...]],
) -> tuple[np.ndarray, np.ndarray, tuple[Mapping[int, float], ...]]:
    existing = np.zeros_like(total_labels)
    arrival = np.zeros_like(total_labels)
    session_maps: list[Mapping[int, float]] = []
    for row, issue_raw in enumerate(issue_times):
        issue = int(issue_raw)
        per_horizon: dict[int, float] = {}
        for column, horizon in enumerate(HORIZONS_MINUTES):
            start = issue + horizon * 60 - 900
            rows = contributions.get(start, ())
            existing_rows = [
                (session, value)
                for session, connection, value in rows
                if connection <= issue
            ]
            arrival_rows = [
                (session, value)
                for session, connection, value in rows
                if connection > issue
            ]
            existing[row, column] = math.fsum(value for _, value in existing_rows)
            arrival[row, column] = math.fsum(value for _, value in arrival_rows)
            for session, value in existing_rows:
                per_horizon[(column << 32) | session] = value
        session_maps.append(MappingProxyType(per_horizon))
    if not np.allclose(
        existing + arrival,
        total_labels,
        rtol=0.0,
        atol=_RECONSTRUCTION_TOLERANCE_A,
    ):
        raise MechanismProbeError("COMPONENT_RECONSTRUCTION_INVALID")
    return existing, arrival, tuple(session_maps)


def _load_m3_groups(
    processed: Path, issue_times: np.ndarray
) -> tuple[tuple[Mapping[str, Any], ...], ...]:
    rows: list[Mapping[str, Any]] = []
    path = processed / "m3.jsonl.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for ordinal, line in enumerate(handle):
                if not line.strip():
                    raise MechanismProbeError("M3_SESSION_FEATURE_INVALID")
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise MechanismProbeError("M3_SESSION_FEATURE_INVALID")
                rows.append(
                    MappingProxyType(
                        _validate_m3_row(
                            raw,
                            ordinal,
                            require_unobserved_trajectory_missingness=True,
                        )
                    )
                )
    except MechanismProbeError:
        raise
    except (
        OSError,
        UnicodeError,
        gzip.BadGzipFile,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as exc:
        raise MechanismProbeError("M3_SESSION_FEATURE_INVALID") from exc
    try:
        return group_by_canonical_issue_time(issue_times, rows)
    except (TypeError, ValueError) as exc:
        raise MechanismProbeError("M3_SESSION_FEATURE_INVALID") from exc


def _calendar_columns(data: MonthData) -> np.ndarray:
    block = data.blocks["M2"]
    indexes = []
    for name in _CALENDAR_NAMES:
        try:
            indexes.append(block.feature_names.index(name))
        except ValueError as exc:
            raise MechanismProbeError("FEATURE_INVALID") from exc
    calendar = block.values[:, indexes]
    if calendar.shape != (len(data.issue_times), 3) or not np.isfinite(calendar).all():
        raise MechanismProbeError("FEATURE_INVALID")
    return np.asarray(calendar, dtype=np.float64)


def _e_raw_groups(
    *,
    data: MonthData,
    m3_groups: tuple[tuple[Mapping[str, Any], ...], ...],
) -> tuple[np.ndarray, ...]:
    calendar = _calendar_columns(data)
    groups: list[np.ndarray] = []
    for position, rows in enumerate(m3_groups):
        matrix = np.empty((len(rows), _EXPECTED_E_RAW_WIDTH), dtype=np.float64)
        for row_position, row in enumerate(rows):
            values: list[float] = []
            for field in _SESSION_PREDICTORS:
                value = row[field]
                values.append(np.nan if value is None else float(value))
            values.extend(float(item) for item in calendar[position])
            matrix[row_position] = np.asarray(values, dtype=np.float64)
        if np.any(np.isinf(matrix)):
            raise MechanismProbeError("FEATURE_INVALID")
        groups.append(matrix)
    return tuple(groups)


def _e_label_groups(
    *,
    existing_labels: np.ndarray,
    m3_groups: tuple[tuple[Mapping[str, Any], ...], ...],
    session_maps: tuple[Mapping[int, float], ...],
    horizon_position: int,
) -> tuple[np.ndarray, ...]:
    groups: list[np.ndarray] = []
    for issue_position, rows in enumerate(m3_groups):
        labels = np.zeros(len(rows), dtype=np.float64)
        mapping = session_maps[issue_position]
        for row_position, row in enumerate(rows):
            session = int(row["anonymous_session_index"])
            labels[row_position] = mapping.get(
                (horizon_position << 32) | session,
                0.0,
            )
        if (
            abs(
                float(np.sum(labels))
                - float(existing_labels[issue_position, horizon_position])
            )
            > _RECONSTRUCTION_TOLERANCE_A
        ):
            raise MechanismProbeError("EXISTING_SESSION_RECONSTRUCTION_INVALID")
        groups.append(labels)
    return tuple(groups)


def _a_targets(
    *,
    issue_times: np.ndarray,
    arrival_labels: np.ndarray,
    contributions: Mapping[int, tuple[tuple[int, int, float], ...]],
    horizon_position: int,
) -> tuple[np.ndarray, np.ndarray]:
    horizon = HORIZONS_MINUTES[horizon_position]
    counts = np.zeros(len(issue_times), dtype=np.float64)
    marks = np.zeros(len(issue_times), dtype=np.float64)
    for row, issue_raw in enumerate(issue_times):
        issue = int(issue_raw)
        start = issue + horizon * 60 - 900
        values = [
            value
            for _, connection, value in contributions.get(start, ())
            if connection > issue
        ]
        count = len(values)
        total = math.fsum(values)
        counts[row] = float(count)
        marks[row] = 0.0 if count == 0 else total / count
        if (
            abs(
                float(counts[row] * marks[row])
                - float(arrival_labels[row, horizon_position])
            )
            > _RECONSTRUCTION_TOLERANCE_A
        ):
            raise MechanismProbeError("ARRIVAL_SESSION_RECONSTRUCTION_INVALID")
    return counts, marks


def _fit_transform_e(
    train_raw: np.ndarray, test_raw: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    if (
        train_raw.ndim != 2
        or test_raw.ndim != 2
        or train_raw.shape[1] != _EXPECTED_E_RAW_WIDTH
        or test_raw.shape[1] != _EXPECTED_E_RAW_WIDTH
    ):
        raise MechanismProbeError("FEATURE_INVALID")
    train_indicators = np.isnan(
        train_raw[:, : len(_SESSION_PREDICTORS)]
    ).astype(np.float64)
    test_indicators = np.isnan(test_raw[:, : len(_SESSION_PREDICTORS)]).astype(
        np.float64
    )
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    train_imputed = imputer.fit_transform(train_raw)
    test_imputed = imputer.transform(test_raw)
    train_encoded = np.concatenate((train_imputed, train_indicators), axis=1)
    test_encoded = np.concatenate((test_imputed, test_indicators), axis=1)
    scaler = StandardScaler()
    train_scaled = scaler.fit_transform(train_encoded)
    test_scaled = scaler.transform(test_encoded)
    if (
        train_scaled.shape[1] != _EXPECTED_E_ENCODED_WIDTH
        or test_scaled.shape[1] != _EXPECTED_E_ENCODED_WIDTH
    ):
        raise MechanismProbeError("FEATURE_INVALID")
    if not np.isfinite(train_scaled).all() or not np.isfinite(test_scaled).all():
        raise MechanismProbeError("FEATURE_INVALID")
    return train_scaled, test_scaled


def _fit_transform_a(
    block_values: np.ndarray,
    nullable_mask: np.ndarray,
    fit_rows: np.ndarray,
    test_rows: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if block_values.ndim != 2 or block_values.shape[1] != _EXPECTED_M2_RAW_WIDTH:
        raise MechanismProbeError("FEATURE_INVALID")
    if (
        nullable_mask.shape != (_EXPECTED_M2_RAW_WIDTH,)
        or nullable_mask.dtype != np.bool_
    ):
        raise MechanismProbeError("FEATURE_INVALID")
    train_raw = block_values[fit_rows]
    test_raw = block_values[test_rows]
    train_indicators = np.isnan(train_raw[:, nullable_mask]).astype(np.float64)
    test_indicators = np.isnan(test_raw[:, nullable_mask]).astype(np.float64)
    imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    train_imputed = imputer.fit_transform(train_raw)
    test_imputed = imputer.transform(test_raw)
    train_encoded = np.concatenate((train_imputed, train_indicators), axis=1)
    test_encoded = np.concatenate((test_imputed, test_indicators), axis=1)
    scaler = StandardScaler()
    train_scaled = scaler.fit_transform(train_encoded)
    test_scaled = scaler.transform(test_encoded)
    if (
        train_scaled.shape[1] != _EXPECTED_M2_ENCODED_WIDTH
        or test_scaled.shape[1] != _EXPECTED_M2_ENCODED_WIDTH
    ):
        raise MechanismProbeError("FEATURE_INVALID")
    if not np.isfinite(train_scaled).all() or not np.isfinite(test_scaled).all():
        raise MechanismProbeError("FEATURE_INVALID")
    return train_scaled, test_scaled


def _fit_continuation(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
) -> tuple[np.ndarray, int, int]:
    unique = np.unique(y_train)
    if y_train.size == 0 or not set(unique.tolist()).issubset({0.0, 1.0}):
        raise MechanismProbeError("CONTINUATION_LABEL_INVALID")
    if unique.size == 1:
        return np.full(len(x_test), float(unique[0]), dtype=np.float64), 0, 1
    try:
        estimator = LogisticRegression(
            penalty="l2",
            C=1.0,
            solver="lbfgs",
            max_iter=1000,
        )
        with threadpool_limits(limits=1):
            estimator.fit(x_train, y_train.astype(np.int8))
            probability = np.asarray(
                estimator.predict_proba(x_test)[:, 1],
                dtype=np.float64,
            )
    except Exception as exc:  # noqa: BLE001 - exception text remains private
        raise MechanismProbeError("MODEL_FIT_FAILED") from exc
    if (
        probability.shape != (len(x_test),)
        or not np.isfinite(probability).all()
        or np.any((probability < 0) | (probability > 1))
    ):
        raise MechanismProbeError("MODEL_OUTPUT_INVALID")
    return probability, 1, 0


def _fit_positive_mark(
    x_train: np.ndarray,
    y_train: np.ndarray,
    positive_mask: np.ndarray,
    x_test: np.ndarray,
) -> tuple[np.ndarray, int, int]:
    positive = y_train[positive_mask]
    if np.any(positive <= 0) or not np.isfinite(positive).all():
        raise MechanismProbeError("POSITIVE_MARK_INVALID")
    if positive.size == 0:
        return np.zeros(len(x_test), dtype=np.float64), 0, 1
    if positive.size == 1:
        return np.full(len(x_test), float(positive[0]), dtype=np.float64), 0, 1
    try:
        estimator = GammaRegressor(alpha=1.0, max_iter=1000)
        with threadpool_limits(limits=1):
            estimator.fit(x_train[positive_mask], positive)
            prediction = np.asarray(estimator.predict(x_test), dtype=np.float64)
    except Exception as exc:  # noqa: BLE001
        raise MechanismProbeError("MODEL_FIT_FAILED") from exc
    if (
        prediction.shape != (len(x_test),)
        or not np.isfinite(prediction).all()
        or np.any(prediction <= 0)
    ):
        raise MechanismProbeError("MODEL_OUTPUT_INVALID")
    return prediction, 1, 0


def _fit_arrival_count(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
) -> tuple[np.ndarray, int, int]:
    if (
        np.any(y_train < 0)
        or not np.isfinite(y_train).all()
        or np.any(y_train != np.floor(y_train))
    ):
        raise MechanismProbeError("ARRIVAL_COUNT_INVALID")
    if np.all(y_train == 0):
        return np.zeros(len(x_test), dtype=np.float64), 0, 1
    try:
        estimator = PoissonRegressor(alpha=1.0, max_iter=1000)
        with threadpool_limits(limits=1):
            estimator.fit(x_train, y_train)
            prediction = np.asarray(estimator.predict(x_test), dtype=np.float64)
    except Exception as exc:  # noqa: BLE001
        raise MechanismProbeError("MODEL_FIT_FAILED") from exc
    if (
        prediction.shape != (len(x_test),)
        or not np.isfinite(prediction).all()
        or np.any(prediction < 0)
    ):
        raise MechanismProbeError("MODEL_OUTPUT_INVALID")
    return prediction, 1, 0


def _concat_groups(groups: tuple[np.ndarray, ...], rows: np.ndarray) -> np.ndarray:
    selected = [
        groups[int(position)] for position in rows if len(groups[int(position)])
    ]
    if not selected:
        width = groups[0].shape[1] if groups and groups[0].ndim == 2 else None
        if width is not None:
            return np.empty((0, width), dtype=np.float64)
        return np.empty(0, dtype=np.float64)
    return np.concatenate(selected, axis=0)


def _predict_horizon(
    *,
    data: MonthData,
    existing_labels: np.ndarray,
    arrival_labels: np.ndarray,
    e_raw_groups: tuple[np.ndarray, ...],
    e_label_groups: tuple[np.ndarray, ...],
    arrival_counts: np.ndarray,
    arrival_marks: np.ndarray,
    horizon_minutes: int,
    test_start_local_day: int,
) -> _TaskPrediction:
    horizon_position = HORIZONS_MINUTES.index(horizon_minutes)
    issue_times = data.issue_times
    all_day_starts, test_days = _test_day_starts(
        issue_times,
        test_start_local_day,
    )
    m2 = data.blocks["M2"]

    predicted_times: list[np.ndarray] = []
    predicted_days: list[np.ndarray] = []
    existing_truth_out: list[np.ndarray] = []
    arrival_truth_out: list[np.ndarray] = []
    e_predictions_out: list[np.ndarray] = []
    a_predictions_out: list[np.ndarray] = []
    continuation_truth_out: list[np.ndarray] = []
    continuation_probability_out: list[np.ndarray] = []
    continuation_mark_truth_out: list[np.ndarray] = []
    continuation_mark_prediction_out: list[np.ndarray] = []
    arrival_count_truth_out: list[np.ndarray] = []
    arrival_count_prediction_out: list[np.ndarray] = []
    arrival_mark_truth_out: list[np.ndarray] = []
    arrival_mark_prediction_out: list[np.ndarray] = []
    e_fit_count = 0
    a_fit_count = 0
    e_constant_probability_folds = 0
    e_constant_mark_folds = 0
    a_constant_count_folds = 0
    a_constant_mark_folds = 0

    for day_start in test_days:
        fit_rows = np.flatnonzero(
            (issue_times < day_start)
            & (issue_times + horizon_minutes * 60 <= day_start)
        ).astype(np.int64)
        test_rows = np.flatnonzero(all_day_starts == day_start).astype(np.int64)
        if (
            not len(fit_rows)
            or not len(test_rows)
            or np.intersect1d(fit_rows, test_rows).size
        ):
            raise MechanismProbeError("ROLLING_SPLIT_INVALID")
        if int(np.max(issue_times[fit_rows] + horizon_minutes * 60)) > int(
            day_start
        ):
            raise MechanismProbeError("TEMPORAL_LEAKAGE")

        e_train_raw = _concat_groups(e_raw_groups, fit_rows)
        e_test_raw = _concat_groups(e_raw_groups, test_rows)
        e_train_y = _concat_groups(e_label_groups, fit_rows)
        e_test_y = _concat_groups(e_label_groups, test_rows)
        if (
            e_train_raw.ndim != 2
            or e_test_raw.ndim != 2
            or e_train_y.ndim != 1
            or e_test_y.ndim != 1
        ):
            raise MechanismProbeError("FEATURE_INVALID")
        if len(e_train_raw) != len(e_train_y) or len(e_test_raw) != len(e_test_y):
            raise MechanismProbeError("FEATURE_LABEL_ALIGNMENT_INVALID")
        if not len(e_test_raw):
            probability = np.empty(0, dtype=np.float64)
            mark_prediction = np.empty(0, dtype=np.float64)
            expected_session = np.empty(0, dtype=np.float64)
            continuation_test = np.empty(0, dtype=np.float64)
        elif len(e_train_raw):
            e_x_train, e_x_test = _fit_transform_e(e_train_raw, e_test_raw)
            continuation_train = (e_train_y > 0).astype(np.float64)
            continuation_test = (e_test_y > 0).astype(np.float64)
            probability, fits, constants = _fit_continuation(
                e_x_train,
                continuation_train,
                e_x_test,
            )
            mark_prediction, mark_fits, mark_constants = _fit_positive_mark(
                e_x_train,
                e_train_y,
                continuation_train.astype(bool),
                e_x_test,
            )
            expected_session = probability * mark_prediction
            e_fit_count += fits + mark_fits
            e_constant_probability_folds += constants
            e_constant_mark_folds += mark_constants
        else:
            raise MechanismProbeError("ROLLING_SPLIT_INVALID")

        e_issue_predictions = np.zeros(len(test_rows), dtype=np.float64)
        cursor = 0
        for output_position, issue_row in enumerate(test_rows):
            size = len(e_raw_groups[int(issue_row)])
            e_issue_predictions[output_position] = float(
                np.sum(expected_session[cursor : cursor + size])
            )
            cursor += size
        if cursor != len(expected_session):
            raise MechanismProbeError("FEATURE_LABEL_ALIGNMENT_INVALID")

        a_x_train, a_x_test = _fit_transform_a(
            m2.values,
            m2.nullable_mask,
            fit_rows,
            test_rows,
        )
        count_prediction, count_fits, count_constants = _fit_arrival_count(
            a_x_train,
            arrival_counts[fit_rows],
            a_x_test,
        )
        mark_positive = arrival_counts[fit_rows] > 0
        mark_prediction_a, mark_fits_a, mark_constants_a = _fit_positive_mark(
            a_x_train,
            arrival_marks[fit_rows],
            mark_positive,
            a_x_test,
        )
        a_prediction = count_prediction * mark_prediction_a
        a_fit_count += count_fits + mark_fits_a
        a_constant_count_folds += count_constants
        a_constant_mark_folds += mark_constants_a

        if not np.isfinite(e_issue_predictions).all() or not np.isfinite(
            a_prediction
        ).all():
            raise MechanismProbeError("MODEL_OUTPUT_INVALID")

        predicted_times.append(issue_times[test_rows])
        predicted_days.append(all_day_starts[test_rows])
        existing_truth_out.append(existing_labels[test_rows, horizon_position])
        arrival_truth_out.append(arrival_labels[test_rows, horizon_position])
        e_predictions_out.append(e_issue_predictions)
        a_predictions_out.append(a_prediction)
        continuation_truth_out.append(continuation_test)
        continuation_probability_out.append(probability)
        continuation_mark_truth_out.append(e_test_y)
        continuation_mark_prediction_out.append(mark_prediction)
        arrival_count_truth_out.append(arrival_counts[test_rows])
        arrival_count_prediction_out.append(count_prediction)
        arrival_mark_truth_out.append(arrival_marks[test_rows])
        arrival_mark_prediction_out.append(mark_prediction_a)

    times = np.concatenate(predicted_times).astype(np.int64, copy=False)
    days = np.concatenate(predicted_days).astype(np.int64, copy=False)
    if np.any(np.diff(times) <= 0):
        raise MechanismProbeError("ROLLING_SPLIT_INVALID")
    return _TaskPrediction(
        issue_times=times,
        day_starts=days,
        existing_truth=np.concatenate(existing_truth_out),
        arrival_truth=np.concatenate(arrival_truth_out),
        e_predictions=np.concatenate(e_predictions_out),
        a_predictions=np.concatenate(a_predictions_out),
        continuation_truth=np.concatenate(continuation_truth_out),
        continuation_probability=np.concatenate(continuation_probability_out),
        continuation_mark_truth=np.concatenate(continuation_mark_truth_out),
        continuation_mark_prediction=np.concatenate(continuation_mark_prediction_out),
        arrival_count_truth=np.concatenate(arrival_count_truth_out),
        arrival_count_prediction=np.concatenate(arrival_count_prediction_out),
        arrival_mark_truth=np.concatenate(arrival_mark_truth_out),
        arrival_mark_prediction=np.concatenate(arrival_mark_prediction_out),
        e_fit_count=e_fit_count,
        a_fit_count=a_fit_count,
        e_constant_probability_folds=e_constant_probability_folds,
        e_constant_mark_folds=e_constant_mark_folds,
        a_constant_count_folds=a_constant_count_folds,
        a_constant_mark_folds=a_constant_mark_folds,
    )


def _metrics(truth: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    if truth.ndim != 1 or prediction.shape != truth.shape or not len(truth):
        raise MechanismProbeError("METRIC_INVALID")
    if not np.isfinite(truth).all() or not np.isfinite(prediction).all():
        raise MechanismProbeError("METRIC_INVALID")
    error = prediction - truth
    absolute = np.abs(error)
    denominator = float(np.sum(np.abs(truth)))
    return {
        "n": int(len(truth)),
        "mae_a": float(np.mean(absolute)),
        "rmse_a": float(np.sqrt(np.mean(np.square(error)))),
        "wape_ratio": (
            None
            if denominator <= _ZERO_TOLERANCE
            else float(np.sum(absolute) / denominator)
        ),
        "negative_prediction_count": int(np.sum(prediction < 0)),
    }


def _positive_mark_mae(
    truth: np.ndarray,
    prediction: np.ndarray,
) -> float | None:
    mask = truth > 0
    if not np.any(mask):
        return None
    return float(np.mean(np.abs(prediction[mask] - truth[mask])))


def _continuation_metrics(
    truth: np.ndarray,
    probability: np.ndarray,
) -> dict[str, Any]:
    if truth.shape != probability.shape or truth.ndim != 1:
        raise MechanismProbeError("METRIC_INVALID")
    if not len(truth):
        return {
            "n": 0,
            "brier": None,
            "log_loss": None,
            "calibration": [],
        }
    if not set(np.unique(truth).tolist()).issubset({0.0, 1.0}):
        raise MechanismProbeError("METRIC_INVALID")
    if not np.isfinite(probability).all() or np.any(
        (probability < 0) | (probability > 1)
    ):
        raise MechanismProbeError("METRIC_INVALID")
    calibration: list[dict[str, Any]] = []
    for decile in range(10):
        lower = decile / 10.0
        upper = (decile + 1) / 10.0
        if decile == 9:
            mask = (probability >= lower) & (probability <= upper)
        else:
            mask = (probability >= lower) & (probability < upper)
        if not np.any(mask):
            continue
        calibration.append(
            {
                "decile": decile,
                "n": int(np.sum(mask)),
                "mean_probability": float(np.mean(probability[mask])),
                "observed_rate": float(np.mean(truth[mask])),
            }
        )
    return {
        "n": int(len(truth)),
        "brier": float(brier_score_loss(truth, probability)),
        "log_loss": float(log_loss(truth, probability, labels=[0, 1])),
        "calibration": calibration,
    }


def _poisson_deviance(
    truth: np.ndarray,
    prediction: np.ndarray,
) -> float | None:
    if truth.shape != prediction.shape or truth.ndim != 1 or not len(truth):
        raise MechanismProbeError("METRIC_INVALID")
    if np.any(truth < 0) or np.any(prediction < 0):
        raise MechanismProbeError("METRIC_INVALID")
    if np.any((truth > 0) & (prediction <= 0)):
        return None
    terms = np.empty(len(truth), dtype=np.float64)
    zero = truth == 0
    terms[zero] = 2.0 * prediction[zero]
    positive = ~zero
    terms[positive] = 2.0 * (
        truth[positive] * np.log(truth[positive] / prediction[positive])
        - truth[positive]
        + prediction[positive]
    )
    return float(np.mean(terms))


def _arrival_metrics(
    count_truth: np.ndarray,
    count_prediction: np.ndarray,
    mark_truth: np.ndarray,
    mark_prediction: np.ndarray,
) -> dict[str, Any]:
    return {
        "count_mae": float(np.mean(np.abs(count_prediction - count_truth))),
        "poisson_deviance": _poisson_deviance(count_truth, count_prediction),
        "positive_mark_mae_a": _positive_mark_mae(mark_truth, mark_prediction),
    }


def _branch_signal(
    *,
    pooled_new: float,
    pooled_old: float,
    horizon_wins: int,
    month_wins: int,
) -> str:
    if pooled_new < pooled_old and horizon_wins >= 3 and month_wins >= 3:
        return "STABLE_COMPONENT_SIGNAL"
    if pooled_new < pooled_old:
        return "MIXED_COMPONENT_SIGNAL"
    return "NO_COMPONENT_SIGNAL"


def _primary_decision(
    *,
    ea_pooled: float,
    equal_pooled: float,
    s1_pooled: float,
    horizon_wins: int,
    month_wins: int,
    max_horizon_degradation: float,
    h60_mae: float,
    h60_equal: float,
    e_signal: str,
    a_signal: str,
) -> str:
    if (
        ea_pooled < equal_pooled
        and ea_pooled < s1_pooled
        and horizon_wins >= 3
        and month_wins >= 3
        and max_horizon_degradation <= 0.05
        and h60_mae < h60_equal
    ):
        return "PASS_MECHANISM_PROBE"
    stable_count = sum(
        value == "STABLE_COMPONENT_SIGNAL" for value in (e_signal, a_signal)
    )
    if ea_pooled < s1_pooled or ea_pooled < equal_pooled or stable_count == 1:
        return "MIXED_MECHANISM_PROBE"
    if (
        e_signal == "NO_COMPONENT_SIGNAL"
        and a_signal == "NO_COMPONENT_SIGNAL"
        and ea_pooled >= s1_pooled
        and ea_pooled >= equal_pooled
    ):
        return "STOP_MECHANISM_ROUTE"
    return "MIXED_MECHANISM_PROBE"


def _aggregate_metric(
    records: Sequence[Mapping[str, np.ndarray]],
    truth_key: str,
    prediction_key: str,
) -> dict[str, Any]:
    truth = np.concatenate([record[truth_key] for record in records])
    prediction = np.concatenate([record[prediction_key] for record in records])
    return _metrics(truth, prediction)


def _composition_bin(truth: float, arrival: float) -> str:
    if truth <= _ZERO_TOLERANCE:
        return "total_zero"
    if arrival <= _ZERO_TOLERANCE:
        return "existing_only"
    share = arrival / truth
    if share >= 1.0 - 1e-12:
        return "arrival_only"
    if share < 0.25:
        return "arrival_share_0_25"
    if share < 0.50:
        return "arrival_share_25_50"
    if share < 0.75:
        return "arrival_share_50_75"
    return "arrival_share_75_100"


def _mechanism_diagnostics(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    composition_by_horizon: list[dict[str, Any]] = []
    bin_order = (
        "total_zero",
        "existing_only",
        "arrival_share_0_25",
        "arrival_share_25_50",
        "arrival_share_50_75",
        "arrival_share_75_100",
        "arrival_only",
    )
    for horizon in HORIZONS_MINUTES:
        selected = [record for record in records if record["horizon"] == horizon]
        truth = np.concatenate([record["truth"] for record in selected])
        arrival = np.concatenate([record["arrival_truth"] for record in selected])
        ea = np.concatenate([record["ea"] for record in selected])
        equal = np.concatenate([record["equal"] for record in selected])
        names = np.asarray(
            [
                _composition_bin(float(t), float(a))
                for t, a in zip(truth, arrival, strict=True)
            ],
            dtype=object,
        )
        bins: list[dict[str, Any]] = []
        for name in bin_order:
            mask = names == name
            if not np.any(mask):
                bins.append(
                    {
                        "composition_bin": name,
                        "n": 0,
                        "P1_EA_mae_a": None,
                        "Equal_mae_a": None,
                    }
                )
                continue
            p1_mae = float(np.mean(np.abs(ea[mask] - truth[mask])))
            equal_mae = float(np.mean(np.abs(equal[mask] - truth[mask])))
            bins.append(
                {
                    "composition_bin": name,
                    "n": int(np.sum(mask)),
                    "P1_EA_mae_a": p1_mae,
                    "Equal_mae_a": equal_mae,
                    "P1_EA_minus_equal_mae_a": p1_mae - equal_mae,
                }
            )
        composition_by_horizon.append(
            {"horizon_minutes": horizon, "bins": bins}
        )

    local_hour_rows: list[dict[str, Any]] = []
    for record in records:
        issue_times = record["issue_times"]
        hours = np.asarray(
            [
                datetime.fromtimestamp(int(value), timezone.utc)
                .astimezone(_ZONE)
                .hour
                for value in issue_times
            ],
            dtype=np.int16,
        )
        for hour in range(24):
            mask = hours == hour
            if not np.any(mask):
                continue
            truth = record["truth"][mask]
            ea = record["ea"][mask]
            equal = record["equal"][mask]
            p1_mae = float(np.mean(np.abs(ea - truth)))
            equal_mae = float(np.mean(np.abs(equal - truth)))
            local_hour_rows.append(
                {
                    "month": record["month"],
                    "horizon_minutes": record["horizon"],
                    "local_hour": hour,
                    "n": int(np.sum(mask)),
                    "P1_EA_mae_a": p1_mae,
                    "Equal_mae_a": equal_mae,
                    "P1_EA_minus_equal_mae_a": p1_mae - equal_mae,
                }
            )
    special: list[dict[str, Any]] = []
    for horizon in (30, 60, 120):
        for hour in (7, 9):
            rows = [
                row
                for row in local_hour_rows
                if row["horizon_minutes"] == horizon
                and row["local_hour"] == hour
            ]
            gaps = [float(row["P1_EA_minus_equal_mae_a"]) for row in rows]
            special.append(
                {
                    "horizon_minutes": horizon,
                    "local_hour": hour,
                    "months_present": len(rows),
                    "months_P1_EA_better": sum(gap < 0 for gap in gaps),
                    "months_P1_EA_worse": sum(gap > 0 for gap in gaps),
                    "median_P1_EA_minus_equal_mae_a": (
                        None if not gaps else float(np.median(gaps))
                    ),
                }
            )
    return {
        "composition_by_horizon": composition_by_horizon,
        "month_horizon_local_hour": local_hour_rows,
        "special_07_09": special,
    }


def _write_private_cache(
    *,
    stage: Path,
    month: str,
    horizon: int,
    reference: Mapping[str, np.ndarray],
    task: _TaskPrediction,
) -> tuple[str, str, Mapping[str, np.ndarray]]:
    if not (
        np.array_equal(reference["issue_times"], task.issue_times)
        and np.array_equal(reference["day_start_utc_s"], task.day_starts)
        and np.allclose(
            reference["existing_truth"],
            task.existing_truth,
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
        and np.allclose(
            reference["arrival_truth"],
            task.arrival_truth,
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise MechanismProbeError("COMMON_ROW_IDENTITY_INVALID")
    total_truth = task.existing_truth + task.arrival_truth
    if not np.allclose(
        reference["y_true"],
        total_truth,
        rtol=0.0,
        atol=_RECONSTRUCTION_TOLERANCE_A,
    ):
        raise MechanismProbeError("COMMON_ROW_IDENTITY_INVALID")
    eonly = task.e_predictions + reference["arrival_predictions"]
    aonly = reference["existing_predictions"] + task.a_predictions
    ea = task.e_predictions + task.a_predictions
    arrays = {
        "issue_times": task.issue_times,
        "day_start_utc_s": task.day_starts,
        "y_true": total_truth,
        "existing_truth": task.existing_truth,
        "arrival_truth": task.arrival_truth,
        "m2_predictions": reference["m2_predictions"],
        "m3_predictions": reference["m3_predictions"],
        "equal_predictions": reference["equal_predictions"],
        "s1_existing_predictions": reference["existing_predictions"],
        "s1_arrival_predictions": reference["arrival_predictions"],
        "s1_predictions": reference["structured_predictions"],
        "p1_e_predictions": task.e_predictions,
        "p1_a_predictions": task.a_predictions,
        "p1_eonly_predictions": eonly,
        "p1_aonly_predictions": aonly,
        "p1_ea_predictions": ea,
    }
    if not all(array.shape == (len(task.issue_times),) for array in arrays.values()):
        raise MechanismProbeError("MODEL_OUTPUT_INVALID")
    name = f"{month}_h{horizon:03d}.npz"
    path = stage / name
    np.savez_compressed(path, **arrays)
    return name, _sha256_file(path), MappingProxyType(arrays)


def run_structured_mechanism_probe(
    *,
    authorized: bool,
    interim_root: str | Path,
    processed_root: str | Path,
    baseline_private_run: str | Path,
    structured_private_run: str | Path,
    private_output_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
) -> MechanismProbeRunResult:
    if authorized is not True:
        raise MechanismProbeError("MECHANISM_PROBE_NOT_AUTHORIZED")
    root = Path(repo_root).resolve(strict=True)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    baseline_root = Path(baseline_private_run).resolve(strict=True)
    structured_root = Path(structured_private_run).resolve(strict=True)
    output = Path(private_output_root).resolve(strict=False)
    if output.exists() or any(
        path.is_symlink()
        for path in (interim, processed, baseline_root, structured_root)
    ):
        raise MechanismProbeError("OUTPUT_TOPOLOGY_INVALID")

    _git_semantic_verify(code_commit, repo_root=root)
    expert_protocol = load_development_expert_protocol()
    structured_protocol = load_structured_protocol()
    if expert_protocol.protocol_sha256 != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256:
        raise MechanismProbeError("PROTOCOL_INVALID")
    if structured_protocol.protocol_sha256 != EXPECTED_STRUCTURED_PROTOCOL_SHA256:
        raise MechanismProbeError("PROTOCOL_INVALID")
    if tuple(contract.month for contract in expert_protocol.months) != DEVELOPMENT_MONTHS:
        raise MechanismProbeError("PROTOCOL_INVALID")
    if (
        tuple(contract.month for contract in structured_protocol.months)
        != DEVELOPMENT_MONTHS
    ):
        raise MechanismProbeError("PROTOCOL_INVALID")

    baseline_manifest = _verify_private_manifest(
        baseline_root,
        expected_sha256=EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256,
        schema_version="evcf-jpl-development-expert-private-cache/v1",
        entries_key="files",
    )
    structured_manifest = _verify_private_manifest(
        structured_root,
        expected_sha256=EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256,
        schema_version="evcf-jpl-structured-s1-private-cache/v1",
        entries_key="entries",
    )
    if baseline_manifest.get("protocol_sha256") != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256:
        raise MechanismProbeError("PRIVATE_CACHE_IDENTITY_INVALID")
    if structured_manifest.get("protocol_sha256") != EXPECTED_STRUCTURED_PROTOCOL_SHA256:
        raise MechanismProbeError("PRIVATE_CACHE_IDENTITY_INVALID")

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".evcf-p1-mechanism-", dir=output.parent))
    private_entries: list[dict[str, str]] = []
    task_records: list[dict[str, Any]] = []
    month_summaries: list[Mapping[str, Any]] = []
    total_fit_count = 0

    try:
        for expert_contract, structured_contract in zip(
            expert_protocol.months,
            structured_protocol.months,
            strict=True,
        ):
            if (
                expert_contract.month != structured_contract.month
                or expert_contract.processed_snapshot_sha256
                != structured_contract.processed_snapshot_sha256
            ):
                raise MechanismProbeError("PROTOCOL_INVALID")
            try:
                data = load_month_data(
                    contract=expert_contract,
                    interim_root=interim,
                    processed_root=processed,
                )
            except DevelopmentExpertError as exc:
                raise MechanismProbeError(exc.reason_code) from exc
            month_processed = processed / expert_contract.month
            month_interim = interim / expert_contract.month
            sessions = _load_current_sessions(
                month_interim / "cleaned_sessions.jsonl.gz",
                expected_count=structured_contract.cleaned_session_count,
            )
            contributions = _build_contributions(sessions, data.issue_times)
            existing_labels, arrival_labels, session_maps = _component_labels(
                issue_times=data.issue_times,
                total_labels=data.labels,
                contributions=contributions,
            )
            m3_groups = _load_m3_groups(month_processed, data.issue_times)
            e_raw_groups = _e_raw_groups(data=data, m3_groups=m3_groups)
            month_horizons: list[dict[str, Any]] = []

            for horizon_position, horizon in enumerate(HORIZONS_MINUTES):
                e_labels = _e_label_groups(
                    existing_labels=existing_labels,
                    m3_groups=m3_groups,
                    session_maps=session_maps,
                    horizon_position=horizon_position,
                )
                arrival_counts, arrival_marks = _a_targets(
                    issue_times=data.issue_times,
                    arrival_labels=arrival_labels,
                    contributions=contributions,
                    horizon_position=horizon_position,
                )
                task = _predict_horizon(
                    data=data,
                    existing_labels=existing_labels,
                    arrival_labels=arrival_labels,
                    e_raw_groups=e_raw_groups,
                    e_label_groups=e_labels,
                    arrival_counts=arrival_counts,
                    arrival_marks=arrival_marks,
                    horizon_minutes=horizon,
                    test_start_local_day=expert_protocol.test_start_local_day,
                )
                total_fit_count += task.e_fit_count + task.a_fit_count
                reference = _load_reference_pair(
                    baseline_root=baseline_root,
                    structured_root=structured_root,
                    month=expert_contract.month,
                    horizon=horizon,
                )
                name, digest, arrays = _write_private_cache(
                    stage=stage,
                    month=expert_contract.month,
                    horizon=horizon,
                    reference=reference,
                    task=task,
                )
                private_entries.append({"name": name, "sha256": digest})

                e_metrics = _metrics(task.existing_truth, task.e_predictions)
                s1_e_metrics = _metrics(
                    task.existing_truth,
                    reference["existing_predictions"],
                )
                a_metrics = _metrics(task.arrival_truth, task.a_predictions)
                s1_a_metrics = _metrics(
                    task.arrival_truth,
                    reference["arrival_predictions"],
                )
                equal_metrics = _metrics(
                    arrays["y_true"],
                    arrays["equal_predictions"],
                )
                s1_metrics = _metrics(
                    arrays["y_true"],
                    arrays["s1_predictions"],
                )
                eonly_metrics = _metrics(
                    arrays["y_true"],
                    arrays["p1_eonly_predictions"],
                )
                aonly_metrics = _metrics(
                    arrays["y_true"],
                    arrays["p1_aonly_predictions"],
                )
                ea_metrics = _metrics(
                    arrays["y_true"],
                    arrays["p1_ea_predictions"],
                )
                continuation_metrics = _continuation_metrics(
                    task.continuation_truth,
                    task.continuation_probability,
                )
                continuation_metrics["positive_mark_mae_a"] = _positive_mark_mae(
                    task.continuation_mark_truth,
                    task.continuation_mark_prediction,
                )
                arrival_diagnostics = _arrival_metrics(
                    task.arrival_count_truth,
                    task.arrival_count_prediction,
                    task.arrival_mark_truth,
                    task.arrival_mark_prediction,
                )
                month_horizons.append(
                    {
                        "horizon_minutes": horizon,
                        "test_rows": int(len(task.issue_times)),
                        "fits": {"E": task.e_fit_count, "A": task.a_fit_count},
                        "constant_folds": {
                            "E_probability": task.e_constant_probability_folds,
                            "E_mark": task.e_constant_mark_folds,
                            "A_count": task.a_constant_count_folds,
                            "A_mark": task.a_constant_mark_folds,
                        },
                        "components": {
                            "P1_E": e_metrics,
                            "S1_existing": s1_e_metrics,
                            "P1_A": a_metrics,
                            "S1_arrival": s1_a_metrics,
                        },
                        "totals": {
                            "Equal": equal_metrics,
                            "S1": s1_metrics,
                            "P1_Eonly": eonly_metrics,
                            "P1_Aonly": aonly_metrics,
                            "P1_EA": ea_metrics,
                        },
                        "continuation": continuation_metrics,
                        "arrival_process": arrival_diagnostics,
                    }
                )
                task_records.append(
                    {
                        "month": expert_contract.month,
                        "horizon": horizon,
                        "existing_truth": arrays["existing_truth"],
                        "arrival_truth": arrays["arrival_truth"],
                        "p1_e": arrays["p1_e_predictions"],
                        "s1_e": arrays["s1_existing_predictions"],
                        "p1_a": arrays["p1_a_predictions"],
                        "s1_a": arrays["s1_arrival_predictions"],
                        "truth": arrays["y_true"],
                        "equal": arrays["equal_predictions"],
                        "s1": arrays["s1_predictions"],
                        "eonly": arrays["p1_eonly_predictions"],
                        "aonly": arrays["p1_aonly_predictions"],
                        "ea": arrays["p1_ea_predictions"],
                        "issue_times": arrays["issue_times"],
                        "day_starts": arrays["day_start_utc_s"],
                    }
                )
            month_summaries.append(
                MappingProxyType(
                    {
                        "month": expert_contract.month,
                        "processed_snapshot_sha256": (
                            expert_contract.processed_snapshot_sha256
                        ),
                        "horizons": month_horizons,
                    }
                )
            )

        def select_records(
            *,
            month: str | None = None,
            horizon: int | None = None,
        ) -> list[dict[str, Any]]:
            return [
                record
                for record in task_records
                if (month is None or record["month"] == month)
                and (horizon is None or record["horizon"] == horizon)
            ]

        def total_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
            return {
                "Equal": _aggregate_metric(records, "truth", "equal"),
                "S1": _aggregate_metric(records, "truth", "s1"),
                "P1_Eonly": _aggregate_metric(records, "truth", "eonly"),
                "P1_Aonly": _aggregate_metric(records, "truth", "aonly"),
                "P1_EA": _aggregate_metric(records, "truth", "ea"),
                "components": {
                    "P1_E": _aggregate_metric(
                        records,
                        "existing_truth",
                        "p1_e",
                    ),
                    "S1_existing": _aggregate_metric(
                        records,
                        "existing_truth",
                        "s1_e",
                    ),
                    "P1_A": _aggregate_metric(
                        records,
                        "arrival_truth",
                        "p1_a",
                    ),
                    "S1_arrival": _aggregate_metric(
                        records,
                        "arrival_truth",
                        "s1_a",
                    ),
                },
            }

        pooled_by_horizon: list[Mapping[str, Any]] = []
        for horizon in HORIZONS_MINUTES:
            summary = total_summary(select_records(horizon=horizon))
            pooled_by_horizon.append(
                MappingProxyType({"horizon_minutes": horizon, **summary})
            )
        pooled_by_month: list[Mapping[str, Any]] = []
        for month in DEVELOPMENT_MONTHS:
            summary = total_summary(select_records(month=month))
            pooled_by_month.append(MappingProxyType({"month": month, **summary}))
        pooled_overall = total_summary(task_records)

        e_horizon_wins = sum(
            item["components"]["P1_E"]["mae_a"]
            < item["components"]["S1_existing"]["mae_a"]
            for item in pooled_by_horizon
        )
        a_horizon_wins = sum(
            item["components"]["P1_A"]["mae_a"]
            < item["components"]["S1_arrival"]["mae_a"]
            for item in pooled_by_horizon
        )
        e_month_wins = sum(
            item["components"]["P1_E"]["mae_a"]
            < item["components"]["S1_existing"]["mae_a"]
            for item in pooled_by_month
        )
        a_month_wins = sum(
            item["components"]["P1_A"]["mae_a"]
            < item["components"]["S1_arrival"]["mae_a"]
            for item in pooled_by_month
        )
        e_signal = _branch_signal(
            pooled_new=pooled_overall["components"]["P1_E"]["mae_a"],
            pooled_old=pooled_overall["components"]["S1_existing"]["mae_a"],
            horizon_wins=e_horizon_wins,
            month_wins=e_month_wins,
        )
        a_signal = _branch_signal(
            pooled_new=pooled_overall["components"]["P1_A"]["mae_a"],
            pooled_old=pooled_overall["components"]["S1_arrival"]["mae_a"],
            horizon_wins=a_horizon_wins,
            month_wins=a_month_wins,
        )
        ea_horizon_wins = sum(
            item["P1_EA"]["mae_a"] < item["Equal"]["mae_a"]
            for item in pooled_by_horizon
        )
        ea_month_wins = sum(
            item["P1_EA"]["mae_a"] < item["Equal"]["mae_a"]
            for item in pooled_by_month
        )
        degradations = [
            (
                max(
                    0.0,
                    (item["P1_EA"]["mae_a"] - item["Equal"]["mae_a"])
                    / item["Equal"]["mae_a"],
                )
                if item["Equal"]["mae_a"] > 0
                else 0.0
            )
            for item in pooled_by_horizon
        ]
        h60 = next(
            item for item in pooled_by_horizon if item["horizon_minutes"] == 60
        )
        decision = _primary_decision(
            ea_pooled=pooled_overall["P1_EA"]["mae_a"],
            equal_pooled=pooled_overall["Equal"]["mae_a"],
            s1_pooled=pooled_overall["S1"]["mae_a"],
            horizon_wins=ea_horizon_wins,
            month_wins=ea_month_wins,
            max_horizon_degradation=max(degradations),
            h60_mae=h60["P1_EA"]["mae_a"],
            h60_equal=h60["Equal"]["mae_a"],
            e_signal=e_signal,
            a_signal=a_signal,
        )
        pooled_overall["mechanism_diagnostics"] = _mechanism_diagnostics(
            task_records
        )
        pooled_overall["decision_support"] = {
            "E_horizon_wins": e_horizon_wins,
            "E_month_wins": e_month_wins,
            "A_horizon_wins": a_horizon_wins,
            "A_month_wins": a_month_wins,
            "EA_horizon_wins_vs_equal": ea_horizon_wins,
            "EA_month_wins_vs_equal": ea_month_wins,
            "EA_max_horizon_degradation_fraction": max(degradations),
            "EA_60min_better_than_equal": (
                h60["P1_EA"]["mae_a"] < h60["Equal"]["mae_a"]
            ),
        }

        private_manifest = {
            "schema_version": "evcf-jpl-structured-mechanism-p1-private-cache/v1",
            "code_commit": code_commit,
            "source_expert_protocol_sha256": EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
            "source_structured_protocol_sha256": EXPECTED_STRUCTURED_PROTOCOL_SHA256,
            "source_baseline_private_manifest_sha256": (
                EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256
            ),
            "source_structured_private_manifest_sha256": (
                EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256
            ),
            "holdout_accessed": False,
            "hyperparameter_search": False,
            "entries": sorted(private_entries, key=lambda item: item["name"]),
        }
        manifest_bytes = _canonical_json_bytes(private_manifest)
        (stage / "private_manifest.json").write_bytes(manifest_bytes)
        os.replace(stage, output)
        stage = output
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        return MechanismProbeRunResult(
            status="COMPLETE",
            code_commit=code_commit,
            fit_count=total_fit_count,
            private_cache_file_count=len(private_entries),
            private_manifest_sha256=manifest_sha,
            branch_decisions=MappingProxyType({"E": e_signal, "A": a_signal}),
            decision=decision,
            pooled_overall=MappingProxyType(pooled_overall),
            pooled_by_horizon=tuple(pooled_by_horizon),
            pooled_by_month=tuple(pooled_by_month),
            month_summaries=tuple(month_summaries),
            holdout_accessed=False,
        )
    except BaseException:
        if stage.exists() and stage != output:
            shutil.rmtree(stage, ignore_errors=True)
        raise


__all__ = [
    "DEVELOPMENT_MONTHS",
    "FINAL_HOLDOUT_MONTHS",
    "HORIZONS_MINUTES",
    "MechanismProbeError",
    "MechanismProbeRunResult",
    "run_structured_mechanism_probe",
]
