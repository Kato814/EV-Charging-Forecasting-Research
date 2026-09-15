"""Fail-closed CUDA/device preflight for the formal R11-S0 run."""

from __future__ import annotations

import json

from evcf.forecasting.r11_s0_contracts import R11S0ContractError
from evcf.forecasting.r11_s0_screen import validate_formal_device


def main() -> int:
    try:
        result = validate_formal_device()
    except R11S0ContractError as exc:
        print(json.dumps({"status": "FAIL", "reason_code": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "PASS", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
