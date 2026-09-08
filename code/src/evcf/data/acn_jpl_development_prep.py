"""Fail-closed preparation controller for the four JPL 2019 development months.

This module reuses the reviewed single-month seasonal preparation path while
keeping the historical 02/08/11 protocol and three-month publication contract
unchanged. Only 2019-01/04/07/10 may be materialized here; final holdout months
are never installed by this controller.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .acn_jpl_development_months import (
    DEVELOPMENT_MONTHS,
    FINAL_HOLDOUT_MONTHS,
    installed_development_month_contracts,
)
from .acn_jpl_month_config import jpl_month_config
from .acn_jpl_seasonal_prep import (
    MonthPreparationResult,
    SeasonalPreparationError,
    SeasonalPreparationProtocol,
    prepare_jpl_seasonal_month,
    verify_implementation_commit,
)

DEFAULT_DEVELOPMENT_PROTOCOL_PATH = Path("code/configs/acn_jpl_development_prep_2019.yaml")
DEVELOPMENT_IMPLEMENTATION_PATHS = (
    "code/configs/acn_jpl_development_prep_2019.yaml",
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


def _exact_mapping(value: object, keys: tuple[str, ...], context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or tuple(value) != keys:
        raise SeasonalPreparationError("PROTOCOL_SCHEMA_INVALID")
    if any(type(key) is not str for key in value):
        raise SeasonalPreparationError("PROTOCOL_SCHEMA_INVALID")
    return value


def load_development_preparation_protocol(
    path: str | Path = DEFAULT_DEVELOPMENT_PROTOCOL_PATH,
) -> SeasonalPreparationProtocol:
    """Load the closed 01/04/07/10 protocol without reusing the 02/08/11 identity."""

    import yaml

    class UniqueLoader(yaml.SafeLoader):
        pass

    def construct_mapping(
        loader: yaml.SafeLoader,
        node: yaml.nodes.MappingNode,
        deep: bool = False,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in loader.construct_pairs(node, deep=deep):
            if type(key) is not str or key in result:
                raise SeasonalPreparationError("PROTOCOL_SCHEMA_INVALID")
            result[key] = value
        return result

    UniqueLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping,
    )
    source = Path(path)
    try:
        raw = source.read_bytes()
        parsed = yaml.load(raw.decode("utf-8"), Loader=UniqueLoader)
    except SeasonalPreparationError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise SeasonalPreparationError("PROTOCOL_SCHEMA_INVALID") from exc

    root = _exact_mapping(
        parsed,
        (
            "schema_version",
            "months",
            "cleaning",
            "aggregation",
            "acquisition_gate",
            "trajectory_quarantine",
            "missing_trajectory",
            "snapshots",
            "features",
            "publication",
            "final_holdout",
        ),
        "PROTOCOL",
    )
    cleaning = _exact_mapping(
        root["cleaning"],
        (
            "sampling_derivation",
            "locf_mode_multiplier",
            "locf_cap_seconds",
            "boundary_sensitivity_seconds",
        ),
        "CLEANING",
    )
    aggregation = _exact_mapping(
        root["aggregation"],
        (
            "bin_minutes",
            "grid_policy",
            "coverage_thresholds",
            "main_valid_bin_field",
            "minimum_valid_bin_rate",
            "main_active_threshold_a",
            "comparison_active_threshold_a",
        ),
        "AGGREGATION",
    )
    acquisition_gate = _exact_mapping(
        root["acquisition_gate"],
        ("charging_current_invalid_rate_max", "pilot_signal_invalid_rate_max"),
        "ACQUISITION_GATE",
    )
    quarantine = _exact_mapping(
        root["trajectory_quarantine"],
        (
            "policy",
            "expected_counts",
            "detector",
            "preserve_raw",
            "preserve_manifest",
            "preserve_timestamps",
            "sort_repair",
            "timestamp_shift_seconds",
            "interpolation",
            "full_session_quarantine_allowed",
        ),
        "TRAJECTORY_QUARANTINE",
    )
    quarantine_counts = _exact_mapping(
        quarantine["expected_counts"],
        DEVELOPMENT_MONTHS,
        "TRAJECTORY_QUARANTINE_COUNTS",
    )
    missing = _exact_mapping(
        root["missing_trajectory"],
        (
            "preserve_invalid_container_structure",
            "verify_official_structural_metadata",
            "branchwise_availability",
            "invalid_metadata_action",
            "coverage_denominator_includes_structural_placeholders",
            "whole_current_unobservable_overlap_rejects_target",
            "pilot_only_missing_rejects_current_target",
            "impute_future_labels",
            "coverage_rescale_current",
            "final_energy_reconstruction",
            "offline_qa_reasons_are_features",
            "active_count_semantics",
        ),
        "MISSING_TRAJECTORY",
    )
    snapshots = _exact_mapping(
        root["snapshots"],
        ("lookback_minutes", "horizons_minutes", "issue_step_minutes", "tiers"),
        "SNAPSHOTS",
    )
    features = _exact_mapping(
        root["features"],
        ("raw_dimensions", "encoded_dimensions"),
        "FEATURES",
    )
    publication = _exact_mapping(
        root["publication"],
        (
            "local_interim_processed_only",
            "public_seasonal_release_created",
            "aggregate_status_stdout_only",
        ),
        "PUBLICATION",
    )
    holdout = _exact_mapping(
        root["final_holdout"],
        ("months", "access_allowed"),
        "FINAL_HOLDOUT",
    )

    valid = bool(
        root["schema_version"] == "acn-jpl-development-preparation-protocol/v1"
        and root["months"] == list(DEVELOPMENT_MONTHS)
        and cleaning
        == {
            "sampling_derivation": "mode_of_positive_raw_timestamp_differences",
            "locf_mode_multiplier": 3,
            "locf_cap_seconds": 60,
            "boundary_sensitivity_seconds": 60,
        }
        and aggregation
        == {
            "bin_minutes": 15,
            "grid_policy": "continuous_physical_utc",
            "coverage_thresholds": [0.8, 0.9, 0.95],
            "main_valid_bin_field": "valid_bin_90",
            "minimum_valid_bin_rate": 0.8,
            "main_active_threshold_a": 0.1,
            "comparison_active_threshold_a": 1.0,
        }
        and acquisition_gate
        == {
            "charging_current_invalid_rate_max": 0.1,
            "pilot_signal_invalid_rate_max": 0.1,
        }
        and quarantine_counts == {month: 0 for month in DEVELOPMENT_MONTHS}
        and quarantine["policy"] == "reject_any_candidate"
        and quarantine["detector"]
        == "synchronized_current_pilot_raw_order_utc_nonmonotonic"
        and quarantine["preserve_raw"] is True
        and quarantine["preserve_manifest"] is True
        and quarantine["preserve_timestamps"] is True
        and quarantine["sort_repair"] is False
        and quarantine["timestamp_shift_seconds"] == 0
        and quarantine["interpolation"] is False
        and quarantine["full_session_quarantine_allowed"] is False
        and missing
        == {
            "preserve_invalid_container_structure": True,
            "verify_official_structural_metadata": True,
            "branchwise_availability": True,
            "invalid_metadata_action": "stop_month_preparation",
            "coverage_denominator_includes_structural_placeholders": True,
            "whole_current_unobservable_overlap_rejects_target": True,
            "pilot_only_missing_rejects_current_target": False,
            "impute_future_labels": False,
            "coverage_rescale_current": False,
            "final_energy_reconstruction": False,
            "offline_qa_reasons_are_features": False,
            "active_count_semantics": "observed_active_lower_bound_unknown_is_not_inactive",
        }
        and snapshots
        == {
            "lookback_minutes": 1440,
            "horizons_minutes": [15, 30, 60, 120, 240],
            "issue_step_minutes": 15,
            "tiers": ["M1", "M2", "M3"],
        }
        and features
        == {
            "raw_dimensions": [195, 201, 311],
            "encoded_dimensions": [195, 204, 391],
        }
        and publication
        == {
            "local_interim_processed_only": True,
            "public_seasonal_release_created": False,
            "aggregate_status_stdout_only": True,
        }
        and holdout == {"months": list(FINAL_HOLDOUT_MONTHS), "access_allowed": False}
    )
    if not valid:
        raise SeasonalPreparationError("PROTOCOL_SCHEMA_INVALID")

    return SeasonalPreparationProtocol(
        config_sha256=hashlib.sha256(raw).hexdigest(),
        locf_mode_multiplier=3,
        locf_cap_seconds=60,
        boundary_sensitivity_seconds=60,
        coverage_thresholds=(0.8, 0.9, 0.95),
        minimum_valid_bin_rate=0.8,
        main_active_threshold_a=0.1,
        comparison_active_threshold_a=1.0,
        lookback_minutes=1440,
        horizons_minutes=(15, 30, 60, 120, 240),
        issue_step_minutes=15,
        trajectory_quarantine_month="NONE",
        trajectory_quarantine_expected_counts=(0, 0, 0, 0),  # type: ignore[arg-type]
        trajectory_quarantine_backward_seconds=0,
        trajectory_quarantine_preserves_raw=True,
        trajectory_quarantine_preserves_connected=True,
        preserve_invalid_container_structure=True,
        enforce_known_incomplete_current=True,
    )


@contextmanager
def _installed_development_protocol_loader():  # type: ignore[no-untyped-def]
    import evcf.data.acn_jpl_seasonal_prep as seasonal_prep

    original = seasonal_prep.load_seasonal_preparation_protocol
    seasonal_prep.load_seasonal_preparation_protocol = load_development_preparation_protocol
    try:
        yield
    finally:
        seasonal_prep.load_seasonal_preparation_protocol = original


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
    protocol_path: str | Path = DEFAULT_DEVELOPMENT_PROTOCOL_PATH,
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
    protocol = load_development_preparation_protocol(protocol_path)
    runner = prepare_jpl_seasonal_month if month_runner is None else month_runner

    results: list[MonthPreparationResult] = []
    with installed_development_month_contracts(), _installed_development_protocol_loader():
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
    "DEFAULT_DEVELOPMENT_PROTOCOL_PATH",
    "DEVELOPMENT_IMPLEMENTATION_PATHS",
    "DevelopmentPreparationResult",
    "load_development_preparation_protocol",
    "prepare_jpl_development_data",
    "verify_development_implementation_commit",
]
