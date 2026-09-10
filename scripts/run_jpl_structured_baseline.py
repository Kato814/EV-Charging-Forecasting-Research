"""Authorized CLI for the frozen JPL structured S1 development baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

AUTHORIZATION_MESSAGE = (
    "未授权JPL结构化S1开发基线；必须显式提供 --authorize-structured-baseline。"
)
_SAFE_REASONS = frozenset(
    {
        "BASELINE_CACHE_INVALID",
        "CLEANED_SESSION_COUNT_INVALID",
        "CLEANED_SESSION_INVALID",
        "COMMON_ROW_IDENTITY_INVALID",
        "COMPONENT_LABEL_INVALID",
        "COMPONENT_RECONSTRUCTION_INVALID",
        "FEATURE_INVALID",
        "HOLDOUT_PATH_PRESENT",
        "IMPLEMENTATION_DRIFT",
        "METRIC_INVALID",
        "MODEL_FIT_FAILED",
        "MODEL_OUTPUT_INVALID",
        "MODEL_SELECTION_INVALID",
        "OUTPUT_TOPOLOGY_INVALID",
        "PROCESSED_SNAPSHOT_INVALID",
        "PROTOCOL_INVALID",
        "ROLLING_SPLIT_INVALID",
        "SOURCE_EXPERT_IDENTITY_INVALID",
        "STRUCTURED_RUN_NOT_AUTHORIZED",
        "TEMPORAL_LEAKAGE",
        "UNEXPECTED_ERROR",
    }
)


def run_cli(
    *,
    authorized: bool,
    interim_root: str | Path,
    processed_root: str | Path,
    baseline_private_root: str | Path,
    private_output_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    protocol_path: str | Path = "code/configs/acn_jpl_structured_baseline_2019.yaml",
    source_expert_protocol_path: str | Path = (
        "code/configs/acn_jpl_development_experts_2019.yaml"
    ),
    stdout: TextIO = sys.stdout,
) -> int:
    if authorized is not True:
        print(AUTHORIZATION_MESSAGE, file=stdout)
        return 2
    try:
        from evcf.forecasting.acn_jpl_structured_baseline import (
            run_structured_baseline,
        )

        result = run_structured_baseline(
            authorized=True,
            interim_root=interim_root,
            processed_root=processed_root,
            baseline_private_root=baseline_private_root,
            private_output_root=private_output_root,
            code_commit=code_commit,
            repo_root=repo_root,
            protocol_path=protocol_path,
            source_expert_protocol_path=source_expert_protocol_path,
        )
        payload = result.to_public_dict()
    except Exception as exc:  # noqa: BLE001 - private exception text is never published
        reason = getattr(exc, "reason_code", "UNEXPECTED_ERROR")
        if reason not in _SAFE_REASONS:
            reason = "UNEXPECTED_ERROR"
        payload = {
            "schema_version": "evcf-jpl-structured-s1-summary/v1",
            "status": "FAIL",
            "reason_code": reason,
            "holdout_accessed": False,
            "branch_specific_retuning": False,
            "prediction_clipping": False,
            "prediction_calibration": False,
            "hsmm_trained": False,
            "gate_trained": False,
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
            "Run the frozen development-only JPL structured S1 baseline "
            "(existing-session target + future-arrival target)."
        )
    )
    parser.add_argument("--authorize-structured-baseline", action="store_true")
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--baseline-private-root", type=Path, required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--protocol-path",
        type=Path,
        default=Path("code/configs/acn_jpl_structured_baseline_2019.yaml"),
    )
    parser.add_argument(
        "--source-expert-protocol-path",
        type=Path,
        default=Path("code/configs/acn_jpl_development_experts_2019.yaml"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.authorize_structured_baseline and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return run_cli(
        authorized=args.authorize_structured_baseline,
        interim_root=args.interim_root,
        processed_root=args.processed_root,
        baseline_private_root=args.baseline_private_root,
        private_output_root=args.private_output_root,
        code_commit=args.code_commit,
        repo_root=args.repo_root,
        protocol_path=args.protocol_path,
        source_expert_protocol_path=args.source_expert_protocol_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
