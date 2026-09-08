"""Explicitly authorized preparation for JPL 2019 method-development months.

The CLI has no arbitrary month selector. It may prepare only 2019-01/04/07/10
and emits aggregate, identifier-free status. Final holdout months remain outside
this execution surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

DEVELOPMENT_PREPARATION_AUTHORIZATION_MESSAGE = (
    "未授权 JPL 2019 方法开发月份数据准备；必须显式提供 --authorize-development-prepare。"
)
_DEFAULT_PROTOCOL_PATH = Path("code/configs/acn_jpl_development_prep_2019.yaml")
_SAFE_REASON_CODES = frozenset(
    {
        "ACQUISITION_INTEGRITY_FAILED",
        "ACQUISITION_QA_GATE_FAILED",
        "BOUNDARY_AUDIT_FAILED",
        "CLEANING_GATE_FAILED",
        "CLEANING_SENSITIVITY_FAILED",
        "CODE_BINDING_INVALID",
        "CONFIG_BINDING_INVALID",
        "DEVELOPMENT_MONTH_ORDER_INVALID",
        "DEVELOPMENT_RESULT_INVALID",
        "FEATURE_DIMENSION_INVALID",
        "FEATURE_TIER_INVALID",
        "HOLDOUT_ACCESS_INVALID",
        "IMPLEMENTATION_DRIFT",
        "INVALID_CONTAINER_METADATA_FAILED",
        "INVALID_CONTAINER_PARTITION_INVALID",
        "INVALID_CONTAINER_RATE_EXCEEDED",
        "ISSUE_SNAPSHOT_GATE_FAILED",
        "LOCAL_ARTIFACT_INVALID",
        "METADATA_SCOPE_INVALID",
        "MONTH_CONFIG_INVALID",
        "MONTH_RESULT_BINDING_INVALID",
        "OUTPUT_TOPOLOGY_INVALID",
        "POWER_SEMANTICS_GATE_FAILED",
        "PREPARATION_NOT_AUTHORIZED",
        "PROTOCOL_SCHEMA_INVALID",
        "RAW_RECORD_COUNT_INVALID",
        "TRAJECTORY_QUARANTINE_POLICY_FAIL",
        "FULL_SESSION_QUARANTINE_REQUIRED",
        "VALID_BIN_90_GATE_FAILED",
    }
)


def _safe_payload(result: Any) -> dict[str, Any]:
    months = []
    for item in result.months:
        months.append(
            {
                "month": item.month,
                "status": item.status,
                "sessions_processed": item.sessions_processed,
                "cleaned_session_count": item.cleaned_session_count,
                "invalid_skipped_session_count": item.invalid_skipped_session_count,
                "trajectory_quarantine_count": item.trajectory_quarantine_count,
                "full_session_quarantine_count": item.full_session_quarantine_count,
                "station_bins": item.station_bins,
                "valid_bin_90_count": item.valid_bin_90_count,
                "scheduled_issue_times": item.scheduled_issue_times,
                "formal_issue_times": item.formal_issue_times,
                "power_semantics_status": item.power_semantics_status,
                "processed_snapshot_sha256": item.processed_snapshot_sha256,
                "raw_unchanged": item.raw_unchanged,
            }
        )
    return {
        "schema_version": "evcf-jpl-development-preparation/v1",
        "status": result.status,
        "months": months,
        "protocol_sha256": result.protocol_sha256,
        "code_commit": result.code_commit,
        "holdout_accessed": result.holdout_accessed,
        "models_trained": False,
        "public_seasonal_release_created": False,
    }


def run_development_prepare_cli(
    *,
    authorized: bool,
    metadata_root: str | Path,
    raw_root: str | Path,
    interim_root: str | Path,
    processed_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    protocol_path: str | Path = _DEFAULT_PROTOCOL_PATH,
    runner: Callable[..., object] | None = None,
    stdout: TextIO = sys.stdout,
) -> int:
    """Prepare the fixed development months and print one safe JSON line."""

    if authorized is not True:
        print(DEVELOPMENT_PREPARATION_AUTHORIZATION_MESSAGE, file=stdout)
        return 2

    try:
        from evcf.data.acn_jpl_development_prep import (
            DevelopmentPreparationResult,
            prepare_jpl_development_data,
        )

        selected = prepare_jpl_development_data if runner is None else runner
        result = selected(
            authorized=True,
            metadata_root=metadata_root,
            raw_root=raw_root,
            interim_root=interim_root,
            processed_root=processed_root,
            code_commit=code_commit,
            repo_root=repo_root,
            protocol_path=protocol_path,
        )
        if type(result) is not DevelopmentPreparationResult:
            raise TypeError("closed development preparation result required")
        payload = _safe_payload(result)
    except Exception as exc:  # noqa: BLE001 - never expose path/identifier details
        reason = getattr(exc, "reason_code", None)
        payload = {
            "schema_version": "evcf-jpl-development-preparation/v1",
            "status": "FAIL",
            "months": [],
            "reason_code": reason if reason in _SAFE_REASON_CODES else "UNEXPECTED_ERROR",
            "holdout_accessed": False,
            "models_trained": False,
            "public_seasonal_release_created": False,
        }
        diagnostics = getattr(exc, "diagnostics", None)
        if reason == "INVALID_CONTAINER_METADATA_FAILED" and isinstance(diagnostics, dict):
            names = (
                "metadata_checked_session_count",
                "metadata_match_session_count",
                "metadata_anomaly_count",
            )
            if set(diagnostics) == set(names) and all(
                type(diagnostics[name]) is int and diagnostics[name] >= 0 for name in names
            ):
                payload["metadata_diagnostics"] = {name: diagnostics[name] for name in names}
        print(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            file=stdout,
        )
        return 1

    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        file=stdout,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare fixed JPL 2019 method-development months locally"
    )
    parser.add_argument(
        "--authorize-development-prepare",
        action="store_true",
        help="literal opt-in required before project import or filesystem access",
    )
    parser.add_argument("--metadata-root", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--protocol-path",
        type=Path,
        default=_DEFAULT_PROTOCOL_PATH,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.authorize_development_prepare and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return run_development_prepare_cli(
        authorized=args.authorize_development_prepare,
        metadata_root=args.metadata_root,
        raw_root=args.raw_root,
        interim_root=args.interim_root,
        processed_root=args.processed_root,
        code_commit=args.code_commit,
        repo_root=args.repo_root,
        protocol_path=args.protocol_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
