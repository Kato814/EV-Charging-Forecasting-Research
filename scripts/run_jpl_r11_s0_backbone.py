"""CLI for the frozen JPL/ACN R11-S0 station-level backbone screen."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

import evcf.forecasting.acn_jpl_r11_s0_backbone as controller
from evcf.forecasting.acn_jpl_r11_s0_backbone import R11S0Error


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-r11-s0-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "fit_count": None,
        "holdout_accessed": False,
        "session_predictors_used": False,
        "hyperparameter_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "model_ensemble": False,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _portable_verify_r11_s0_implementation_commit(
    code_commit: str, *, repo_root: str | Path
) -> None:
    """Verify frozen Git content without raw working-tree byte assumptions.

    Git checkout filters may normalize text bytes without changing tracked
    content. The formal identity check therefore requires exact HEAD identity
    plus a clean Git diff for every authoritative runtime path.
    """

    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R11S0Error("IMPLEMENTATION_DRIFT")
    root = Path(repo_root).resolve(strict=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if head.returncode != 0 or head.stdout.strip() != code_commit:
        raise R11S0Error("IMPLEMENTATION_DRIFT")
    for relative in controller.IMPLEMENTATION_PATHS:
        path = root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R11S0Error("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode != 0:
            raise R11S0Error("IMPLEMENTATION_DRIFT")
        clean = subprocess.run(
            ["git", "diff", "--quiet", "--no-ext-diff", code_commit, "--", relative],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if clean.returncode != 0:
            raise R11S0Error("IMPLEMENTATION_DRIFT")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--authorize-r11-s0", action="store_true")
    args = parser.parse_args()
    if not args.authorize_r11_s0:
        print(json.dumps(_failure("R11_S0_NOT_AUTHORIZED"), sort_keys=True))
        return 2
    try:
        controller.verify_r11_s0_implementation_commit = (
            _portable_verify_r11_s0_implementation_commit
        )
        result = controller.run_r11_s0(
            repo_root=args.repo_root,
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            code_commit=args.code_commit,
            progress=_progress,
        )
        public = result.to_public_dict()
        public.update(
            {
                "code_commit": args.code_commit,
                "r11_protocol_sha256": _sha256(
                    args.repo_root
                    / "docs/JPL_R11_S0_STATION_LEVEL_DEEP_BACKBONE_SCREENING_PROTOCOL_20260914.md"
                ),
                "source_expert_protocol_sha256": _sha256(
                    args.repo_root / "code/configs/acn_jpl_development_experts_2019.yaml"
                ),
                "model_fit_attempted": True,
                "hyperparameter_search": False,
                "prediction_clipping": False,
                "prediction_calibration": False,
                "model_ensemble": False,
                "development_data_written": False,
            }
        )
    except R11S0Error as exc:
        print(json.dumps(_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, TypeError, ValueError, RuntimeError, FloatingPointError):
        print(json.dumps(_failure("UNEXPECTED_ERROR"), sort_keys=True))
        return 2
    print(json.dumps(public, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
