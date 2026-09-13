"""CLI for the frozen JPL/ACN R4-D1 state-geometry diagnostic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evcf.forecasting.acn_jpl_r4_d1_state_geometry_diagnostic import (
    R4D1Error,
    run_diagnostic,
)


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-r4-d1-state-geometry-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "fit_count": 0,
        "model_fit_attempted": False,
        "holdout_accessed": False,
        "reference_models_retrained": False,
        "alternate_analog_rule": False,
        "metric_learning": False,
        "pca_or_feature_selection": False,
        "target_informed_matching": False,
    }


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--authorize-r4-d1", action="store_true")
    args = parser.parse_args()

    if not args.authorize_r4_d1:
        print(json.dumps(_failure("R4_D1_NOT_AUTHORIZED"), sort_keys=True))
        return 2

    try:
        result = run_diagnostic(
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            code_commit=args.code_commit,
            repo_root=args.repo_root,
            progress=_progress,
        )
    except R4D1Error as exc:
        print(json.dumps(_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, TypeError, ValueError, RuntimeError, FloatingPointError):
        print(json.dumps(_failure("UNEXPECTED_ERROR"), sort_keys=True))
        return 2

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
