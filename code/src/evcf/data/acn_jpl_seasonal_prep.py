"""Fail-closed preparation and aggregate-only publication for seasonal JPL months.

Every public JSON document has a closed schema, canonical serialization, and
an independent disk loader. Private identifiers, raw records, and filesystem
paths never cross the :class:`MonthPreparationResult` boundary.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .acn_jpl_month_config import (
    SEASONAL_MONTHS,
    JPLMonthConfig,
    is_canonical_jpl_month_config,
    jpl_month_config,
    verify_complete_metadata_scope,
)
from .acn_jpl_seasonal_reporting import (
    SeasonalReportingError,
    build_month_summary_row,
    render_report_markdown,
    render_summary_csv,
    validate_report_markdown,
    validate_summary_csv,
)

MONTH_PAYLOAD_NAMES = (
    "acquisition_summary.json",
    "cleaning_qa.json",
    "cleaning_sensitivity.json",
    "boundary_current_audit.json",
    "power_semantics_audit.json",
    "station_15min_qa.json",
    "issue_snapshot_qa.json",
    "leakage_audit.json",
    "data_snapshot_manifest.json",
    "run_manifest.json",
)
MONTH_RELEASE_NAMES = (*MONTH_PAYLOAD_NAMES, "SHA256SUMS")
ROOT_PAYLOAD_NAMES = (
    "seasonal_prep_summary.csv",
    "seasonal_snapshot_manifest.json",
    "seasonal_prep_report.md",
)
ROOT_RELEASE_NAMES = (*ROOT_PAYLOAD_NAMES, "SHA256SUMS")

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_ABSOLUTE_PATH = re.compile(
    r"(?:\b[A-Za-z]:[\\/]|(?:^|[\s\"'])/(?:home|Users|mnt|tmp|var)/|\\\\[^\s\\]+\\)",
    re.IGNORECASE,
)
_STATUSES = frozenset({"PASS", "CONDITIONAL_PASS"})
_MONTH_STATUSES = frozenset(
    {"PASS", "CONDITIONAL_PASS", "PASS_WITH_TRAJECTORY_QUARANTINE"}
)
_POWER_STATUSES = frozenset({"CURRENT_PROXY_ONLY", "KW_RECONSTRUCTION_CANDIDATE"})
_RAW_DIMENSIONS = (195, 201, 311)
_ENCODED_DIMENSIONS = (195, 204, 391)
_TIERS = ("M1", "M2", "M3")
_HORIZONS_MINUTES = (15, 30, 60, 120, 240)
_SNAPSHOT_MISSING_RATE_NAMES = (
    "M1_history",
    "M2_station_current",
    "M2_pilot_sum",
    "M2_pilot_mean",
    "M3_current_current",
    "M3_elapsed_charging_time_proxy",
    "M3_recent_current_mean",
    "M3_recent_current_peak",
    "M3_current_pilot",
    "M3_cumulative_current_ah",
    "M3_known_requested_departure",
    "M3_known_requested_energy",
)
DEFAULT_SEASONAL_PROTOCOL_PATH = Path("code/configs/acn_jpl_seasonal_prep_2019.yaml")
IMPLEMENTATION_PATHS = (
    "environment-gate1-pilot.yml",
    "pyproject.toml",
    "code/configs/acn_jpl_seasonal_prep_2019.yaml",
    "code/src/evcf/__init__.py",
    "code/src/evcf/data/__init__.py",
    "code/src/evcf/data/acn_coverage.py",
    "code/src/evcf/data/acn_api.py",
    "code/src/evcf/data/acn_audit.py",
    "code/src/evcf/data/acn_jpl_gate0.py",
    "code/src/evcf/data/acn_jpl_month_config.py",
    "code/src/evcf/data/acn_jpl_seasonal_acquisition.py",
    "code/src/evcf/data/acn_jpl_full_month_ts.py",
    "code/src/evcf/data/acn_jpl_full_month_qa.py",
    "code/src/evcf/data/acn_jpl_official_reference.py",
    "code/src/evcf/data/acn_jpl_preparation.py",
    "code/src/evcf/data/acn_jpl_cleaning.py",
    "code/src/evcf/data/acn_jpl_gate1_prep.py",
    "code/src/evcf/data/acn_jpl_power_semantics.py",
    "code/src/evcf/data/acn_jpl_15min.py",
    "code/src/evcf/data/acn_jpl_issue_snapshots.py",
    "code/src/evcf/data/acn_jpl_trajectory_quarantine.py",
    "code/src/evcf/data/acn_jpl_seasonal_reporting.py",
    "code/src/evcf/data/acn_jpl_seasonal_prep.py",
    "code/src/evcf/forecasting/__init__.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_data.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "scripts/prepare_jpl_seasonal_data.py",
    "scripts/acquire_jpl_seasonal.py",
)


class SeasonalPreparationError(RuntimeError):
    """A path-free, static reason emitted by a fail-closed preparation gate."""

    def __init__(self, reason_code: str) -> None:
        if (
            not isinstance(reason_code, str)
            or re.fullmatch(r"[A-Z][A-Z0-9_]+", reason_code) is None
        ):
            reason_code = "UNEXPECTED_ERROR"
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class SeasonalPreparationProtocol:
    """Hash-bound fixed preparation choices with no mutable containers."""

    config_sha256: str
    locf_mode_multiplier: int
    locf_cap_seconds: int
    boundary_sensitivity_seconds: int
    coverage_thresholds: tuple[float, float, float]
    minimum_valid_bin_rate: float
    main_active_threshold_a: float
    comparison_active_threshold_a: float
    lookback_minutes: int
    horizons_minutes: tuple[int, ...]
    issue_step_minutes: int
    trajectory_quarantine_month: str
    trajectory_quarantine_expected_counts: tuple[int, int, int]
    trajectory_quarantine_backward_seconds: int
    trajectory_quarantine_preserves_raw: bool
    trajectory_quarantine_preserves_connected: bool


def load_seasonal_preparation_protocol(
    path: str | Path = DEFAULT_SEASONAL_PROTOCOL_PATH,
) -> SeasonalPreparationProtocol:
    """Load the one closed YAML protocol and reject duplicate keys."""

    import yaml

    class UniqueLoader(yaml.SafeLoader):
        pass

    def construct_mapping(
        loader: yaml.SafeLoader, node: yaml.nodes.MappingNode, deep: bool = False
    ) -> dict[str, Any]:
        pairs = loader.construct_pairs(node, deep=deep)
        result: dict[str, Any] = {}
        for key, value in pairs:
            if not isinstance(key, str) or key in result:
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
    root = _exact(
        parsed,
        (
            "schema_version",
            "months",
            "cleaning",
            "aggregation",
            "acquisition_gate",
            "trajectory_quarantine",
            "snapshots",
            "features",
            "publication",
        ),
        "PROTOCOL",
    )
    cleaning = _exact(
        root["cleaning"],
        (
            "sampling_derivation",
            "locf_mode_multiplier",
            "locf_cap_seconds",
            "boundary_sensitivity_seconds",
        ),
        "PROTOCOL_CLEANING",
    )
    aggregation = _exact(
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
        "PROTOCOL_AGGREGATION",
    )
    acquisition_gate = _exact(
        root["acquisition_gate"],
        (
            "charging_current_invalid_rate_max",
            "pilot_signal_invalid_rate_max",
        ),
        "PROTOCOL_ACQUISITION_GATE",
    )
    quarantine = _exact(
        root["trajectory_quarantine"],
        (
            "approved_month",
            "expected_counts",
            "detector",
            "expected_nonmonotonic_pairs_per_series",
            "expected_backward_seconds",
            "preserve_raw",
            "preserve_manifest",
            "preserve_timestamps",
            "sort_repair",
            "timestamp_shift_seconds",
            "interpolation",
            "preserve_structural_metadata_when_bounds_valid",
            "preserve_connected_state_when_bounds_valid",
            "whole_current_pilot_trajectory_unobservable",
            "coverage_denominator_includes_quarantined",
            "invalid_metadata_action",
            "month_status",
            "seasonal_status_ceiling",
        ),
        "PROTOCOL_TRAJECTORY_QUARANTINE",
    )
    quarantine_counts = _exact(
        quarantine["expected_counts"],
        SEASONAL_MONTHS,
        "PROTOCOL_TRAJECTORY_QUARANTINE_COUNTS",
    )
    snapshots = _exact(
        root["snapshots"],
        (
            "lookback_minutes",
            "horizons_minutes",
            "issue_step_minutes",
            "tiers",
        ),
        "PROTOCOL_SNAPSHOTS",
    )
    features = _exact(
        root["features"],
        ("raw_dimensions", "encoded_dimensions"),
        "PROTOCOL_FEATURES",
    )
    publication = _exact(
        root["publication"],
        ("aggregate_only", "exact_file_count"),
        "PROTOCOL_PUBLICATION",
    )
    numeric_contract = (
        root["schema_version"] == "acn-jpl-seasonal-preparation-protocol/v1"
        and root["months"] == list(SEASONAL_MONTHS)
        and cleaning["sampling_derivation"] == "mode_of_positive_raw_timestamp_differences"
        and cleaning["locf_mode_multiplier"] == 3
        and cleaning["locf_cap_seconds"] == 60
        and cleaning["boundary_sensitivity_seconds"] == 60
        and aggregation["bin_minutes"] == 15
        and aggregation["grid_policy"] == "continuous_physical_utc"
        and aggregation["coverage_thresholds"] == [0.8, 0.9, 0.95]
        and aggregation["main_valid_bin_field"] == "valid_bin_90"
        and aggregation["minimum_valid_bin_rate"] == 0.8
        and aggregation["main_active_threshold_a"] == 0.1
        and aggregation["comparison_active_threshold_a"] == 1.0
        and acquisition_gate["charging_current_invalid_rate_max"] == 0.1
        and acquisition_gate["pilot_signal_invalid_rate_max"] == 0.1
        and quarantine["approved_month"] == "2019-11"
        and quarantine_counts == {"2019-02": 0, "2019-08": 0, "2019-11": 1}
        and quarantine["detector"]
        == "synchronized_current_pilot_raw_order_utc_nonmonotonic"
        and quarantine["expected_nonmonotonic_pairs_per_series"] == 1
        and quarantine["expected_backward_seconds"] == 3596
        and quarantine["preserve_raw"] is True
        and quarantine["preserve_manifest"] is True
        and quarantine["preserve_timestamps"] is True
        and quarantine["sort_repair"] is False
        and quarantine["timestamp_shift_seconds"] == 0
        and quarantine["interpolation"] is False
        and quarantine["preserve_structural_metadata_when_bounds_valid"] is True
        and quarantine["preserve_connected_state_when_bounds_valid"] is True
        and quarantine["whole_current_pilot_trajectory_unobservable"] is True
        and quarantine["coverage_denominator_includes_quarantined"] is True
        and quarantine["invalid_metadata_action"] == "full_session_quarantine"
        and quarantine["month_status"] == "PASS_WITH_TRAJECTORY_QUARANTINE"
        and quarantine["seasonal_status_ceiling"] == "CONDITIONAL_PASS"
        and snapshots["lookback_minutes"] == 1440
        and snapshots["horizons_minutes"] == [15, 30, 60, 120, 240]
        and snapshots["issue_step_minutes"] == 15
        and snapshots["tiers"] == list(_TIERS)
        and features["raw_dimensions"] == list(_RAW_DIMENSIONS)
        and features["encoded_dimensions"] == list(_ENCODED_DIMENSIONS)
        and publication == {"aggregate_only": True, "exact_file_count": 37}
    )
    if not numeric_contract:
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
        trajectory_quarantine_month="2019-11",
        trajectory_quarantine_expected_counts=(0, 0, 1),
        trajectory_quarantine_backward_seconds=3596,
        trajectory_quarantine_preserves_raw=True,
        trajectory_quarantine_preserves_connected=True,
    )


def verify_implementation_commit(
    code_commit: str,
    *,
    repo_root: str | Path,
) -> None:
    """Require every implementation/config byte to equal an explicit commit."""

    commit = _commit(code_commit)
    root = Path(repo_root).resolve(strict=True)
    for relative in IMPLEMENTATION_PATHS:
        current = root / PurePosixPath(relative)
        if not current.is_file() or _is_reparse(current):
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


@dataclass(frozen=True, slots=True)
class ClosedArtifact:
    """One immutable canonical public payload and its content digest."""

    name: str
    content: bytes = field(repr=False)
    sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.name not in MONTH_PAYLOAD_NAMES or type(self.content) is not bytes:
            raise SeasonalPreparationError("PUBLIC_SCHEMA_INVALID")
        object.__setattr__(self, "sha256", hashlib.sha256(self.content).hexdigest())


@dataclass(frozen=True, slots=True)
class MonthPreparationResult:
    """Closed aggregate evidence for one successfully prepared seasonal month."""

    month: str
    status: str
    official_total: int
    local_session_count: int
    carry_in_count: int
    sessions_processed: int
    cleaned_session_count: int
    invalid_skipped_session_count: int
    trajectory_quarantine_count: int
    full_session_quarantine_count: int
    station_bins: int
    valid_bin_90_count: int
    scheduled_issue_times: int
    formal_issue_times: int
    power_semantics_status: str
    grid_policy: str
    raw_dimensions: tuple[int, int, int]
    encoded_dimensions: tuple[int, int, int]
    config_sha256: str
    code_commit: str
    metadata_source_inventory_sha256: str
    metadata_record_inventory_sha256: str
    raw_inventory_sha256: str
    processed_snapshot_sha256: str
    raw_unchanged: bool
    artifacts: tuple[ClosedArtifact, ...] = field(repr=False)

    @property
    def valid_bin_90_rate(self) -> float:
        return self.valid_bin_90_count / self.station_bins

    def __post_init__(self) -> None:
        _validate_month_result(self)


@dataclass(frozen=True, slots=True)
class SeasonalPreparationResult:
    """Fixed-order aggregate evidence for a complete three-month preparation."""

    status: str
    months: tuple[MonthPreparationResult, ...]
    config_sha256: str
    code_commit: str

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise SeasonalPreparationError("SEASONAL_RESULT_INVALID")
        if tuple(item.month for item in self.months) != SEASONAL_MONTHS:
            raise SeasonalPreparationError("MONTH_ORDER_INVALID")
        if any(item.config_sha256 != self.config_sha256 for item in self.months):
            raise SeasonalPreparationError("CONFIG_BINDING_INVALID")
        if any(item.code_commit != self.code_commit for item in self.months):
            raise SeasonalPreparationError("CODE_BINDING_INVALID")
        expected_status = (
            "PASS" if all(item.status == "PASS" for item in self.months) else "CONDITIONAL_PASS"
        )
        if self.status != expected_status:
            raise SeasonalPreparationError("SEASONAL_RESULT_INVALID")


def expected_seasonal_release_paths() -> tuple[str, ...]:
    """Return the one fixed, normalized 37-file seasonal public allowlist."""

    paths = (
        tuple(f"{month}/{name}" for month in SEASONAL_MONTHS for name in MONTH_RELEASE_NAMES)
        + ROOT_RELEASE_NAMES
    )
    if len(paths) != len(set(paths)) or len(paths) != 37:
        raise AssertionError("seasonal release allowlist must contain exactly 37 unique paths")
    return paths


def _json_bytes(payload: object) -> bytes:
    try:
        rendered = json.dumps(
            _plain_json_value(payload),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise SeasonalPreparationError("PUBLIC_SCHEMA_INVALID") from exc
    return (rendered + "\n").encode("utf-8")


def _reject_constant(_value: str) -> None:
    raise SeasonalPreparationError("PUBLIC_JSON_NONFINITE")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SeasonalPreparationError("PUBLIC_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _decode_json_bytes(content: bytes) -> dict[str, Any]:
    if type(content) is not bytes:
        raise SeasonalPreparationError("PUBLIC_SCHEMA_INVALID")
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except SeasonalPreparationError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SeasonalPreparationError("PUBLIC_JSON_INVALID") from exc
    if type(value) is not dict:
        raise SeasonalPreparationError("PUBLIC_SCHEMA_INVALID")
    if _json_bytes(value) != content:
        raise SeasonalPreparationError("PUBLIC_JSON_NOT_CANONICAL")
    return value


def _exact(value: object, names: Sequence[str], context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(names):
        raise SeasonalPreparationError(f"{context}_SCHEMA_INVALID")
    return value


def _integer(value: object, context: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise SeasonalPreparationError(f"{context}_INVALID")
    return value


def _number(value: object, context: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise SeasonalPreparationError(f"{context}_INVALID")
    return float(value)


def _optional_number(value: object, context: str) -> float | None:
    return None if value is None else _number(value, context)


def _digest(value: object, context: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SeasonalPreparationError(f"{context}_INVALID")
    return value


def _commit(value: object) -> str:
    if not isinstance(value, str) or _COMMIT.fullmatch(value) is None:
        raise SeasonalPreparationError("CODE_COMMIT_INVALID")
    return value


def _same_number(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _require_ratio(
    value: object,
    *,
    numerator: int,
    denominator: int,
    context: str,
) -> None:
    if denominator == 0:
        if value is not None:
            raise SeasonalPreparationError(f"{context}_INVALID")
        return
    if not _same_number(_number(value, context), numerator / denominator):
        raise SeasonalPreparationError(f"{context}_INVALID")


def _validate_public_value(value: object, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for raw_key, nested in value.items():
            if not isinstance(raw_key, str):
                raise SeasonalPreparationError("PUBLIC_PRIVACY_INVALID")
            normalized = "".join(
                character for character in raw_key.casefold() if character.isalnum()
            )
            if normalized == "m4generated":
                if path or nested is not False:
                    raise SeasonalPreparationError("PUBLIC_TIER_SCOPE_INVALID")
            elif "m4" in normalized:
                raise SeasonalPreparationError("PUBLIC_TIER_SCOPE_INVALID")
            forbidden = (
                "sessionid",
                "objectid",
                "userid",
                "email",
                "hostname",
                "username",
                "credential",
                "password",
                "apikey",
                "prediction",
                "modelweight",
            )
            if any(token in normalized for token in forbidden) and nested not in (
                False,
                0,
                None,
            ):
                raise SeasonalPreparationError("PUBLIC_PRIVACY_INVALID")
            if "token" in normalized and nested not in (False, 0, None):
                raise SeasonalPreparationError("PUBLIC_PRIVACY_INVALID")
            if "path" in normalized and nested not in (False, 0, None):
                raise SeasonalPreparationError("PUBLIC_PRIVACY_INVALID")
            _validate_public_value(nested, path=(*path, raw_key))
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _validate_public_value(nested, path=path)
        return
    if isinstance(value, str):
        lowered = value.casefold()
        if (
            _ABSOLUTE_PATH.search(value)
            or "m4" in lowered
            or "bearer " in lowered
            or "api_key=" in lowered
        ):
            raise SeasonalPreparationError("PUBLIC_PRIVACY_INVALID")
        return
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    raise SeasonalPreparationError("PUBLIC_SCHEMA_INVALID")


def _validate_acquisition(
    config: JPLMonthConfig, document: Mapping[str, Any]
) -> tuple[int, int, int, int, int]:
    value = _exact(
        document,
        (
            "schema_version",
            "month",
            "status",
            "official_total",
            "local_session_count",
            "carry_in_count",
            "combined_session_count",
            "trajectory_quarantine_count",
            "trajectory_quarantine_rate",
            "full_session_quarantine_count",
            "metadata_scope",
            "official_probe",
            "chunk_integrity",
            "linkage",
            "valid_daily_chunks",
            "expected_daily_chunks",
            "metadata_source_inventory_sha256",
            "metadata_record_inventory_sha256",
            "official_reference_sha256",
            "raw_file_count",
            "raw_inventory_sha256",
            "raw_inventory_before_sha256",
            "raw_inventory_after_sha256",
            "partial_file_count",
            "integrity",
        ),
        "ACQUISITION",
    )
    integrity = _exact(
        value["integrity"],
        (
            "scope_verified",
            "official_reference_verified",
            "raw_snapshot_valid",
            "raw_unchanged",
            "linkage_exact",
            "partial_files_absent",
        ),
        "ACQUISITION_INTEGRITY",
    )
    local = _integer(value["local_session_count"], "LOCAL_SESSION_COUNT")
    carry = _integer(value["carry_in_count"], "CARRY_IN_COUNT")
    combined = _integer(value["combined_session_count"], "COMBINED_SESSION_COUNT")
    trajectory = _integer(
        value["trajectory_quarantine_count"],
        "TRAJECTORY_QUARANTINE_COUNT",
    )
    full = _integer(
        value["full_session_quarantine_count"],
        "FULL_SESSION_QUARANTINE_COUNT",
    )
    metadata_scope = _exact(
        value["metadata_scope"],
        (
            "local_calendar_session_count",
            "utc_calendar_session_count",
            "left_boundary_count",
            "right_boundary_count",
            "carry_in_count",
        ),
        "METADATA_SCOPE",
    )
    official_probe = _exact(
        value["official_probe"],
        ("request_count", "timeseries", "total_matches_local", "reference_valid"),
        "OFFICIAL_PROBE",
    )
    chunks = _exact(
        value["chunk_integrity"],
        (
            "daily_expected",
            "daily_data_files_present",
            "daily_manifests_present",
            "daily_manifest_contracts_valid",
            "daily_sha256_verified",
            "daily_json_valid",
            "daily_record_manifest_matches",
            "daily_record_remote_matches",
            "daily_valid",
            "carry_expected",
            "carry_completed",
            "carry_manifest_sha_json_valid",
        ),
        "CHUNK_INTEGRITY",
    )
    linkage = _exact(
        value["linkage"],
        (
            "daily_record_count",
            "daily_unique_object_count",
            "daily_unique_session_count",
            "daily_unique_pair_count",
            "combined_record_count",
            "combined_unique_object_count",
            "combined_unique_session_count",
            "combined_unique_pair_count",
            "matched_metadata_pairs",
            "missing_metadata_pairs",
            "orphan_timeseries_pairs",
        ),
        "LINKAGE",
    )
    source_digest = _digest(value["raw_inventory_sha256"], "RAW_INVENTORY")
    if (
        value["schema_version"] != "acn-jpl-seasonal-acquisition-summary/v1"
        or value["month"] != config.month
        or value["status"] != "COMPLETE"
        or _integer(value["official_total"], "OFFICIAL_TOTAL") != local
        or combined != local + carry
        or trajectory != (1 if config.month == "2019-11" else 0)
        or full != 0
        or metadata_scope
        != {
            "local_calendar_session_count": local,
            "utc_calendar_session_count": _integer(
                metadata_scope["utc_calendar_session_count"], "UTC_SESSION_COUNT"
            ),
            "left_boundary_count": _integer(
                metadata_scope["left_boundary_count"], "LEFT_BOUNDARY_COUNT"
            ),
            "right_boundary_count": _integer(
                metadata_scope["right_boundary_count"], "RIGHT_BOUNDARY_COUNT"
            ),
            "carry_in_count": carry,
        }
        or official_probe
        != {
            "request_count": 1,
            "timeseries": False,
            "total_matches_local": True,
            "reference_valid": True,
        }
        or any(
            _integer(chunks[name], "DAILY_CHUNK_COUNT") != config.day_count
            for name in (
                "daily_expected",
                "daily_data_files_present",
                "daily_manifests_present",
                "daily_manifest_contracts_valid",
                "daily_sha256_verified",
                "daily_json_valid",
                "daily_record_manifest_matches",
                "daily_record_remote_matches",
                "daily_valid",
            )
        )
        or _integer(chunks["carry_expected"], "CARRY_EXPECTED") != carry
        or _integer(chunks["carry_completed"], "CARRY_COMPLETED") != carry
        or chunks["carry_manifest_sha_json_valid"] is not True
        or _integer(linkage["daily_record_count"], "DAILY_RECORD_COUNT") != local
        or _integer(linkage["daily_unique_object_count"], "DAILY_UNIQUE_OBJECT") != local
        or _integer(linkage["daily_unique_session_count"], "DAILY_UNIQUE_SESSION") != local
        or _integer(linkage["daily_unique_pair_count"], "DAILY_UNIQUE_PAIR") != local
        or _integer(linkage["combined_record_count"], "COMBINED_RECORD") != combined
        or _integer(linkage["combined_unique_object_count"], "COMBINED_UNIQUE_OBJECT") != combined
        or _integer(linkage["combined_unique_session_count"], "COMBINED_UNIQUE_SESSION") != combined
        or _integer(linkage["combined_unique_pair_count"], "COMBINED_UNIQUE_PAIR") != combined
        or _integer(linkage["matched_metadata_pairs"], "MATCHED_METADATA") != combined
        or _integer(linkage["missing_metadata_pairs"], "MISSING_METADATA") != 0
        or _integer(linkage["orphan_timeseries_pairs"], "ORPHAN_TIMESERIES") != 0
        or _integer(value["valid_daily_chunks"], "VALID_DAILY_CHUNKS") != config.day_count
        or _integer(value["expected_daily_chunks"], "EXPECTED_DAILY_CHUNKS") != config.day_count
        or _integer(value["raw_file_count"], "RAW_FILE_COUNT", positive=True)
        != 2 * (config.day_count + carry)
        or _digest(value["raw_inventory_before_sha256"], "RAW_INVENTORY_BEFORE") != source_digest
        or _digest(value["raw_inventory_after_sha256"], "RAW_INVENTORY_AFTER") != source_digest
        or _integer(value["partial_file_count"], "PARTIAL_FILE_COUNT") != 0
        or any(item is not True for item in integrity.values())
    ):
        raise SeasonalPreparationError("ACQUISITION_INTEGRITY_FAILED")
    _require_ratio(
        value["trajectory_quarantine_rate"],
        numerator=trajectory,
        denominator=combined,
        context="TRAJECTORY_QUARANTINE_RATE",
    )
    for name in (
        "metadata_source_inventory_sha256",
        "metadata_record_inventory_sha256",
        "official_reference_sha256",
        "raw_inventory_sha256",
    ):
        _digest(value[name], name.upper())
    return local, carry, combined, trajectory, full


def _validate_cleaning(
    config: JPLMonthConfig,
    document: Mapping[str, Any],
    *,
    combined_count: int,
    trajectory_quarantine_count: int,
    full_session_quarantine_count: int,
) -> tuple[int, int]:
    value = _exact(
        document,
        (
            "schema_version",
            "month",
            "status",
            "sessions_processed",
            "expected_sessions",
            "cleaned_session_count",
            "invalid_skipped_session_count",
            "trajectory_quarantine",
            "analysis_window",
            "sampling",
            "invalid_containers",
            "duplicate_conflict",
            "series",
            "user_inputs",
            "retrospective_done_time",
            "raw_modified",
        ),
        "CLEANING",
    )
    window = _exact(
        value["analysis_window"],
        (
            "timezone",
            "local_start_inclusive",
            "local_end_exclusive",
            "utc_start_inclusive",
            "utc_end_exclusive",
        ),
        "ANALYSIS_WINDOW",
    )
    expected_window = {
        "timezone": config.timezone_name,
        "local_start_inclusive": config.local_start.isoformat(),
        "local_end_exclusive": config.local_end.isoformat(),
        "utc_start_inclusive": config.utc_start.isoformat(),
        "utc_end_exclusive": config.utc_end.isoformat(),
    }
    sampling = _exact(
        value["sampling"],
        (
            "derivation",
            "current_mode_seconds",
            "pilot_mode_seconds",
            "current_hold_seconds",
            "pilot_hold_seconds",
            "mode_multiplier",
            "cap_seconds",
        ),
        "SAMPLING",
    )
    current_mode = _integer(sampling["current_mode_seconds"], "CURRENT_MODE", positive=True)
    pilot_mode = _integer(sampling["pilot_mode_seconds"], "PILOT_MODE", positive=True)
    current_hold = _integer(sampling["current_hold_seconds"], "CURRENT_HOLD", positive=True)
    pilot_hold = _integer(sampling["pilot_hold_seconds"], "PILOT_HOLD", positive=True)
    attempted = _integer(value["sessions_processed"], "SESSIONS_PROCESSED")
    cleaned_count = _integer(value["cleaned_session_count"], "CLEANED_SESSION_COUNT")
    skipped_count = _integer(
        value["invalid_skipped_session_count"], "INVALID_SKIPPED_SESSION_COUNT"
    )
    quarantine = _exact(
        value["trajectory_quarantine"],
        (
            "denominator_sessions",
            "trajectory_quarantine_count",
            "trajectory_quarantine_rate",
            "full_session_quarantine_count",
            "full_session_quarantine_rate",
            "synchronized_utc_nonmonotonic_sessions",
            "raw_trajectory_anomalies_retained",
            "raw_manifest_modified",
            "raw_timestamps_modified",
            "sort_repair_applied",
            "timestamp_shift_seconds",
            "interpolation_applied",
            "whole_current_pilot_trajectory_unobservable",
            "coverage_denominator_includes_quarantined",
            "structural_metadata_retained_count",
            "connected_state_retained_count",
            "raw_field_coverage",
            "analysis_field_coverage",
        ),
        "TRAJECTORY_QUARANTINE",
    )
    if (
        value["schema_version"] != "acn-jpl-seasonal-preparation-cleaning-qa/v1"
        or value["month"] != config.month
        or value["status"] != "PASS"
        or attempted != combined_count
        or _integer(value["expected_sessions"], "EXPECTED_SESSIONS") != combined_count
        or cleaned_count + skipped_count != combined_count
        or dict(window) != expected_window
        or sampling["derivation"] != "mode_of_positive_raw_timestamp_differences"
        or sampling["mode_multiplier"] != 3
        or sampling["cap_seconds"] != 60
        or current_hold != min(3 * current_mode, 60)
        or pilot_hold != min(3 * pilot_mode, 60)
        or value["raw_modified"] is not False
    ):
        raise SeasonalPreparationError("CLEANING_GATE_FAILED")

    if (
        _integer(quarantine["denominator_sessions"], "QUARANTINE_DENOMINATOR")
        != combined_count
        or _integer(
            quarantine["trajectory_quarantine_count"],
            "TRAJECTORY_QUARANTINE_COUNT",
        )
        != trajectory_quarantine_count
        or _integer(
            quarantine["full_session_quarantine_count"],
            "FULL_SESSION_QUARANTINE_COUNT",
        )
        != full_session_quarantine_count
        or _integer(
            quarantine["synchronized_utc_nonmonotonic_sessions"],
            "SYNCHRONIZED_NONMONOTONIC_SESSIONS",
        )
        != trajectory_quarantine_count + full_session_quarantine_count
        or _integer(
            quarantine["structural_metadata_retained_count"],
            "STRUCTURAL_METADATA_RETAINED_COUNT",
        )
        != trajectory_quarantine_count
        or _integer(
            quarantine["connected_state_retained_count"],
            "CONNECTED_STATE_RETAINED_COUNT",
        )
        != trajectory_quarantine_count
        or quarantine["raw_trajectory_anomalies_retained"] is not True
        or quarantine["raw_manifest_modified"] is not False
        or quarantine["raw_timestamps_modified"] is not False
        or quarantine["sort_repair_applied"] is not False
        or _integer(quarantine["timestamp_shift_seconds"], "TIMESTAMP_SHIFT_SECONDS") != 0
        or quarantine["interpolation_applied"] is not False
        or quarantine["whole_current_pilot_trajectory_unobservable"] is not True
        or quarantine["coverage_denominator_includes_quarantined"] is not True
    ):
        raise SeasonalPreparationError("TRAJECTORY_QUARANTINE_INVALID")
    _require_ratio(
        quarantine["trajectory_quarantine_rate"],
        numerator=trajectory_quarantine_count,
        denominator=combined_count,
        context="TRAJECTORY_QUARANTINE_RATE",
    )
    _require_ratio(
        quarantine["full_session_quarantine_rate"],
        numerator=full_session_quarantine_count,
        denominator=combined_count,
        context="FULL_SESSION_QUARANTINE_RATE",
    )
    coverage_counts: dict[str, dict[str, int]] = {}
    for coverage_name in ("raw_field_coverage", "analysis_field_coverage"):
        coverage = _exact(
            quarantine[coverage_name],
            ("current", "pilot"),
            "QUARANTINE_FIELD_COVERAGE",
        )
        coverage_counts[coverage_name] = {}
        for field_name in ("current", "pilot"):
            item = _exact(
                coverage[field_name],
                ("count", "denominator", "rate"),
                "QUARANTINE_FIELD_COVERAGE",
            )
            count = _integer(item["count"], "QUARANTINE_FIELD_COVERAGE_COUNT")
            if (
                count > combined_count
                or _integer(
                    item["denominator"],
                    "QUARANTINE_FIELD_COVERAGE_DENOMINATOR",
                )
                != combined_count
            ):
                raise SeasonalPreparationError("TRAJECTORY_QUARANTINE_INVALID")
            _require_ratio(
                item["rate"],
                numerator=count,
                denominator=combined_count,
                context="QUARANTINE_FIELD_COVERAGE_RATE",
            )
            coverage_counts[coverage_name][field_name] = count
    for field_name in ("current", "pilot"):
        if coverage_counts["analysis_field_coverage"][field_name] != (
            coverage_counts["raw_field_coverage"][field_name]
            - trajectory_quarantine_count
            - full_session_quarantine_count
        ):
            raise SeasonalPreparationError("TRAJECTORY_QUARANTINE_INVALID")

    invalid = _exact(
        value["invalid_containers"],
        ("denominator", "charging_current", "pilot_signal"),
        "INVALID_CONTAINER",
    )
    if (
        _integer(invalid["denominator"], "INVALID_CONTAINER_DENOMINATOR", positive=True)
        != combined_count
    ):
        raise SeasonalPreparationError("INVALID_CONTAINER_RATE_EXCEEDED")
    invalid_counts: dict[str, int] = {}
    for field_name in ("charging_current", "pilot_signal"):
        item = _exact(
            invalid[field_name],
            ("count", "rate", "limit", "status"),
            "INVALID_CONTAINER",
        )
        count = _integer(item["count"], "INVALID_CONTAINER_COUNT")
        invalid_counts[field_name] = count
        rate = _number(item["rate"], "INVALID_CONTAINER_RATE")
        limit = _number(item["limit"], "INVALID_CONTAINER_LIMIT")
        if (
            count > combined_count
            or not _same_number(rate, count / combined_count)
            or not _same_number(limit, 0.10)
            or rate > 0.10
            or item["status"] != "PASS"
        ):
            raise SeasonalPreparationError("INVALID_CONTAINER_RATE_EXCEEDED")
    if (
        not max(invalid_counts.values())
        <= skipped_count
        <= min(combined_count, sum(invalid_counts.values()))
        or coverage_counts["raw_field_coverage"]["current"]
        != combined_count - invalid_counts["charging_current"]
        or coverage_counts["raw_field_coverage"]["pilot"]
        != combined_count - invalid_counts["pilot_signal"]
    ):
        raise SeasonalPreparationError("INVALID_CONTAINER_PARTITION_INVALID")

    series = _exact(value["series"], ("current", "pilot"), "CLEANING_SERIES")
    for name, invalid_name in (
        ("current", "charging_current"),
        ("pilot", "pilot_signal"),
    ):
        section = _exact(
            series[name],
            (
                "raw_samples",
                "usable_samples",
                "retained_samples",
                "retained_sample_rate",
                "invalid_timestamps",
                "invalid_values",
                "exact_duplicate_extras",
                "conflicting_timestamps",
                "conflict_affected_sessions",
                "nonmonotonic_pairs",
                "nonmonotonic_sessions",
                "bounded_observation_coverage",
                "bounded_value_hours",
            ),
            "CLEANING_SERIES",
        )
        raw_samples = _integer(section["raw_samples"], "RAW_SAMPLES")
        usable_samples = _integer(section["usable_samples"], "USABLE_SAMPLES")
        retained_samples = _integer(section["retained_samples"], "RETAINED_SAMPLES")
        if not raw_samples >= usable_samples >= retained_samples >= 0:
            raise SeasonalPreparationError("CLEANING_GATE_FAILED")
        _require_ratio(
            section["retained_sample_rate"],
            numerator=retained_samples,
            denominator=raw_samples,
            context="RETAINED_SAMPLE_RATE",
        )
        for count_name in (
            "invalid_timestamps",
            "invalid_values",
            "exact_duplicate_extras",
            "conflicting_timestamps",
            "conflict_affected_sessions",
        ):
            _integer(section[count_name], "CLEANING_SERIES_COUNT")
        if (
            _integer(section["nonmonotonic_pairs"], "NONMONOTONIC_PAIRS")
            != trajectory_quarantine_count
            or _integer(section["nonmonotonic_sessions"], "NONMONOTONIC_SESSIONS")
            != trajectory_quarantine_count
            or _number(section["bounded_observation_coverage"], "BOUNDED_COVERAGE") < 0
            or _number(section["bounded_observation_coverage"], "BOUNDED_COVERAGE") > 1
            or (
                name == "current"
                and _number(section["bounded_value_hours"], "BOUNDED_VALUE_HOURS") < 0
            )
        ):
            raise SeasonalPreparationError("CLEANING_GATE_FAILED")

    duplicate = _exact(
        value["duplicate_conflict"],
        (
            "exact_duplicate_policy",
            "conflict_main_policy",
            "conflict_sensitivity_policy",
            "current_conflicting_timestamps",
            "pilot_conflicting_timestamps",
        ),
        "DUPLICATE_CONFLICT",
    )
    if (
        duplicate["exact_duplicate_policy"] != "retain_first_remove_extra"
        or duplicate["conflict_main_policy"] != "mark_timestamp_missing"
        or duplicate["conflict_sensitivity_policy"] != "last_write_wins"
    ):
        raise SeasonalPreparationError("CLEANING_GATE_FAILED")
    _integer(duplicate["current_conflicting_timestamps"], "CURRENT_CONFLICTS")
    _integer(duplicate["pilot_conflicting_timestamps"], "PILOT_CONFLICTS")

    user_inputs = _exact(
        value["user_inputs"],
        (
            "raw_revision_count",
            "sanitized_revision_count",
            "unparseable_modified_count",
            "issue_time_truncation_ready",
        ),
        "USER_INPUTS",
    )
    raw_revisions = _integer(user_inputs["raw_revision_count"], "RAW_USER_INPUTS")
    sanitized = _integer(user_inputs["sanitized_revision_count"], "SANITIZED_USER_INPUTS")
    if (
        sanitized > raw_revisions
        or sanitized
        + _integer(user_inputs["unparseable_modified_count"], "UNPARSEABLE_USER_INPUTS")
        != raw_revisions
        or user_inputs["unparseable_modified_count"] != 0
        or user_inputs["issue_time_truncation_ready"] is not True
    ):
        raise SeasonalPreparationError("USER_INPUT_GATE_FAILED")
    retrospective = _exact(
        value["retrospective_done_time"],
        (
            "present_count",
            "parsed_count",
            "unparseable_count",
            "online_feature_allowed",
            "original_value_retained_locally",
        ),
        "RETROSPECTIVE_DONE_TIME",
    )
    present = _integer(retrospective["present_count"], "DONE_PRESENT")
    parsed = _integer(retrospective["parsed_count"], "DONE_PARSED")
    unparseable = _integer(retrospective["unparseable_count"], "DONE_UNPARSEABLE")
    if (
        present > cleaned_count
        or parsed + unparseable != present
        or retrospective["online_feature_allowed"] is not False
        or retrospective["original_value_retained_locally"] is not True
    ):
        raise SeasonalPreparationError("CLEANING_GATE_FAILED")
    return current_hold, pilot_hold


def _validate_sensitivity(
    config: JPLMonthConfig,
    document: Mapping[str, Any],
    *,
    current_hold: int,
    pilot_hold: int,
) -> None:
    value = _exact(
        document,
        (
            "schema_version",
            "month",
            "status",
            "main_hold_seconds",
            "hold_thresholds_seconds",
            "hold_thresholds",
            "last_write_wins",
            "boundary_plus_minus_60_seconds",
            "boundary_sensitivity_seconds",
            "last_write_wins_compared",
        ),
        "CLEANING_SENSITIVITY",
    )
    main_hold = _exact(value["main_hold_seconds"], ("current", "pilot"), "MAIN_HOLD")
    thresholds = _exact(
        value["hold_thresholds_seconds"],
        ("current", "pilot"),
        "HOLD_THRESHOLDS",
    )
    if (
        value["schema_version"] != "acn-jpl-seasonal-preparation-cleaning-sensitivity/v1"
        or value["month"] != config.month
        or value["status"] != "PASS"
        or main_hold != {"current": current_hold, "pilot": pilot_hold}
        or value["boundary_sensitivity_seconds"] != 60
        or value["last_write_wins_compared"] is not True
    ):
        raise SeasonalPreparationError("CLEANING_SENSITIVITY_FAILED")
    for name, hold in (("current", current_hold), ("pilot", pilot_hold)):
        items = thresholds[name]
        if (
            not isinstance(items, list)
            or any(type(item) is not int or item <= 0 for item in items)
            or items != sorted(set(items))
            or hold not in items
            or 60 not in items
        ):
            raise SeasonalPreparationError("CLEANING_SENSITIVITY_FAILED")
    hold_reports = _exact(value["hold_thresholds"], ("current", "pilot"), "HOLD_REPORTS")
    lww = _exact(value["last_write_wins"], ("current", "pilot"), "LAST_WRITE_WINS")
    boundary = _exact(
        value["boundary_plus_minus_60_seconds"],
        ("current", "pilot"),
        "BOUNDARY_SENSITIVITY",
    )
    for name in ("current", "pilot"):
        expected_keys = tuple(str(item) for item in thresholds[name])
        reports = _exact(hold_reports[name], expected_keys, "HOLD_REPORTS")
        previous_observed = -1
        expected_eligible: int | None = None
        for threshold in expected_keys:
            observed, eligible = _validate_integral_report(reports[threshold], comparison=False)
            if observed < previous_observed or (
                expected_eligible is not None and eligible != expected_eligible
            ):
                raise SeasonalPreparationError("CLEANING_SENSITIVITY_FAILED")
            previous_observed = observed
            expected_eligible = eligible
        _validate_integral_report(lww[name], comparison=True)
        _validate_integral_report(boundary[name], comparison=True)


def _validate_integral_report(
    value: object,
    *,
    comparison: bool,
) -> tuple[int, int]:
    names = (
        "observed_seconds",
        "eligible_seconds",
        "coverage",
        "value_hours",
        *(("relative_value_hours_change",) if comparison else ()),
    )
    report = _exact(value, names, "INTEGRAL_REPORT")
    observed = _integer(report["observed_seconds"], "OBSERVED_SECONDS")
    eligible = _integer(report["eligible_seconds"], "ELIGIBLE_SECONDS")
    if observed > eligible:
        raise SeasonalPreparationError("CLEANING_SENSITIVITY_FAILED")
    _require_ratio(
        report["coverage"],
        numerator=observed,
        denominator=eligible,
        context="INTEGRAL_COVERAGE",
    )
    _number(report["value_hours"], "INTEGRAL_VALUE_HOURS")
    if comparison and report["relative_value_hours_change"] is not None:
        _number(report["relative_value_hours_change"], "RELATIVE_VALUE_HOURS_CHANGE")
    return observed, eligible


def _validate_boundary(config: JPLMonthConfig, document: Mapping[str, Any]) -> None:
    value = _exact(
        document,
        (
            "schema_version",
            "month",
            "status",
            "positive_points_excluded",
            "sessions_affected",
            "signed_distance_seconds",
            "before_connection_count",
            "at_or_after_disconnect_count",
            "excluded_positive_ampere_seconds",
            "raw_total_ampere_seconds",
            "current_integral_share",
            "sensitivity_window_seconds",
            "main_result_excludes_boundary_points",
        ),
        "BOUNDARY_AUDIT",
    )
    if (
        value["schema_version"] != "acn-jpl-seasonal-preparation-boundary-audit/v1"
        or value["month"] != config.month
        or value["status"] != "PASS"
        or value["sensitivity_window_seconds"] != 60
        or value["main_result_excludes_boundary_points"] is not True
    ):
        raise SeasonalPreparationError("BOUNDARY_AUDIT_FAILED")
    for name in (
        "positive_points_excluded",
        "sessions_affected",
        "before_connection_count",
        "at_or_after_disconnect_count",
    ):
        _integer(value[name], "BOUNDARY_COUNT")
    distribution = _exact(
        value["signed_distance_seconds"],
        ("count", "minimum", "p05", "median", "p95", "maximum"),
        "BOUNDARY_DISTRIBUTION",
    )
    if (
        _integer(distribution["count"], "BOUNDARY_DISTANCE_COUNT")
        != value["positive_points_excluded"]
        or value["before_connection_count"] + value["at_or_after_disconnect_count"]
        != value["positive_points_excluded"]
    ):
        raise SeasonalPreparationError("BOUNDARY_AUDIT_FAILED")
    for name in ("minimum", "p05", "median", "p95", "maximum"):
        if distribution[name] is not None:
            _number(distribution[name], "BOUNDARY_DISTANCE")
    excluded = _number(value["excluded_positive_ampere_seconds"], "EXCLUDED_AMPERE_SECONDS")
    raw_total = _number(value["raw_total_ampere_seconds"], "RAW_AMPERE_SECONDS")
    share = _number(value["current_integral_share"], "CURRENT_INTEGRAL_SHARE")
    expected_share = excluded / raw_total if raw_total else 0.0
    if (
        excluded < 0
        or raw_total < 0
        or not 0 <= share <= 1
        or not _same_number(share, expected_share)
    ):
        raise SeasonalPreparationError("BOUNDARY_AUDIT_FAILED")


def _validate_power(config: JPLMonthConfig, document: Mapping[str, Any]) -> str:
    value = _exact(
        document,
        (
            "schema_version",
            "month",
            "status",
            "legacy_classifier_status",
            "continue_current_pipeline",
            "e208_authorized",
            "reconstructed_kw_column_authorized",
            "current_proxy_available",
            "pinned_evidence",
            "mapping",
            "primary_cohort",
            "statistics_finite",
            "privacy",
        ),
        "POWER_SEMANTICS",
    )
    privacy = _exact(
        value["privacy"],
        ("aggregate_only", "identifiers_emitted"),
        "POWER_PRIVACY",
    )
    evidence = _exact(
        value["pinned_evidence"],
        (
            "repository",
            "commit",
            "source_sha256",
            "default_evse_voltage_v",
            "line_to_line_network",
            "e208_formula",
        ),
        "PINNED_POWER_EVIDENCE",
    )
    mapping = _exact(
        value["mapping"],
        (
            "raw_record_count",
            "mapped_record_count",
            "unmapped_record_count",
            "mapping_rate",
        ),
        "POWER_MAPPING",
    )
    primary = _exact(
        value["primary_cohort"],
        (
            "thresholds",
            "input_session_count",
            "eligible_session_count",
            "coverage_qualified_session_count",
            "retained_session_count",
            "audit_coverage",
            "retained_rate",
            "effective_voltage_v",
            "e208_error",
            "aggregate_energy",
        ),
        "PRIMARY_POWER_COHORT",
    )
    thresholds = _exact(
        primary["thresholds"],
        ("minimum_kwh_delivered", "minimum_current_coverage"),
        "POWER_THRESHOLDS",
    )
    voltage = _exact(
        primary["effective_voltage_v"],
        ("count", "q1", "median", "q3", "iqr"),
        "VOLTAGE",
    )
    error = _exact(
        primary["e208_error"],
        ("count", "median_absolute_percentage_error", "p90_absolute_percentage_error"),
        "E208_ERROR",
    )
    aggregate = _exact(
        primary["aggregate_energy"],
        (
            "session_count",
            "observed_kwh",
            "e208_kwh",
            "error_kwh",
            "relative_error",
            "absolute_relative_error",
        ),
        "AGGREGATE_ENERGY",
    )
    raw_count = _integer(mapping["raw_record_count"], "POWER_RAW_COUNT")
    mapped_count = _integer(mapping["mapped_record_count"], "POWER_MAPPED_COUNT")
    unmapped_count = _integer(mapping["unmapped_record_count"], "POWER_UNMAPPED_COUNT")
    mapping_rate = _number(mapping["mapping_rate"], "POWER_MAPPING_RATE")
    if mapped_count + unmapped_count != raw_count or not _same_number(
        mapping_rate, mapped_count / raw_count if raw_count else 0.0
    ):
        raise SeasonalPreparationError("POWER_SEMANTICS_GATE_FAILED")
    input_count = _integer(primary["input_session_count"], "POWER_INPUT_COUNT")
    eligible_count = _integer(primary["eligible_session_count"], "POWER_ELIGIBLE_COUNT")
    qualified_count = _integer(primary["coverage_qualified_session_count"], "POWER_QUALIFIED_COUNT")
    retained_count = _integer(primary["retained_session_count"], "POWER_RETAINED_COUNT")
    if not input_count >= eligible_count >= qualified_count >= retained_count >= 0:
        raise SeasonalPreparationError("POWER_SEMANTICS_GATE_FAILED")
    _require_ratio(
        primary["audit_coverage"],
        numerator=qualified_count,
        denominator=eligible_count,
        context="POWER_AUDIT_COVERAGE",
    )
    _require_ratio(
        primary["retained_rate"],
        numerator=retained_count,
        denominator=eligible_count,
        context="POWER_RETAINED_RATE",
    )
    for section in (voltage, error):
        if _integer(section["count"], "POWER_STATISTIC_COUNT") != retained_count:
            raise SeasonalPreparationError("POWER_SEMANTICS_GATE_FAILED")
    if _integer(aggregate["session_count"], "POWER_ENERGY_COUNT") != retained_count:
        raise SeasonalPreparationError("POWER_SEMANTICS_GATE_FAILED")
    q1_voltage = _optional_number(voltage["q1"], "Q1_VOLTAGE")
    median_voltage = _optional_number(voltage["median"], "MEDIAN_VOLTAGE")
    q3_voltage = _optional_number(voltage["q3"], "Q3_VOLTAGE")
    voltage_iqr = _optional_number(voltage["iqr"], "VOLTAGE_IQR")
    median_ape = _optional_number(error["median_absolute_percentage_error"], "MEDIAN_APE")
    p90_ape = _optional_number(error["p90_absolute_percentage_error"], "P90_APE")
    observed_kwh = _number(aggregate["observed_kwh"], "OBSERVED_KWH")
    e208_kwh = _number(aggregate["e208_kwh"], "E208_KWH")
    error_kwh = _number(aggregate["error_kwh"], "ENERGY_ERROR_KWH")
    relative_error = _optional_number(aggregate["relative_error"], "ENERGY_RELATIVE_ERROR")
    absolute_relative_error = _optional_number(
        aggregate["absolute_relative_error"], "ABSOLUTE_ENERGY_RELATIVE_ERROR"
    )
    if (
        evidence
        != {
            "repository": "https://github.com/zach401/acnportal",
            "commit": "14e723b11339e56ca3afd2bf4969f9e4bc8c2623",
            "source_sha256": "0a8c9de3c972995dd323e3c2a976bff8511b795553f3926b60251b5418d6140d",
            "default_evse_voltage_v": 208.0,
            "line_to_line_network": True,
            "e208_formula": "E_208_kWh=208*ampere_hours/1000",
        }
        or thresholds != {"minimum_kwh_delivered": 0.5, "minimum_current_coverage": 0.9}
        or input_count != raw_count
        or observed_kwh < 0
        or e208_kwh < 0
        or not _same_number(error_kwh, e208_kwh - observed_kwh)
        or (relative_error is None) != (observed_kwh == 0)
        or (
            relative_error is not None
            and not _same_number(relative_error, error_kwh / observed_kwh)
        )
        or (absolute_relative_error is None) != (relative_error is None)
        or (
            relative_error is not None
            and not _same_number(absolute_relative_error, abs(relative_error))
        )
        or (
            retained_count == 0
            and any(
                item is not None
                for item in (q1_voltage, median_voltage, q3_voltage, voltage_iqr)
            )
        )
        or (
            retained_count > 0
            and (
                any(
                    item is None
                    for item in (q1_voltage, median_voltage, q3_voltage, voltage_iqr)
                )
                or not q1_voltage <= median_voltage <= q3_voltage  # type: ignore[operator]
                or not _same_number(voltage_iqr, q3_voltage - q1_voltage)  # type: ignore[operator]
            )
        )
    ):
        raise SeasonalPreparationError("POWER_SEMANTICS_GATE_FAILED")
    statistics_finite = value["statistics_finite"]
    if type(statistics_finite) is not bool or (
        statistics_finite
        and not all(
            item is not None
            for item in (median_voltage, voltage_iqr, median_ape, p90_ape, relative_error)
        )
    ):
        raise SeasonalPreparationError("POWER_SEMANTICS_GATE_FAILED")
    from .acn_jpl_power_semantics import PowerDecisionInputs, seasonal_power_decision

    decision = seasonal_power_decision(
        PowerDecisionInputs(
            mapping_rate=mapping_rate,
            primary_audit_coverage=(
                float(primary["audit_coverage"])
                if primary["audit_coverage"] is not None
                else math.nan
            ),
            eligible_session_count=eligible_count,
            retained_session_count=retained_count,
            median_absolute_percentage_error=(median_ape if median_ape is not None else math.nan),
            p90_absolute_percentage_error=p90_ape if p90_ape is not None else math.nan,
            monthly_relative_energy_error=(
                relative_error if relative_error is not None else math.nan
            ),
            statistics_finite=statistics_finite,
        )
    )
    if (
        value["schema_version"] != "acn-jpl-seasonal-preparation-power-semantics/v1"
        or value["month"] != config.month
        or value["status"] not in _POWER_STATUSES
        or value["legacy_classifier_status"] not in {"POWER_SEMANTICS_FAIL", *_POWER_STATUSES}
        or value["continue_current_pipeline"] is not True
        or value["e208_authorized"] is not False
        or value["reconstructed_kw_column_authorized"] is not False
        or value["current_proxy_available"] is not True
        or value["legacy_classifier_status"] != decision.legacy_classifier_status
        or value["status"] != decision.power_semantics_status
        or privacy != {"aggregate_only": True, "identifiers_emitted": False}
    ):
        raise SeasonalPreparationError("POWER_SEMANTICS_GATE_FAILED")
    return str(value["status"])


def _validate_station(
    config: JPLMonthConfig,
    document: Mapping[str, Any],
    *,
    trajectory_quarantine_count: int,
) -> int:
    value = _exact(
        document,
        (
            "schema_version",
            "month",
            "status",
            "grid_policy",
            "station_columns",
            "expected_bins",
            "generated_bins",
            "valid_bins_at_80",
            "valid_bins_at_90",
            "valid_bins_at_95",
            "pilot_valid_bins_at_80",
            "pilot_valid_bins_at_90",
            "pilot_valid_bins_at_95",
            "valid_bin_rate_at_80",
            "valid_bin_rate_at_90",
            "valid_bin_rate_at_95",
            "missing_bin_rate_at_80",
            "missing_bin_rate_at_90",
            "missing_bin_rate_at_95",
            "valid_bin_90_rate",
            "valid_bin_90_rate_min",
            "valid_bin_90_gate",
            "trajectory_quarantine_count",
            "coverage_denominator_includes_quarantined",
            "missing_bin_rate",
            "longest_missing_run",
            "peak_current_proxy_a",
            "max_absolute_ramp_a",
            "weekday_distribution",
            "weekend_distribution",
            "active_threshold_sensitivity",
            "aggregation_semantics",
            "dst_fold_extra_bins",
            "repeated_local_quarter_count",
            "time_weighted_integral_status",
        ),
        "STATION_15MIN",
    )
    valid_80 = _integer(value["valid_bins_at_80"], "VALID_BIN_80")
    valid_90 = _integer(value["valid_bins_at_90"], "VALID_BIN_90")
    valid_95 = _integer(value["valid_bins_at_95"], "VALID_BIN_95")
    valid_rate = _number(value["valid_bin_90_rate"], "VALID_BIN_90_RATE")
    missing_rate = _number(value["missing_bin_rate"], "MISSING_BIN_RATE")
    expected_columns = [
        "station_current_mean_a",
        "station_current_peak_a",
        "connected_session_count",
        "active_charging_session_count",
        "pilot_sum_a",
        "pilot_mean_a",
        "arrival_count",
        "disconnect_count",
        "observed_coverage_ratio",
        "valid_bin_80",
        "valid_bin_90",
        "valid_bin_95",
    ]
    if (
        value["schema_version"] != "acn-jpl-seasonal-preparation-station-15min-qa/v1"
        or value["month"] != config.month
        or value["status"] != "PASS"
        or value["grid_policy"] != config.grid_policy
        or value["station_columns"] != expected_columns
        or _integer(value["expected_bins"], "EXPECTED_BINS", positive=True) != config.expected_bins
        or _integer(value["generated_bins"], "GENERATED_BINS", positive=True)
        != config.expected_bins
        or not config.expected_bins >= valid_80 >= valid_90 >= valid_95 >= 0
        or not _same_number(valid_rate, valid_90 / config.expected_bins)
        or not _same_number(missing_rate, 1.0 - valid_rate)
        or not _same_number(_number(value["valid_bin_90_rate_min"], "VALID_BIN_MIN"), 0.80)
        or valid_rate < 0.80
        or value["valid_bin_90_gate"] != "PASS"
        or _integer(
            value["trajectory_quarantine_count"],
            "TRAJECTORY_QUARANTINE_COUNT",
        )
        != trajectory_quarantine_count
        or value["coverage_denominator_includes_quarantined"] is not True
        or value["time_weighted_integral_status"] != "PASS"
    ):
        raise SeasonalPreparationError("VALID_BIN_90_GATE_FAILED")
    for threshold, count in ((80, valid_80), (90, valid_90), (95, valid_95)):
        rate = _number(value[f"valid_bin_rate_at_{threshold}"], "VALID_BIN_RATE")
        missing = _number(value[f"missing_bin_rate_at_{threshold}"], "MISSING_BIN_RATE")
        pilot_count = _integer(value[f"pilot_valid_bins_at_{threshold}"], "PILOT_VALID_BINS")
        if (
            pilot_count > config.expected_bins
            or not _same_number(rate, count / config.expected_bins)
            or not _same_number(missing, 1.0 - rate)
        ):
            raise SeasonalPreparationError("VALID_BIN_90_GATE_FAILED")
    longest = _integer(value["longest_missing_run"], "LONGEST_MISSING_RUN")
    peak = _optional_number(value["peak_current_proxy_a"], "PEAK_CURRENT_PROXY")
    ramp = _number(value["max_absolute_ramp_a"], "MAX_ABSOLUTE_RAMP")
    if longest > config.expected_bins or ramp < 0 or (peak is not None and peak < 0):
        raise SeasonalPreparationError("VALID_BIN_90_GATE_FAILED")
    distributions = []
    for name in ("weekday_distribution", "weekend_distribution"):
        distribution = _exact(
            value[name],
            ("bin_count", "valid_bin_count", "mean_current_a", "median_current_a"),
            "STATION_DISTRIBUTION",
        )
        bin_count = _integer(distribution["bin_count"], "DISTRIBUTION_BIN_COUNT")
        distribution_valid = _integer(distribution["valid_bin_count"], "DISTRIBUTION_VALID_COUNT")
        if distribution_valid > bin_count:
            raise SeasonalPreparationError("VALID_BIN_90_GATE_FAILED")
        for statistic in ("mean_current_a", "median_current_a"):
            number = _optional_number(distribution[statistic], "DISTRIBUTION_CURRENT")
            if number is not None and number < 0:
                raise SeasonalPreparationError("VALID_BIN_90_GATE_FAILED")
        distributions.append((bin_count, distribution_valid))
    if (
        sum(item[0] for item in distributions) != config.expected_bins
        or sum(item[1] for item in distributions) != valid_90
    ):
        raise SeasonalPreparationError("VALID_BIN_90_GATE_FAILED")
    active = _exact(
        value["active_threshold_sensitivity"],
        (
            "main_threshold_a",
            "comparison_threshold_a",
            "main_end_bin_count_sum",
            "comparison_end_bin_count_sum",
        ),
        "ACTIVE_THRESHOLD_SENSITIVITY",
    )
    if (
        _number(active["main_threshold_a"], "MAIN_ACTIVE_THRESHOLD") != 0.1
        or _number(active["comparison_threshold_a"], "COMPARISON_ACTIVE_THRESHOLD") != 1.0
        or _integer(active["main_end_bin_count_sum"], "MAIN_ACTIVE_COUNT")
        < _integer(active["comparison_end_bin_count_sum"], "COMPARISON_ACTIVE_COUNT")
    ):
        raise SeasonalPreparationError("VALID_BIN_90_GATE_FAILED")
    semantics = _exact(
        value["aggregation_semantics"],
        ("bin_rule", "missing_is_zero", "power_label_type"),
        "AGGREGATION_SEMANTICS",
    )
    expected_fold = 4 if config.month == "2019-11" else 0
    if (
        semantics
        != {
            "bin_rule": "left_closed_right_open",
            "missing_is_zero": False,
            "power_label_type": "none",
        }
        or _integer(value["dst_fold_extra_bins"], "DST_FOLD_EXTRA") != expected_fold
        or _integer(value["repeated_local_quarter_count"], "REPEATED_LOCAL_QUARTERS")
        != expected_fold
    ):
        raise SeasonalPreparationError("VALID_BIN_90_GATE_FAILED")
    return valid_90


def _validate_issue(config: JPLMonthConfig, document: Mapping[str, Any]) -> int:
    value = _exact(
        document,
        (
            "schema_version",
            "month",
            "status",
            "tiers",
            "lookback_minutes",
            "horizons_minutes",
            "scheduled_issue_times",
            "formal_issue_times",
            "incomplete_label_issue_times",
            "samples",
            "ragged_rows",
            "valid_labels_by_horizon",
            "shapes",
            "missing_rates",
            "snapshot_sha256",
            "m4_generated",
            "leakage_status",
        ),
        "ISSUE_SNAPSHOT",
    )
    scheduled = _integer(value["scheduled_issue_times"], "SCHEDULED_ISSUE_TIMES", positive=True)
    formal = _integer(value["formal_issue_times"], "FORMAL_ISSUE_TIMES")
    samples = _exact(value["samples"], _TIERS, "ISSUE_SAMPLES")
    ragged = _exact(value["ragged_rows"], ("M3",), "ISSUE_RAGGED_ROWS")
    expected_labels = tuple(str(item) for item in _HORIZONS_MINUTES)
    labels = _exact(value["valid_labels_by_horizon"], expected_labels, "ISSUE_LABEL_COUNTS")
    shapes = _exact(
        value["shapes"],
        (
            "M1_history",
            "M2_dense",
            "M3_ragged_rows",
            "M3_session_feature_width",
            "labels",
        ),
        "ISSUE_SHAPES",
    )
    m3_rows = _integer(ragged["M3"], "M3_RAGGED_ROWS")
    expected_shapes = {
        "M1_history": [formal, 96],
        "M2_dense": [formal, 6],
        "M3_ragged_rows": m3_rows,
        "M3_session_feature_width": 11,
        "labels": [formal, len(_HORIZONS_MINUTES)],
    }
    missing = _exact(value["missing_rates"], _SNAPSHOT_MISSING_RATE_NAMES, "ISSUE_MISSING_RATES")
    for item in missing.values():
        parsed = _optional_number(item, "ISSUE_MISSING_RATE")
        if parsed is not None and not 0 <= parsed <= 1:
            raise SeasonalPreparationError("ISSUE_SNAPSHOT_GATE_FAILED")
    if (
        value["schema_version"] != "acn-jpl-seasonal-preparation-issue-snapshot-qa/v1"
        or value["month"] != config.month
        or value["status"] != "PASS"
        or value["tiers"] != list(_TIERS)
        or _integer(value["lookback_minutes"], "LOOKBACK_MINUTES", positive=True) != 1440
        or value["horizons_minutes"] != list(_HORIZONS_MINUTES)
        or scheduled != config.expected_scheduled_issue_times
        or not 0 < formal <= scheduled
        or _integer(value["incomplete_label_issue_times"], "INCOMPLETE_LABELS")
        != scheduled - formal
        or samples != {tier: formal for tier in _TIERS}
        or any(
            not formal <= _integer(labels[str(item)], "VALID_LABEL_COUNT") <= scheduled
            for item in _HORIZONS_MINUTES
        )
        or shapes != expected_shapes
        or _integer(shapes["M3_ragged_rows"], "M3_SHAPE_ROWS") != m3_rows
        or value["m4_generated"] is not False
        or value["leakage_status"] != "PASS"
    ):
        raise SeasonalPreparationError("ISSUE_SNAPSHOT_GATE_FAILED")
    _digest(value["snapshot_sha256"], "SNAPSHOT_SHA256")
    return formal


def _validate_leakage(config: JPLMonthConfig, document: Mapping[str, Any]) -> None:
    value = _exact(
        document,
        (
            "schema_version",
            "month",
            "status",
            "identifiers_emitted",
            "future_outcome_fields_emitted",
            "future_outcome_field_count",
            "private_identifier_field_count",
            "unexpected_feature_key_count",
            "temporal_violation_count",
            "late_user_input_rows",
            "issue_time_user_input_status",
            "connected_user_input_rows",
            "known_user_input_rows",
            "user_input_rule",
            "feature_whitelist_status",
        ),
        "LEAKAGE",
    )
    connected = _integer(value["connected_user_input_rows"], "CONNECTED_USER_INPUT_ROWS")
    known = _integer(value["known_user_input_rows"], "KNOWN_USER_INPUT_ROWS")
    if (
        value["schema_version"] != "acn-jpl-seasonal-preparation-leakage-audit/v1"
        or value["month"] != config.month
        or value["status"] != "PASS"
        or value["identifiers_emitted"] is not False
        or value["future_outcome_fields_emitted"] is not False
        or _integer(value["future_outcome_field_count"], "FUTURE_FIELD_COUNT") != 0
        or _integer(value["private_identifier_field_count"], "PRIVATE_FIELD_COUNT") != 0
        or value["unexpected_feature_key_count"] != 0
        or value["temporal_violation_count"] != 0
        or value["late_user_input_rows"] != 0
        or value["issue_time_user_input_status"] != "PASS"
        or known > connected
        or value["user_input_rule"] != "last modifiedAt at or before issue time"
        or value["feature_whitelist_status"] != "PASS"
    ):
        raise SeasonalPreparationError("LEAKAGE_GATE_FAILED")


def _validate_data_manifest(config: JPLMonthConfig, document: Mapping[str, Any]) -> None:
    value = _exact(
        document,
        (
            "schema_version",
            "month",
            "status",
            "config_sha256",
            "code_commit",
            "metadata_source_inventory_sha256",
            "metadata_record_inventory_sha256",
            "raw_inventory_sha256",
            "processed_snapshot_sha256",
            "raw_dimensions",
            "encoded_dimensions",
            "local_artifact_count",
            "trajectory_quarantine_count",
            "full_session_quarantine_count",
            "anonymous_local_indexes_published",
            "large_arrays_published",
        ),
        "DATA_SNAPSHOT",
    )
    if (
        value["schema_version"] != "acn-jpl-seasonal-preparation-data-snapshot/v1"
        or value["month"] != config.month
        or value["status"] != "PASS"
        or not isinstance(value["raw_dimensions"], list)
        or tuple(value["raw_dimensions"]) != _RAW_DIMENSIONS
        or not isinstance(value["encoded_dimensions"], list)
        or tuple(value["encoded_dimensions"]) != _ENCODED_DIMENSIONS
        or _integer(
            value["trajectory_quarantine_count"],
            "TRAJECTORY_QUARANTINE_COUNT",
        )
        != (1 if config.month == "2019-11" else 0)
        or _integer(
            value["full_session_quarantine_count"],
            "FULL_SESSION_QUARANTINE_COUNT",
        )
        != 0
        or value["anonymous_local_indexes_published"] is not False
        or value["large_arrays_published"] is not False
    ):
        raise SeasonalPreparationError("DATA_SNAPSHOT_GATE_FAILED")
    _digest(value["config_sha256"], "CONFIG_SHA256")
    _commit(value["code_commit"])
    for name in (
        "metadata_source_inventory_sha256",
        "metadata_record_inventory_sha256",
        "raw_inventory_sha256",
        "processed_snapshot_sha256",
    ):
        _digest(value[name], name.upper())
    _integer(value["local_artifact_count"], "LOCAL_ARTIFACT_COUNT", positive=True)


def _validate_run(
    config: JPLMonthConfig,
    document: Mapping[str, Any],
    *,
    local_count: int,
    carry_count: int,
    combined_count: int,
    valid_90: int,
    formal: int,
    power_status: str,
    trajectory_quarantine_count: int,
    full_session_quarantine_count: int,
) -> str:
    value = _exact(
        document,
        (
            "schema_version",
            "month",
            "status",
            "raw_unchanged",
            "official_total",
            "local_session_count",
            "carry_in_count",
            "sessions_processed",
            "cleaned_session_count",
            "invalid_skipped_session_count",
            "trajectory_quarantine_count",
            "full_session_quarantine_count",
            "station_bins",
            "valid_bin_90_count",
            "scheduled_issue_times",
            "formal_issue_times",
            "power_semantics_status",
            "ready_for_gate1_baseline",
            "scope",
            "privacy",
        ),
        "RUN_MANIFEST",
    )
    scope = _exact(value["scope"], ("training", "network", "optimization"), "RUN_SCOPE")
    privacy = _exact(
        value["privacy"],
        ("aggregate_only", "private_values_emitted", "absolute_paths_emitted"),
        "RUN_PRIVACY",
    )
    expected_status = (
        "PASS_WITH_TRAJECTORY_QUARANTINE"
        if trajectory_quarantine_count
        else (
            "PASS"
            if power_status == "KW_RECONSTRUCTION_CANDIDATE"
            else "CONDITIONAL_PASS"
        )
    )
    if (
        value["schema_version"] != "acn-jpl-seasonal-preparation-run/v1"
        or value["month"] != config.month
        or value["status"] != expected_status
        or value["raw_unchanged"] is not True
        or value["official_total"] != local_count
        or value["local_session_count"] != local_count
        or value["carry_in_count"] != carry_count
        or value["sessions_processed"] != combined_count
        or type(value["invalid_skipped_session_count"]) is not int
        or value["invalid_skipped_session_count"] < 0
        or value["cleaned_session_count"] != combined_count - value["invalid_skipped_session_count"]
        or value["trajectory_quarantine_count"] != trajectory_quarantine_count
        or value["full_session_quarantine_count"] != full_session_quarantine_count
        or value["station_bins"] != config.expected_bins
        or value["valid_bin_90_count"] != valid_90
        or value["scheduled_issue_times"] != config.expected_scheduled_issue_times
        or value["formal_issue_times"] != formal
        or value["power_semantics_status"] != power_status
        or value["ready_for_gate1_baseline"] is not True
        or scope != {"training": False, "network": False, "optimization": False}
        or privacy
        != {
            "aggregate_only": True,
            "private_values_emitted": False,
            "absolute_paths_emitted": False,
        }
    ):
        raise SeasonalPreparationError("RUN_MANIFEST_INVALID")
    return expected_status


def _validate_month_documents(
    config: JPLMonthConfig,
    documents: Mapping[str, Mapping[str, Any]],
) -> None:
    if (
        type(config) is not JPLMonthConfig
        or not is_canonical_jpl_month_config(config)
        or config.month not in SEASONAL_MONTHS
        or config.tiers != _TIERS
        or config.grid_policy != "continuous_physical_utc"
    ):
        raise SeasonalPreparationError("MONTH_CONFIG_INVALID")
    if set(documents) != set(MONTH_PAYLOAD_NAMES):
        raise SeasonalPreparationError("PUBLIC_SCHEMA_INVALID")
    for document in documents.values():
        _validate_public_value(document)
    local, carry, combined, trajectory, full = _validate_acquisition(
        config,
        documents["acquisition_summary.json"],
    )
    current_hold, pilot_hold = _validate_cleaning(
        config,
        documents["cleaning_qa.json"],
        combined_count=combined,
        trajectory_quarantine_count=trajectory,
        full_session_quarantine_count=full,
    )
    _validate_sensitivity(
        config,
        documents["cleaning_sensitivity.json"],
        current_hold=current_hold,
        pilot_hold=pilot_hold,
    )
    _validate_boundary(config, documents["boundary_current_audit.json"])
    power = _validate_power(config, documents["power_semantics_audit.json"])
    valid_90 = _validate_station(
        config,
        documents["station_15min_qa.json"],
        trajectory_quarantine_count=trajectory,
    )
    formal = _validate_issue(config, documents["issue_snapshot_qa.json"])
    _validate_leakage(config, documents["leakage_audit.json"])
    _validate_data_manifest(config, documents["data_snapshot_manifest.json"])
    _validate_run(
        config,
        documents["run_manifest.json"],
        local_count=local,
        carry_count=carry,
        combined_count=combined,
        valid_90=valid_90,
        formal=formal,
        power_status=power,
        trajectory_quarantine_count=trajectory,
        full_session_quarantine_count=full,
    )
    acquisition = documents["acquisition_summary.json"]
    data_manifest = documents["data_snapshot_manifest.json"]
    for name in (
        "metadata_source_inventory_sha256",
        "metadata_record_inventory_sha256",
        "raw_inventory_sha256",
    ):
        if acquisition[name] != data_manifest[name]:
            raise SeasonalPreparationError("PROVENANCE_BINDING_INVALID")


def build_month_preparation_result(
    *,
    config: JPLMonthConfig,
    documents: Mapping[str, object],
) -> MonthPreparationResult:
    """Close aggregate documents into one independently verifiable result."""

    if not isinstance(documents, Mapping) or set(documents) != set(MONTH_PAYLOAD_NAMES):
        raise SeasonalPreparationError("PUBLIC_SCHEMA_INVALID")
    canonical: dict[str, Mapping[str, Any]] = {}
    artifacts: list[ClosedArtifact] = []
    for name in MONTH_PAYLOAD_NAMES:
        raw_value = documents[name]
        if not isinstance(raw_value, Mapping):
            raise SeasonalPreparationError("PUBLIC_SCHEMA_INVALID")
        content = _json_bytes(raw_value)
        parsed = _decode_json_bytes(content)
        canonical[name] = parsed
        artifacts.append(ClosedArtifact(name, content))
    _validate_month_documents(config, canonical)
    acquisition = canonical["acquisition_summary.json"]
    cleaning = canonical["cleaning_qa.json"]
    station = canonical["station_15min_qa.json"]
    issue = canonical["issue_snapshot_qa.json"]
    power = canonical["power_semantics_audit.json"]
    data_manifest = canonical["data_snapshot_manifest.json"]
    run = canonical["run_manifest.json"]
    raw_dimensions = tuple(data_manifest["raw_dimensions"])
    encoded_dimensions = tuple(data_manifest["encoded_dimensions"])
    if raw_dimensions != _RAW_DIMENSIONS or encoded_dimensions != _ENCODED_DIMENSIONS:
        raise SeasonalPreparationError("DATA_SNAPSHOT_GATE_FAILED")
    return MonthPreparationResult(
        month=config.month,
        status=str(run["status"]),
        official_total=int(acquisition["official_total"]),
        local_session_count=int(acquisition["local_session_count"]),
        carry_in_count=int(acquisition["carry_in_count"]),
        sessions_processed=int(cleaning["sessions_processed"]),
        cleaned_session_count=int(cleaning["cleaned_session_count"]),
        invalid_skipped_session_count=int(cleaning["invalid_skipped_session_count"]),
        trajectory_quarantine_count=int(acquisition["trajectory_quarantine_count"]),
        full_session_quarantine_count=int(acquisition["full_session_quarantine_count"]),
        station_bins=int(station["generated_bins"]),
        valid_bin_90_count=int(station["valid_bins_at_90"]),
        scheduled_issue_times=int(issue["scheduled_issue_times"]),
        formal_issue_times=int(issue["formal_issue_times"]),
        power_semantics_status=str(power["status"]),
        grid_policy=str(station["grid_policy"]),
        raw_dimensions=_RAW_DIMENSIONS,
        encoded_dimensions=_ENCODED_DIMENSIONS,
        config_sha256=str(data_manifest["config_sha256"]),
        code_commit=str(data_manifest["code_commit"]),
        metadata_source_inventory_sha256=str(data_manifest["metadata_source_inventory_sha256"]),
        metadata_record_inventory_sha256=str(data_manifest["metadata_record_inventory_sha256"]),
        raw_inventory_sha256=str(data_manifest["raw_inventory_sha256"]),
        processed_snapshot_sha256=str(data_manifest["processed_snapshot_sha256"]),
        raw_unchanged=run["raw_unchanged"] is True,
        artifacts=tuple(artifacts),
    )


def _validate_month_result(result: MonthPreparationResult) -> None:
    if (
        type(result) is not MonthPreparationResult
        or result.month not in SEASONAL_MONTHS
        or result.status not in _MONTH_STATUSES
    ):
        raise SeasonalPreparationError("MONTH_RESULT_INVALID")
    try:
        config = jpl_month_config(result.month)
    except (TypeError, ValueError) as exc:
        raise SeasonalPreparationError("MONTH_RESULT_INVALID") from exc
    if tuple(item.name for item in result.artifacts) != MONTH_PAYLOAD_NAMES:
        raise SeasonalPreparationError("PUBLIC_SCHEMA_INVALID")
    documents: dict[str, Mapping[str, Any]] = {}
    for item in result.artifacts:
        if (
            type(item) is not ClosedArtifact
            or item.sha256 != hashlib.sha256(item.content).hexdigest()
        ):
            raise SeasonalPreparationError("PUBLIC_HASH_INVALID")
        documents[item.name] = _decode_json_bytes(item.content)
    _validate_month_documents(config, documents)
    acquisition = documents["acquisition_summary.json"]
    cleaning = documents["cleaning_qa.json"]
    station = documents["station_15min_qa.json"]
    issue = documents["issue_snapshot_qa.json"]
    power = documents["power_semantics_audit.json"]
    data_manifest = documents["data_snapshot_manifest.json"]
    run = documents["run_manifest.json"]
    expected: Mapping[str, object] = {
        "status": run["status"],
        "official_total": acquisition["official_total"],
        "local_session_count": acquisition["local_session_count"],
        "carry_in_count": acquisition["carry_in_count"],
        "sessions_processed": cleaning["sessions_processed"],
        "cleaned_session_count": cleaning["cleaned_session_count"],
        "invalid_skipped_session_count": cleaning["invalid_skipped_session_count"],
        "trajectory_quarantine_count": acquisition["trajectory_quarantine_count"],
        "full_session_quarantine_count": acquisition["full_session_quarantine_count"],
        "station_bins": station["generated_bins"],
        "valid_bin_90_count": station["valid_bins_at_90"],
        "scheduled_issue_times": issue["scheduled_issue_times"],
        "formal_issue_times": issue["formal_issue_times"],
        "power_semantics_status": power["status"],
        "grid_policy": station["grid_policy"],
        "raw_dimensions": tuple(data_manifest["raw_dimensions"]),
        "encoded_dimensions": tuple(data_manifest["encoded_dimensions"]),
        "config_sha256": data_manifest["config_sha256"],
        "code_commit": data_manifest["code_commit"],
        "metadata_source_inventory_sha256": data_manifest["metadata_source_inventory_sha256"],
        "metadata_record_inventory_sha256": data_manifest["metadata_record_inventory_sha256"],
        "raw_inventory_sha256": data_manifest["raw_inventory_sha256"],
        "processed_snapshot_sha256": data_manifest["processed_snapshot_sha256"],
        "raw_unchanged": run["raw_unchanged"],
    }
    for name, expected_value in expected.items():
        if getattr(result, name) != expected_value:
            raise SeasonalPreparationError("MONTH_RESULT_INVALID")


def _month_release_bytes(result: MonthPreparationResult) -> dict[str, bytes]:
    _validate_month_result(result)
    contents = {item.name: item.content for item in result.artifacts}
    checksum = "".join(
        f"{hashlib.sha256(contents[name]).hexdigest()}  {name}\n" for name in MONTH_PAYLOAD_NAMES
    ).encode("ascii")
    return {**contents, "SHA256SUMS": checksum}


def _parse_checksums(
    content: bytes,
    *,
    expected_names: Sequence[str],
) -> dict[str, str]:
    try:
        text = content.decode("ascii")
    except UnicodeError as exc:
        raise SeasonalPreparationError("PUBLIC_HASH_INVALID") from exc
    declared: dict[str, str] = {}
    for line in text.splitlines(keepends=True):
        if not line.endswith("\n") or line.count("  ") != 1:
            raise SeasonalPreparationError("PUBLIC_HASH_INVALID")
        digest, name = line[:-1].split("  ", 1)
        pure = PurePosixPath(name)
        if (
            _SHA256.fullmatch(digest) is None
            or name in declared
            or pure.as_posix() != name
            or pure.is_absolute()
            or ".." in pure.parts
        ):
            raise SeasonalPreparationError("PUBLIC_HASH_INVALID")
        declared[name] = digest
    if tuple(declared) != tuple(expected_names):
        raise SeasonalPreparationError("PUBLIC_HASH_INVALID")
    canonical = "".join(f"{declared[name]}  {name}\n" for name in expected_names).encode("ascii")
    if canonical != content:
        raise SeasonalPreparationError("PUBLIC_HASH_INVALID")
    return declared


def _is_reparse(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return True
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_flag)


def _closed_files(root: Path, names: Sequence[str]) -> dict[str, bytes]:
    if not root.is_dir() or _is_reparse(root):
        raise SeasonalPreparationError("PUBLIC_LAYOUT_INVALID")
    children = tuple(root.iterdir())
    if any(_is_reparse(child) or not child.is_file() for child in children):
        raise SeasonalPreparationError("PUBLIC_LAYOUT_INVALID")
    if {child.name for child in children} != set(names):
        raise SeasonalPreparationError("PUBLIC_LAYOUT_INVALID")
    try:
        return {name: (root / name).read_bytes() for name in names}
    except OSError as exc:
        raise SeasonalPreparationError("PUBLIC_LAYOUT_INVALID") from exc


def load_verified_month_release(
    output_root: str | Path,
    *,
    config: JPLMonthConfig | None = None,
) -> MonthPreparationResult:
    """Independently load one exact 11-file month release from disk."""

    root = Path(output_root)
    if config is None:
        try:
            config = jpl_month_config(root.name)
        except (TypeError, ValueError) as exc:
            raise SeasonalPreparationError("MONTH_CONFIG_INVALID") from exc
    contents = _closed_files(root, MONTH_RELEASE_NAMES)
    declared = _parse_checksums(contents["SHA256SUMS"], expected_names=MONTH_PAYLOAD_NAMES)
    if any(
        declared[name] != hashlib.sha256(contents[name]).hexdigest() for name in MONTH_PAYLOAD_NAMES
    ):
        raise SeasonalPreparationError("PUBLIC_HASH_INVALID")
    documents = {name: _decode_json_bytes(contents[name]) for name in MONTH_PAYLOAD_NAMES}
    return build_month_preparation_result(config=config, documents=documents)


def _seasonal_result(
    results: Sequence[MonthPreparationResult],
) -> SeasonalPreparationResult:
    materialized = tuple(results)
    if tuple(item.month for item in materialized) != SEASONAL_MONTHS:
        raise SeasonalPreparationError("MONTH_ORDER_INVALID")
    if any(type(item) is not MonthPreparationResult for item in materialized):
        raise SeasonalPreparationError("MONTH_RESULT_INVALID")
    for item in materialized:
        _validate_month_result(item)
    config_hashes = {item.config_sha256 for item in materialized}
    commits = {item.code_commit for item in materialized}
    if len(config_hashes) != 1:
        raise SeasonalPreparationError("CONFIG_BINDING_INVALID")
    if len(commits) != 1:
        raise SeasonalPreparationError("CODE_BINDING_INVALID")
    status = "PASS" if all(item.status == "PASS" for item in materialized) else "CONDITIONAL_PASS"
    return SeasonalPreparationResult(
        status=status,
        months=materialized,
        config_sha256=next(iter(config_hashes)),
        code_commit=next(iter(commits)),
    )


def _root_summary_rows(result: SeasonalPreparationResult) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    try:
        for item in result.months:
            documents = {
                artifact.name: _decode_json_bytes(artifact.content)
                for artifact in item.artifacts
            }
            rows.append(build_month_summary_row(documents))
    except SeasonalReportingError as exc:
        raise SeasonalPreparationError("SEASONAL_REPORT_INVALID") from exc
    return tuple(rows)


def _root_payloads(result: SeasonalPreparationResult) -> dict[str, bytes]:
    rows = _root_summary_rows(result)
    try:
        summary = render_summary_csv(rows)
        report = render_report_markdown(
            rows,
            status=result.status,
            config_sha256=result.config_sha256,
            code_commit=result.code_commit,
        )
        validate_summary_csv(summary, rows)
        validate_report_markdown(
            report,
            rows,
            status=result.status,
            config_sha256=result.config_sha256,
            code_commit=result.code_commit,
        )
    except SeasonalReportingError as exc:
        raise SeasonalPreparationError("SEASONAL_REPORT_INVALID") from exc
    snapshots = []
    for item in result.months:
        month_release = _month_release_bytes(item)
        snapshots.append(
            {
                "month": item.month,
                "status": item.status,
                "trajectory_quarantine_count": item.trajectory_quarantine_count,
                "full_session_quarantine_count": item.full_session_quarantine_count,
                "metadata_source_inventory_sha256": (item.metadata_source_inventory_sha256),
                "metadata_record_inventory_sha256": (item.metadata_record_inventory_sha256),
                "raw_inventory_sha256": item.raw_inventory_sha256,
                "processed_snapshot_sha256": item.processed_snapshot_sha256,
                "month_public_sha256": hashlib.sha256(month_release["SHA256SUMS"]).hexdigest(),
            }
        )
    manifest = {
        "schema_version": "acn-jpl-seasonal-preparation-snapshot/v1",
        "status": result.status,
        "months": list(SEASONAL_MONTHS),
        "config_sha256": result.config_sha256,
        "code_commit": result.code_commit,
        "month_snapshots": snapshots,
        "public_file_count": 37,
        "aggregate_only": True,
    }
    payloads = {
        "seasonal_prep_summary.csv": summary,
        "seasonal_snapshot_manifest.json": _json_bytes(manifest),
        "seasonal_prep_report.md": report,
    }
    for name, content in payloads.items():
        text = content.decode("utf-8")
        privacy_text = text
        if name == "seasonal_prep_report.md":
            if text.count("M4 generated: NO") != 1:
                raise SeasonalPreparationError("PUBLIC_PRIVACY_INVALID")
            privacy_text = text.replace("M4 generated: NO", "")
        if (
            _ABSOLUTE_PATH.search(text)
            or "m4" in privacy_text.casefold()
            or "prediction" in text.casefold()
        ):
            raise SeasonalPreparationError("PUBLIC_PRIVACY_INVALID")
    return payloads


def _release_bytes(result: SeasonalPreparationResult) -> dict[str, bytes]:
    contents: dict[str, bytes] = {}
    for item in result.months:
        for name, content in _month_release_bytes(item).items():
            contents[f"{item.month}/{name}"] = content
    contents.update(_root_payloads(result))
    checksum_names = (
        *ROOT_PAYLOAD_NAMES,
        *(f"{month}/{name}" for month in SEASONAL_MONTHS for name in MONTH_RELEASE_NAMES),
    )
    contents["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(contents[name]).hexdigest()}  {name}\n" for name in checksum_names
    ).encode("ascii")
    if set(contents) != set(expected_seasonal_release_paths()):
        raise AssertionError("internal seasonal release layout drift")
    return contents


def release_paths(output_root: str | Path) -> tuple[str, ...]:
    """List actual files with canonical allowlist-first relative paths."""

    root = Path(output_root)
    if not root.is_dir() or _is_reparse(root):
        return ()
    actual: set[str] = set()
    try:
        for path in root.rglob("*"):
            if _is_reparse(path) or path.is_file():
                actual.add(path.relative_to(root).as_posix())
    except OSError:
        return ()
    expected = expected_seasonal_release_paths()
    return tuple(path for path in expected if path in actual) + tuple(
        sorted(actual - set(expected))
    )


def _validate_root_documents(
    root: Path,
    result: SeasonalPreparationResult,
    contents: Mapping[str, bytes],
) -> None:
    manifest = _decode_json_bytes(contents["seasonal_snapshot_manifest.json"])
    _exact(
        manifest,
        (
            "schema_version",
            "status",
            "months",
            "config_sha256",
            "code_commit",
            "month_snapshots",
            "public_file_count",
            "aggregate_only",
        ),
        "SEASONAL_MANIFEST",
    )
    snapshots = manifest["month_snapshots"]
    if (
        manifest["schema_version"] != "acn-jpl-seasonal-preparation-snapshot/v1"
        or manifest["status"] != result.status
        or manifest["months"] != list(SEASONAL_MONTHS)
        or manifest["config_sha256"] != result.config_sha256
        or manifest["code_commit"] != result.code_commit
        or manifest["public_file_count"] != 37
        or manifest["aggregate_only"] is not True
        or not isinstance(snapshots, list)
        or len(snapshots) != 3
    ):
        raise SeasonalPreparationError("SEASONAL_MANIFEST_INVALID")
    for declared, item in zip(snapshots, result.months, strict=True):
        _exact(
            declared,
            (
                "month",
                "status",
                "trajectory_quarantine_count",
                "full_session_quarantine_count",
                "metadata_source_inventory_sha256",
                "metadata_record_inventory_sha256",
                "raw_inventory_sha256",
                "processed_snapshot_sha256",
                "month_public_sha256",
            ),
            "MONTH_SNAPSHOT",
        )
        expected = {
            "month": item.month,
            "status": item.status,
            "trajectory_quarantine_count": item.trajectory_quarantine_count,
            "full_session_quarantine_count": item.full_session_quarantine_count,
            "metadata_source_inventory_sha256": (item.metadata_source_inventory_sha256),
            "metadata_record_inventory_sha256": (item.metadata_record_inventory_sha256),
            "raw_inventory_sha256": item.raw_inventory_sha256,
            "processed_snapshot_sha256": item.processed_snapshot_sha256,
            "month_public_sha256": hashlib.sha256(
                (root / item.month / "SHA256SUMS").read_bytes()
            ).hexdigest(),
        }
        if dict(declared) != expected:
            raise SeasonalPreparationError("SEASONAL_MANIFEST_INVALID")
    rows = _root_summary_rows(result)
    try:
        validate_summary_csv(contents["seasonal_prep_summary.csv"], rows)
        validate_report_markdown(
            contents["seasonal_prep_report.md"],
            rows,
            status=result.status,
            config_sha256=result.config_sha256,
            code_commit=result.code_commit,
        )
    except SeasonalReportingError as exc:
        raise SeasonalPreparationError("SEASONAL_REPORT_INVALID") from exc
    expected_roots = _root_payloads(result)
    if any(contents[name] != expected_roots[name] for name in ROOT_PAYLOAD_NAMES):
        raise SeasonalPreparationError("SEASONAL_MANIFEST_INVALID")


def load_verified_seasonal_release(
    output_root: str | Path,
) -> SeasonalPreparationResult:
    """Strictly load and cross-check the exact deterministic 37-file release."""

    root = Path(output_root)
    if release_paths(root) != expected_seasonal_release_paths() or _is_reparse(root):
        raise SeasonalPreparationError("PUBLIC_LAYOUT_INVALID")
    children = tuple(root.iterdir())
    expected_children = {*SEASONAL_MONTHS, *ROOT_RELEASE_NAMES}
    if {child.name for child in children} != expected_children:
        raise SeasonalPreparationError("PUBLIC_LAYOUT_INVALID")
    for child in children:
        if _is_reparse(child):
            raise SeasonalPreparationError("PUBLIC_LAYOUT_INVALID")
        if child.name in SEASONAL_MONTHS and not child.is_dir():
            raise SeasonalPreparationError("PUBLIC_LAYOUT_INVALID")
        if child.name in ROOT_RELEASE_NAMES and not child.is_file():
            raise SeasonalPreparationError("PUBLIC_LAYOUT_INVALID")
    months = tuple(
        load_verified_month_release(root / month, config=jpl_month_config(month))
        for month in SEASONAL_MONTHS
    )
    result = _seasonal_result(months)
    root_contents = {name: (root / name).read_bytes() for name in ROOT_RELEASE_NAMES}
    checksum_names = (
        *ROOT_PAYLOAD_NAMES,
        *(f"{month}/{name}" for month in SEASONAL_MONTHS for name in MONTH_RELEASE_NAMES),
    )
    declared = _parse_checksums(root_contents["SHA256SUMS"], expected_names=checksum_names)
    for name in checksum_names:
        if declared[name] != hashlib.sha256((root / PurePosixPath(name)).read_bytes()).hexdigest():
            raise SeasonalPreparationError("PUBLIC_HASH_INVALID")
    _validate_root_documents(root, result, root_contents)
    return result


def verify_seasonal_release(output_root: str | Path) -> bool:
    """Return whether a release is exact, private-safe, canonical, and hash-bound."""

    try:
        load_verified_seasonal_release(output_root)
    except (OSError, SeasonalPreparationError, TypeError, ValueError):
        return False
    return True


def _guard_destination(destination: Path, protected_roots: Sequence[str | Path]) -> Path:
    resolved = destination.resolve(strict=False)
    for raw in protected_roots:
        protected = Path(raw).resolve(strict=False)
        if resolved == protected or protected in resolved.parents or resolved in protected.parents:
            raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")
    if destination.exists() and _is_reparse(destination):
        raise SeasonalPreparationError("PUBLIC_LAYOUT_INVALID")
    return resolved


def _write_staged_tree(staging: Path, contents: Mapping[str, bytes]) -> None:
    for relative in expected_seasonal_release_paths():
        content = contents.get(relative)
        if type(content) is not bytes:
            raise SeasonalPreparationError("PUBLIC_SCHEMA_INVALID")
        path = staging / PurePosixPath(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())


def _safe_remove_generated(path: Path, *, parent: Path) -> None:
    resolved = path.resolve(strict=False)
    if resolved.parent != parent.resolve(strict=False) or not resolved.name.startswith("."):
        raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")
    if resolved.exists():
        shutil.rmtree(resolved)


def _retry_remove_generated(path: Path, *, parent: Path) -> bool:
    """Best-effort removal used only after the prior destination is safe."""

    for _attempt in range(2):
        try:
            _safe_remove_generated(path, parent=parent)
        except (OSError, SeasonalPreparationError):  # restore has priority
            if not path.exists():
                return True
        else:
            return not path.exists()
    return not path.exists()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        name: (root / PurePosixPath(name)).read_bytes()
        for name in expected_seasonal_release_paths()
    }


def _existing_month_only_compatible(root: Path, target: Mapping[str, bytes]) -> bool:
    if not root.exists():
        return True
    if not root.is_dir() or _is_reparse(root):
        return False
    children = tuple(root.iterdir())
    if not children:
        return True
    if any(child.name not in SEASONAL_MONTHS or not child.is_dir() for child in children):
        return False
    for child in children:
        try:
            load_verified_month_release(child, config=jpl_month_config(child.name))
        except (OSError, SeasonalPreparationError, TypeError, ValueError):
            return False
        for name in MONTH_RELEASE_NAMES:
            if (child / name).read_bytes() != target[f"{child.name}/{name}"]:
                return False
    return True


def publish_seasonal_release(
    results: Sequence[MonthPreparationResult],
    output_root: str | Path,
    *,
    protected_roots: Sequence[str | Path] = (),
) -> SeasonalPreparationResult:
    """Atomically publish one exact three-month aggregate-only release."""

    result = _seasonal_result(results)
    contents = _release_bytes(result)
    destination = _guard_destination(Path(output_root), protected_roots)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and verify_seasonal_release(destination):
        if _tree_bytes(destination) == contents:
            return result
        raise SeasonalPreparationError("PUBLIC_ROLLBACK_REJECTED")
    if not _existing_month_only_compatible(destination, contents):
        raise SeasonalPreparationError("PUBLIC_EXISTING_STATE_INVALID")
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    backup: Path | None = None
    old_moved = False
    tree_installed = False
    committed = False
    try:
        _write_staged_tree(staging, contents)
        if not verify_seasonal_release(staging):
            raise SeasonalPreparationError("PUBLIC_STAGING_INVALID")
        if destination.exists():
            backup = destination.with_name(f".{destination.name}.backup-{os.getpid()}")
            _safe_remove_generated(backup, parent=destination.parent)
            os.replace(destination, backup)
            old_moved = True
        os.replace(staging, destination)
        tree_installed = True
        if not verify_seasonal_release(destination):
            raise SeasonalPreparationError("PUBLIC_INSTALL_INVALID")
        committed = True
        if backup is not None:
            _safe_remove_generated(backup, parent=destination.parent)
            # The verified destination was committed before backup cleanup.
    except BaseException:
        if committed:
            backup_cleaned = backup is None or _retry_remove_generated(
                backup,
                parent=destination.parent,
            )
            staging_cleaned = _retry_remove_generated(
                staging,
                parent=destination.parent,
            )
            if not verify_seasonal_release(destination):
                raise SeasonalPreparationError("PUBLIC_COMMITTED_TREE_INVALID") from None
            if not backup_cleaned or not staging_cleaned:
                raise SeasonalPreparationError("PUBLIC_COMMITTED_CLEANUP_FAILED") from None
            return result
        displaced_installed_tree = not tree_installed or not destination.exists()
        if tree_installed and destination.exists():
            try:
                os.replace(destination, staging)
                displaced_installed_tree = True
            except OSError:
                displaced_installed_tree = False
        restored = not old_moved and displaced_installed_tree
        if old_moved and backup is not None and backup.exists():
            try:
                if displaced_installed_tree:
                    os.replace(backup, destination)
                    restored = True
            except OSError:
                restored = False
        cleaned = _retry_remove_generated(staging, parent=destination.parent)
        if not restored or not cleaned or (backup is not None and backup.exists()):
            raise SeasonalPreparationError("PUBLIC_ROLLBACK_FAILED") from None
        raise
    return result


def publish_month_release(
    result: MonthPreparationResult,
    output_root: str | Path,
    *,
    protected_roots: Sequence[str | Path] = (),
) -> None:
    """Atomically add one fixed month while preserving completed month bytes."""

    _validate_month_result(result)
    root = _guard_destination(Path(output_root), protected_roots)
    root.parent.mkdir(parents=True, exist_ok=True)
    if root.exists() and (not root.is_dir() or _is_reparse(root)):
        raise SeasonalPreparationError("PUBLIC_EXISTING_STATE_INVALID")
    root.mkdir(parents=True, exist_ok=True)
    contents = _month_release_bytes(result)
    destination = root / result.month
    children = tuple(root.iterdir())
    if any(child.name in ROOT_RELEASE_NAMES for child in children):
        if not verify_seasonal_release(root):
            raise SeasonalPreparationError("PUBLIC_EXISTING_STATE_INVALID")
    elif any(child.name not in SEASONAL_MONTHS or not child.is_dir() for child in children):
        raise SeasonalPreparationError("PUBLIC_EXISTING_STATE_INVALID")
    if destination.exists():
        existing = load_verified_month_release(destination, config=jpl_month_config(result.month))
        if _month_release_bytes(existing) == contents:
            return
        raise SeasonalPreparationError("PUBLIC_ROLLBACK_REJECTED")
    staging = Path(tempfile.mkdtemp(prefix=f".{result.month}.staging-", dir=root))
    try:
        for name in MONTH_RELEASE_NAMES:
            with (staging / name).open("xb") as handle:
                handle.write(contents[name])
                handle.flush()
                os.fsync(handle.fileno())
        load_verified_month_release(staging, config=jpl_month_config(result.month))
        os.replace(staging, destination)
    except BaseException:
        if staging.exists():
            _safe_remove_generated(staging, parent=root)
        raise


def publish_seasonal_root(
    results: Sequence[MonthPreparationResult],
    output_root: str | Path,
    *,
    protected_roots: Sequence[str | Path] = (),
) -> SeasonalPreparationResult:
    """Atomically close three already-published months with root evidence."""

    return publish_seasonal_release(
        results,
        output_root,
        protected_roots=protected_roots,
    )


def _topology(
    raw_root: Path,
    destinations: Sequence[Path],
) -> tuple[Path, ...]:
    raw = raw_root.resolve(strict=True)
    resolved = tuple(path.resolve(strict=False) for path in destinations)
    all_paths = (raw, *resolved)
    for index, left in enumerate(all_paths):
        for right in all_paths[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")
    if raw_root.is_symlink() or any(path.exists() and _is_reparse(path) for path in destinations):
        raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")
    return resolved


def _preparation_root_topology(
    metadata_root: Path,
    raw_root: Path,
    destinations: Sequence[Path],
) -> tuple[Path, Path, tuple[Path, ...]]:
    """Resolve protected/source/output roots and reject destructive overlap."""

    try:
        metadata = metadata_root.resolve(strict=True)
        raw = raw_root.resolve(strict=True)
        resolved_destinations = tuple(path.resolve(strict=False) for path in destinations)
    except (OSError, RuntimeError) as exc:
        raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID") from exc
    originals = (metadata_root, raw_root, *destinations)
    resolved = (metadata, raw, *resolved_destinations)
    if not metadata.is_dir() or not raw.is_dir():
        raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")
    if any(path.exists() and _is_reparse(path) for path in originals):
        raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")
    for index, left in enumerate(resolved):
        for right in resolved[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")
    return metadata, raw, resolved_destinations


def _gzip_jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    target = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    _plain_json_value(row),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                + b"\n"
            )
    return target.getvalue()


def _plain_json_value(value: object) -> object:
    """Recursively thaw immutable producer containers for canonical JSON."""

    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise SeasonalPreparationError("PUBLIC_SCHEMA_INVALID")
        return {key: _plain_json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json_value(item) for item in value]
    return value


def _npy_bytes(value: object) -> bytes:
    import numpy as np

    target = io.BytesIO()
    np.save(target, np.asarray(value), allow_pickle=False)
    return target.getvalue()


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_local_roots(
    pairs: Sequence[tuple[Path, Path]],
) -> None:
    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for staging, destination in pairs:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if _is_reparse(destination):
                    raise SeasonalPreparationError("OUTPUT_TOPOLOGY_INVALID")
                backup = destination.with_name(f".{destination.name}.backup-{os.getpid()}")
                _safe_remove_generated(backup, parent=destination.parent)
                os.replace(destination, backup)
                backups.append((backup, destination))
            os.replace(staging, destination)
            installed.append(destination)
    except BaseException:
        for destination in reversed(installed):
            if destination.exists():
                temporary = destination.with_name(f".{destination.name}.failed-{os.getpid()}")
                os.replace(destination, temporary)
                _safe_remove_generated(temporary, parent=destination.parent)
        for backup, destination in reversed(backups):
            if backup.exists() and not destination.exists():
                os.replace(backup, destination)
        raise
    for backup, _destination in backups:
        _safe_remove_generated(backup, parent=backup.parent)


def _materialize_local_artifacts(
    *,
    month: str,
    cleaned_sessions: Sequence[object],
    cleaning_policy: object,
    source_inventory_sha256: str,
    station_rows: Sequence[Mapping[str, Any]],
    snapshots: object,
    blocks: Mapping[str, object],
    interim_root: Path,
    processed_root: Path,
    raw_root: Path,
    data_snapshot_sha256: str,
) -> tuple[str, int]:
    from .acn_jpl_cleaning import write_cleaned_sessions

    interim_parent = interim_root.parent
    processed_parent = processed_root.parent
    interim_parent.mkdir(parents=True, exist_ok=True)
    processed_parent.mkdir(parents=True, exist_ok=True)
    interim_stage = Path(tempfile.mkdtemp(prefix=f".{month}.interim-", dir=interim_parent))
    processed_stage = Path(tempfile.mkdtemp(prefix=f".{month}.processed-", dir=processed_parent))
    try:
        cleaned_store = write_cleaned_sessions(
            cleaned_sessions,
            interim_stage / "cleaned_sessions.jsonl.gz",
            policy=cleaning_policy,
            source_inventory_sha256=source_inventory_sha256,
        )
        processed_payloads: dict[str, bytes] = {
            "station_15min.jsonl.gz": _gzip_jsonl_bytes(station_rows),
            "m1.jsonl.gz": _gzip_jsonl_bytes(snapshots.m1_rows),
            "m2.jsonl.gz": _gzip_jsonl_bytes(snapshots.m2_rows),
            "m3.jsonl.gz": _gzip_jsonl_bytes(snapshots.m3_rows),
            "labels.jsonl.gz": _gzip_jsonl_bytes(snapshots.label_rows),
        }
        for tier in _TIERS:
            block = blocks[tier]
            processed_payloads[f"{tier}.values.npy"] = _npy_bytes(block.values)
            processed_payloads[f"{tier}.issue_times.npy"] = _npy_bytes(block.issue_times)
            processed_payloads[f"{tier}.nullable_mask.npy"] = _npy_bytes(block.nullable_mask)
        for name, content in processed_payloads.items():
            _write_bytes(processed_stage / name, content)
        local_entries = [
            {
                "name": "interim/cleaned_sessions.jsonl.gz",
                "sha256": cleaned_store.sha256,
                "size": cleaned_store.data_path.stat().st_size,
            },
            {
                "name": "interim/cleaned_sessions.jsonl.gz.manifest.json",
                "sha256": hashlib.sha256(cleaned_store.manifest_path.read_bytes()).hexdigest(),
                "size": cleaned_store.manifest_path.stat().st_size,
            },
        ]
        local_entries.extend(
            {
                "name": f"processed/{name}",
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
            for name, content in sorted(processed_payloads.items())
        )
        local_manifest = {
            "schema_version": "acn-jpl-seasonal-local-snapshot/v1",
            "month": month,
            "source_inventory_sha256": source_inventory_sha256,
            "data_snapshot_sha256": data_snapshot_sha256,
            "artifacts": local_entries,
            "tiers": list(_TIERS),
        }
        manifest_bytes = _json_bytes(local_manifest)
        processed_snapshot_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        _write_bytes(processed_stage / "data_snapshot_manifest.json", manifest_bytes)
        # Verify every staged byte before either destination can be replaced.
        for entry in local_entries:
            prefix, relative = str(entry["name"]).split("/", 1)
            base = interim_stage if prefix == "interim" else processed_stage
            path = base / relative
            if (
                not path.is_file()
                or _is_reparse(path)
                or path.stat().st_size != entry["size"]
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
            ):
                raise SeasonalPreparationError("LOCAL_ARTIFACT_INVALID")
        _replace_local_roots(
            (
                (interim_stage, interim_root),
                (processed_stage, processed_root),
            )
        )
        return processed_snapshot_sha256, len(local_entries)
    except BaseException:
        for staging, parent in (
            (interim_stage, interim_parent),
            (processed_stage, processed_parent),
        ):
            if staging.exists():
                _safe_remove_generated(staging, parent=parent)
        raise


def _mapping(value: object, reason: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SeasonalPreparationError(reason)
    return value


def _canonicalize_compact_rates(documents: Mapping[str, object]) -> dict[str, object]:
    """Copy rounded producer rates into exact count-based seasonal report rates.

    Only the exact ratio and the frozen producer's eight-decimal representation
    are accepted. A contradictory rate must still fail before publication.
    """

    def count_rate(
        value: object,
        count: object,
        denominator: int,
        context: str,
        *,
        missing: bool = False,
    ) -> float:
        numerator = _integer(count, f"{context}_COUNT")
        if numerator > denominator:
            raise SeasonalPreparationError(f"{context}_COUNT_INVALID")
        exact = numerator / denominator
        if missing:
            exact = 1.0 - exact
        if _number(value, context) not in (exact, round(exact, 8)):
            raise SeasonalPreparationError(f"{context}_INVALID")
        return exact

    canonical = dict(documents)
    cleaning = dict(_mapping(documents["cleaning_qa.json"], "CLEANING_QA_INVALID"))
    quarantine = dict(_mapping(cleaning["trajectory_quarantine"], "TRAJECTORY_QUARANTINE_INVALID"))
    combined = _integer(cleaning["sessions_processed"], "COMBINED_SESSION_COUNT", positive=True)
    for coverage_name in ("raw_field_coverage", "analysis_field_coverage"):
        coverage = _exact(quarantine[coverage_name], ("current", "pilot"), "QUARANTINE_FIELD_COVERAGE")
        normalized: dict[str, object] = {}
        for field_name in ("current", "pilot"):
            item = _exact(coverage[field_name], ("count", "denominator", "rate"), "FIELD_COVERAGE")
            denominator = _integer(item["denominator"], "FIELD_COVERAGE_DENOMINATOR", positive=True)
            if denominator != combined:
                raise SeasonalPreparationError("QUARANTINE_FIELD_COVERAGE_DENOMINATOR_INVALID")
            normalized[field_name] = {
                **item,
                "rate": count_rate(item["rate"], item["count"], denominator, "FIELD_COVERAGE_RATE"),
            }
        quarantine[coverage_name] = normalized
    cleaning["trajectory_quarantine"] = quarantine
    canonical["cleaning_qa.json"] = cleaning

    station = dict(_mapping(documents["station_15min_qa.json"], "STATION_QA_INVALID"))
    bins = _integer(station["expected_bins"], "EXPECTED_BINS", positive=True)
    for threshold in (80, 90, 95):
        count = station[f"valid_bins_at_{threshold}"]
        for name, missing in (("valid_bin_rate", False), ("missing_bin_rate", True)):
            key = f"{name}_at_{threshold}"
            station[key] = count_rate(station[key], count, bins, name.upper(), missing=missing)
    canonical["station_15min_qa.json"] = station
    return canonical


def _compact_month_documents(
    *,
    config: JPLMonthConfig,
    protocol: SeasonalPreparationProtocol,
    scope: object,
    acquisition: object,
    acquisition_qa: Mapping[str, Any],
    cleaning_qa: Mapping[str, Any],
    cleaning_sensitivity: Mapping[str, Any],
    boundary_audit: Mapping[str, Any],
    power_audit: Mapping[str, Any],
    station_qa: Mapping[str, Any],
    issue_qa: Mapping[str, Any],
    blocks: Mapping[str, object],
    invalid_skipped_session_count: int,
    processed_snapshot_sha256: str,
    local_artifact_count: int,
    official_reference_sha256: str,
    code_commit: str,
) -> dict[str, object]:
    evidence = getattr(scope, "source_evidence", None)
    metadata_source = getattr(evidence, "source_inventory_sha256", None)
    metadata_record = getattr(scope, "record_inventory_sha256", None)
    _digest(metadata_source, "METADATA_SOURCE_INVENTORY")
    _digest(metadata_record, "METADATA_RECORD_INVENTORY")
    raw_inventory = _digest(getattr(acquisition, "raw_inventory_sha256", None), "RAW_INVENTORY")
    _digest(processed_snapshot_sha256, "PROCESSED_SNAPSHOT")
    _digest(official_reference_sha256, "OFFICIAL_REFERENCE")
    quality = _mapping(acquisition_qa.get("quality"), "ACQUISITION_QA_INVALID")
    acquisition_integrity = _mapping(acquisition_qa.get("integrity"), "ACQUISITION_QA_INVALID")
    daily_integrity = _mapping(acquisition_integrity.get("daily_chunks"), "ACQUISITION_QA_INVALID")
    combined_integrity = _mapping(acquisition_integrity.get("combined"), "ACQUISITION_QA_INVALID")
    series = _mapping(quality.get("series"), "ACQUISITION_QA_INVALID")
    current_quality = _mapping(series.get("chargingCurrent"), "ACQUISITION_QA_INVALID")
    pilot_quality = _mapping(series.get("pilotSignal"), "ACQUISITION_QA_INVALID")
    quarantine = _mapping(
        acquisition_qa.get("trajectory_quarantine"),
        "TRAJECTORY_QUARANTINE_INVALID",
    )
    trajectory_count = _integer(
        quarantine.get("trajectory_quarantine_count"),
        "TRAJECTORY_QUARANTINE_COUNT",
    )
    full_count = _integer(
        quarantine.get("full_session_quarantine_count"),
        "FULL_SESSION_QUARANTINE_COUNT",
    )
    current_invalid = _integer(
        current_quality.get("invalid_container_count"), "CURRENT_INVALID_CONTAINERS"
    )
    pilot_invalid = _integer(
        pilot_quality.get("invalid_container_count"), "PILOT_INVALID_CONTAINERS"
    )
    combined = _integer(
        getattr(acquisition, "combined_record_count", None),
        "COMBINED_SESSION_COUNT",
        positive=True,
    )
    sampling = _mapping(cleaning_qa.get("sampling_interval"), "CLEANING_QA_INVALID")
    duplicate = _mapping(cleaning_qa.get("duplicate_policy"), "CLEANING_QA_INVALID")
    current_clean = _mapping(cleaning_qa.get("current"), "CLEANING_QA_INVALID")
    pilot_clean = _mapping(cleaning_qa.get("pilot"), "CLEANING_QA_INVALID")
    user_inputs = _mapping(cleaning_qa.get("user_inputs"), "CLEANING_QA_INVALID")
    main_holds = _mapping(cleaning_sensitivity.get("main_hold_seconds"), "CLEANING_QA_INVALID")
    hold_thresholds = _mapping(
        cleaning_sensitivity.get("hold_thresholds_seconds"),
        "CLEANING_QA_INVALID",
    )
    valid_90 = _integer(station_qa.get("valid_bins_at_90"), "VALID_BIN_90")
    scheduled = _integer(issue_qa.get("issue_times"), "SCHEDULED_ISSUE_TIMES", positive=True)
    formal = _integer(issue_qa.get("formal_issue_times"), "FORMAL_ISSUE_TIMES")
    power_evidence = _mapping(power_audit.get("evidence"), "POWER_AUDIT_INVALID")
    power_mapping = _mapping(power_audit.get("mapping"), "POWER_AUDIT_INVALID")
    power_cohorts = _mapping(power_audit.get("cohorts"), "POWER_AUDIT_INVALID")
    power_primary = _mapping(power_cohorts.get("primary"), "POWER_AUDIT_INVALID")
    power_voltage = _mapping(power_primary.get("effective_voltage_v"), "POWER_AUDIT_INVALID")
    power_error = _mapping(power_primary.get("e208_error"), "POWER_AUDIT_INVALID")
    power_energy = _mapping(power_primary.get("aggregate_energy"), "POWER_AUDIT_INVALID")
    power_decision = _mapping(power_audit.get("decision"), "POWER_AUDIT_INVALID")
    power_conditions = _mapping(power_decision.get("conditions"), "POWER_AUDIT_INVALID")
    raw_dimensions = tuple(int(blocks[tier].values.shape[1]) for tier in _TIERS)
    encoded_dimensions = tuple(
        int(blocks[tier].values.shape[1]) + int(blocks[tier].nullable_mask.sum()) for tier in _TIERS
    )
    if raw_dimensions != _RAW_DIMENSIONS or encoded_dimensions != _ENCODED_DIMENSIONS:
        raise SeasonalPreparationError("FEATURE_DIMENSION_INVALID")
    power_status = power_audit.get("status")
    run_status = (
        "PASS_WITH_TRAJECTORY_QUARANTINE"
        if trajectory_count
        else (
            "PASS"
            if power_status == "KW_RECONSTRUCTION_CANDIDATE"
            else "CONDITIONAL_PASS"
        )
    )
    acquisition_document = {
        "schema_version": "acn-jpl-seasonal-acquisition-summary/v1",
        "month": config.month,
        "status": getattr(acquisition, "status", None),
        "official_total": getattr(acquisition, "official_total", None),
        "local_session_count": getattr(acquisition, "local_session_count", None),
        "carry_in_count": getattr(acquisition, "carry_in_count", None),
        "combined_session_count": combined,
        "trajectory_quarantine_count": trajectory_count,
        "trajectory_quarantine_rate": quarantine.get("trajectory_quarantine_rate"),
        "full_session_quarantine_count": full_count,
        "metadata_scope": {
            "local_calendar_session_count": getattr(scope, "local_month_session_count", None),
            "utc_calendar_session_count": getattr(scope, "utc_month_session_count", None),
            "left_boundary_count": getattr(scope, "left_boundary_count", None),
            "right_boundary_count": getattr(scope, "right_boundary_count", None),
            "carry_in_count": getattr(scope, "carry_in_session_count", None),
        },
        "official_probe": {
            "request_count": 1,
            "timeseries": False,
            "total_matches_local": True,
            "reference_valid": True,
        },
        "chunk_integrity": {
            "daily_expected": daily_integrity.get("expected"),
            "daily_data_files_present": daily_integrity.get("data_files_present"),
            "daily_manifests_present": daily_integrity.get("manifests_present"),
            "daily_manifest_contracts_valid": daily_integrity.get("manifest_contracts_valid"),
            "daily_sha256_verified": daily_integrity.get("sha256_verified"),
            "daily_json_valid": daily_integrity.get("gzip_json_valid"),
            "daily_record_manifest_matches": daily_integrity.get("record_manifest_matches"),
            "daily_record_remote_matches": daily_integrity.get("record_remote_matches"),
            "daily_valid": daily_integrity.get("valid"),
            "carry_expected": getattr(acquisition, "carry_in_count", None),
            "carry_completed": getattr(acquisition, "carry_in_completed", None),
            "carry_manifest_sha_json_valid": True,
        },
        "linkage": {
            "daily_record_count": getattr(acquisition, "daily_record_count", None),
            "daily_unique_object_count": getattr(acquisition, "daily_unique_object_count", None),
            "daily_unique_session_count": getattr(acquisition, "daily_unique_session_count", None),
            "daily_unique_pair_count": getattr(acquisition, "daily_unique_pair_count", None),
            "combined_record_count": getattr(acquisition, "combined_record_count", None),
            "combined_unique_object_count": getattr(
                acquisition, "combined_unique_object_count", None
            ),
            "combined_unique_session_count": getattr(
                acquisition, "combined_unique_session_count", None
            ),
            "combined_unique_pair_count": getattr(acquisition, "combined_unique_pair_count", None),
            "matched_metadata_pairs": combined_integrity.get("matched_metadata_pairs"),
            "missing_metadata_pairs": combined_integrity.get("missing_metadata_pairs"),
            "orphan_timeseries_pairs": combined_integrity.get("orphan_timeseries_pairs"),
        },
        "valid_daily_chunks": getattr(acquisition, "valid_daily_chunks", None),
        "expected_daily_chunks": config.day_count,
        "metadata_source_inventory_sha256": metadata_source,
        "metadata_record_inventory_sha256": metadata_record,
        "official_reference_sha256": official_reference_sha256,
        "raw_file_count": getattr(acquisition, "raw_file_count", None),
        "raw_inventory_sha256": raw_inventory,
        "raw_inventory_before_sha256": raw_inventory,
        "raw_inventory_after_sha256": raw_inventory,
        "partial_file_count": getattr(acquisition, "partial_file_count", None),
        "integrity": {
            "scope_verified": True,
            "official_reference_verified": True,
            "raw_snapshot_valid": True,
            "raw_unchanged": True,
            "linkage_exact": True,
            "partial_files_absent": True,
        },
    }
    cleaning_document = {
        "schema_version": "acn-jpl-seasonal-preparation-cleaning-qa/v1",
        "month": config.month,
        "status": cleaning_qa.get("status"),
        "sessions_processed": combined,
        "expected_sessions": combined,
        "cleaned_session_count": cleaning_qa.get("sessions_processed"),
        "invalid_skipped_session_count": invalid_skipped_session_count,
        "trajectory_quarantine": {
            **dict(quarantine),
            "raw_field_coverage": {
                "current": current_quality.get("raw_field_coverage"),
                "pilot": pilot_quality.get("raw_field_coverage"),
            },
            "analysis_field_coverage": {
                "current": current_quality.get("analysis_field_coverage"),
                "pilot": pilot_quality.get("analysis_field_coverage"),
            },
        },
        "analysis_window": {
            "timezone": config.timezone_name,
            "local_start_inclusive": config.local_start.isoformat(),
            "local_end_exclusive": config.local_end.isoformat(),
            "utc_start_inclusive": config.utc_start.isoformat(),
            "utc_end_exclusive": config.utc_end.isoformat(),
        },
        "sampling": {
            "derivation": sampling.get("derivation"),
            "current_mode_seconds": sampling.get("current_mode_seconds"),
            "pilot_mode_seconds": sampling.get("pilot_mode_seconds"),
            "current_hold_seconds": sampling.get("main_current_hold_seconds"),
            "pilot_hold_seconds": sampling.get("main_pilot_hold_seconds"),
            "mode_multiplier": protocol.locf_mode_multiplier,
            "cap_seconds": protocol.locf_cap_seconds,
        },
        "invalid_containers": {
            "denominator": combined,
            "charging_current": {
                "count": current_invalid,
                "rate": current_invalid / combined,
                "limit": 0.10,
                "status": "PASS" if current_invalid / combined <= 0.10 else "FAIL",
            },
            "pilot_signal": {
                "count": pilot_invalid,
                "rate": pilot_invalid / combined,
                "limit": 0.10,
                "status": "PASS" if pilot_invalid / combined <= 0.10 else "FAIL",
            },
        },
        "duplicate_conflict": {
            "exact_duplicate_policy": duplicate.get("exact"),
            "conflict_main_policy": duplicate.get("conflict_main"),
            "conflict_sensitivity_policy": duplicate.get("conflict_sensitivity"),
            "current_conflicting_timestamps": current_clean.get("conflicting_timestamps"),
            "pilot_conflicting_timestamps": pilot_clean.get("conflicting_timestamps"),
        },
        "series": {
            "current": {
                "raw_samples": current_clean.get("raw_samples"),
                "usable_samples": current_quality.get("usable_samples"),
                "retained_samples": current_clean.get("retained_samples"),
                "retained_sample_rate": current_clean.get("retained_sample_rate"),
                "invalid_timestamps": current_clean.get("invalid_timestamps"),
                "invalid_values": current_clean.get("invalid_values"),
                "exact_duplicate_extras": current_clean.get("exact_duplicate_extras"),
                "conflicting_timestamps": current_clean.get("conflicting_timestamps"),
                "conflict_affected_sessions": current_clean.get("conflict_affected_sessions"),
                "nonmonotonic_pairs": current_quality.get("nonmonotonic_pairs"),
                "nonmonotonic_sessions": current_quality.get(
                    "nonmonotonic_affected_sessions",
                    current_quality.get("nonmonotonic_sessions"),
                ),
                "bounded_observation_coverage": current_clean.get("bounded_observation_coverage"),
                "bounded_value_hours": current_clean.get("bounded_value_hours"),
            },
            "pilot": {
                "raw_samples": pilot_clean.get("raw_samples"),
                "usable_samples": pilot_quality.get("usable_samples"),
                "retained_samples": pilot_clean.get("retained_samples"),
                "retained_sample_rate": pilot_clean.get("retained_sample_rate"),
                "invalid_timestamps": pilot_clean.get("invalid_timestamps"),
                "invalid_values": pilot_clean.get("invalid_values"),
                "exact_duplicate_extras": pilot_clean.get("exact_duplicate_extras"),
                "conflicting_timestamps": pilot_clean.get("conflicting_timestamps"),
                "conflict_affected_sessions": pilot_clean.get("conflict_affected_sessions"),
                "nonmonotonic_pairs": pilot_quality.get("nonmonotonic_pairs"),
                "nonmonotonic_sessions": pilot_quality.get(
                    "nonmonotonic_affected_sessions",
                    pilot_quality.get("nonmonotonic_sessions"),
                ),
                "bounded_observation_coverage": pilot_clean.get("bounded_observation_coverage"),
                "bounded_value_hours": pilot_clean.get("bounded_value_hours"),
            },
        },
        "user_inputs": {
            "raw_revision_count": user_inputs.get("raw_revision_count"),
            "sanitized_revision_count": user_inputs.get("sanitized_revision_count"),
            "unparseable_modified_count": user_inputs.get("unparseable_modified_count"),
            "issue_time_truncation_ready": user_inputs.get("issue_time_truncation_ready"),
        },
        "retrospective_done_time": cleaning_qa.get("retrospective_done_time"),
        "raw_modified": cleaning_qa.get("raw_modified"),
    }
    sensitivity_document = {
        "schema_version": ("acn-jpl-seasonal-preparation-cleaning-sensitivity/v1"),
        "month": config.month,
        "status": "PASS",
        "main_hold_seconds": {
            "current": main_holds.get("current"),
            "pilot": main_holds.get("pilot"),
        },
        "hold_thresholds_seconds": {
            "current": hold_thresholds.get("current"),
            "pilot": hold_thresholds.get("pilot"),
        },
        "hold_thresholds": cleaning_sensitivity.get("hold_thresholds"),
        "last_write_wins": cleaning_sensitivity.get("last_write_wins"),
        "boundary_plus_minus_60_seconds": cleaning_sensitivity.get(
            "boundary_plus_minus_60_seconds"
        ),
        "boundary_sensitivity_seconds": protocol.boundary_sensitivity_seconds,
        "last_write_wins_compared": True,
    }
    boundary_document = {
        "schema_version": "acn-jpl-seasonal-preparation-boundary-audit/v1",
        "month": config.month,
        "status": boundary_audit.get("status"),
        "positive_points_excluded": boundary_audit.get("positive_points_excluded"),
        "sessions_affected": boundary_audit.get("sessions_affected"),
        "signed_distance_seconds": boundary_audit.get("signed_distance_seconds"),
        "before_connection_count": boundary_audit.get("before_connection_count"),
        "at_or_after_disconnect_count": boundary_audit.get("at_or_after_disconnect_count"),
        "excluded_positive_ampere_seconds": boundary_audit.get("excluded_positive_ampere_seconds"),
        "raw_total_ampere_seconds": boundary_audit.get("raw_total_ampere_seconds"),
        "current_integral_share": boundary_audit.get("current_integral_share"),
        "sensitivity_window_seconds": boundary_audit.get("sensitivity_window_seconds"),
        "main_result_excludes_boundary_points": boundary_audit.get(
            "main_result_excludes_boundary_points"
        ),
    }
    power_document = {
        "schema_version": "acn-jpl-seasonal-preparation-power-semantics/v1",
        "month": config.month,
        "status": power_status,
        "legacy_classifier_status": power_audit.get("legacy_classifier_status"),
        "continue_current_pipeline": power_audit.get("continue_current_pipeline"),
        "e208_authorized": power_audit.get("e208_authorized"),
        "reconstructed_kw_column_authorized": False,
        "current_proxy_available": True,
        "pinned_evidence": {
            "repository": power_evidence.get("repository"),
            "commit": power_evidence.get("commit"),
            "source_sha256": power_evidence.get("source_sha256"),
            "default_evse_voltage_v": power_evidence.get("default_evse_voltage_v"),
            "line_to_line_network": power_evidence.get("line_to_line_network"),
            "e208_formula": "E_208_kWh=208*ampere_hours/1000",
        },
        "mapping": {
            "raw_record_count": power_mapping.get("raw_record_count"),
            "mapped_record_count": power_mapping.get("mapped_record_count"),
            "unmapped_record_count": power_mapping.get("unmapped_record_count"),
            "mapping_rate": power_mapping.get("mapping_rate"),
        },
        "primary_cohort": {
            "thresholds": power_primary.get("thresholds"),
            "input_session_count": power_primary.get("input_session_count"),
            "eligible_session_count": power_primary.get("eligible_session_count"),
            "coverage_qualified_session_count": power_primary.get(
                "coverage_qualified_session_count"
            ),
            "retained_session_count": power_primary.get("retained_session_count"),
            "audit_coverage": power_primary.get("audit_coverage"),
            "retained_rate": power_primary.get("retained_rate"),
            "effective_voltage_v": {
                "count": power_voltage.get("count"),
                "q1": power_voltage.get("q1"),
                "median": power_voltage.get("median"),
                "q3": power_voltage.get("q3"),
                "iqr": power_voltage.get("iqr"),
            },
            "e208_error": {
                "count": power_error.get("count"),
                "median_absolute_percentage_error": power_error.get(
                    "median_absolute_percentage_error"
                ),
                "p90_absolute_percentage_error": power_error.get("p90_absolute_percentage_error"),
            },
            "aggregate_energy": {
                "session_count": power_energy.get("session_count"),
                "observed_kwh": power_energy.get("observed_kwh"),
                "e208_kwh": power_energy.get("e208_kwh"),
                "error_kwh": power_energy.get("error_kwh"),
                "relative_error": power_energy.get("relative_error"),
                "absolute_relative_error": power_energy.get("absolute_relative_error"),
            },
        },
        "statistics_finite": power_conditions.get("statistics_finite"),
        "privacy": {"aggregate_only": True, "identifiers_emitted": False},
    }
    station_document = {
        "schema_version": "acn-jpl-seasonal-preparation-station-15min-qa/v1",
        "month": config.month,
        "status": "PASS",
        "grid_policy": station_qa.get("grid_policy"),
        "station_columns": [
            "station_current_mean_a",
            "station_current_peak_a",
            "connected_session_count",
            "active_charging_session_count",
            "pilot_sum_a",
            "pilot_mean_a",
            "arrival_count",
            "disconnect_count",
            "observed_coverage_ratio",
            "valid_bin_80",
            "valid_bin_90",
            "valid_bin_95",
        ],
        "expected_bins": station_qa.get("expected_bins"),
        "generated_bins": station_qa.get("generated_bins"),
        "valid_bins_at_80": station_qa.get("valid_bins_at_80"),
        "valid_bins_at_90": valid_90,
        "valid_bins_at_95": station_qa.get("valid_bins_at_95"),
        "pilot_valid_bins_at_80": station_qa.get("pilot_valid_bins_at_80"),
        "pilot_valid_bins_at_90": station_qa.get("pilot_valid_bins_at_90"),
        "pilot_valid_bins_at_95": station_qa.get("pilot_valid_bins_at_95"),
        "valid_bin_rate_at_80": station_qa.get("valid_bin_rate_at_80"),
        "valid_bin_rate_at_90": station_qa.get("valid_bin_rate_at_90"),
        "valid_bin_rate_at_95": station_qa.get("valid_bin_rate_at_95"),
        "missing_bin_rate_at_80": station_qa.get("missing_bin_rate_at_80"),
        "missing_bin_rate_at_90": station_qa.get("missing_bin_rate_at_90"),
        "missing_bin_rate_at_95": station_qa.get("missing_bin_rate_at_95"),
        "valid_bin_90_rate": valid_90 / config.expected_bins,
        "valid_bin_90_rate_min": protocol.minimum_valid_bin_rate,
        "valid_bin_90_gate": (
            "PASS" if valid_90 / config.expected_bins >= protocol.minimum_valid_bin_rate else "FAIL"
        ),
        "trajectory_quarantine_count": trajectory_count,
        "coverage_denominator_includes_quarantined": quarantine.get(
            "coverage_denominator_includes_quarantined"
        ),
        "missing_bin_rate": 1.0 - valid_90 / config.expected_bins,
        "longest_missing_run": station_qa.get("longest_missing_run"),
        "peak_current_proxy_a": station_qa.get("peak_current_proxy_a"),
        "max_absolute_ramp_a": station_qa.get("max_absolute_ramp_a"),
        "weekday_distribution": station_qa.get("weekday_distribution"),
        "weekend_distribution": station_qa.get("weekend_distribution"),
        "active_threshold_sensitivity": station_qa.get("active_threshold_sensitivity"),
        "aggregation_semantics": {
            "bin_rule": _mapping(station_qa.get("aggregation_semantics"), "STATION_QA_INVALID").get(
                "bin_rule"
            ),
            "missing_is_zero": _mapping(
                station_qa.get("aggregation_semantics"), "STATION_QA_INVALID"
            ).get("missing_is_zero"),
            "power_label_type": _mapping(
                station_qa.get("aggregation_semantics"), "STATION_QA_INVALID"
            ).get("power_label_type"),
        },
        "dst_fold_extra_bins": station_qa.get("dst_fold_extra_bins"),
        "repeated_local_quarter_count": station_qa.get("repeated_local_quarter_count"),
        "time_weighted_integral_status": station_qa.get("time_weighted_integral_status"),
    }
    issue_document = {
        "schema_version": "acn-jpl-seasonal-preparation-issue-snapshot-qa/v1",
        "month": config.month,
        "status": "PASS",
        "tiers": list(_TIERS),
        "lookback_minutes": issue_qa.get("lookback_minutes"),
        "horizons_minutes": issue_qa.get("horizons_minutes"),
        "scheduled_issue_times": scheduled,
        "formal_issue_times": formal,
        "incomplete_label_issue_times": issue_qa.get("incomplete_label_issue_times"),
        "samples": issue_qa.get("samples"),
        "ragged_rows": issue_qa.get("ragged_rows"),
        "valid_labels_by_horizon": issue_qa.get("valid_labels_by_horizon"),
        "shapes": issue_qa.get("shapes"),
        "missing_rates": issue_qa.get("missing_rates"),
        "snapshot_sha256": issue_qa.get("snapshot_sha256"),
        "m4_generated": issue_qa.get("m4_generated"),
        "leakage_status": issue_qa.get("leakage_audit"),
    }
    temporal = _mapping(issue_qa.get("temporal_violations"), "LEAKAGE_QA_INVALID")
    truncation = _mapping(
        issue_qa.get("user_inputs_issue_time_truncation"),
        "LEAKAGE_QA_INVALID",
    )
    whitelist = _mapping(issue_qa.get("feature_whitelist_enforcement"), "LEAKAGE_QA_INVALID")
    leakage_document = {
        "schema_version": "acn-jpl-seasonal-preparation-leakage-audit/v1",
        "month": config.month,
        "status": issue_qa.get("leakage_audit"),
        "identifiers_emitted": False,
        "future_outcome_fields_emitted": False,
        "future_outcome_field_count": len(issue_qa.get("future_fields_found", ())),
        "private_identifier_field_count": 0,
        "unexpected_feature_key_count": len(issue_qa.get("unexpected_feature_keys", ())),
        "temporal_violation_count": temporal.get("total"),
        "late_user_input_rows": temporal.get("late_user_input_rows"),
        "issue_time_user_input_status": truncation.get("status"),
        "connected_user_input_rows": truncation.get("connected_session_rows"),
        "known_user_input_rows": truncation.get("rows_with_known_input"),
        "user_input_rule": truncation.get("rule"),
        "feature_whitelist_status": whitelist.get("status"),
    }
    data_document = {
        "schema_version": "acn-jpl-seasonal-preparation-data-snapshot/v1",
        "month": config.month,
        "status": "PASS",
        "config_sha256": protocol.config_sha256,
        "code_commit": code_commit,
        "metadata_source_inventory_sha256": metadata_source,
        "metadata_record_inventory_sha256": metadata_record,
        "raw_inventory_sha256": raw_inventory,
        "processed_snapshot_sha256": processed_snapshot_sha256,
        "raw_dimensions": list(raw_dimensions),
        "encoded_dimensions": list(encoded_dimensions),
        "local_artifact_count": local_artifact_count,
        "trajectory_quarantine_count": trajectory_count,
        "full_session_quarantine_count": full_count,
        "anonymous_local_indexes_published": False,
        "large_arrays_published": False,
    }
    run_document = {
        "schema_version": "acn-jpl-seasonal-preparation-run/v1",
        "month": config.month,
        "status": run_status,
        "raw_unchanged": True,
        "official_total": getattr(acquisition, "official_total", None),
        "local_session_count": getattr(acquisition, "local_session_count", None),
        "carry_in_count": getattr(acquisition, "carry_in_count", None),
        "sessions_processed": combined,
        "cleaned_session_count": cleaning_qa.get("sessions_processed"),
        "invalid_skipped_session_count": invalid_skipped_session_count,
        "trajectory_quarantine_count": trajectory_count,
        "full_session_quarantine_count": full_count,
        "station_bins": station_qa.get("generated_bins"),
        "valid_bin_90_count": valid_90,
        "scheduled_issue_times": scheduled,
        "formal_issue_times": formal,
        "power_semantics_status": power_status,
        "ready_for_gate1_baseline": True,
        "scope": {"training": False, "network": False, "optimization": False},
        "privacy": {
            "aggregate_only": True,
            "private_values_emitted": False,
            "absolute_paths_emitted": False,
        },
    }
    return _canonicalize_compact_rates({
        "acquisition_summary.json": acquisition_document,
        "cleaning_qa.json": cleaning_document,
        "cleaning_sensitivity.json": sensitivity_document,
        "boundary_current_audit.json": boundary_document,
        "power_semantics_audit.json": power_document,
        "station_15min_qa.json": station_document,
        "issue_snapshot_qa.json": issue_document,
        "leakage_audit.json": leakage_document,
        "data_snapshot_manifest.json": data_document,
        "run_manifest.json": run_document,
    })


def _series_container_valid(record: Mapping[str, Any], field_name: str) -> bool:
    value = record.get(field_name)
    if not isinstance(value, Mapping):
        return False
    timestamps = value.get("timestamps")
    values = value.get("current" if field_name == "chargingCurrent" else "pilot")
    return (
        isinstance(timestamps, list) and isinstance(values, list) and len(timestamps) == len(values)
    )


def _prepare_verified_month(
    *,
    config: JPLMonthConfig,
    protocol: SeasonalPreparationProtocol,
    metadata_root: Path,
    raw_root: Path,
    interim_root: Path,
    processed_root: Path,
    code_commit: str,
) -> MonthPreparationResult:
    from evcf.forecasting.acn_jpl_gate1_data import (
        build_seasonal_gate1_snapshot,
        verified_snapshot_provenance,
    )
    from evcf.forecasting.acn_jpl_gate1_features import (
        build_feature_blocks,
        verified_feature_block_provenance,
    )

    from .acn_jpl_15min import AggregationPolicy, aggregate_station_15min
    from .acn_jpl_cleaning import (
        clean_quarantined_session,
        clean_session,
        cleaning_policy_from_sampling_modes,
        derive_sampling_modes,
    )
    from .acn_jpl_full_month_qa import generate_month_timeseries_qa
    from .acn_jpl_gate1_prep import (
        CleaningAccumulator,
        build_cleaning_qa,
        build_seasonal_cleaning_sensitivity,
        validate_seasonal_cleaning_documents,
    )
    from .acn_jpl_issue_snapshots import SnapshotPolicy, build_issue_snapshots
    from .acn_jpl_month_config import (
        CompleteMetadataScope,
        load_verified_complete_metadata,
    )
    from .acn_jpl_power_semantics import audit_seasonal_power_semantics
    from .acn_jpl_preparation import (
        RawSnapshotContract,
        assert_raw_snapshot_unchanged,
        canonical_seasonal_inventory,
        iter_validated_raw_records,
        validate_raw_snapshot,
    )
    from .acn_jpl_seasonal_acquisition import (
        MonthAcquisitionResult,
        verified_existing_official_reference_sha256,
        verify_existing_jpl_month,
        verify_month_acquisition_result,
    )
    from .acn_jpl_trajectory_quarantine import (
        FULL_SESSION_QUARANTINE,
        NO_QUARANTINE,
        TRAJECTORY_QUARANTINE,
        build_trajectory_quarantine_audit,
        quarantine_record_for_analysis,
    )

    if (
        type(config) is not JPLMonthConfig
        or not is_canonical_jpl_month_config(config)
        or config.month not in SEASONAL_MONTHS
        or config.tiers != _TIERS
    ):
        raise SeasonalPreparationError("MONTH_CONFIG_INVALID")
    raw = raw_root.resolve(strict=True)
    interim, processed = _topology(raw, (interim_root, processed_root))
    scope = load_verified_complete_metadata(metadata_root, config)
    if type(scope) is not CompleteMetadataScope or not verify_complete_metadata_scope(
        scope, config
    ):
        raise SeasonalPreparationError("METADATA_SCOPE_INVALID")
    before = canonical_seasonal_inventory(raw)
    acquisition = verify_existing_jpl_month(
        config=config,
        scope=scope,
        raw_root=raw,
    )
    if type(acquisition) is not MonthAcquisitionResult or not verify_month_acquisition_result(
        acquisition,
        config=config,
        scope=scope,
        inventory=before,
    ):
        raise SeasonalPreparationError("ACQUISITION_INTEGRITY_FAILED")
    full_qa = generate_month_timeseries_qa(
        config=config,
        scope=scope,
        raw_root=raw,
        acquisition_result=acquisition,
    )
    if full_qa.gate_status != "PASS":
        raise SeasonalPreparationError("ACQUISITION_QA_GATE_FAILED")
    acquisition_qa = full_qa.qa

    contract = RawSnapshotContract.for_month(
        config,
        local_record_count=scope.local_month_session_count,
        carry_in_record_count=scope.carry_in_session_count,
        inventory=before,
    )
    validation = validate_raw_snapshot(raw, contract=contract)
    expected_sessions = scope.local_month_session_count + scope.carry_in_session_count
    if validation.total_record_count != expected_sessions:
        raise SeasonalPreparationError("RAW_RECORD_COUNT_INVALID")
    raw_records = tuple(iter_validated_raw_records(raw, contract=contract))
    metadata_by_pair = {
        (str(record["_id"]), str(record["sessionID"])): record
        for record in (*scope.local_month_records, *scope.carry_in_records)
    }
    decisions_by_ordinal = {
        record.ordinal: quarantine_record_for_analysis(
            record.payload,
            expected_metadata=metadata_by_pair.get(
                (record.payload.get("_id"), record.payload.get("sessionID"))
            ),
        )[0]
        for record in raw_records
    }
    quarantine_audit = build_trajectory_quarantine_audit(
        config,
        tuple(
            decision
            for decision in decisions_by_ordinal.values()
            if decision.action != NO_QUARANTINE
        ),
        denominator_sessions=expected_sessions,
    )
    if (
        not quarantine_audit.approved
        or quarantine_audit.full_session_quarantine_count
        or full_qa.gate_status != "PASS"
        or acquisition_qa.get("trajectory_quarantine")
        != quarantine_audit.public_dict()
    ):
        raise SeasonalPreparationError("TRAJECTORY_QUARANTINE_POLICY_FAIL")
    current_invalid_ordinals = {
        record.ordinal
        for record in raw_records
        if not _series_container_valid(record.payload, "chargingCurrent")
    }
    pilot_invalid_ordinals = {
        record.ordinal
        for record in raw_records
        if not _series_container_valid(record.payload, "pilotSignal")
    }
    invalid_ordinals = current_invalid_ordinals | pilot_invalid_ordinals
    if any(
        decisions_by_ordinal[ordinal].action != NO_QUARANTINE
        for ordinal in invalid_ordinals
    ):
        raise SeasonalPreparationError("TRAJECTORY_QUARANTINE_POLICY_FAIL")
    quality_series = _mapping(
        _mapping(acquisition_qa.get("quality"), "ACQUISITION_QA_INVALID").get("series"),
        "ACQUISITION_QA_INVALID",
    )
    if _mapping(quality_series.get("chargingCurrent"), "ACQUISITION_QA_INVALID").get(
        "invalid_container_count"
    ) != len(current_invalid_ordinals) or _mapping(
        quality_series.get("pilotSignal"), "ACQUISITION_QA_INVALID"
    ).get("invalid_container_count") != len(pilot_invalid_ordinals):
        raise SeasonalPreparationError("INVALID_CONTAINER_PARTITION_INVALID")
    if (
        len(current_invalid_ordinals) / expected_sessions > 0.10
        or len(pilot_invalid_ordinals) / expected_sessions > 0.10
    ):
        raise SeasonalPreparationError("INVALID_CONTAINER_RATE_EXCEEDED")
    valid_raw_records = tuple(
        record for record in raw_records if record.ordinal not in invalid_ordinals
    )
    modes = derive_sampling_modes(
        record.payload
        for record in valid_raw_records
        if decisions_by_ordinal[record.ordinal].action == NO_QUARANTINE
    )
    cleaning_policy = cleaning_policy_from_sampling_modes(
        modes,
        locf_mode_multiplier=protocol.locf_mode_multiplier,
        locf_cap_seconds=protocol.locf_cap_seconds,
        boundary_sensitivity_seconds=protocol.boundary_sensitivity_seconds,
    )
    accumulator = CleaningAccumulator(cleaning_policy)
    cleaned = []
    try:
        for raw_record in valid_raw_records:
            decision = decisions_by_ordinal[raw_record.ordinal]
            if decision.action == TRAJECTORY_QUARANTINE:
                item = clean_quarantined_session(
                    raw_record.payload,
                    session_index=len(cleaned),
                    policy=cleaning_policy,
                )
            elif decision.action == FULL_SESSION_QUARANTINE:
                raise SeasonalPreparationError("FULL_SESSION_QUARANTINE_REQUIRED")
            else:
                item = clean_session(
                    raw_record.payload,
                    session_index=len(cleaned),
                    policy=cleaning_policy,
                )
            accumulator.add(item, raw_record.payload)
            cleaned.append(item)
    except Exception as exc:
        raise SeasonalPreparationError("CLEANING_GATE_FAILED") from exc
    analysis_window = {
        "month": config.month,
        "timezone": config.timezone_name,
        "local_start_inclusive": config.local_start.isoformat(),
        "local_end_exclusive": config.local_end.isoformat(),
        "utc_start_inclusive": config.utc_start.isoformat(),
        "utc_end_exclusive": config.utc_end.isoformat(),
    }
    cleaning_qa = build_cleaning_qa(
        accumulator,
        modes=modes,
        expected_sessions=len(cleaned),
        analysis_window=analysis_window,
    )
    sensitivity = build_seasonal_cleaning_sensitivity(accumulator)
    boundary = accumulator.boundary_current_audit()
    validate_seasonal_cleaning_documents(
        cleaning_qa=cleaning_qa,
        cleaning_sensitivity=sensitivity,
        boundary_audit=boundary,
        config=config,
        modes=modes,
        policy=cleaning_policy,
        expected_sessions=len(cleaned),
    )

    power = audit_seasonal_power_semantics(accumulator.power_sessions)
    if power.get("continue_current_pipeline") is not True:
        raise SeasonalPreparationError("POWER_SEMANTICS_GATE_FAILED")
    aggregation_policy = AggregationPolicy(
        max_hold_seconds=cleaning_policy.hold_cap_for("chargingCurrent"),
        pilot_max_hold_seconds=cleaning_policy.hold_cap_for("pilotSignal"),
        main_active_threshold_a=protocol.main_active_threshold_a,
        comparison_active_threshold_a=protocol.comparison_active_threshold_a,
        coverage_thresholds=protocol.coverage_thresholds,
    )
    station = aggregate_station_15min(
        cleaned,
        start_utc=config.utc_start,
        end_utc=config.utc_end,
        policy=aggregation_policy,
        grid_policy=config.grid_policy,
    )
    valid_90 = _integer(station.qa.get("valid_bins_at_90"), "VALID_BIN_90")
    if (
        station.qa.get("session_count") != len(cleaned)
        or station.qa.get("generated_bins") != config.expected_bins
        or station.qa.get("expected_bins") != config.expected_bins
        or valid_90 / config.expected_bins < protocol.minimum_valid_bin_rate
        or station.qa.get("time_weighted_integral_status") != "PASS"
    ):
        raise SeasonalPreparationError("VALID_BIN_90_GATE_FAILED")

    snapshot_policy = SnapshotPolicy(
        lookback_minutes=protocol.lookback_minutes,
        horizons_minutes=protocol.horizons_minutes,
        issue_step_minutes=protocol.issue_step_minutes,
        # Seasonal Gate-1 snapshot semantics deliberately retain the frozen
        # May 12-second history hold. The month-derived current/pilot holds are
        # already applied independently by station aggregation above.
        max_hold_seconds=12,
        active_threshold_a=protocol.main_active_threshold_a,
        tiers=config.tiers,
    )
    snapshots = build_issue_snapshots(
        station.rows,
        cleaned,
        start_utc=config.utc_start,
        end_utc=config.utc_end,
        policy=snapshot_policy,
        preserve_unobserved_trajectory_missingness=True,
    )
    if (
        snapshots.qa.get("issue_times") != config.expected_scheduled_issue_times
        or snapshots.qa.get("formal_issue_times", 0) <= 0
        or snapshots.qa.get("leakage_audit") != "PASS"
        or snapshots.qa.get("m4_generated") is not False
        or snapshots.m4_rows
    ):
        raise SeasonalPreparationError("ISSUE_SNAPSHOT_GATE_FAILED")
    sealed_snapshot = build_seasonal_gate1_snapshot(
        snapshots,
        station.rows,
        config=config,
    )
    snapshot_provenance = verified_snapshot_provenance(sealed_snapshot)
    blocks = build_feature_blocks(sealed_snapshot, tiers=config.tiers)
    if tuple(blocks) != _TIERS:
        raise SeasonalPreparationError("FEATURE_TIER_INVALID")
    for tier in _TIERS:
        verified_feature_block_provenance(
            blocks[tier],
            sealed_snapshot,
            tier=tier,
        )
    processed_snapshot, local_count = _materialize_local_artifacts(
        month=config.month,
        cleaned_sessions=tuple(cleaned),
        cleaning_policy=cleaning_policy,
        source_inventory_sha256=before.digest,
        station_rows=station.rows,
        snapshots=snapshots,
        blocks=blocks,
        interim_root=interim,
        processed_root=processed,
        raw_root=raw,
        data_snapshot_sha256=snapshot_provenance,
    )
    after = canonical_seasonal_inventory(raw)
    assert_raw_snapshot_unchanged(before, after)
    # Reconstruct again after every local write so state/content evidence is
    # current at the exact public-result boundary.
    acquisition = verify_existing_jpl_month(
        config=config,
        scope=scope,
        raw_root=raw,
    )
    if not verify_month_acquisition_result(
        acquisition,
        config=config,
        scope=scope,
        inventory=after,
    ):
        raise SeasonalPreparationError("ACQUISITION_INTEGRITY_FAILED")
    official_reference_sha256 = verified_existing_official_reference_sha256(
        acquisition,
        config=config,
        scope=scope,
        inventory=after,
        raw_root=raw,
    )
    issue_qa = {**snapshots.qa, "snapshot_sha256": snapshots.snapshot_sha256}
    documents = _compact_month_documents(
        config=config,
        protocol=protocol,
        scope=scope,
        acquisition=acquisition,
        acquisition_qa=acquisition_qa,
        cleaning_qa=cleaning_qa,
        cleaning_sensitivity=sensitivity,
        boundary_audit=boundary,
        power_audit=power,
        station_qa=station.qa,
        issue_qa=issue_qa,
        blocks=blocks,
        invalid_skipped_session_count=len(invalid_ordinals),
        processed_snapshot_sha256=processed_snapshot,
        local_artifact_count=local_count,
        official_reference_sha256=official_reference_sha256,
        code_commit=code_commit,
    )
    result = build_month_preparation_result(config=config, documents=documents)
    assert_raw_snapshot_unchanged(before, canonical_seasonal_inventory(raw))
    return result


def prepare_jpl_seasonal_month(
    *,
    authorized: bool,
    config: JPLMonthConfig,
    metadata_root: str | Path,
    raw_root: str | Path,
    interim_root: str | Path,
    processed_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    protocol_path: str | Path = DEFAULT_SEASONAL_PROTOCOL_PATH,
) -> MonthPreparationResult:
    """Prepare one canonical month strictly from current on-disk evidence."""

    if authorized is not True:
        raise SeasonalPreparationError("PREPARATION_NOT_AUTHORIZED")
    metadata, raw, (interim, processed) = _preparation_root_topology(
        Path(metadata_root),
        Path(raw_root),
        (Path(interim_root), Path(processed_root)),
    )
    protocol = load_seasonal_preparation_protocol(protocol_path)
    verify_implementation_commit(code_commit, repo_root=repo_root)
    return _prepare_verified_month(
        config=config,
        protocol=protocol,
        metadata_root=metadata,
        raw_root=raw,
        interim_root=interim,
        processed_root=processed,
        code_commit=code_commit,
    )


def prepare_jpl_seasonal_data(
    *,
    authorized: bool,
    metadata_root: str | Path,
    raw_root: str | Path,
    interim_root: str | Path,
    processed_root: str | Path,
    public_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    protocol_path: str | Path = DEFAULT_SEASONAL_PROTOCOL_PATH,
) -> SeasonalPreparationResult:
    """Prepare/publish February, August, November in the one frozen order."""

    if authorized is not True:
        raise SeasonalPreparationError("PREPARATION_NOT_AUTHORIZED")
    metadata, raw_parent, (interim_parent, processed_parent, public) = _preparation_root_topology(
        Path(metadata_root),
        Path(raw_root),
        (Path(interim_root), Path(processed_root), Path(public_root)),
    )
    protocol = load_seasonal_preparation_protocol(protocol_path)
    verify_implementation_commit(code_commit, repo_root=repo_root)
    results: list[MonthPreparationResult] = []
    for month in SEASONAL_MONTHS:
        config = jpl_month_config(month)
        result = _prepare_verified_month(
            config=config,
            protocol=protocol,
            metadata_root=metadata,
            raw_root=raw_parent / month,
            interim_root=interim_parent / month,
            processed_root=processed_parent / month,
            code_commit=code_commit,
        )
        if (
            type(result) is not MonthPreparationResult
            or result.month != month
            or result.config_sha256 != protocol.config_sha256
            or result.code_commit != code_commit
        ):
            raise SeasonalPreparationError("MONTH_RESULT_BINDING_INVALID")
        publish_month_release(
            result,
            public,
            protected_roots=(raw_parent, metadata, interim_parent, processed_parent),
        )
        results.append(result)
    return publish_seasonal_root(
        tuple(results),
        public,
        protected_roots=(raw_parent, metadata, interim_parent, processed_parent),
    )


__all__ = [
    "MONTH_PAYLOAD_NAMES",
    "MONTH_RELEASE_NAMES",
    "ROOT_PAYLOAD_NAMES",
    "ROOT_RELEASE_NAMES",
    "ClosedArtifact",
    "MonthPreparationResult",
    "SeasonalPreparationError",
    "SeasonalPreparationProtocol",
    "SeasonalPreparationResult",
    "build_month_preparation_result",
    "expected_seasonal_release_paths",
    "load_seasonal_preparation_protocol",
    "load_verified_month_release",
    "load_verified_seasonal_release",
    "prepare_jpl_seasonal_data",
    "prepare_jpl_seasonal_month",
    "publish_month_release",
    "publish_seasonal_release",
    "publish_seasonal_root",
    "release_paths",
    "verify_implementation_commit",
    "verify_seasonal_release",
]
