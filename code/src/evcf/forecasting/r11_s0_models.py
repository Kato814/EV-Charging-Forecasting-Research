"""Compact station-only model families for R11-S0.

Torch is imported lazily so the repository's CPU-only contract tests can import
this module without requiring the formal R11 environment.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

from evcf.forecasting.r11_s0_contracts import (
    CONTEXT_LENGTH,
    HISTORY_CHANNELS,
    HORIZONS_MINUTES,
    ISSUE_CONTEXT_WIDTH,
    TARGET_CONTEXT_WIDTH,
    R11S0ContractError,
)

ModelFactory = Callable[[], Any]


def _torch_modules() -> tuple[Any, Any]:
    try:
        torch = importlib.import_module("torch")
        nn = importlib.import_module("torch.nn")
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise R11S0ContractError("TORCH_UNAVAILABLE") from exc
    return torch, nn


def _validate_inputs(history: Any, issue_context: Any, target_context: Any) -> None:
    if tuple(history.shape[1:]) != (CONTEXT_LENGTH, HISTORY_CHANNELS):
        raise R11S0ContractError("INVALID_HISTORY_SHAPE")
    if tuple(issue_context.shape[1:]) != (ISSUE_CONTEXT_WIDTH,):
        raise R11S0ContractError("INVALID_ISSUE_CONTEXT_SHAPE")
    if tuple(target_context.shape[1:]) != (
        len(HORIZONS_MINUTES),
        TARGET_CONTEXT_WIDTH,
    ):
        raise R11S0ContractError("INVALID_TARGET_CONTEXT_SHAPE")
    if history.shape[0] != issue_context.shape[0] or history.shape[0] != target_context.shape[0]:
        raise R11S0ContractError("BATCH_ALIGNMENT_INVALID")


def _make_decoder(latent_width: int, hidden_width: int = 64) -> Any:
    torch, nn = _torch_modules()

    class HorizonDecoder(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.network = nn.Sequential(
                nn.Linear(latent_width + ISSUE_CONTEXT_WIDTH + TARGET_CONTEXT_WIDTH, hidden_width),
                nn.ReLU(),
                nn.Linear(hidden_width, 1),
            )

        def forward(self, latent: Any, issue_context: Any, target_context: Any) -> Any:
            horizon_count = len(HORIZONS_MINUTES)
            repeated_latent = latent[:, None, :].expand(-1, horizon_count, -1)
            repeated_issue = issue_context[:, None, :].expand(-1, horizon_count, -1)
            features = torch.cat((repeated_latent, repeated_issue, target_context), dim=-1)
            return self.network(features).squeeze(-1)

    return HorizonDecoder()


def make_gru_model() -> Any:
    _torch, nn = _torch_modules()

    class GRUForecaster(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.encoder = nn.GRU(
                input_size=HISTORY_CHANNELS,
                hidden_size=96,
                num_layers=2,
                batch_first=True,
                dropout=0.10,
            )
            self.decoder = _make_decoder(96)

        def forward(self, history: Any, issue_context: Any, target_context: Any) -> Any:
            _validate_inputs(history, issue_context, target_context)
            _output, hidden = self.encoder(history)
            return self.decoder(hidden[-1], issue_context, target_context)

    return GRUForecaster()


def make_tcn_model() -> Any:
    torch, nn = _torch_modules()

    class Chomp1d(nn.Module):
        def __init__(self, size: int) -> None:
            super().__init__()
            self.size = size

        def forward(self, x: Any) -> Any:
            return x[:, :, : -self.size] if self.size else x

    class ResidualBlock(nn.Module):
        def __init__(self, in_channels: int, dilation: int) -> None:
            super().__init__()
            padding = 2 * dilation
            self.main = nn.Sequential(
                nn.Conv1d(in_channels, 64, 3, padding=padding, dilation=dilation),
                Chomp1d(padding),
                nn.ReLU(),
                nn.Dropout(0.10),
                nn.Conv1d(64, 64, 3, padding=padding, dilation=dilation),
                Chomp1d(padding),
                nn.ReLU(),
                nn.Dropout(0.10),
            )
            self.skip = nn.Identity() if in_channels == 64 else nn.Conv1d(in_channels, 64, 1)

        def forward(self, x: Any) -> Any:
            return torch.relu(self.main(x) + self.skip(x))

    class TCNForecaster(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            blocks: list[Any] = []
            channels = HISTORY_CHANNELS
            for dilation in (1, 2, 4, 8, 16):
                blocks.append(ResidualBlock(channels, dilation))
                channels = 64
            self.encoder = nn.Sequential(*blocks)
            self.decoder = _make_decoder(64)

        def forward(self, history: Any, issue_context: Any, target_context: Any) -> Any:
            _validate_inputs(history, issue_context, target_context)
            encoded = self.encoder(history.transpose(1, 2))
            latent = encoded[:, :, -1]
            return self.decoder(latent, issue_context, target_context)

    return TCNForecaster()


def make_nhits_model() -> Any:
    torch, nn = _torch_modules()

    class NHiTSBlock(nn.Module):
        def __init__(self, factor: int) -> None:
            super().__init__()
            self.factor = factor
            self.pooled_length = CONTEXT_LENGTH // factor
            input_width = 2 * self.pooled_length
            output_width = self.pooled_length + 64
            self.mlp = nn.Sequential(
                nn.Linear(input_width, 128),
                nn.ReLU(),
                nn.Linear(128, 128),
                nn.ReLU(),
                nn.Linear(128, output_width),
            )

        def forward(self, residual: Any, mask: Any) -> tuple[Any, Any]:
            if self.factor == 1:
                pooled_residual = residual
                pooled_mask = mask
            else:
                pooled_residual = torch.nn.functional.avg_pool1d(
                    residual[:, None, :], self.factor, self.factor
                ).squeeze(1)
                pooled_mask = torch.nn.functional.avg_pool1d(
                    mask[:, None, :], self.factor, self.factor
                ).squeeze(1)
            theta = self.mlp(torch.cat((pooled_residual, pooled_mask), dim=1))
            backcast_pooled = theta[:, : self.pooled_length]
            latent = theta[:, self.pooled_length :]
            if self.factor == 1:
                backcast = backcast_pooled
            else:
                backcast = torch.nn.functional.interpolate(
                    backcast_pooled[:, None, :],
                    size=CONTEXT_LENGTH,
                    mode="linear",
                    align_corners=False,
                ).squeeze(1)
            return backcast, latent

    class NHiTSForecaster(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.blocks = nn.ModuleList(NHiTSBlock(factor) for factor in (1, 4, 16))
            self.decoder = _make_decoder(64)

        def forward(self, history: Any, issue_context: Any, target_context: Any) -> Any:
            _validate_inputs(history, issue_context, target_context)
            residual = history[:, :, 0]
            mask = history[:, :, 1]
            latent = torch.zeros((history.shape[0], 64), device=history.device, dtype=history.dtype)
            for block in self.blocks:
                backcast, block_latent = block(residual, mask)
                residual = residual - backcast
                latent = latent + block_latent
            return self.decoder(latent, issue_context, target_context)

    return NHiTSForecaster()


def make_patchtst_model() -> Any:
    torch, nn = _torch_modules()
    patch_length = 16
    stride = 8
    patch_count = 1 + (CONTEXT_LENGTH - patch_length) // stride

    class PatchTSTForecaster(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.patch_projection = nn.Linear(patch_length * HISTORY_CHANNELS, 64)
            self.position = nn.Parameter(torch.zeros(1, patch_count, 64))
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
            self.norm = nn.LayerNorm(64)
            self.decoder = _make_decoder(64)

        def forward(self, history: Any, issue_context: Any, target_context: Any) -> Any:
            _validate_inputs(history, issue_context, target_context)
            patches = history.unfold(1, patch_length, stride)
            patches = patches.permute(0, 1, 3, 2).reshape(history.shape[0], patch_count, -1)
            encoded = self.patch_projection(patches) + self.position
            encoded = self.norm(self.encoder(encoded))
            latent = encoded.mean(dim=1)
            return self.decoder(latent, issue_context, target_context)

    return PatchTSTForecaster()


MODEL_FACTORIES: dict[str, ModelFactory] = {
    "GRU": make_gru_model,
    "TCN": make_tcn_model,
    "NHiTS": make_nhits_model,
    "PatchTST": make_patchtst_model,
}


def make_model(name: str) -> Any:
    try:
        return MODEL_FACTORIES[name]()
    except KeyError as exc:
        raise R11S0ContractError("UNKNOWN_MODEL_FAMILY") from exc


def trainable_parameter_count(model: Any) -> int:
    return int(sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad))
