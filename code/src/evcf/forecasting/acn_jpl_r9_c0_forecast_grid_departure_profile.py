"""Frozen R9-C0 forecast-grid requested-departure profile probe."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

import numpy as np

from evcf.forecasting.acn_jpl_development_experts import MonthData, load_selected_hgb_parameters
from evcf.forecasting.acn_jpl_development_experts_compat import (
    DevelopmentExpertError,
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock
from evcf.forecasting.acn_jpl_r7_c0_departure_arrival import (
    EXPECTED_ROWS_BY_MONTH,
    EXPECTED_ROWS_PER_HORIZON,
    HORIZONS_MINUTES,
    SELECTED_M2_PARAMETER_SHA256,
    _predict_custom_arm,
)
from evcf.forecasting.acn_jpl_r8_c0_horizon_departure_exposure import (
    ARRIVAL_DOMINANT_HORIZONS,
    R8_PROTOCOL_COMMIT,
    _load_m3_groups,
)
from evcf.forecasting.acn_jpl_structured_baseline import (
    _component_label_matrices,
    _load_cleaned_current_sessions,
    _metrics,
    load_structured_protocol,
)
from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
    EXPECTED_STRUCTURED_PROTOCOL_SHA256,
    _load_npz,
    _verify_private_manifest,
)

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
SOURCE_R8_STATUS_SHA256 = (
    "5f69386c62bff1314cc16de94d1667421e872aada739194e41ab41c5f5e2a6fe"
)
SOURCE_R8_DECISION = "NO_STABLE_HORIZON_ALIGNED_ADVANTAGE"
EXPECTED_R8_PRIVATE_MANIFEST_SHA256 = (
    "ec11e3555727259960e355b12ac1867d14adef876fedf2d7580daaa3366ff2d2"
)
R8_REVIEWED_EXECUTABLE = "91ab4a18f776b33e00a439ab10c74fd42a04f9b5"
R9_PROTOCOL_COMMIT = "35ed40105faaa82f0c9d7e6a96f805ffdf4aea35"
EXPECTED_FIT_COUNT = 275
EXPECTED_RECORD_COUNT = 25_375
PROFILE_RAW_WIDTH = 210
PROFILE_ENCODED_WIDTH = 213
MAX_DEGRADATION_FRACTION = 0.05
RECONSTRUCTION_TOLERANCE_A = 1e-6
Progress = Callable[[str], None]

_PROFILE_FEATURE_NAMES = (
    "requested_departure_observed_count",
    "requested_departure_missing_count",
    "requested_departure_overdue_count",
    "requested_departure_bin_0_15_count",
    "requested_departure_bin_15_30_count",
    "requested_departure_bin_30_60_count",
    "requested_departure_bin_60_120_count",
    "requested_departure_bin_120_240_count",
    "requested_departure_beyond_240_count",
)
_CANONICAL_AVAILABILITY_FEATURE_NAMES = (
    "m3_requested_departure_minutes_from_issue_count",
    "m3_requested_departure_minutes_from_issue_missing_count",
)
_EXPECTED_R8_REPLAY = MappingProxyType(
    {
        "base_arrival_mae_a": 23.105151690700726,
        "availability_arrival_mae_a": 23.05575637085551,
        "departure_arrival_mae_a": 22.748690662816003,
        "horizon_exposure_arrival_mae_a": 23.1408646360853,
        "s1_total_mae_a": 28.594881529741027,
        "equal_total_mae_a": 28.91728598859252,
        "availability_total_mae_a": 28.454658943488642,
        "departure_total_mae_a": 28.435454290098633,
        "horizon_exposure_total_mae_a": 28.635877053083146,
    }
)
_R8_REQUIRED_FIELDS = {
    "issue_times",
    "day_start_utc_s",
    "y_true",
    "arrival_truth",
    "base_arrival_predictions",
    "availability_arrival_predictions",
    "departure_arrival_predictions",
    "horizon_exposure_arrival_predictions",
    "s1_existing_predictions",
    "s1_predictions",
    "equal_predictions",
    "total_availability_predictions",
    "total_departure_predictions",
    "total_horizon_exposure_predictions",
}
_REUSED_R8_PATHS = (
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/configs/acn_jpl_structured_baseline_2019.yaml",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_data.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_models.py",
    "code/src/evcf/forecasting/acn_jpl_structured_baseline.py",
    "code/src/evcf/forecasting/acn_jpl_structured_mechanism_probe.py",
    "code/src/evcf/forecasting/acn_jpl_r7_c0_departure_arrival.py",
    "code/src/evcf/forecasting/acn_jpl_r7_d1_departure_attribution.py",
    "code/src/evcf/forecasting/acn_jpl_r8_c0_horizon_departure_exposure.py",
)
_PROTOCOL_PATH = "docs/JPL_R9_C0_FORECAST_GRID_DEPARTURE_PROFILE_PROTOCOL_20260914.md"
_IMPLEMENTATION_PATHS = _REUSED_R8_PATHS + (
    _PROTOCOL_PATH,
    "code/src/evcf/forecasting/acn_jpl_r9_c0_forecast_grid_departure_profile.py",
    "scripts/run_jpl_r9_c0_forecast_grid_departure_profile.py",
)


class R9C0Error(RuntimeError):
    """Static identifier-free failure safe for aggregate publication."""

    def __init__(self, reason_code: str) -> None:
        if (
            not isinstance(reason_code, str)
            or not reason_code
            or not reason_code.replace("_", "").isalnum()
        ):
            reason_code = "UNEXPECTED_ERROR"
        self.reason_code = reason_code
        super().__init__(reason_code)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_sha(repo_root: Path, ref: str, relative: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", f"{ref}:{relative}"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
        encoding="ascii",
        errors="ignore",
    )
    value = completed.stdout.strip()
    if completed.returncode or len(value) != 40:
        raise R9C0Error("IMPLEMENTATION_DRIFT")
    return value


def _git_semantic_verify(code_commit: str, *, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R9C0Error("IMPLEMENTATION_DRIFT")
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
    if head.returncode or head.stdout.strip() != code_commit:
        raise R9C0Error("IMPLEMENTATION_DRIFT")
    for relative in _IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R9C0Error("IMPLEMENTATION_DRIFT")
        if _git_blob_sha(repo_root, code_commit, relative) != _git_blob_sha(
            repo_root, "HEAD", relative
        ):
            raise R9C0Error("IMPLEMENTATION_DRIFT")
    for relative in _REUSED_R8_PATHS:
        if _git_blob_sha(repo_root, code_commit, relative) != _git_blob_sha(
            repo_root, R8_REVIEWED_EXECUTABLE, relative
        ):
            raise R9C0Error("R8_REUSED_IMPLEMENTATION_DRIFT")
    if _git_blob_sha(repo_root, code_commit, _PROTOCOL_PATH) != _git_blob_sha(
        repo_root, R9_PROTOCOL_COMMIT, _PROTOCOL_PATH
    ):
        raise R9C0Error("PROTOCOL_DRIFT")
    diff = subprocess.run(
        ["git", "diff", "--quiet", "--no-ext-diff", code_commit, "--", *_IMPLEMENTATION_PATHS],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if diff.returncode:
        raise R9C0Error("IMPLEMENTATION_DRIFT")


def _forecast_grid_profile_block(
    m2: FeatureBlock,
    m3: FeatureBlock,
    m3_groups: Sequence[Sequence[Mapping[str, Any]]],
) -> FeatureBlock:
    if (
        len(m3_groups) != len(m2.issue_times)
        or not np.array_equal(m2.issue_times, m3.issue_times)
        or len(m2.feature_names) != 201
        or len(m3.feature_names) != 311
        or tuple(m3.feature_names[:201]) != tuple(m2.feature_names)
        or not np.array_equal(m3.values[:, :201], m2.values, equal_nan=True)
        or not np.array_equal(m3.nullable_mask[:201], m2.nullable_mask)
    ):
        raise R9C0Error("FEATURE_ALIGNMENT_INVALID")
    try:
        connected_position = m2.feature_names.index("connected_session_count")
        count_position = m3.feature_names.index(_CANONICAL_AVAILABILITY_FEATURE_NAMES[0])
        missing_position = m3.feature_names.index(_CANONICAL_AVAILABILITY_FEATURE_NAMES[1])
    except ValueError as exc:
        raise R9C0Error("PROFILE_SCHEMA_INVALID") from exc
    if bool(m3.nullable_mask[count_position]) or bool(m3.nullable_mask[missing_position]):
        raise R9C0Error("PROFILE_SCHEMA_INVALID")

    profile_rows: list[list[float]] = []
    for position, group in enumerate(m3_groups):
        finite: list[float] = []
        for row in group:
            value = row.get("requested_departure_minutes_from_issue")
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise R9C0Error("PROFILE_SCHEMA_INVALID")
            parsed = float(value)
            if not np.isfinite(parsed):
                raise R9C0Error("PROFILE_SCHEMA_INVALID")
            finite.append(parsed)

        observed = len(finite)
        missing = len(group) - observed
        overdue = sum(value <= 0.0 for value in finite)
        bin_0_15 = sum(0.0 < value <= 15.0 for value in finite)
        bin_15_30 = sum(15.0 < value <= 30.0 for value in finite)
        bin_30_60 = sum(30.0 < value <= 60.0 for value in finite)
        bin_60_120 = sum(60.0 < value <= 120.0 for value in finite)
        bin_120_240 = sum(120.0 < value <= 240.0 for value in finite)
        beyond_240 = sum(value > 240.0 for value in finite)
        partition = (
            overdue
            + bin_0_15
            + bin_15_30
            + bin_30_60
            + bin_60_120
            + bin_120_240
            + beyond_240
        )
        connected = float(m2.values[position, connected_position])
        canonical_count = float(m3.values[position, count_position])
        canonical_missing = float(m3.values[position, missing_position])
        if (
            partition != observed
            or observed + missing != len(group)
            or not np.isfinite(connected)
            or connected < 0
            or connected != float(len(group))
            or canonical_count != float(observed)
            or canonical_missing != float(missing)
        ):
            raise R9C0Error("PROFILE_IDENTITY_INVALID")
        profile_rows.append(
            [
                float(observed),
                float(missing),
                float(overdue),
                float(bin_0_15),
                float(bin_15_30),
                float(bin_30_60),
                float(bin_60_120),
                float(bin_120_240),
                float(beyond_240),
            ]
        )

    profile = np.asarray(profile_rows, dtype=np.float64)
    if profile.shape != (len(m2.issue_times), 9) or not np.isfinite(profile).all():
        raise R9C0Error("PROFILE_SCHEMA_INVALID")
    values = np.concatenate((m2.values, profile), axis=1)
    nullable = np.concatenate((m2.nullable_mask, np.zeros(9, dtype=np.bool_)))
    names = tuple(m2.feature_names) + _PROFILE_FEATURE_NAMES
    if values.shape[1] != PROFILE_RAW_WIDTH or (
        values.shape[1] + int(np.sum(nullable)) != PROFILE_ENCODED_WIDTH
    ):
        raise R9C0Error("PROFILE_SCHEMA_INVALID")
    try:
        return FeatureBlock(m2.issue_times, values, names, nullable)
    except (TypeError, ValueError) as exc:
        raise R9C0Error("PROFILE_SCHEMA_INVALID") from exc


def _load_r8_reference(root: Path, *, month: str, horizon: int) -> dict[str, np.ndarray]:
    try:
        reference = _load_npz(root / f"{month}_h{horizon:03d}.npz", _R8_REQUIRED_FIELDS)
    except Exception as exc:
        raise R9C0Error("R8_PRIVATE_CACHE_SCHEMA_INVALID") from exc
    expected_n = EXPECTED_ROWS_BY_MONTH[month]
    if any(array.shape != (expected_n,) for array in reference.values()):
        raise R9C0Error("R8_PRIVATE_CACHE_SCHEMA_INVALID")
    if (
        reference["issue_times"].dtype != np.dtype(np.int64)
        or reference["day_start_utc_s"].dtype != np.dtype(np.int64)
        or np.any(np.diff(reference["issue_times"]) <= 0)
    ):
        raise R9C0Error("R8_PRIVATE_CACHE_SCHEMA_INVALID")
    numeric = [
        value for key, value in reference.items() if key not in {"issue_times", "day_start_utc_s"}
    ]
    if not all(np.isfinite(array).all() for array in numeric):
        raise R9C0Error("R8_PRIVATE_CACHE_SCHEMA_INVALID")
    existing = reference["s1_existing_predictions"]
    if not (
        np.allclose(
            existing + reference["base_arrival_predictions"],
            reference["s1_predictions"],
            rtol=0.0,
            atol=RECONSTRUCTION_TOLERANCE_A,
        )
        and np.allclose(
            existing + reference["availability_arrival_predictions"],
            reference["total_availability_predictions"],
            rtol=0.0,
            atol=RECONSTRUCTION_TOLERANCE_A,
        )
        and np.allclose(
            existing + reference["departure_arrival_predictions"],
            reference["total_departure_predictions"],
            rtol=0.0,
            atol=RECONSTRUCTION_TOLERANCE_A,
        )
        and np.allclose(
            existing + reference["horizon_exposure_arrival_predictions"],
            reference["total_horizon_exposure_predictions"],
            rtol=0.0,
            atol=RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise R9C0Error("R8_PRIVATE_CACHE_RECONSTRUCTION_INVALID")
    return reference


def _record(
    *,
    month: str,
    horizon: int,
    reference: Mapping[str, np.ndarray],
    profile_prediction: Mapping[str, Any],
) -> dict[str, Any]:
    expected_n = EXPECTED_ROWS_BY_MONTH[month]
    if (
        len(profile_prediction["issue_times"]) != expected_n
        or not np.array_equal(reference["issue_times"], profile_prediction["issue_times"])
        or not np.array_equal(reference["day_start_utc_s"], profile_prediction["day_starts"])
        or not np.allclose(
            reference["arrival_truth"],
            profile_prediction["truth"],
            rtol=0.0,
            atol=RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise R9C0Error("COMMON_ROW_IDENTITY_INVALID")
    profile_arrival = np.asarray(profile_prediction["predictions"], dtype=np.float64)
    profile_total = np.asarray(reference["s1_existing_predictions"], dtype=np.float64) + profile_arrival
    if not np.isfinite(profile_total).all():
        raise R9C0Error("MODEL_OUTPUT_INVALID")
    return {
        "month": month,
        "horizon": horizon,
        "issue_times": np.asarray(reference["issue_times"], dtype=np.int64),
        "day_starts": np.asarray(reference["day_start_utc_s"], dtype=np.int64),
        "total_truth": np.asarray(reference["y_true"], dtype=np.float64),
        "arrival_truth": np.asarray(reference["arrival_truth"], dtype=np.float64),
        "base_arrival": np.asarray(reference["base_arrival_predictions"], dtype=np.float64),
        "availability_arrival": np.asarray(
            reference["availability_arrival_predictions"], dtype=np.float64
        ),
        "departure_arrival": np.asarray(reference["departure_arrival_predictions"], dtype=np.float64),
        "horizon_exposure_arrival": np.asarray(
            reference["horizon_exposure_arrival_predictions"], dtype=np.float64
        ),
        "profile_arrival": profile_arrival,
        "s1_existing": np.asarray(reference["s1_existing_predictions"], dtype=np.float64),
        "s1_total": np.asarray(reference["s1_predictions"], dtype=np.float64),
        "equal_total": np.asarray(reference["equal_predictions"], dtype=np.float64),
        "availability_total": np.asarray(
            reference["total_availability_predictions"], dtype=np.float64
        ),
        "departure_total": np.asarray(reference["total_departure_predictions"], dtype=np.float64),
        "horizon_exposure_total": np.asarray(
            reference["total_horizon_exposure_predictions"], dtype=np.float64
        ),
        "profile_total": profile_total,
    }


def _summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise R9C0Error("METRIC_INVALID")

    def cat(name: str) -> np.ndarray:
        return np.concatenate([np.asarray(record[name], dtype=np.float64) for record in records])

    arrival_truth = cat("arrival_truth")
    total_truth = cat("total_truth")
    return {
        "arrival": {
            "BaseM2": _metrics(arrival_truth, cat("base_arrival")),
            "DepartureAvailability": _metrics(arrival_truth, cat("availability_arrival")),
            "DepartureAug": _metrics(arrival_truth, cat("departure_arrival")),
            "HorizonExposure": _metrics(arrival_truth, cat("horizon_exposure_arrival")),
            "ForecastGridProfile": _metrics(arrival_truth, cat("profile_arrival")),
        },
        "total": {
            "S1": _metrics(total_truth, cat("s1_total")),
            "Equal": _metrics(total_truth, cat("equal_total")),
            "TotalAvailability": _metrics(total_truth, cat("availability_total")),
            "TotalDeparture": _metrics(total_truth, cat("departure_total")),
            "TotalHorizonExposure": _metrics(total_truth, cat("horizon_exposure_total")),
            "TotalForecastGridProfile": _metrics(total_truth, cat("profile_total")),
        },
    }


def _degradation(reference: float, candidate: float) -> float:
    if reference < 0 or candidate < 0:
        raise R9C0Error("METRIC_INVALID")
    if reference == 0.0:
        if candidate == 0.0:
            return 0.0
        raise R9C0Error("METRIC_INVALID")
    return float((candidate - reference) / reference)


def decide_r9(
    pooled: Mapping[str, Any],
    by_horizon: Sequence[Mapping[str, Any]],
    by_month: Sequence[Mapping[str, Any]],
) -> tuple[str, dict[str, Any]]:
    departure = float(pooled["arrival"]["DepartureAug"]["mae_a"])
    profile = float(pooled["arrival"]["ForecastGridProfile"]["mae_a"])
    r8_exposure = float(pooled["arrival"]["HorizonExposure"]["mae_a"])
    departure_total = float(pooled["total"]["TotalDeparture"]["mae_a"])
    profile_total = float(pooled["total"]["TotalForecastGridProfile"]["mae_a"])
    r8_total = float(pooled["total"]["TotalHorizonExposure"]["mae_a"])
    s1 = float(pooled["total"]["S1"]["mae_a"])
    equal = float(pooled["total"]["Equal"]["mae_a"])

    def wins(items: Sequence[Mapping[str, Any]], group: str, left: str, right: str) -> int:
        return sum(
            float(item[group][left]["mae_a"]) < float(item[group][right]["mae_a"])
            for item in items
        )

    component_horizon_wins = wins(
        by_horizon, "arrival", "ForecastGridProfile", "DepartureAug"
    )
    component_month_wins = wins(by_month, "arrival", "ForecastGridProfile", "DepartureAug")
    total_horizon_wins = wins(
        by_horizon, "total", "TotalForecastGridProfile", "TotalDeparture"
    )
    total_month_wins = wins(by_month, "total", "TotalForecastGridProfile", "TotalDeparture")
    r8_component_horizon_wins = wins(
        by_horizon, "arrival", "ForecastGridProfile", "HorizonExposure"
    )
    r8_component_month_wins = wins(
        by_month, "arrival", "ForecastGridProfile", "HorizonExposure"
    )
    r8_total_horizon_wins = wins(
        by_horizon, "total", "TotalForecastGridProfile", "TotalHorizonExposure"
    )
    r8_total_month_wins = wins(
        by_month, "total", "TotalForecastGridProfile", "TotalHorizonExposure"
    )
    long_horizon_wins = sum(
        float(item["arrival"]["ForecastGridProfile"]["mae_a"])
        < float(item["arrival"]["DepartureAug"]["mae_a"])
        for item in by_horizon
        if int(item["horizon_minutes"]) in ARRIVAL_DOMINANT_HORIZONS
    )
    component_max_degradation = max(
        _degradation(
            float(item["arrival"]["DepartureAug"]["mae_a"]),
            float(item["arrival"]["ForecastGridProfile"]["mae_a"]),
        )
        for item in by_horizon
    )
    total_max_degradation = max(
        _degradation(
            float(item["total"]["TotalDeparture"]["mae_a"]),
            float(item["total"]["TotalForecastGridProfile"]["mae_a"]),
        )
        for item in by_horizon
    )

    stop = (
        component_horizon_wins <= 1
        or component_month_wins <= 1
        or (profile >= departure and profile_total >= departure_total)
    )
    passed = (
        not stop
        and profile < departure
        and component_horizon_wins >= 3
        and component_month_wins >= 3
        and long_horizon_wins >= 2
        and profile_total < departure_total
        and total_horizon_wins >= 3
        and total_month_wins >= 3
        and profile_total < s1
        and profile_total < equal
        and component_max_degradation <= MAX_DEGRADATION_FRACTION
        and total_max_degradation <= MAX_DEGRADATION_FRACTION
    )
    if stop:
        decision = "STOP_DEPARTURE_REPRESENTATION_REFINEMENT"
    elif passed:
        decision = "PASS_FORECAST_GRID_DEPARTURE_PROFILE"
    else:
        decision = "MIXED_FORECAST_GRID_DEPARTURE_PROFILE_SIGNAL"

    support = {
        "component_horizon_wins_vs_DepartureAug": int(component_horizon_wins),
        "component_month_wins_vs_DepartureAug": int(component_month_wins),
        "component_long_horizon_wins_vs_DepartureAug": int(long_horizon_wins),
        "total_horizon_wins_vs_TotalDeparture": int(total_horizon_wins),
        "total_month_wins_vs_TotalDeparture": int(total_month_wins),
        "component_horizon_wins_vs_HorizonExposure": int(r8_component_horizon_wins),
        "component_month_wins_vs_HorizonExposure": int(r8_component_month_wins),
        "total_horizon_wins_vs_TotalHorizonExposure": int(r8_total_horizon_wins),
        "total_month_wins_vs_TotalHorizonExposure": int(r8_total_month_wins),
        "max_component_horizon_degradation_vs_DepartureAug": float(component_max_degradation),
        "max_total_horizon_degradation_vs_TotalDeparture": float(total_max_degradation),
        "pooled_component_improvement_vs_DepartureAug_fraction": (
            None if departure == 0 else float((departure - profile) / departure)
        ),
        "pooled_total_improvement_vs_TotalDeparture_fraction": (
            None if departure_total == 0 else float((departure_total - profile_total) / departure_total)
        ),
        "pooled_component_improvement_vs_HorizonExposure_fraction": (
            None if r8_exposure == 0 else float((r8_exposure - profile) / r8_exposure)
        ),
        "pooled_total_improvement_vs_TotalHorizonExposure_fraction": (
            None if r8_total == 0 else float((r8_total - profile_total) / r8_total)
        ),
        "pooled_total_improvement_vs_S1_fraction": (
            None if s1 == 0 else float((s1 - profile_total) / s1)
        ),
        "pooled_total_improvement_vs_Equal_fraction": (
            None if equal == 0 else float((equal - profile_total) / equal)
        ),
    }
    return decision, support


def _write_private_task(stage: Path, record: Mapping[str, Any]) -> tuple[str, str]:
    name = f"{record['month']}_h{int(record['horizon']):03d}.npz"
    path = stage / name
    np.savez_compressed(
        path,
        issue_times=record["issue_times"],
        day_start_utc_s=record["day_starts"],
        y_true=record["total_truth"],
        arrival_truth=record["arrival_truth"],
        base_arrival_predictions=record["base_arrival"],
        availability_arrival_predictions=record["availability_arrival"],
        departure_arrival_predictions=record["departure_arrival"],
        horizon_exposure_arrival_predictions=record["horizon_exposure_arrival"],
        forecast_grid_profile_arrival_predictions=record["profile_arrival"],
        s1_existing_predictions=record["s1_existing"],
        s1_predictions=record["s1_total"],
        equal_predictions=record["equal_total"],
        total_availability_predictions=record["availability_total"],
        total_departure_predictions=record["departure_total"],
        total_horizon_exposure_predictions=record["horizon_exposure_total"],
        total_forecast_grid_profile_predictions=record["profile_total"],
    )
    return name, _sha256_file(path)


def _assert_r8_replay(pooled: Mapping[str, Any]) -> None:
    observed = {
        "base_arrival_mae_a": float(pooled["arrival"]["BaseM2"]["mae_a"]),
        "availability_arrival_mae_a": float(
            pooled["arrival"]["DepartureAvailability"]["mae_a"]
        ),
        "departure_arrival_mae_a": float(pooled["arrival"]["DepartureAug"]["mae_a"]),
        "horizon_exposure_arrival_mae_a": float(
            pooled["arrival"]["HorizonExposure"]["mae_a"]
        ),
        "s1_total_mae_a": float(pooled["total"]["S1"]["mae_a"]),
        "equal_total_mae_a": float(pooled["total"]["Equal"]["mae_a"]),
        "availability_total_mae_a": float(pooled["total"]["TotalAvailability"]["mae_a"]),
        "departure_total_mae_a": float(pooled["total"]["TotalDeparture"]["mae_a"]),
        "horizon_exposure_total_mae_a": float(
            pooled["total"]["TotalHorizonExposure"]["mae_a"]
        ),
    }
    if any(
        not np.isclose(observed[key], expected, rtol=0.0, atol=1e-10)
        for key, expected in _EXPECTED_R8_REPLAY.items()
    ):
        raise R9C0Error("R8_REPLAY_INVALID")


def run_r9_c0(
    *,
    authorized: bool,
    interim_root: str | Path,
    processed_root: str | Path,
    r8_private_run: str | Path,
    private_output_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    progress: Progress | None = None,
) -> dict[str, Any]:
    if authorized is not True:
        raise R9C0Error("R9_C0_NOT_AUTHORIZED")

    repo = Path(repo_root).resolve(strict=True)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    r8_root = Path(r8_private_run).resolve(strict=True)
    output = Path(private_output_root).resolve(strict=False)
    if output.exists() or any(path.is_symlink() for path in (interim, processed, r8_root)):
        raise R9C0Error("OUTPUT_TOPOLOGY_INVALID")

    _git_semantic_verify(code_commit, repo_root=repo)
    source_protocol = load_development_expert_protocol(
        repo / "code/configs/acn_jpl_development_experts_2019.yaml"
    )
    structured_protocol = load_structured_protocol(
        repo / "code/configs/acn_jpl_structured_baseline_2019.yaml"
    )
    if (
        source_protocol.protocol_sha256 != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256
        or structured_protocol.protocol_sha256 != EXPECTED_STRUCTURED_PROTOCOL_SHA256
        or tuple(contract.month for contract in source_protocol.months) != DEVELOPMENT_MONTHS
        or tuple(contract.month for contract in structured_protocol.months) != DEVELOPMENT_MONTHS
        or source_protocol.test_start_local_day != 18
        or any(
            source_protocol.selected_parameter_sha256["M2"][horizon]
            != SELECTED_M2_PARAMETER_SHA256[horizon]
            for horizon in HORIZONS_MINUTES
        )
    ):
        raise R9C0Error("PROTOCOL_INVALID")

    try:
        r8_manifest = _verify_private_manifest(
            r8_root,
            expected_sha256=EXPECTED_R8_PRIVATE_MANIFEST_SHA256,
            schema_version="evcf-jpl-r8-c0-private-cache/v1",
            entries_key="entries",
        )
    except Exception as exc:
        raise R9C0Error("R8_PRIVATE_CACHE_IDENTITY_INVALID") from exc
    if (
        r8_manifest.get("code_commit") != R8_REVIEWED_EXECUTABLE
        or r8_manifest.get("protocol_commit") != R8_PROTOCOL_COMMIT
        or r8_manifest.get("source_r7_d1_status_sha256")
        != "48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b"
    ):
        raise R9C0Error("R8_PRIVATE_CACHE_IDENTITY_INVALID")

    try:
        selected = load_selected_hgb_parameters(protocol=source_protocol, repo_root=repo)
    except DevelopmentExpertError as exc:
        raise R9C0Error(exc.reason_code) from exc

    source_contracts = {contract.month: contract for contract in source_protocol.months}
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".evcf-r9-c0-", dir=output.parent))
    records: list[dict[str, Any]] = []
    private_entries: list[dict[str, str]] = []
    fit_count = 0
    try:
        for structured_contract in structured_protocol.months:
            month = structured_contract.month
            if month not in DEVELOPMENT_MONTHS:
                raise R9C0Error("HOLDOUT_ACCESS_ATTEMPT")
            source_contract = source_contracts.get(month)
            if (
                source_contract is None
                or source_contract.processed_snapshot_sha256
                != structured_contract.processed_snapshot_sha256
            ):
                raise R9C0Error("PROTOCOL_INVALID")
            try:
                data = load_month_data(
                    contract=source_contract,
                    interim_root=interim,
                    processed_root=processed,
                )
                cleaned = _load_cleaned_current_sessions(
                    interim / month / "cleaned_sessions.jsonl.gz",
                    expected_count=structured_contract.cleaned_session_count,
                )
                _, arrival_labels = _component_label_matrices(
                    sessions=cleaned,
                    issue_times=data.issue_times,
                    total_labels=data.labels,
                )
                m3_groups = _load_m3_groups(processed / month, data.issue_times)
            except Exception as exc:
                reason = getattr(exc, "reason_code", "SOURCE_DATA_INVALID")
                raise R9C0Error(reason) from exc

            arrival_data = MonthData(
                month=data.month,
                issue_times=data.issue_times,
                labels=arrival_labels,
                blocks=data.blocks,
                processed_snapshot_sha256=data.processed_snapshot_sha256,
            )
            profile_block = _forecast_grid_profile_block(
                data.blocks["M2"], data.blocks["M3"], m3_groups
            )
            if progress is not None:
                progress(f"R9_C0_STAGE=MONTH_START; MONTH={month}")
            for horizon in HORIZONS_MINUTES:
                try:
                    prediction = _predict_custom_arm(
                        data=arrival_data,
                        block=profile_block,
                        horizon_minutes=horizon,
                        params=selected[("M2", horizon)],
                        encoded_width=PROFILE_ENCODED_WIDTH,
                        native_thread_limit=source_protocol.native_thread_limit,
                    )
                except Exception as exc:
                    reason = getattr(exc, "reason_code", "MODEL_FIT_FAILED")
                    raise R9C0Error(reason) from exc
                fit_count += int(prediction["fit_count"])
                reference = _load_r8_reference(r8_root, month=month, horizon=horizon)
                record = _record(
                    month=month,
                    horizon=horizon,
                    reference=reference,
                    profile_prediction=prediction,
                )
                name, digest = _write_private_task(stage, record)
                private_entries.append({"name": name, "sha256": digest})
                records.append(record)
                if progress is not None:
                    progress(
                        "R9_C0_STAGE=HORIZON_COMPLETE; "
                        f"MONTH={month}; HORIZON={horizon}; FITS={fit_count}/{EXPECTED_FIT_COUNT}"
                    )
            if progress is not None:
                progress(f"R9_C0_STAGE=MONTH_COMPLETE; MONTH={month}")

        if fit_count != EXPECTED_FIT_COUNT or len(records) != 20 or len(private_entries) != 20:
            raise R9C0Error("FIT_COUNT_INVALID")

        pooled = _summary(records)
        _assert_r8_replay(pooled)
        by_horizon = []
        for horizon in HORIZONS_MINUTES:
            selected_records = [record for record in records if int(record["horizon"]) == horizon]
            summary = _summary(selected_records)
            if int(summary["arrival"]["BaseM2"]["n"]) != EXPECTED_ROWS_PER_HORIZON:
                raise R9C0Error("COMMON_ROW_IDENTITY_INVALID")
            by_horizon.append({"horizon_minutes": horizon, **summary})
        by_month = []
        for month in DEVELOPMENT_MONTHS:
            selected_records = [record for record in records if str(record["month"]) == month]
            summary = _summary(selected_records)
            if int(summary["arrival"]["BaseM2"]["n"]) != EXPECTED_ROWS_BY_MONTH[month] * 5:
                raise R9C0Error("COMMON_ROW_IDENTITY_INVALID")
            by_month.append({"month": month, **summary})
        cells = [
            {"month": record["month"], "horizon_minutes": record["horizon"], **_summary([record])}
            for record in records
        ]
        if int(pooled["arrival"]["BaseM2"]["n"]) != EXPECTED_RECORD_COUNT:
            raise R9C0Error("COMMON_ROW_IDENTITY_INVALID")
        decision, support = decide_r9(pooled, by_horizon, by_month)

        manifest = {
            "schema_version": "evcf-jpl-r9-c0-private-cache/v1",
            "source_r8_status_sha256": SOURCE_R8_STATUS_SHA256,
            "source_r8_private_manifest_sha256": EXPECTED_R8_PRIVATE_MANIFEST_SHA256,
            "code_commit": code_commit,
            "protocol_commit": R9_PROTOCOL_COMMIT,
            "entries": private_entries,
        }
        manifest_path = stage / "private_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
            encoding="ascii",
            newline="\n",
        )
        manifest_sha = _sha256_file(manifest_path)
        stage.replace(output)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return {
        "schema_version": "evcf-jpl-r9-c0-summary/v1",
        "status": "COMPLETE",
        "decision": decision,
        "decision_support": support,
        "code_commit": code_commit,
        "protocol_commit": R9_PROTOCOL_COMMIT,
        "source_r8_status_sha256": SOURCE_R8_STATUS_SHA256,
        "source_r8_decision": SOURCE_R8_DECISION,
        "source_r8_decision_unchanged": True,
        "source_r8_private_manifest_sha256": EXPECTED_R8_PRIVATE_MANIFEST_SHA256,
        "r8_reviewed_executable": R8_REVIEWED_EXECUTABLE,
        "fit_count": fit_count,
        "model_fit_attempted": True,
        "private_cache_file_count": len(private_entries),
        "private_manifest_sha256": manifest_sha,
        "pooled_overall": pooled,
        "pooled_by_horizon": by_horizon,
        "pooled_by_month": by_month,
        "month_horizon_cells": cells,
        "holdout_accessed": False,
        "reference_models_retrained": False,
        "r8_references_retrained": False,
        "hyperparameter_search": False,
        "feature_search": False,
        "data_driven_bins": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "gate_trained": False,
        "moe_trained": False,
        "neural_model_trained": False,
        "survival_model_trained": False,
        "tpp_model_trained": False,
        "current_weighted_departure_feature": False,
        "pilot_weighted_departure_feature": False,
        "energy_weighted_departure_feature": False,
        "actual_disconnect_predictor": False,
        "actual_done_charging_predictor": False,
    }
