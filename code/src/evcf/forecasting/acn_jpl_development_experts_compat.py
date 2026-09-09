"""Compatibility repair for canonically sorted development-expert label JSON.

The accepted development snapshots serialize JSON with ``sort_keys=True``.
JSON object key order is not semantic, so the expert reader must validate the
exact horizon-key set and then read values in the frozen horizon order.
No model, feature, target, split, or evaluation rule is changed here.
"""

from __future__ import annotations

import gzip
import json
import math
import subprocess
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
    """Load the frozen horizon labels without depending on JSON object key order."""

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


def install_label_loader_compat() -> None:
    """Install the narrow process-local label-order repair in the base controller."""

    _base._load_labels = _load_labels_order_insensitive


def verify_compat_implementation_commit(
    code_commit: str,
    *,
    repo_root: str | Path,
) -> None:
    """Bind the compatibility layer and v1.1 CLI to the exact checkout commit."""

    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise DevelopmentExpertError("IMPLEMENTATION_DRIFT")
    root = Path(repo_root).resolve(strict=True)
    for relative in COMPAT_IMPLEMENTATION_PATHS:
        current = root / relative
        if not current.is_file() or current.is_symlink():
            raise DevelopmentExpertError("IMPLEMENTATION_DRIFT")
        completed = subprocess.run(
            ["git", "show", f"{code_commit}:{relative}"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode != 0 or completed.stdout != current.read_bytes():
            raise DevelopmentExpertError("IMPLEMENTATION_DRIFT")


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
    install_label_loader_compat()
    return _base.run_development_experts(**kwargs)
