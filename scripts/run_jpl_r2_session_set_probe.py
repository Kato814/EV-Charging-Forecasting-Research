"""CLI for the frozen JPL/ACN R2 higher-order origin-active session-set probe."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evcf.forecasting.acn_jpl_r2_session_set_probe import R2ProbeError, run_r2_probe


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-r2-higher-order-session-set-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "holdout_accessed": False,
        "hyperparameter_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "realized_composition_predictor": False,
        "future_session_generation": False,
        "set_transformer_trained": False,
        "moe_trained": False,
    }


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--r1-private-run", type=Path, required=True)
    parser.add_argument("--private-output-dir", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--authorize-r2", action="store_true")
    args = parser.parse_args()

    if not args.authorize_r2:
        print(json.dumps(_failure("R2_NOT_AUTHORIZED"), sort_keys=True))
        return 2

    try:
        result = run_r2_probe(
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            r1_private_run=args.r1_private_run,
            private_output_dir=args.private_output_dir,
            code_commit=args.code_commit,
            repo_root=args.repo_root,
            progress=_progress,
        )
    except R2ProbeError as exc:
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
