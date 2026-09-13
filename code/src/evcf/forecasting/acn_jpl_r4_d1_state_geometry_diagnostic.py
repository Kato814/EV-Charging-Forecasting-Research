"""Read-only R4-D1 state-geometry failure diagnostic."""

from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

import evcf.forecasting.acn_jpl_r4_information_sufficiency_gate as r4
from evcf.forecasting.acn_jpl_development_experts_compat import (
    DevelopmentExpertError,
    load_development_expert_protocol,
    load_month_data,
)
from evcf.forecasting.acn_jpl_gate1_models import RidgePreprocessor
from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
)

SOURCE_R4_STATUS_SHA256 = (
    "a8b7142e0361b5cd56e53c7de99d8e699a27e1aee78728810773c127f385823f"
)
SOURCE_R4_CODE_COMMIT = "d3f00320e90aeb213d97d63d3460f58d495dd34a"
SOURCE_R4_DECISION = "MIXED_STATE_ALIASING_SIGNAL"
D1_PROTOCOL_MERGE_COMMIT = "e20481f304d416433ca2d30b9e3bae57a017a8f6"
ACCEPTED_REFERENCE_RELATIVE = PurePosixPath(
    "code/configs/acn_jpl_r4_i0_accepted_reference_20260913.json"
)
REPLAY_ATOL = 1e-12
EXPECTED_EXTENSION_ENCODED_WIDTH = r4.M3_ENCODED_WIDTH - r4.M2_ENCODED_WIDTH

IMPLEMENTATION_PATHS = (
    "docs/JPL_R4_D1_STATE_GEOMETRY_DIAGNOSTIC_PROTOCOL_20260913.md",
    str(ACCEPTED_REFERENCE_RELATIVE),
    "code/src/evcf/forecasting/acn_jpl_r4_information_sufficiency_gate.py",
    "code/src/evcf/forecasting/acn_jpl_r4_d1_state_geometry_diagnostic.py",
    "scripts/run_jpl_r4_d1_state_geometry_diagnostic.py",
)

_CONTINUOUS_KEYS = (
    "C_Level",
    "C_M2",
    "C_M3",
    "Q2_Level",
    "Q2_M2",
    "Q2_M3",
    "QE_Level",
    "QE_M2",
    "QE_M3",
    "Q3_Level",
    "Q3_M2",
    "Q3_M3",
    "D_Level",
    "D_M2",
    "D_M3",
    "DeltaFuture_M3_Level",
    "DeltaFuture_M3_M2",
)
_OVERLAP_KEYS = ("O_Level_M2", "O_Level_M3", "O_M2_M3")
Progress = Callable[[str], None]


class R4D1Error(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = (
            reason_code
            if isinstance(reason_code, str)
            and reason_code
            and reason_code.replace("_", "").isalnum()
            else "UNEXPECTED_ERROR"
        )
        super().__init__(self.reason_code)


def _verify_git(code_commit: str, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R4D1Error("IMPLEMENTATION_DRIFT")
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
        raise R4D1Error("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R4D1Error("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode:
            raise R4D1Error("IMPLEMENTATION_DRIFT")
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            "--no-ext-diff",
            code_commit,
            "--",
            *IMPLEMENTATION_PATHS,
        ],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if diff.returncode:
        raise R4D1Error("IMPLEMENTATION_DRIFT")


def load_accepted_reference(repo_root: Path) -> Mapping[str, Any]:
    path = repo_root / ACCEPTED_REFERENCE_RELATIVE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R4D1Error("ACCEPTED_REFERENCE_INVALID") from exc
    if not isinstance(payload, dict):
        raise R4D1Error("ACCEPTED_REFERENCE_INVALID")
    required = {
        "schema_version",
        "source_status_sha256",
        "code_commit",
        "protocol_merge_commit",
        "decision",
        "support",
        "pooled_overall",
        "pooled_by_horizon",
        "pooled_by_month",
        "month_horizon_cells",
    }
    if not required.issubset(payload):
        raise R4D1Error("ACCEPTED_REFERENCE_INVALID")
    if payload["source_status_sha256"] != SOURCE_R4_STATUS_SHA256:
        raise R4D1Error("ACCEPTED_REFERENCE_INVALID")
    if payload["code_commit"] != SOURCE_R4_CODE_COMMIT:
        raise R4D1Error("ACCEPTED_REFERENCE_INVALID")
    if payload["decision"] != SOURCE_R4_DECISION:
        raise R4D1Error("ACCEPTED_REFERENCE_INVALID")
    return payload


def _assert_close(actual: Any, expected: Any, context: str) -> None:
    if isinstance(expected, bool):
        if actual is not expected:
            raise R4D1Error("R4_REPLAY_MISMATCH")
        return
    if isinstance(expected, int) and not isinstance(expected, bool):
        if int(actual) != expected:
            raise R4D1Error("R4_REPLAY_MISMATCH")
        return
    if isinstance(expected, str):
        if actual != expected:
            raise R4D1Error("R4_REPLAY_MISMATCH")
        return
    try:
        actual_value = float(actual)
        expected_value = float(expected)
    except (TypeError, ValueError) as exc:
        raise R4D1Error("R4_REPLAY_MISMATCH") from exc
    if not (
        math.isfinite(actual_value)
        and math.isfinite(expected_value)
        and math.isclose(actual_value, expected_value, rel_tol=0.0, abs_tol=REPLAY_ATOL)
    ):
        raise R4D1Error("R4_REPLAY_MISMATCH")


def _compare_metric_mapping(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    context: str,
) -> None:
    for key, expected_value in expected.items():
        if key not in actual:
            raise R4D1Error("R4_REPLAY_MISMATCH")
        _assert_close(actual[key], expected_value, f"{context}.{key}")


def assert_r4_replay_matches(
    replay_public: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> None:
    if replay_public.get("status") != "COMPLETE":
        raise R4D1Error("R4_REPLAY_MISMATCH")
    if replay_public.get("decision") != reference["decision"]:
        raise R4D1Error("R4_REPLAY_MISMATCH")
    if replay_public.get("fit_count") != 0:
        raise R4D1Error("R4_REPLAY_MISMATCH")

    actual_support = replay_public.get("support")
    expected_support = reference["support"]
    if not isinstance(actual_support, Mapping) or not isinstance(expected_support, Mapping):
        raise R4D1Error("R4_REPLAY_MISMATCH")
    _compare_metric_mapping(actual_support, expected_support, "support")

    pooled = replay_public.get("pooled_overall")
    if not isinstance(pooled, Mapping):
        raise R4D1Error("R4_REPLAY_MISMATCH")
    _compare_metric_mapping(pooled, reference["pooled_overall"], "pooled")

    actual_horizons = replay_public.get("pooled_by_horizon")
    expected_horizons = reference["pooled_by_horizon"]
    if not isinstance(actual_horizons, list) or len(actual_horizons) != len(expected_horizons):
        raise R4D1Error("R4_REPLAY_MISMATCH")
    actual_horizon_map = {int(item["horizon_minutes"]): item for item in actual_horizons}
    for expected in expected_horizons:
        horizon = int(expected["horizon_minutes"])
        if horizon not in actual_horizon_map:
            raise R4D1Error("R4_REPLAY_MISMATCH")
        _compare_metric_mapping(
            actual_horizon_map[horizon],
            expected,
            f"horizon.{horizon}",
        )

    actual_months = replay_public.get("pooled_by_month")
    expected_months = reference["pooled_by_month"]
    if not isinstance(actual_months, list) or len(actual_months) != len(expected_months):
        raise R4D1Error("R4_REPLAY_MISMATCH")
    actual_month_map = {str(item["month"]): item for item in actual_months}
    for expected in expected_months:
        month = str(expected["month"])
        if month not in actual_month_map:
            raise R4D1Error("R4_REPLAY_MISMATCH")
        _compare_metric_mapping(actual_month_map[month], expected, f"month.{month}")

    actual_cells = replay_public.get("month_horizon_cells")
    expected_cells = reference["month_horizon_cells"]
    if not isinstance(actual_cells, list) or len(actual_cells) != len(expected_cells):
        raise R4D1Error("R4_REPLAY_MISMATCH")
    actual_cell_map = {
        (str(item["month"]), int(item["horizon_minutes"])): item for item in actual_cells
    }
    for expected in expected_cells:
        key = (str(expected["month"]), int(expected["horizon_minutes"]))
        actual = actual_cell_map.get(key)
        if actual is None:
            raise R4D1Error("R4_REPLAY_MISMATCH")
        for count_key in (
            "oos_records",
            "supported_records",
            "unsupported_candidate_floor",
            "unsupported_m3_distance",
        ):
            _assert_close(actual[count_key], expected[count_key], f"cell.{key}.{count_key}")
        _assert_close(
            actual["supported_fraction"],
            expected["supported_fraction"],
            f"cell.{key}.supported_fraction",
        )
        actual_metrics = actual.get("metrics")
        expected_metrics = expected.get("metrics")
        if not isinstance(actual_metrics, Mapping) or not isinstance(expected_metrics, Mapping):
            raise R4D1Error("R4_REPLAY_MISMATCH")
        _compare_metric_mapping(actual_metrics, expected_metrics, f"cell.{key}.metrics")


def m3_extension_encoded_indices(
    *,
    m2_feature_names: Sequence[str],
    m3_feature_names: Sequence[str],
    m3_nullable_mask: np.ndarray,
) -> np.ndarray:
    m2_names = tuple(m2_feature_names)
    m3_names = tuple(m3_feature_names)
    nullable = np.asarray(m3_nullable_mask, dtype=np.bool_)
    if (
        len(m2_names) != r4.M2_RAW_WIDTH
        or len(m3_names) != r4.M3_RAW_WIDTH
        or m3_names[: len(m2_names)] != m2_names
        or nullable.shape != (len(m3_names),)
    ):
        raise R4D1Error("M3_EXTENSION_SCHEMA_INVALID")

    raw_extension = np.arange(len(m2_names), len(m3_names), dtype=np.int64)
    nullable_positions = np.flatnonzero(nullable).astype(np.int64)
    extension_indicator_ordinals = np.flatnonzero(
        nullable_positions >= len(m2_names)
    ).astype(np.int64)
    indicator_extension = len(m3_names) + extension_indicator_ordinals
    result = np.concatenate((raw_extension, indicator_extension)).astype(np.int64)
    if (
        len(result) != EXPECTED_EXTENSION_ENCODED_WIDTH
        or np.any(result < 0)
        or np.any(result >= r4.M3_ENCODED_WIDTH)
        or len(np.unique(result)) != len(result)
    ):
        raise R4D1Error("M3_EXTENSION_SCHEMA_INVALID")
    return result


def _mean_rms(
    test_vector: np.ndarray,
    candidate_vectors: np.ndarray,
    selected_rows: np.ndarray,
) -> float:
    selected = np.asarray(selected_rows, dtype=np.int64)
    if selected.shape != (r4.K_ANALOGS,):
        raise R4D1Error("GEOMETRY_SELECTION_INVALID")
    return float(np.mean(r4.rms_distances(test_vector, candidate_vectors[selected])))


def arm_geometry(
    *,
    selected_rows: np.ndarray,
    candidate_level: np.ndarray,
    test_level: float,
    candidate_m2: np.ndarray,
    test_m2: np.ndarray,
    candidate_m3: np.ndarray,
    test_m3: np.ndarray,
    extension_indices: np.ndarray,
) -> tuple[float, float, float, float]:
    selected = np.asarray(selected_rows, dtype=np.int64)
    level = np.asarray(candidate_level, dtype=np.float64)
    if selected.shape != (r4.K_ANALOGS,) or not math.isfinite(float(test_level)):
        raise R4D1Error("GEOMETRY_SELECTION_INVALID")
    current_gap = float(np.mean(np.abs(level[selected] - float(test_level))))
    q2 = _mean_rms(test_m2, candidate_m2, selected)
    q3 = _mean_rms(test_m3, candidate_m3, selected)
    ext = np.asarray(extension_indices, dtype=np.int64)
    qe = _mean_rms(test_m3[ext], candidate_m3[:, ext], selected)
    if not all(math.isfinite(value) for value in (current_gap, q2, qe, q3)):
        raise R4D1Error("GEOMETRY_INVALID")
    return current_gap, q2, qe, q3


def overlap_count(left: np.ndarray, right: np.ndarray) -> int:
    left_values = np.asarray(left, dtype=np.int64)
    right_values = np.asarray(right, dtype=np.int64)
    if left_values.shape != (r4.K_ANALOGS,) or right_values.shape != (r4.K_ANALOGS,):
        raise R4D1Error("OVERLAP_INPUT_INVALID")
    if len(np.unique(left_values)) != r4.K_ANALOGS or len(np.unique(right_values)) != r4.K_ANALOGS:
        raise R4D1Error("OVERLAP_INPUT_INVALID")
    return len(set(left_values.tolist()).intersection(right_values.tolist()))


def _continuous_summary(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or not len(array) or not np.isfinite(array).all():
        raise R4D1Error("GEOMETRY_AGGREGATE_INVALID")
    return {
        "mean": float(np.mean(array)),
        "median": float(np.median(array)),
    }


def _overlap_summary(values: Sequence[int]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.int64)
    if array.ndim != 1 or not len(array) or np.any((array < 0) | (array > r4.K_ANALOGS)):
        raise R4D1Error("GEOMETRY_AGGREGATE_INVALID")
    result: dict[str, float] = {"mean": float(np.mean(array))}
    for overlap in range(r4.K_ANALOGS + 1):
        result[f"fraction_{overlap}"] = float(np.mean(array == overlap))
    return result


def aggregate_geometry(records: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    result: dict[str, Any] = {"records": len(records)}
    result["geometry"] = {
        "current_level_gap": {
            arm: _continuous_summary([float(item[f"C_{arm}"]) for item in records])
            for arm in ("Level", "M2", "M3")
        },
        "m2_rms": {
            arm: _continuous_summary([float(item[f"Q2_{arm}"]) for item in records])
            for arm in ("Level", "M2", "M3")
        },
        "m3_extension_rms": {
            arm: _continuous_summary([float(item[f"QE_{arm}"]) for item in records])
            for arm in ("Level", "M2", "M3")
        },
        "m3_full_rms": {
            arm: _continuous_summary([float(item[f"Q3_{arm}"]) for item in records])
            for arm in ("Level", "M2", "M3")
        },
    }
    result["neighbor_overlap"] = {
        "Level_M2": _overlap_summary([int(item["O_Level_M2"]) for item in records]),
        "Level_M3": _overlap_summary([int(item["O_Level_M3"]) for item in records]),
        "M2_M3": _overlap_summary([int(item["O_M2_M3"]) for item in records]),
    }
    result["future_divergence"] = {
        "D_Level": _continuous_summary([float(item["D_Level"]) for item in records]),
        "D_M2": _continuous_summary([float(item["D_M2"]) for item in records]),
        "D_M3": _continuous_summary([float(item["D_M3"]) for item in records]),
        "Delta_M3_Level": _continuous_summary(
            [float(item["DeltaFuture_M3_Level"]) for item in records]
        ),
        "Delta_M3_M2": _continuous_summary(
            [float(item["DeltaFuture_M3_M2"]) for item in records]
        ),
    }
    return result


def run_diagnostic(
    *,
    interim_root: str | Path,
    processed_root: str | Path,
    code_commit: str,
    repo_root: str | Path,
    progress: Progress | None = None,
) -> dict[str, Any]:
    repo = Path(repo_root).resolve(strict=True)
    interim = Path(interim_root).resolve(strict=True)
    processed = Path(processed_root).resolve(strict=True)
    _verify_git(code_commit, repo)
    reference = load_accepted_reference(repo)

    if progress is not None:
        progress("R4_D1_STAGE=REPLAY_R4")
    try:
        replay_result = r4.run_gate(
            interim_root=interim,
            processed_root=processed,
            code_commit=code_commit,
            repo_root=repo,
            progress=None,
        )
    except r4.R4I0Error as exc:
        raise R4D1Error(exc.reason_code) from exc
    replay_public = replay_result.to_public_dict()
    assert_r4_replay_matches(replay_public, reference)

    protocol = load_development_expert_protocol(
        repo / "code/configs/acn_jpl_development_experts_2019.yaml"
    )
    if protocol.protocol_sha256 != EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256:
        raise R4D1Error("PROTOCOL_INVALID")

    records: list[dict[str, Any]] = []
    preprocessor_fit_count = replay_result.preprocessor_fit_count

    for contract in protocol.months:
        if contract.month not in r4.DEVELOPMENT_MONTHS:
            raise R4D1Error("HOLDOUT_ACCESS_ATTEMPT")
        try:
            data = load_month_data(
                contract=contract,
                interim_root=interim,
                processed_root=processed,
            )
        except DevelopmentExpertError as exc:
            raise R4D1Error(exc.reason_code) from exc

        m2 = data.blocks["M2"]
        m3 = data.blocks["M3"]
        try:
            station_index = m2.feature_names.index(r4.STATION_CURRENT_FEATURE)
        except ValueError as exc:
            raise R4D1Error("STATE_SCHEMA_INVALID") from exc
        extension_indices = m3_extension_encoded_indices(
            m2_feature_names=m2.feature_names,
            m3_feature_names=m3.feature_names,
            m3_nullable_mask=m3.nullable_mask,
        )

        issue_times = np.asarray(data.issue_times, dtype=np.int64)
        labels = np.asarray(data.labels, dtype=np.float64)
        day_starts = r4._day_starts(issue_times)
        clock_slots = r4._clock_slots(issue_times)
        local_days = np.asarray(
            [
                datetime.fromtimestamp(int(value), timezone.utc)
                .astimezone(r4._ZONE)
                .day
                for value in issue_times
            ],
            dtype=np.int16,
        )
        test_days = np.unique(day_starts[local_days >= protocol.test_start_local_day])

        for horizon_position, horizon in enumerate(r4.HORIZONS_MINUTES):
            cell_supported = 0
            for day_start in test_days:
                eligible = np.flatnonzero(
                    issue_times + horizon * 60 <= int(day_start)
                ).astype(np.int64)
                test_rows = np.flatnonzero(day_starts == int(day_start)).astype(np.int64)
                if (
                    not len(eligible)
                    or not len(test_rows)
                    or np.intersect1d(eligible, test_rows).size
                ):
                    raise R4D1Error("ROLLING_SPLIT_INVALID")

                m2_pre = RidgePreprocessor().fit(m2, eligible)
                m3_pre = RidgePreprocessor().fit(m3, eligible)
                preprocessor_fit_count += 2
                m2_history = m2_pre.transform(m2, eligible)
                m3_history = m3_pre.transform(m3, eligible)
                m2_test = m2_pre.transform(m2, test_rows)
                m3_test = m3_pre.transform(m3, test_rows)

                for test_position, test_row in enumerate(test_rows):
                    slot = clock_slots[test_row]
                    candidate_positions = np.flatnonzero(
                        clock_slots[eligible] == slot
                    ).astype(np.int64)
                    candidate_rows = eligible[candidate_positions]
                    if len(candidate_rows) < r4.MIN_CANDIDATES:
                        continue

                    selection = r4.select_analogs(
                        candidate_issue_times=issue_times[candidate_rows],
                        candidate_level=m2_history[candidate_positions, station_index],
                        test_level=float(m2_test[test_position, station_index]),
                        candidate_m2=m2_history[candidate_positions],
                        test_m2=m2_test[test_position],
                        candidate_m3=m3_history[candidate_positions],
                        test_m3=m3_test[test_position],
                    )
                    if not selection.supported:
                        continue

                    candidate_level = m2_history[candidate_positions, station_index]
                    candidate_m2 = m2_history[candidate_positions]
                    candidate_m3 = m3_history[candidate_positions]
                    test_level = float(m2_test[test_position, station_index])
                    test_m2 = m2_test[test_position]
                    test_m3 = m3_test[test_position]
                    selections = {
                        "Level": selection.level_rows,
                        "M2": selection.m2_rows,
                        "M3": selection.m3_rows,
                    }
                    record: dict[str, Any] = {
                        "month": contract.month,
                        "horizon_minutes": horizon,
                    }
                    for arm, selected in selections.items():
                        current_gap, q2, qe, q3 = arm_geometry(
                            selected_rows=selected,
                            candidate_level=candidate_level,
                            test_level=test_level,
                            candidate_m2=candidate_m2,
                            test_m2=test_m2,
                            candidate_m3=candidate_m3,
                            test_m3=test_m3,
                            extension_indices=extension_indices,
                        )
                        record[f"C_{arm}"] = current_gap
                        record[f"Q2_{arm}"] = q2
                        record[f"QE_{arm}"] = qe
                        record[f"Q3_{arm}"] = q3

                    record["O_Level_M2"] = overlap_count(
                        selection.level_rows, selection.m2_rows
                    )
                    record["O_Level_M3"] = overlap_count(
                        selection.level_rows, selection.m3_rows
                    )
                    record["O_M2_M3"] = overlap_count(
                        selection.m2_rows, selection.m3_rows
                    )

                    target = float(labels[test_row, horizon_position])
                    candidate_targets = labels[candidate_rows, horizon_position]
                    d_level = r4.analog_divergence(
                        target, candidate_targets[selection.level_rows]
                    )
                    d_m2 = r4.analog_divergence(
                        target, candidate_targets[selection.m2_rows]
                    )
                    d_m3 = r4.analog_divergence(
                        target, candidate_targets[selection.m3_rows]
                    )
                    record["D_Level"] = d_level
                    record["D_M2"] = d_m2
                    record["D_M3"] = d_m3
                    record["DeltaFuture_M3_Level"] = d_m3 - d_level
                    record["DeltaFuture_M3_M2"] = d_m3 - d_m2
                    records.append(record)
                    cell_supported += 1

            if progress is not None:
                progress(
                    "R4_D1_STAGE=MONTH_HORIZON; "
                    f"MONTH={contract.month}; HORIZON={horizon}; "
                    f"SUPPORTED={cell_supported}"
                )

    if len(records) != int(reference["support"]["supported_origin_horizon_records"]):
        raise R4D1Error("R4_REPLAY_MISMATCH")

    pooled = aggregate_geometry(records)
    by_horizon = []
    for horizon in r4.HORIZONS_MINUTES:
        metrics = aggregate_geometry(
            [item for item in records if item["horizon_minutes"] == horizon]
        )
        by_horizon.append(
            {"horizon_minutes": horizon, **({} if metrics is None else metrics)}
        )
    by_month = []
    for month in r4.DEVELOPMENT_MONTHS:
        metrics = aggregate_geometry([item for item in records if item["month"] == month])
        by_month.append({"month": month, **({} if metrics is None else metrics)})
    cells = []
    for month in r4.DEVELOPMENT_MONTHS:
        for horizon in r4.HORIZONS_MINUTES:
            metrics = aggregate_geometry(
                [
                    item
                    for item in records
                    if item["month"] == month and item["horizon_minutes"] == horizon
                ]
            )
            cells.append(
                {
                    "month": month,
                    "horizon_minutes": horizon,
                    **({} if metrics is None else metrics),
                }
            )

    return {
        "schema_version": "evcf-jpl-r4-d1-state-geometry-summary/v1",
        "status": "COMPLETE",
        "code_commit": code_commit,
        "d1_protocol_merge_commit": D1_PROTOCOL_MERGE_COMMIT,
        "source_r4_status_sha256": SOURCE_R4_STATUS_SHA256,
        "source_r4_code_commit": SOURCE_R4_CODE_COMMIT,
        "source_r4_decision": SOURCE_R4_DECISION,
        "scientific_decision_unchanged": True,
        "r4_replay_verified": True,
        "pooled_overall": pooled,
        "pooled_by_horizon": by_horizon,
        "pooled_by_month": by_month,
        "month_horizon_cells": cells,
        "preprocessor_fit_count": preprocessor_fit_count,
        "fit_count": 0,
        "model_fit_attempted": False,
        "holdout_accessed": False,
        "reference_models_retrained": False,
        "alternate_analog_rule": False,
        "metric_learning": False,
        "pca_or_feature_selection": False,
        "target_informed_matching": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
    }
