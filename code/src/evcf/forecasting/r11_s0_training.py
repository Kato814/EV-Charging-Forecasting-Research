"""Controlled R11-S0 station-level backbone screening implementation.

The public controller is development-only and aggregate-only.  It consumes the
already frozen JPL development snapshots through the accepted artifact reader,
never traverses final-holdout months, never uses session-resolved predictors,
and never performs architecture/hyperparameter search.

The formal run is not authorized merely by the presence of this module.  A
reviewed executable and pinned external launcher are still required.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from threadpoolctl import threadpool_limits

from evcf.forecasting.acn_jpl_development_experts import load_selected_hgb_parameters
from evcf.forecasting.acn_jpl_development_experts_compat import (
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_gate1_models import make_frozen_estimator
from evcf.forecasting.r11_s0_contracts import (
    DEEP_SEEDS,
    DEVELOPMENT_MONTHS,
    EXPECTED_TEST_ORIGINS,
    EXPECTED_TOTAL_FITS,
    HORIZONS_MINUTES,
    R11S0ContractError,
    assert_test_origin_counts,
)
from evcf.forecasting.r11_s0_data import EncodedFold, encode_fold, view_from_month_data
from evcf.forecasting.r11_s0_models import MODEL_FACTORIES, make_model, trainable_parameter_count
from evcf.forecasting.r11_s0_screen import CandidateSummary, decide_backbone, validate_formal_device


def _metrics(y_true: np.ndarray, prediction: np.ndarray) -> dict[str, float | int | None]:
    if y_true.shape != prediction.shape or y_true.ndim != 1 or not y_true.size:
        raise R11S0ContractError("METRIC_SHAPE_INVALID")
    if not np.isfinite(y_true).all() or not np.isfinite(prediction).all():
        raise R11S0ContractError("NONFINITE_MODEL_OUTPUT")
    error = prediction - y_true
    absolute = np.abs(error)
    denominator = float(np.sum(np.abs(y_true)))
    return {
        "n": int(y_true.size),
        "mae_a": float(np.mean(absolute)),
        "rmse_a": float(np.sqrt(np.mean(np.square(error)))),
        "wape_ratio": None if denominator == 0.0 else float(np.sum(absolute) / denominator),
        "negative_prediction_count": int(np.sum(prediction < 0.0)),
    }


def _feature_matrix(fold: EncodedFold, partition: str, horizon_position: int) -> np.ndarray:
    history = getattr(fold, f"{partition}_history")
    issue = getattr(fold, f"{partition}_issue_context")
    target = getattr(fold, f"{partition}_target_context")[:, horizon_position, :]
    return np.concatenate((history.reshape(history.shape[0], -1), issue, target), axis=1).astype(
        np.float64
    )


def _run_station_hgb(
    folds: Mapping[str, EncodedFold],
    selected_params: Mapping[tuple[str, int], Mapping[str, Any]],
) -> tuple[dict[str, Any], int, dict[str, np.ndarray], dict[str, np.ndarray]]:
    predictions_by_month: dict[str, np.ndarray] = {}
    truths_by_month: dict[str, np.ndarray] = {}
    fit_count = 0
    for month in DEVELOPMENT_MONTHS:
        fold = folds[month]
        month_predictions = np.empty_like(fold.test_target, dtype=np.float64)
        month_truth = fold.target_standardizer.inverse(fold.test_target).astype(np.float64)
        for hpos, horizon in enumerate(HORIZONS_MINUTES):
            x_train = _feature_matrix(fold, "train", hpos)
            x_test = _feature_matrix(fold, "test", hpos)
            y_train = fold.target_standardizer.inverse(fold.train_target[:, hpos])
            estimator = make_frozen_estimator("hgb", selected_params[("M2", horizon)])
            with threadpool_limits(limits=1):
                estimator.fit(x_train, y_train)
                prediction = np.asarray(estimator.predict(x_test), dtype=np.float64)
            if prediction.shape != (x_test.shape[0],) or not np.isfinite(prediction).all():
                raise R11S0ContractError("STATION_HGB_OUTPUT_INVALID")
            month_predictions[:, hpos] = prediction
            fit_count += 1
        predictions_by_month[month] = month_predictions
        truths_by_month[month] = month_truth
    summary = _aggregate_single_prediction_set(truths_by_month, predictions_by_month)
    return summary, fit_count, truths_by_month, predictions_by_month


def _set_determinism(seed: int) -> Any:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - formal environment
        raise R11S0ContractError("TORCH_UNAVAILABLE") from exc
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)
    return torch


def _tensor_dataset(fold: EncodedFold, partition: str, torch: Any) -> Any:
    from torch.utils.data import TensorDataset

    return TensorDataset(
        torch.from_numpy(getattr(fold, f"{partition}_history")).float(),
        torch.from_numpy(getattr(fold, f"{partition}_issue_context")).float(),
        torch.from_numpy(getattr(fold, f"{partition}_target_context")).float(),
        torch.from_numpy(getattr(fold, f"{partition}_target")).float(),
    )


def _fit_deep_fold(
    *,
    model_name: str,
    seed: int,
    fold: EncodedFold,
    device: str,
) -> tuple[np.ndarray, int, float, int]:
    torch = _set_determinism(seed)
    from torch.utils.data import DataLoader

    model = make_model(model_name).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = torch.nn.SmoothL1Loss(beta=1.0, reduction="mean")
    generator = torch.Generator()
    generator.manual_seed(seed)
    train_loader = DataLoader(
        _tensor_dataset(fold, "train", torch),
        batch_size=256,
        shuffle=True,
        num_workers=0,
        generator=generator,
        drop_last=False,
    )
    validation_loader = DataLoader(
        _tensor_dataset(fold, "validation", torch),
        batch_size=256,
        shuffle=False,
        num_workers=0,
    )
    test_loader = DataLoader(
        _tensor_dataset(fold, "test", torch),
        batch_size=256,
        shuffle=False,
        num_workers=0,
    )
    best_state: dict[str, Any] | None = None
    best_validation = float("inf")
    best_epoch = 0
    stale_epochs = 0
    start = time.perf_counter()
    for epoch in range(1, 121):
        model.train()
        for history, issue_context, target_context, target in train_loader:
            history = history.to(device)
            issue_context = issue_context.to(device)
            target_context = target_context.to(device)
            target = target.to(device)
            optimizer.zero_grad(set_to_none=True)
            prediction = model(history, issue_context, target_context)
            loss = loss_fn(prediction, target)
            if not torch.isfinite(loss):
                raise R11S0ContractError("NONFINITE_TRAINING_LOSS")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        model.eval()
        absolute_errors: list[Any] = []
        with torch.no_grad():
            for history, issue_context, target_context, target in validation_loader:
                prediction = model(
                    history.to(device), issue_context.to(device), target_context.to(device)
                )
                absolute_errors.append(torch.abs(prediction - target.to(device)).cpu())
        validation_mae = float(torch.cat(absolute_errors).mean().item())
        if best_validation - validation_mae > 1e-4:
            best_validation = validation_mae
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= 12:
                break
    if best_state is None:
        raise R11S0ContractError("NO_VALID_CHECKPOINT")
    model.load_state_dict(best_state)
    model.eval()
    batches: list[np.ndarray] = []
    with torch.no_grad():
        for history, issue_context, target_context, _target in test_loader:
            output = model(
                history.to(device), issue_context.to(device), target_context.to(device)
            )
            batches.append(output.cpu().numpy().astype(np.float64))
    elapsed = float(time.perf_counter() - start)
    standardized_prediction = np.concatenate(batches, axis=0)
    if standardized_prediction.shape != fold.test_target.shape:
        raise R11S0ContractError("DEEP_OUTPUT_SHAPE_INVALID")
    prediction = fold.target_standardizer.inverse(standardized_prediction)
    if not np.isfinite(prediction).all():
        raise R11S0ContractError("NONFINITE_MODEL_OUTPUT")
    return prediction, best_epoch, elapsed, trainable_parameter_count(model)


def _aggregate_single_prediction_set(
    truths_by_month: Mapping[str, np.ndarray],
    predictions_by_month: Mapping[str, np.ndarray],
) -> dict[str, Any]:
    pooled_truth = np.concatenate([truths_by_month[month].reshape(-1) for month in DEVELOPMENT_MONTHS])
    pooled_prediction = np.concatenate(
        [predictions_by_month[month].reshape(-1) for month in DEVELOPMENT_MONTHS]
    )
    by_month = {
        month: _metrics(truths_by_month[month].reshape(-1), predictions_by_month[month].reshape(-1))
        for month in DEVELOPMENT_MONTHS
    }
    by_horizon: dict[int, dict[str, float | int | None]] = {}
    for hpos, horizon in enumerate(HORIZONS_MINUTES):
        truth = np.concatenate([truths_by_month[month][:, hpos] for month in DEVELOPMENT_MONTHS])
        prediction = np.concatenate(
            [predictions_by_month[month][:, hpos] for month in DEVELOPMENT_MONTHS]
        )
        by_horizon[horizon] = _metrics(truth, prediction)
    return {
        "pooled": _metrics(pooled_truth, pooled_prediction),
        "by_month": by_month,
        "by_horizon": by_horizon,
    }


def _deep_model_summary(
    *,
    model_name: str,
    seed_runs: Mapping[int, Mapping[str, Any]],
    hgb_summary: Mapping[str, Any],
    parameter_count: int,
) -> tuple[dict[str, Any], CandidateSummary]:
    pooled_seed_mae = np.asarray(
        [seed_runs[seed]["metrics"]["pooled"]["mae_a"] for seed in DEEP_SEEDS], dtype=float
    )
    pooled_median = float(np.median(pooled_seed_mae))
    horizon_medians: dict[int, float] = {}
    for horizon in HORIZONS_MINUTES:
        horizon_medians[horizon] = float(
            np.median(
                [seed_runs[seed]["metrics"]["by_horizon"][horizon]["mae_a"] for seed in DEEP_SEEDS]
            )
        )
    month_medians: dict[str, float] = {}
    for month in DEVELOPMENT_MONTHS:
        month_medians[month] = float(
            np.median(
                [seed_runs[seed]["metrics"]["by_month"][month]["mae_a"] for seed in DEEP_SEEDS]
            )
        )
    worst_horizon = max(
        horizon_medians[horizon] / float(hgb_summary["by_horizon"][horizon]["mae_a"]) - 1.0
        for horizon in HORIZONS_MINUTES
    )
    worst_month = max(
        month_medians[month] / float(hgb_summary["by_month"][month]["mae_a"]) - 1.0
        for month in DEVELOPMENT_MONTHS
    )
    seed_spread = float((np.max(pooled_seed_mae) - np.min(pooled_seed_mae)) / pooled_median)
    candidate = CandidateSummary(
        name=model_name,
        pooled_mae_a=pooled_median,
        worst_horizon_relative_degradation=float(worst_horizon),
        worst_month_relative_degradation=float(worst_month),
        seed_spread=seed_spread,
        parameter_count=parameter_count,
        folds_complete=True,
    )
    return (
        {
            "median_pooled_mae_a": pooled_median,
            "median_horizon_mae_a": horizon_medians,
            "median_month_mae_a": month_medians,
            "seed_spread": seed_spread,
            "worst_horizon_relative_degradation_vs_StationHGB": float(worst_horizon),
            "worst_month_relative_degradation_vs_StationHGB": float(worst_month),
            "parameter_count": parameter_count,
            "seeds": {str(seed): dict(seed_runs[seed]) for seed in DEEP_SEEDS},
        },
        candidate,
    )


def run_r11_s0(
    *,
    authorized: bool,
    interim_root: str | Path,
    processed_root: str | Path,
    repo_root: str | Path = ".",
    protocol_path: str | Path = "code/configs/acn_jpl_development_experts_2019.yaml",
) -> dict[str, Any]:
    if authorized is not True:
        raise R11S0ContractError("R11_S0_RUN_NOT_AUTHORIZED")
    device = validate_formal_device()
    repo = Path(repo_root).resolve(strict=True)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    protocol = load_development_expert_protocol(protocol_path)
    if tuple(contract.month for contract in protocol.months) != DEVELOPMENT_MONTHS:
        raise R11S0ContractError("DEVELOPMENT_MONTH_IDENTITY_INVALID")
    views = {}
    for contract in protocol.months:
        month_data = load_month_data(
            contract=contract,
            interim_root=interim,
            processed_root=processed,
        )
        views[contract.month] = view_from_month_data(month_data)
    folds = {month: encode_fold(views, month) for month in DEVELOPMENT_MONTHS}
    assert_test_origin_counts({month: int(folds[month].test_issue_times.size) for month in DEVELOPMENT_MONTHS})

    selected_params = load_selected_hgb_parameters(protocol=protocol, repo_root=repo)
    hgb_summary, fit_count, truths_by_month, _hgb_predictions = _run_station_hgb(
        folds, selected_params
    )

    deep_public: dict[str, Any] = {}
    candidates: dict[str, CandidateSummary] = {}
    for model_name in MODEL_FACTORIES:
        seed_runs: dict[int, Mapping[str, Any]] = {}
        parameter_count: int | None = None
        for seed in DEEP_SEEDS:
            predictions_by_month: dict[str, np.ndarray] = {}
            best_epochs: dict[str, int] = {}
            wall_seconds: dict[str, float] = {}
            for month in DEVELOPMENT_MONTHS:
                prediction, best_epoch, elapsed, count = _fit_deep_fold(
                    model_name=model_name,
                    seed=seed,
                    fold=folds[month],
                    device=device["device"],
                )
                if parameter_count is None:
                    parameter_count = count
                elif parameter_count != count:
                    raise R11S0ContractError("PARAMETER_COUNT_DRIFT")
                predictions_by_month[month] = prediction
                best_epochs[month] = best_epoch
                wall_seconds[month] = elapsed
                fit_count += 1
            seed_runs[seed] = {
                "metrics": _aggregate_single_prediction_set(truths_by_month, predictions_by_month),
                "best_epoch_by_month": best_epochs,
                "wall_seconds_by_month": wall_seconds,
            }
        if parameter_count is None:
            raise R11S0ContractError("PARAMETER_COUNT_MISSING")
        public, candidate = _deep_model_summary(
            model_name=model_name,
            seed_runs=seed_runs,
            hgb_summary=hgb_summary,
            parameter_count=parameter_count,
        )
        deep_public[model_name] = public
        candidates[model_name] = candidate

    if fit_count != EXPECTED_TOTAL_FITS:
        raise R11S0ContractError("FIT_COUNT_INVALID")
    decision, selected, support = decide_backbone(
        float(hgb_summary["pooled"]["mae_a"]), candidates
    )
    return {
        "schema_version": "evcf-r11-s0-station-backbone-summary/v1",
        "status": "COMPLETE",
        "decision": decision,
        "selected_backbone": selected,
        "fit_count": fit_count,
        "development_months": list(DEVELOPMENT_MONTHS),
        "final_holdout_accessed": False,
        "session_predictors_used": False,
        "station_hgb": hgb_summary,
        "deep_models": deep_public,
        "decision_support": support,
        "environment": device,
    }
