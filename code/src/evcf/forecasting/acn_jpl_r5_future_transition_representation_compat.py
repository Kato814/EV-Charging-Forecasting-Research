"""Pre-fit compatibility repair for the frozen R5 held-out geometry audit."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from evcf.forecasting import acn_jpl_r5_future_transition_representation as _base

R5Error = _base.R5Error
DailyPrediction = _base.DailyPrediction
MonthPrediction = _base.MonthPrediction
GLOBAL_SEED = _base.GLOBAL_SEED
MAX_AUDIT_PAIRS_PER_MONTH = _base.MAX_AUDIT_PAIRS_PER_MONTH
SCORE_EPS = _base.SCORE_EPS

GEOMETRY_AUDIT_SCALE_REPAIR_MERGE_COMMIT = (
    "431e1fe2fede50216d36ab89a5e61a835a29e737"
)
REPAIR_PATHS = (
    "docs/JPL_R5_GEOMETRY_AUDIT_SCALE_REPAIR_20260913.md",
    "code/src/evcf/forecasting/acn_jpl_r5_future_transition_representation_compat.py",
    "scripts/run_jpl_r5_future_transition_representation.py",
)


def _verify_repair_checkout(code_commit: str, repo_root: str | Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R5Error("IMPLEMENTATION_DRIFT")
    root = Path(repo_root).resolve(strict=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
        encoding="ascii",
        errors="ignore",
    )
    if head.returncode or head.stdout.strip() != code_commit:
        raise R5Error("IMPLEMENTATION_DRIFT")
    for relative in REPAIR_PATHS:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise R5Error("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode:
            raise R5Error("IMPLEMENTATION_DRIFT")
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            "--no-ext-diff",
            code_commit,
            "--",
            *REPAIR_PATHS,
        ],
        cwd=root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if diff.returncode:
        raise R5Error("IMPLEMENTATION_DRIFT")


def _standardize(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or not len(array) or not np.isfinite(array).all():
        raise R5Error("GEOMETRY_AUDIT_INVALID")
    return (array - np.mean(array)) / (np.std(array, ddof=0) + SCORE_EPS)


def standardized_same_refit_pair_distances(
    block: DailyPrediction,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    direct, ftar, future = _base._pair_distances(block)
    if not len(direct):
        return direct, ftar, future
    return _standardize(direct), _standardize(ftar), _standardize(future)


def geometry_audit(
    months: Sequence[MonthPrediction],
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    rng = np.random.Generator(np.random.PCG64(GLOBAL_SEED))
    month_rows: list[dict[str, Any]] = []
    pooled_direct: list[np.ndarray] = []
    pooled_ftar: list[np.ndarray] = []
    pooled_future: list[np.ndarray] = []
    for month in months:
        direct_parts: list[np.ndarray] = []
        ftar_parts: list[np.ndarray] = []
        future_parts: list[np.ndarray] = []
        for block in month.daily:
            direct, ftar, future = standardized_same_refit_pair_distances(block)
            if len(direct):
                direct_parts.append(direct)
                ftar_parts.append(ftar)
                future_parts.append(future)
        if not direct_parts:
            raise R5Error("GEOMETRY_AUDIT_INVALID")
        direct_all = np.concatenate(direct_parts)
        ftar_all = np.concatenate(ftar_parts)
        future_all = np.concatenate(future_parts)
        available = len(direct_all)
        if available > MAX_AUDIT_PAIRS_PER_MONTH:
            selected = rng.choice(
                available, size=MAX_AUDIT_PAIRS_PER_MONTH, replace=False
            )
            direct_all = direct_all[selected]
            ftar_all = ftar_all[selected]
            future_all = future_all[selected]
        row = {
            "month": month.month,
            "available_same_refit_pairs": available,
            "retained_pairs": len(direct_all),
            "Direct_spearman": _base._spearman(direct_all, future_all),
            "FTAR_spearman": _base._spearman(ftar_all, future_all),
            "daily_distance_standardization": True,
        }
        month_rows.append(row)
        pooled_direct.append(direct_all)
        pooled_ftar.append(ftar_all)
        pooled_future.append(future_all)
    direct = np.concatenate(pooled_direct)
    ftar = np.concatenate(pooled_ftar)
    future = np.concatenate(pooled_future)
    pooled = {
        "retained_pairs": len(direct),
        "Direct_spearman": _base._spearman(direct, future),
        "FTAR_spearman": _base._spearman(ftar, future),
        "daily_distance_standardization": True,
    }
    return pooled, tuple(month_rows)


def run_r5(**kwargs: Any) -> dict[str, Any]:
    code_commit = kwargs.get("code_commit")
    repo_root = kwargs.get("repo_root", ".")
    _verify_repair_checkout(code_commit, repo_root)
    original = _base.geometry_audit
    _base.geometry_audit = geometry_audit
    try:
        result = _base.run_r5(**kwargs)
    finally:
        _base.geometry_audit = original
    result["geometry_audit_scale_repair_merge_commit"] = (
        GEOMETRY_AUDIT_SCALE_REPAIR_MERGE_COMMIT
    )
    result["heldout_geometry"]["daily_distance_standardization"] = True
    return result
