"""Resumable metadata-only entry point for the frozen JPL Gate 0 window.

The command intentionally has no time-series mode. Phase 2 must remain unreachable
after the Phase 1 count gate fails.
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
from evcf.data.acn_jpl_gate0 import jpl_acquisition_windows, run_daily_chunks

DEFAULT_RAW_ROOT = Path("data/raw/acn/jpl/gate0/2019-05")
MISSING_TOKEN_MESSAGE = (
    "ACN_API_TOKEN 未配置，请在本地环境变量或 PyCharm Run Configuration 中设置。"
)


def run_metadata(
    *,
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    environ: Mapping[str, str] = os.environ,
    client_factory: Callable[[], Any] | None = None,
    chunk_runner: Callable[..., dict[str, Any]] = run_daily_chunks,
    stdout: TextIO = sys.stdout,
) -> int:
    """Download/resume only the 38 metadata chunks and print aggregate progress."""

    token = environ.get(DEFAULT_TOKEN_ENV)
    if token is None or not token.strip():
        print(MISSING_TOKEN_MESSAGE, file=stdout)
        return 2

    client = client_factory() if client_factory is not None else ACNClient.from_env()
    root = Path(raw_root)
    progress = chunk_runner(
        client,
        root,
        jpl_acquisition_windows(),
        endpoint="metadata",
    )
    completed = progress.get("completed_days", [])
    pending = progress.get("pending_days", [])
    failed = progress.get("failed_days", [])
    complete = len(completed) == 38 and not pending and not failed
    public_progress = {
        "raw_root": str(root),
        "completed_days": len(completed),
        "pending_days": len(pending),
        "failed_days": len(failed),
        "last_success": progress.get("last_success"),
        "retry_count": progress.get("retry_count", 0),
        "status": "COMPLETE" if complete else "INCOMPLETE",
    }
    print(
        json.dumps(public_progress, ensure_ascii=False, sort_keys=True),
        file=stdout,
    )
    return 0 if complete else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Acquire the frozen JPL 2019-05 Gate 0 metadata window only"
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return run_metadata(raw_root=args.raw_root)


if __name__ == "__main__":
    raise SystemExit(main())
