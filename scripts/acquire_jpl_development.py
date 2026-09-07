"""Explicitly authorized JPL 2019 method-development acquisition CLI.

Only 2019-01/04/07/10 are installed for the duration of this command. Final
holdout months 2019-03/06/09/12 remain unavailable by construction.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

from evcf.data.acn_api import DEFAULT_TOKEN_ENV
from evcf.data.acn_jpl_development_months import (
    DEVELOPMENT_MONTHS,
    installed_development_month_contracts,
)
from evcf.data.acn_jpl_month_config import jpl_month_config

from scripts.acquire_jpl_seasonal import _default_month_executor, _safe_month_result

DEVELOPMENT_AUTHORIZATION_MESSAGE = (
    "未授权 JPL 2019 方法开发月份时序采集；必须显式提供 --authorize-development。"
)
DEVELOPMENT_MISSING_TOKEN_MESSAGE = (
    "ACN_API_TOKEN 未配置；请仅在本地环境变量中设置后重试。"
)


def run_development_cli(
    *,
    authorized: bool,
    metadata_root: str | Path,
    raw_root: str | Path,
    concurrency: int = 1,
    environ: Mapping[str, str] = os.environ,
    month_executor: Callable[..., object] = _default_month_executor,
    stdout: TextIO = sys.stdout,
) -> int:
    """Acquire/QA the four frozen development months and emit aggregate JSON only."""

    if authorized is not True:
        print(DEVELOPMENT_AUTHORIZATION_MESSAGE, file=stdout)
        return 2
    if (
        not isinstance(concurrency, int)
        or isinstance(concurrency, bool)
        or concurrency not in {1, 2}
    ):
        raise ValueError("concurrency must be 1 or 2")
    token = environ.get(DEFAULT_TOKEN_ENV)
    if not isinstance(token, str) or not token.strip():
        print(DEVELOPMENT_MISSING_TOKEN_MESSAGE, file=stdout)
        return 2
    clean_token = token.strip()

    results: list[dict[str, Any]] = []
    with installed_development_month_contracts():
        for month in DEVELOPMENT_MONTHS:
            config = jpl_month_config(month)
            try:
                value = month_executor(
                    config=config,
                    token=clean_token,
                    metadata_root=Path(metadata_root),
                    raw_root=Path(raw_root) / config.month,
                    concurrency=concurrency,
                )
                safe_result = _safe_month_result(config, value)
            except Exception:  # noqa: BLE001 - never expose token, URL, path, or identifiers
                safe_result = {
                    "month": config.month,
                    "status": "FAIL",
                    "valid_daily_chunks": 0,
                    "failed_daily_chunks": config.day_count,
                    "local_records": 0,
                    "carry_records": 0,
                    "combined_records": 0,
                    "trajectory_quarantine_count": 0,
                    "trajectory_quarantine_rate": 0.0,
                    "full_session_quarantine_count": 0,
                    "reason_codes": ["UNEXPECTED_ERROR"],
                }
            results.append(safe_result)

    payload = {
        "schema_version": "evcf-jpl-development-acquisition/v1",
        "status": (
            "COMPLETE"
            if all(item["status"] == "PASS" for item in results)
            else "INCOMPLETE"
        ),
        "months": results,
        "holdout_accessed": False,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stdout)
    return 0 if payload["status"] == "COMPLETE" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Acquire and QA frozen JPL 2019 method-development months"
    )
    parser.add_argument(
        "--authorize-development",
        action="store_true",
        help="literal opt-in required before credential, metadata, network, or file access",
    )
    parser.add_argument("--metadata-root", type=Path, required=True)
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path("data/raw/acn/jpl/development"),
    )
    parser.add_argument("--concurrency", type=int, choices=(1, 2), default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.authorize_development and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return run_development_cli(
        authorized=args.authorize_development,
        metadata_root=args.metadata_root,
        raw_root=args.raw_root,
        concurrency=args.concurrency,
    )


if __name__ == "__main__":
    raise SystemExit(main())
