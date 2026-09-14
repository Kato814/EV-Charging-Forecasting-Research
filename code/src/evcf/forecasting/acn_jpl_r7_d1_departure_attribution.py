"""Frozen R7-D1 attribution ablation for requested-departure information."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

import numpy as np

from evcf.forecasting.acn_jpl_development_experts import MonthData, load_selected_hgb_parameters
from evcf.forecasting.acn_jpl_development_experts_compat import (
    DevelopmentExpertError,
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock
from evcf.forecasting.acn_jpl_r7_c0_departure_arrival import (
    EXPECTED_ROWS_BY_MONTH,
    EXPECTED_ROWS_PER_HORIZON,
    HORIZONS_MINUTES,
    SELECTED_M2_PARAMETER_SHA256,
    _predict_custom_arm,
)
from evcf.forecasting.acn_jpl_structured_baseline import (
    _component_label_matrices,
    _load_cleaned_current_sessions,
    _metrics,
    load_structured_protocol,
)
from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
    EXPECTED_STRUCTURED_PROTOCOL_SHA256,
    _load_npz,
    _verify_private_manifest,
)

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
SOURCE_R7_STATUS_SHA256 = (
    "deb7fc1700fccd3eb53616bbe2e65de0941b6294d60aec58e4f63953b576bce0"
)
SOURCE_R7_DECISION = "PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL"
EXPECTED_R7_PRIVATE_MANIFEST_SHA256 = (
    "172c69c71e6baef689f65ad0169b3440947675f462dd1bc9b72479e11bad6967"
)
R7_REVIEWED_EXECUTABLE = "24e9e69413cb4b224bd1c59cdd3725b352bd27ed"
R7_PROTOCOL_COMMIT = "ed427067015e60b417cd5da3838b4e0a5701b01e"
D1_PROTOCOL_COMMIT = "5532e2f9aca90e03c580d0203aec6b193b71cda3"
EXPECTED_FIT_COUNT = 275
EXPECTED_RECORD_COUNT = 25_375
AVAILABILITY_RAW_WIDTH = 203
AVAILABILITY_ENCODED_WIDTH = 206
MAX_DEGRADATION_FRACTION = 0.05
RECONSTRUCTION_TOLERANCE_A = 1e-6
Progress = Callable[[str], None]

_AVAILABILITY_FEATURE_NAMES = (
    "m3_requested_departure_minutes_from_issue_count",
    "m3_requested_departure_minutes_from_issue_missing_count",
)
_EXPECTED_R7_REPLAY = MappingProxyType(
    {
        "base_arrival_mae_a": 23.105151690700726,
        "departure_arrival_mae_a": 22.748690662816003,
        "s1_total_mae_a": 28.594881529741027,
        "equal_total_mae_a": 28.91728598859252,
        "departure_total_mae_a": 28.435454290098633,
    }
)
_R7_REQUIRED_FIELDS = {
    "issue_times",
    "day_start_utc_s",
    "y_true",
    "arrival_truth",
    "base_arrival_predictions",
    "departure_arrival_predictions",
    "full_m3_arrival_predictions",
    "s1_existing_predictions",
    "s1_predictions",
    "equal_predictions",
    "total_departure_predictions",
    "total_full_m3_predictions",
}

_REUSED_R7_PATHS = (
    "code/configs/acn_jpl_development_experts_2019.yaml",
    "code/configs/acn_jpl_structured_baseline_2019.yaml",
    "code/src/evcf/forecasting/acn_jpl_development_experts.py",
    "code/src/evcf/forecasting/acn_jpl_development_experts_compat.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_features.py",
    "code/src/evcf/forecasting/acn_jpl_gate1_models.py",
    "code/src/evcf/forecasting/acn_jpl_structured_baseline.py",
    "code/src/evcf/forecasting/acn_jpl_structured_mechanism_probe.py",
    "code/src/evcf/forecasting/acn_jpl_r7_c0_departure_arrival.py",
)
_IMPLEMENTATION_PATHS = _REUSED_R7_PATHS + (
    "docs/JPL_R7_D1_DEPARTURE_ATTRIBUTION_PROTOCOL_20260914.md",
    "code/src/evcf/forecasting/acn_jpl_r7_d1_departure_attribution.py",
    "scripts/run_jpl_r7_d1_departure_attribution.py",
)


class R7D1Error(RuntimeError):
    """Static failure code safe for aggregate publication."""

    def __init__(self, reason_code: str) -> None:
        if (
            not isinstance(reason_code, str)
            or not reason_code
            or not reason_code.replace("_", "").isalnum()
        ):
            reason_code = "UNEXPECTED_ERROR"
        self.reason_code = reason_code
        super().__init__(reason_code)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_sha(repo_root: Path, ref: str, relative: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", f"{ref}:{relative}"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
        encoding="ascii",
        errors="ignore",
    )
    if completed.returncode or len(completed.stdout.strip()) != 40:
        raise R7D1Error("IMPLEMENTATION_DRIFT")
    return completed.stdout.strip()


def _git_semantic_verify(code_commit: str, *, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R7D1Error("IMPLEMENTATION_DRIFT")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        text=True,
        encoding="ascii",
        errors="ignore",
    )
    if head.returncode or head.stdout.strip() != code_commit:
        raise R7D1Error("IMPLEMENTATION_DRIFT")
    for relative in _IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R7D1Error("IMPLEMENTATION_DRIFT")
        if _git_blob_sha(repo_root, code_commit, relative) != _git_blob_sha(
            repo_root, "HEAD", relative
        ):
            raise R7D1Error("IMPLEMENTATION_DRIFT")
    for relative in _REUSED_R7_PATHS:
        if _git_blob_sha(repo_root, code_commit, relative) != _git_blob_sha(
            repo_root, R7_REVIEWED_EXECUTABLE, relative
        ):
            raise R7D1Error("R7_REUSED_IMPLEMENTATION_DRIFT")
    diff = subprocess.run(
        ["git", "diff", "--quiet", "--no-ext-diff", code_commit, "--", *_IMPLEMENTATION_PATHS],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if diff.returncode:
        raise R7D1Error("IMPLEMENTATION_DRIFT")


def _availability_block(m2: FeatureBlock, m3: FeatureBlock) -> FeatureBlock:
    if (
        not np.array_equal(m2.issue_times, m3.issue_times)
        or len(m2.feature_names) != 201
        or len(m3.feature_names) != 311
        or tuple(m3.feature_names[:201]) != tuple(m2.feature_names)
        or not np.array_equal(m3.values[:, :201], m2.values, equal_nan=True)
        or not np.array_equal(m3.nullable_mask[:201], m2.nullable_mask)
    ):
        raise R7D1Error("FEATURE_ALIGNMENT_INVALID")
    try:
        positions = [m3.feature_names.index(name) for name in _AVAILABILITY_FEATURE_NAMES]
    except ValueError as exc:
        raise R7D1Error("AVAILABILITY_FEATURE_SCHEMA_INVALID") from exc
    if len(set(positions)) != 2 or any(bool(m3.nullable_mask[position]) for position in positions):
        raise R7D1Error("AVAILABILITY_FEATURE_SCHEMA_INVALID")
    selected = np.asarray(m3.values[:, positions], dtype=np.float64)
    if (
        np.any(~np.isfinite(selected))
        or np.any(selected < 0)
        or np.any(selected != np.floor(selected))
    ):
        raise R7D1Error("AVAILABILITY_FEATURE_SCHEMA_INVALID")
    values = np.concatenate((m2.values, selected), axis=1)
    nullable = np.concatenate((m2.nullable_mask, np.zeros(2, dtype=np.bool_)))
    names = tuple(m2.feature_names) + _AVAILABILITY_FEATURE_NAMES
    if values.shape[1] != AVAILABILITY_RAW_WIDTH or (
        values.shape[1] + int(np.sum(nullable)) != AVAILABILITY_ENCODED_WIDTH
    ):
        raise R7D1Error("AVAILABILITY_FEATURE_SCHEMA_INVALID")
    try:
        return FeatureBlock(m2.issue_times, values, names, nullable)
    except (TypeError, ValueError) as exc:
        raise R7D1Error("AVAILABILITY_FEATURE_SCHEMA_INVALID") from exc


def _load_r7_reference(root: Path, *, month: str, horizon: int) -> dict[str, np.ndarray]:
    reference = _load_npz(root / f"{month}_h{horizon:03d}.npz", _R7_REQUIRED_FIELDS)
    expected_n = EXPECTED_ROWS_BY_MONTH[month]
    if any(array.shape != (expected_n,) for array in reference.values()):
        raise R7D1Error("R7_PRIVATE_CACHE_SCHEMA_INVALID")
    if (
        reference["issue_times"].dtype != np.dtype(np.int64)
        or reference["day_start_utc_s"].dtype != np.dtype(np.int64)
        or np.any(np.diff(reference["issue_times"]) <= 0)
    ):
        raise R7D1Error("R7_PRIVATE_CACHE_SCHEMA_INVALID")
    numeric = [
        value
        for key, value in reference.items()
        if key not in {"issue_times", "day_start_utc_s"}
    ]
    if not all(np.isfinite(array).all() for array in numeric):
        raise R7D1Error("R7_PRIVATE_CACHE_SCHEMA_INVALID")
    if not (
        np.allclose(
            reference["s1_existing_predictions"] + reference["base_arrival_predictions"],
            reference["s1_predictions"],
            rtol=0.0,
            atol=RECONSTRUCTION_TOLERANCE_A,
        )
        and np.allclose(
            reference["s1_existing_predictions"]
            + reference["departure_arrival_predictions"],
            reference["total_departure_predictions"],
            rtol=0.0,
            atol=RECONSTRUCTION_TOLERANCE_A,
        )
        and np.allclose(
            reference["s1_existing_predictions"]
            + reference["full_m3_arrival_predictions"],
            reference["total_full_m3_predictions"],
            rtol=0.0,
            atol=RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise R7D1Error("R7_PRIVATE_CACHE_RECONSTRUCTION_INVALID")
    return reference


def _record(
    *,
    month: str,
    horizon: int,
    reference: Mapping[str, np.ndarray],
    availability: Mapping[str, Any],
) -> dict[str, Any]:
    expected_n = EXPECTED_ROWS_BY_MONTH[month]
    if (
        len(availability["issue_times"]) != expected_n
        or not np.array_equal(reference["issue_times"], availability["issue_times"])
        or not np.array_equal(reference["day_start_utc_s"], availability["day_starts"])
        or not np.allclose(
            reference["arrival_truth"],
            availability["truth"],
            rtol=0.0,
            atol=RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise R7D1Error("COMMON_ROW_IDENTITY_INVALID")
    availability_arrival = np.asarray(availability["predictions"], dtype=np.float64)
    availability_total = (
        np.asarray(reference["s1_existing_predictions"], dtype=np.float64)
        + availability_arrival
    )
    if not np.isfinite(availability_total).all():
        raise R7D1Error("MODEL_OUTPUT_INVALID")
    return {
        "month": month,
        "horizon": horizon,
        "issue_times": np.asarray(reference["issue_times"], dtype=np.int64),
        "day_starts": np.asarray(reference["day_start_utc_s"], dtype=np.int64),
        "total_truth": np.asarray(reference["y_true"], dtype=np.float64),
        "arrival_truth": np.asarray(reference["arrival_truth"], dtype=np.float64),
        "base_arrival": np.asarray(reference["base_arrival_predictions"], dtype=np.float64),
        "availability_arrival": availability_arrival,
        "departure_arrival": np.asarray(
            reference["departure_arrival_predictions"], dtype=np.float64
        ),
        "s1_existing": np.asarray(reference["s1_existing_predictions"], dtype=np.float64),
        "s1_total": np.asarray(reference["s1_predictions"], dtype=np.float64),
        "equal_total": np.asarray(reference["equal_predictions"], dtype=np.float64),
        "availability_total": availability_total,
        "departure_total": np.asarray(
            reference["total_departure_predictions"], dtype=np.float64
        ),
    }


def _summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise R7D1Error("METRIC_INVALID")

    def cat(name: str) -> np.ndarray:
        return np.concatenate(
            [np.asarray(record[name], dtype=np.float64) for record in records]
        )

    arrival_truth = cat("arrival_truth")
    total_truth = cat("total_truth")
    return {
        "arrival": {
            "BaseM2": _metrics(arrival_truth, cat("base_arrival")),
            "DepartureAvailability": _metrics(arrival_truth, cat("availability_arrival")),
            "DepartureAug": _metrics(arrival_truth, cat("departure_arrival")),
        },
        "total": {
            "S1": _metrics(total_truth, cat("s1_total")),
            "Equal": _metrics(total_truth, cat("equal_total")),
            "TotalAvailability": _metrics(total_truth, cat("availability_total")),
            "TotalDeparture": _metrics(total_truth, cat("departure_total")),
        },
    }


def _degradation(reference: float, candidate: float) -> float:
    if reference < 0 or candidate < 0:
        raise R7D1Error("METRIC_INVALID")
    if reference == 0.0:
        if candidate == 0.0:
            return 0.0
        raise R7D1Error("METRIC_INVALID")
    return float((candidate - reference) / reference)


def decide_attribution(
    pooled: Mapping[str, Any],
    by_horizon: Sequence[Mapping[str, Any]],
    by_month: Sequence[Mapping[str, Any]],
) -> tuple[str, dict[str, Any]]:
    base = float(pooled["arrival"]["BaseM2"]["mae_a"])
    availability = float(pooled["arrival"]["DepartureAvailability"]["mae_a"])
    departure = float(pooled["arrival"]["DepartureAug"]["mae_a"])
    s1 = float(pooled["total"]["S1"]["mae_a"])
    equal = float(pooled["total"]["Equal"]["mae_a"])
    availability_total = float(pooled["total"]["TotalAvailability"]["mae_a"])
    departure_total = float(pooled["total"]["TotalDeparture"]["mae_a"])

    def wins(items: Sequence[Mapping[str, Any]], group: str, left: str, right: str) -> int:
        return sum(
            float(item[group][left]["mae_a"]) < float(item[group][right]["mae_a"])
            for item in items
        )

    availability_horizon_wins = wins(
        by_horizon, "arrival", "DepartureAvailability", "BaseM2"
    )
    availability_month_wins = wins(
        by_month, "arrival", "DepartureAvailability", "BaseM2"
    )
    availability_total_horizon_wins = wins(
        by_horizon, "total", "TotalAvailability", "S1"
    )
    availability_total_month_wins = wins(
        by_month, "total", "TotalAvailability", "S1"
    )
    timing_horizon_wins = wins(
        by_horizon, "arrival", "DepartureAug", "DepartureAvailability"
    )
    timing_month_wins = wins(
        by_month, "arrival", "DepartureAug", "DepartureAvailability"
    )
    timing_total_horizon_wins = wins(
        by_horizon, "total", "TotalDeparture", "TotalAvailability"
    )
    timing_total_month_wins = wins(
        by_month, "total", "TotalDeparture", "TotalAvailability"
    )

    availability_component_max_degradation = max(
        _degradation(
            float(item["arrival"]["BaseM2"]["mae_a"]),
            float(item["arrival"]["DepartureAvailability"]["mae_a"]),
        )
        for item in by_horizon
    )
    availability_total_max_degradation = max(
        _degradation(
            float(item["total"]["S1"]["mae_a"]),
            float(item["total"]["TotalAvailability"]["mae_a"]),
        )
        for item in by_horizon
    )
    timing_component_max_degradation = max(
        _degradation(
            float(item["arrival"]["DepartureAvailability"]["mae_a"]),
            float(item["arrival"]["DepartureAug"]["mae_a"]),
        )
        for item in by_horizon
    )
    timing_total_max_degradation = max(
        _degradation(
            float(item["total"]["TotalAvailability"]["mae_a"]),
            float(item["total"]["TotalDeparture"]["mae_a"]),
        )
        for item in by_horizon
    )

    timing_signal = (
        departure < availability
        and timing_horizon_wins >= 3
        and timing_month_wins >= 3
        and departure_total < availability_total
        and timing_total_horizon_wins >= 3
        and timing_total_month_wins >= 3
        and timing_component_max_degradation <= MAX_DEGRADATION_FRACTION
        and timing_total_max_degradation <= MAX_DEGRADATION_FRACTION
    )
    availability_sufficient = (
        not timing_signal
        and availability < base
        and availability_horizon_wins >= 3
        and availability_month_wins >= 3
        and availability_total < s1
        and availability_total < equal
        and availability_total_horizon_wins >= 3
        and availability_total_month_wins >= 3
        and availability_component_max_degradation <= MAX_DEGRADATION_FRACTION
        and availability_total_max_degradation <= MAX_DEGRADATION_FRACTION
    )

    if timing_signal:
        decision = "TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL"
    elif availability_sufficient:
        decision = "AVAILABILITY_PROXY_SUFFICIENT_SIGNAL"
    else:
        decision = "MIXED_DEPARTURE_ATTRIBUTION_SIGNAL"

    support = {
        "availability_component_horizon_wins_vs_BaseM2": int(availability_horizon_wins),
        "availability_component_month_wins_vs_BaseM2": int(availability_month_wins),
        "availability_total_horizon_wins_vs_S1": int(availability_total_horizon_wins),
        "availability_total_month_wins_vs_S1": int(availability_total_month_wins),
        "departure_component_horizon_wins_vs_Availability": int(timing_horizon_wins),
        "departure_component_month_wins_vs_Availability": int(timing_month_wins),
        "departure_total_horizon_wins_vs_Availability": int(timing_total_horizon_wins),
        "departure_total_month_wins_vs_Availability": int(timing_total_month_wins),
        "max_availability_component_horizon_degradation_vs_BaseM2": float(
            availability_component_max_degradation
        ),
        "max_availability_total_horizon_degradation_vs_S1": float(
            availability_total_max_degradation
        ),
        "max_departure_component_horizon_degradation_vs_Availability": float(
            timing_component_max_degradation
        ),
        "max_departure_total_horizon_degradation_vs_Availability": float(
            timing_total_max_degradation
        ),
        "pooled_availability_arrival_improvement_vs_BaseM2_fraction": (
            None if base == 0 else float((base - availability) / base)
        ),
        "pooled_departure_arrival_improvement_vs_Availability_fraction": (
            None if availability == 0 else float((availability - departure) / availability)
        ),
        "pooled_availability_total_improvement_vs_S1_fraction": (
            None if s1 == 0 else float((s1 - availability_total) / s1)
        ),
        "pooled_departure_total_improvement_vs_Availability_fraction": (
            None
            if availability_total == 0
            else float((availability_total - departure_total) / availability_total)
        ),
    }
    return decision, support


def _write_private_task(stage: Path, record: Mapping[str, Any]) -> tuple[str, str]:
    name = f"{record['month']}_h{int(record['horizon']):03d}.npz"
    path = stage / name
    np.savez_compressed(
        path,
        issue_times=record["issue_times"],
        day_start_utc_s=record["day_starts"],
        y_true=record["total_truth"],
        arrival_truth=record["arrival_truth"],
        base_arrival_predictions=record["base_arrival"],
        availability_arrival_predictions=record["availability_arrival"],
        departure_arrival_predictions=record["departure_arrival"],
        s1_existing_predictions=record["s1_existing"],
        s1_predictions=record["s1_total"],
        equal_predictions=record["equal_total"],
        total_availability_predictions=record["availability_total"],
        total_departure_predictions=record["departure_total"],
    )
    return name, _sha256_file(path)


def _assert_r7_replay(pooled: Mapping[str, Any]) -> None:
    observed = {
        "base_arrival_mae_a": float(pooled["arrival"]["BaseM2"]["mae_a"]),
        "departure_arrival_mae_a": float(pooled["arrival"]["DepartureAug"]["mae_a"]),
        "s1_total_mae_a": float(pooled["total"]["S1"]["mae_a"]),
        "equal_total_mae_a": float(pooled["total"]["Equal"]["mae_a"]),
        "departure_total_mae_a": float(pooled["total"]["TotalDeparture"]["mae_a"]),
    }
    if any(
        not np.isclose(observed[key], expected, rtol=0.0, atol=1e-10)
        for key, expected in _EXPECTED_R7_REPLAY.items()
    ):
        raise R7D1Error("R7_REPLAY_INVALID")


def run_r7_d1(
    *,
    authorized: bool,
    interim_root: str | Path,
    processed_root: str | Path,
    r7_private_run: str | Path,
    private_output_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
    progress: Progress | None = None,
) -> dict[str, Any]:
    if authorized is not True:
        raise R7D1Error("R7_D1_NOT_AUTHORIZED")

    repo = Path(repo_root).resolve(strict=True)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    r7_root = Path(r7_private_run).resolve(strict=True)
    output = Path(private_output_root).resolve(strict=False)
    if output.exists() or any(path.is_symlink() for path in (interim, processed, r7_root)):
        raise R7D1Error("OUTPUT_TOPOLOGY_INVALID")

    _git_semantic_verify(code_commit, repo_root=repo)
    source_protocol = load_development_expert_protocol(
        repo / "code/configs/acn_jpl_development_experts_2019.yaml"
    )
    structured_protocol = load_structured_protocol(
        repo / "code/configs/acn_jpl_structured_baseline_2019.yaml"
    )
    if (
        source_protocol.protocol_sha256 != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256
        or structured_protocol.protocol_sha256 != EXPECTED_STRUCTURED_PROTOCOL_SHA256
        or tuple(contract.month for contract in source_protocol.months) != DEVELOPMENT_MONTHS
        or tuple(contract.month for contract in structured_protocol.months) != DEVELOPMENT_MONTHS
        or source_protocol.test_start_local_day != 18
        or any(
            source_protocol.selected_parameter_sha256["M2"][horizon]
            != SELECTED_M2_PARAMETER_SHA256[horizon]
            for horizon in HORIZONS_MINUTES
        )
    ):
        raise R7D1Error("PROTOCOL_INVALID")

    try:
        r7_manifest = _verify_private_manifest(
            r7_root,
            expected_sha256=EXPECTED_R7_PRIVATE_MANIFEST_SHA256,
            schema_version="evcf-jpl-r7-c0-private-cache/v1",
            entries_key="entries",
        )
    except Exception as exc:
        raise R7D1Error("R7_PRIVATE_CACHE_IDENTITY_INVALID") from exc
    if (
        r7_manifest.get("code_commit") != R7_REVIEWED_EXECUTABLE
        or r7_manifest.get("protocol_commit") != R7_PROTOCOL_COMMIT
        or r7_manifest.get("source_r6_status_sha256")
        != "52bf3d7753b095a0faf39bc9aaefbd07b2c11f406ab05abd4bd1534e921dacce"
    ):
        raise R7D1Error("R7_PRIVATE_CACHE_IDENTITY_INVALID")

    try:
        selected = load_selected_hgb_parameters(protocol=source_protocol, repo_root=repo)
    except DevelopmentExpertError as exc:
        raise R7D1Error(exc.reason_code) from exc

    source_contracts = {contract.month: contract for contract in source_protocol.months}
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".evcf-r7-d1-", dir=output.parent))
    records: list[dict[str, Any]] = []
    private_entries: list[dict[str, str]] = []
    fit_count = 0
    try:
        for structured_contract in structured_protocol.months:
            month = structured_contract.month
            if month not in DEVELOPMENT_MONTHS:
                raise R7D1Error("HOLDOUT_ACCESS_ATTEMPT")
            source_contract = source_contracts.get(month)
            if (
                source_contract is None
                or source_contract.processed_snapshot_sha256
                != structured_contract.processed_snapshot_sha256
            ):
                raise R7D1Error("PROTOCOL_INVALID")
            try:
                data = load_month_data(
                    contract=source_contract,
                    interim_root=interim,
                    processed_root=processed,
                )
                cleaned = _load_cleaned_current_sessions(
                    interim / month / "cleaned_sessions.jsonl.gz",
                    expected_count=structured_contract.cleaned_session_count,
                )
                _, arrival_labels = _component_label_matrices(
                    sessions=cleaned,
                    issue_times=data.issue_times,
                    total_labels=data.labels,
                )
            except Exception as exc:
                reason = getattr(exc, "reason_code", "SOURCE_DATA_INVALID")
                raise R7D1Error(reason) from exc

            arrival_data = MonthData(
                month=data.month,
                issue_times=data.issue_times,
                labels=arrival_labels,
                blocks=data.blocks,
                processed_snapshot_sha256=data.processed_snapshot_sha256,
            )
            availability_block = _availability_block(data.blocks["M2"], data.blocks["M3"])
            if progress is not None:
                progress(f"R7_D1_STAGE=MONTH_START; MONTH={month}")
            for horizon in HORIZONS_MINUTES:
                try:
                    availability = _predict_custom_arm(
                        data=arrival_data,
                        block=availability_block,
                        horizon_minutes=horizon,
                        params=selected[("M2", horizon)],
                        encoded_width=AVAILABILITY_ENCODED_WIDTH,
                        native_thread_limit=source_protocol.native_thread_limit,
                    )
                except Exception as exc:
                    reason = getattr(exc, "reason_code", "MODEL_FIT_FAILED")
                    raise R7D1Error(reason) from exc
                fit_count += int(availability["fit_count"])
                reference = _load_r7_reference(r7_root, month=month, horizon=horizon)
                record = _record(
                    month=month,
                    horizon=horizon,
                    reference=reference,
                    availability=availability,
                )
                name, digest = _write_private_task(stage, record)
                private_entries.append({"name": name, "sha256": digest})
                records.append(record)
                if progress is not None:
                    progress(
                        "R7_D1_STAGE=HORIZON_COMPLETE; "
                        f"MONTH={month}; HORIZON={horizon}; FITS={fit_count}/{EXPECTED_FIT_COUNT}"
                    )
            if progress is not None:
                progress(f"R7_D1_STAGE=MONTH_COMPLETE; MONTH={month}")

        if fit_count != EXPECTED_FIT_COUNT or len(records) != 20 or len(private_entries) != 20:
            raise R7D1Error("FIT_COUNT_INVALID")

        pooled = _summary(records)
        _assert_r7_replay(pooled)
        by_horizon = []
        for horizon in HORIZONS_MINUTES:
            selected_records = [record for record in records if int(record["horizon"]) == horizon]
            summary = _summary(selected_records)
            if int(summary["arrival"]["BaseM2"]["n"]) != EXPECTED_ROWS_PER_HORIZON:
                raise R7D1Error("COMMON_ROW_IDENTITY_INVALID")
            by_horizon.append({"horizon_minutes": horizon, **summary})
        by_month = []
        for month in DEVELOPMENT_MONTHS:
            selected_records = [record for record in records if str(record["month"]) == month]
            summary = _summary(selected_records)
            if int(summary["arrival"]["BaseM2"]["n"]) != EXPECTED_ROWS_BY_MONTH[month] * 5:
                raise R7D1Error("COMMON_ROW_IDENTITY_INVALID")
            by_month.append({"month": month, **summary})
        cells = [
            {
                "month": record["month"],
                "horizon_minutes": record["horizon"],
                **_summary([record]),
            }
            for record in records
        ]
        if int(pooled["arrival"]["BaseM2"]["n"]) != EXPECTED_RECORD_COUNT:
            raise R7D1Error("COMMON_ROW_IDENTITY_INVALID")
        decision, support = decide_attribution(pooled, by_horizon, by_month)

        manifest = {
            "schema_version": "evcf-jpl-r7-d1-private-cache/v1",
            "source_r7_status_sha256": SOURCE_R7_STATUS_SHA256,
            "source_r7_private_manifest_sha256": EXPECTED_R7_PRIVATE_MANIFEST_SHA256,
            "code_commit": code_commit,
            "protocol_commit": D1_PROTOCOL_COMMIT,
            "entries": private_entries,
        }
        manifest_path = stage / "private_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n",
            encoding="ascii",
            newline="\n",
        )
        manifest_sha = _sha256_file(manifest_path)
        stage.replace(output)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    return {
        "schema_version": "evcf-jpl-r7-d1-summary/v1",
        "status": "COMPLETE",
        "decision": decision,
        "decision_support": support,
        "code_commit": code_commit,
        "protocol_commit": D1_PROTOCOL_COMMIT,
        "source_r7_status_sha256": SOURCE_R7_STATUS_SHA256,
        "source_r7_decision": SOURCE_R7_DECISION,
        "source_r7_decision_unchanged": True,
        "source_r7_private_manifest_sha256": EXPECTED_R7_PRIVATE_MANIFEST_SHA256,
        "r7_reviewed_executable": R7_REVIEWED_EXECUTABLE,
        "fit_count": fit_count,
        "private_cache_file_count": len(private_entries),
        "private_manifest_sha256": manifest_sha,
        "pooled_overall": pooled,
        "pooled_by_horizon": by_horizon,
        "pooled_by_month": by_month,
        "month_horizon_cells": cells,
        "holdout_accessed": False,
        "reference_models_retrained": False,
        "r7_departure_retrained": False,
        "hyperparameter_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "gate_trained": False,
        "moe_trained": False,
        "neural_model_trained": False,
        "survival_model_trained": False,
        "tpp_model_trained": False,
    }
