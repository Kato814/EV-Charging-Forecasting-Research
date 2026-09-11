"""CLI for the read-only JPL structured transition-map diagnostic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evcf.forecasting.acn_jpl_structured_mixed_diagnostic import (
    StructuredMixedDiagnosticError,
)
from evcf.forecasting.acn_jpl_structured_transition_diagnostic import (
    run_structured_transition_diagnostic,
)


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-structured-transition-diagnostic/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "analysis_only": True,
        "model_fit_attempted": False,
        "network_requests": False,
        "development_data_accessed": False,
        "holdout_accessed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-private-run", type=Path, required=True)
    parser.add_argument("--structured-private-run", type=Path, required=True)
    parser.add_argument("--authorize-transition-diagnostic", action="store_true")
    args = parser.parse_args()

    if not args.authorize_transition_diagnostic:
        print(json.dumps(_failure("TRANSITION_DIAGNOSTIC_NOT_AUTHORIZED"), sort_keys=True))
        return 2

    try:
        result = run_structured_transition_diagnostic(
            baseline_private_run=args.baseline_private_run,
            structured_private_run=args.structured_private_run,
        )
    except StructuredMixedDiagnosticError as exc:
        print(json.dumps(_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, ValueError):
        print(json.dumps(_failure("UNEXPECTED_ERROR"), sort_keys=True))
        return 2

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
