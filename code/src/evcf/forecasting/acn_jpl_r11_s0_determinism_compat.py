"""Deterministic CUDA compatibility repair for the frozen R11-S0 N-HiTS arm.

PyTorch 2.14 raises under ``torch.use_deterministic_algorithms(True)`` when
``torch.nn.functional.interpolate(..., mode='linear')`` participates in CUDA
backpropagation. The frozen compact N-HiTS implementation used that operation
for knot interpolation.

This module preserves the same N-HiTS hierarchy, pooling factors, hidden widths,
parameter count and align_corners=False linear interpolation geometry, but
implements the 1-D interpolation explicitly with deterministic tensor indexing
and weighted sums. No model-selection or performance-dependent setting is
changed.
"""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

from evcf.forecasting import acn_jpl_r11_s0_models as _models
from evcf.forecasting.acn_jpl_r11_s0_common import (
    CONTEXT_LENGTH,
    DECODER_CONTEXT_WIDTH,
    DEEP_ARCHITECTURES,
    HISTORY_CHANNELS,
    HORIZONS_MINUTES,
    R11S0Error,
)


def deterministic_linear_interpolate(torch: Any, values: Any, size: int):
    """1-D linear resize equivalent to align_corners=False without CUDA interpolate backward."""

    input_size = int(values.shape[-1])
    if size <= 0 or input_size <= 0:
        raise R11S0Error("DETERMINISTIC_INTERPOLATION_INVALID")
    if input_size == size:
        return values
    if input_size == 1:
        return values.expand(*values.shape[:-1], size)

    coordinate = (
        (torch.arange(size, device=values.device, dtype=values.dtype) + 0.5)
        * (float(input_size) / float(size))
        - 0.5
    )
    coordinate = coordinate.clamp(0.0, float(input_size - 1))
    left = torch.floor(coordinate).to(dtype=torch.long)
    right = torch.clamp(left + 1, max=input_size - 1)
    weight_right = coordinate - left.to(dtype=values.dtype)
    weight_left = 1.0 - weight_right
    left_values = values.index_select(-1, left)
    right_values = values.index_select(-1, right)
    return left_values * weight_left + right_values * weight_right


def _make_nhits_deterministic(torch: Any):
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

        def forward(self, residual):
            pooled = residual.transpose(1, 2)
            if self.factor > 1:
                pooled = functional.avg_pool1d(pooled, self.factor, self.factor)
            hidden = self.mlp(pooled.flatten(1))
            backcast = self.backcast(hidden).view(-1, HISTORY_CHANNELS, self.pooled_length)
            backcast = deterministic_linear_interpolate(torch, backcast, CONTEXT_LENGTH).transpose(1, 2)
            forecast = self.forecast(hidden).unsqueeze(1)
            forecast = deterministic_linear_interpolate(
                torch, forecast, len(HORIZONS_MINUTES)
            ).squeeze(1)
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


def install_deterministic_nhits_compat() -> None:
    """Install the process-local deterministic N-HiTS factory."""

    _models._make_nhits = _make_nhits_deterministic


def validate_deterministic_backward_smoke(torch: Any | None = None) -> MappingProxyType:
    """Run a synthetic CUDA forward/backward for every frozen deep architecture."""

    torch = _models.import_torch() if torch is None else torch
    install_deterministic_nhits_compat()
    try:
        _models._configure_determinism(torch, 2026091401)
        device = torch.device("cuda:0")
        completed: list[str] = []
        for architecture in DEEP_ARCHITECTURES:
            model = _models.make_deep_model(torch, architecture).to(
                device=device, dtype=torch.float32
            )
            history = torch.zeros((2, CONTEXT_LENGTH, HISTORY_CHANNELS), device=device)
            issue = torch.zeros((2, 5), device=device)
            target = torch.zeros((2, len(HORIZONS_MINUTES), 6), device=device)
            loss = model(history, issue, target).square().mean()
            loss.backward()
            torch.cuda.synchronize(device)
            completed.append(architecture)
    except RuntimeError as exc:
        raise R11S0Error("DETERMINISTIC_BACKWARD_UNAVAILABLE") from exc
    return MappingProxyType(
        {
            "deterministic_backward_smoke": True,
            "deterministic_backward_architectures": tuple(completed),
        }
    )
