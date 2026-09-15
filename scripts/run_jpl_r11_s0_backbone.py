"""CLI for the frozen JPL/ACN R11-S0 station-level backbone screen."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evcf.forecasting.acn_jpl_r11_s0_backbone import R11S0Error, run_r11_s0


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-r11-s0-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "fit_count": None,
        "holdout_accessed": False,
        "session_predictors_used": False,
        "hyperparameter_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "model_ensemble": False,
    }


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--authorize-r11-s0", action="store_true")
    args = parser.parse_args()
    if not args.authorize_r11_s0:
        print(json.dumps(_failure("R11_S0_NOT_AUTHORIZED"), sort_keys=True))
        return 2
    try:
        result = run_r11_s0(
            repo_root=args.repo_root,
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            code_commit=args.code_commit,
            progress=_progress,
        )
    except R11S0Error as exc:
        print(json.dumps(_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, TypeError, ValueError, RuntimeError, FloatingPointError):
        print(json.dumps(_failure("UNEXPECTED_ERROR"), sort_keys=True))
        return 2
    print(json.dumps(result.to_public_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
