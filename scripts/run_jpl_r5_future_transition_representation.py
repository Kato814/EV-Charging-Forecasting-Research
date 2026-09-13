"""CLI for the frozen JPL/ACN R5 FTAR development experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evcf.forecasting.acn_jpl_r5_future_transition_representation_compat import (
    R5Error,
    run_r5,
)


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-r5-ftar-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "fit_count": 0,
        "holdout_accessed": False,
        "hyperparameter_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "gate_trained": False,
        "moe_trained": False,
        "set_transformer_trained": False,
        "reference_models_retrained": False,
    }


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--baseline-private-run", type=Path, required=True)
    parser.add_argument("--structured-private-run", type=Path, required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--authorize-r5", action="store_true")
    args = parser.parse_args()

    if not args.authorize_r5:
        print(json.dumps(_failure("R5_NOT_AUTHORIZED"), sort_keys=True))
        return 2
    try:
        result = run_r5(
            authorized=True,
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            baseline_private_run=args.baseline_private_run,
            structured_private_run=args.structured_private_run,
            private_output_root=args.private_output_root,
            code_commit=args.code_commit,
            repo_root=args.repo_root,
            progress=_progress,
        )
    except R5Error as exc:
        print(json.dumps(_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, TypeError, ValueError, RuntimeError, FloatingPointError):
        print(json.dumps(_failure("UNEXPECTED_ERROR"), sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
