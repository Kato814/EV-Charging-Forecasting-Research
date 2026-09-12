"""CLI for the frozen JPL P1 structured mechanism probe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    MechanismProbeError,
    run_structured_mechanism_probe,
)


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-structured-mechanism-p1-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "holdout_accessed": False,
        "hyperparameter_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "neural_survival_trained": False,
        "neural_tpp_trained": False,
        "gate_trained": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--baseline-private-run", type=Path, required=True)
    parser.add_argument("--structured-private-run", type=Path, required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--authorize-mechanism-probe", action="store_true")
    args = parser.parse_args()

    if not args.authorize_mechanism_probe:
        print(json.dumps(_failure("MECHANISM_PROBE_NOT_AUTHORIZED"), sort_keys=True))
        return 2
    try:
        result = run_structured_mechanism_probe(
            authorized=True,
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            baseline_private_run=args.baseline_private_run,
            structured_private_run=args.structured_private_run,
            private_output_root=args.private_output_root,
            code_commit=args.code_commit,
            repo_root=args.repo_root,
        )
    except MechanismProbeError as exc:
        print(json.dumps(_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, ValueError):
        print(json.dumps(_failure("UNEXPECTED_ERROR"), sort_keys=True))
        return 2
    print(json.dumps(result.to_public_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
