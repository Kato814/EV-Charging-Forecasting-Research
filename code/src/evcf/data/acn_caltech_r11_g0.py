"""Pre-fit Caltech data preparation for frozen R11-G0 independent replication.

No forecasting model is imported or fitted here. Row-level arrays and cleaned
trajectories remain local under ignored data directories; public output is aggregate.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import yaml

from evcf.data.acn_api import (
    ACNClient,
    DEFAULT_API_BASE_URL,
    DEFAULT_TOKEN_ENV,
    download_sessions,
    format_http_date,
    iter_jsonl,
)
from evcf.data.acn_jpl_15min import AggregationPolicy, aggregate_station_15min
from evcf.data.acn_jpl_cleaning import (
    CleanSession,
    clean_session,
    cleaning_policy_from_sampling_modes,
    derive_sampling_modes,
    parse_timestamp_utc_s,
    write_cleaned_sessions,
)
from evcf.data.acn_jpl_issue_snapshots import SnapshotPolicy, build_issue_snapshots
from evcf.data.acn_jpl_trajectory_quarantine import (
    FULL_SESSION_QUARANTINE,
    TRAJECTORY_QUARANTINE,
    quarantine_record_for_analysis,
)

DEFAULT_PROTOCOL_PATH = Path("code/configs/acn_caltech_r11_g0_prefit_2019.yaml")
CALTECH_MONTHS = ("2019-02", "2019-05", "2019-08", "2019-11")
JPL_FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
TIMEZONE_NAME = "America/Los_Angeles"
BIN_SECONDS = 900
CONTEXT_BINS = 96
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_EPS = 1e-12

IMPLEMENTATION_PATHS = (
    "docs/JPL_R11_G0_CALTECH_INDEPENDENT_REPLICATION_PROTOCOL_20260915.md",
    "code/configs/acn_caltech_r11_g0_prefit_2019.yaml",
    "code/src/evcf/data/acn_caltech_r11_g0.py",
    "scripts/acquire_caltech_r11_g0.py",
    "scripts/prepare_caltech_r11_g0.py",
)

_EXPECTED_PROTOCOL: dict[str, Any] = {
    "schema_version": "acn-caltech-r11-g0-prefit/v1",
    "site_id": "caltech",
    "timezone": TIMEZONE_NAME,
    "months": list(CALTECH_MONTHS),
    "source": {
        "api_base_url": DEFAULT_API_BASE_URL,
        "endpoint": "sessions/caltech/ts",
        "token_environment_variable": DEFAULT_TOKEN_ENV,
        "overlap_query": "connectionTime < month_end and disconnectTime > month_start",
    },
    "target": {"name": "station_current_mean_a", "unit": "A"},
    "cleaning": {
        "sampling_derivation": "mode_of_positive_raw_timestamp_differences",
        "locf_mode_multiplier": 3,
        "locf_cap_seconds": 60,
        "boundary_sensitivity_seconds": 60,
    },
    "aggregation": {
        "bin_minutes": 15,
        "grid_policy": "continuous_physical_utc",
        "coverage_thresholds": [0.8, 0.9, 0.95],
        "main_valid_bin_field": "valid_bin_90",
        "minimum_valid_bin_rate": 0.8,
        "main_active_threshold_a": 0.1,
        "comparison_active_threshold_a": 1.0,
    },
    "missing_trajectory": {
        "preserve_structural_interval": True,
        "branchwise_availability": True,
        "whole_current_unobservable_overlap_rejects_target": True,
        "pilot_only_missing_rejects_current_target": False,
        "impute_future_labels": False,
        "coverage_rescale_current": False,
        "final_energy_reconstruction": False,
    },
    "trajectory_quarantine": {
        "detector": "synchronized_current_pilot_raw_order_utc_nonmonotonic",
        "preserve_raw": True,
        "sort_repair": False,
        "timestamp_shift_seconds": 0,
        "interpolation": False,
        "trajectory_unobservable": True,
        "coverage_denominator_includes_quarantined": True,
        "maximum_session_fraction": 0.001,
    },
    "snapshots": {
        "lookback_minutes": 1440,
        "horizons_minutes": list(HORIZONS_MINUTES),
        "issue_step_minutes": 15,
        "tier": "M1",
    },
    "privileged_label": {
        "name": "future_arrival_current",
        "arrival_rule": "connection_time_utc_s > issue_time_utc_s",
        "target_window": "[issue+h-15min, issue+h)",
        "reconstruction_absolute_tolerance_a": 0.000001,
    },
    "chronology": {
        "train_current_month_last_day": 14,
        "validation_first_day": 15,
        "validation_last_day": 17,
        "test_first_day": 18,
    },
    "publication": {
        "aggregate_status_only": True,
        "row_level_data_local_only": True,
        "session_identifiers_public": False,
        "absolute_paths_public": False,
    },
    "jpl_final_holdout": {
        "months": list(JPL_FINAL_HOLDOUT_MONTHS),
        "access_allowed": False,
    },
}


class R11G0Error(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        if not isinstance(reason_code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]+", reason_code) is None:
            reason_code = "UNEXPECTED_ERROR"
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class R11G0Protocol:
    protocol_sha256: str
    site_id: str = "caltech"
    timezone_name: str = TIMEZONE_NAME
    months: tuple[str, ...] = CALTECH_MONTHS
    locf_mode_multiplier: int = 3
    locf_cap_seconds: int = 60
    boundary_sensitivity_seconds: int = 60
    minimum_valid_bin_rate: float = 0.8
    main_active_threshold_a: float = 0.1
    comparison_active_threshold_a: float = 1.0
    maximum_quarantine_fraction: float = 0.001
    lookback_minutes: int = 1440
    horizons_minutes: tuple[int, ...] = HORIZONS_MINUTES
    issue_step_minutes: int = 15
    reconstruction_tolerance_a: float = 1e-6


@dataclass(frozen=True, slots=True)
class CaltechMonthConfig:
    month: str
    local_start: datetime
    local_end: datetime
    utc_start: datetime
    utc_end: datetime
    expected_bins: int
    expected_scheduled_issue_times: int


@dataclass(frozen=True, slots=True)
class OverlapQuery:
    site: str
    start: datetime
    end: datetime
    timeseries: bool
    max_sessions: int | None = None
    sort: str = "-connectionTime"

    def __post_init__(self) -> None:
        if self.site != "caltech" or _utc(self.start) >= _utc(self.end):
            raise ValueError("invalid frozen Caltech overlap query")
        if self.max_sessions is not None and (
            isinstance(self.max_sessions, bool) or self.max_sessions <= 0
        ):
            raise ValueError("max_sessions must be positive")

    @property
    def start_utc(self) -> datetime:
        return _utc(self.start)

    @property
    def end_utc(self) -> datetime:
        return _utc(self.end)

    @property
    def condition(self) -> str:
        return (
            f'connectionTime < "{format_http_date(self.end_utc)}" and '
            f'disconnectTime > "{format_http_date(self.start_utc)}"'
        )

    @property
    def endpoint(self) -> str:
        return f"sessions/{self.site}" + ("/ts" if self.timeseries else "")

    def public_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "start_utc": self.start_utc.isoformat(),
            "end_utc": self.end_utc.isoformat(),
            "timeseries": self.timeseries,
            "max_sessions": self.max_sessions,
            "sort": self.sort,
            "where": self.condition,
            "endpoint": self.endpoint,
            "selection": "connectionTime < month_end and disconnectTime > month_start",
        }


@dataclass(frozen=True, slots=True)
class AcquisitionMonthResult:
    month: str
    session_count: int
    raw_sha256: str
    reused_existing: bool

    def public_dict(self) -> dict[str, Any]:
        return {
            "month": self.month,
            "status": "COMPLETE",
            "session_count": self.session_count,
            "metadata_total": self.session_count,
            "raw_sha256": self.raw_sha256,
            "reused_existing": self.reused_existing,
        }


@dataclass(frozen=True, slots=True)
class PreparationMonthResult:
    month: str
    raw_session_count: int
    invalid_current_container_count: int
    invalid_pilot_container_count: int
    trajectory_quarantine_count: int
    trajectory_quarantine_rate: float
    current_mode_seconds: int
    pilot_mode_seconds: int
    current_hold_seconds: int
    pilot_hold_seconds: int
    station_bins: int
    valid_bin_90_count: int
    scheduled_issue_times: int
    formal_issue_times: int
    formal_test_origins: int
    common_rows_by_horizon: Mapping[str, int]
    component_reconstruction_max_abs_error_a: float
    processed_snapshot_sha256: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "month": self.month,
            "raw_session_count": self.raw_session_count,
            "cleaned_session_count": self.raw_session_count,
            "invalid_current_container_count": self.invalid_current_container_count,
            "invalid_pilot_container_count": self.invalid_pilot_container_count,
            "trajectory_quarantine_count": self.trajectory_quarantine_count,
            "trajectory_quarantine_rate": self.trajectory_quarantine_rate,
            "current_mode_seconds": self.current_mode_seconds,
            "pilot_mode_seconds": self.pilot_mode_seconds,
            "current_hold_seconds": self.current_hold_seconds,
            "pilot_hold_seconds": self.pilot_hold_seconds,
            "station_bins": self.station_bins,
            "valid_bin_90_count": self.valid_bin_90_count,
            "scheduled_issue_times": self.scheduled_issue_times,
            "formal_issue_times": self.formal_issue_times,
            "formal_test_origins": self.formal_test_origins,
            "common_rows_by_horizon": dict(self.common_rows_by_horizon),
            "component_reconstruction_max_abs_error_a": (
                self.component_reconstruction_max_abs_error_a
            ),
            "processed_snapshot_sha256": self.processed_snapshot_sha256,
        }


@dataclass(frozen=True, slots=True)
class PreparationResult:
    protocol_sha256: str
    code_commit: str
    months: tuple[PreparationMonthResult, ...]

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "evcf-r11-g0-caltech-prefit-manifest/v1",
            "status": "COMPLETE",
            "stage": "PREFIT_DATA_FREEZE",
            "site_id": "caltech",
            "protocol_sha256": self.protocol_sha256,
            "code_commit": self.code_commit,
            "months": [item.public_dict() for item in self.months],
            "models_trained": False,
            "model_fit_count": 0,
            "jpl_final_holdout_accessed": False,
            "session_predictors_used": False,
            "row_level_data_public": False,
        }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(timezone.utc)


def month_config(month: str) -> CaltechMonthConfig:
    if month not in CALTECH_MONTHS:
        raise R11G0Error("MONTH_NOT_AUTHORIZED")
    year, number = (int(part) for part in month.split("-"))
    next_year, next_number = (year + 1, 1) if number == 12 else (year, number + 1)
    zone = ZoneInfo(TIMEZONE_NAME)
    local_start = datetime(year, number, 1, tzinfo=zone)
    local_end = datetime(next_year, next_number, 1, tzinfo=zone)
    utc_start = local_start.astimezone(timezone.utc)
    utc_end = local_end.astimezone(timezone.utc)
    seconds = int((utc_end - utc_start).total_seconds())
    if seconds <= 0 or seconds % BIN_SECONDS:
        raise R11G0Error("MONTH_CONFIG_INVALID")
    expected_bins = seconds // BIN_SECONDS
    scheduled = expected_bins - 111
    if scheduled <= 0:
        raise R11G0Error("MONTH_CONFIG_INVALID")
    return CaltechMonthConfig(
        month=month,
        local_start=local_start,
        local_end=local_end,
        utc_start=utc_start,
        utc_end=utc_end,
        expected_bins=expected_bins,
        expected_scheduled_issue_times=scheduled,
    )


def load_protocol(path: str | Path = DEFAULT_PROTOCOL_PATH) -> R11G0Protocol:
    source = Path(path)
    try:
        raw = source.read_bytes()
        parsed = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise R11G0Error("PROTOCOL_INVALID") from exc
    if parsed != _EXPECTED_PROTOCOL:
        raise R11G0Error("PROTOCOL_INVALID")
    return R11G0Protocol(protocol_sha256=hashlib.sha256(raw).hexdigest())


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def verify_implementation_commit(code_commit: str, *, repo_root: str | Path) -> None:
    if not isinstance(code_commit, str) or _COMMIT.fullmatch(code_commit) is None:
        raise R11G0Error("IMPLEMENTATION_DRIFT")
    root = Path(repo_root).resolve(strict=True)
    head = _git(root, "rev-parse", "HEAD")
    if head.returncode != 0 or head.stdout.decode("ascii").strip() != code_commit:
        raise R11G0Error("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        if (
            _git(root, "cat-file", "-e", f"{code_commit}:{relative}").returncode != 0
            or _git(root, "diff", "--quiet", code_commit, "--", relative).returncode != 0
            or _git(root, "diff", "--cached", "--quiet", code_commit, "--", relative).returncode
            != 0
        ):
            raise R11G0Error("IMPLEMENTATION_DRIFT")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    if path.exists() or partial.exists():
        raise R11G0Error("OUTPUT_ALREADY_EXISTS")
    data = _json_bytes(payload)
    try:
        with partial.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise R11G0Error("LOCAL_ARTIFACT_INVALID") from exc
    if not isinstance(value, Mapping):
        raise R11G0Error("LOCAL_ARTIFACT_INVALID")
    return value


def _raw_paths(root: Path, month: str) -> tuple[Path, Path, Path]:
    data = root / month / "sessions_overlap.jsonl"
    return (
        data,
        data.with_suffix(data.suffix + ".manifest.json"),
        data.parent / "acquisition_summary.json",
    )


def _bounds(record: Mapping[str, Any]) -> tuple[int, int]:
    try:
        connection = parse_timestamp_utc_s(record.get("connectionTime"))
        disconnect = parse_timestamp_utc_s(record.get("disconnectTime"))
    except (TypeError, ValueError) as exc:
        raise R11G0Error("METADATA_BOUNDS_INVALID") from exc
    if disconnect <= connection:
        raise R11G0Error("METADATA_BOUNDS_INVALID")
    return connection, disconnect


def _validate_raw(path: Path, config: CaltechMonthConfig, expected: int) -> None:
    start = int(config.utc_start.timestamp())
    end = int(config.utc_end.timestamp())
    pairs: set[tuple[str, str]] = set()
    count = 0
    for record in iter_jsonl(path):
        connection, disconnect = _bounds(record)
        if not (connection < end and disconnect > start):
            raise R11G0Error("RAW_SCOPE_INVALID")
        object_id, session_id = record.get("_id"), record.get("sessionID")
        if not isinstance(object_id, str) or not isinstance(session_id, str):
            raise R11G0Error("RAW_IDENTITY_INVALID")
        pair = (object_id, session_id)
        if not object_id or not session_id or pair in pairs:
            raise R11G0Error("RAW_DUPLICATE_IDENTITY")
        pairs.add(pair)
        count += 1
    if count != expected or count <= 0:
        raise R11G0Error("RAW_RECORD_COUNT_INVALID")


def _existing_acquisition(
    protocol: R11G0Protocol,
    config: CaltechMonthConfig,
    raw: Path,
    manifest_path: Path,
    summary_path: Path,
) -> AcquisitionMonthResult:
    manifest, summary = _load_json(manifest_path), _load_json(summary_path)
    query = OverlapQuery("caltech", config.utc_start, config.utc_end, True)
    raw_sha = _sha256_file(raw)
    count = manifest.get("record_count")
    if (
        manifest.get("schema_version") != "acn-download-manifest/v1"
        or manifest.get("query") != query.public_dict()
        or manifest.get("complete_for_query") is not True
        or manifest.get("sha256") != raw_sha
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count <= 0
        or manifest.get("remote_total_reported") != count
        or summary.get("schema_version") != "evcf-r11-g0-caltech-acquisition-month/v1"
        or summary.get("protocol_sha256") != protocol.protocol_sha256
        or summary.get("month") != config.month
        or summary.get("session_count") != count
        or summary.get("metadata_total") != count
        or summary.get("raw_sha256") != raw_sha
    ):
        raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID")
    _validate_raw(raw, config, count)
    return AcquisitionMonthResult(config.month, count, raw_sha, True)


def acquire_caltech_r11_g0(
    *,
    authorized: bool,
    raw_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    protocol_path: str | Path = DEFAULT_PROTOCOL_PATH,
    client: ACNClient | None = None,
) -> tuple[R11G0Protocol, tuple[AcquisitionMonthResult, ...]]:
    if authorized is not True:
        raise R11G0Error("ACQUISITION_NOT_AUTHORIZED")
    verify_implementation_commit(code_commit, repo_root=repo_root)
    protocol = load_protocol(protocol_path)
    root = Path(raw_root)
    if root.exists() and (not root.is_dir() or root.is_symlink()):
        raise R11G0Error("OUTPUT_TOPOLOGY_INVALID")
    root.mkdir(parents=True, exist_ok=True)
    active_client = client or ACNClient.from_env(DEFAULT_TOKEN_ENV)

    results: list[AcquisitionMonthResult] = []
    for month in CALTECH_MONTHS:
        config = month_config(month)
        raw, manifest_path, summary_path = _raw_paths(root, month)
        existing = tuple(path.exists() for path in (raw, manifest_path, summary_path))
        if any(existing):
            if not all(existing):
                raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID")
            results.append(
                _existing_acquisition(protocol, config, raw, manifest_path, summary_path)
            )
            continue

        metadata = OverlapQuery("caltech", config.utc_start, config.utc_end, False)
        timeseries = OverlapQuery("caltech", config.utc_start, config.utc_end, True)
        try:
            total = active_client.fetch_total_once(metadata)  # type: ignore[arg-type]
            downloaded = download_sessions(
                active_client,
                timeseries,  # type: ignore[arg-type]
                raw,
                overwrite=False,
            )
        except Exception as exc:
            raise R11G0Error("ACN_ACQUISITION_FAILED") from exc
        if (
            total <= 0
            or downloaded.complete is not True
            or downloaded.record_count != total
            or downloaded.remote_total_reported != total
            or downloaded.sha256 != _sha256_file(raw)
        ):
            raise R11G0Error("ACN_ACQUISITION_INTEGRITY_FAILED")
        _validate_raw(raw, config, total)
        _atomic_json(
            summary_path,
            {
                "schema_version": "evcf-r11-g0-caltech-acquisition-month/v1",
                "status": "COMPLETE",
                "month": month,
                "site_id": "caltech",
                "protocol_sha256": protocol.protocol_sha256,
                "session_count": total,
                "metadata_total": total,
                "raw_sha256": downloaded.sha256,
                "partial_file_count": 0,
                "timeseries": True,
                "overlap_selection": True,
                "identifiers_public": False,
                "token_stored": False,
            },
        )
        results.append(AcquisitionMonthResult(month, total, downloaded.sha256, False))
    return protocol, tuple(results)


def _valid_container(record: Mapping[str, Any], field: str, value_key: str) -> bool:
    series = record.get(field)
    if not isinstance(series, Mapping):
        return False
    timestamps, values = series.get("timestamps"), series.get(value_key)
    return (
        isinstance(timestamps, list)
        and isinstance(values, list)
        and len(timestamps) == len(values)
    )


def _analysis_records(
    records: Sequence[Mapping[str, Any]],
    max_quarantine_fraction: float,
) -> tuple[list[Mapping[str, Any]], int, int, int]:
    output: list[Mapping[str, Any]] = []
    bad_current = bad_pilot = quarantined = 0
    for record in records:
        _bounds(record)
        decision, projected = quarantine_record_for_analysis(record)
        if decision.action == FULL_SESSION_QUARANTINE or not decision.metadata_bounds_valid:
            raise R11G0Error("METADATA_BOUNDS_INVALID")
        if decision.action == TRAJECTORY_QUARANTINE:
            if projected is None:
                raise R11G0Error("TRAJECTORY_QUARANTINE_INVALID")
            quarantined += 1
            output.append(projected)
            continue
        branchwise = dict(record)
        if not _valid_container(record, "chargingCurrent", "current"):
            bad_current += 1
            branchwise["chargingCurrent"] = {"timestamps": [], "current": []}
        if not _valid_container(record, "pilotSignal", "pilot"):
            bad_pilot += 1
            branchwise["pilotSignal"] = {"timestamps": [], "pilot": []}
        output.append(branchwise)
    if not records or quarantined / len(records) > max_quarantine_fraction + _EPS:
        raise R11G0Error("TRAJECTORY_QUARANTINE_RATE_EXCEEDED")
    return output, bad_current, bad_pilot, quarantined


def _write_npy(path: Path, array: np.ndarray) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    if path.exists() or partial.exists():
        raise R11G0Error("OUTPUT_ALREADY_EXISTS")
    try:
        with partial.open("xb") as handle:
            np.save(handle, np.asarray(array), allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return _sha256_file(path)


def _formal_arrays(snapshot: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    features, targets = snapshot.m1_rows, snapshot.label_rows
    if len(features) != len(targets) or not features:
        raise R11G0Error("FORMAL_ROW_INVALID")
    issue = np.asarray([row["issue_time_utc_s"] for row in features], dtype=np.int64)
    history = np.empty((len(features), CONTEXT_BINS), dtype=np.float64)
    mask = np.empty((len(features), CONTEXT_BINS), dtype=np.uint8)
    labels = np.empty((len(features), len(HORIZONS_MINUTES)), dtype=np.float64)
    for row_index, (feature, target) in enumerate(zip(features, targets, strict=True)):
        if feature["issue_index"] != target["issue_index"]:
            raise R11G0Error("FORMAL_ROW_INVALID")
        values = feature["history_station_current_mean_a"]
        observed = feature["history_observed_mask"]
        if len(values) != CONTEXT_BINS or len(observed) != CONTEXT_BINS:
            raise R11G0Error("FORMAL_ROW_INVALID")
        for lag, (value, flag) in enumerate(zip(values, observed, strict=True)):
            if type(flag) is not bool:
                raise R11G0Error("FORMAL_ROW_INVALID")
            mask[row_index, lag] = int(flag)
            if flag:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise R11G0Error("FORMAL_ROW_INVALID")
                history[row_index, lag] = float(value)
            else:
                if value is not None:
                    raise R11G0Error("FORMAL_ROW_INVALID")
                history[row_index, lag] = np.nan
        raw_labels = target["labels"]
        for position, horizon in enumerate(HORIZONS_MINUTES):
            value = raw_labels[str(horizon)]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise R11G0Error("FORMAL_ROW_INVALID")
            labels[row_index, position] = float(value)
    if (
        np.any(np.diff(issue) <= 0)
        or not np.isfinite(labels).all()
        or not np.isfinite(history[mask.astype(bool)]).all()
    ):
        raise R11G0Error("FORMAL_ROW_INVALID")
    return issue, history, mask, labels


def _bin_components(
    sessions: Sequence[CleanSession],
    config: CaltechMonthConfig,
) -> tuple[tuple[tuple[int, float], ...], ...]:
    start, end = int(config.utc_start.timestamp()), int(config.utc_end.timestamp())
    bins: list[list[tuple[int, float]]] = [[] for _ in range(config.expected_bins)]
    for session in sessions:
        for item in session.current.main_integral.contributions:
            left, right = max(item.start_utc_s, start), min(item.end_utc_s, end)
            if right <= left:
                continue
            first, last = (left - start) // BIN_SECONDS, (right - 1 - start) // BIN_SECONDS
            for index in range(first, last + 1):
                bin_start = start + index * BIN_SECONDS
                seconds = min(right, bin_start + BIN_SECONDS) - max(left, bin_start)
                if seconds <= 0:
                    continue
                value = float(item.value) * seconds / BIN_SECONDS
                if value < -_EPS:
                    raise R11G0Error("COMPONENT_LABEL_INVALID")
                if value > _EPS:
                    bins[index].append((session.connection_utc_s, value))
    return tuple(tuple(values) for values in bins)


def _arrival_labels(
    sessions: Sequence[CleanSession],
    config: CaltechMonthConfig,
    issue: np.ndarray,
    labels: np.ndarray,
    tolerance: float,
) -> tuple[np.ndarray, float]:
    components = _bin_components(sessions, config)
    start = int(config.utc_start.timestamp())
    arrival = np.empty_like(labels)
    maximum_error = 0.0
    for row, issue_time in enumerate(issue):
        issue_bin = (int(issue_time) - start) // BIN_SECONDS
        for position, horizon in enumerate(HORIZONS_MINUTES):
            target_bin = issue_bin + horizon // 15 - 1
            existing_sum = arrival_sum = 0.0
            for connection, value in components[target_bin]:
                if connection > int(issue_time):
                    arrival_sum += value
                else:
                    existing_sum += value
            error = abs(existing_sum + arrival_sum - float(labels[row, position]))
            maximum_error = max(maximum_error, error)
            if error > tolerance or existing_sum < -_EPS or arrival_sum < -_EPS:
                raise R11G0Error("COMPONENT_RECONSTRUCTION_FAILED")
            arrival[row, position] = max(0.0, arrival_sum)
    return arrival, maximum_error


def _prepare_month(
    protocol: R11G0Protocol,
    config: CaltechMonthConfig,
    raw_root: Path,
    interim_root: Path,
    processed_root: Path,
) -> PreparationMonthResult:
    raw, _download_manifest, summary_path = _raw_paths(raw_root, config.month)
    summary = _load_json(summary_path)
    count = summary.get("session_count")
    if not raw.is_file() or not isinstance(count, int) or isinstance(count, bool):
        raise R11G0Error("RAW_NOT_ACQUIRED")
    _validate_raw(raw, config, count)
    raw_records = list(iter_jsonl(raw))
    records, bad_current, bad_pilot, quarantined = _analysis_records(
        raw_records,
        protocol.maximum_quarantine_fraction,
    )
    try:
        modes = derive_sampling_modes(records)
        policy = cleaning_policy_from_sampling_modes(
            modes,
            locf_mode_multiplier=protocol.locf_mode_multiplier,
            locf_cap_seconds=protocol.locf_cap_seconds,
            boundary_sensitivity_seconds=protocol.boundary_sensitivity_seconds,
        )
        cleaned = [
            clean_session(record, session_index=index, policy=policy)
            for index, record in enumerate(records)
        ]
    except (TypeError, ValueError) as exc:
        raise R11G0Error("CLEANING_FAILED") from exc

    interim = interim_root / config.month
    processed = processed_root / config.month
    interim.mkdir(parents=True, exist_ok=False)
    processed.mkdir(parents=True, exist_ok=False)
    store = write_cleaned_sessions(
        cleaned,
        interim / "cleaned_sessions.jsonl.gz",
        policy=policy,
        source_inventory_sha256=_sha256_file(raw),
    )

    aggregation_policy = AggregationPolicy(
        max_hold_seconds=policy.hold_cap_for("chargingCurrent"),
        pilot_max_hold_seconds=policy.hold_cap_for("pilotSignal"),
        main_active_threshold_a=protocol.main_active_threshold_a,
        comparison_active_threshold_a=protocol.comparison_active_threshold_a,
        coverage_thresholds=(0.8, 0.9, 0.95),
    )
    try:
        station = aggregate_station_15min(
            cleaned,
            start_utc=config.utc_start,
            end_utc=config.utc_end,
            policy=aggregation_policy,
            grid_policy="continuous_physical_utc",
            enforce_known_incomplete_current=True,
        )
        snapshot = build_issue_snapshots(
            station.rows,
            cleaned,
            start_utc=config.utc_start,
            end_utc=config.utc_end,
            policy=SnapshotPolicy(
                lookback_minutes=protocol.lookback_minutes,
                horizons_minutes=protocol.horizons_minutes,
                issue_step_minutes=protocol.issue_step_minutes,
                max_hold_seconds=policy.hold_cap_for("chargingCurrent"),
                active_threshold_a=protocol.main_active_threshold_a,
                tiers=("M1",),
            ),
            preserve_unobserved_trajectory_missingness=True,
        )
    except (TypeError, ValueError) as exc:
        raise R11G0Error("SNAPSHOT_BUILD_FAILED") from exc

    if (
        len(station.rows) != config.expected_bins
        or snapshot.qa.get("issue_times") != config.expected_scheduled_issue_times
    ):
        raise R11G0Error("SCHEDULE_IDENTITY_INVALID")
    issue, history, mask, labels = _formal_arrays(snapshot)
    arrival, reconstruction_error = _arrival_labels(
        cleaned,
        config,
        issue,
        labels,
        protocol.reconstruction_tolerance_a,
    )
    zone = ZoneInfo(TIMEZONE_NAME)
    local_days = np.asarray(
        [datetime.fromtimestamp(int(value), timezone.utc).astimezone(zone).day for value in issue],
        dtype=np.int16,
    )
    test_origins = int(np.sum(local_days >= 18))
    if test_origins <= 0:
        raise R11G0Error("FORMAL_ROW_INVALID")

    arrays = {
        "issue_times.npy": issue,
        "local_days.npy": local_days,
        "history_raw.npy": history,
        "history_mask.npy": mask,
        "labels.npy": labels,
        "future_arrival_labels.npy": arrival,
    }
    files: dict[str, Any] = {}
    for name, values in arrays.items():
        files[name] = {
            "sha256": _write_npy(processed / name, values),
            "shape": list(values.shape),
            "dtype": str(values.dtype),
        }

    valid_bins = sum(bool(row.get("valid_bin_90")) for row in station.rows)
    if valid_bins / config.expected_bins < protocol.minimum_valid_bin_rate:
        raise R11G0Error("VALID_BIN_90_RATE_TOO_LOW")
    common = {str(horizon): len(issue) for horizon in HORIZONS_MINUTES}
    core = {
        "schema_version": "evcf-r11-g0-caltech-private-snapshot/v1",
        "month": config.month,
        "protocol_sha256": protocol.protocol_sha256,
        "raw_sha256": _sha256_file(raw),
        "cleaned_sessions_sha256": store.sha256,
        "cleaned_session_count": len(cleaned),
        "invalid_current_container_count": bad_current,
        "invalid_pilot_container_count": bad_pilot,
        "trajectory_quarantine_count": quarantined,
        "current_mode_seconds": modes.current.mode_seconds,
        "pilot_mode_seconds": modes.pilot.mode_seconds,
        "current_hold_seconds": policy.hold_cap_for("chargingCurrent"),
        "pilot_hold_seconds": policy.hold_cap_for("pilotSignal"),
        "station_bins": config.expected_bins,
        "valid_bin_90_count": valid_bins,
        "scheduled_issue_times": config.expected_scheduled_issue_times,
        "formal_issue_times": len(issue),
        "formal_test_origins": test_origins,
        "common_rows_by_horizon": common,
        "component_reconstruction_max_abs_error_a": reconstruction_error,
        "files": files,
        "models_trained": False,
        "row_level_data_public": False,
    }
    snapshot_sha = hashlib.sha256(_json_bytes(core)).hexdigest()
    _atomic_json(
        processed / "data_snapshot_manifest.json",
        {**core, "processed_snapshot_sha256": snapshot_sha},
    )
    return PreparationMonthResult(
        month=config.month,
        raw_session_count=count,
        invalid_current_container_count=bad_current,
        invalid_pilot_container_count=bad_pilot,
        trajectory_quarantine_count=quarantined,
        trajectory_quarantine_rate=quarantined / count,
        current_mode_seconds=modes.current.mode_seconds,
        pilot_mode_seconds=modes.pilot.mode_seconds,
        current_hold_seconds=policy.hold_cap_for("chargingCurrent"),
        pilot_hold_seconds=policy.hold_cap_for("pilotSignal"),
        station_bins=config.expected_bins,
        valid_bin_90_count=valid_bins,
        scheduled_issue_times=config.expected_scheduled_issue_times,
        formal_issue_times=len(issue),
        formal_test_origins=test_origins,
        common_rows_by_horizon=MappingProxyType(common),
        component_reconstruction_max_abs_error_a=reconstruction_error,
        processed_snapshot_sha256=snapshot_sha,
    )


def prepare_caltech_r11_g0(
    *,
    authorized: bool,
    raw_root: str | Path,
    interim_root: str | Path,
    processed_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    protocol_path: str | Path = DEFAULT_PROTOCOL_PATH,
    public_manifest_output: str | Path | None = None,
) -> PreparationResult:
    if authorized is not True:
        raise R11G0Error("PREFIT_NOT_AUTHORIZED")
    verify_implementation_commit(code_commit, repo_root=repo_root)
    protocol = load_protocol(protocol_path)
    raw = Path(raw_root).resolve(strict=True)
    interim, processed = Path(interim_root), Path(processed_root)
    if not raw.is_dir() or raw.is_symlink() or interim.exists() or processed.exists():
        raise R11G0Error("OUTPUT_TOPOLOGY_INVALID")
    interim.mkdir(parents=True, exist_ok=False)
    processed.mkdir(parents=True, exist_ok=False)

    months = tuple(
        _prepare_month(protocol, month_config(month), raw, interim, processed)
        for month in CALTECH_MONTHS
    )
    result = PreparationResult(protocol.protocol_sha256, code_commit, months)
    payload = result.public_dict()
    _atomic_json(processed / "r11_g0_prefit_manifest.json", payload)
    if public_manifest_output is not None:
        _atomic_json(Path(public_manifest_output), payload)
    return result


__all__ = [
    "CALTECH_MONTHS",
    "DEFAULT_PROTOCOL_PATH",
    "HORIZONS_MINUTES",
    "JPL_FINAL_HOLDOUT_MONTHS",
    "AcquisitionMonthResult",
    "CaltechMonthConfig",
    "OverlapQuery",
    "PreparationMonthResult",
    "PreparationResult",
    "R11G0Error",
    "R11G0Protocol",
    "acquire_caltech_r11_g0",
    "load_protocol",
    "month_config",
    "prepare_caltech_r11_g0",
    "verify_implementation_commit",
]
