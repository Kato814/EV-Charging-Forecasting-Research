"""Authorized v1.1 CLI for fixed M2/M3 development-set OOS expert predictions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

AUTHORIZATION_MESSAGE = (
    "未授权JPL开发集M2/M3专家预测；必须显式提供 --authorize-development-experts。"
)
_SAFE_REASONS = frozenset(
    {
        "EXPERT_RUN_NOT_AUTHORIZED",
        "FEATURE_INVALID",
        "FEATURE_LABEL_ALIGNMENT_INVALID",
        "IMPLEMENTATION_DRIFT",
        "LABEL_INVALID",
        "METRIC_INVALID",
        "MODEL_FIT_FAILED",
        "MODEL_OUTPUT_INVALID",
        "MODEL_SELECTION_INVALID",
        "OUTPUT_TOPOLOGY_INVALID",
        "PROCESSED_SNAPSHOT_INVALID",
        "PROTOCOL_INVALID",
        "ROLLING_SPLIT_INVALID",
        "TEMPORAL_LEAKAGE",
        "COMMON_ROW_IDENTITY_INVALID",
        "UNEXPECTED_ERROR",
    }
)


def run_cli(
    *,
    authorized: bool,
    interim_root: str | Path,
    processed_root: str | Path,
    private_output_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    protocol_path: str | Path = "code/configs/acn_jpl_development_experts_2019.yaml",
    stdout: TextIO = sys.stdout,
) -> int:
    if authorized is not True:
        print(AUTHORIZATION_MESSAGE, file=stdout)
        return 2
    try:
        from evcf.forecasting.acn_jpl_development_experts_compat import (
            run_development_experts,
        )

        result = run_development_experts(
            authorized=True,
            interim_root=interim_root,
            processed_root=processed_root,
            private_output_root=private_output_root,
            code_commit=code_commit,
            repo_root=repo_root,
            protocol_path=protocol_path,
        )
        payload = result.to_public_dict()
    except Exception as exc:  # noqa: BLE001 - never expose private paths/IDs
        reason = getattr(exc, "reason_code", "UNEXPECTED_ERROR")
        if reason not in _SAFE_REASONS:
            reason = "UNEXPECTED_ERROR"
        payload = {
            "schema_version": "evcf-jpl-development-expert-oos-summary/v1",
            "status": "FAIL",
            "reason_code": reason,
            "holdout_accessed": False,
            "gate_trained": False,
            "expert_retuning": False,
        }
        print(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            file=stdout,
        )
        return 1
    print(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        file=stdout,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run fixed HGB M2/M3 OOS predictions on JPL development months (v1.1)"
    )
    parser.add_argument("--authorize-development-experts", action="store_true")
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--protocol-path",
        type=Path,
        default=Path("code/configs/acn_jpl_development_experts_2019.yaml"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.authorize_development_experts and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return run_cli(
        authorized=args.authorize_development_experts,
        interim_root=args.interim_root,
        processed_root=args.processed_root,
        private_output_root=args.private_output_root,
        code_commit=args.code_commit,
        repo_root=args.repo_root,
        protocol_path=args.protocol_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
