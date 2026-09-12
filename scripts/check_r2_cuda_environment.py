"""Fail-closed formal CUDA environment preflight for the frozen R2 probe."""

from __future__ import annotations

import json

from evcf.forecasting.acn_jpl_r2_session_set_probe import R2ProbeError, validate_formal_device


def main() -> int:
    try:
        info = dict(validate_formal_device())
    except R2ProbeError as exc:
        print(
            json.dumps(
                {
                    "schema_version": "evcf-jpl-r2-cuda-preflight/v1",
                    "status": "FAIL",
                    "reason_code": exc.reason_code,
                    "model_fit_attempted": False,
                },
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "schema_version": "evcf-jpl-r2-cuda-preflight/v1",
                "status": "PASS",
                "reason_code": None,
                "model_fit_attempted": False,
                **info,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
