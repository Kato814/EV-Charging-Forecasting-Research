"""Frozen R3-C0 issue-time control-endogeneity diagnostic gate."""

from __future__ import annotations

import hashlib
import math
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

import numpy as np

from evcf.forecasting.acn_jpl_development_experts_compat import (
    DevelopmentExpertError,
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
    _load_m3_groups,
    _verify_private_manifest,
)

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
PRIMARY_MODELS = ("Equal", "S1")
SECONDARY_MODELS = ("R1_Joint",)
CONTROL_FIELDS = ("current_current_a", "current_pilot_a")
STATION_CURRENT_FEATURE = "station_current_a"
COVERAGE_FLOOR = 0.80
PILOT_SUM_FLOOR_A = 6.0
CURRENT_LEVEL_BINS = 5
PASS_EFFECT_FRACTION = 0.05
MIXED_EFFECT_FRACTION = 0.03
MIN_OVERALL_VALID_FRACTION = 0.70
MIN_MONTH_VALID_FRACTION = 0.50
MIN_MONTH_PAIRS = 100

EXPECTED_R2_PRIVATE_MANIFEST_SHA256 = (
    "9f35cffc192ebcebe30204fa1d23137ffc41e8ba858d9c55acfa85952d09bdd6"
)
EXPECTED_R2_CODE_COMMIT = "1ec7b02bb0e44353034aa86678ce039e747a589f"
EXPECTED_R2_PROTOCOL_MERGE_COMMIT = "ab0b8f6b7521f9e55d65a82fe7d44140a0973fef"

IMPLEMENTATION_PATHS = (
    "docs/JPL_R3_C0_CONTROL_ENDOGENEITY_GATE_PROTOCOL_20260913.md",
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_data.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_structured_mechanism_probe.py",
    "code/src/evcf/forecasting/acn_jpl_r3_control_endogeneity_gate.py",
    "scripts/run_jpl_r3_control_endogeneity_gate.py",
)

Progress = Callable[[str], None]


class R3C0Error(RuntimeError):
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
class ControlState:
    utilization: np.ndarray
    coverage: np.ndarray
    pilot_sum_a: np.ndarray
    binding_fraction_90: np.ndarray
    valid: np.ndarray


@dataclass(frozen=True, slots=True)
class MatchPairs:
    low_rows: np.ndarray
    high_rows: np.ndarray
    mean_abs_current_gap_a: float
    max_abs_current_gap_a: float
    low_u_mean: float
    high_u_mean: float


@dataclass(frozen=True, slots=True)
class Result:
    code_commit: str
    decision: str
    decision_support: Mapping[str, Any]
    pooled: Mapping[str, Any]
    by_horizon: tuple[Mapping[str, Any], ...]
    by_month: tuple[Mapping[str, Any], ...]
    cells: tuple[Mapping[str, Any], ...]
    month_support: tuple[Mapping[str, Any], ...]
    overall_valid_issue_fraction: float

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "evcf-jpl-r3-c0-control-endogeneity-summary/v1",
            "status": "COMPLETE",
            "code_commit": self.code_commit,
            "decision": self.decision,
            "decision_support": dict(self.decision_support),
            "pooled_overall": dict(self.pooled),
            "pooled_by_horizon": [dict(item) for item in self.by_horizon],
            "pooled_by_month": [dict(item) for item in self.by_month],
            "month_horizon_cells": [dict(item) for item in self.cells],
            "month_support": [dict(item) for item in self.month_support],
            "overall_valid_issue_fraction": self.overall_valid_issue_fraction,
            "fit_count": 0,
            "model_fit_attempted": False,
            "reference_models_retrained": False,
            "holdout_accessed": False,
            "hyperparameter_search": False,
            "prediction_clipping": False,
            "prediction_calibration": False,
            "future_control_predictor": False,
            "causal_claim": False,
            "source_r2_private_manifest_sha256": EXPECTED_R2_PRIVATE_MANIFEST_SHA256,
        }


def _verify_git(code_commit: str, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R3C0Error("IMPLEMENTATION_DRIFT")
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
        raise R3C0Error("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R3C0Error("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode:
            raise R3C0Error("IMPLEMENTATION_DRIFT")
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
        raise R3C0Error("IMPLEMENTATION_DRIFT")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_npz(path: Path, required: set[str]) -> dict[str, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != required:
                raise R3C0Error("R2_CACHE_SCHEMA_INVALID")
            return {name: np.asarray(archive[name]) for name in required}
    except R3C0Error:
        raise
    except (OSError, ValueError) as exc:
        raise R3C0Error("R2_CACHE_SCHEMA_INVALID") from exc


def _load_r2_reference(root: Path, month: str, horizon: int) -> dict[str, np.ndarray]:
    required = {
        "issue_times",
        "day_start_utc_s",
        "y_true",
        "m2_predictions",
        "m3_predictions",
        "equal_predictions",
        "s1_predictions",
        "r1_joint_predictions",
        "r2_permuted_predictions",
        "r2_joint_predictions",
    }
    data = _load_npz(root / f"{month}_h{horizon:03d}.npz", required)
    n = len(data["issue_times"])
    if n == 0 or any(array.shape != (n,) for array in data.values()):
        raise R3C0Error("R2_CACHE_SCHEMA_INVALID")
    if np.any(np.diff(data["issue_times"]) <= 0):
        raise R3C0Error("R2_CACHE_SCHEMA_INVALID")
    numeric = [
        value
        for key, value in data.items()
        if key not in {"issue_times", "day_start_utc_s"}
    ]
    if not all(np.isfinite(value).all() for value in numeric):
        raise R3C0Error("R2_CACHE_SCHEMA_INVALID")
    if not np.allclose(
        data["equal_predictions"],
        0.5 * data["m2_predictions"] + 0.5 * data["m3_predictions"],
        rtol=0.0,
        atol=1e-6,
    ):
        raise R3C0Error("R2_CACHE_IDENTITY_INVALID")
    return data


def build_control_state(
    groups: Sequence[Sequence[Mapping[str, Any]]],
    station_current_a: np.ndarray,
) -> ControlState:
    station_current = np.asarray(station_current_a, dtype=np.float64)
    if station_current.shape != (len(groups),) or np.any(np.isinf(station_current)):
        raise R3C0Error("CONTROL_STATE_INVALID")
    utilization = np.full(len(groups), np.nan, dtype=np.float64)
    coverage = np.zeros(len(groups), dtype=np.float64)
    pilot_sum = np.zeros(len(groups), dtype=np.float64)
    binding = np.full(len(groups), np.nan, dtype=np.float64)
    valid = np.zeros(len(groups), dtype=np.bool_)
    for position, rows in enumerate(groups):
        total = len(rows)
        if total == 0:
            continue
        currents: list[float] = []
        pilots: list[float] = []
        for row in rows:
            current = row[CONTROL_FIELDS[0]]
            pilot = row[CONTROL_FIELDS[1]]
            if current is None or pilot is None:
                continue
            parsed_current = float(current)
            parsed_pilot = float(pilot)
            if not math.isfinite(parsed_current) or not math.isfinite(parsed_pilot):
                raise R3C0Error("CONTROL_STATE_INVALID")
            if parsed_pilot <= 0:
                continue
            currents.append(parsed_current)
            pilots.append(parsed_pilot)
        count = len(currents)
        coverage[position] = count / total
        if count == 0:
            continue
        current_sum = math.fsum(currents)
        pilot_sum[position] = math.fsum(pilots)
        if pilot_sum[position] <= 0:
            continue
        utilization[position] = current_sum / pilot_sum[position]
        binding[position] = sum(
            current >= 0.90 * pilot
            for current, pilot in zip(currents, pilots, strict=True)
        ) / count
        valid[position] = bool(
            coverage[position] >= COVERAGE_FLOOR
            and pilot_sum[position] >= PILOT_SUM_FLOOR_A
            and math.isfinite(station_current[position])
            and math.isfinite(utilization[position])
        )
    return ControlState(
        utilization=utilization,
        coverage=coverage,
        pilot_sum_a=pilot_sum,
        binding_fraction_90=binding,
        valid=valid,
    )


def _stable_order(rows: np.ndarray, primary: np.ndarray, issue_times: np.ndarray) -> np.ndarray:
    if rows.ndim != 1:
        raise R3C0Error("MATCHING_INVALID")
    return rows[np.lexsort((issue_times[rows], primary[rows]))]


def build_match_pairs(
    issue_times: np.ndarray,
    station_current_a: np.ndarray,
    utilization: np.ndarray,
    valid: np.ndarray,
) -> MatchPairs:
    issues = np.asarray(issue_times, dtype=np.int64)
    current = np.asarray(station_current_a, dtype=np.float64)
    u = np.asarray(utilization, dtype=np.float64)
    mask = np.asarray(valid, dtype=np.bool_)
    n = len(issues)
    if current.shape != (n,) or u.shape != (n,) or mask.shape != (n,):
        raise R3C0Error("MATCHING_INVALID")
    rows = np.flatnonzero(mask).astype(np.int64)
    rows = _stable_order(rows, current, issues)
    low_parts: list[np.ndarray] = []
    high_parts: list[np.ndarray] = []
    for block in np.array_split(rows, CURRENT_LEVEL_BINS):
        ordered = _stable_order(np.asarray(block, dtype=np.int64), u, issues)
        half = len(ordered) // 2
        if len(ordered) % 2:
            low = ordered[:half]
            high = ordered[half + 1 :]
        else:
            low = ordered[:half]
            high = ordered[half:]
        low = _stable_order(low, current, issues)
        high = _stable_order(high, current, issues)
        if len(low) != len(high):
            raise R3C0Error("MATCHING_INVALID")
        if len(low):
            low_parts.append(low)
            high_parts.append(high)
    if low_parts:
        low_rows = np.concatenate(low_parts).astype(np.int64)
        high_rows = np.concatenate(high_parts).astype(np.int64)
    else:
        low_rows = np.empty(0, dtype=np.int64)
        high_rows = np.empty(0, dtype=np.int64)
    if len(low_rows) != len(high_rows):
        raise R3C0Error("MATCHING_INVALID")
    gaps = np.abs(current[low_rows] - current[high_rows])
    return MatchPairs(
        low_rows=low_rows,
        high_rows=high_rows,
        mean_abs_current_gap_a=0.0 if not len(gaps) else float(np.mean(gaps)),
        max_abs_current_gap_a=0.0 if not len(gaps) else float(np.max(gaps)),
        low_u_mean=float("nan") if not len(low_rows) else float(np.mean(u[low_rows])),
        high_u_mean=float("nan") if not len(high_rows) else float(np.mean(u[high_rows])),
    )


def contrast_metrics(
    y_true: np.ndarray,
    predictions: np.ndarray,
    pairs: MatchPairs,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    y = np.asarray(y_true, dtype=np.float64)
    pred = np.asarray(predictions, dtype=np.float64)
    if y.shape != pred.shape or y.ndim != 1:
        raise R3C0Error("CONTRAST_INVALID")
    if not np.isfinite(y).all() or not np.isfinite(pred).all():
        raise R3C0Error("CONTRAST_INVALID")
    low = pairs.low_rows
    high = pairs.high_rows
    ae_low = np.abs(pred[low] - y[low])
    ae_high = np.abs(pred[high] - y[high])
    d = ae_low - ae_high
    b = (ae_low + ae_high) / 2.0
    base = float(np.mean(b)) if len(b) else 0.0
    delta = float(np.mean(d)) if len(d) else 0.0
    fraction = 0.0 if base <= 0 else delta / base
    return (
        {
            "pair_count": len(d),
            "low_mae_a": 0.0 if not len(ae_low) else float(np.mean(ae_low)),
            "high_mae_a": 0.0 if not len(ae_high) else float(np.mean(ae_high)),
            "delta_mae_a": delta,
            "base_mae_a": base,
            "delta_fraction": float(fraction),
        },
        d,
        b,
    )


def _aggregate(records: Sequence[Mapping[str, Any]], model: str) -> dict[str, Any]:
    d = np.concatenate([np.asarray(record["raw"][model][0]) for record in records])
    b = np.concatenate([np.asarray(record["raw"][model][1]) for record in records])
    base = float(np.mean(b)) if len(b) else 0.0
    delta = float(np.mean(d)) if len(d) else 0.0
    return {
        "pair_records": len(d),
        "delta_mae_a": delta,
        "base_mae_a": base,
        "delta_fraction": 0.0 if base <= 0 else float(delta / base),
    }


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def decide(
    *,
    overall_valid_issue_fraction: float,
    month_support: Sequence[Mapping[str, Any]],
    pooled: Mapping[str, Any],
    by_horizon: Sequence[Mapping[str, Any]],
    by_month: Sequence[Mapping[str, Any]],
    cells: Sequence[Mapping[str, Any]],
) -> tuple[str, dict[str, Any]]:
    support_pass = bool(
        overall_valid_issue_fraction >= MIN_OVERALL_VALID_FRACTION
        and all(
            float(item["valid_issue_fraction"]) >= MIN_MONTH_VALID_FRACTION
            and int(item["matched_pair_count"]) >= MIN_MONTH_PAIRS
            for item in month_support
        )
    )
    eq = float(pooled["Equal"]["delta_fraction"])
    s1 = float(pooled["S1"]["delta_fraction"])
    eq_sign = _sign(eq)
    s1_sign = _sign(s1)

    def wins(rows: Sequence[Mapping[str, Any]], model: str, sign: int) -> int:
        return sum(_sign(float(row[model]["delta_fraction"])) == sign for row in rows)

    eq_h = wins(by_horizon, "Equal", eq_sign)
    s1_h = wins(by_horizon, "S1", s1_sign)
    eq_m = wins(by_month, "Equal", eq_sign)
    s1_m = wins(by_month, "S1", s1_sign)
    sixty = [row for row in cells if int(row["horizon_minutes"]) == 60]
    sixty_joint = sum(
        _sign(float(row["Equal"]["delta_fraction"])) == eq_sign
        and _sign(float(row["S1"]["delta_fraction"])) == s1_sign
        for row in sixty
    )
    support = {
        "support_pass": support_pass,
        "equal_pooled_sign": eq_sign,
        "s1_pooled_sign": s1_sign,
        "equal_pooled_abs_delta_fraction": abs(eq),
        "s1_pooled_abs_delta_fraction": abs(s1),
        "equal_horizon_sign_matches": int(eq_h),
        "s1_horizon_sign_matches": int(s1_h),
        "equal_month_sign_matches": int(eq_m),
        "s1_month_sign_matches": int(s1_m),
        "sixty_min_months_both_match_pooled_sign": int(sixty_joint),
    }
    if not support_pass:
        return "STOP_CONTROL_ENDOGENEITY_ROUTE", {
            **support,
            "stop_reason": "INSUFFICIENT_CONTROL_STATE_SUPPORT",
        }
    if eq_sign == 0 or s1_sign == 0 or eq_sign != s1_sign:
        return "STOP_CONTROL_ENDOGENEITY_ROUTE", {
            **support,
            "stop_reason": "POOLED_DIRECTION_UNSTABLE",
        }
    if abs(eq) < MIXED_EFFECT_FRACTION and abs(s1) < MIXED_EFFECT_FRACTION:
        return "STOP_CONTROL_ENDOGENEITY_ROUTE", {
            **support,
            "stop_reason": "POOLED_EFFECT_TOO_SMALL",
        }
    if eq_h <= 1 or s1_h <= 1 or eq_m <= 1 or s1_m <= 1:
        return "STOP_CONTROL_ENDOGENEITY_ROUTE", {
            **support,
            "stop_reason": "DIRECTION_NOT_REPRODUCIBLE",
        }
    passed = bool(
        abs(eq) >= PASS_EFFECT_FRACTION
        and abs(s1) >= PASS_EFFECT_FRACTION
        and eq_h >= 3
        and s1_h >= 3
        and eq_m >= 3
        and s1_m >= 3
        and sixty_joint >= 3
    )
    if passed:
        return "PASS_CONTROL_ENDOGENEITY_SIGNAL", {**support, "stop_reason": None}
    return "MIXED_CONTROL_ENDOGENEITY_SIGNAL", {**support, "stop_reason": None}


def _positions(full_issue_times: np.ndarray, query: np.ndarray) -> np.ndarray:
    full = np.asarray(full_issue_times, dtype=np.int64)
    values = np.asarray(query, dtype=np.int64)
    positions = np.searchsorted(full, values)
    if (
        np.any(positions >= len(full))
        or not np.array_equal(full[positions], values)
    ):
        raise R3C0Error("COMMON_ROW_IDENTITY_INVALID")
    return positions.astype(np.int64)


def run_gate(
    *,
    interim_root: str | Path,
    processed_root: str | Path,
    r2_private_run: str | Path,
    code_commit: str,
    repo_root: str | Path,
    progress: Progress | None = None,
) -> Result:
    repo = Path(repo_root).resolve(strict=True)
    _verify_git(code_commit, repo)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    r2_root = Path(r2_private_run).resolve(strict=True)
    try:
        manifest = _verify_private_manifest(
            r2_root,
            expected_sha256=EXPECTED_R2_PRIVATE_MANIFEST_SHA256,
            schema_version="evcf-jpl-r2-higher-order-session-set-private-cache/v1",
            entries_key="entries",
        )
    except Exception as exc:
        raise R3C0Error("R2_CACHE_IDENTITY_INVALID") from exc
    if (
        manifest.get("code_commit") != EXPECTED_R2_CODE_COMMIT
        or manifest.get("protocol_merge_commit") != EXPECTED_R2_PROTOCOL_MERGE_COMMIT
        or manifest.get("holdout_accessed") is not False
        or manifest.get("hyperparameter_search") is not False
    ):
        raise R3C0Error("R2_CACHE_IDENTITY_INVALID")

    protocol = load_development_expert_protocol(
        repo / "code/configs/acn_jpl_development_experts_2019.yaml"
    )
    if protocol.protocol_sha256 != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256:
        raise R3C0Error("PROTOCOL_INVALID")

    records: list[dict[str, Any]] = []
    supports: list[dict[str, Any]] = []
    total_oos = 0
    total_valid = 0
    for contract in protocol.months:
        if contract.month not in DEVELOPMENT_MONTHS:
            raise R3C0Error("HOLDOUT_ACCESS_ATTEMPT")
        if progress is not None:
            progress(f"R3_C0_STAGE=MONTH; MONTH={contract.month}")
        try:
            data = load_month_data(
                contract=contract,
                interim_root=interim,
                processed_root=processed,
            )
        except DevelopmentExpertError as exc:
            raise R3C0Error(exc.reason_code) from exc
        m2 = data.blocks["M2"]
        try:
            station_index = m2.feature_names.index(STATION_CURRENT_FEATURE)
        except ValueError as exc:
            raise R3C0Error("CONTROL_STATE_INVALID") from exc
        station_current = np.asarray(m2.values[:, station_index], dtype=np.float64)
        groups = _load_m3_groups(processed / contract.month, data.issue_times)
        state = build_control_state(groups, station_current)

        references = {
            horizon: _load_r2_reference(r2_root, contract.month, horizon)
            for horizon in HORIZONS_MINUTES
        }
        common = references[HORIZONS_MINUTES[0]]["issue_times"]
        day_starts = references[HORIZONS_MINUTES[0]]["day_start_utc_s"]
        for horizon in HORIZONS_MINUTES[1:]:
            ref = references[horizon]
            if not (
                np.array_equal(ref["issue_times"], common)
                and np.array_equal(ref["day_start_utc_s"], day_starts)
            ):
                raise R3C0Error("COMMON_ROW_IDENTITY_INVALID")
        positions = _positions(data.issue_times, common)
        common_current = station_current[positions]
        common_u = state.utilization[positions]
        common_valid = state.valid[positions]
        common_binding = state.binding_fraction_90[positions]
        pairs = build_match_pairs(common, common_current, common_u, common_valid)
        valid_count = int(np.sum(common_valid))
        valid_fraction = valid_count / len(common)
        total_oos += len(common)
        total_valid += valid_count
        supports.append(
            {
                "month": contract.month,
                "common_oos_issue_count": len(common),
                "valid_issue_count": valid_count,
                "valid_issue_fraction": float(valid_fraction),
                "matched_pair_count": len(pairs.low_rows),
                "binding_fraction_90_mean": None
                if not valid_count
                else float(np.nanmean(common_binding[common_valid])),
                "low_u_mean": pairs.low_u_mean,
                "high_u_mean": pairs.high_u_mean,
                "mean_abs_current_gap_a": pairs.mean_abs_current_gap_a,
                "max_abs_current_gap_a": pairs.max_abs_current_gap_a,
            }
        )
        for horizon_position, horizon in enumerate(HORIZONS_MINUTES):
            ref = references[horizon]
            expected_truth = np.asarray(data.labels[positions, horizon_position])
            if not np.allclose(ref["y_true"], expected_truth, rtol=0.0, atol=1e-6):
                raise R3C0Error("COMMON_ROW_IDENTITY_INVALID")
            public_models: dict[str, Any] = {}
            raw_models: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            for model, key in (
                ("Equal", "equal_predictions"),
                ("S1", "s1_predictions"),
                ("R1_Joint", "r1_joint_predictions"),
            ):
                metrics, d, b = contrast_metrics(ref["y_true"], ref[key], pairs)
                public_models[model] = metrics
                raw_models[model] = (d, b)
            records.append(
                {
                    "month": contract.month,
                    "horizon_minutes": horizon,
                    "public": {
                        "month": contract.month,
                        "horizon_minutes": horizon,
                        **public_models,
                    },
                    "raw": raw_models,
                }
            )

    overall_valid = 0.0 if not total_oos else total_valid / total_oos
    pooled = {
        model: _aggregate(records, model)
        for model in (*PRIMARY_MODELS, *SECONDARY_MODELS)
    }
    by_horizon = tuple(
        {
            "horizon_minutes": horizon,
            **{
                model: _aggregate(
                    [r for r in records if r["horizon_minutes"] == horizon], model
                )
                for model in (*PRIMARY_MODELS, *SECONDARY_MODELS)
            },
        }
        for horizon in HORIZONS_MINUTES
    )
    by_month = tuple(
        {
            "month": month,
            **{
                model: _aggregate([r for r in records if r["month"] == month], model)
                for model in (*PRIMARY_MODELS, *SECONDARY_MODELS)
            },
        }
        for month in DEVELOPMENT_MONTHS
    )
    cells = tuple(MappingProxyType(dict(record["public"])) for record in records)
    decision, decision_support = decide(
        overall_valid_issue_fraction=overall_valid,
        month_support=supports,
        pooled=pooled,
        by_horizon=by_horizon,
        by_month=by_month,
        cells=cells,
    )
    return Result(
        code_commit=code_commit,
        decision=decision,
        decision_support=MappingProxyType(decision_support),
        pooled=MappingProxyType(pooled),
        by_horizon=tuple(MappingProxyType(item) for item in by_horizon),
        by_month=tuple(MappingProxyType(item) for item in by_month),
        cells=cells,
        month_support=tuple(MappingProxyType(item) for item in supports),
        overall_valid_issue_fraction=float(overall_valid),
    )
