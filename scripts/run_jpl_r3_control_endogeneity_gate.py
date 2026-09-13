"""CLI for the frozen JPL/ACN R3-C0 control-endogeneity gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evcf.forecasting.acn_jpl_r3_control_endogeneity_gate import (
    R3C0Error,
    run_gate,
)


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-r3-c0-control-endogeneity-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "fit_count": 0,
        "model_fit_attempted": False,
        "reference_models_retrained": False,
        "holdout_accessed": False,
        "hyperparameter_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "future_control_predictor": False,
        "causal_claim": False,
    }


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--r2-private-run", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--authorize-r3-c0", action="store_true")
    args = parser.parse_args()

    if not args.authorize_r3_c0:
        print(json.dumps(_failure("R3_C0_NOT_AUTHORIZED"), sort_keys=True))
        return 2

    try:
        result = run_gate(
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            r2_private_run=args.r2_private_run,
            code_commit=args.code_commit,
            repo_root=args.repo_root,
            progress=_progress,
        )
    except R3C0Error as exc:
        print(json.dumps(_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, TypeError, ValueError, RuntimeError, FloatingPointError) as exc:
        reason = getattr(exc, "reason_code", "UNEXPECTED_ERROR")
        if not isinstance(reason, str) or not reason.replace("_", "").isalnum():
            reason = "UNEXPECTED_ERROR"
        print(json.dumps(_failure(reason), sort_keys=True))
        return 2

    print(json.dumps(result.to_public_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
