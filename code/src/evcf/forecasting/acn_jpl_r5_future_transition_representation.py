"""Frozen R5 future-transition-aligned representation experiment for JPL."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
import math
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from scipy.stats import spearmanr

from evcf.forecasting.acn_jpl_development_experts_compat import (
    DevelopmentExpertError,
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_gate1_models import RidgePreprocessor
from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256,
    EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256,
    _load_reference_pair,
    _verify_private_manifest,
)

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
TIMEZONE_NAME = "America/Los_Angeles"
_ZONE = ZoneInfo(TIMEZONE_NAME)

EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256 = (
    "02c7809f1113aeaf20723030c96006ee0831b20ff219106da7d6968df535d71a"
)
EXPECTED_STRUCTURED_PROTOCOL_SHA256 = (
    "74af85044d12f3c68fe4156e6ad1ae67b6e5486b47aecd5637cd67d6539c1902"
)
SOURCE_D2_STATUS_SHA256 = (
    "d04a5f185b193e7b2dd3bafbafe3e095a054de3c71e9a69143f7a8d58f84bdfa"
)
SOURCE_D2_CODE_COMMIT = "599982eadbf1c1ea9868ea20ad5ed0a87d19b74d"
SOURCE_R4_DECISION = "MIXED_STATE_ALIASING_SIGNAL"
PROTOCOL_MERGE_COMMIT = "3f964696606f05bdc01b6f0b217e821d0f1933bf"

M3_RAW_WIDTH = 311
M3_ENCODED_WIDTH = 391
LATENT_WIDTH = 32
EPOCHS = 80
BATCH_SIZE = 256
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
GEOMETRY_WEIGHT = 0.25
GLOBAL_SEED = 20260913
SCORE_EPS = 1e-6
MAX_AUDIT_PAIRS_PER_MONTH = 20_000
EXPECTED_FIT_COUNT = 110
Progress = Callable[[str], None]

IMPLEMENTATION_PATHS = (
    "docs/JPL_R5_FUTURE_TRANSITION_ALIGNED_REPRESENTATION_PROTOCOL_20260913.md",
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_models.py",
    "code/src/evcf/forecasting/acn_jpl_structured_baseline.py",
    "code/src/evcf/forecasting/acn_jpl_structured_mechanism_probe.py",
    "code/src/evcf/forecasting/acn_jpl_r5_future_transition_representation.py",
    "scripts/run_jpl_r5_future_transition_representation.py",
    "scripts/check_r5_cuda_environment.py",
)


class R5Error(RuntimeError):
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
class DailyPrediction:
    issue_times: np.ndarray
    day_start: int
    truth: np.ndarray
    direct: np.ndarray
    ftar: np.ndarray
    q_truth: np.ndarray
    direct_latent: np.ndarray
    ftar_latent: np.ndarray


@dataclass(frozen=True, slots=True)
class MonthPrediction:
    month: str
    issue_times: np.ndarray
    day_starts: np.ndarray
    truth: np.ndarray
    direct: np.ndarray
    ftar: np.ndarray
    daily: tuple[DailyPrediction, ...]
    fit_count: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_semantic_verify(code_commit: str, *, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R5Error("IMPLEMENTATION_DRIFT")
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
        raise R5Error("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R5Error("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode:
            raise R5Error("IMPLEMENTATION_DRIFT")
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
        raise R5Error("IMPLEMENTATION_DRIFT")


def _import_torch():
    try:
        return importlib.import_module("torch")
    except ImportError as exc:
        raise R5Error("PYTORCH_NOT_AVAILABLE") from exc


def validate_formal_device() -> Mapping[str, Any]:
    try:
        version = importlib.metadata.version("torch")
    except importlib.metadata.PackageNotFoundError as exc:
        raise R5Error("PYTORCH_NOT_AVAILABLE") from exc
    if version.split("+", 1)[0] != "2.14.0":
        raise R5Error("PYTORCH_VERSION_MISMATCH")
    torch = _import_torch()
    if not bool(torch.cuda.is_available()) or int(torch.cuda.device_count()) < 1:
        raise R5Error("CUDA_NOT_AVAILABLE")
    name = str(torch.cuda.get_device_name(0))
    if "RTX 5080" not in name:
        raise R5Error("GPU_IDENTITY_MISMATCH")
    cuda_version = str(torch.version.cuda)
    if not cuda_version.startswith("13.2"):
        raise R5Error("CUDA_WHEEL_MISMATCH")
    device = torch.device("cuda:0")
    try:
        x = torch.tensor(
            [[1.0, 2.0]], dtype=torch.float32, device=device, requires_grad=True
        )
        w = torch.tensor(
            [[0.5], [-0.25]], dtype=torch.float32, device=device, requires_grad=True
        )
        loss = (x @ w).abs().sum()
        loss.backward()
        torch.cuda.synchronize(device)
    except Exception as exc:  # noqa: BLE001
        raise R5Error("CUDA_SMOKE_TEST_FAILED") from exc
    return MappingProxyType(
        {
            "torch_version": version,
            "torch_cuda_version": cuda_version,
            "device": "cuda:0",
            "device_name": name,
            "float32_smoke_test": True,
        }
    )


def _local_midnight(epoch: int) -> int:
    local = datetime.fromtimestamp(epoch, timezone.utc).astimezone(_ZONE)
    return int(datetime.combine(local.date(), time.min, tzinfo=_ZONE).timestamp())


def _local_date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).astimezone(_ZONE).date().isoformat()


def rolling_train_rows(issue_times: np.ndarray, cutoff: int) -> np.ndarray:
    values = np.asarray(issue_times, dtype=np.int64)
    rows = np.flatnonzero(
        (values < cutoff) & (values + 240 * 60 <= cutoff)
    ).astype(np.int64)
    if not len(rows):
        raise R5Error("ROLLING_SPLIT_INVALID")
    if int(np.max(values[rows] + 240 * 60)) > int(cutoff):
        raise R5Error("TEMPORAL_LEAKAGE")
    return rows


def fill_issue_current(raw: np.ndarray, training_median: float) -> np.ndarray:
    values = np.asarray(raw, dtype=np.float64)
    median = float(training_median)
    if values.ndim != 1 or not math.isfinite(median) or np.any(np.isinf(values)):
        raise R5Error("CURRENT_LEVEL_INVALID")
    filled = np.where(np.isfinite(values), values, median)
    if not np.isfinite(filled).all():
        raise R5Error("CURRENT_LEVEL_INVALID")
    return filled


def standardized_distance_mse(
    latent_distance: np.ndarray, future_distance: np.ndarray
) -> float:
    latent = np.asarray(latent_distance, dtype=np.float64)
    future = np.asarray(future_distance, dtype=np.float64)
    if (
        latent.ndim != 1
        or latent.shape != future.shape
        or len(latent) < 1
        or not np.isfinite(latent).all()
        or not np.isfinite(future).all()
    ):
        raise R5Error("GEOMETRY_INVALID")
    latent_norm = (latent - np.mean(latent)) / (
        np.std(latent, ddof=0) + SCORE_EPS
    )
    future_norm = (future - np.mean(future)) / (
        np.std(future, ddof=0) + SCORE_EPS
    )
    return float(np.mean(np.square(latent_norm - future_norm)))


def transition_location_scale(
    labels: np.ndarray, current: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y = np.asarray(labels, dtype=np.float64)
    p = np.asarray(current, dtype=np.float64)
    if y.ndim != 2 or y.shape[1] != len(HORIZONS_MINUTES) or p.shape != (len(y),):
        raise R5Error("TARGET_INVALID")
    if not np.isfinite(y).all() or not np.isfinite(p).all():
        raise R5Error("TARGET_INVALID")
    r = y - p[:, None]
    location = np.median(r, axis=0)
    scale = np.median(np.abs(r - location[None, :]), axis=0)
    scale = np.maximum(scale, 1.0)
    q = (r - location[None, :]) / scale[None, :]
    if not np.isfinite(q).all():
        raise R5Error("TARGET_INVALID")
    return location, scale, q


def reconstruct_load(
    current: np.ndarray,
    location: np.ndarray,
    scale: np.ndarray,
    q_prediction: np.ndarray,
) -> np.ndarray:
    p = np.asarray(current, dtype=np.float64)
    m = np.asarray(location, dtype=np.float64)
    s = np.asarray(scale, dtype=np.float64)
    q = np.asarray(q_prediction, dtype=np.float64)
    if p.ndim != 1 or m.shape != (5,) or s.shape != (5,) or q.shape != (len(p), 5):
        raise R5Error("PREDICTION_INVALID")
    output = p[:, None] + m[None, :] + s[None, :] * q
    if not np.isfinite(output).all():
        raise R5Error("PREDICTION_INVALID")
    return output


def batch_partitions(
    row_count: int, batch_size: int = BATCH_SIZE
) -> tuple[tuple[int, int], ...]:
    if row_count < 2 or batch_size < 2:
        raise R5Error("BATCH_INVALID")
    parts: list[tuple[int, int]] = []
    start = 0
    while start < row_count:
        remaining = row_count - start
        size = min(batch_size, remaining)
        if remaining == batch_size + 1:
            size = remaining
        stop = start + size
        parts.append((start, stop))
        start = stop
    if any(stop - start < 2 for start, stop in parts):
        raise R5Error("BATCH_INVALID")
    return tuple(parts)


def epoch_orders(row_count: int, seed: int) -> tuple[np.ndarray, ...]:
    if row_count < 2:
        raise R5Error("TRAINING_DATA_INVALID")
    rng = np.random.Generator(np.random.PCG64(seed))
    return tuple(
        rng.permutation(row_count).astype(np.int64) for _ in range(EPOCHS)
    )


def _fold_seed(month: str, local_date: str) -> int:
    payload = f"R5_FTAR_V1|{GLOBAL_SEED}|{month}|{local_date}".encode("ascii")
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=False)
    return int(value % (2**31 - 1))


def architecture_spec() -> tuple[int, int, int, int, int]:
    return (M3_ENCODED_WIDTH, 128, LATENT_WIDTH, 64, 5)


def _make_model(torch):
    nn = torch.nn

    class R5Network(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.encoder = nn.Sequential(
                nn.Linear(M3_ENCODED_WIDTH, 128),
                nn.GELU(),
                nn.Linear(128, LATENT_WIDTH),
            )
            self.head = nn.Sequential(
                nn.Linear(LATENT_WIDTH, 64),
                nn.GELU(),
                nn.Linear(64, len(HORIZONS_MINUTES)),
            )
            for module in self.modules():
                if isinstance(module, nn.Linear):
                    nn.init.xavier_uniform_(module.weight)
                    nn.init.zeros_(module.bias)

        def forward(self, x):
            z = self.encoder(x)
            return self.head(z), z

    return R5Network()


def _geometry_loss(torch, latent, target):
    n = int(latent.shape[0])
    if n < 2 or target.shape[0] != n:
        raise R5Error("BATCH_INVALID")
    tri = torch.triu_indices(n, n, offset=1, device=latent.device)
    left = tri[0]
    right = tri[1]
    latent_distance = torch.sqrt(
        torch.mean((latent[left] - latent[right]) ** 2, dim=1)
    )
    future_distance = torch.sqrt(
        torch.mean((target[left] - target[right]) ** 2, dim=1)
    )
    latent_std = torch.std(latent_distance, correction=0)
    future_std = torch.std(future_distance, correction=0)
    latent_norm = (latent_distance - torch.mean(latent_distance)) / (
        latent_std + SCORE_EPS
    )
    future_norm = (future_distance - torch.mean(future_distance)) / (
        future_std + SCORE_EPS
    )
    return torch.mean((latent_norm - future_norm) ** 2)


def _train_predict_arm(
    *,
    x_train: np.ndarray,
    q_train: np.ndarray,
    x_test: np.ndarray,
    seed: int,
    orders: Sequence[np.ndarray],
    use_geometry: bool,
) -> tuple[np.ndarray, np.ndarray]:
    torch = _import_torch()
    if not bool(torch.cuda.is_available()):
        raise R5Error("CUDA_NOT_AVAILABLE")
    device = torch.device("cuda:0")
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    if hasattr(torch.backends, "cuda") and hasattr(torch.backends.cuda, "matmul"):
        torch.backends.cuda.matmul.allow_tf32 = False
    if hasattr(torch.backends, "cudnn"):
        torch.backends.cudnn.allow_tf32 = False
    if hasattr(torch, "set_float32_matmul_precision"):
        torch.set_float32_matmul_precision("highest")

    x_train_np = np.asarray(x_train, dtype=np.float32)
    q_train_np = np.asarray(q_train, dtype=np.float32)
    x_test_np = np.asarray(x_test, dtype=np.float32)
    if (
        x_train_np.ndim != 2
        or x_train_np.shape[1] != M3_ENCODED_WIDTH
        or q_train_np.shape != (len(x_train_np), 5)
        or x_test_np.ndim != 2
        or x_test_np.shape[1] != M3_ENCODED_WIDTH
        or not np.isfinite(x_train_np).all()
        or not np.isfinite(q_train_np).all()
        or not np.isfinite(x_test_np).all()
        or len(orders) != EPOCHS
    ):
        raise R5Error("TRAINING_DATA_INVALID")

    model = _make_model(torch).to(device=device, dtype=torch.float32)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY
    )
    smooth_l1 = torch.nn.SmoothL1Loss(beta=1.0, reduction="mean")
    partitions = batch_partitions(len(x_train_np))

    for order in orders:
        if not np.array_equal(
            np.sort(order), np.arange(len(x_train_np), dtype=np.int64)
        ):
            raise R5Error("BATCH_INVALID")
        model.train()
        for begin, end in partitions:
            rows = order[begin:end]
            x = torch.as_tensor(
                x_train_np[rows], dtype=torch.float32, device=device
            )
            q = torch.as_tensor(
                q_train_np[rows], dtype=torch.float32, device=device
            )
            optimizer.zero_grad(set_to_none=True)
            pred, latent = model(x)
            loss = smooth_l1(pred, q)
            if use_geometry:
                loss = loss + GEOMETRY_WEIGHT * _geometry_loss(torch, latent, q)
            if not bool(torch.isfinite(loss).item()):
                raise R5Error("MODEL_FIT_INVALID")
            loss.backward()
            optimizer.step()

    model.eval()
    predictions = np.empty((len(x_test_np), 5), dtype=np.float64)
    latents = np.empty((len(x_test_np), LATENT_WIDTH), dtype=np.float64)
    with torch.no_grad():
        for start in range(0, len(x_test_np), BATCH_SIZE):
            stop = min(start + BATCH_SIZE, len(x_test_np))
            x = torch.as_tensor(
                x_test_np[start:stop], dtype=torch.float32, device=device
            )
            pred, latent = model(x)
            predictions[start:stop] = (
                pred.detach().cpu().numpy().astype(np.float64)
            )
            latents[start:stop] = (
                latent.detach().cpu().numpy().astype(np.float64)
            )
    if not np.isfinite(predictions).all() or not np.isfinite(latents).all():
        raise R5Error("PREDICTION_INVALID")
    return predictions, latents


def _month_prediction(
    *,
    data,
    test_start_local_day: int,
    progress: Progress | None,
    fit_offset: int,
) -> MonthPrediction:
    issue_times = np.asarray(data.issue_times, dtype=np.int64)
    labels = np.asarray(data.labels, dtype=np.float64)
    m3 = data.blocks["M3"]
    if m3.values.shape[1] != M3_RAW_WIDTH:
        raise R5Error("STATE_SCHEMA_INVALID")
    try:
        current_index = m3.feature_names.index("station_current_a")
    except ValueError as exc:
        raise R5Error("STATE_SCHEMA_INVALID") from exc
    raw_current = np.asarray(m3.values[:, current_index], dtype=np.float64)
    if np.any(np.isinf(raw_current)):
        raise R5Error("CURRENT_LEVEL_INVALID")
    day_starts = np.asarray(
        [_local_midnight(int(t)) for t in issue_times], dtype=np.int64
    )
    local_days = np.asarray(
        [
            datetime.fromtimestamp(int(t), timezone.utc).astimezone(_ZONE).day
            for t in issue_times
        ],
        dtype=np.int16,
    )
    test_days = np.unique(day_starts[local_days >= test_start_local_day])
    if not len(test_days):
        raise R5Error("ROLLING_SPLIT_INVALID")

    output_times: list[np.ndarray] = []
    output_days: list[np.ndarray] = []
    truths: list[np.ndarray] = []
    direct_outputs: list[np.ndarray] = []
    ftar_outputs: list[np.ndarray] = []
    daily: list[DailyPrediction] = []
    fits = 0

    for day in test_days:
        train = rolling_train_rows(issue_times, int(day))
        test = np.flatnonzero(day_starts == int(day)).astype(np.int64)
        if not len(test) or np.intersect1d(train, test).size:
            raise R5Error("ROLLING_SPLIT_INVALID")
        if not np.isfinite(labels[train]).all() or not np.isfinite(labels[test]).all():
            raise R5Error("TARGET_INVALID")
        preprocessor = RidgePreprocessor().fit(m3, train)
        x_train = preprocessor.transform(m3, train).astype(np.float32)
        x_test = preprocessor.transform(m3, test).astype(np.float32)
        current_fill = float(preprocessor.medians[current_index])
        train_current = fill_issue_current(raw_current[train], current_fill)
        test_current = fill_issue_current(raw_current[test], current_fill)
        location, scale, q_train = transition_location_scale(
            labels[train], train_current
        )
        q_truth = (
            labels[test] - test_current[:, None] - location[None, :]
        ) / scale[None, :]
        if not np.isfinite(q_truth).all():
            raise R5Error("TARGET_INVALID")
        date_text = _local_date(int(day))
        seed = _fold_seed(data.month, date_text)
        orders = epoch_orders(len(train), seed)

        direct_q, direct_latent = _train_predict_arm(
            x_train=x_train,
            q_train=q_train,
            x_test=x_test,
            seed=seed,
            orders=orders,
            use_geometry=False,
        )
        fits += 1
        ftar_q, ftar_latent = _train_predict_arm(
            x_train=x_train,
            q_train=q_train,
            x_test=x_test,
            seed=seed,
            orders=orders,
            use_geometry=True,
        )
        fits += 1
        if progress is not None:
            progress(
                "R5_STAGE=DAY_COMPLETE; "
                f"MONTH={data.month}; DAY={date_text}; "
                f"FITS={fit_offset + fits}/{EXPECTED_FIT_COUNT}"
            )
        direct = reconstruct_load(test_current, location, scale, direct_q)
        ftar = reconstruct_load(test_current, location, scale, ftar_q)
        output_times.append(issue_times[test])
        output_days.append(day_starts[test])
        truths.append(labels[test])
        direct_outputs.append(direct)
        ftar_outputs.append(ftar)
        daily.append(
            DailyPrediction(
                issue_times=issue_times[test],
                day_start=int(day),
                truth=labels[test],
                direct=direct,
                ftar=ftar,
                q_truth=q_truth,
                direct_latent=direct_latent,
                ftar_latent=ftar_latent,
            )
        )

    times = np.concatenate(output_times).astype(np.int64, copy=False)
    days = np.concatenate(output_days).astype(np.int64, copy=False)
    if np.any(np.diff(times) <= 0):
        raise R5Error("ROLLING_SPLIT_INVALID")
    return MonthPrediction(
        month=data.month,
        issue_times=times,
        day_starts=days,
        truth=np.concatenate(truths, axis=0),
        direct=np.concatenate(direct_outputs, axis=0),
        ftar=np.concatenate(ftar_outputs, axis=0),
        daily=tuple(daily),
        fit_count=fits,
    )


def _metric(truth: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    y = np.asarray(truth, dtype=np.float64)
    p = np.asarray(prediction, dtype=np.float64)
    if y.ndim != 1 or p.shape != y.shape or not len(y):
        raise R5Error("METRIC_INVALID")
    if not np.isfinite(y).all() or not np.isfinite(p).all():
        raise R5Error("METRIC_INVALID")
    error = p - y
    absolute = np.abs(error)
    denominator = float(np.sum(np.abs(y)))
    return {
        "n": int(len(y)),
        "mae_a": float(np.mean(absolute)),
        "rmse_a": float(np.sqrt(np.mean(np.square(error)))),
        "wape_ratio": (
            None
            if denominator <= 1e-12
            else float(np.sum(absolute) / denominator)
        ),
        "negative_prediction_count": int(np.sum(p < 0)),
    }


def _aligned_reference_task(
    *,
    month_prediction: MonthPrediction,
    reference: Mapping[str, np.ndarray],
    horizon: int,
) -> dict[str, Any]:
    position = HORIZONS_MINUTES.index(horizon)
    ref_times = np.asarray(reference["issue_times"], dtype=np.int64)
    indexes = np.searchsorted(month_prediction.issue_times, ref_times)
    if (
        np.any(indexes < 0)
        or np.any(indexes >= len(month_prediction.issue_times))
        or not np.array_equal(month_prediction.issue_times[indexes], ref_times)
        or not np.array_equal(
            month_prediction.day_starts[indexes], reference["day_start_utc_s"]
        )
        or not np.allclose(
            month_prediction.truth[indexes, position],
            reference["y_true"],
            rtol=0.0,
            atol=1e-6,
        )
    ):
        raise R5Error("COMMON_ROW_IDENTITY_INVALID")
    truth = np.asarray(reference["y_true"], dtype=np.float64)
    return {
        "month": month_prediction.month,
        "horizon": horizon,
        "issue_times": ref_times,
        "day_starts": np.asarray(reference["day_start_utc_s"], dtype=np.int64),
        "truth": truth,
        "Direct": month_prediction.direct[indexes, position],
        "FTAR": month_prediction.ftar[indexes, position],
        "M3": np.asarray(reference["m3_predictions"], dtype=np.float64),
        "Equal": np.asarray(reference["equal_predictions"], dtype=np.float64),
        "S1": np.asarray(reference["structured_predictions"], dtype=np.float64),
    }


def _summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise R5Error("METRIC_INVALID")
    truth = np.concatenate([np.asarray(item["truth"]) for item in records])
    return {
        name: _metric(
            truth,
            np.concatenate([np.asarray(item[name]) for item in records]),
        )
        for name in ("Direct", "FTAR", "M3", "Equal", "S1")
    }


def _pair_distances(
    block: DailyPrediction,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(block.issue_times)
    if n < 2:
        return (np.empty(0), np.empty(0), np.empty(0))
    left, right = np.triu_indices(n, k=1)
    future = np.sqrt(
        np.mean((block.q_truth[left] - block.q_truth[right]) ** 2, axis=1)
    )
    direct = np.sqrt(
        np.mean(
            (block.direct_latent[left] - block.direct_latent[right]) ** 2,
            axis=1,
        )
    )
    ftar = np.sqrt(
        np.mean(
            (block.ftar_latent[left] - block.ftar_latent[right]) ** 2,
            axis=1,
        )
    )
    if not (
        np.isfinite(future).all()
        and np.isfinite(direct).all()
        and np.isfinite(ftar).all()
    ):
        raise R5Error("GEOMETRY_AUDIT_INVALID")
    return direct, ftar, future


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 2 or left.shape != right.shape:
        raise R5Error("GEOMETRY_AUDIT_INVALID")
    value = float(spearmanr(left, right).statistic)
    if not math.isfinite(value):
        raise R5Error("GEOMETRY_AUDIT_INVALID")
    return value


def geometry_audit(
    months: Sequence[MonthPrediction],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    rng = np.random.Generator(np.random.PCG64(GLOBAL_SEED))
    month_rows: list[dict[str, Any]] = []
    pooled_direct: list[np.ndarray] = []
    pooled_ftar: list[np.ndarray] = []
    pooled_future: list[np.ndarray] = []
    for month in months:
        direct_parts: list[np.ndarray] = []
        ftar_parts: list[np.ndarray] = []
        future_parts: list[np.ndarray] = []
        for block in month.daily:
            direct, ftar, future = _pair_distances(block)
            if len(direct):
                direct_parts.append(direct)
                ftar_parts.append(ftar)
                future_parts.append(future)
        if not direct_parts:
            raise R5Error("GEOMETRY_AUDIT_INVALID")
        direct_all = np.concatenate(direct_parts)
        ftar_all = np.concatenate(ftar_parts)
        future_all = np.concatenate(future_parts)
        available = len(direct_all)
        if available > MAX_AUDIT_PAIRS_PER_MONTH:
            selected = rng.choice(
                available, size=MAX_AUDIT_PAIRS_PER_MONTH, replace=False
            )
            direct_all = direct_all[selected]
            ftar_all = ftar_all[selected]
            future_all = future_all[selected]
        row = {
            "month": month.month,
            "available_same_refit_pairs": int(available),
            "retained_pairs": int(len(direct_all)),
            "Direct_spearman": _spearman(direct_all, future_all),
            "FTAR_spearman": _spearman(ftar_all, future_all),
        }
        month_rows.append(row)
        pooled_direct.append(direct_all)
        pooled_ftar.append(ftar_all)
        pooled_future.append(future_all)
    direct = np.concatenate(pooled_direct)
    ftar = np.concatenate(pooled_ftar)
    future = np.concatenate(pooled_future)
    pooled = {
        "retained_pairs": int(len(direct)),
        "Direct_spearman": _spearman(direct, future),
        "FTAR_spearman": _spearman(ftar, future),
    }
    return pooled, tuple(month_rows)


def decide(
    pooled: Mapping[str, Any],
    by_horizon: Sequence[Mapping[str, Any]],
    by_month: Sequence[Mapping[str, Any]],
    geometry: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    direct = float(pooled["Direct"]["mae_a"])
    ftar = float(pooled["FTAR"]["mae_a"])
    equal = float(pooled["Equal"]["mae_a"])
    s1 = float(pooled["S1"]["mae_a"])
    horizon_wins = sum(
        float(item["FTAR"]["mae_a"]) < float(item["Direct"]["mae_a"])
        for item in by_horizon
    )
    month_wins = sum(
        float(item["FTAR"]["mae_a"]) < float(item["Direct"]["mae_a"])
        for item in by_month
    )
    degradation = max(
        float(item["FTAR"]["mae_a"]) / float(item["Direct"]["mae_a"]) - 1.0
        for item in by_horizon
    )
    geometry_gain = float(geometry["FTAR_spearman"]) - float(
        geometry["Direct_spearman"]
    )
    support = {
        "pooled_improvement_vs_Direct": 1.0 - ftar / direct,
        "pooled_improvement_vs_Equal": 1.0 - ftar / equal,
        "pooled_improvement_vs_S1": 1.0 - ftar / s1,
        "horizon_wins_vs_Direct": int(horizon_wins),
        "month_wins_vs_Direct": int(month_wins),
        "max_horizon_degradation_vs_Direct": float(degradation),
        "heldout_geometry_spearman_gain": float(geometry_gain),
    }
    if ftar >= direct or horizon_wins <= 1 or month_wins <= 1:
        return "STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE", support
    if (
        ftar < direct
        and ftar < equal
        and ftar < s1
        and horizon_wins >= 3
        and month_wins >= 3
        and degradation <= 0.05
        and geometry_gain > 0.0
    ):
        return "PASS_FUTURE_TRANSITION_GEOMETRY", support
    return "MIXED_FUTURE_TRANSITION_GEOMETRY", support


def _write_task_cache(
    *, stage: Path, record: Mapping[str, Any]
) -> tuple[str, str]:
    name = f"{record['month']}_h{int(record['horizon']):03d}.npz"
    path = stage / name
    np.savez_compressed(
        path,
        issue_times=record["issue_times"],
        day_start_utc_s=record["day_starts"],
        y_true=record["truth"],
        direct_predictions=record["Direct"],
        ftar_predictions=record["FTAR"],
        m3_predictions=record["M3"],
        equal_predictions=record["Equal"],
        s1_predictions=record["S1"],
    )
    return name, _sha256_file(path)


def run_r5(
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
        raise R5Error("R5_NOT_AUTHORIZED")
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
        raise R5Error("OUTPUT_TOPOLOGY_INVALID")

    _git_semantic_verify(code_commit, repo_root=repo)
    device_info = validate_formal_device()
    protocol = load_development_expert_protocol(
        repo / "code/configs/acn_jpl_development_experts_2019.yaml"
    )
    if (
        protocol.protocol_sha256 != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256
        or tuple(contract.month for contract in protocol.months) != DEVELOPMENT_MONTHS
        or protocol.test_start_local_day != 18
    ):
        raise R5Error("PROTOCOL_INVALID")

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
        raise R5Error("PRIVATE_CACHE_IDENTITY_INVALID") from exc
    if baseline_manifest.get("protocol_sha256") != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256:
        raise R5Error("PRIVATE_CACHE_IDENTITY_INVALID")
    if structured_manifest.get("protocol_sha256") != EXPECTED_STRUCTURED_PROTOCOL_SHA256:
        raise R5Error("PRIVATE_CACHE_IDENTITY_INVALID")

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(
        tempfile.mkdtemp(prefix=".evcf-r5-ftar-", dir=output.parent)
    )
    month_predictions: list[MonthPrediction] = []
    records: list[dict[str, Any]] = []
    private_entries: list[dict[str, str]] = []
    fit_count = 0
    try:
        for contract in protocol.months:
            if contract.month not in DEVELOPMENT_MONTHS:
                raise R5Error("HOLDOUT_ACCESS_ATTEMPT")
            try:
                data = load_month_data(
                    contract=contract,
                    interim_root=interim,
                    processed_root=processed,
                )
            except DevelopmentExpertError as exc:
                raise R5Error(exc.reason_code) from exc
            if progress is not None:
                progress(f"R5_STAGE=MONTH_START; MONTH={contract.month}")
            prediction = _month_prediction(
                data=data,
                test_start_local_day=protocol.test_start_local_day,
                progress=progress,
                fit_offset=fit_count,
            )
            fit_count += prediction.fit_count
            month_predictions.append(prediction)
            for horizon in HORIZONS_MINUTES:
                reference = _load_reference_pair(
                    baseline_root=baseline_root,
                    structured_root=structured_root,
                    month=contract.month,
                    horizon=horizon,
                )
                record = _aligned_reference_task(
                    month_prediction=prediction,
                    reference=reference,
                    horizon=horizon,
                )
                name, digest = _write_task_cache(stage=stage, record=record)
                private_entries.append({"name": name, "sha256": digest})
                records.append(record)
            if progress is not None:
                progress(
                    f"R5_STAGE=MONTH_COMPLETE; MONTH={contract.month}; "
                    f"FITS={prediction.fit_count}"
                )

        if fit_count != EXPECTED_FIT_COUNT or len(private_entries) != 20:
            raise R5Error("FIT_COUNT_INVALID")
        pooled = _summary(records)
        by_horizon = []
        for horizon in HORIZONS_MINUTES:
            summary = _summary(
                [item for item in records if item["horizon"] == horizon]
            )
            by_horizon.append({"horizon_minutes": horizon, **summary})
        by_month = []
        for month in DEVELOPMENT_MONTHS:
            summary = _summary(
                [item for item in records if item["month"] == month]
            )
            by_month.append({"month": month, **summary})
        cells = [
            {
                "month": item["month"],
                "horizon_minutes": item["horizon"],
                **_summary([item]),
            }
            for item in records
        ]
        geometry_pooled, geometry_months = geometry_audit(month_predictions)
        decision, decision_support = decide(
            pooled, by_horizon, by_month, geometry_pooled
        )

        manifest = {
            "schema_version": "evcf-jpl-r5-ftar-private-cache/v1",
            "source_d2_status_sha256": SOURCE_D2_STATUS_SHA256,
            "code_commit": code_commit,
            "protocol_merge_commit": PROTOCOL_MERGE_COMMIT,
            "entries": private_entries,
        }
        manifest_path = stage / "private_manifest.json"
        manifest_path.write_text(
            json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            encoding="ascii",
            newline="\n",
        )
        manifest_sha = _sha256_file(manifest_path)
        stage.replace(output)
    except Exception:  # noqa: BLE001
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return {
        "schema_version": "evcf-jpl-r5-ftar-summary/v1",
        "status": "COMPLETE",
        "code_commit": code_commit,
        "protocol_merge_commit": PROTOCOL_MERGE_COMMIT,
        "source_d2_status_sha256": SOURCE_D2_STATUS_SHA256,
        "source_d2_code_commit": SOURCE_D2_CODE_COMMIT,
        "source_r4_decision": SOURCE_R4_DECISION,
        "scientific_decision_unchanged": True,
        "decision": decision,
        "decision_support": decision_support,
        "pooled_overall": pooled,
        "pooled_by_horizon": by_horizon,
        "pooled_by_month": by_month,
        "month_horizon_cells": cells,
        "heldout_geometry": {
            "pooled": geometry_pooled,
            "by_month": list(geometry_months),
            "same_refit_pairs_only": True,
        },
        "fit_count": fit_count,
        "model_fit_attempted": True,
        "direct_model_trained": True,
        "ftar_model_trained": True,
        "private_cache_file_count": 20,
        "private_manifest_sha256": manifest_sha,
        "device": dict(device_info),
        "holdout_accessed": False,
        "hyperparameter_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "gate_trained": False,
        "moe_trained": False,
        "set_transformer_trained": False,
        "individual_session_set_encoder_trained": False,
        "future_transition_geometry_trained": True,
        "reference_models_retrained": False,
    }
