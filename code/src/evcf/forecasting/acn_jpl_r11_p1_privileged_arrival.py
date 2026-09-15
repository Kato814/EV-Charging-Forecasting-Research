"""R11-P1 horizon-targeted privileged future-arrival supervision for JPL/ACN."""

from __future__ import annotations

import copy
import math
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from evcf.forecasting.acn_jpl_development_experts import (
    DevelopmentExpertError,
    DevelopmentExpertProtocol,
    load_selected_hgb_parameters,
)
from evcf.forecasting.acn_jpl_development_experts_compat import (
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_r11_s0_backbone import (
    predict_station_hgb_fold,
    summarize_predictions,
)
from evcf.forecasting.acn_jpl_r11_s0_common import (
    BATCH_SIZE,
    CONTEXT_LENGTH,
    DEEP_SEEDS,
    DEVELOPMENT_MONTHS,
    FINAL_HOLDOUT_MONTHS,
    GRADIENT_CLIP_NORM,
    HISTORY_CHANNELS,
    LEARNING_RATE,
    MAX_EPOCHS,
    MAX_HORIZON_MINUTES,
    MIN_VALIDATION_IMPROVEMENT,
    PATIENCE,
    TARGET_CONTEXT_WIDTH,
    TEST_START_LOCAL_DAY,
    TIMEZONE_NAME,
    TRAIN_LAST_LOCAL_DAY,
    VALIDATION_FIRST_LOCAL_DAY,
    VALIDATION_LAST_LOCAL_DAY,
    WEIGHT_DECAY,
)
from evcf.forecasting.acn_jpl_r11_s0_data import (
    FoldScaler,
    StationFold,
    StationMonthData,
    build_station_folds,
    fit_scaler,
    station_month_from_frozen_data,
    transform_history,
)
from evcf.forecasting.acn_jpl_r11_s0_models import (
    FoldPrediction,
    import_torch,
    validate_formal_device,
)
from evcf.forecasting.acn_jpl_structured_baseline import (
    StructuredBaselineError,
    load_structured_protocol,
)
from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    MechanismProbeError,
    _build_contributions,
    _component_labels,
    _load_current_sessions,
)

LONG_HORIZONS = (60, 120, 240)
LONG_POSITIONS = (2, 3, 4)
AUXILIARY_WEIGHT = 0.5
EXPECTED_DEEP_FITS = 24
EXPECTED_HGB_REPLAY_FITS = 20
EXPECTED_TOTAL_FITS = 44
_ZONE = ZoneInfo(TIMEZONE_NAME)

IMPLEMENTATION_PATHS = (
    "docs/JPL_R11_P1_HORIZON_TARGETED_PRIVILEGED_ARRIVAL_PROTOCOL_20260915.md",
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/configs/acn_jpl_structured_baseline_2019.yaml",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_r11_s0_common.py",
    "code/src/evcf/forecasting/acn_jpl_r11_s0_data.py",
    "code/src/evcf/forecasting/acn_jpl_r11_s0_models.py",
    "code/src/evcf/forecasting/acn_jpl_r11_s0_backbone.py",
    "code/src/evcf/forecasting/acn_jpl_structured_baseline.py",
    "code/src/evcf/forecasting/acn_jpl_structured_mechanism_probe.py",
    "code/src/evcf/forecasting/acn_jpl_r11_p1_privileged_arrival.py",
    "scripts/check_r11_p1_environment.py",
    "scripts/run_jpl_r11_p1_privileged_arrival.py",
)


class R11P1Error(RuntimeError):
    """Identifier-free failure safe for public R11-P1 output."""

    def __init__(self, reason_code: str) -> None:
        if not isinstance(reason_code, str) or not reason_code.replace("_", "").isalnum():
            reason_code = "UNEXPECTED_ERROR"
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class P1Month:
    station: StationMonthData
    arrival_labels: np.ndarray


@dataclass(frozen=True, slots=True)
class P1Scaler:
    station: FoldScaler
    arrival_mean: float
    arrival_scale: float


@dataclass(frozen=True, slots=True)
class P1Fold:
    month: str
    train_history: np.ndarray
    train_issue_context: np.ndarray
    train_target_context: np.ndarray
    train_labels: np.ndarray
    train_arrival_labels: np.ndarray
    validation_history: np.ndarray
    validation_issue_context: np.ndarray
    validation_target_context: np.ndarray
    validation_labels: np.ndarray
    test_history: np.ndarray
    test_issue_context: np.ndarray
    test_target_context: np.ndarray
    test_labels: np.ndarray
    test_issue_times: np.ndarray
    test_local_days: np.ndarray
    scaler: P1Scaler


@dataclass(frozen=True, slots=True)
class LongFoldPrediction:
    month: str
    issue_times: np.ndarray
    local_days: np.ndarray
    y_true: np.ndarray
    predictions: np.ndarray
    best_epoch: int
    wall_seconds: float


@dataclass(frozen=True, slots=True)
class R11P1RunResult:
    status: str
    decision: str
    station_hgb: Mapping[str, Any]
    arm_b: Mapping[str, Any]
    arm_c: Mapping[str, Any]
    decision_support: Mapping[str, Any]
    model_parameter_count: int
    deep_fit_count: int
    hgb_replay_fit_count: int
    fit_count: int
    holdout_accessed: bool = False
    session_predictors_used: bool = False

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "evcf-jpl-r11-p1-summary/v1",
            "status": self.status,
            "decision": self.decision,
            "station_hgb": dict(self.station_hgb),
            "arm_b": dict(self.arm_b),
            "arm_c": dict(self.arm_c),
            "decision_support": dict(self.decision_support),
            "model_parameter_count": self.model_parameter_count,
            "deep_fit_count": self.deep_fit_count,
            "hgb_replay_fit_count": self.hgb_replay_fit_count,
            "fit_count": self.fit_count,
            "development_months": list(DEVELOPMENT_MONTHS),
            "final_holdout_months": list(FINAL_HOLDOUT_MONTHS),
            "long_horizons_minutes": list(LONG_HORIZONS),
            "auxiliary_weight": AUXILIARY_WEIGHT,
            "holdout_accessed": self.holdout_accessed,
            "session_predictors_used": self.session_predictors_used,
            "hyperparameter_search": False,
            "prediction_clipping": False,
            "prediction_calibration": False,
            "model_ensemble": False,
        }


def verify_implementation_commit(code_commit: str, *, repo_root: str | Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R11P1Error("IMPLEMENTATION_DRIFT")
    root = Path(repo_root).resolve(strict=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if head.returncode != 0 or head.stdout.strip() != code_commit:
        raise R11P1Error("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R11P1Error("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode != 0:
            raise R11P1Error("IMPLEMENTATION_DRIFT")
        clean = subprocess.run(
            ["git", "diff", "--quiet", "--no-ext-diff", code_commit, "--", relative],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if clean.returncode != 0:
            raise R11P1Error("IMPLEMENTATION_DRIFT")


def _month_start(month: str) -> int:
    year, number = (int(value) for value in month.split("-"))
    return int(datetime(year, number, 1, tzinfo=_ZONE).timestamp())


def _day_start(month: str, day: int) -> int:
    year, number = (int(value) for value in month.split("-"))
    return int(datetime(year, number, day, tzinfo=_ZONE).timestamp())


def _history_eligible(month: StationMonthData) -> np.ndarray:
    return month.issue_times >= _month_start(month.month) + 24 * 60 * 60


def _arrival_scaler(labels: np.ndarray) -> tuple[float, float]:
    values = np.asarray(labels, dtype=np.float64).reshape(-1)
    if not len(values) or not np.isfinite(values).all() or np.any(values < 0):
        raise R11P1Error("ARRIVAL_NORMALIZATION_INVALID")
    scale = float(np.std(values))
    return float(np.mean(values)), scale if scale > 1e-8 else 1.0


def _build_p1_folds(months: Sequence[P1Month]) -> tuple[P1Fold, ...]:
    by_name = {item.station.month: item for item in months}
    if tuple(by_name) != DEVELOPMENT_MONTHS:
        raise R11P1Error("DEVELOPMENT_MONTH_IDENTITY_INVALID")
    folds: list[P1Fold] = []
    expected_test = {
        "2019-01": 1305,
        "2019-04": 1180,
        "2019-07": 1294,
        "2019-10": 1296,
    }
    for position, month_name in enumerate(DEVELOPMENT_MONTHS):
        current = by_name[month_name]
        station = current.station
        train_cutoff = _day_start(month_name, 15)
        test_cutoff = _day_start(month_name, 18)
        eligible = _history_eligible(station)
        current_train = np.flatnonzero(
            eligible
            & (station.local_days <= TRAIN_LAST_LOCAL_DAY)
            & (station.issue_times + MAX_HORIZON_MINUTES * 60 <= train_cutoff)
        ).astype(np.int64)
        validation = np.flatnonzero(
            eligible
            & (station.local_days >= VALIDATION_FIRST_LOCAL_DAY)
            & (station.local_days <= VALIDATION_LAST_LOCAL_DAY)
            & (station.issue_times + MAX_HORIZON_MINUTES * 60 <= test_cutoff)
        ).astype(np.int64)
        test = np.flatnonzero(station.local_days >= TEST_START_LOCAL_DAY).astype(np.int64)
        if len(test) != expected_test[month_name] or not len(current_train) or not len(validation):
            raise R11P1Error("CHRONOLOGY_INVALID")

        train_months: list[P1Month] = []
        train_rows: list[np.ndarray] = []
        for earlier_name in DEVELOPMENT_MONTHS[:position]:
            earlier = by_name[earlier_name]
            idx = np.flatnonzero(_history_eligible(earlier.station)).astype(np.int64)
            if not len(idx):
                raise R11P1Error("CHRONOLOGY_INVALID")
            train_months.append(earlier)
            train_rows.append(idx)
        train_months.append(current)
        train_rows.append(current_train)

        h_raw = np.concatenate(
            [item.station.history_raw[idx] for item, idx in zip(train_months, train_rows, strict=True)]
        )
        h_mask = np.concatenate(
            [item.station.history_mask[idx] for item, idx in zip(train_months, train_rows, strict=True)]
        )
        train_issue = np.concatenate(
            [item.station.issue_context[idx] for item, idx in zip(train_months, train_rows, strict=True)]
        )
        train_target = np.concatenate(
            [
                item.station.target_context[idx][:, LONG_POSITIONS]
                for item, idx in zip(train_months, train_rows, strict=True)
            ]
        )
        train_labels = np.concatenate(
            [
                item.station.labels[idx][:, LONG_POSITIONS]
                for item, idx in zip(train_months, train_rows, strict=True)
            ]
        )
        train_arrival = np.concatenate(
            [
                item.arrival_labels[idx][:, LONG_POSITIONS]
                for item, idx in zip(train_months, train_rows, strict=True)
            ]
        )
        station_scaler = fit_scaler(h_raw, h_mask, train_labels)
        arrival_mean, arrival_scale = _arrival_scaler(train_arrival)
        scaler = P1Scaler(
            station=station_scaler,
            arrival_mean=arrival_mean,
            arrival_scale=arrival_scale,
        )

        if np.max(station.issue_times[current_train] + MAX_HORIZON_MINUTES * 60) > train_cutoff:
            raise R11P1Error("TEMPORAL_LEAKAGE")
        if np.max(station.issue_times[validation] + MAX_HORIZON_MINUTES * 60) > test_cutoff:
            raise R11P1Error("TEMPORAL_LEAKAGE")

        folds.append(
            P1Fold(
                month=month_name,
                train_history=transform_history(h_raw, h_mask, station_scaler),
                train_issue_context=train_issue.astype(np.float32),
                train_target_context=train_target.astype(np.float32),
                train_labels=train_labels,
                train_arrival_labels=train_arrival,
                validation_history=transform_history(
                    station.history_raw[validation], station.history_mask[validation], station_scaler
                ),
                validation_issue_context=station.issue_context[validation].astype(np.float32),
                validation_target_context=station.target_context[validation][:, LONG_POSITIONS].astype(
                    np.float32
                ),
                validation_labels=station.labels[validation][:, LONG_POSITIONS],
                test_history=transform_history(
                    station.history_raw[test], station.history_mask[test], station_scaler
                ),
                test_issue_context=station.issue_context[test].astype(np.float32),
                test_target_context=station.target_context[test][:, LONG_POSITIONS].astype(np.float32),
                test_labels=station.labels[test][:, LONG_POSITIONS],
                test_issue_times=station.issue_times[test],
                test_local_days=station.local_days[test],
                scaler=scaler,
            )
        )
    return tuple(folds)


def _load_p1_months(
    *,
    expert_protocol: DevelopmentExpertProtocol,
    repo_root: Path,
    interim_root: Path,
    processed_root: Path,
) -> tuple[tuple[P1Month, ...], tuple[StationMonthData, ...]]:
    try:
        structured_protocol = load_structured_protocol(
            repo_root / "code/configs/acn_jpl_structured_baseline_2019.yaml"
        )
    except StructuredBaselineError as exc:
        raise R11P1Error(exc.reason_code) from exc
    if tuple(contract.month for contract in structured_protocol.months) != DEVELOPMENT_MONTHS:
        raise R11P1Error("STRUCTURED_PROTOCOL_INVALID")
    structured_by_month = {contract.month: contract for contract in structured_protocol.months}

    p1_months: list[P1Month] = []
    station_months: list[StationMonthData] = []
    for contract in expert_protocol.months:
        structured = structured_by_month.get(contract.month)
        if (
            structured is None
            or structured.processed_snapshot_sha256 != contract.processed_snapshot_sha256
        ):
            raise R11P1Error("STRUCTURED_PROTOCOL_INVALID")
        try:
            data = load_month_data(
                contract=contract,
                interim_root=interim_root,
                processed_root=processed_root,
            )
        except DevelopmentExpertError as exc:
            raise R11P1Error(exc.reason_code) from exc
        station = station_month_from_frozen_data(data)
        try:
            sessions = _load_current_sessions(
                interim_root / contract.month / "cleaned_sessions.jsonl.gz",
                expected_count=structured.cleaned_session_count,
            )
            contributions = _build_contributions(sessions, data.issue_times)
            existing, arrival, _session_maps = _component_labels(
                issue_times=data.issue_times,
                total_labels=data.labels,
                contributions=contributions,
            )
        except MechanismProbeError as exc:
            raise R11P1Error(exc.reason_code) from exc
        if (
            existing.shape != data.labels.shape
            or arrival.shape != data.labels.shape
            or not np.isfinite(existing).all()
            or not np.isfinite(arrival).all()
            or np.any(existing < 0)
            or np.any(arrival < 0)
            or not np.allclose(existing + arrival, data.labels, rtol=0.0, atol=1e-6)
        ):
            raise R11P1Error("PRIVILEGED_LABEL_INVALID")
        station_months.append(station)
        p1_months.append(P1Month(station=station, arrival_labels=arrival))
    return tuple(p1_months), tuple(station_months)


def _configure_determinism(torch, seed: int) -> None:
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends, "cuda") and hasattr(torch.backends.cuda, "matmul"):
        torch.backends.cuda.matmul.allow_tf32 = False
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
    if hasattr(torch, "set_float32_matmul_precision"):
        torch.set_float32_matmul_precision("highest")


def make_p1_tcn(torch):
    nn = torch.nn
    functional = torch.nn.functional

    class CausalConv(nn.Module):
        def __init__(self, input_width: int, output_width: int, dilation: int) -> None:
            super().__init__()
            self.left = 2 * dilation
            self.conv = nn.Conv1d(input_width, output_width, 3, dilation=dilation)

        def forward(self, x):
            return self.conv(functional.pad(x, (self.left, 0)))

    class Block(nn.Module):
        def __init__(self, input_width: int, dilation: int) -> None:
            super().__init__()
            self.conv1 = CausalConv(input_width, 64, dilation)
            self.conv2 = CausalConv(64, 64, dilation)
            self.dropout = nn.Dropout(0.10)
            self.skip = nn.Identity() if input_width == 64 else nn.Conv1d(input_width, 64, 1)

        def forward(self, x):
            skip = self.skip(x)
            x = self.dropout(torch.relu(self.conv1(x)))
            x = self.dropout(torch.relu(self.conv2(x)))
            return torch.relu(x + skip)

    class Head(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(64 + 5 + TARGET_CONTEXT_WIDTH, 64),
                nn.ReLU(),
                nn.Linear(64, 32),
                nn.ReLU(),
                nn.Linear(32, 1),
            )

        def forward(self, latent, issue_context, target_context):
            count = len(LONG_HORIZONS)
            latent = latent.unsqueeze(1).expand(-1, count, -1)
            issue = issue_context.unsqueeze(1).expand(-1, count, -1)
            return self.net(torch.cat((latent, issue, target_context), dim=-1)).squeeze(-1)

    class Model(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            blocks = []
            width = HISTORY_CHANNELS
            for dilation in (1, 2, 4, 8, 16):
                blocks.append(Block(width, dilation))
                width = 64
            self.encoder = nn.Sequential(*blocks)
            self.total_head = Head()
            self.arrival_head = Head()

        def encode(self, history):
            return self.encoder(history.transpose(1, 2))[:, :, -1]

        def forward(self, history, issue_context, target_context):
            latent = self.encode(history)
            return (
                self.total_head(latent, issue_context, target_context),
                self.arrival_head(latent, issue_context, target_context),
            )

        def predict_total(self, history, issue_context, target_context):
            latent = self.encode(history)
            return self.total_head(latent, issue_context, target_context)

    return Model()


def count_trainable_parameters(model) -> int:
    return int(sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad))


def validate_model_environment(torch=None) -> Mapping[str, Any]:
    torch = import_torch() if torch is None else torch
    device_info = dict(validate_formal_device())
    _configure_determinism(torch, DEEP_SEEDS[0])
    device = torch.device("cuda:0")
    model = make_p1_tcn(torch).to(device=device, dtype=torch.float32)
    history = torch.zeros((2, CONTEXT_LENGTH, HISTORY_CHANNELS), device=device)
    issue = torch.zeros((2, 5), device=device)
    target = torch.zeros((2, len(LONG_HORIZONS), TARGET_CONTEXT_WIDTH), device=device)
    total, arrival = model(history, issue, target)
    if total.shape != (2, 3) or arrival.shape != (2, 3):
        raise R11P1Error("MODEL_SHAPE_INVALID")
    loss = total.square().mean() + AUXILIARY_WEIGHT * arrival.square().mean()
    try:
        loss.backward()
        torch.cuda.synchronize(device)
    except RuntimeError as exc:
        raise R11P1Error("DETERMINISTIC_BACKWARD_UNAVAILABLE") from exc
    return MappingProxyType(
        {
            **device_info,
            "parameter_count": count_trainable_parameters(model),
            "deterministic_backward_smoke": True,
        }
    )


def _tensor_bundle(torch, device, fold: P1Fold, split: str):
    history = getattr(fold, f"{split}_history")
    issue = getattr(fold, f"{split}_issue_context")
    target = getattr(fold, f"{split}_target_context")
    labels = getattr(fold, f"{split}_labels")
    total = (labels - fold.scaler.station.target_mean) / fold.scaler.station.target_scale
    return tuple(
        torch.as_tensor(value, dtype=torch.float32, device=device)
        for value in (history, issue, target, total)
    )


def _validation_mae(torch, model, bundle) -> float:
    history, issue, target, labels = bundle
    model.eval()
    total_absolute = 0.0
    count = 0
    with torch.no_grad():
        for start in range(0, len(history), BATCH_SIZE):
            stop = min(start + BATCH_SIZE, len(history))
            prediction = model.predict_total(
                history[start:stop], issue[start:stop], target[start:stop]
            )
            total_absolute += float(torch.sum(torch.abs(prediction - labels[start:stop])).item())
            count += (stop - start) * len(LONG_HORIZONS)
    if count <= 0:
        raise R11P1Error("VALIDATION_INVALID")
    return total_absolute / count


def train_p1_fold(
    *,
    fold: P1Fold,
    seed: int,
    auxiliary_weight: float,
    progress: Callable[[str], None] | None = None,
) -> LongFoldPrediction:
    if auxiliary_weight not in (0.0, AUXILIARY_WEIGHT):
        raise R11P1Error("AUXILIARY_WEIGHT_INVALID")
    torch = import_torch()
    if not bool(torch.cuda.is_available()):
        raise R11P1Error("CUDA_NOT_AVAILABLE")
    _configure_determinism(torch, seed)
    device = torch.device("cuda:0")
    model = make_p1_tcn(torch).to(device=device, dtype=torch.float32)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
    )
    loss_fn = torch.nn.SmoothL1Loss(beta=1.0, reduction="mean")

    train = _tensor_bundle(torch, device, fold, "train")
    validation = _tensor_bundle(torch, device, fold, "validation")
    test = _tensor_bundle(torch, device, fold, "test")
    h_train, i_train, t_train, y_train = train
    arrival_std = (
        fold.train_arrival_labels - fold.scaler.arrival_mean
    ) / fold.scaler.arrival_scale
    a_train = torch.as_tensor(arrival_std, dtype=torch.float32, device=device)

    rng = np.random.default_rng(seed)
    best_score = math.inf
    best_epoch = 0
    best_state = None
    stale = 0
    started = time.perf_counter()

    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        order = rng.permutation(len(h_train)).astype(np.int64)
        for start in range(0, len(order), BATCH_SIZE):
            rows = torch.as_tensor(
                order[start : start + BATCH_SIZE], dtype=torch.long, device=device
            )
            optimizer.zero_grad(set_to_none=True)
            total_pred, arrival_pred = model(
                h_train.index_select(0, rows),
                i_train.index_select(0, rows),
                t_train.index_select(0, rows),
            )
            total_loss = loss_fn(total_pred, y_train.index_select(0, rows))
            if auxiliary_weight > 0.0:
                arrival_loss = loss_fn(arrival_pred, a_train.index_select(0, rows))
                loss = total_loss + auxiliary_weight * arrival_loss
            else:
                loss = total_loss
            if not bool(torch.isfinite(loss).item()):
                raise R11P1Error("MODEL_FIT_INVALID")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), GRADIENT_CLIP_NORM)
            optimizer.step()
        score = _validation_mae(torch, model, validation)
        if best_score - score >= MIN_VALIDATION_IMPROVEMENT:
            best_score = score
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            stale = 0
        else:
            stale += 1
        if progress is not None and (epoch == 1 or epoch % 10 == 0 or stale >= PATIENCE):
            arm = "C" if auxiliary_weight > 0 else "B"
            progress(
                f"R11_P1_PROGRESS=DEEP_FIT; ARM={arm}; MONTH={fold.month}; "
                f"SEED={seed}; EPOCH={epoch}; BEST_EPOCH={best_epoch}; "
                f"VAL_TOTAL_MAE_STD={best_score:.8f}"
            )
        if stale >= PATIENCE:
            break

    if best_state is None:
        raise R11P1Error("EARLY_STOP_INVALID")
    model.load_state_dict(best_state)
    model.eval()
    h_test, i_test, t_test, _y_test = test
    pred_std = np.empty((len(h_test), len(LONG_HORIZONS)), dtype=np.float64)
    with torch.no_grad():
        for start in range(0, len(h_test), BATCH_SIZE):
            stop = min(start + BATCH_SIZE, len(h_test))
            values = model.predict_total(
                h_test[start:stop], i_test[start:stop], t_test[start:stop]
            )
            pred_std[start:stop] = values.detach().cpu().numpy().astype(np.float64)
    predictions = (
        pred_std * fold.scaler.station.target_scale + fold.scaler.station.target_mean
    )
    if predictions.shape != fold.test_labels.shape or not np.isfinite(predictions).all():
        raise R11P1Error("MODEL_OUTPUT_INVALID")
    return LongFoldPrediction(
        month=fold.month,
        issue_times=fold.test_issue_times,
        local_days=fold.test_local_days,
        y_true=fold.test_labels,
        predictions=predictions,
        best_epoch=best_epoch,
        wall_seconds=float(time.perf_counter() - started),
    )


def _metric(y: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y, dtype=np.float64).reshape(-1)
    prediction = np.asarray(prediction, dtype=np.float64).reshape(-1)
    if (
        y.shape != prediction.shape
        or not len(y)
        or not np.isfinite(y).all()
        or not np.isfinite(prediction).all()
    ):
        raise R11P1Error("METRIC_INPUT_INVALID")
    error = prediction - y
    absolute = np.abs(error)
    denominator = float(np.sum(np.abs(y)))
    return {
        "n": int(len(y)),
        "mae_a": float(np.mean(absolute)),
        "rmse_a": float(np.sqrt(np.mean(np.square(error)))),
        "wape_ratio": None if denominator <= 0 else float(np.sum(absolute) / denominator),
        "negative_prediction_count": int(np.sum(prediction < 0)),
        "negative_prediction_fraction": float(np.mean(prediction < 0)),
    }


def summarize_long(records: Sequence[LongFoldPrediction]) -> dict[str, Any]:
    if tuple(record.month for record in records) != DEVELOPMENT_MONTHS:
        raise R11P1Error("SUMMARY_IDENTITY_INVALID")
    by_horizon = []
    for position, horizon in enumerate(LONG_HORIZONS):
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
        {"month": record.month, **_metric(record.y_true, record.predictions)}
        for record in records
    ]
    local_days = []
    for record in records:
        for day in np.unique(record.local_days):
            rows = np.flatnonzero(record.local_days == day)
            local_days.append(
                {
                    "month": record.month,
                    "local_day": int(day),
                    **_metric(record.y_true[rows], record.predictions[rows]),
                }
            )
    return {
        "pooled": _metric(
            np.concatenate([record.y_true for record in records]),
            np.concatenate([record.predictions for record in records]),
        ),
        "by_horizon": by_horizon,
        "by_month": by_month,
        "local_days": local_days,
        "best_epochs": {record.month: record.best_epoch for record in records},
        "wall_seconds": {record.month: record.wall_seconds for record in records},
    }


def _median_long(seed_summaries: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    if tuple(seed_summaries) != DEEP_SEEDS:
        raise R11P1Error("SEED_IDENTITY_INVALID")
    pooled = np.asarray(
        [seed_summaries[seed]["pooled"]["mae_a"] for seed in DEEP_SEEDS],
        dtype=np.float64,
    )
    median = float(np.median(pooled))
    return {
        "pooled_mae_a": median,
        "pooled_seed_spread": float((np.max(pooled) - np.min(pooled)) / median),
        "by_horizon": [
            {
                "horizon_minutes": horizon,
                "mae_a": float(
                    np.median(
                        [
                            seed_summaries[seed]["by_horizon"][position]["mae_a"]
                            for seed in DEEP_SEEDS
                        ]
                    )
                ),
            }
            for position, horizon in enumerate(LONG_HORIZONS)
        ],
        "by_month": [
            {
                "month": month,
                "mae_a": float(
                    np.median(
                        [
                            seed_summaries[seed]["by_month"][position]["mae_a"]
                            for seed in DEEP_SEEDS
                        ]
                    )
                ),
            }
            for position, month in enumerate(DEVELOPMENT_MONTHS)
        ],
    }


def _hybrid_records(
    hgb_records: Sequence[FoldPrediction],
    long_records: Sequence[LongFoldPrediction],
) -> tuple[FoldPrediction, ...]:
    if len(hgb_records) != len(long_records):
        raise R11P1Error("SUMMARY_IDENTITY_INVALID")
    output = []
    for hgb, long in zip(hgb_records, long_records, strict=True):
        if (
            hgb.month != long.month
            or not np.array_equal(hgb.issue_times, long.issue_times)
            or not np.array_equal(hgb.local_days, long.local_days)
            or not np.allclose(hgb.y_true[:, LONG_POSITIONS], long.y_true, rtol=0, atol=0)
        ):
            raise R11P1Error("SUMMARY_IDENTITY_INVALID")
        predictions = np.array(hgb.predictions, copy=True)
        predictions[:, LONG_POSITIONS] = long.predictions
        output.append(
            FoldPrediction(
                month=hgb.month,
                issue_times=hgb.issue_times,
                local_days=hgb.local_days,
                y_true=hgb.y_true,
                predictions=predictions,
                best_epoch=long.best_epoch,
                wall_seconds=long.wall_seconds,
            )
        )
    return tuple(output)


def _long_hgb_metric(hgb_records: Sequence[FoldPrediction]) -> dict[str, Any]:
    return _metric(
        np.concatenate([record.y_true[:, LONG_POSITIONS] for record in hgb_records]),
        np.concatenate([record.predictions[:, LONG_POSITIONS] for record in hgb_records]),
    )


def decide(
    *,
    hgb_records: Sequence[FoldPrediction],
    arm_b_seeds: Mapping[int, Mapping[str, Any]],
    arm_c_seeds: Mapping[int, Mapping[str, Any]],
    arm_c_hybrid_seeds: Mapping[int, Mapping[str, Any]],
) -> tuple[str, dict[str, Any]]:
    b = _median_long(arm_b_seeds)
    c = _median_long(arm_c_seeds)
    if tuple(arm_c_hybrid_seeds) != DEEP_SEEDS:
        raise R11P1Error("SEED_IDENTITY_INVALID")
    hybrid_pooled = np.asarray(
        [arm_c_hybrid_seeds[seed]["pooled"]["mae_a"] for seed in DEEP_SEEDS],
        dtype=np.float64,
    )
    hybrid_median = float(np.median(hybrid_pooled))
    hgb_summary = summarize_predictions(hgb_records)
    hgb_pooled = float(hgb_summary["pooled"]["mae_a"])
    hgb_long = float(_long_hgb_metric(hgb_records)["mae_a"])

    improvement = (float(b["pooled_mae_a"]) - float(c["pooled_mae_a"])) / float(
        b["pooled_mae_a"]
    )
    horizon_relative = []
    horizon_wins = 0
    for b_item, c_item in zip(b["by_horizon"], c["by_horizon"], strict=True):
        if b_item["horizon_minutes"] != c_item["horizon_minutes"]:
            raise R11P1Error("SUMMARY_IDENTITY_INVALID")
        b_mae = float(b_item["mae_a"])
        c_mae = float(c_item["mae_a"])
        horizon_wins += c_mae < b_mae
        horizon_relative.append((c_mae - b_mae) / b_mae)
    month_wins = sum(
        float(c_item["mae_a"]) < float(b_item["mae_a"])
        for b_item, c_item in zip(b["by_month"], c["by_month"], strict=True)
    )
    paired_seed_wins = sum(
        float(arm_c_seeds[seed]["pooled"]["mae_a"])
        < float(arm_b_seeds[seed]["pooled"]["mae_a"])
        for seed in DEEP_SEEDS
    )
    support = {
        "arm_b_median": b,
        "arm_c_median": c,
        "median_long_mae_improvement_fraction": float(improvement),
        "long_horizon_wins": int(horizon_wins),
        "worst_long_horizon_relative_degradation": float(max(horizon_relative)),
        "month_wins": int(month_wins),
        "paired_seed_wins": int(paired_seed_wins),
        "arm_c_seed_spread": float(c["pooled_seed_spread"]),
        "station_hgb_long_pooled_mae_a": hgb_long,
        "arm_c_hybrid_median_pooled_mae_a": hybrid_median,
        "station_hgb_all_horizon_pooled_mae_a": hgb_pooled,
    }
    if float(c["pooled_mae_a"]) >= float(b["pooled_mae_a"]):
        return "STOP_PRIVILEGED_SUPERVISION_ROUTE", support
    passed = (
        improvement >= 0.01
        and horizon_wins >= 2
        and max(horizon_relative) <= 0.01
        and month_wins >= 3
        and paired_seed_wins >= 2
        and float(c["pooled_seed_spread"]) <= 0.03
        and float(c["pooled_mae_a"]) < hgb_long
        and hybrid_median < hgb_pooled
    )
    if passed:
        return "PASS_PRIVILEGED_ARRIVAL_SUPERVISION", support
    return "MIXED_PRIVILEGED_ARRIVAL_SIGNAL", support


def run_r11_p1(
    *,
    repo_root: str | Path,
    interim_root: str | Path,
    processed_root: str | Path,
    code_commit: str,
    progress: Callable[[str], None] | None = None,
) -> R11P1RunResult:
    root = Path(repo_root).resolve(strict=True)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    verify_implementation_commit(code_commit, repo_root=root)

    try:
        expert_protocol = load_development_expert_protocol(
            root / "code/configs/acn_jpl_development_experts_2019.yaml"
        )
    except DevelopmentExpertError as exc:
        raise R11P1Error(exc.reason_code) from exc
    if tuple(contract.month for contract in expert_protocol.months) != DEVELOPMENT_MONTHS:
        raise R11P1Error("DEVELOPMENT_MONTH_IDENTITY_INVALID")

    validate_model_environment()
    p1_months, station_months = _load_p1_months(
        expert_protocol=expert_protocol,
        repo_root=root,
        interim_root=interim,
        processed_root=processed,
    )
    p1_folds = _build_p1_folds(p1_months)
    station_folds: tuple[StationFold, ...] = build_station_folds(station_months)

    try:
        all_parameters = load_selected_hgb_parameters(
            protocol=expert_protocol, repo_root=root
        )
    except DevelopmentExpertError as exc:
        raise R11P1Error(exc.reason_code) from exc
    hgb_parameters = MappingProxyType(
        {
            horizon: all_parameters[("M2", horizon)]
            for horizon in (15, 30, 60, 120, 240)
        }
    )
    hgb_records: list[FoldPrediction] = []
    for fold in station_folds:
        if progress:
            progress(f"R11_P1_PROGRESS=HGB_REPLAY; MONTH={fold.month}")
        hgb_records.append(
            predict_station_hgb_fold(fold=fold, parameters=hgb_parameters)
        )
    hgb_records_tuple = tuple(hgb_records)
    station_hgb = summarize_predictions(hgb_records_tuple)

    parameter_count = count_trainable_parameters(make_p1_tcn(import_torch()))
    arm_b_seeds: dict[int, Mapping[str, Any]] = {}
    arm_c_seeds: dict[int, Mapping[str, Any]] = {}
    arm_c_hybrid_seeds: dict[int, Mapping[str, Any]] = {}
    deep_fits = 0

    for seed in DEEP_SEEDS:
        b_records = []
        c_records = []
        for fold in p1_folds:
            if progress:
                progress(f"R11_P1_PROGRESS=START; ARM=B; MONTH={fold.month}; SEED={seed}")
            b_records.append(
                train_p1_fold(
                    fold=fold,
                    seed=seed,
                    auxiliary_weight=0.0,
                    progress=progress,
                )
            )
            deep_fits += 1
            if progress:
                progress(f"R11_P1_PROGRESS=START; ARM=C; MONTH={fold.month}; SEED={seed}")
            c_records.append(
                train_p1_fold(
                    fold=fold,
                    seed=seed,
                    auxiliary_weight=AUXILIARY_WEIGHT,
                    progress=progress,
                )
            )
            deep_fits += 1
        b_tuple = tuple(b_records)
        c_tuple = tuple(c_records)
        arm_b_seeds[seed] = summarize_long(b_tuple)
        arm_c_seeds[seed] = summarize_long(c_tuple)
        arm_c_hybrid_seeds[seed] = summarize_predictions(
            _hybrid_records(hgb_records_tuple, c_tuple)
        )

    if deep_fits != EXPECTED_DEEP_FITS:
        raise R11P1Error("FIT_COUNT_INVALID")
    decision, support = decide(
        hgb_records=hgb_records_tuple,
        arm_b_seeds=arm_b_seeds,
        arm_c_seeds=arm_c_seeds,
        arm_c_hybrid_seeds=arm_c_hybrid_seeds,
    )
    arm_b = {
        "median": _median_long(arm_b_seeds),
        "seeds": {str(seed): dict(arm_b_seeds[seed]) for seed in DEEP_SEEDS},
    }
    arm_c = {
        "median": _median_long(arm_c_seeds),
        "seeds": {str(seed): dict(arm_c_seeds[seed]) for seed in DEEP_SEEDS},
        "hybrid_seeds": {
            str(seed): dict(arm_c_hybrid_seeds[seed]) for seed in DEEP_SEEDS
        },
    }
    return R11P1RunResult(
        status="COMPLETE",
        decision=decision,
        station_hgb=station_hgb,
        arm_b=MappingProxyType(arm_b),
        arm_c=MappingProxyType(arm_c),
        decision_support=MappingProxyType(support),
        model_parameter_count=parameter_count,
        deep_fit_count=deep_fits,
        hgb_replay_fit_count=EXPECTED_HGB_REPLAY_FITS,
        fit_count=deep_fits + EXPECTED_HGB_REPLAY_FITS,
    )
