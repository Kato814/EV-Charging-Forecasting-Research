"""Explicitly authorized CLI for the frozen, offline JPL Gate 1 pilot."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

RUN_AUTHORIZATION_MESSAGE = "未授权JPL Gate 1正式运行；必须显式提供 --authorize-run。"
THREAD_CAP_ENV_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "BLIS_NUM_THREADS",
)

DEFAULT_CONFIG_PATH = Path("code/configs/acn_jpl_gate1_pilot_2019-05.yaml")
DEFAULT_PROCESSED_ROOT = Path("data/processed/acn/jpl/2019-05")
DEFAULT_INTERIM_ROOT = Path("data/interim/acn/jpl/2019-05")
DEFAULT_LOCAL_RUN_ROOT = Path("outputs/runs/jpl-2019-05-gate1-pilot-seed20260901")
DEFAULT_PUBLIC_ROOT = Path("outputs/gate1_pilot/jpl_2019-05")

_SUCCESS_CLASSIFICATIONS = frozenset(
    {
        "PASS_ACTIVE_SESSION",
        "PASS_SIMPLE_STATE_ONLY",
        "PASS_ACTIVE_SESSION_DROP_M4",
        "FAIL_DIRECTION",
    }
)
_REPRODUCIBILITY_STATUSES = frozenset({"REFERENCE_PUBLISHED", "BYTE_IDENTICAL_REPEAT"})


def _execution_failure_payload() -> dict[str, object]:
    return {
        "status": "EXECUTION_FAIL",
        "task_count": 0,
        "public_file_count": 0,
        "reproducibility_status": "NOT_VERIFIED",
    }


def _safe_outcome_payload(result: Any) -> dict[str, object]:
    status = getattr(result, "status", None)
    task_count = getattr(result, "task_count", None)
    public_file_count = getattr(result, "public_file_count", None)
    reproducibility = getattr(result, "reproducibility_status", None)
    if (
        status not in _SUCCESS_CLASSIFICATIONS
        or task_count != 40
        or public_file_count != 13
        or reproducibility not in _REPRODUCIBILITY_STATUSES
    ):
        return _execution_failure_payload()
    return {
        "status": status,
        "task_count": 40,
        "public_file_count": 13,
        "reproducibility_status": reproducibility,
    }


def _cap_native_threads() -> None:
    for name in THREAD_CAP_ENV_VARS:
        os.environ[name] = "1"


def _verify_cli_runtime_location() -> None:
    expected = (Path.cwd() / "scripts/run_jpl_gate1_pilot.py").resolve()
    if Path(__file__).resolve() != expected:
        raise RuntimeError("formal CLI must execute from its tracked repository root")


def _verify_pilot_import_origin() -> None:
    expected = (Path.cwd() / "code/src/evcf/forecasting/acn_jpl_gate1_pilot.py").resolve()
    spec = importlib.util.find_spec("evcf.forecasting.acn_jpl_gate1_pilot")
    origin = None if spec is None else spec.origin
    if not isinstance(origin, str) or Path(origin).resolve() != expected:
        raise RuntimeError("formal pilot import does not resolve to the tracked worktree")


def run_pilot_cli(
    *,
    authorized: bool,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    processed_root: str | Path = DEFAULT_PROCESSED_ROOT,
    interim_root: str | Path = DEFAULT_INTERIM_ROOT,
    local_run_root: str | Path = DEFAULT_LOCAL_RUN_ROOT,
    public_root: str | Path = DEFAULT_PUBLIC_ROOT,
    runner: Callable[..., Any] | None = None,
    stdout: TextIO = sys.stdout,
) -> int:
    """Run only after literal authorization and print four safe aggregate fields."""

    if authorized is not True:
        print(RUN_AUTHORIZATION_MESSAGE, file=stdout)
        return 2

    try:
        _cap_native_threads()
        if runner is None:
            _verify_cli_runtime_location()
            _verify_pilot_import_origin()
            from evcf.forecasting.acn_jpl_gate1_pilot import run_gate1_pilot

            selected_runner = run_gate1_pilot
        else:
            selected_runner = runner
        result = selected_runner(
            authorized=True,
            config_path=config_path,
            processed_root=processed_root,
            interim_root=interim_root,
            local_run_root=local_run_root,
            public_root=public_root,
        )
        payload = _safe_outcome_payload(result)
    except Exception:  # noqa: BLE001 - never echo paths, identifiers, or credentials
        payload = _execution_failure_payload()
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=stdout)
    return 0 if payload["status"] in _SUCCESS_CLASSIFICATIONS else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the frozen offline JPL 2019-05 Gate 1 pilot")
    parser.add_argument(
        "--authorize-run",
        action="store_true",
        help="literal opt-in required before any data access or model execution",
    )
    parser.add_argument("--config", dest="config_path", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    parser.add_argument("--interim-root", type=Path, default=DEFAULT_INTERIM_ROOT)
    parser.add_argument("--local-run-root", type=Path, default=DEFAULT_LOCAL_RUN_ROOT)
    parser.add_argument("--public-root", type=Path, default=DEFAULT_PUBLIC_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return run_pilot_cli(
        authorized=args.authorize_run,
        config_path=args.config_path,
        processed_root=args.processed_root,
        interim_root=args.interim_root,
        local_run_root=args.local_run_root,
        public_root=args.public_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
