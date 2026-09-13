"""CLI for the frozen JPL/ACN R4-I0 information-sufficiency gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evcf.forecasting.acn_jpl_r4_information_sufficiency_gate import (
    R4I0Error,
    run_gate,
)


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-r4-i0-information-sufficiency-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "fit_count": 0,
        "model_fit_attempted": False,
        "reference_models_retrained": False,
        "holdout_accessed": False,
        "target_informed_matching": False,
        "pca_or_metric_learning": False,
        "nearest_neighbor_forecast_trained": False,
    }


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--authorize-r4-i0", action="store_true")
    args = parser.parse_args()

    if not args.authorize_r4_i0:
        print(json.dumps(_failure("R4_I0_NOT_AUTHORIZED"), sort_keys=True))
        return 2

    try:
        result = run_gate(
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            code_commit=args.code_commit,
            repo_root=args.repo_root,
            progress=_progress,
        )
    except R4I0Error as exc:
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
