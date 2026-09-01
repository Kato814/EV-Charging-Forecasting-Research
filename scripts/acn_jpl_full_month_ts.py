"""Explicitly authorized JPL May 2019 full-month ``/ts`` acquisition and QA CLI.

The command has no implicit download mode.  It requires the literal runtime flag,
caller-provided metadata/raw roots, and ``ACN_API_TOKEN`` from the environment.
Only aggregate status is printed; raw/state material remains under the ignored root.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

from evcf.data.acn_api import DEFAULT_TOKEN_ENV, ACNClient
from evcf.data.acn_jpl_full_month_qa import generate_full_month_timeseries_qa
from evcf.data.acn_jpl_full_month_ts import run_full_month_timeseries

DEFAULT_OUTPUT_ROOT = Path("outputs/acn_gate0/jpl_2019-05-full-ts")
FULL_MONTH_AUTHORIZATION_MESSAGE = "未授权完整月份时序采集；必须显式提供 --authorize-full-month。"
FULL_MONTH_MISSING_TOKEN_MESSAGE = "ACN_API_TOKEN 未配置；请仅在本地环境变量中设置后重试。"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_nonnegative_int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _aggregate_stdout(
    acquisition: Mapping[str, Any],
    qa_result: Any,
) -> dict[str, Any]:
    qa = _mapping(getattr(qa_result, "qa", {}))
    integrity = _mapping(qa.get("integrity"))
    daily = _mapping(integrity.get("daily_chunks"))
    local = _mapping(integrity.get("local_month"))
    carry = _mapping(integrity.get("carry_in"))
    combined = _mapping(integrity.get("combined"))
    gate = _mapping(qa.get("gate"))
    acquisition_status = acquisition.get("status")
    if acquisition_status not in {"COMPLETE", "INCOMPLETE"}:
        acquisition_status = "INCOMPLETE"
    qa_status = gate.get("status")
    if qa_status not in {"PASS", "FAIL"}:
        qa_status = "FAIL"
    ready_15_min = gate.get("ready_for_15_min")
    if ready_15_min not in {"YES_CURRENT_PROXY_ONLY", "NO"}:
        ready_15_min = "NO"
    return {
        "acquisition_status": acquisition_status,
        "qa_status": qa_status,
        "valid_daily_chunks": _safe_nonnegative_int(daily.get("valid")),
        "failed_daily_chunks": _safe_nonnegative_int(daily.get("failed_or_incomplete")),
        "local_records": _safe_nonnegative_int(local.get("observed_records")),
        "carry_records": _safe_nonnegative_int(carry.get("observed_records")),
        "combined_records": _safe_nonnegative_int(combined.get("observed_records")),
        "ready_for_cleaning": gate.get("ready_for_cleaning") is True,
        "ready_for_15_min": ready_15_min,
        "gate1_ready": "NO",
    }


def run_full_month_cli(
    *,
    authorized: bool,
    metadata_root: str | Path,
    raw_root: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    environ: Mapping[str, str] = os.environ,
    client_factory: Callable[[], Any] | None = None,
    acquisition_runner: Callable[..., Mapping[str, Any]] = run_full_month_timeseries,
    qa_runner: Callable[..., Any] = generate_full_month_timeseries_qa,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run acquisition then QA, with fail-closed preconditions and safe stdout."""

    if authorized is not True:
        print(FULL_MONTH_AUTHORIZATION_MESSAGE, file=stdout)
        return 2

    token = environ.get(DEFAULT_TOKEN_ENV)
    if token is None or not token.strip():
        print(FULL_MONTH_MISSING_TOKEN_MESSAGE, file=stdout)
        return 2
    clean_token = token.strip()
    factory = client_factory if client_factory is not None else lambda: ACNClient(clean_token)

    try:
        acquisition = acquisition_runner(
            authorized=True,
            metadata_root=metadata_root,
            raw_root=raw_root,
            client_factory=factory,
        )
    except Exception:  # noqa: BLE001 - never echo private exception material
        acquisition = {"status": "INCOMPLETE"}

    try:
        qa_result = qa_runner(
            metadata_root=metadata_root,
            raw_root=raw_root,
            output_root=output_root,
            acquisition_result=acquisition,
            sensitive_values=(clean_token,),
        )
    except Exception:  # noqa: BLE001 - keep stdout aggregate-only and secret-free
        payload = {
            "acquisition_status": (
                "COMPLETE" if acquisition.get("status") == "COMPLETE" else "INCOMPLETE"
            ),
            "qa_status": "FAIL",
            "valid_daily_chunks": 0,
            "failed_daily_chunks": 31,
            "local_records": 0,
            "carry_records": 0,
            "combined_records": 0,
            "ready_for_cleaning": False,
            "ready_for_15_min": "NO",
            "gate1_ready": "NO",
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stdout)
        return 1

    payload = _aggregate_stdout(acquisition, qa_result)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stdout)
    return (
        0 if (payload["acquisition_status"] == "COMPLETE" and payload["qa_status"] == "PASS") else 1
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Acquire/resume and QA the frozen JPL 2019-05 full-month time-series scope")
    )
    parser.add_argument(
        "--authorize-full-month",
        action="store_true",
        help="literal opt-in required before any credential, client, or file access",
    )
    parser.add_argument("--metadata-root", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return run_full_month_cli(
        authorized=args.authorize_full_month,
        metadata_root=args.metadata_root,
        raw_root=args.raw_root,
        output_root=args.output_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
