"""Development-only structured S1 baseline for JPL charging-station current.

S1 changes only the supervised target structure. It reuses the accepted M3 issue-time
features and frozen M3 HGB parameters to predict the contribution of sessions already
connected at prediction issue time, and the accepted M2 features / frozen M2 parameters
to predict the contribution of sessions arriving after issue time. The two predictions
are summed and compared on the exact existing OOS rows against M2, M3, and the fixed
0.5 average.

This module never accesses the final holdout, never retunes branch models, and never
publishes row-level predictions. Future session identity is used only to construct
offline training/evaluation labels.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import yaml

from evcf.forecasting.acn_jpl_development_experts import (
    DevelopmentExpertProtocol,
    EstimatorFactory,
    MonthData,
    load_selected_hgb_parameters,
    predict_task,
)
from evcf.forecasting.acn_jpl_development_experts_compat import (
    DevelopmentExpertError,
    load_development_expert_protocol,
    load_month_data,
)

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
TIMEZONE_NAME = "America/Los_Angeles"
_ZONE = ZoneInfo(TIMEZONE_NAME)

DEFAULT_PROTOCOL_PATH = Path("code/configs/acn_jpl_structured_baseline_2019.yaml")
SOURCE_EXPERT_PROTOCOL_PATH = Path("code/configs/acn_jpl_development_experts_2019.yaml")
EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256 = (
    "02c7809f1113aeaf20723030c96006ee0831b20ff219106da7d6968df535d71a"
)
EXPECTED_SOURCE_MODEL_SELECTION_SHA256 = (
    "a43ac609629d0dfa1568ce19d8e51666cbeb8392d96cbe976927f9397f19cb0d"
)
EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256 = (
    "2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd"
)

IMPLEMENTATION_PATHS = (
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/configs/acn_jpl_structured_baseline_2019.yaml",
    "code/src/evcf/data/acn_jpl_cleaning.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_models.py",
    "code/src/evcf/forecasting/acn_jpl_structured_baseline.py",
    "scripts/run_jpl_structured_baseline.py",
)

_RECONSTRUCTION_TOLERANCE_A = 1e-6


class StructuredBaselineError(RuntimeError):
    """Static path-free failure code safe for aggregate reporting."""

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
class StructuredMonthContract:
    month: str
    cleaned_session_count: int
    processed_snapshot_sha256: str


@dataclass(frozen=True, slots=True)
class StructuredProtocol:
    protocol_id: str
    protocol_sha256: str
    months: tuple[StructuredMonthContract, ...]
    source_expert_protocol_sha256: str
    source_model_selection_sha256: str
    source_private_manifest_sha256: str
    max_horizon_degradation_fraction: float
    minimum_horizon_wins: int
    minimum_month_wins: int
    mixed_minimum_horizon_wins: int
    mixed_minimum_month_wins: int


@dataclass(frozen=True, slots=True)
class _CleanCurrentSession:
    connection_utc_s: int
    disconnect_utc_s: int
    starts: np.ndarray
    ends: np.ndarray
    values: np.ndarray


@dataclass(frozen=True, slots=True)
class StructuredTask:
    month: str
    horizon_minutes: int
    issue_times: np.ndarray
    day_starts: np.ndarray
    y_true: np.ndarray
    existing_truth: np.ndarray
    arrival_truth: np.ndarray
    existing_predictions: np.ndarray
    arrival_predictions: np.ndarray
    structured_predictions: np.ndarray
    existing_fit_count: int
    arrival_fit_count: int
    existing_parameter_sha256: str
    arrival_parameter_sha256: str


@dataclass(frozen=True, slots=True)
class StructuredBaselineRunResult:
    status: str
    protocol_sha256: str
    code_commit: str
    source_expert_protocol_sha256: str
    source_model_selection_sha256: str
    source_private_manifest_sha256: str
    fit_count: int
    private_cache_file_count: int
    private_manifest_sha256: str
    decision: str
    month_summaries: tuple[Mapping[str, Any], ...]
    pooled_by_horizon: tuple[Mapping[str, Any], ...]
    pooled_by_month: tuple[Mapping[str, Any], ...]
    pooled_overall: Mapping[str, Any]
    holdout_accessed: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "evcf-jpl-structured-s1-summary/v1",
            "status": self.status,
            "protocol_sha256": self.protocol_sha256,
            "code_commit": self.code_commit,
            "source_expert_protocol_sha256": self.source_expert_protocol_sha256,
            "source_model_selection_sha256": self.source_model_selection_sha256,
            "source_private_manifest_sha256": self.source_private_manifest_sha256,
            "fit_count": self.fit_count,
            "private_cache_file_count": self.private_cache_file_count,
            "private_manifest_sha256": self.private_manifest_sha256,
            "decision": self.decision,
            "months": [dict(item) for item in self.month_summaries],
            "pooled_by_horizon": [dict(item) for item in self.pooled_by_horizon],
            "pooled_by_month": [dict(item) for item in self.pooled_by_month],
            "pooled_overall": dict(self.pooled_overall),
            "holdout_accessed": self.holdout_accessed,
            "branch_specific_retuning": False,
            "prediction_clipping": False,
            "prediction_calibration": False,
            "hsmm_trained": False,
            "gate_trained": False,
        }


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _validate_sha256(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise StructuredBaselineError("PROTOCOL_INVALID")
    return value


def _exact_mapping(value: object, keys: tuple[str, ...]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or tuple(value) != keys:
        raise StructuredBaselineError("PROTOCOL_INVALID")
    return value


def load_structured_protocol(
    path: str | Path = DEFAULT_PROTOCOL_PATH,
) -> StructuredProtocol:
    source = Path(path)
    try:
        raw = source.read_bytes()
        root = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise StructuredBaselineError("PROTOCOL_INVALID") from exc

    top = _exact_mapping(
        root,
        (
            "schema_version",
            "protocol_id",
            "target",
            "development_months",
            "final_holdout",
            "source_experts",
            "horizons_minutes",
            "component_labels",
            "branches",
            "rolling_origin",
            "prediction",
            "evaluation",
            "decision",
            "publication",
        ),
    )
    if top["schema_version"] != "acn-jpl-structured-baseline-protocol/v1":
        raise StructuredBaselineError("PROTOCOL_INVALID")
    if top["target"] != {"name": "station_current_mean_a", "unit": "A"}:
        raise StructuredBaselineError("PROTOCOL_INVALID")

    month_map = top["development_months"]
    if not isinstance(month_map, Mapping) or tuple(month_map) != DEVELOPMENT_MONTHS:
        raise StructuredBaselineError("PROTOCOL_INVALID")
    months: list[StructuredMonthContract] = []
    for month in DEVELOPMENT_MONTHS:
        item = _exact_mapping(
            month_map[month],
            ("cleaned_session_count", "processed_snapshot_sha256"),
        )
        count = item["cleaned_session_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise StructuredBaselineError("PROTOCOL_INVALID")
        months.append(
            StructuredMonthContract(
                month=month,
                cleaned_session_count=count,
                processed_snapshot_sha256=_validate_sha256(
                    item["processed_snapshot_sha256"]
                ),
            )
        )

    if top["final_holdout"] != {
        "months": list(FINAL_HOLDOUT_MONTHS),
        "access_allowed": False,
    }:
        raise StructuredBaselineError("PROTOCOL_INVALID")

    source_experts = _exact_mapping(
        top["source_experts"],
        (
            "protocol_sha256",
            "model_selection_sha256",
            "private_manifest_sha256",
        ),
    )
    if (
        _validate_sha256(source_experts["protocol_sha256"])
        != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256
        or _validate_sha256(source_experts["model_selection_sha256"])
        != EXPECTED_SOURCE_MODEL_SELECTION_SHA256
        or _validate_sha256(source_experts["private_manifest_sha256"])
        != EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256
    ):
        raise StructuredBaselineError("PROTOCOL_INVALID")

    if top["horizons_minutes"] != list(HORIZONS_MINUTES):
        raise StructuredBaselineError("PROTOCOL_INVALID")
    if top["component_labels"] != {
        "existing_rule": "connection_time_utc_s <= issue_time_utc_s",
        "arrival_rule": "connection_time_utc_s > issue_time_utc_s",
        "target_window": "[issue+h-15min, issue+h)",
        "reconstruction_absolute_tolerance_a": _RECONSTRUCTION_TOLERANCE_A,
    }:
        raise StructuredBaselineError("PROTOCOL_INVALID")
    if top["branches"] != {
        "existing": {
            "input_tier": "M3",
            "target": "existing_session_current",
            "learner": "hgb",
            "parameters": "reuse_source_M3_same_horizon",
        },
        "arrival": {
            "input_tier": "M2",
            "target": "future_arrival_current",
            "learner": "hgb",
            "parameters": "reuse_source_M2_same_horizon",
        },
    }:
        raise StructuredBaselineError("PROTOCOL_INVALID")
    if top["rolling_origin"] != {"inherit_source_expert_protocol": True}:
        raise StructuredBaselineError("PROTOCOL_INVALID")
    if top["prediction"] != {
        "clipping": False,
        "calibration": False,
        "branch_specific_retuning": False,
        "nonnegative_projection_primary": False,
    }:
        raise StructuredBaselineError("PROTOCOL_INVALID")
    if top["evaluation"] != {
        "primary_metric": "MAE",
        "secondary_metrics": ["RMSE", "WAPE"],
        "common_rows_required": True,
        "local_day_aggregates": True,
    }:
        raise StructuredBaselineError("PROTOCOL_INVALID")

    decision = _exact_mapping(top["decision"], ("pass", "mixed", "stop"))
    pass_rule = _exact_mapping(
        decision["pass"],
        (
            "pooled_mae_better_than_M3",
            "pooled_mae_better_than_equal",
            "min_horizons_better_than_equal",
            "min_months_better_than_equal",
            "max_horizon_mae_degradation_vs_equal_fraction",
        ),
    )
    mixed_rule = _exact_mapping(
        decision["mixed"],
        (
            "require_overall_gain_vs_at_least_one_strong_baseline",
            "minimum_horizon_wins",
            "minimum_month_wins",
        ),
    )
    stop_rule = _exact_mapping(
        decision["stop"],
        (
            "stop_if_no_overall_gain_vs_M3_and_equal",
            "stop_if_horizon_wins_at_most",
            "stop_if_month_wins_at_most",
        ),
    )
    if (
        pass_rule["pooled_mae_better_than_M3"] is not True
        or pass_rule["pooled_mae_better_than_equal"] is not True
        or pass_rule["min_horizons_better_than_equal"] != 3
        or pass_rule["min_months_better_than_equal"] != 3
        or float(pass_rule["max_horizon_mae_degradation_vs_equal_fraction"]) != 0.05
        or mixed_rule
        != {
            "require_overall_gain_vs_at_least_one_strong_baseline": True,
            "minimum_horizon_wins": 2,
            "minimum_month_wins": 2,
        }
        or stop_rule
        != {
            "stop_if_no_overall_gain_vs_M3_and_equal": True,
            "stop_if_horizon_wins_at_most": 1,
            "stop_if_month_wins_at_most": 1,
        }
    ):
        raise StructuredBaselineError("PROTOCOL_INVALID")
    if top["publication"] != {
        "aggregate_only": True,
        "private_row_predictions_local_only": True,
        "model_objects_public": False,
        "absolute_paths_public": False,
    }:
        raise StructuredBaselineError("PROTOCOL_INVALID")
    protocol_id = top["protocol_id"]
    if not isinstance(protocol_id, str) or not protocol_id:
        raise StructuredBaselineError("PROTOCOL_INVALID")

    return StructuredProtocol(
        protocol_id=protocol_id,
        protocol_sha256=_sha256_bytes(raw),
        months=tuple(months),
        source_expert_protocol_sha256=source_experts["protocol_sha256"],
        source_model_selection_sha256=source_experts["model_selection_sha256"],
        source_private_manifest_sha256=source_experts["private_manifest_sha256"],
        max_horizon_degradation_fraction=0.05,
        minimum_horizon_wins=3,
        minimum_month_wins=3,
        mixed_minimum_horizon_wins=2,
        mixed_minimum_month_wins=2,
    )


def verify_structured_implementation_commit(
    code_commit: str,
    *,
    repo_root: str | Path,
) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise StructuredBaselineError("IMPLEMENTATION_DRIFT")
    root = Path(repo_root).resolve(strict=True)
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
        encoding="ascii",
        errors="ignore",
    )
    if completed.returncode != 0 or completed.stdout.strip() != code_commit:
        raise StructuredBaselineError("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise StructuredBaselineError("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode != 0:
            raise StructuredBaselineError("IMPLEMENTATION_DRIFT")
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
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if diff.returncode != 0:
        raise StructuredBaselineError("IMPLEMENTATION_DRIFT")


def _load_cleaned_current_sessions(
    path: Path,
    *,
    expected_count: int,
) -> tuple[_CleanCurrentSession, ...]:
    sessions: list[_CleanCurrentSession] = []
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for line in handle:
                if not line.strip():
                    raise StructuredBaselineError("CLEANED_SESSION_INVALID")
                item = json.loads(line)
                if not isinstance(item, Mapping):
                    raise StructuredBaselineError("CLEANED_SESSION_INVALID")
                if item.get("schema_version") != "acn-jpl-clean-session/v1":
                    raise StructuredBaselineError("CLEANED_SESSION_INVALID")
                connection = item.get("connection_utc_s")
                disconnect = item.get("disconnect_utc_s")
                current = item.get("current")
                if (
                    isinstance(connection, bool)
                    or not isinstance(connection, int)
                    or isinstance(disconnect, bool)
                    or not isinstance(disconnect, int)
                    or disconnect <= connection
                    or not isinstance(current, Mapping)
                    or current.get("field_name") != "chargingCurrent"
                ):
                    raise StructuredBaselineError("CLEANED_SESSION_INVALID")
                timestamps = current.get("timestamps_utc_s")
                values = current.get("values")
                ordinals = current.get("raw_ordinals")
                hold_cap = current.get("locf_cap_s")
                if (
                    not isinstance(timestamps, list)
                    or not isinstance(values, list)
                    or not isinstance(ordinals, list)
                    or len(timestamps) != len(values)
                    or len(values) != len(ordinals)
                    or isinstance(hold_cap, bool)
                    or not isinstance(hold_cap, int)
                    or hold_cap <= 0
                ):
                    raise StructuredBaselineError("CLEANED_SESSION_INVALID")
                parsed_times: list[int] = []
                parsed_values: list[float] = []
                previous: int | None = None
                for timestamp, value, ordinal in zip(
                    timestamps, values, ordinals, strict=True
                ):
                    if (
                        isinstance(timestamp, bool)
                        or not isinstance(timestamp, int)
                        or isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or isinstance(ordinal, bool)
                        or not isinstance(ordinal, int)
                    ):
                        raise StructuredBaselineError("CLEANED_SESSION_INVALID")
                    parsed = float(value)
                    if (
                        timestamp < connection
                        or timestamp >= disconnect
                        or not math.isfinite(parsed)
                        or parsed < 0
                        or (previous is not None and timestamp <= previous)
                    ):
                        raise StructuredBaselineError("CLEANED_SESSION_INVALID")
                    parsed_times.append(timestamp)
                    parsed_values.append(parsed)
                    previous = timestamp

                starts = np.asarray(parsed_times, dtype=np.int64)
                signal_values = np.asarray(parsed_values, dtype=np.float64)
                ends = np.empty_like(starts)
                for index, timestamp in enumerate(starts):
                    next_timestamp = (
                        int(starts[index + 1])
                        if index + 1 < len(starts)
                        else disconnect
                    )
                    ends[index] = min(
                        next_timestamp,
                        int(timestamp) + hold_cap,
                        disconnect,
                    )
                keep = ends > starts
                sessions.append(
                    _CleanCurrentSession(
                        connection_utc_s=connection,
                        disconnect_utc_s=disconnect,
                        starts=starts[keep],
                        ends=ends[keep],
                        values=signal_values[keep],
                    )
                )
    except StructuredBaselineError:
        raise
    except (OSError, UnicodeError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise StructuredBaselineError("CLEANED_SESSION_INVALID") from exc

    if len(sessions) != expected_count:
        raise StructuredBaselineError("CLEANED_SESSION_COUNT_INVALID")
    return tuple(
        sorted(
            sessions,
            key=lambda item: (item.connection_utc_s, item.disconnect_utc_s),
        )
    )


def _session_integral(
    session: _CleanCurrentSession,
    start_utc_s: int,
    end_utc_s: int,
) -> float:
    if end_utc_s <= start_utc_s or session.starts.size == 0:
        return 0.0
    index = max(
        0,
        int(np.searchsorted(session.ends, start_utc_s, side="right")),
    )
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


def _component_label_matrices(
    *,
    sessions: tuple[_CleanCurrentSession, ...],
    issue_times: np.ndarray,
    total_labels: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if (
        issue_times.dtype != np.dtype(np.int64)
        or issue_times.ndim != 1
        or total_labels.dtype != np.dtype(np.float64)
        or total_labels.shape != (len(issue_times), len(HORIZONS_MINUTES))
    ):
        raise StructuredBaselineError("COMPONENT_LABEL_INVALID")

    target_starts = {
        int(issue) + horizon * 60 - 900
        for issue in issue_times
        for horizon in HORIZONS_MINUTES
    }
    contributions: dict[int, list[tuple[int, float]]] = {}
    if target_starts:
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
                    _session_integral(
                        session,
                        eligible_start,
                        eligible_end,
                    )
                    / 900.0
                )
                if contribution > 0:
                    contributions.setdefault(start, []).append(
                        (session.connection_utc_s, contribution)
                    )

    for rows in contributions.values():
        rows.sort(key=lambda item: item[0])

    existing = np.zeros_like(total_labels)
    arrival = np.zeros_like(total_labels)
    for row, issue_raw in enumerate(issue_times):
        issue = int(issue_raw)
        for column, horizon in enumerate(HORIZONS_MINUTES):
            start = issue + horizon * 60 - 900
            rows = contributions.get(start, ())
            existing_value = math.fsum(
                value for connection, value in rows if connection <= issue
            )
            arrival_value = math.fsum(
                value for connection, value in rows if connection > issue
            )
            existing[row, column] = existing_value
            arrival[row, column] = arrival_value

    reconstructed = existing + arrival
    absolute = np.abs(reconstructed - total_labels)
    if absolute.size and float(np.max(absolute)) > _RECONSTRUCTION_TOLERANCE_A:
        raise StructuredBaselineError("COMPONENT_RECONSTRUCTION_INVALID")
    if (
        not np.isfinite(existing).all()
        or not np.isfinite(arrival).all()
        or np.any(existing < 0)
        or np.any(arrival < 0)
    ):
        raise StructuredBaselineError("COMPONENT_LABEL_INVALID")
    return existing, arrival


def _component_month_data(
    data: MonthData,
    labels: np.ndarray,
) -> MonthData:
    return MonthData(
        month=data.month,
        issue_times=data.issue_times,
        labels=labels,
        blocks=data.blocks,
        processed_snapshot_sha256=data.processed_snapshot_sha256,
    )


def predict_structured_task(
    *,
    data: MonthData,
    existing_labels: np.ndarray,
    arrival_labels: np.ndarray,
    source_protocol: DevelopmentExpertProtocol,
    selected_params: Mapping[tuple[str, int], Mapping[str, Any]],
    horizon_minutes: int,
    estimator_factory: EstimatorFactory | None = None,
) -> StructuredTask:
    if horizon_minutes not in HORIZONS_MINUTES:
        raise StructuredBaselineError("ROLLING_SPLIT_INVALID")
    existing_data = _component_month_data(data, existing_labels)
    arrival_data = _component_month_data(data, arrival_labels)

    common = {
        "horizon_minutes": horizon_minutes,
        "test_start_local_day": source_protocol.test_start_local_day,
        "native_thread_limit": source_protocol.native_thread_limit,
    }
    existing_kwargs: dict[str, Any] = {
        "data": existing_data,
        "tier": "M3",
        "params": selected_params[("M3", horizon_minutes)],
        "selected_parameter_sha256": source_protocol.selected_parameter_sha256[
            "M3"
        ][horizon_minutes],
        **common,
    }
    arrival_kwargs: dict[str, Any] = {
        "data": arrival_data,
        "tier": "M2",
        "params": selected_params[("M2", horizon_minutes)],
        "selected_parameter_sha256": source_protocol.selected_parameter_sha256[
            "M2"
        ][horizon_minutes],
        **common,
    }
    if estimator_factory is not None:
        existing_kwargs["estimator_factory"] = estimator_factory
        arrival_kwargs["estimator_factory"] = estimator_factory
    try:
        existing_task = predict_task(**existing_kwargs)
        arrival_task = predict_task(**arrival_kwargs)
    except DevelopmentExpertError as exc:
        raise StructuredBaselineError(exc.reason_code) from exc

    position = HORIZONS_MINUTES.index(horizon_minutes)
    if not (
        np.array_equal(existing_task.issue_times, arrival_task.issue_times)
        and np.array_equal(existing_task.day_starts, arrival_task.day_starts)
        and np.allclose(
            existing_task.y_true + arrival_task.y_true,
            data.labels[
                np.searchsorted(data.issue_times, existing_task.issue_times), position
            ],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise StructuredBaselineError("COMMON_ROW_IDENTITY_INVALID")
    structured = existing_task.predictions + arrival_task.predictions
    if structured.shape != existing_task.y_true.shape or not np.isfinite(
        structured
    ).all():
        raise StructuredBaselineError("MODEL_OUTPUT_INVALID")

    return StructuredTask(
        month=data.month,
        horizon_minutes=horizon_minutes,
        issue_times=existing_task.issue_times,
        day_starts=existing_task.day_starts,
        y_true=existing_task.y_true + arrival_task.y_true,
        existing_truth=existing_task.y_true,
        arrival_truth=arrival_task.y_true,
        existing_predictions=existing_task.predictions,
        arrival_predictions=arrival_task.predictions,
        structured_predictions=structured,
        existing_fit_count=existing_task.fit_count,
        arrival_fit_count=arrival_task.fit_count,
        existing_parameter_sha256=existing_task.selected_parameter_sha256,
        arrival_parameter_sha256=arrival_task.selected_parameter_sha256,
    )


def _verify_baseline_private_run(
    root: Path,
    *,
    protocol: StructuredProtocol,
) -> None:
    manifest_path = root / "private_manifest.json"
    if (
        not manifest_path.is_file()
        or manifest_path.is_symlink()
        or _sha256_file(manifest_path) != protocol.source_private_manifest_sha256
    ):
        raise StructuredBaselineError("BASELINE_CACHE_INVALID")
    try:
        document = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StructuredBaselineError("BASELINE_CACHE_INVALID") from exc
    if (
        not isinstance(document, Mapping)
        or document.get("schema_version")
        != "evcf-jpl-development-expert-private-cache/v1"
        or document.get("protocol_sha256")
        != protocol.source_expert_protocol_sha256
        or document.get("source_model_selection_sha256")
        != protocol.source_model_selection_sha256
        or document.get("holdout_accessed") is not False
        or document.get("gate_trained") is not False
    ):
        raise StructuredBaselineError("BASELINE_CACHE_INVALID")
    files = document.get("files")
    expected_names = {
        f"{month}_h{horizon:03d}.npz"
        for month in DEVELOPMENT_MONTHS
        for horizon in HORIZONS_MINUTES
    }
    if not isinstance(files, list) or len(files) != len(expected_names):
        raise StructuredBaselineError("BASELINE_CACHE_INVALID")
    seen: set[str] = set()
    for item in files:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"name", "sha256"}
            or not isinstance(item["name"], str)
            or item["name"] in seen
        ):
            raise StructuredBaselineError("BASELINE_CACHE_INVALID")
        name = item["name"]
        digest = _validate_sha256(item["sha256"])
        path = root / name
        if (
            name not in expected_names
            or not path.is_file()
            or path.is_symlink()
            or _sha256_file(path) != digest
        ):
            raise StructuredBaselineError("BASELINE_CACHE_INVALID")
        seen.add(name)
    if seen != expected_names:
        raise StructuredBaselineError("BASELINE_CACHE_INVALID")


def _load_baseline_cache(
    root: Path,
    *,
    month: str,
    horizon: int,
    expected_issue_times: np.ndarray,
    expected_truth: np.ndarray,
) -> Mapping[str, np.ndarray]:
    path = root / f"{month}_h{horizon:03d}.npz"
    required = {
        "issue_times",
        "day_start_utc_s",
        "y_true",
        "m2_predictions",
        "m3_predictions",
        "equal_predictions",
    }
    if not path.is_file() or path.is_symlink():
        raise StructuredBaselineError("BASELINE_CACHE_INVALID")
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != required:
                raise StructuredBaselineError("BASELINE_CACHE_INVALID")
            arrays = {name: np.asarray(archive[name]) for name in required}
    except (OSError, ValueError) as exc:
        raise StructuredBaselineError("BASELINE_CACHE_INVALID") from exc
    n = len(expected_issue_times)
    if any(array.shape != (n,) for array in arrays.values()):
        raise StructuredBaselineError("BASELINE_CACHE_INVALID")
    if not (
        np.array_equal(arrays["issue_times"], expected_issue_times)
        and np.allclose(
            arrays["y_true"],
            expected_truth,
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise StructuredBaselineError("COMMON_ROW_IDENTITY_INVALID")
    return MappingProxyType(arrays)


def _metrics(truth: np.ndarray, predictions: np.ndarray) -> dict[str, Any]:
    if (
        truth.ndim != 1
        or predictions.shape != truth.shape
        or not len(truth)
        or not np.isfinite(truth).all()
        or not np.isfinite(predictions).all()
    ):
        raise StructuredBaselineError("METRIC_INVALID")
    error = predictions - truth
    absolute = np.abs(error)
    denominator = float(np.sum(np.abs(truth)))
    return {
        "n": len(truth),
        "mae_a": float(np.mean(absolute)),
        "rmse_a": float(np.sqrt(np.mean(np.square(error)))),
        "wape_ratio": None
        if denominator == 0
        else float(np.sum(absolute) / denominator),
        "negative_prediction_count": int(np.sum(predictions < 0)),
    }


def _daily_summary(
    *,
    task: StructuredTask,
    m3: np.ndarray,
    equal: np.ndarray,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for day in np.unique(task.day_starts):
        mask = task.day_starts == day
        local_date = (
            datetime.fromtimestamp(int(day), timezone.utc)
            .astimezone(_ZONE)
            .date()
            .isoformat()
        )
        rows.append(
            {
                "local_date": local_date,
                "n": int(np.sum(mask)),
                "M3_mae_a": _metrics(task.y_true[mask], m3[mask])["mae_a"],
                "equal_mae_a": _metrics(task.y_true[mask], equal[mask])["mae_a"],
                "S1_mae_a": _metrics(
                    task.y_true[mask], task.structured_predictions[mask]
                )["mae_a"],
            }
        )
    return rows


def _improvement_fraction(reference_mae: float, candidate_mae: float) -> float | None:
    return (
        None
        if reference_mae == 0
        else float((reference_mae - candidate_mae) / reference_mae)
    )


def _aggregate_metrics(
    records: list[tuple[np.ndarray, Mapping[str, np.ndarray], np.ndarray]],
) -> dict[str, Mapping[str, Any]]:
    truth = np.concatenate([item[0] for item in records])
    m2 = np.concatenate([item[1]["m2_predictions"] for item in records])
    m3 = np.concatenate([item[1]["m3_predictions"] for item in records])
    equal = np.concatenate([item[1]["equal_predictions"] for item in records])
    s1 = np.concatenate([item[2] for item in records])
    return {
        "M2": _metrics(truth, m2),
        "M3": _metrics(truth, m3),
        "equal": _metrics(truth, equal),
        "S1": _metrics(truth, s1),
    }


def _decision(
    *,
    protocol: StructuredProtocol,
    pooled_overall: Mapping[str, Mapping[str, Any]],
    pooled_by_horizon: tuple[Mapping[str, Any], ...],
    pooled_by_month: tuple[Mapping[str, Any], ...],
) -> dict[str, Any]:
    s1_overall = float(pooled_overall["S1"]["mae_a"])
    m3_overall = float(pooled_overall["M3"]["mae_a"])
    equal_overall = float(pooled_overall["equal"]["mae_a"])
    horizon_wins = sum(
        float(item["metrics"]["S1"]["mae_a"])
        < float(item["metrics"]["equal"]["mae_a"])
        for item in pooled_by_horizon
    )
    month_wins = sum(
        float(item["metrics"]["S1"]["mae_a"])
        < float(item["metrics"]["equal"]["mae_a"])
        for item in pooled_by_month
    )

    degradations: list[float] = []
    for item in pooled_by_horizon:
        equal_mae = float(item["metrics"]["equal"]["mae_a"])
        s1_mae = float(item["metrics"]["S1"]["mae_a"])
        degradation = 0.0 if equal_mae == 0 else (s1_mae - equal_mae) / equal_mae
        degradations.append(degradation)
    max_degradation = max(degradations, default=0.0)

    passed = (
        s1_overall < m3_overall
        and s1_overall < equal_overall
        and horizon_wins >= protocol.minimum_horizon_wins
        and month_wins >= protocol.minimum_month_wins
        and max_degradation <= protocol.max_horizon_degradation_fraction
    )
    no_overall_gain = s1_overall >= m3_overall and s1_overall >= equal_overall
    concentrated = horizon_wins <= 1 or month_wins <= 1
    if passed:
        decision = "PASS_STRUCTURED_SIGNAL"
    elif no_overall_gain or concentrated:
        decision = "STOP_STRUCTURED_ROUTE"
    elif (
        (s1_overall < m3_overall or s1_overall < equal_overall)
        and horizon_wins >= protocol.mixed_minimum_horizon_wins
        and month_wins >= protocol.mixed_minimum_month_wins
    ):
        decision = "MIXED_STRUCTURED_SIGNAL"
    else:
        decision = "STOP_STRUCTURED_ROUTE"
    return {
        "decision": decision,
        "overall_S1_vs_M3_improvement_fraction": _improvement_fraction(
            m3_overall, s1_overall
        ),
        "overall_S1_vs_equal_improvement_fraction": _improvement_fraction(
            equal_overall, s1_overall
        ),
        "horizons_better_than_equal": horizon_wins,
        "months_better_than_equal": month_wins,
        "max_horizon_degradation_vs_equal_fraction": max_degradation,
        "thresholds": {
            "min_horizons_better_than_equal_for_pass": protocol.minimum_horizon_wins,
            "min_months_better_than_equal_for_pass": protocol.minimum_month_wins,
            "max_horizon_degradation_fraction_for_pass": (
                protocol.max_horizon_degradation_fraction
            ),
        },
    }


def _write_private_cache(
    *,
    stage: Path,
    task: StructuredTask,
) -> tuple[str, str]:
    name = f"{task.month}_h{task.horizon_minutes:03d}.npz"
    path = stage / name
    np.savez_compressed(
        path,
        issue_times=task.issue_times,
        day_start_utc_s=task.day_starts,
        y_true=task.y_true,
        existing_truth=task.existing_truth,
        arrival_truth=task.arrival_truth,
        existing_predictions=task.existing_predictions,
        arrival_predictions=task.arrival_predictions,
        structured_predictions=task.structured_predictions,
    )
    return name, _sha256_file(path)


def run_structured_baseline(
    *,
    authorized: bool,
    interim_root: str | Path,
    processed_root: str | Path,
    baseline_private_root: str | Path,
    private_output_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    protocol_path: str | Path = DEFAULT_PROTOCOL_PATH,
    source_expert_protocol_path: str | Path = SOURCE_EXPERT_PROTOCOL_PATH,
    implementation_verifier: Callable[..., None] | None = None,
    estimator_factory: EstimatorFactory | None = None,
) -> StructuredBaselineRunResult:
    if authorized is not True:
        raise StructuredBaselineError("STRUCTURED_RUN_NOT_AUTHORIZED")
    root = Path(repo_root).resolve(strict=True)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    baseline_private = Path(baseline_private_root).resolve(strict=True)
    output = Path(private_output_root).resolve(strict=False)
    if (
        interim.is_symlink()
        or processed.is_symlink()
        or baseline_private.is_symlink()
        or output.exists()
    ):
        raise StructuredBaselineError("OUTPUT_TOPOLOGY_INVALID")
    if any(
        (interim / month).exists() or (processed / month).exists()
        for month in FINAL_HOLDOUT_MONTHS
    ):
        raise StructuredBaselineError("HOLDOUT_PATH_PRESENT")

    verifier = (
        verify_structured_implementation_commit
        if implementation_verifier is None
        else implementation_verifier
    )
    verifier(code_commit, repo_root=root)
    protocol = load_structured_protocol(protocol_path)
    source_protocol = load_development_expert_protocol(source_expert_protocol_path)
    if (
        source_protocol.protocol_sha256 != protocol.source_expert_protocol_sha256
        or source_protocol.source_model_selection_sha256
        != protocol.source_model_selection_sha256
    ):
        raise StructuredBaselineError("SOURCE_EXPERT_IDENTITY_INVALID")
    selected_params = load_selected_hgb_parameters(
        protocol=source_protocol,
        repo_root=root,
    )
    _verify_baseline_private_run(
        baseline_private,
        protocol=protocol,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=".evcf-structured-s1-", dir=output.parent)
    )
    private_entries: list[dict[str, str]] = []
    month_summaries: list[Mapping[str, Any]] = []
    all_records: list[
        tuple[str, int, np.ndarray, Mapping[str, np.ndarray], np.ndarray]
    ] = []
    fit_count = 0

    try:
        source_contracts = {item.month: item for item in source_protocol.months}
        for contract in protocol.months:
            source_contract = source_contracts.get(contract.month)
            if (
                source_contract is None
                or source_contract.processed_snapshot_sha256
                != contract.processed_snapshot_sha256
            ):
                raise StructuredBaselineError("SOURCE_EXPERT_IDENTITY_INVALID")
            data = load_month_data(
                contract=source_contract,
                interim_root=interim,
                processed_root=processed,
            )
            cleaned = _load_cleaned_current_sessions(
                interim / contract.month / "cleaned_sessions.jsonl.gz",
                expected_count=contract.cleaned_session_count,
            )
            existing_labels, arrival_labels = _component_label_matrices(
                sessions=cleaned,
                issue_times=data.issue_times,
                total_labels=data.labels,
            )
            horizon_summaries: list[dict[str, Any]] = []
            for horizon in HORIZONS_MINUTES:
                task = predict_structured_task(
                    data=data,
                    existing_labels=existing_labels,
                    arrival_labels=arrival_labels,
                    source_protocol=source_protocol,
                    selected_params=selected_params,
                    horizon_minutes=horizon,
                    estimator_factory=estimator_factory,
                )
                baseline = _load_baseline_cache(
                    baseline_private,
                    month=contract.month,
                    horizon=horizon,
                    expected_issue_times=task.issue_times,
                    expected_truth=task.y_true,
                )
                fit_count += task.existing_fit_count + task.arrival_fit_count
                name, digest = _write_private_cache(stage=stage, task=task)
                private_entries.append({"name": name, "sha256": digest})

                metrics = {
                    "M2": _metrics(task.y_true, baseline["m2_predictions"]),
                    "M3": _metrics(task.y_true, baseline["m3_predictions"]),
                    "equal": _metrics(task.y_true, baseline["equal_predictions"]),
                    "S1": _metrics(task.y_true, task.structured_predictions),
                    "existing_branch": _metrics(
                        task.existing_truth, task.existing_predictions
                    ),
                    "arrival_branch": _metrics(
                        task.arrival_truth, task.arrival_predictions
                    ),
                }
                horizon_summaries.append(
                    {
                        "horizon_minutes": horizon,
                        "test_rows": len(task.issue_times),
                        "test_days": task.existing_fit_count,
                        "selected_parameter_sha256": {
                            "existing_M3": task.existing_parameter_sha256,
                            "arrival_M2": task.arrival_parameter_sha256,
                        },
                        "metrics": metrics,
                        "S1_mae_improvement_fraction": {
                            "vs_M3": _improvement_fraction(
                                metrics["M3"]["mae_a"], metrics["S1"]["mae_a"]
                            ),
                            "vs_equal": _improvement_fraction(
                                metrics["equal"]["mae_a"], metrics["S1"]["mae_a"]
                            ),
                        },
                        "daily": _daily_summary(
                            task=task,
                            m3=baseline["m3_predictions"],
                            equal=baseline["equal_predictions"],
                        ),
                    }
                )
                all_records.append(
                    (
                        contract.month,
                        horizon,
                        task.y_true,
                        baseline,
                        task.structured_predictions,
                    )
                )
            month_summaries.append(
                MappingProxyType(
                    {
                        "month": contract.month,
                        "processed_snapshot_sha256": contract.processed_snapshot_sha256,
                        "horizons": horizon_summaries,
                    }
                )
            )

        pooled_horizons: list[Mapping[str, Any]] = []
        for horizon in HORIZONS_MINUTES:
            records = [
                (truth, baseline, s1)
                for month, h, truth, baseline, s1 in all_records
                if h == horizon
            ]
            pooled_horizons.append(
                MappingProxyType(
                    {
                        "horizon_minutes": horizon,
                        "metrics": _aggregate_metrics(records),
                    }
                )
            )

        pooled_months: list[Mapping[str, Any]] = []
        for month in DEVELOPMENT_MONTHS:
            records = [
                (truth, baseline, s1)
                for m, _, truth, baseline, s1 in all_records
                if m == month
            ]
            pooled_months.append(
                MappingProxyType(
                    {"month": month, "metrics": _aggregate_metrics(records)}
                )
            )

        pooled_overall = _aggregate_metrics(
            [(truth, baseline, s1) for _, _, truth, baseline, s1 in all_records]
        )
        decision_payload = _decision(
            protocol=protocol,
            pooled_overall=pooled_overall,
            pooled_by_horizon=tuple(pooled_horizons),
            pooled_by_month=tuple(pooled_months),
        )

        private_manifest = {
            "schema_version": "evcf-jpl-structured-s1-private-cache/v1",
            "protocol_sha256": protocol.protocol_sha256,
            "code_commit": code_commit,
            "source_private_manifest_sha256": protocol.source_private_manifest_sha256,
            "entries": private_entries,
        }
        manifest_path = stage / "private_manifest.json"
        manifest_path.write_text(
            json.dumps(
                private_manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            + "\n",
            encoding="ascii",
            newline="\n",
        )
        private_manifest_sha = _sha256_file(manifest_path)
        if output.exists():
            raise StructuredBaselineError("OUTPUT_TOPOLOGY_INVALID")
        shutil.move(str(stage), str(output))

        return StructuredBaselineRunResult(
            status="COMPLETE",
            protocol_sha256=protocol.protocol_sha256,
            code_commit=code_commit,
            source_expert_protocol_sha256=protocol.source_expert_protocol_sha256,
            source_model_selection_sha256=protocol.source_model_selection_sha256,
            source_private_manifest_sha256=protocol.source_private_manifest_sha256,
            fit_count=fit_count,
            private_cache_file_count=len(private_entries),
            private_manifest_sha256=private_manifest_sha,
            decision=decision_payload["decision"],
            month_summaries=tuple(month_summaries),
            pooled_by_horizon=tuple(pooled_horizons),
            pooled_by_month=tuple(pooled_months),
            pooled_overall=MappingProxyType(
                {**pooled_overall, "decision_evidence": decision_payload}
            ),
        )
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage)
        raise
