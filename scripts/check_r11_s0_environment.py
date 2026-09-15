"""Fail-closed environment and parameter-count preflight for R11-S0."""

from __future__ import annotations

import argparse
import json

from evcf.forecasting.acn_jpl_r11_s0_common import R11S0Error
from evcf.forecasting.acn_jpl_r11_s0_models import (
    import_torch,
    parameter_count_report,
    validate_formal_device,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--shape-only",
        action="store_true",
        help="Report architecture parameter counts without requiring the formal GPU environment.",
    )
    args = parser.parse_args()
    try:
        torch = import_torch()
        counts = dict(parameter_count_report(torch))
        result: dict[str, object] = {
            "status": "PASS",
            "shape_only": bool(args.shape_only),
            "parameter_counts": counts,
        }
        if not args.shape_only:
            result.update(dict(validate_formal_device()))
    except R11S0Error as exc:
        print(json.dumps({"status": "FAIL", "reason_code": exc.reason_code}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
