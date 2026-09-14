"""Frozen R7-C0 departure-state -> future-arrival mechanism probe for JPL."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, time, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from threadpoolctl import threadpool_limits

from evcf.forecasting.acn_jpl_development_experts import (
    MonthData,
    load_selected_hgb_parameters,
)
from evcf.forecasting.acn_jpl_development_experts_compat import (
    DevelopmentExpertError,
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock
from evcf.forecasting.acn_jpl_gate1_models import make_frozen_estimator
from evcf.forecasting.acn_jpl_structured_baseline import (
    _component_label_matrices,
    _load_cleaned_current_sessions,
    _metrics,
    load_structured_protocol,
)
from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256,
    EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
    EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256,
    EXPECTED_STRUCTURED_PROTOCOL_SHA256,
    _load_reference_pair,
    _verify_private_manifest,
)

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
ARRIVAL_DOMINANT_HORIZONS = (60, 120, 240)
TIMEZONE_NAME = "America/Los_Angeles"
_ZONE = ZoneInfo(TIMEZONE_NAME)

SOURCE_R6_STATUS_SHA256 = (
    "52bf3d7753b095a0faf39bc9aaefbd07b2c11f406ab05abd4bd1534e921dacce"
)
SOURCE_R6_DECISION = "MIXED_COMPONENT_ORACLE_SIGNAL"
PROTOCOL_COMMIT = "ed427067015e60b417cd5da3838b4e0a5701b01e"
EXPECTED_ROWS_BY_MONTH = MappingProxyType(
    {"2019-01": 1305, "2019-04": 1180, "2019-07": 1294, "2019-10": 1296}
)
EXPECTED_ROWS_PER_HORIZON = 5075
EXPECTED_RECORD_COUNT = 25375
EXPECTED_FIT_COUNT_PER_ARM = 275
EXPECTED_FIT_COUNT = 550
RECONSTRUCTION_TOLERANCE_A = 1e-6
MAX_DEGRADATION_FRACTION = 0.05
SELECTED_M2_PARAMETER_SHA256 = MappingProxyType(
    {
        15: "92b00c5e34dddd323774012fddbc1a63d1c953b9abd79fdf071f26aa92553fff",
        30: "a7405c4486297b12f246c39592d536818fda29d187c99a63876f97dd696ece1a",
        60: "1e99af2c4d2ac923bcd6cb6f6e5991380aef1161b5f4295af23edc450feace48",
        120: "a7405c4486297b12f246c39592d536818fda29d187c99a63876f97dd696ece1a",
        240: "9b92e929ae0566dd606ef7ae464df81be87712cff7ff31c89acf15b047ee58ac",
    }
)
DEPARTURE_RAW_WIDTH = 211
DEPARTURE_ENCODED_WIDTH = 221
FULL_M3_RAW_WIDTH = 311
FULL_M3_ENCODED_WIDTH = 391
Progress = Callable[[str], None]

_POOL_STAT_NAMES = (
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
_DEPARTURE_FEATURE_NAMES = tuple(
    f"m3_requested_departure_minutes_from_issue_{name}" for name in _POOL_STAT_NAMES
)

IMPLEMENTATION_PATHS = (
    "docs/JPL_R7_C0_DEPARTURE_STATE_ARRIVAL_PROTOCOL_20260914.md",
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/configs/acn_jpl_structured_baseline_2019.yaml",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_models.py",
    "code/src/evcf/forecasting/acn_jpl_structured_baseline.py",
    "code/src/evcf/forecasting/acn_jpl_structured_mechanism_probe.py",
    "code/src/evcf/forecasting/acn_jpl_r7_c0_departure_arrival.py",
    "scripts/run_jpl_r7_c0_departure_arrival.py",
)


class R7C0Error(RuntimeError):
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


def _git_semantic_verify(code_commit: str, *, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R7C0Error("IMPLEMENTATION_DRIFT")
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
        raise R7C0Error("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R7C0Error("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode:
            raise R7C0Error("IMPLEMENTATION_DRIFT")
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
        raise R7C0Error("IMPLEMENTATION_DRIFT")


def _departure_aug_block(m2: FeatureBlock, m3: FeatureBlock) -> FeatureBlock:
    if (
        not np.array_equal(m2.issue_times, m3.issue_times)
        or len(m2.feature_names) != 201
        or len(m3.feature_names) != FULL_M3_RAW_WIDTH
        or tuple(m3.feature_names[: len(m2.feature_names)]) != tuple(m2.feature_names)
        or not np.array_equal(
            m3.values[:, : len(m2.feature_names)],
            m2.values,
            equal_nan=True,
        )
        or not np.array_equal(
            m3.nullable_mask[: len(m2.feature_names)],
            m2.nullable_mask,
        )
    ):
        raise R7C0Error("FEATURE_ALIGNMENT_INVALID")

    positions: list[int] = []
    for name in _DEPARTURE_FEATURE_NAMES:
        try:
            positions.append(m3.feature_names.index(name))
        except ValueError as exc:
            raise R7C0Error("DEPARTURE_FEATURE_SCHEMA_INVALID") from exc
    if len(set(positions)) != len(_DEPARTURE_FEATURE_NAMES):
        raise R7C0Error("DEPARTURE_FEATURE_SCHEMA_INVALID")

    values = np.concatenate((m2.values, m3.values[:, positions]), axis=1)
    names = tuple(m2.feature_names) + _DEPARTURE_FEATURE_NAMES
    nullable = np.concatenate((m2.nullable_mask, m3.nullable_mask[positions]))
    if values.shape[1] != DEPARTURE_RAW_WIDTH or (
        values.shape[1] + int(np.sum(nullable)) != DEPARTURE_ENCODED_WIDTH
    ):
        raise R7C0Error("DEPARTURE_FEATURE_SCHEMA_INVALID")
    try:
        return FeatureBlock(m2.issue_times, values, names, nullable.astype(np.bool_))
    except (TypeError, ValueError) as exc:
        raise R7C0Error("DEPARTURE_FEATURE_SCHEMA_INVALID") from exc


def _row_indexes(rows: Sequence[int] | np.ndarray, row_count: int) -> np.ndarray:
    value = np.asarray(rows)
    if value.ndim != 1 or not np.issubdtype(value.dtype, np.integer) or not len(value):
        raise R7C0Error("ROLLING_SPLIT_INVALID")
    result = value.astype(np.int64, copy=False)
    if (
        np.any(result < 0)
        or np.any(result >= row_count)
        or np.any(np.diff(result) <= 0)
    ):
        raise R7C0Error("ROLLING_SPLIT_INVALID")
    return result


def _encode(block: FeatureBlock, rows: Sequence[int] | np.ndarray) -> np.ndarray:
    selected = _row_indexes(rows, len(block.issue_times))
    raw = np.asarray(block.values[selected], dtype=np.float64)
    if np.any(np.isinf(raw)):
        raise R7C0Error("FEATURE_INVALID")
    nullable = np.asarray(block.nullable_mask, dtype=np.bool_)
    indicators = np.isnan(raw[:, nullable]).astype(np.float64)
    encoded = np.concatenate((raw, indicators), axis=1)
    if np.any(np.isinf(encoded)):
        raise R7C0Error("FEATURE_INVALID")
    return encoded


def _local_midnight_epoch(epoch_seconds: int) -> int:
    local = datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(_ZONE)
    return int(datetime.combine(local.date(), time.min, tzinfo=_ZONE).timestamp())


def _rolling_test_days(
    issue_times: np.ndarray, test_start_local_day: int
) -> tuple[np.ndarray, np.ndarray]:
    day_starts = np.asarray(
        [_local_midnight_epoch(int(value)) for value in issue_times], dtype=np.int64
    )
    local_days = np.asarray(
        [
            datetime.fromtimestamp(int(value), timezone.utc).astimezone(_ZONE).day
            for value in issue_times
        ],
        dtype=np.int16,
    )
    test_rows = np.flatnonzero(local_days >= test_start_local_day).astype(np.int64)
    if not len(test_rows):
        raise R7C0Error("ROLLING_SPLIT_INVALID")
    return day_starts, np.unique(day_starts[test_rows])


def _predict_custom_arm(
    *,
    data: MonthData,
    block: FeatureBlock,
    horizon_minutes: int,
    params: Mapping[str, Any],
    encoded_width: int,
    native_thread_limit: int,
) -> dict[str, Any]:
    if horizon_minutes not in HORIZONS_MINUTES:
        raise R7C0Error("ROLLING_SPLIT_INVALID")
    position = HORIZONS_MINUTES.index(horizon_minutes)
    labels = np.asarray(data.labels[:, position], dtype=np.float64)
    issue_times = np.asarray(data.issue_times, dtype=np.int64)
    if (
        block.values.shape[0] != len(issue_times)
        or not np.array_equal(block.issue_times, issue_times)
        or not np.isfinite(labels).all()
    ):
        raise R7C0Error("FEATURE_LABEL_ALIGNMENT_INVALID")

    all_day_starts, test_days = _rolling_test_days(issue_times, 18)
    output_times: list[np.ndarray] = []
    output_days: list[np.ndarray] = []
    output_truth: list[np.ndarray] = []
    output_predictions: list[np.ndarray] = []
    fits = 0

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
            or int(np.max(issue_times[fit_rows] + horizon_minutes * 60))
            > int(day_start)
        ):
            raise R7C0Error("ROLLING_SPLIT_INVALID")

        x_train = _encode(block, fit_rows)
        x_test = _encode(block, test_rows)
        if x_train.shape[1] != encoded_width or x_test.shape[1] != encoded_width:
            raise R7C0Error("FEATURE_INVALID")
        try:
            estimator = make_frozen_estimator("hgb", params)
            with threadpool_limits(limits=native_thread_limit):
                estimator.fit(x_train, labels[fit_rows])
                prediction = np.asarray(estimator.predict(x_test), dtype=np.float64)
        except Exception as exc:  # noqa: BLE001
            raise R7C0Error("MODEL_FIT_FAILED") from exc
        if prediction.shape != (len(test_rows),) or not np.isfinite(prediction).all():
            raise R7C0Error("MODEL_OUTPUT_INVALID")

        output_times.append(issue_times[test_rows])
        output_days.append(all_day_starts[test_rows])
        output_truth.append(labels[test_rows])
        output_predictions.append(prediction)
        fits += 1

    times = np.concatenate(output_times)
    days = np.concatenate(output_days)
    truth = np.concatenate(output_truth)
    predictions = np.concatenate(output_predictions)
    if np.any(np.diff(times) <= 0):
        raise R7C0Error("ROLLING_SPLIT_INVALID")
    return {
        "issue_times": times,
        "day_starts": days,
        "truth": truth,
        "predictions": predictions,
        "fit_count": fits,
    }


def _record(
    *,
    month: str,
    horizon: int,
    reference: Mapping[str, np.ndarray],
    departure: Mapping[str, Any],
    full_m3: Mapping[str, Any],
) -> dict[str, Any]:
    expected_n = EXPECTED_ROWS_BY_MONTH[month]
    if (
        len(reference["issue_times"]) != expected_n
        or len(departure["issue_times"]) != expected_n
        or len(full_m3["issue_times"]) != expected_n
        or not np.array_equal(reference["issue_times"], departure["issue_times"])
        or not np.array_equal(reference["issue_times"], full_m3["issue_times"])
        or not np.array_equal(reference["day_start_utc_s"], departure["day_starts"])
        or not np.array_equal(reference["day_start_utc_s"], full_m3["day_starts"])
        or not np.allclose(
            reference["arrival_truth"],
            departure["truth"],
            rtol=0.0,
            atol=RECONSTRUCTION_TOLERANCE_A,
        )
        or not np.allclose(
            reference["arrival_truth"],
            full_m3["truth"],
            rtol=0.0,
            atol=RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise R7C0Error("COMMON_ROW_IDENTITY_INVALID")

    dep_arrival = np.asarray(departure["predictions"], dtype=np.float64)
    full_arrival = np.asarray(full_m3["predictions"], dtype=np.float64)
    existing = np.asarray(reference["existing_predictions"], dtype=np.float64)
    dep_total = existing + dep_arrival
    full_total = existing + full_arrival
    if not np.isfinite(dep_total).all() or not np.isfinite(full_total).all():
        raise R7C0Error("MODEL_OUTPUT_INVALID")

    return {
        "month": month,
        "horizon": horizon,
        "issue_times": np.asarray(reference["issue_times"], dtype=np.int64),
        "day_starts": np.asarray(reference["day_start_utc_s"], dtype=np.int64),
        "total_truth": np.asarray(reference["y_true"], dtype=np.float64),
        "arrival_truth": np.asarray(reference["arrival_truth"], dtype=np.float64),
        "base_arrival": np.asarray(reference["arrival_predictions"], dtype=np.float64),
        "departure_arrival": dep_arrival,
        "full_m3_arrival": full_arrival,
        "s1_existing": existing,
        "s1_total": np.asarray(reference["structured_predictions"], dtype=np.float64),
        "equal_total": np.asarray(reference["equal_predictions"], dtype=np.float64),
        "departure_total": dep_total,
        "full_m3_total": full_total,
    }


def _summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise R7C0Error("METRIC_INVALID")

    def cat(name: str) -> np.ndarray:
        return np.concatenate(
            [np.asarray(record[name], dtype=np.float64) for record in records]
        )

    arrival_truth = cat("arrival_truth")
    total_truth = cat("total_truth")
    return {
        "arrival": {
            "BaseM2": _metrics(arrival_truth, cat("base_arrival")),
            "DepartureAug": _metrics(arrival_truth, cat("departure_arrival")),
            "FullM3": _metrics(arrival_truth, cat("full_m3_arrival")),
        },
        "total": {
            "S1": _metrics(total_truth, cat("s1_total")),
            "Equal": _metrics(total_truth, cat("equal_total")),
            "TotalDeparture": _metrics(total_truth, cat("departure_total")),
            "TotalFullM3": _metrics(total_truth, cat("full_m3_total")),
        },
    }


def _degradation(reference: float, candidate: float) -> float:
    if reference < 0 or candidate < 0:
        raise R7C0Error("METRIC_INVALID")
    if reference == 0.0:
        if candidate == 0.0:
            return 0.0
        raise R7C0Error("METRIC_INVALID")
    return float((candidate - reference) / reference)


def decide(
    pooled: Mapping[str, Any],
    by_horizon: Sequence[Mapping[str, Any]],
    by_month: Sequence[Mapping[str, Any]],
) -> tuple[str, str, dict[str, Any]]:
    base_arrival = float(pooled["arrival"]["BaseM2"]["mae_a"])
    dep_arrival = float(pooled["arrival"]["DepartureAug"]["mae_a"])
    full_arrival = float(pooled["arrival"]["FullM3"]["mae_a"])
    s1_total = float(pooled["total"]["S1"]["mae_a"])
    equal_total = float(pooled["total"]["Equal"]["mae_a"])
    dep_total = float(pooled["total"]["TotalDeparture"]["mae_a"])

    component_horizon_wins = sum(
        float(item["arrival"]["DepartureAug"]["mae_a"])
        < float(item["arrival"]["BaseM2"]["mae_a"])
        for item in by_horizon
    )
    component_month_wins = sum(
        float(item["arrival"]["DepartureAug"]["mae_a"])
        < float(item["arrival"]["BaseM2"]["mae_a"])
        for item in by_month
    )
    dominant_horizon_wins = sum(
        float(item["arrival"]["DepartureAug"]["mae_a"])
        < float(item["arrival"]["BaseM2"]["mae_a"])
        for item in by_horizon
        if int(item["horizon_minutes"]) in ARRIVAL_DOMINANT_HORIZONS
    )
    total_horizon_wins = sum(
        float(item["total"]["TotalDeparture"]["mae_a"])
        < float(item["total"]["S1"]["mae_a"])
        for item in by_horizon
    )
    total_month_wins = sum(
        float(item["total"]["TotalDeparture"]["mae_a"])
        < float(item["total"]["S1"]["mae_a"])
        for item in by_month
    )
    component_max_degradation = max(
        _degradation(
            float(item["arrival"]["BaseM2"]["mae_a"]),
            float(item["arrival"]["DepartureAug"]["mae_a"]),
        )
        for item in by_horizon
    )
    total_max_degradation = max(
        _degradation(
            float(item["total"]["S1"]["mae_a"]),
            float(item["total"]["TotalDeparture"]["mae_a"]),
        )
        for item in by_horizon
    )

    passed = (
        dep_arrival < base_arrival
        and component_horizon_wins >= 3
        and component_month_wins >= 3
        and dominant_horizon_wins >= 2
        and component_max_degradation <= MAX_DEGRADATION_FRACTION
        and dep_total < s1_total
        and dep_total < equal_total
        and total_horizon_wins >= 3
        and total_month_wins >= 3
        and total_max_degradation <= MAX_DEGRADATION_FRACTION
    )
    if passed:
        decision = "PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL"
    elif dep_arrival < base_arrival or dep_total < s1_total:
        decision = "MIXED_DEPARTURE_STATE_ARRIVAL_SIGNAL"
    else:
        decision = "STOP_DEPARTURE_STATE_ARRIVAL_ROUTE"

    full_horizon_wins = sum(
        float(item["arrival"]["FullM3"]["mae_a"])
        < float(item["arrival"]["BaseM2"]["mae_a"])
        for item in by_horizon
    )
    full_month_wins = sum(
        float(item["arrival"]["FullM3"]["mae_a"])
        < float(item["arrival"]["BaseM2"]["mae_a"])
        for item in by_month
    )
    full_total_horizon_wins = sum(
        float(item["total"]["TotalFullM3"]["mae_a"])
        < float(item["total"]["S1"]["mae_a"])
        for item in by_horizon
    )
    full_total_month_wins = sum(
        float(item["total"]["TotalFullM3"]["mae_a"])
        < float(item["total"]["S1"]["mae_a"])
        for item in by_month
    )
    secondary = (
        "FULL_M3_INCREMENTAL_SIGNAL"
        if (
            full_arrival < base_arrival
            and full_horizon_wins >= 3
            and full_month_wins >= 3
        )
        else "NO_STABLE_FULL_M3_INCREMENT"
    )

    support = {
        "pooled_arrival_improvement_fraction": (
            None
            if base_arrival == 0
            else float((base_arrival - dep_arrival) / base_arrival)
        ),
        "pooled_total_improvement_vs_S1_fraction": (
            None if s1_total == 0 else float((s1_total - dep_total) / s1_total)
        ),
        "pooled_total_improvement_vs_Equal_fraction": (
            None if equal_total == 0 else float((equal_total - dep_total) / equal_total)
        ),
        "component_horizon_wins": int(component_horizon_wins),
        "component_month_wins": int(component_month_wins),
        "arrival_dominant_horizon_wins": int(dominant_horizon_wins),
        "total_horizon_wins_vs_S1": int(total_horizon_wins),
        "total_month_wins_vs_S1": int(total_month_wins),
        "max_component_horizon_degradation": float(component_max_degradation),
        "max_total_horizon_degradation": float(total_max_degradation),
        "full_m3_component_horizon_wins": int(full_horizon_wins),
        "full_m3_component_month_wins": int(full_month_wins),
        "full_m3_total_horizon_wins_vs_S1": int(full_total_horizon_wins),
        "full_m3_total_month_wins_vs_S1": int(full_total_month_wins),
        "pooled_full_m3_arrival_improvement_fraction": (
            None
            if base_arrival == 0
            else float((base_arrival - full_arrival) / base_arrival)
        ),
    }
    return decision, secondary, support


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
        departure_arrival_predictions=record["departure_arrival"],
        full_m3_arrival_predictions=record["full_m3_arrival"],
        s1_existing_predictions=record["s1_existing"],
        s1_predictions=record["s1_total"],
        equal_predictions=record["equal_total"],
        total_departure_predictions=record["departure_total"],
        total_full_m3_predictions=record["full_m3_total"],
    )
    return name, _sha256_file(path)


def run_r7_c0(
    *,
    authorized: bool,
    interim_root: str | Path,
    processed_root: str | Path,
    baseline_private_run: str | Path,
    structured_private_run: str | Path,
    private_output_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    progress: Progress | None = None,
) -> dict[str, Any]:
    if authorized is not True:
        raise R7C0Error("R7_C0_NOT_AUTHORIZED")

    repo = Path(repo_root).resolve(strict=True)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    baseline_root = Path(baseline_private_run).resolve(strict=True)
    structured_root = Path(structured_private_run).resolve(strict=True)
    output = Path(private_output_root).resolve(strict=False)
    if output.exists() or any(
        path.is_symlink()
        for path in (interim, processed, baseline_root, structured_root)
    ):
        raise R7C0Error("OUTPUT_TOPOLOGY_INVALID")

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
        or tuple(contract.month for contract in source_protocol.months)
        != DEVELOPMENT_MONTHS
        or tuple(contract.month for contract in structured_protocol.months)
        != DEVELOPMENT_MONTHS
        or source_protocol.test_start_local_day != 18
        or any(
            source_protocol.selected_parameter_sha256["M2"][horizon]
            != SELECTED_M2_PARAMETER_SHA256[horizon]
            for horizon in HORIZONS_MINUTES
        )
    ):
        raise R7C0Error("PROTOCOL_INVALID")

    try:
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
    except Exception as exc:  # noqa: BLE001
        raise R7C0Error("PRIVATE_CACHE_IDENTITY_INVALID") from exc
    if (
        baseline_manifest.get("protocol_sha256")
        != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256
        or structured_manifest.get("protocol_sha256")
        != EXPECTED_STRUCTURED_PROTOCOL_SHA256
    ):
        raise R7C0Error("PRIVATE_CACHE_IDENTITY_INVALID")

    try:
        selected = load_selected_hgb_parameters(
            protocol=source_protocol,
            repo_root=repo,
        )
    except DevelopmentExpertError as exc:
        raise R7C0Error(exc.reason_code) from exc

    source_contracts = {contract.month: contract for contract in source_protocol.months}
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".evcf-r7-c0-", dir=output.parent))
    records: list[dict[str, Any]] = []
    private_entries: list[dict[str, str]] = []
    departure_fit_count = 0
    full_m3_fit_count = 0
    try:
        for structured_contract in structured_protocol.months:
            month = structured_contract.month
            if month not in DEVELOPMENT_MONTHS:
                raise R7C0Error("HOLDOUT_ACCESS_ATTEMPT")
            source_contract = source_contracts.get(month)
            if (
                source_contract is None
                or source_contract.processed_snapshot_sha256
                != structured_contract.processed_snapshot_sha256
            ):
                raise R7C0Error("PROTOCOL_INVALID")
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
            except Exception as exc:  # noqa: BLE001
                reason = getattr(exc, "reason_code", "SOURCE_DATA_INVALID")
                raise R7C0Error(reason) from exc

            arrival_data = MonthData(
                month=data.month,
                issue_times=data.issue_times,
                labels=arrival_labels,
                blocks=data.blocks,
                processed_snapshot_sha256=data.processed_snapshot_sha256,
            )
            departure_block = _departure_aug_block(
                data.blocks["M2"], data.blocks["M3"]
            )
            m3_block = data.blocks["M3"]
            if (
                m3_block.values.shape[1] != FULL_M3_RAW_WIDTH
                or m3_block.values.shape[1] + int(np.sum(m3_block.nullable_mask))
                != FULL_M3_ENCODED_WIDTH
            ):
                raise R7C0Error("FEATURE_INVALID")

            if progress is not None:
                progress(f"R7_STAGE=MONTH_START; MONTH={month}")
            for horizon in HORIZONS_MINUTES:
                params = selected[("M2", horizon)]
                departure = _predict_custom_arm(
                    data=arrival_data,
                    block=departure_block,
                    horizon_minutes=horizon,
                    params=params,
                    encoded_width=DEPARTURE_ENCODED_WIDTH,
                    native_thread_limit=source_protocol.native_thread_limit,
                )
                full_m3 = _predict_custom_arm(
                    data=arrival_data,
                    block=m3_block,
                    horizon_minutes=horizon,
                    params=params,
                    encoded_width=FULL_M3_ENCODED_WIDTH,
                    native_thread_limit=source_protocol.native_thread_limit,
                )
                departure_fit_count += int(departure["fit_count"])
                full_m3_fit_count += int(full_m3["fit_count"])
                reference = _load_reference_pair(
                    baseline_root=baseline_root,
                    structured_root=structured_root,
                    month=month,
                    horizon=horizon,
                )
                record = _record(
                    month=month,
                    horizon=horizon,
                    reference=reference,
                    departure=departure,
                    full_m3=full_m3,
                )
                name, digest = _write_private_task(stage, record)
                private_entries.append({"name": name, "sha256": digest})
                records.append(record)
                if progress is not None:
                    completed = departure_fit_count + full_m3_fit_count
                    progress(
                        "R7_STAGE=HORIZON_COMPLETE; "
                        f"MONTH={month}; HORIZON={horizon}; "
                        f"FITS={completed}/{EXPECTED_FIT_COUNT}"
                    )
            if progress is not None:
                progress(f"R7_STAGE=MONTH_COMPLETE; MONTH={month}")

        if (
            departure_fit_count != EXPECTED_FIT_COUNT_PER_ARM
            or full_m3_fit_count != EXPECTED_FIT_COUNT_PER_ARM
            or departure_fit_count + full_m3_fit_count != EXPECTED_FIT_COUNT
            or len(records) != 20
            or len(private_entries) != 20
        ):
            raise R7C0Error("FIT_COUNT_INVALID")

        pooled = _summary(records)
        by_horizon = []
        for horizon in HORIZONS_MINUTES:
            selected_records = [
                record for record in records if int(record["horizon"]) == horizon
            ]
            summary = _summary(selected_records)
            if int(summary["arrival"]["BaseM2"]["n"]) != EXPECTED_ROWS_PER_HORIZON:
                raise R7C0Error("COMMON_ROW_IDENTITY_INVALID")
            by_horizon.append({"horizon_minutes": horizon, **summary})

        by_month = []
        for month in DEVELOPMENT_MONTHS:
            selected_records = [
                record for record in records if str(record["month"]) == month
            ]
            summary = _summary(selected_records)
            if int(summary["arrival"]["BaseM2"]["n"]) != EXPECTED_ROWS_BY_MONTH[month] * 5:
                raise R7C0Error("COMMON_ROW_IDENTITY_INVALID")
            by_month.append({"month": month, **summary})

        cells = [
            {
                "month": record["month"],
                "horizon_minutes": record["horizon"],
                **_summary([record]),
            }
            for record in records
        ]
        if int(pooled["arrival"]["BaseM2"]["n"]) != EXPECTED_RECORD_COUNT:
            raise R7C0Error("COMMON_ROW_IDENTITY_INVALID")

        decision, secondary, support = decide(pooled, by_horizon, by_month)

        manifest = {
            "schema_version": "evcf-jpl-r7-c0-private-cache/v1",
            "source_r6_status_sha256": SOURCE_R6_STATUS_SHA256,
            "code_commit": code_commit,
            "protocol_commit": PROTOCOL_COMMIT,
            "entries": private_entries,
        }
        manifest_path = stage / "private_manifest.json"
        manifest_path.write_text(
            json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            + "\n",
            encoding="ascii",
            newline="\n",
        )
        manifest_sha = _sha256_file(manifest_path)
        stage.replace(output)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return {
        "schema_version": "evcf-jpl-r7-c0-summary/v1",
        "status": "COMPLETE",
        "code_commit": code_commit,
        "protocol_commit": PROTOCOL_COMMIT,
        "source_r6_status_sha256": SOURCE_R6_STATUS_SHA256,
        "source_r6_decision": SOURCE_R6_DECISION,
        "selected_m2_parameter_sha256": {
            str(horizon): SELECTED_M2_PARAMETER_SHA256[horizon]
            for horizon in HORIZONS_MINUTES
        },
        "decision": decision,
        "secondary_full_m3_label": secondary,
        "decision_support": support,
        "pooled_overall": pooled,
        "pooled_by_horizon": by_horizon,
        "pooled_by_month": by_month,
        "month_horizon_cells": cells,
        "fit_count": departure_fit_count + full_m3_fit_count,
        "departure_fit_count": departure_fit_count,
        "full_m3_fit_count": full_m3_fit_count,
        "model_fit_attempted": True,
        "hyperparameter_search": False,
        "reference_models_retrained": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "gate_trained": False,
        "moe_trained": False,
        "neural_model_trained": False,
        "holdout_accessed": False,
        "private_cache_file_count": len(private_entries),
        "private_manifest_sha256": manifest_sha,
    }
