"""Frozen R11-S0 station-level deep-backbone screening controller for JPL."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

import numpy as np
from threadpoolctl import threadpool_limits

from evcf.forecasting.acn_jpl_development_experts import (
    DevelopmentExpertError,
    DevelopmentExpertProtocol,
    load_development_expert_protocol,
    load_month_data,
    load_selected_hgb_parameters,
)
from evcf.forecasting.acn_jpl_gate1_models import make_frozen_estimator
from evcf.forecasting.acn_jpl_r11_s0_common import (
    DEEP_ARCHITECTURES,
    DEEP_SEEDS,
    DEVELOPMENT_MONTHS,
    EXPECTED_FIT_COUNT,
    EXPECTED_HGB_FITS,
    FINAL_HOLDOUT_MONTHS,
    HORIZONS_MINUTES,
    R11S0Error,
)
from evcf.forecasting.acn_jpl_r11_s0_data import (
    StationFold,
    StationMonthData,
    build_station_folds,
    station_month_from_frozen_data,
)
from evcf.forecasting.acn_jpl_r11_s0_models import (
    FoldPrediction,
    parameter_count_report,
    train_deep_fold,
    validate_formal_device,
)
from evcf.forecasting.acn_jpl_r11_s0_models import (
    import_torch as _import_torch,
)

IMPLEMENTATION_PATHS = (
    "docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md",
    "code/src/evcf/forecasting/acn_jpl_r11_s0_common.py",
    "code/src/evcf/forecasting/acn_jpl_r11_s0_data.py",
    "code/src/evcf/forecasting/acn_jpl_r11_s0_models.py",
    "code/src/evcf/forecasting/acn_jpl_r11_s0_backbone.py",
    "scripts/check_r11_s0_environment.py",
    "scripts/run_jpl_r11_s0_backbone.py",
)


@dataclass(frozen=True, slots=True)
class R11S0RunResult:
    status: str
    decision: str
    selected_backbone: str | None
    parameter_counts: Mapping[str, int]
    station_hgb: Mapping[str, Any]
    deep_models: Mapping[str, Any]
    decision_support: Mapping[str, Any]
    fit_count: int
    holdout_accessed: bool = False
    session_predictors_used: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "evcf-jpl-r11-s0-summary/v1",
            "status": self.status,
            "decision": self.decision,
            "selected_backbone": self.selected_backbone,
            "parameter_counts": dict(self.parameter_counts),
            "station_hgb": dict(self.station_hgb),
            "deep_models": {key: dict(value) for key, value in self.deep_models.items()},
            "decision_support": dict(self.decision_support),
            "fit_count": self.fit_count,
            "holdout_accessed": self.holdout_accessed,
            "session_predictors_used": self.session_predictors_used,
            "development_months": list(DEVELOPMENT_MONTHS),
            "final_holdout_months": list(FINAL_HOLDOUT_MONTHS),
            "horizons_minutes": list(HORIZONS_MINUTES),
        }


def _verify_file_at_commit(root: Path, commit: str, relative: str) -> None:
    path = root / PurePosixPath(relative)
    if not path.is_file() or path.is_symlink():
        raise R11S0Error("IMPLEMENTATION_DRIFT")
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0 or completed.stdout != path.read_bytes():
        raise R11S0Error("IMPLEMENTATION_DRIFT")


def verify_r11_s0_implementation_commit(code_commit: str, *, repo_root: str | Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R11S0Error("IMPLEMENTATION_DRIFT")
    root = Path(repo_root).resolve(strict=True)
    for relative in IMPLEMENTATION_PATHS:
        _verify_file_at_commit(root, code_commit, relative)


def _station_hgb_features(fold: StationFold, split: str, horizon_position: int) -> np.ndarray:
    history = getattr(fold, f"{split}_history")
    issue = getattr(fold, f"{split}_issue_context")
    target = getattr(fold, f"{split}_target_context")[:, horizon_position]
    output = np.concatenate((history.reshape(len(history), -1), issue, target), axis=1)
    if output.shape[1] != 203 or not np.isfinite(output).all():
        raise R11S0Error("HGB_FEATURE_INVALID")
    return output.astype(np.float64)


def predict_station_hgb_fold(
    *, fold: StationFold, parameters: Mapping[int, Mapping[str, Any]]
) -> FoldPrediction:
    predictions = np.empty_like(fold.test_labels, dtype=np.float64)
    started = time.perf_counter()
    for position, horizon in enumerate(HORIZONS_MINUTES):
        x_train = _station_hgb_features(fold, "train", position)
        x_test = _station_hgb_features(fold, "test", position)
        estimator = make_frozen_estimator("hgb", parameters[horizon])
        try:
            with threadpool_limits(limits=1):
                estimator.fit(x_train, fold.train_labels[:, position])
                values = np.asarray(estimator.predict(x_test), dtype=np.float64)
        except Exception as exc:
            raise R11S0Error("HGB_FIT_FAILED") from exc
        if values.shape != (len(x_test),) or not np.isfinite(values).all():
            raise R11S0Error("HGB_OUTPUT_INVALID")
        predictions[:, position] = values
    return FoldPrediction(
        month=fold.month,
        issue_times=fold.test_issue_times,
        local_days=fold.test_local_days,
        y_true=fold.test_labels,
        predictions=predictions,
        best_epoch=0,
        wall_seconds=float(time.perf_counter() - started),
    )


def _metric(y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y, dtype=np.float64).reshape(-1)
    pred = np.asarray(pred, dtype=np.float64).reshape(-1)
    if y.shape != pred.shape or not len(y) or not np.isfinite(y).all() or not np.isfinite(pred).all():
        raise R11S0Error("METRIC_INPUT_INVALID")
    error = pred - y
    absolute = np.abs(error)
    denominator = float(np.sum(np.abs(y)))
    return {
        "n": len(y),
        "mae_a": float(np.mean(absolute)),
        "rmse_a": float(np.sqrt(np.mean(np.square(error)))),
        "wape_ratio": None if denominator <= 0 else float(np.sum(absolute) / denominator),
        "negative_prediction_count": int(np.sum(pred < 0)),
        "negative_prediction_fraction": float(np.mean(pred < 0)),
    }


def summarize_predictions(records: Sequence[FoldPrediction]) -> dict[str, Any]:
    if tuple(record.month for record in records) != DEVELOPMENT_MONTHS:
        raise R11S0Error("SUMMARY_IDENTITY_INVALID")
    truth = np.concatenate([record.y_true for record in records])
    prediction = np.concatenate([record.predictions for record in records])
    by_horizon = []
    for position, horizon in enumerate(HORIZONS_MINUTES):
        by_horizon.append(
            {
                "horizon_minutes": horizon,
                **_metric(
                    np.concatenate([record.y_true[:, position] for record in records]),
                    np.concatenate([record.predictions[:, position] for record in records]),
                ),
            }
        )
    by_month = [
        {"month": record.month, **_metric(record.y_true, record.predictions)} for record in records
    ]
    cells = []
    days = []
    for record in records:
        for position, horizon in enumerate(HORIZONS_MINUTES):
            cells.append(
                {
                    "month": record.month,
                    "horizon_minutes": horizon,
                    **_metric(record.y_true[:, position], record.predictions[:, position]),
                }
            )
        for day in np.unique(record.local_days):
            rows = np.flatnonzero(record.local_days == day)
            days.append(
                {
                    "month": record.month,
                    "local_day": int(day),
                    **_metric(record.y_true[rows], record.predictions[rows]),
                }
            )
    return {
        "pooled": _metric(truth, prediction),
        "by_horizon": by_horizon,
        "by_month": by_month,
        "month_horizon": cells,
        "local_days": days,
        "best_epochs": {record.month: record.best_epoch for record in records},
        "wall_seconds": {record.month: record.wall_seconds for record in records},
    }


def median_deep_summary(seed_summaries: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    if tuple(seed_summaries) != DEEP_SEEDS:
        raise R11S0Error("SEED_IDENTITY_INVALID")
    pooled = np.asarray([seed_summaries[seed]["pooled"]["mae_a"] for seed in DEEP_SEEDS])
    median_pooled = float(np.median(pooled))
    return {
        "pooled_mae_a": median_pooled,
        "pooled_seed_spread": float((np.max(pooled) - np.min(pooled)) / median_pooled),
        "by_horizon": [
            {
                "horizon_minutes": horizon,
                "mae_a": float(
                    np.median(
                        [seed_summaries[seed]["by_horizon"][position]["mae_a"] for seed in DEEP_SEEDS]
                    )
                ),
            }
            for position, horizon in enumerate(HORIZONS_MINUTES)
        ],
        "by_month": [
            {
                "month": month,
                "mae_a": float(
                    np.median(
                        [seed_summaries[seed]["by_month"][position]["mae_a"] for seed in DEEP_SEEDS]
                    )
                ),
            }
            for position, month in enumerate(DEVELOPMENT_MONTHS)
        ],
    }


def decide_backbone(
    *, station_hgb: Mapping[str, Any], deep_models: Mapping[str, Mapping[str, Any]]
) -> tuple[str, str | None, dict[str, Any]]:
    anchor = float(station_hgb["pooled"]["mae_a"])
    horizon_anchor = {
        int(item["horizon_minutes"]): float(item["mae_a"]) for item in station_hgb["by_horizon"]
    }
    month_anchor = {str(item["month"]): float(item["mae_a"]) for item in station_hgb["by_month"]}
    support: dict[str, Any] = {}
    eligible: list[tuple[str, float, int]] = []
    mixed = False
    for name in DEEP_ARCHITECTURES:
        summary = deep_models[name]["median"]
        pooled = float(summary["pooled_mae_a"])
        spread = float(summary["pooled_seed_spread"])
        worst_horizon = max(
            (float(item["mae_a"]) - horizon_anchor[int(item["horizon_minutes"])])
            / horizon_anchor[int(item["horizon_minutes"])]
            for item in summary["by_horizon"]
        )
        worst_month = max(
            (float(item["mae_a"]) - month_anchor[str(item["month"])])
            / month_anchor[str(item["month"])]
            for item in summary["by_month"]
        )
        is_eligible = (
            pooled <= 1.02 * anchor
            and worst_horizon <= 0.10
            and worst_month <= 0.10
            and spread <= 0.03
        )
        parameter_count = int(deep_models[name]["parameter_count"])
        support[name] = {
            "pooled_mae_a": pooled,
            "relative_pooled_vs_station_hgb": float((pooled - anchor) / anchor),
            "worst_horizon_relative_degradation": float(worst_horizon),
            "worst_month_relative_degradation": float(worst_month),
            "pooled_seed_spread": spread,
            "eligible": is_eligible,
            "parameter_count": parameter_count,
        }
        mixed |= pooled <= 1.02 * anchor and spread <= 0.03
        if is_eligible:
            eligible.append((name, pooled, parameter_count))
    if eligible:
        eligible.sort(key=lambda item: item[1])
        selected = eligible[0]
        if len(eligible) > 1:
            second = eligible[1]
            if (second[1] - selected[1]) / selected[1] < 0.0025 and second[2] < selected[2]:
                selected = second
        return "SELECT_STATION_BACKBONE", selected[0], support
    if mixed:
        return "MIXED_STATION_BACKBONE", None, support
    return "STOP_DEEP_CORE_ROUTE", None, support


def _load_station_months(
    *, protocol: DevelopmentExpertProtocol, interim_root: Path, processed_root: Path
) -> tuple[StationMonthData, ...]:
    output = []
    for contract in protocol.months:
        try:
            data = load_month_data(
                contract=contract, interim_root=interim_root, processed_root=processed_root
            )
        except DevelopmentExpertError as exc:
            raise R11S0Error(exc.reason_code) from exc
        output.append(station_month_from_frozen_data(data))
    return tuple(output)


def run_r11_s0(
    *,
    repo_root: str | Path,
    interim_root: str | Path,
    processed_root: str | Path,
    code_commit: str,
    progress: Callable[[str], None] | None = None,
) -> R11S0RunResult:
    root = Path(repo_root).resolve(strict=True)
    verify_r11_s0_implementation_commit(code_commit, repo_root=root)
    protocol = load_development_expert_protocol(
        root / "code/configs/acn_jpl_development_experts_2019.yaml"
    )
    if tuple(contract.month for contract in protocol.months) != DEVELOPMENT_MONTHS:
        raise R11S0Error("DEVELOPMENT_MONTH_IDENTITY_INVALID")
    validate_formal_device()
    parameter_counts = parameter_count_report(_import_torch())
    months = _load_station_months(
        protocol=protocol,
        interim_root=Path(interim_root).resolve(strict=True),
        processed_root=Path(processed_root).resolve(strict=True),
    )
    folds = build_station_folds(months)
    try:
        all_parameters = load_selected_hgb_parameters(protocol=protocol, repo_root=root)
    except DevelopmentExpertError as exc:
        raise R11S0Error(exc.reason_code) from exc
    hgb_parameters = MappingProxyType(
        {horizon: all_parameters[("M2", horizon)] for horizon in HORIZONS_MINUTES}
    )
    hgb_records = []
    for fold in folds:
        if progress:
            progress(f"R11_S0_PROGRESS=HGB; MONTH={fold.month}")
        hgb_records.append(predict_station_hgb_fold(fold=fold, parameters=hgb_parameters))
    station_hgb = summarize_predictions(tuple(hgb_records))
    deep_public: dict[str, Any] = {}
    fit_count = EXPECTED_HGB_FITS
    for architecture in DEEP_ARCHITECTURES:
        seed_summaries: dict[int, Mapping[str, Any]] = {}
        for seed in DEEP_SEEDS:
            records = []
            for fold in folds:
                if progress:
                    progress(
                        f"R11_S0_PROGRESS=START_DEEP; ARCH={architecture}; MONTH={fold.month}; SEED={seed}"
                    )
                records.append(
                    train_deep_fold(architecture=architecture, fold=fold, seed=seed, progress=progress)
                )
                fit_count += 1
            seed_summaries[seed] = summarize_predictions(tuple(records))
        deep_public[architecture] = {
            "parameter_count": int(parameter_counts[architecture]),
            "seeds": {str(seed): dict(seed_summaries[seed]) for seed in DEEP_SEEDS},
            "median": median_deep_summary(seed_summaries),
        }
    if fit_count != EXPECTED_FIT_COUNT:
        raise R11S0Error("FIT_COUNT_INVALID")
    decision, selected, support = decide_backbone(station_hgb=station_hgb, deep_models=deep_public)
    return R11S0RunResult(
        status="COMPLETE",
        decision=decision,
        selected_backbone=selected,
        parameter_counts=parameter_counts,
        station_hgb=station_hgb,
        deep_models=MappingProxyType(deep_public),
        decision_support=MappingProxyType(support),
        fit_count=fit_count,
    )
