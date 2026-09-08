"""Fail-closed preparation controller for the four JPL 2019 development months.

This module reuses the reviewed single-month seasonal preparation path while
keeping the historical 02/08/11 three-month publication contract unchanged.
Only 2019-01/04/07/10 may be materialized here; final holdout months are never
installed by this controller.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .acn_jpl_development_months import (
    DEVELOPMENT_MONTHS,
    FINAL_HOLDOUT_MONTHS,
    installed_development_month_contracts,
)
from .acn_jpl_month_config import jpl_month_config
from .acn_jpl_seasonal_prep import (
    DEFAULT_SEASONAL_PROTOCOL_PATH,
    MonthPreparationResult,
    SeasonalPreparationError,
    load_seasonal_preparation_protocol,
    prepare_jpl_seasonal_month,
    verify_implementation_commit,
)

DEVELOPMENT_IMPLEMENTATION_PATHS = (
    "code/src/evcf/data/acn_jpl_development_months.py",
    "code/src/evcf/data/acn_jpl_development_prep.py",
    "scripts/prepare_jpl_development.py",
)


@dataclass(frozen=True, slots=True)
class DevelopmentPreparationResult:
    """Aggregate result for one fixed four-month development preparation run."""

    status: str
    months: tuple[MonthPreparationResult, ...]
    protocol_sha256: str
    code_commit: str
    holdout_accessed: bool = False

    def __post_init__(self) -> None:
        if self.status != "COMPLETE":
            raise SeasonalPreparationError("DEVELOPMENT_RESULT_INVALID")
        if tuple(item.month for item in self.months) != DEVELOPMENT_MONTHS:
            raise SeasonalPreparationError("DEVELOPMENT_MONTH_ORDER_INVALID")
        if any(item.code_commit != self.code_commit for item in self.months):
            raise SeasonalPreparationError("CODE_BINDING_INVALID")
        if any(item.config_sha256 != self.protocol_sha256 for item in self.months):
            raise SeasonalPreparationError("CONFIG_BINDING_INVALID")
        if any(
            item.trajectory_quarantine_count != 0
            or item.full_session_quarantine_count != 0
            or item.raw_unchanged is not True
            or item.formal_issue_times <= 0
            or item.station_bins <= 0
            or item.valid_bin_90_count <= 0
            for item in self.months
        ):
            raise SeasonalPreparationError("DEVELOPMENT_RESULT_INVALID")
        if self.holdout_accessed is not False:
            raise SeasonalPreparationError("HOLDOUT_ACCESS_INVALID")


def _verify_file_at_commit(root: Path, commit: str, relative: str) -> None:
    current = root / PurePosixPath(relative)
    if not current.is_file() or current.is_symlink():
        raise SeasonalPreparationError("IMPLEMENTATION_DRIFT")
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0 or completed.stdout != current.read_bytes():
        raise SeasonalPreparationError("IMPLEMENTATION_DRIFT")


def verify_development_implementation_commit(
    code_commit: str,
    *,
    repo_root: str | Path,
) -> None:
    """Bind both the reviewed seasonal implementation and development wrapper."""

    root = Path(repo_root).resolve(strict=True)
    verify_implementation_commit(code_commit, repo_root=root)
    for relative in DEVELOPMENT_IMPLEMENTATION_PATHS:
        _verify_file_at_commit(root, code_commit, relative)


def _validate_output_topology(
    *,
    raw_root: Path,
    interim_root: Path,
    processed_root: Path,
) -> None:
    raw = raw_root.resolve(strict=True)
    interim = interim_root.resolve(strict=False)
    processed = processed_root.resolve(strict=False)
    if not raw.is_dir() or raw.is_symlink():
        raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")
    roots = (raw, interim, processed)
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")
    if any(path.exists() and path.is_symlink() for path in (interim_root, processed_root)):
        raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")


def prepare_jpl_development_data(
    *,
    authorized: bool,
    metadata_root: str | Path,
    raw_root: str | Path,
    interim_root: str | Path,
    processed_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    protocol_path: str | Path = DEFAULT_SEASONAL_PROTOCOL_PATH,
    month_runner: Callable[..., MonthPreparationResult] | None = None,
    implementation_verifier: Callable[..., None] | None = None,
) -> DevelopmentPreparationResult:
    """Prepare 2019-01/04/07/10 in fixed order, without public seasonal release."""

    if authorized is not True:
        raise SeasonalPreparationError("PREPARATION_NOT_AUTHORIZED")
    metadata = Path(metadata_root).resolve(strict=True)
    raw_parent = Path(raw_root)
    interim_parent = Path(interim_root)
    processed_parent = Path(processed_root)
    if not metadata.is_dir() or metadata.is_symlink():
        raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")
    _validate_output_topology(
        raw_root=raw_parent,
        interim_root=interim_parent,
        processed_root=processed_parent,
    )
    verifier = (
        verify_development_implementation_commit
        if implementation_verifier is None
        else implementation_verifier
    )
    verifier(code_commit, repo_root=repo_root)
    protocol = load_seasonal_preparation_protocol(protocol_path)
    runner = prepare_jpl_seasonal_month if month_runner is None else month_runner

    results: list[MonthPreparationResult] = []
    with installed_development_month_contracts():
        for month in DEVELOPMENT_MONTHS:
            config = jpl_month_config(month)
            result = runner(
                authorized=True,
                config=config,
                metadata_root=metadata,
                raw_root=raw_parent / month,
                interim_root=interim_parent / month,
                processed_root=processed_parent / month,
                code_commit=code_commit,
                repo_root=repo_root,
                protocol_path=protocol_path,
            )
            if (
                type(result) is not MonthPreparationResult
                or result.month != month
                or result.config_sha256 != protocol.config_sha256
                or result.code_commit != code_commit
                or result.trajectory_quarantine_count != 0
                or result.full_session_quarantine_count != 0
                or result.raw_unchanged is not True
            ):
                raise SeasonalPreparationError("MONTH_RESULT_BINDING_INVALID")
            results.append(result)
        for month in FINAL_HOLDOUT_MONTHS:
            try:
                jpl_month_config(month)
            except ValueError:
                continue
            raise SeasonalPreparationError("HOLDOUT_ACCESS_INVALID")

    return DevelopmentPreparationResult(
        status="COMPLETE",
        months=tuple(results),
        protocol_sha256=protocol.config_sha256,
        code_commit=code_commit,
        holdout_accessed=False,
    )


__all__ = [
    "DEVELOPMENT_IMPLEMENTATION_PATHS",
    "DevelopmentPreparationResult",
    "prepare_jpl_development_data",
    "verify_development_implementation_commit",
]
