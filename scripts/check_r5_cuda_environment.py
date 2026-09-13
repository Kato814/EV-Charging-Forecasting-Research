"""Fail-closed CUDA preflight for the formal R5 FTAR experiment."""

from __future__ import annotations

import json

from evcf.forecasting.acn_jpl_r5_future_transition_representation import (
    R5Error,
    validate_formal_device,
)


def main() -> int:
    try:
        result = dict(validate_formal_device())
    except R5Error as exc:
        print(json.dumps({"status": "FAIL", "reason_code": exc.reason_code}, sort_keys=True))
        return 2
    print(json.dumps({"status": "PASS", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
