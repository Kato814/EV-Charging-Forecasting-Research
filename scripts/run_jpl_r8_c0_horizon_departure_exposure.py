"""CLI for the frozen JPL/ACN R8-C0 horizon departure exposure probe."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evcf.forecasting.acn_jpl_r8_c0_horizon_departure_exposure import (
    R8C0Error,
    run_r8_c0,
)


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-r8-c0-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "fit_count": 0,
        "model_fit_attempted": False,
        "holdout_accessed": False,
        "reference_models_retrained": False,
        "r7_d1_references_retrained": False,
        "hyperparameter_search": False,
        "feature_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "gate_trained": False,
        "moe_trained": False,
        "neural_model_trained": False,
        "survival_model_trained": False,
        "tpp_model_trained": False,
        "current_weighted_departure_feature": False,
        "pilot_weighted_departure_feature": False,
        "energy_weighted_departure_feature": False,
        "actual_disconnect_predictor": False,
        "actual_done_charging_predictor": False,
    }


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen JPL R8-C0 horizon-aligned departure exposure probe"
    )
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--r7-d1-private-run", type=Path, required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--authorize-r8-c0", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.authorize_r8_c0:
        print(json.dumps(_failure("R8_C0_NOT_AUTHORIZED"), sort_keys=True))
        return 2
    try:
        result = run_r8_c0(
            authorized=True,
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            r7_d1_private_run=args.r7_d1_private_run,
            private_output_root=args.private_output_root,
            code_commit=args.code_commit,
            repo_root=args.repo_root,
            progress=_progress,
        )
    except R8C0Error as exc:
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
