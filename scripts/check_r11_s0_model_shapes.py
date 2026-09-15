"""CPU-safe shape and parameter-count preflight for frozen R11-S0 models."""

from __future__ import annotations

import json

from evcf.forecasting.r11_s0_contracts import R11S0ContractError
from evcf.forecasting.r11_s0_models import MODEL_FACTORIES, make_model
from evcf.forecasting.r11_s0_screen import parameter_preflight


def main() -> int:
    try:
        counts = parameter_preflight()
        import torch

        batch = 2
        history = torch.zeros(batch, 96, 2, dtype=torch.float32)
        issue_context = torch.zeros(batch, 5, dtype=torch.float32)
        target_context = torch.zeros(batch, 5, 6, dtype=torch.float32)
        shapes = {}
        for name in MODEL_FACTORIES:
            model = make_model(name)
            output = model(history, issue_context, target_context)
            shapes[name] = list(output.shape)
            if tuple(output.shape) != (batch, 5):
                raise R11S0ContractError("MODEL_OUTPUT_SHAPE_INVALID")
    except (R11S0ContractError, ImportError) as exc:
        reason = exc.args[0] if exc.args else "UNEXPECTED_ERROR"
        print(json.dumps({"status": "FAIL", "reason_code": str(reason)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {"status": "PASS", "parameter_counts": counts, "output_shapes": shapes},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
