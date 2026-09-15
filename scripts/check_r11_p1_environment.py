"""Fail-closed environment preflight for R11-P1."""

from __future__ import annotations

import json

from evcf.forecasting.acn_jpl_r11_p1_privileged_arrival import (
    R11P1Error,
    validate_model_environment,
)


def main() -> int:
    try:
        result = {"status": "PASS", **dict(validate_model_environment())}
    except R11P1Error as exc:
        print(json.dumps({"status": "FAIL", "reason_code": exc.reason_code}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
