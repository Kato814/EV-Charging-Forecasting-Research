"""Prepare the frozen R11-G0 Caltech pre-fit data/row manifest; train no model."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _safe_reason(exc: BaseException) -> str:
    value = getattr(exc, "reason_code", None)
    if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", value):
        return value
    return "UNEXPECTED_ERROR"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare fixed Caltech R11-G0 pre-fit evidence without model fitting"
    )
    parser.add_argument("--authorize-r11-g0-prefit", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--public-manifest-output", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument(
        "--protocol-path",
        type=Path,
        default=Path("code/configs/acn_caltech_r11_g0_prefit_2019.yaml"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not args.authorize_r11_g0_prefit:
        payload: dict[str, Any] = {
            "schema_version": "evcf-r11-g0-caltech-prefit/v1",
            "status": "FAIL",
            "reason_code": "PREFIT_NOT_AUTHORIZED",
            "models_trained": False,
            "jpl_final_holdout_accessed": False,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 2

    try:
        from evcf.data.acn_caltech_r11_g0 import prepare_caltech_r11_g0

        result = prepare_caltech_r11_g0(
            authorized=True,
            raw_root=args.raw_root,
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            code_commit=args.code_commit,
            repo_root=args.repo_root,
            protocol_path=args.protocol_path,
            public_manifest_output=args.public_manifest_output,
        )
        payload = result.public_dict()
        code = 0
    except Exception as exc:  # noqa: BLE001
        payload = {
            "schema_version": "evcf-r11-g0-caltech-prefit/v1",
            "status": "FAIL",
            "reason_code": _safe_reason(exc),
            "models_trained": False,
            "model_fit_count": 0,
            "jpl_final_holdout_accessed": False,
        }
        code = 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
