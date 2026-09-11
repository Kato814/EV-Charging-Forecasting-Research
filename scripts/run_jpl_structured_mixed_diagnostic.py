"""Authorized read-only diagnostic for the completed JPL S1 MIXED result."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

AUTHORIZATION_MESSAGE = (
    "未授权JPL S1 MIXED只读诊断；必须显式提供 --authorize-mixed-diagnostic。"
)
_SAFE_REASONS = frozenset(
    {
        "BASELINE_CACHE_INVALID",
        "CACHE_ARRAY_INVALID",
        "COMMON_ROW_IDENTITY_INVALID",
        "DIAGNOSTIC_EMPTY",
        "MIXED_DIAGNOSTIC_NOT_AUTHORIZED",
        "PRIVATE_PARENT_INVALID",
        "PRIVATE_RUN_NOT_UNIQUE",
        "STRUCTURED_CACHE_INVALID",
        "UNEXPECTED_ERROR",
    }
)


def run_cli(
    *,
    authorized: bool,
    structured_private_parent: str | Path,
    baseline_private_parent: str | Path,
    stdout: TextIO = sys.stdout,
) -> int:
    if authorized is not True:
        print(AUTHORIZATION_MESSAGE, file=stdout)
        return 2
    try:
        from evcf.forecasting.acn_jpl_structured_mixed_diagnostic import (
            run_structured_mixed_diagnostic,
        )

        payload = run_structured_mixed_diagnostic(
            authorized=True,
            structured_private_parent=structured_private_parent,
            baseline_private_parent=baseline_private_parent,
        )
    except Exception as exc:  # noqa: BLE001 - private exception text is never published
        reason = getattr(exc, "reason_code", "UNEXPECTED_ERROR")
        if reason not in _SAFE_REASONS:
            reason = "UNEXPECTED_ERROR"
        payload = {
            "schema_version": "evcf-jpl-structured-s1-mixed-diagnostic/v1",
            "status": "FAIL",
            "reason_code": reason,
            "decision_context": "MIXED_STRUCTURED_SIGNAL",
            "holdout_accessed": False,
            "training_performed": False,
            "model_parameters_changed": False,
            "row_level_output": False,
        }
        print(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
            file=stdout,
        )
        return 1
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        file=stdout,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run aggregate-only residual diagnostics on the already-completed "
            "development S1 MIXED result. No model fitting is performed."
        )
    )
    parser.add_argument("--authorize-mixed-diagnostic", action="store_true")
    parser.add_argument("--structured-private-parent", type=Path, required=True)
    parser.add_argument("--baseline-private-parent", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.authorize_mixed_diagnostic and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return run_cli(
        authorized=args.authorize_mixed_diagnostic,
        structured_private_parent=args.structured_private_parent,
        baseline_private_parent=args.baseline_private_parent,
    )


if __name__ == "__main__":
    raise SystemExit(main())
