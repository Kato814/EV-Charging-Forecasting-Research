"""Explicitly authorized, fixed-order JPL seasonal acquisition and QA CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TextIO

from evcf.data.acn_api import DEFAULT_TOKEN_ENV, ACNClient
from evcf.data.acn_jpl_full_month_qa import generate_month_timeseries_qa
from evcf.data.acn_jpl_month_config import (
    SEASONAL_MONTHS,
    JPLMonthConfig,
    jpl_month_config,
    load_verified_complete_metadata,
)
from evcf.data.acn_jpl_official_reference import probe_official_local_month_total
from evcf.data.acn_jpl_seasonal_acquisition import acquire_jpl_month

SEASONAL_AUTHORIZATION_MESSAGE = "未授权 JPL 季节月份时序采集；必须显式提供 --authorize-seasonal。"
SEASONAL_MISSING_TOKEN_MESSAGE = "ACN_API_TOKEN 未配置；请仅在本地环境变量中设置后重试。"
_SAFE_REASON_CODES = frozenset(
    {
        "SCOPE_NOT_VERIFIED",
        "MONTH_NOT_SEASONAL",
        "OFFICIAL_PROBE_FAILED",
        "OFFICIAL_PROBE_NOT_LIVE",
        "OFFICIAL_REFERENCE_LOCATION_INVALID",
        "OFFICIAL_TOTAL_MISMATCH",
        "DAILY_INCOMPLETE",
        "DAILY_LINKAGE_FAIL",
        "CARRY_INCOMPLETE",
        "COMBINED_LINKAGE_FAIL",
        "PARTIAL_FILES_PRESENT",
        "RAW_LAYOUT_INVALID",
        "ACN_DATA_ERROR",
        "NETWORK_ERROR",
        "INCOMPLETE_RESPONSE",
        "RAW_SNAPSHOT_INVALID",
        "RAW_SNAPSHOT_CHANGED",
        "LOCAL_LINKAGE_FAIL",
        "CARRY_LINKAGE_FAIL",
        "ACQUISITION_INCOMPLETE",
        "INVALID_CONTAINER_RATE_EXCEEDED",
        "TIMESTAMP_QUALITY_FAIL",
        "UNEXPECTED_ERROR",
    }
)


def _nonnegative(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _default_month_executor(
    *,
    config: JPLMonthConfig,
    token: str,
    metadata_root: Path,
    raw_root: Path,
    concurrency: int,
) -> dict[str, Any]:
    scope = load_verified_complete_metadata(metadata_root, config)
    reference = raw_root / "state" / "official_local_month_total.json"

    def live_probe(month: JPLMonthConfig):  # type: ignore[no-untyped-def]
        reference.unlink(missing_ok=True)
        reference.with_suffix(reference.suffix + ".partial").unlink(missing_ok=True)
        return probe_official_local_month_total(
            ACNClient(token),
            reference,
            month=month,
        )

    acquisition = acquire_jpl_month(
        authorized=True,
        config=config,
        scope=scope,
        official_probe=live_probe,
        raw_root=raw_root,
        ts_client_factory=lambda: ACNClient(token),
        concurrency=concurrency,
    )
    qa_result = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw_root,
        acquisition_result=acquisition,
        sensitive_values=(token,),
    )
    integrity = qa_result.qa.get("integrity", {})
    daily = integrity.get("daily_chunks", {})
    local = integrity.get("local_month", {})
    carry = integrity.get("carry_in", {})
    combined = integrity.get("combined", {})
    qa_gate = qa_result.qa.get("gate", {})
    reasons = tuple(acquisition.reason_codes) + tuple(qa_gate.get("reason_codes", ()))
    return {
        "month": config.month,
        "acquisition_status": acquisition.status,
        "qa_status": qa_result.gate_status,
        "valid_daily_chunks": daily.get("valid"),
        "local_records": local.get("observed_records"),
        "carry_records": carry.get("observed_records"),
        "combined_records": combined.get("observed_records"),
        "reason_codes": reasons,
    }


def _safe_month_result(config: JPLMonthConfig, value: object) -> dict[str, Any]:
    payload = value if isinstance(value, Mapping) else {}
    acquisition_status = payload.get("acquisition_status")
    qa_status = payload.get("qa_status")
    raw_reasons = payload.get("reason_codes")
    reasons = (
        [
            reason
            for reason in raw_reasons
            if isinstance(reason, str) and reason in _SAFE_REASON_CODES
        ]
        if isinstance(raw_reasons, (list, tuple))
        else []
    )
    valid_daily = _nonnegative(payload.get("valid_daily_chunks"))
    local_records = _nonnegative(payload.get("local_records"))
    carry_records = _nonnegative(payload.get("carry_records"))
    combined_records = _nonnegative(payload.get("combined_records"))
    passed = (
        payload.get("month") == config.month
        and acquisition_status == "COMPLETE"
        and qa_status == "PASS"
        and valid_daily == config.day_count
        and combined_records == local_records + carry_records
        and not reasons
    )
    if not passed and not reasons:
        reasons = ["UNEXPECTED_ERROR"]
    return {
        "month": config.month,
        "status": "PASS" if passed else "FAIL",
        "valid_daily_chunks": valid_daily,
        "failed_daily_chunks": config.day_count - min(valid_daily, config.day_count),
        "local_records": local_records,
        "carry_records": carry_records,
        "combined_records": combined_records,
        "reason_codes": reasons,
    }


def run_seasonal_cli(
    *,
    authorized: bool,
    metadata_root: str | Path,
    raw_root: str | Path,
    concurrency: int = 1,
    environ: Mapping[str, str] = os.environ,
    month_executor: Callable[..., object] = _default_month_executor,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run all approved months serially and print only aggregate status."""

    del stderr
    if authorized is not True:
        print(SEASONAL_AUTHORIZATION_MESSAGE, file=stdout)
        return 2
    if (
        not isinstance(concurrency, int)
        or isinstance(concurrency, bool)
        or concurrency not in {1, 2}
    ):
        raise ValueError("concurrency must be 1 or 2")
    token = environ.get(DEFAULT_TOKEN_ENV)
    if not isinstance(token, str) or not token.strip():
        print(SEASONAL_MISSING_TOKEN_MESSAGE, file=stdout)
        return 2
    clean_token = token.strip()

    results: list[dict[str, Any]] = []
    for month in SEASONAL_MONTHS:
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
        except Exception:  # noqa: BLE001 - never emit URL, query, token, or path details
            safe_result = {
                "month": config.month,
                "status": "FAIL",
                "valid_daily_chunks": 0,
                "failed_daily_chunks": config.day_count,
                "local_records": 0,
                "carry_records": 0,
                "combined_records": 0,
                "reason_codes": ["UNEXPECTED_ERROR"],
            }
        results.append(safe_result)

    payload = {
        "status": "COMPLETE" if all(item["status"] == "PASS" for item in results) else "INCOMPLETE",
        "months": results,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stdout)
    return 0 if payload["status"] == "COMPLETE" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Acquire and QA the fixed JPL 2019 seasonal replication months"
    )
    parser.add_argument(
        "--authorize-seasonal",
        action="store_true",
        help="literal opt-in required before any credential, metadata, client, or file access",
    )
    parser.add_argument("--metadata-root", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, choices=(1, 2), default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return run_seasonal_cli(
        authorized=args.authorize_seasonal,
        metadata_root=args.metadata_root,
        raw_root=args.raw_root,
        concurrency=args.concurrency,
    )


if __name__ == "__main__":
    raise SystemExit(main())
