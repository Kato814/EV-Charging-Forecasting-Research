"""Selection logic and formal-environment guards for R11-S0.

Real-data fitting is intentionally separated from these pure helpers so that
selection thresholds can be unit-tested without touching development data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

from evcf.forecasting.r11_s0_contracts import PARAMETER_BAND, R11S0ContractError
from evcf.forecasting.r11_s0_models import MODEL_FACTORIES, make_model, trainable_parameter_count

FORMAL_GPU_NAME: Final[str] = "NVIDIA GeForce RTX 5080"
FORMAL_TORCH_VERSION_PREFIX: Final[str] = "2.14."
FORMAL_CUDA_PREFIX: Final[str] = "13.2"
POOLED_RELATIVE_CEILING: Final[float] = 0.02
WORST_CELL_RELATIVE_CEILING: Final[float] = 0.10
SEED_SPREAD_CEILING: Final[float] = 0.03
TIE_RELATIVE_BAND: Final[float] = 0.0025


@dataclass(frozen=True, slots=True)
class CandidateSummary:
    name: str
    pooled_mae_a: float
    worst_horizon_relative_degradation: float
    worst_month_relative_degradation: float
    seed_spread: float
    parameter_count: int
    folds_complete: bool

    def validate(self) -> None:
        if self.name not in MODEL_FACTORIES:
            raise R11S0ContractError("UNKNOWN_MODEL_FAMILY")
        numeric = (
            self.pooled_mae_a,
            self.worst_horizon_relative_degradation,
            self.worst_month_relative_degradation,
            self.seed_spread,
        )
        if not all(np.isfinite(value) for value in numeric) or self.pooled_mae_a < 0:
            raise R11S0ContractError("INVALID_CANDIDATE_SUMMARY")
        if self.parameter_count < PARAMETER_BAND[0] or self.parameter_count > PARAMETER_BAND[1]:
            raise R11S0ContractError("PARAMETER_COUNT_OUTSIDE_FROZEN_BAND")


def _eligible(candidate: CandidateSummary, station_hgb_pooled_mae_a: float) -> bool:
    return bool(
        candidate.folds_complete
        and candidate.pooled_mae_a <= (1.0 + POOLED_RELATIVE_CEILING) * station_hgb_pooled_mae_a
        and candidate.worst_horizon_relative_degradation <= WORST_CELL_RELATIVE_CEILING
        and candidate.worst_month_relative_degradation <= WORST_CELL_RELATIVE_CEILING
        and candidate.seed_spread <= SEED_SPREAD_CEILING
    )


def decide_backbone(
    station_hgb_pooled_mae_a: float,
    candidates: Mapping[str, CandidateSummary],
) -> tuple[str, str | None, dict[str, Any]]:
    if not np.isfinite(station_hgb_pooled_mae_a) or station_hgb_pooled_mae_a <= 0:
        raise R11S0ContractError("INVALID_STATION_HGB_REFERENCE")
    if tuple(candidates) != tuple(MODEL_FACTORIES):
        raise R11S0ContractError("CANDIDATE_SET_INVALID")
    for name, candidate in candidates.items():
        candidate.validate()
        if name != candidate.name:
            raise R11S0ContractError("CANDIDATE_SET_INVALID")

    eligible = [candidate for candidate in candidates.values() if _eligible(candidate, station_hgb_pooled_mae_a)]
    support = {
        name: {
            "eligible": _eligible(candidate, station_hgb_pooled_mae_a),
            "pooled_relative_degradation": candidate.pooled_mae_a / station_hgb_pooled_mae_a - 1.0,
            "worst_horizon_relative_degradation": candidate.worst_horizon_relative_degradation,
            "worst_month_relative_degradation": candidate.worst_month_relative_degradation,
            "seed_spread": candidate.seed_spread,
            "parameter_count": candidate.parameter_count,
            "folds_complete": candidate.folds_complete,
        }
        for name, candidate in candidates.items()
    }
    if eligible:
        ranked = sorted(eligible, key=lambda item: (item.pooled_mae_a, item.parameter_count, item.name))
        selected = ranked[0]
        if len(ranked) > 1:
            second = ranked[1]
            relative_gap = (second.pooled_mae_a - selected.pooled_mae_a) / selected.pooled_mae_a
            if relative_gap < TIE_RELATIVE_BAND:
                selected = min((selected, second), key=lambda item: (item.parameter_count, item.pooled_mae_a, item.name))
        return "SELECT_STATION_BACKBONE", selected.name, support

    near = [
        candidate
        for candidate in candidates.values()
        if candidate.pooled_mae_a <= (1.0 + POOLED_RELATIVE_CEILING) * station_hgb_pooled_mae_a
        and candidate.seed_spread <= SEED_SPREAD_CEILING
    ]
    if near:
        return "MIXED_STATION_BACKBONE", None, support
    return "STOP_DEEP_CORE_ROUTE", None, support


def parameter_preflight() -> dict[str, int]:
    """Build all four frozen models without labels and return exact parameter counts."""

    counts: dict[str, int] = {}
    for name in MODEL_FACTORIES:
        model = make_model(name)
        count = trainable_parameter_count(model)
        if not PARAMETER_BAND[0] <= count <= PARAMETER_BAND[1]:
            raise R11S0ContractError("PARAMETER_COUNT_OUTSIDE_FROZEN_BAND")
        counts[name] = count
    return counts


def validate_formal_device() -> dict[str, str]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise R11S0ContractError("TORCH_UNAVAILABLE") from exc
    if not str(torch.__version__).startswith(FORMAL_TORCH_VERSION_PREFIX):
        raise R11S0ContractError("TORCH_VERSION_INVALID")
    if torch.version.cuda is None or not str(torch.version.cuda).startswith(FORMAL_CUDA_PREFIX):
        raise R11S0ContractError("CUDA_VERSION_INVALID")
    if not torch.cuda.is_available():
        raise R11S0ContractError("CUDA_UNAVAILABLE")
    if torch.cuda.device_count() < 1:
        raise R11S0ContractError("CUDA_DEVICE_MISSING")
    device_name = torch.cuda.get_device_name(0)
    if device_name != FORMAL_GPU_NAME:
        raise R11S0ContractError("GPU_IDENTITY_INVALID")
    return {
        "torch": str(torch.__version__),
        "cuda": str(torch.version.cuda),
        "device": "cuda:0",
        "gpu_name": device_name,
    }
