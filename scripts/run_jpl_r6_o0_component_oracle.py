"""CLI for the frozen read-only JPL/ACN R6-O0 component-oracle diagnostic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evcf.forecasting.acn_jpl_r6_o0_component_oracle import R6O0Error, run_r6_o0


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-r6-o0-component-oracle-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "fit_count": 0,
        "model_fit_attempted": False,
        "raw_or_processed_data_accessed": False,
        "r5_private_predictions_accessed": False,
        "holdout_accessed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--s1-private-run", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--authorize-r6-o0", action="store_true")
    args = parser.parse_args()

    if not args.authorize_r6_o0:
        print(json.dumps(_failure("R6_O0_NOT_AUTHORIZED"), sort_keys=True))
        return 2
    try:
        result = run_r6_o0(
            authorized=True,
            s1_private_root=args.s1_private_run,
            code_commit=args.code_commit,
            repo_root=args.repo_root,
        )
    except R6O0Error as exc:
        print(json.dumps(_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, TypeError, ValueError, RuntimeError, FloatingPointError):
        print(json.dumps(_failure("UNEXPECTED_ERROR"), sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
