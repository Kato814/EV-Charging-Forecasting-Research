"""Explicitly authorized, local-only JPL Gate 1 preparation CLI.

The command performs no acquisition and never accesses the frozen raw snapshot
until the caller provides the literal ``--authorize-prepare`` flag.  Console
output is restricted to a small aggregate allowlist; detailed reports remain in
the pipeline's local and public artifact roots.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

from evcf.data.acn_jpl_preparation import (
    DEFAULT_INTERIM_ROOT,
    DEFAULT_PROCESSED_ROOT,
    DEFAULT_PUBLIC_ROOT,
    DEFAULT_RAW_ROOT,
)

PREPARATION_AUTHORIZATION_MESSAGE = "未授权JPL Gate 1数据准备；必须显式提供 --authorize-prepare。"

_OVERALL_STATUSES = frozenset({"PASS", "CONDITIONAL_PASS", "FAIL"})
_POWER_STATUSES = frozenset(
    {
        "KW_RECONSTRUCTION_CANDIDATE",
        "CURRENT_PROXY_ONLY",
        "POWER_SEMANTICS_FAIL",
    }
)


def _safe_nonnegative_int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _result_summary(result: Any) -> Mapping[str, Any]:
    if isinstance(result, Mapping):
        nested = result.get("summary")
        return nested if isinstance(nested, Mapping) else result
    summary = getattr(result, "summary", None)
    return summary if isinstance(summary, Mapping) else {}


def _aggregate_stdout(result: Any) -> dict[str, object]:
    """Reduce a pipeline result to non-sensitive, fixed-schema aggregates."""

    summary = _result_summary(result)
    status = summary.get("status")
    if status not in _OVERALL_STATUSES:
        status = "FAIL"

    raw_value = summary.get("raw_unchanged")
    raw_unchanged = "PASS" if raw_value is True or raw_value == "PASS" else "FAIL"

    power_status = summary.get("power_semantics_status")
    if power_status not in _POWER_STATUSES:
        power_status = "POWER_SEMANTICS_FAIL"

    training_environment_frozen = summary.get("training_environment_frozen")
    if training_environment_frozen != "NO":
        status = "FAIL"
    if raw_unchanged != "PASS":
        status = "FAIL"

    return {
        "status": status,
        "raw_unchanged": raw_unchanged,
        "sessions_processed": _safe_nonnegative_int(summary.get("sessions_processed")),
        "station_bins": _safe_nonnegative_int(summary.get("station_bins")),
        "scheduled_issue_times": _safe_nonnegative_int(summary.get("scheduled_issue_times")),
        "formal_issue_times": _safe_nonnegative_int(summary.get("formal_issue_times")),
        "power_semantics_status": power_status,
        "training_environment_frozen": "NO",
    }


def _failed_aggregate() -> dict[str, object]:
    return {
        "status": "FAIL",
        "raw_unchanged": "NOT_VERIFIED",
        "sessions_processed": 0,
        "station_bins": 0,
        "scheduled_issue_times": 0,
        "formal_issue_times": 0,
        "power_semantics_status": "NOT_RUN",
        "training_environment_frozen": "NO",
    }


def _default_runner(**kwargs: Any) -> Any:
    # Import only after the explicit authorization gate.  Besides keeping startup
    # light, this prevents an unauthorized command from triggering pipeline-level
    # imports or filesystem inspection.
    from evcf.data.acn_jpl_gate1_prep import prepare_jpl_gate1_data

    return prepare_jpl_gate1_data(**kwargs)


def run_prepare_cli(
    *,
    authorized: bool,
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    interim_root: str | Path = DEFAULT_INTERIM_ROOT,
    processed_root: str | Path = DEFAULT_PROCESSED_ROOT,
    public_root: str | Path = DEFAULT_PUBLIC_ROOT,
    runner: Callable[..., Any] | None = None,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run the local preparation pipeline behind an explicit authorization gate."""

    if authorized is not True:
        print(PREPARATION_AUTHORIZATION_MESSAGE, file=stdout)
        return 2

    selected_runner = runner if runner is not None else _default_runner
    try:
        result = selected_runner(
            raw_root=raw_root,
            interim_root=interim_root,
            processed_root=processed_root,
            public_root=public_root,
        )
        payload = _aggregate_stdout(result)
    except Exception as error:  # noqa: BLE001 - never echo private paths, records, or credentials
        payload = _aggregate_stdout(error) if _result_summary(error) else _failed_aggregate()

    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stdout)
    return 0 if payload["status"] in {"PASS", "CONDITIONAL_PASS"} else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare the frozen local JPL 2019-05 snapshot for Gate 1 without acquisition or training"
        )
    )
    parser.add_argument(
        "--authorize-prepare",
        action="store_true",
        help="literal opt-in required before any frozen raw snapshot access",
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--interim-root", type=Path, default=DEFAULT_INTERIM_ROOT)
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    parser.add_argument(
        "--output-root",
        "--public-root",
        dest="public_root",
        type=Path,
        default=DEFAULT_PUBLIC_ROOT,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return run_prepare_cli(
        authorized=args.authorize_prepare,
        raw_root=args.raw_root,
        interim_root=args.interim_root,
        processed_root=args.processed_root,
        public_root=args.public_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
