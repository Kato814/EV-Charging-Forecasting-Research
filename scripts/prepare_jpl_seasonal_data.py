"""Local-only, explicitly authorized JPL seasonal preparation CLI."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import TextIO

PREPARATION_AUTHORIZATION_MESSAGE = (
    "未授权 JPL 季节月份数据准备；必须显式提供 --authorize-prepare。"
)
_SAFE_REASON_CODES = frozenset(
    {
        "ACQUISITION_INTEGRITY_FAILED",
        "ACQUISITION_QA_GATE_FAILED",
        "CLEANING_GATE_FAILED",
        "FEATURE_DIMENSION_INVALID",
        "FEATURE_TIER_INVALID",
        "IMPLEMENTATION_DRIFT",
        "INVALID_CONTAINER_PARTITION_INVALID",
        "INVALID_CONTAINER_METADATA_FAILED",
        "INVALID_CONTAINER_RATE_EXCEEDED",
        "ISSUE_SNAPSHOT_GATE_FAILED",
        "LOCAL_ARTIFACT_INVALID",
        "METADATA_SCOPE_INVALID",
        "MONTH_CONFIG_INVALID",
        "MONTH_RESULT_BINDING_INVALID",
        "OUTPUT_TOPOLOGY_INVALID",
        "POWER_SEMANTICS_GATE_FAILED",
        "PROTOCOL_SCHEMA_INVALID",
        "TRAJECTORY_QUARANTINE_INVALID",
        "TRAJECTORY_QUARANTINE_POLICY_FAIL",
        "FULL_SESSION_QUARANTINE_REQUIRED",
        "PUBLIC_EXISTING_STATE_INVALID",
        "PUBLIC_LAYOUT_INVALID",
        "PUBLIC_PRIVACY_INVALID",
        "PUBLIC_ROLLBACK_REJECTED",
        "PUBLIC_SCHEMA_INVALID",
        "PUBLIC_STAGING_INVALID",
        "RAW_RECORD_COUNT_INVALID",
        "VALID_BIN_90_GATE_FAILED",
    }
)


def run_prepare_cli(
    *,
    authorized: bool,
    metadata_root: object,
    raw_root: object,
    interim_root: object,
    processed_root: object,
    public_root: object,
    code_commit: str,
    repo_root: object = ".",
    protocol_path: object = "code/configs/acn_jpl_seasonal_prep_2019.yaml",
    runner: Callable[..., object] | None = None,
    stdout: TextIO = sys.stdout,
) -> int:
    """Prepare the fixed months and emit one secret-free aggregate JSON line."""

    if authorized is not True:
        print(PREPARATION_AUTHORIZATION_MESSAGE, file=stdout)
        return 2

    try:
        # Project imports are deliberately delayed until after literal opt-in.
        from evcf.data.acn_jpl_seasonal_prep import (
            SeasonalPreparationResult,
            prepare_jpl_seasonal_data,
        )

        selected_runner = prepare_jpl_seasonal_data if runner is None else runner
        result = selected_runner(
            authorized=True,
            metadata_root=metadata_root,
            raw_root=raw_root,
            interim_root=interim_root,
            processed_root=processed_root,
            public_root=public_root,
            code_commit=code_commit,
            repo_root=repo_root,
            protocol_path=protocol_path,
        )
        if type(result) is not SeasonalPreparationResult:
            raise TypeError("closed seasonal preparation result required")
        payload = {
            "status": result.status,
            "months": [
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
                }
                for item in result.months
            ],
        }
    except Exception as exc:  # noqa: BLE001 - never expose paths or producer errors
        reason = getattr(exc, "reason_code", None)
        payload = {
            "status": "FAIL",
            "months": [],
            "reason_code": reason if reason in _SAFE_REASON_CODES else "UNEXPECTED_ERROR",
        }
        if reason == "INVALID_CONTAINER_METADATA_FAILED":
            diagnostics = getattr(exc, "diagnostics", {})
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
        description="Prepare the fixed JPL 2019 seasonal replication months locally"
    )
    parser.add_argument(
        "--authorize-prepare",
        action="store_true",
        help="literal opt-in required before project import or filesystem access",
    )
    parser.add_argument("--metadata-root", default="data/raw/acn/jpl/metadata")
    parser.add_argument("--raw-root", default="data/raw/acn/jpl/seasonal")
    parser.add_argument("--interim-root", default="data/interim/acn/jpl/seasonal")
    parser.add_argument("--processed-root", default="data/processed/acn/jpl/seasonal")
    parser.add_argument("--public-root", default="outputs/seasonal_prep/jpl_2019")
    parser.add_argument("--code-commit", default="")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--protocol-path",
        default="code/configs/acn_jpl_seasonal_prep_2019.yaml",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.authorize_prepare and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return run_prepare_cli(
        authorized=args.authorize_prepare,
        metadata_root=args.metadata_root,
        raw_root=args.raw_root,
        interim_root=args.interim_root,
        processed_root=args.processed_root,
        public_root=args.public_root,
        code_commit=args.code_commit,
        repo_root=args.repo_root,
        protocol_path=args.protocol_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
