"""Frozen R4-I0 issue-time information-sufficiency / state-aliasing gate."""

from __future__ import annotations

import math
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from evcf.forecasting.acn_jpl_development_experts_compat import (
    DevelopmentExpertError,
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_gate1_models import RidgePreprocessor
from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
)

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
TIMEZONE_NAME = "America/Los_Angeles"
_ZONE = ZoneInfo(TIMEZONE_NAME)

M2_RAW_WIDTH = 201
M2_ENCODED_WIDTH = 204
M3_RAW_WIDTH = 311
M3_ENCODED_WIDTH = 391
STATION_CURRENT_FEATURE = "station_current_a"
MIN_CANDIDATES = 10
K_ANALOGS = 3
SUPPORT_QUANTILE = 0.95
MIN_POOLED_SUPPORT_FRACTION = 0.70
MIN_CELL_SUPPORT_FRACTION = 0.50
MIN_CELL_SUPPORTED_RECORDS = 250

PROTOCOL_MERGE_COMMIT = "fec13c28cb5d4b2490256f8a26d82f45d8af6051"

IMPLEMENTATION_PATHS = (
    "docs/JPL_R4_I0_INFORMATION_SUFFICIENCY_PROTOCOL_20260913.md",
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_data.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_models.py",
    "code/src/evcf/forecasting/acn_jpl_r4_information_sufficiency_gate.py",
    "scripts/run_jpl_r4_information_sufficiency_gate.py",
)

Progress = Callable[[str], None]


class R4I0Error(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = (
            reason_code
            if isinstance(reason_code, str)
            and reason_code
            and reason_code.replace("_", "").isalnum()
            else "UNEXPECTED_ERROR"
        )
        super().__init__(self.reason_code)


@dataclass(frozen=True, slots=True)
class AnalogSelection:
    level_rows: np.ndarray
    m2_rows: np.ndarray
    m3_rows: np.ndarray
    supported: bool
    candidate_count: int
    test_third_m3_distance: float
    historical_q95_m3_distance: float
    distance_ratio: float | None


@dataclass(frozen=True, slots=True)
class Result:
    code_commit: str
    decision: str
    decision_support: Mapping[str, Any]
    pooled: Mapping[str, Any] | None
    by_horizon: tuple[Mapping[str, Any], ...]
    by_month: tuple[Mapping[str, Any], ...]
    cells: tuple[Mapping[str, Any], ...]
    support: Mapping[str, Any]
    preprocessor_fit_count: int

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "evcf-jpl-r4-i0-information-sufficiency-summary/v1",
            "status": "COMPLETE",
            "code_commit": self.code_commit,
            "protocol_merge_commit": PROTOCOL_MERGE_COMMIT,
            "decision": self.decision,
            "decision_support": dict(self.decision_support),
            "pooled_overall": None if self.pooled is None else dict(self.pooled),
            "pooled_by_horizon": [dict(item) for item in self.by_horizon],
            "pooled_by_month": [dict(item) for item in self.by_month],
            "month_horizon_cells": [dict(item) for item in self.cells],
            "support": dict(self.support),
            "preprocessor_fit_count": self.preprocessor_fit_count,
            "fit_count": 0,
            "model_fit_attempted": False,
            "reference_models_retrained": False,
            "holdout_accessed": False,
            "hyperparameter_search": False,
            "prediction_clipping": False,
            "prediction_calibration": False,
            "target_informed_matching": False,
            "pca_or_metric_learning": False,
            "nearest_neighbor_forecast_trained": False,
            "causal_claim": False,
        }


def _verify_git(code_commit: str, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R4I0Error("IMPLEMENTATION_DRIFT")
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
        raise R4I0Error("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R4I0Error("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode:
            raise R4I0Error("IMPLEMENTATION_DRIFT")
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
    if diff.returncode:
        raise R4I0Error("IMPLEMENTATION_DRIFT")


def _local_midnight(epoch_seconds: int) -> int:
    local = datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(_ZONE)
    return int(datetime.combine(local.date(), time.min, tzinfo=_ZONE).timestamp())


def _local_clock_slot(epoch_seconds: int) -> int:
    local = datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(_ZONE)
    if local.minute not in (0, 15, 30, 45) or local.second != 0:
        raise R4I0Error("ISSUE_TIME_GRID_INVALID")
    return local.hour * 4 + local.minute // 15


def rms_distances(test_vector: np.ndarray, candidates: np.ndarray) -> np.ndarray:
    test = np.asarray(test_vector, dtype=np.float64)
    values = np.asarray(candidates, dtype=np.float64)
    if test.ndim != 1 or values.ndim != 2 or values.shape[1] != len(test):
        raise R4I0Error("DISTANCE_INPUT_INVALID")
    if not np.isfinite(test).all() or not np.isfinite(values).all():
        raise R4I0Error("DISTANCE_INPUT_INVALID")
    distances = np.sqrt(np.mean(np.square(values - test), axis=1))
    if not np.isfinite(distances).all():
        raise R4I0Error("DISTANCE_INVALID")
    return distances


def select_top_k(
    distances: np.ndarray,
    candidate_issue_times: np.ndarray,
    *,
    k: int = K_ANALOGS,
) -> np.ndarray:
    values = np.asarray(distances, dtype=np.float64)
    issues = np.asarray(candidate_issue_times, dtype=np.int64)
    if values.ndim != 1 or issues.shape != values.shape or len(values) < k:
        raise R4I0Error("ANALOG_SELECTION_INVALID")
    if not np.isfinite(values).all() or k <= 0:
        raise R4I0Error("ANALOG_SELECTION_INVALID")
    order = np.lexsort((issues, values))
    return order[:k].astype(np.int64)


def historical_third_neighbor_threshold(candidate_m3: np.ndarray) -> tuple[float, np.ndarray]:
    values = np.asarray(candidate_m3, dtype=np.float64)
    if values.ndim != 2 or len(values) < MIN_CANDIDATES or not np.isfinite(values).all():
        raise R4I0Error("SUPPORT_CALIBRATION_INVALID")
    diff = values[:, None, :] - values[None, :, :]
    pairwise = np.sqrt(np.mean(np.square(diff), axis=2))
    np.fill_diagonal(pairwise, np.inf)
    third = np.partition(pairwise, K_ANALOGS - 1, axis=1)[:, K_ANALOGS - 1]
    if not np.isfinite(third).all():
        raise R4I0Error("SUPPORT_CALIBRATION_INVALID")
    threshold = float(np.quantile(third, SUPPORT_QUANTILE, method="higher"))
    if not math.isfinite(threshold) or threshold < 0:
        raise R4I0Error("SUPPORT_CALIBRATION_INVALID")
    return threshold, third


def select_analogs(
    *,
    candidate_issue_times: np.ndarray,
    candidate_level: np.ndarray,
    test_level: float,
    candidate_m2: np.ndarray,
    test_m2: np.ndarray,
    candidate_m3: np.ndarray,
    test_m3: np.ndarray,
) -> AnalogSelection:
    issues = np.asarray(candidate_issue_times, dtype=np.int64)
    level = np.asarray(candidate_level, dtype=np.float64)
    if len(issues) < MIN_CANDIDATES or level.shape != issues.shape:
        return AnalogSelection(
            level_rows=np.empty(0, dtype=np.int64),
            m2_rows=np.empty(0, dtype=np.int64),
            m3_rows=np.empty(0, dtype=np.int64),
            supported=False,
            candidate_count=len(issues),
            test_third_m3_distance=float("nan"),
            historical_q95_m3_distance=float("nan"),
            distance_ratio=None,
        )
    if not math.isfinite(float(test_level)) or not np.isfinite(level).all():
        raise R4I0Error("ANALOG_SELECTION_INVALID")
    level_distances = np.abs(level - float(test_level))
    m2_distances = rms_distances(test_m2, candidate_m2)
    m3_distances = rms_distances(test_m3, candidate_m3)
    level_rows = select_top_k(level_distances, issues)
    m2_rows = select_top_k(m2_distances, issues)
    m3_rows = select_top_k(m3_distances, issues)
    threshold, _ = historical_third_neighbor_threshold(candidate_m3)
    ordered_m3 = np.sort(m3_distances)
    test_third = float(ordered_m3[K_ANALOGS - 1])
    supported = bool(test_third <= threshold)
    if supported:
        ratio = 0.0 if threshold == 0.0 else float(test_third / threshold)
    else:
        ratio = None
    return AnalogSelection(
        level_rows=level_rows,
        m2_rows=m2_rows,
        m3_rows=m3_rows,
        supported=supported,
        candidate_count=len(issues),
        test_third_m3_distance=test_third,
        historical_q95_m3_distance=threshold,
        distance_ratio=ratio,
    )


def analog_divergence(test_target: float, analog_targets: np.ndarray) -> float:
    target = float(test_target)
    values = np.asarray(analog_targets, dtype=np.float64)
    if values.shape != (K_ANALOGS,) or not math.isfinite(target) or not np.isfinite(values).all():
        raise R4I0Error("TARGET_DIVERGENCE_INVALID")
    return float(np.mean(np.abs(values - target)))


def _distance_support_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    required = (
        "candidate_count",
        "test_third_m3_distance",
        "historical_q95_m3_distance",
    )
    if not all(all(key in item for key in required) for item in records):
        return {}
    candidate_counts = np.asarray(
        [float(item["candidate_count"]) for item in records], dtype=np.float64
    )
    test_third = np.asarray(
        [float(item["test_third_m3_distance"]) for item in records], dtype=np.float64
    )
    historical_q95 = np.asarray(
        [float(item["historical_q95_m3_distance"]) for item in records], dtype=np.float64
    )
    if (
        not np.isfinite(candidate_counts).all()
        or not np.isfinite(test_third).all()
        or not np.isfinite(historical_q95).all()
        or np.any(candidate_counts < MIN_CANDIDATES)
        or np.any(candidate_counts != np.floor(candidate_counts))
        or np.any(test_third < 0.0)
        or np.any(historical_q95 < 0.0)
    ):
        raise R4I0Error("DISTANCE_SUPPORT_SUMMARY_INVALID")
    return {
        "candidate_count_min": int(np.min(candidate_counts)),
        "candidate_count_mean": float(np.mean(candidate_counts)),
        "candidate_count_median": float(np.median(candidate_counts)),
        "candidate_count_max": int(np.max(candidate_counts)),
        "test_third_m3_distance_mean": float(np.mean(test_third)),
        "test_third_m3_distance_median": float(np.median(test_third)),
        "test_third_m3_distance_p95": float(
            np.quantile(test_third, 0.95, method="higher")
        ),
        "historical_q95_m3_distance_mean": float(np.mean(historical_q95)),
        "historical_q95_m3_distance_median": float(np.median(historical_q95)),
        "historical_q95_m3_distance_p95": float(
            np.quantile(historical_q95, 0.95, method="higher")
        ),
    }


def _aggregate(records: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    d_level = np.asarray([float(item["d_level_a"]) for item in records])
    d_m2 = np.asarray([float(item["d_m2_a"]) for item in records])
    d_m3 = np.asarray([float(item["d_m3_a"]) for item in records])
    y_abs = np.asarray([float(item["y_abs_a"]) for item in records])
    ratios = np.asarray([float(item["distance_ratio"]) for item in records])
    if not (
        np.isfinite(d_level).all()
        and np.isfinite(d_m2).all()
        and np.isfinite(d_m3).all()
        and np.isfinite(y_abs).all()
        and np.isfinite(ratios).all()
    ):
        raise R4I0Error("AGGREGATE_INVALID")
    g_level = float(np.mean(d_level))
    g_m2 = float(np.mean(d_m2))
    g_m3 = float(np.mean(d_m3))
    y_scale = float(np.mean(y_abs))
    if g_level <= 0 or g_m2 <= 0 or y_scale <= 0:
        raise R4I0Error("AGGREGATE_DENOMINATOR_INVALID")
    return {
        "supported_records": len(records),
        "G_level_a": g_level,
        "G_M2_a": g_m2,
        "G_M3_a": g_m3,
        "Y_scale_a": y_scale,
        "skill_M2_vs_Level": float(1.0 - g_m2 / g_level),
        "skill_M3_vs_Level": float(1.0 - g_m3 / g_level),
        "skill_M3_vs_M2": float(1.0 - g_m3 / g_m2),
        "normalized_M3_divergence": float(g_m3 / y_scale),
        "distance_ratio_mean": float(np.mean(ratios)),
        "distance_ratio_median": float(np.median(ratios)),
        "distance_ratio_p95": float(np.quantile(ratios, 0.95, method="higher")),
        **_distance_support_summary(records),
    }


def _metric(row: Mapping[str, Any] | None, key: str) -> float:
    if row is None or key not in row:
        raise R4I0Error("DECISION_INPUT_INVALID")
    value = float(row[key])
    if not math.isfinite(value):
        raise R4I0Error("DECISION_INPUT_INVALID")
    return value


def decide(
    *,
    support: Mapping[str, Any],
    pooled: Mapping[str, Any] | None,
    by_horizon: Sequence[Mapping[str, Any]],
    by_month: Sequence[Mapping[str, Any]],
) -> tuple[str, dict[str, Any]]:
    support_pass = bool(support["support_pass"])
    decision_support: dict[str, Any] = {
        "support_pass": support_pass,
        "pooled_supported_fraction": float(support["pooled_supported_fraction"]),
    }
    if not support_pass:
        return "STOP_STATE_ALIASING_ROUTE", {
            **decision_support,
            "stop_reason": "INSUFFICIENT_ANALOG_SUPPORT",
        }

    norm = _metric(pooled, "normalized_M3_divergence")
    m2_skill = _metric(pooled, "skill_M2_vs_Level")
    m3_skill = _metric(pooled, "skill_M3_vs_Level")
    m3_m2_skill = _metric(pooled, "skill_M3_vs_M2")

    h_norm_material = sum(
        _metric(row, "normalized_M3_divergence") >= 0.08 for row in by_horizon
    )
    h_norm_small = sum(
        _metric(row, "normalized_M3_divergence") < 0.08 for row in by_horizon
    )
    h_m2_ge10 = sum(_metric(row, "skill_M2_vs_Level") >= 0.10 for row in by_horizon)
    h_m3_ge10 = sum(_metric(row, "skill_M3_vs_Level") >= 0.10 for row in by_horizon)
    h_m2_ge05 = sum(_metric(row, "skill_M2_vs_Level") >= 0.05 for row in by_horizon)
    h_m3_ge05 = sum(_metric(row, "skill_M3_vs_Level") >= 0.05 for row in by_horizon)
    m_m2_ge10 = sum(_metric(row, "skill_M2_vs_Level") >= 0.10 for row in by_month)
    m_m3_ge10 = sum(_metric(row, "skill_M3_vs_Level") >= 0.10 for row in by_month)
    m_m2_ge05 = sum(_metric(row, "skill_M2_vs_Level") >= 0.05 for row in by_month)
    m_m3_ge05 = sum(_metric(row, "skill_M3_vs_Level") >= 0.05 for row in by_month)
    h60 = next((row for row in by_horizon if int(row["horizon_minutes"]) == 60), None)
    m2_60 = _metric(h60, "skill_M2_vs_Level")
    m3_60 = _metric(h60, "skill_M3_vs_Level")
    norm_60 = _metric(h60, "normalized_M3_divergence")

    decision_support.update(
        {
            "pooled_normalized_M3_divergence": norm,
            "pooled_skill_M2_vs_Level": m2_skill,
            "pooled_skill_M3_vs_Level": m3_skill,
            "pooled_skill_M3_vs_M2": m3_m2_skill,
            "horizons_normalized_M3_ge_0_08": int(h_norm_material),
            "horizons_normalized_M3_lt_0_08": int(h_norm_small),
            "horizons_M2_skill_ge_0_10": int(h_m2_ge10),
            "horizons_M3_skill_ge_0_10": int(h_m3_ge10),
            "horizons_M2_skill_ge_0_05": int(h_m2_ge05),
            "horizons_M3_skill_ge_0_05": int(h_m3_ge05),
            "months_M2_skill_ge_0_10": int(m_m2_ge10),
            "months_M3_skill_ge_0_10": int(m_m3_ge10),
            "months_M2_skill_ge_0_05": int(m_m2_ge05),
            "months_M3_skill_ge_0_05": int(m_m3_ge05),
            "M2_skill_60min": m2_60,
            "M3_skill_60min": m3_60,
            "normalized_M3_60min": norm_60,
        }
    )

    pass_aliasing = bool(
        norm >= 0.10
        and h_norm_material >= 3
        and m2_skill <= 0.05
        and m3_skill <= 0.05
        and m3_m2_skill <= 0.02
        and h_m2_ge10 <= 1
        and h_m3_ge10 <= 1
        and m_m2_ge10 <= 1
        and m_m3_ge10 <= 1
        and m2_60 <= 0.05
        and m3_60 <= 0.05
        and norm_60 >= 0.10
    )
    if pass_aliasing:
        return "PASS_STATE_ALIASING_SIGNAL", {
            **decision_support,
            "stop_reason": None,
        }

    m2_resolves = bool(
        m2_skill >= 0.10 and h_m2_ge05 >= 3 and m_m2_ge05 >= 3 and m2_60 >= 0.05
    )
    if m2_resolves:
        return "STOP_STATE_ALIASING_ROUTE", {
            **decision_support,
            "stop_reason": "M2_STATE_RESOLVES_DIVERGENCE",
        }
    m3_resolves = bool(
        m3_skill >= 0.10 and h_m3_ge05 >= 3 and m_m3_ge05 >= 3 and m3_60 >= 0.05
    )
    if m3_resolves:
        return "STOP_STATE_ALIASING_ROUTE", {
            **decision_support,
            "stop_reason": "M3_STATE_RESOLVES_DIVERGENCE",
        }
    if norm < 0.05 and h_norm_small >= 4:
        return "STOP_STATE_ALIASING_ROUTE", {
            **decision_support,
            "stop_reason": "M3_FUTURE_DIVERGENCE_SMALL",
        }
    return "MIXED_STATE_ALIASING_SIGNAL", {
        **decision_support,
        "stop_reason": None,
    }


def _clock_slots(issue_times: np.ndarray) -> np.ndarray:
    return np.asarray([_local_clock_slot(int(value)) for value in issue_times], dtype=np.int16)


def _day_starts(issue_times: np.ndarray) -> np.ndarray:
    return np.asarray([_local_midnight(int(value)) for value in issue_times], dtype=np.int64)


def run_gate(
    *,
    interim_root: str | Path,
    processed_root: str | Path,
    code_commit: str,
    repo_root: str | Path,
    progress: Progress | None = None,
) -> Result:
    repo = Path(repo_root).resolve(strict=True)
    _verify_git(code_commit, repo)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    protocol = load_development_expert_protocol(
        repo / "code/configs/acn_jpl_development_experts_2019.yaml"
    )
    if protocol.protocol_sha256 != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256:
        raise R4I0Error("PROTOCOL_INVALID")

    records: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    total_oos = 0
    total_supported = 0
    preprocessor_fit_count = 0

    for contract in protocol.months:
        if contract.month not in DEVELOPMENT_MONTHS:
            raise R4I0Error("HOLDOUT_ACCESS_ATTEMPT")
        try:
            data = load_month_data(
                contract=contract,
                interim_root=interim,
                processed_root=processed,
            )
        except DevelopmentExpertError as exc:
            raise R4I0Error(exc.reason_code) from exc

        m2 = data.blocks["M2"]
        m3 = data.blocks["M3"]
        if m2.values.shape[1] != M2_RAW_WIDTH or m3.values.shape[1] != M3_RAW_WIDTH:
            raise R4I0Error("STATE_WIDTH_INVALID")
        try:
            station_index = m2.feature_names.index(STATION_CURRENT_FEATURE)
        except ValueError as exc:
            raise R4I0Error("STATE_SCHEMA_INVALID") from exc

        issue_times = np.asarray(data.issue_times, dtype=np.int64)
        labels = np.asarray(data.labels, dtype=np.float64)
        if labels.shape != (len(issue_times), len(HORIZONS_MINUTES)):
            raise R4I0Error("TARGET_SCHEMA_INVALID")
        if not np.isfinite(labels).all():
            raise R4I0Error("TARGET_SCHEMA_INVALID")
        day_starts = _day_starts(issue_times)
        clock_slots = _clock_slots(issue_times)
        local_days = np.asarray(
            [datetime.fromtimestamp(int(value), timezone.utc).astimezone(_ZONE).day for value in issue_times],
            dtype=np.int16,
        )
        test_days = np.unique(day_starts[local_days >= protocol.test_start_local_day])

        for horizon_position, horizon in enumerate(HORIZONS_MINUTES):
            cell_total = 0
            cell_supported = 0
            cell_records: list[dict[str, Any]] = []
            unsupported_candidates = 0
            unsupported_distance = 0

            for day_start in test_days:
                eligible = np.flatnonzero(issue_times + horizon * 60 <= int(day_start)).astype(np.int64)
                test_rows = np.flatnonzero(day_starts == int(day_start)).astype(np.int64)
                if not len(eligible) or not len(test_rows) or np.intersect1d(eligible, test_rows).size:
                    raise R4I0Error("ROLLING_SPLIT_INVALID")

                m2_pre = RidgePreprocessor().fit(m2, eligible)
                m3_pre = RidgePreprocessor().fit(m3, eligible)
                preprocessor_fit_count += 2
                m2_history = m2_pre.transform(m2, eligible)
                m3_history = m3_pre.transform(m3, eligible)
                m2_test = m2_pre.transform(m2, test_rows)
                m3_test = m3_pre.transform(m3, test_rows)
                if m2_history.shape[1] != M2_ENCODED_WIDTH or m2_test.shape[1] != M2_ENCODED_WIDTH:
                    raise R4I0Error("M2_ENCODED_WIDTH_INVALID")
                if m3_history.shape[1] != M3_ENCODED_WIDTH or m3_test.shape[1] != M3_ENCODED_WIDTH:
                    raise R4I0Error("M3_ENCODED_WIDTH_INVALID")

                for test_position, test_row in enumerate(test_rows):
                    cell_total += 1
                    slot = clock_slots[test_row]
                    candidate_positions = np.flatnonzero(clock_slots[eligible] == slot).astype(np.int64)
                    candidate_rows = eligible[candidate_positions]
                    if len(candidate_rows) < MIN_CANDIDATES:
                        unsupported_candidates += 1
                        continue

                    selection = select_analogs(
                        candidate_issue_times=issue_times[candidate_rows],
                        candidate_level=m2_history[candidate_positions, station_index],
                        test_level=float(m2_test[test_position, station_index]),
                        candidate_m2=m2_history[candidate_positions],
                        test_m2=m2_test[test_position],
                        candidate_m3=m3_history[candidate_positions],
                        test_m3=m3_test[test_position],
                    )
                    if not selection.supported:
                        unsupported_distance += 1
                        continue
                    if selection.distance_ratio is None:
                        raise R4I0Error("SUPPORT_RATIO_INVALID")

                    target = float(labels[test_row, horizon_position])
                    candidate_targets = labels[candidate_rows, horizon_position]
                    record = {
                        "month": contract.month,
                        "horizon_minutes": horizon,
                        "d_level_a": analog_divergence(
                            target, candidate_targets[selection.level_rows]
                        ),
                        "d_m2_a": analog_divergence(target, candidate_targets[selection.m2_rows]),
                        "d_m3_a": analog_divergence(target, candidate_targets[selection.m3_rows]),
                        "y_abs_a": abs(target),
                        "distance_ratio": float(selection.distance_ratio),
                        "candidate_count": selection.candidate_count,
                        "test_third_m3_distance": selection.test_third_m3_distance,
                        "historical_q95_m3_distance": selection.historical_q95_m3_distance,
                    }
                    records.append(record)
                    cell_records.append(record)
                    cell_supported += 1

            total_oos += cell_total
            total_supported += cell_supported
            cell_fraction = 0.0 if cell_total == 0 else cell_supported / cell_total
            metrics = _aggregate(cell_records)
            cells.append(
                {
                    "month": contract.month,
                    "horizon_minutes": horizon,
                    "oos_records": cell_total,
                    "supported_records": cell_supported,
                    "supported_fraction": float(cell_fraction),
                    "unsupported_candidate_floor": unsupported_candidates,
                    "unsupported_m3_distance": unsupported_distance,
                    "metrics": metrics,
                }
            )
            if progress is not None:
                progress(
                    "R4_I0_STAGE=MONTH_HORIZON; "
                    f"MONTH={contract.month}; HORIZON={horizon}; "
                    f"SUPPORTED={cell_supported}/{cell_total}"
                )

    pooled_fraction = 0.0 if total_oos == 0 else total_supported / total_oos
    cell_support_pass = all(
        float(item["supported_fraction"]) >= MIN_CELL_SUPPORT_FRACTION
        and int(item["supported_records"]) >= MIN_CELL_SUPPORTED_RECORDS
        for item in cells
    )
    support_pass = bool(
        pooled_fraction >= MIN_POOLED_SUPPORT_FRACTION and cell_support_pass
    )
    support = {
        "oos_origin_horizon_records": total_oos,
        "supported_origin_horizon_records": total_supported,
        "pooled_supported_fraction": float(pooled_fraction),
        "minimum_pooled_supported_fraction": MIN_POOLED_SUPPORT_FRACTION,
        "minimum_cell_supported_fraction": MIN_CELL_SUPPORT_FRACTION,
        "minimum_cell_supported_records": MIN_CELL_SUPPORTED_RECORDS,
        "support_pass": support_pass,
    }

    pooled = _aggregate(records)
    by_horizon: list[dict[str, Any]] = []
    for horizon in HORIZONS_MINUTES:
        metrics = _aggregate([item for item in records if item["horizon_minutes"] == horizon])
        by_horizon.append({"horizon_minutes": horizon, **({} if metrics is None else metrics)})
    by_month: list[dict[str, Any]] = []
    for month in DEVELOPMENT_MONTHS:
        metrics = _aggregate([item for item in records if item["month"] == month])
        by_month.append({"month": month, **({} if metrics is None else metrics)})

    decision, decision_support = decide(
        support=support,
        pooled=pooled,
        by_horizon=by_horizon,
        by_month=by_month,
    )
    return Result(
        code_commit=code_commit,
        decision=decision,
        decision_support=MappingProxyType(decision_support),
        pooled=None if pooled is None else MappingProxyType(pooled),
        by_horizon=tuple(MappingProxyType(item) for item in by_horizon),
        by_month=tuple(MappingProxyType(item) for item in by_month),
        cells=tuple(MappingProxyType(item) for item in cells),
        support=MappingProxyType(support),
        preprocessor_fit_count=preprocessor_fit_count,
    )
