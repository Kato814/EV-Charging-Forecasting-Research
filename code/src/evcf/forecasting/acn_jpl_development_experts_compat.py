"""Compatibility repairs for development-expert execution.

The accepted development snapshots serialize JSON with ``sort_keys=True``.
JSON object key order is not semantic, so the expert reader validates the exact
horizon-key set and reads values in the frozen horizon order.

Windows Git worktrees may also materialize tracked text as CRLF while Git blobs
remain LF. Implementation identity therefore uses exact HEAD plus Git's own
normalized diff semantics rather than raw working-tree byte equality. Real
tracked content changes still fail closed.

No model, feature, target, split, or evaluation rule is changed here.
"""

from __future__ import annotations

import gzip
import json
import math
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from evcf.forecasting import acn_jpl_development_experts as _base

DevelopmentExpertError = _base.DevelopmentExpertError
DevelopmentExpertProtocol = _base.DevelopmentExpertProtocol
MonthContract = _base.MonthContract
MonthData = _base.MonthData
HORIZONS_MINUTES = _base.HORIZONS_MINUTES

COMPAT_IMPLEMENTATION_PATHS = (
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "scripts/run_jpl_development_experts_v1_1.py",
)


def _load_labels_order_insensitive(
    processed: Path,
    row_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Load frozen horizon labels without depending on JSON object key order."""

    issue_times: list[int] = []
    rows: list[list[float]] = []
    expected_keys = {str(value) for value in HORIZONS_MINUTES}
    path = processed / "labels.jsonl.gz"
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for ordinal, line in enumerate(handle):
                if not line.strip():
                    raise DevelopmentExpertError("LABEL_INVALID")
                item = json.loads(line)
                if (
                    not isinstance(item, dict)
                    or set(item) != {"issue_index", "issue_time_utc_s", "labels"}
                ):
                    raise DevelopmentExpertError("LABEL_INVALID")
                issue_index = item["issue_index"]
                issue = item["issue_time_utc_s"]
                labels = item["labels"]
                if (
                    isinstance(issue_index, bool)
                    or not isinstance(issue_index, int)
                    or issue_index < 0
                    or isinstance(issue, bool)
                    or not isinstance(issue, int)
                    or not isinstance(labels, dict)
                    or len(labels) != len(expected_keys)
                    or set(labels) != expected_keys
                ):
                    raise DevelopmentExpertError("LABEL_INVALID")
                values: list[float] = []
                for horizon in HORIZONS_MINUTES:
                    value = labels[str(horizon)]
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise DevelopmentExpertError("LABEL_INVALID")
                    parsed = float(value)
                    if not math.isfinite(parsed) or parsed < 0:
                        raise DevelopmentExpertError("LABEL_INVALID")
                    values.append(parsed)
                if ordinal and issue <= issue_times[-1]:
                    raise DevelopmentExpertError("LABEL_INVALID")
                issue_times.append(issue)
                rows.append(values)
    except DevelopmentExpertError:
        raise
    except (OSError, UnicodeError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise DevelopmentExpertError("LABEL_INVALID") from exc

    times = np.asarray(issue_times, dtype=np.int64)
    labels_array = np.asarray(rows, dtype=np.float64)
    if times.shape != (row_count,) or labels_array.shape != (
        row_count,
        len(HORIZONS_MINUTES),
    ):
        raise DevelopmentExpertError("LABEL_INVALID")
    return times, labels_array


def _run_git(root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _verify_git_semantic_checkout(
    code_commit: str,
    *,
    repo_root: str | Path,
    paths: Sequence[str],
) -> None:
    """Verify exact checkout identity while allowing Git-normalized EOL materialization."""

    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise DevelopmentExpertError("IMPLEMENTATION_DRIFT")
    root = Path(repo_root).resolve(strict=True)
    head = _run_git(root, ("rev-parse", "HEAD"))
    if head.returncode != 0 or head.stdout.decode("ascii", errors="ignore").strip() != code_commit:
        raise DevelopmentExpertError("IMPLEMENTATION_DRIFT")

    for relative in paths:
        current = root / relative
        if not current.is_file() or current.is_symlink():
            raise DevelopmentExpertError("IMPLEMENTATION_DRIFT")
        exists = _run_git(root, ("cat-file", "-e", f"{code_commit}:{relative}"))
        if exists.returncode != 0:
            raise DevelopmentExpertError("IMPLEMENTATION_DRIFT")

    diff = _run_git(
        root,
        ("diff", "--quiet", "--no-ext-diff", code_commit, "--", *tuple(paths)),
    )
    if diff.returncode != 0:
        raise DevelopmentExpertError("IMPLEMENTATION_DRIFT")


def install_label_loader_compat() -> None:
    """Install the narrow process-local label-order repair in the base controller."""

    _base._load_labels = _load_labels_order_insensitive


def _verify_base_implementation_commit(
    code_commit: str,
    *,
    repo_root: str | Path,
) -> None:
    _verify_git_semantic_checkout(
        code_commit,
        repo_root=repo_root,
        paths=_base.IMPLEMENTATION_PATHS,
    )


def install_implementation_verifier_compat() -> None:
    """Replace only the process-local raw-byte verifier with Git semantic identity."""

    _base.verify_development_expert_implementation_commit = _verify_base_implementation_commit


def verify_compat_implementation_commit(
    code_commit: str,
    *,
    repo_root: str | Path,
) -> None:
    """Bind compatibility files to the exact checkout using Git-normalized semantics."""

    _verify_git_semantic_checkout(
        code_commit,
        repo_root=repo_root,
        paths=COMPAT_IMPLEMENTATION_PATHS,
    )


def load_development_expert_protocol(
    path: str | Path = _base.DEFAULT_PROTOCOL_PATH,
) -> DevelopmentExpertProtocol:
    return _base.load_development_expert_protocol(path)


def load_month_data(
    *,
    contract: MonthContract,
    interim_root: Path,
    processed_root: Path,
) -> MonthData:
    install_label_loader_compat()
    return _base.load_month_data(
        contract=contract,
        interim_root=interim_root,
        processed_root=processed_root,
    )


def run_development_experts(**kwargs: Any) -> _base.DevelopmentExpertRunResult:
    code_commit = kwargs.get("code_commit")
    repo_root = kwargs.get("repo_root")
    verify_compat_implementation_commit(code_commit, repo_root=repo_root)
    _verify_base_implementation_commit(code_commit, repo_root=repo_root)
    install_label_loader_compat()
    install_implementation_verifier_compat()
    return _base.run_development_experts(**kwargs)
