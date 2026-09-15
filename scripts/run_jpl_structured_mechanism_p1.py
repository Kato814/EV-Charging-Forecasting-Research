"""CLI for the frozen development-only JPL structured mechanism P1 probe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evcf.forecasting.acn_jpl_structured_mechanism_p1_runtime import (
    MechanismP1Error,
    run_mechanism_p1,
)


def _safe_failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-structured-mechanism-p1-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "holdout_accessed": False,
        "development_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--baseline-private-root", type=Path, required=True)
    parser.add_argument("--s1-private-root", type=Path, required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--authorize-mechanism-p1", action="store_true")
    args = parser.parse_args()

    if not args.authorize_mechanism_p1:
        print(
            json.dumps(
                _safe_failure("MECHANISM_P1_NOT_AUTHORIZED"),
                sort_keys=True,
            )
        )
        return 2

    try:
        result = run_mechanism_p1(
            authorized=True,
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            baseline_private_root=args.baseline_private_root,
            s1_private_root=args.s1_private_root,
            private_output_root=args.private_output_root,
            code_commit=args.code_commit,
            repo_root=args.repo_root,
        )
    except MechanismP1Error as exc:
        print(json.dumps(_safe_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, ValueError):
        print(json.dumps(_safe_failure("UNEXPECTED_ERROR"), sort_keys=True))
        return 2

    print(
        json.dumps(
            result.to_public_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
