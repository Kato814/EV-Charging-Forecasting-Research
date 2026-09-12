"""CLI for read-only P1 mechanism-route post-mortem."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evcf.forecasting.acn_jpl_p1_postmortem import (
    P1PostmortemError,
    run_p1_postmortem,
)


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-p1-readonly-postmortem/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "analysis_only": True,
        "model_fit_attempted": False,
        "raw_or_processed_data_accessed": False,
        "holdout_accessed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p1-private-run", type=Path, required=True)
    parser.add_argument("--authorize-p1-postmortem", action="store_true")
    args = parser.parse_args()

    if not args.authorize_p1_postmortem:
        print(json.dumps(_failure("P1_POSTMORTEM_NOT_AUTHORIZED"), sort_keys=True))
        return 2
    try:
        result = run_p1_postmortem(p1_private_run=args.p1_private_run)
    except P1PostmortemError as exc:
        print(json.dumps(_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, ValueError):
        print(json.dumps(_failure("UNEXPECTED_ERROR"), sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
