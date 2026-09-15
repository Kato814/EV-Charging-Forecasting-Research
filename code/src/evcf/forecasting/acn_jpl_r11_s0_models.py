"""Compact deep-model implementations and training loop for JPL R11-S0."""

from __future__ import annotations

import copy
import importlib
import importlib.metadata
import math
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

import numpy as np

from evcf.forecasting.acn_jpl_r11_s0_common import (
    BATCH_SIZE,
    CONTEXT_LENGTH,
    DECODER_CONTEXT_WIDTH,
    DEEP_ARCHITECTURES,
    GRADIENT_CLIP_NORM,
    HISTORY_CHANNELS,
    HORIZONS_MINUTES,
    LEARNING_RATE,
    MAX_EPOCHS,
    MAX_PARAMETER_COUNT,
    MIN_PARAMETER_COUNT,
    MIN_VALIDATION_IMPROVEMENT,
    PATIENCE,
    R11S0Error,
    WEIGHT_DECAY,
)
from evcf.forecasting.acn_jpl_r11_s0_data import StationFold


@dataclass(frozen=True, slots=True)
class FoldPrediction:
    month: str
    issue_times: np.ndarray
    local_days: np.ndarray
    y_true: np.ndarray
    predictions: np.ndarray
    best_epoch: int
    wall_seconds: float


def import_torch():
    try:
        return importlib.import_module("torch")
    except ImportError as exc:
        raise R11S0Error("PYTORCH_NOT_AVAILABLE") from exc


def validate_formal_device() -> Mapping[str, object]:
    try:
        version = importlib.metadata.version("torch")
    except importlib.metadata.PackageNotFoundError as exc:
        raise R11S0Error("PYTORCH_NOT_AVAILABLE") from exc
    if version.split("+", 1)[0] != "2.14.0":
        raise R11S0Error("PYTORCH_VERSION_MISMATCH")
    torch = import_torch()
    if not bool(torch.cuda.is_available()) or int(torch.cuda.device_count()) < 1:
        raise R11S0Error("CUDA_NOT_AVAILABLE")
    name = str(torch.cuda.get_device_name(0))
    if "RTX 5080" not in name:
        raise R11S0Error("GPU_IDENTITY_MISMATCH")
    cuda_version = str(torch.version.cuda)
    if not cuda_version.startswith("13.2"):
        raise R11S0Error("CUDA_WHEEL_MISMATCH")
    device = torch.device("cuda:0")
    try:
        x = torch.tensor([[1.0, -2.0]], dtype=torch.float32, device=device, requires_grad=True)
        x.square().mean().backward()
        torch.cuda.synchronize(device)
    except Exception as exc:  # noqa: BLE001
        raise R11S0Error("CUDA_SMOKE_TEST_FAILED") from exc
    return MappingProxyType(
        {
            "torch_version": version,
            "torch_cuda_version": cuda_version,
            "device": "cuda:0",
            "device_name": name,
            "float32_smoke_test": True,
        }
    )


def _decoder(torch, latent_width: int):
    nn = torch.nn

    class Decoder(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(latent_width + DECODER_CONTEXT_WIDTH, 64),
                nn.ReLU(),
                nn.Linear(64, 32),
                nn.ReLU(),
                nn.Linear(32, 1),
            )

        def forward(self, latent, issue_context, target_context):
            latent = latent.unsqueeze(1).expand(-1, len(HORIZONS_MINUTES), -1)
            issue = issue_context.unsqueeze(1).expand(-1, len(HORIZONS_MINUTES), -1)
            return self.net(torch.cat((latent, issue, target_context), dim=-1)).squeeze(-1)

    return Decoder()


def _make_gru(torch):
    nn = torch.nn

    class Model(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.encoder = nn.GRU(2, 96, num_layers=2, batch_first=True, dropout=0.10)
            self.decoder = _decoder(torch, 96)

        def forward(self, history, issue_context, target_context):
            _output, hidden = self.encoder(history)
            return self.decoder(hidden[-1], issue_context, target_context)

    return Model()


def _make_tcn(torch):
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

    class Model(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            blocks = []
            width = HISTORY_CHANNELS
            for dilation in (1, 2, 4, 8, 16):
                blocks.append(Block(width, dilation))
                width = 64
            self.encoder = nn.Sequential(*blocks)
            self.decoder = _decoder(torch, 64)

        def forward(self, history, issue_context, target_context):
            latent = self.encoder(history.transpose(1, 2))[:, :, -1]
            return self.decoder(latent, issue_context, target_context)

    return Model()


def _make_nhits(torch):
    nn = torch.nn
    functional = torch.nn.functional

    class Block(nn.Module):
        def __init__(self, factor: int) -> None:
            super().__init__()
            self.factor = factor
            self.pooled_length = CONTEXT_LENGTH // factor
            self.forecast_knots = max(1, math.ceil(len(HORIZONS_MINUTES) / factor))
            self.mlp = nn.Sequential(
                nn.Linear(self.pooled_length * HISTORY_CHANNELS, 128),
                nn.ReLU(),
                nn.Linear(128, 128),
                nn.ReLU(),
            )
            self.backcast = nn.Linear(128, self.pooled_length * HISTORY_CHANNELS)
            self.forecast = nn.Linear(128, self.forecast_knots)

        @staticmethod
        def interpolate(values, size: int):
            if values.shape[-1] == 1:
                return values.expand(*values.shape[:-1], size)
            return functional.interpolate(values, size=size, mode="linear", align_corners=False)

        def forward(self, residual):
            pooled = residual.transpose(1, 2)
            if self.factor > 1:
                pooled = functional.avg_pool1d(pooled, self.factor, self.factor)
            hidden = self.mlp(pooled.flatten(1))
            backcast = self.backcast(hidden).view(-1, HISTORY_CHANNELS, self.pooled_length)
            backcast = self.interpolate(backcast, CONTEXT_LENGTH).transpose(1, 2)
            forecast = self.forecast(hidden).unsqueeze(1)
            forecast = self.interpolate(forecast, len(HORIZONS_MINUTES)).squeeze(1)
            return backcast, forecast

    class Model(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.blocks = nn.ModuleList([Block(1), Block(4), Block(16)])
            self.calendar = nn.Sequential(
                nn.Linear(DECODER_CONTEXT_WIDTH, 32), nn.ReLU(), nn.Linear(32, 1)
            )

        def forward(self, history, issue_context, target_context):
            residual = history
            forecast = torch.zeros(
                (history.shape[0], len(HORIZONS_MINUTES)),
                dtype=history.dtype,
                device=history.device,
            )
            for block in self.blocks:
                backcast, increment = block(residual)
                residual = residual - backcast
                forecast = forecast + increment
            issue = issue_context.unsqueeze(1).expand(-1, len(HORIZONS_MINUTES), -1)
            return forecast + self.calendar(torch.cat((issue, target_context), -1)).squeeze(-1)

    return Model()


def _make_patchtst(torch):
    nn = torch.nn

    class Model(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.patch_length = 16
            self.stride = 8
            self.patch_count = (CONTEXT_LENGTH - self.patch_length) // self.stride + 1
            self.projection = nn.Linear(self.patch_length * HISTORY_CHANNELS, 64)
            self.position = nn.Parameter(torch.zeros(1, self.patch_count, 64))
            layer = nn.TransformerEncoderLayer(
                d_model=64,
                nhead=4,
                dim_feedforward=128,
                dropout=0.10,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            )
            self.encoder = nn.TransformerEncoder(layer, num_layers=2)
            self.decoder = _decoder(torch, 64)

        def forward(self, history, issue_context, target_context):
            patches = history.unfold(1, self.patch_length, self.stride)
            patches = patches.contiguous().view(history.shape[0], self.patch_count, -1)
            latent = self.encoder(self.projection(patches) + self.position).mean(dim=1)
            return self.decoder(latent, issue_context, target_context)

    return Model()


def make_deep_model(torch, architecture: str):
    factories = {
        "gru": _make_gru,
        "tcn": _make_tcn,
        "nhits": _make_nhits,
        "patchtst": _make_patchtst,
    }
    try:
        return factories[architecture](torch)
    except KeyError as exc:
        raise R11S0Error("ARCHITECTURE_INVALID") from exc


def count_trainable_parameters(model) -> int:
    return int(sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad))


def parameter_count_report(torch=None) -> Mapping[str, int]:
    torch = import_torch() if torch is None else torch
    counts = {
        name: count_trainable_parameters(make_deep_model(torch, name)) for name in DEEP_ARCHITECTURES
    }
    if any(count < MIN_PARAMETER_COUNT or count > MAX_PARAMETER_COUNT for count in counts.values()):
        raise R11S0Error("PARAMETER_BAND_INVALID")
    return MappingProxyType(counts)


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


def _tensors(torch, device, fold: StationFold, split: str):
    history = getattr(fold, f"{split}_history")
    issue = getattr(fold, f"{split}_issue_context")
    target = getattr(fold, f"{split}_target_context")
    labels = getattr(fold, f"{split}_labels")
    labels = (labels - fold.scaler.target_mean) / fold.scaler.target_scale
    return tuple(
        torch.as_tensor(value, dtype=torch.float32, device=device)
        for value in (history, issue, target, labels)
    )


def _validation_mae(torch, model, tensors) -> float:
    history, issue, target, labels = tensors
    model.eval()
    total = 0.0
    count = 0
    with torch.no_grad():
        for start in range(0, len(history), BATCH_SIZE):
            stop = min(start + BATCH_SIZE, len(history))
            pred = model(history[start:stop], issue[start:stop], target[start:stop])
            total += float(torch.sum(torch.abs(pred - labels[start:stop])).item())
            count += (stop - start) * len(HORIZONS_MINUTES)
    if count <= 0:
        raise R11S0Error("VALIDATION_INVALID")
    return total / count


def train_deep_fold(
    *, architecture: str, fold: StationFold, seed: int, progress: Callable[[str], None] | None = None
) -> FoldPrediction:
    torch = import_torch()
    if not bool(torch.cuda.is_available()):
        raise R11S0Error("CUDA_NOT_AVAILABLE")
    _configure_determinism(torch, seed)
    device = torch.device("cuda:0")
    model = make_deep_model(torch, architecture).to(device=device, dtype=torch.float32)
    if not MIN_PARAMETER_COUNT <= count_trainable_parameters(model) <= MAX_PARAMETER_COUNT:
        raise R11S0Error("PARAMETER_BAND_INVALID")
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    loss_fn = torch.nn.SmoothL1Loss(beta=1.0, reduction="mean")
    train = _tensors(torch, device, fold, "train")
    validation = _tensors(torch, device, fold, "validation")
    test = _tensors(torch, device, fold, "test")
    history, issue, target, labels = train
    rng = np.random.default_rng(seed)
    best_score = math.inf
    best_epoch = 0
    best_state = None
    stale = 0
    started = time.perf_counter()
    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        order = rng.permutation(len(history)).astype(np.int64)
        for start in range(0, len(order), BATCH_SIZE):
            rows = torch.as_tensor(order[start : start + BATCH_SIZE], dtype=torch.long, device=device)
            optimizer.zero_grad(set_to_none=True)
            pred = model(
                history.index_select(0, rows),
                issue.index_select(0, rows),
                target.index_select(0, rows),
            )
            loss = loss_fn(pred, labels.index_select(0, rows))
            if not bool(torch.isfinite(loss).item()):
                raise R11S0Error("MODEL_FIT_INVALID")
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
            progress(
                f"R11_S0_PROGRESS=DEEP_FIT; ARCH={architecture}; MONTH={fold.month}; "
                f"SEED={seed}; EPOCH={epoch}; BEST_EPOCH={best_epoch}; VAL_MAE_STD={best_score:.8f}"
            )
        if stale >= PATIENCE:
            break
    if best_state is None:
        raise R11S0Error("EARLY_STOP_INVALID")
    model.load_state_dict(best_state)
    model.eval()
    h_test, i_test, t_test, _ = test
    pred_std = np.empty((len(h_test), len(HORIZONS_MINUTES)), dtype=np.float64)
    with torch.no_grad():
        for start in range(0, len(h_test), BATCH_SIZE):
            stop = min(start + BATCH_SIZE, len(h_test))
            values = model(h_test[start:stop], i_test[start:stop], t_test[start:stop])
            pred_std[start:stop] = values.detach().cpu().numpy().astype(np.float64)
    predictions = pred_std * fold.scaler.target_scale + fold.scaler.target_mean
    if predictions.shape != fold.test_labels.shape or not np.isfinite(predictions).all():
        raise R11S0Error("MODEL_OUTPUT_INVALID")
    return FoldPrediction(
        month=fold.month,
        issue_times=fold.test_issue_times,
        local_days=fold.test_local_days,
        y_true=fold.test_labels,
        predictions=predictions,
        best_epoch=best_epoch,
        wall_seconds=float(time.perf_counter() - started),
    )
