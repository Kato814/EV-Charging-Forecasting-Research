"""CLI for the frozen zero-fit JPL R10-R0 robustness/readiness audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evcf.forecasting.acn_jpl_r10_r0_r7_robustness_readiness import R10R0Error, run_r10_r0


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-r10-r0-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "fit_count": 0,
        "model_fit_attempted": False,
        "holdout_accessed": False,
        "reference_models_retrained": False,
        "r7_candidate_retrained": False,
        "hyperparameter_search": False,
        "feature_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "gate_trained": False,
        "moe_trained": False,
        "neural_model_trained": False,
        "survival_model_trained": False,
        "tpp_model_trained": False,
        "network_data_acquisition": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen zero-fit JPL R10-R0 development robustness/readiness audit"
    )
    parser.add_argument("--r7-d1-private-run", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--authorize-r10-r0", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.authorize_r10_r0:
        print(json.dumps(_failure("R10_R0_NOT_AUTHORIZED"), sort_keys=True))
        return 2
    try:
        result = run_r10_r0(
            authorized=True,
            r7_d1_private_run=args.r7_d1_private_run,
            code_commit=args.code_commit,
        )
    except R10R0Error as exc:
        print(json.dumps(_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, TypeError, ValueError, RuntimeError, FloatingPointError) as exc:
        reason = getattr(exc, "reason_code", "UNEXPECTED_ERROR")
        print(json.dumps(_failure(str(reason)), sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
