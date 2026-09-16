"""Monthly-chunk resumable acquisition for frozen R11-G0 Caltech scopes.

This is an acquisition-engineering repair only. It preserves the exact frozen
scientific overlap scope and the disconnect-filter-free materialization from v2,
but replaces broad pre-history year queries with one-month metadata queries.
ACN-Data has shown intermittent 5xx behavior on broad filtered requests.

The wrapper also emits privacy-safe progress diagnostics on failure so the next
attempt can resume from completed metadata/day chunks without blind reruns.
No forecasting model is imported or trained here.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import evcf.data.acn_caltech_r11_g0 as core
from evcf.data.acn_caltech_r11_g0 import AcquisitionMonthResult, R11G0Error
from evcf.data.acn_api import DEFAULT_TOKEN_ENV

import scripts.acquire_caltech_r11_g0_resumable_v2 as v2

_SCRIPT_PATH = "scripts/acquire_caltech_r11_g0_resumable_v3.py"
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_HISTORY_ANCHOR = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _verify_self(code_commit: str, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or _COMMIT.fullmatch(code_commit) is None:
        raise R11G0Error("IMPLEMENTATION_DRIFT")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if head.returncode != 0 or head.stdout.strip() != code_commit:
        raise R11G0Error("IMPLEMENTATION_DRIFT")
    for command in (
        ["git", "cat-file", "-e", f"{code_commit}:{_SCRIPT_PATH}"],
        ["git", "diff", "--quiet", code_commit, "--", _SCRIPT_PATH],
        ["git", "diff", "--cached", "--quiet", code_commit, "--", _SCRIPT_PATH],
    ):
        if subprocess.run(
            command,
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode != 0:
            raise R11G0Error("IMPLEMENTATION_DRIFT")


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return datetime(value.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(value.year, value.month + 1, 1, tzinfo=timezone.utc)


def monthly_history_intervals(
    boundary: datetime,
) -> tuple[tuple[str, datetime, datetime], ...]:
    """Exact monthly cover of [2000-01-01 UTC, boundary)."""
    edge = boundary.astimezone(timezone.utc)
    if edge <= _HISTORY_ANCHOR:
        raise R11G0Error("MONTH_CONFIG_INVALID")
    output: list[tuple[str, datetime, datetime]] = []
    current = _HISTORY_ANCHOR
    while current < edge:
        following = min(_next_month(current), edge)
        name = f"month_{current.year:04d}-{current.month:02d}"
        if following != _next_month(current):
            name += f"_to_{edge.strftime('%Y%m%dT%H%M%SZ')}"
        output.append((name, current, following))
        current = following
    return tuple(output)


def _count_pairs(path: Path, namespace: str) -> tuple[int, int, str | None]:
    folder = path / namespace
    if not folder.is_dir():
        return 0, 0, None
    data = sorted(folder.glob("*.jsonl"))
    manifests = sorted(folder.glob("*.jsonl.manifest.json"))
    return len(data), len(manifests), data[-1].name if data else None


def _progress(raw_root: Path) -> dict[str, Any]:
    metadata_data, metadata_manifest, metadata_last = _count_pairs(
        raw_root, "metadata_history"
    )
    months: list[dict[str, Any]] = []
    for month in core.CALTECH_MONTHS:
        root = raw_root / month
        carry_data, carry_manifest, carry_last = _count_pairs(root, "carry_ts")
        day_data, day_manifest, day_last = _count_pairs(root, "day_ts")
        raw, manifest, summary = core._raw_paths(raw_root, month)
        months.append(
            {
                "month": month,
                "final_raw": raw.is_file(),
                "final_manifest": manifest.is_file(),
                "summary": summary.is_file(),
                "carry_data": carry_data,
                "carry_manifest": carry_manifest,
                "carry_last": carry_last,
                "day_data": day_data,
                "day_manifest": day_manifest,
                "day_last": day_last,
            }
        )
    return {
        "metadata_history_data": metadata_data,
        "metadata_history_manifest": metadata_manifest,
        "metadata_history_last": metadata_last,
        "months": months,
    }


def _http_status(exc: BaseException) -> int | None:
    visited: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        response = getattr(current, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status
        next_value = getattr(current, "__cause__", None)
        if not isinstance(next_value, BaseException):
            next_value = getattr(current, "__context__", None)
        current = next_value if isinstance(next_value, BaseException) else None
    return None


def _safe_reason(exc: BaseException) -> str:
    value = getattr(exc, "reason_code", None)
    if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", value):
        return value
    return "UNEXPECTED_ERROR"


def acquire_resumable_v3(
    *,
    raw_root: Path,
    code_commit: str,
    repo_root: Path,
    protocol_path: Path,
) -> tuple[object, tuple[AcquisitionMonthResult, ...]]:
    _verify_self(code_commit, repo_root)
    original = v2.historical_metadata_intervals
    v2.historical_metadata_intervals = monthly_history_intervals
    try:
        return v2.acquire_resumable_v2(
            raw_root=raw_root,
            code_commit=code_commit,
            repo_root=repo_root,
            protocol_path=protocol_path,
        )
    finally:
        v2.historical_metadata_intervals = original


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Monthly-chunk resumable Caltech R11-G0 acquisition"
    )
    parser.add_argument("--authorize-r11-g0-acquisition", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--raw-root", type=Path, required=True)
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
    if not args.authorize_r11_g0_acquisition:
        print(
            json.dumps(
                {
                    "schema_version": "evcf-r11-g0-caltech-acquisition/v1.1",
                    "status": "FAIL",
                    "reason_code": "ACQUISITION_NOT_AUTHORIZED",
                    "models_trained": False,
                    "model_fit_count": 0,
                    "jpl_final_holdout_accessed": False,
                },
                sort_keys=True,
            )
        )
        return 2

    raw_root = args.raw_root
    try:
        protocol, months = acquire_resumable_v3(
            raw_root=raw_root,
            code_commit=args.code_commit,
            repo_root=args.repo_root.resolve(),
            protocol_path=args.protocol_path,
        )
        payload = {
            "schema_version": "evcf-r11-g0-caltech-acquisition/v1.1",
            "status": "COMPLETE",
            "site_id": protocol.site_id,
            "protocol_sha256": protocol.protocol_sha256,
            "code_commit": args.code_commit,
            "months": [item.public_dict() for item in months],
            "models_trained": False,
            "model_fit_count": 0,
            "jpl_final_holdout_accessed": False,
            "session_predictors_used": False,
            "disconnect_filter_sent_to_server": False,
            "history_chunking": "MONTHLY_FROM_2000_UTC",
            "resumable_materialization": True,
            "progress": _progress(raw_root),
        }
        code = 0
    except Exception as exc:  # noqa: BLE001
        payload = {
            "schema_version": "evcf-r11-g0-caltech-acquisition/v1.1",
            "status": "FAIL",
            "reason_code": _safe_reason(exc),
            "http_status": _http_status(exc),
            "models_trained": False,
            "model_fit_count": 0,
            "jpl_final_holdout_accessed": False,
            "session_predictors_used": False,
            "disconnect_filter_sent_to_server": False,
            "history_chunking": "MONTHLY_FROM_2000_UTC",
            "progress": _progress(raw_root),
        }
        code = 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
