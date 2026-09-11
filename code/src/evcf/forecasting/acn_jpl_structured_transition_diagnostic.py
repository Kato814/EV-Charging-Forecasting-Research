"""Read-only transition-map diagnostics for the JPL structured S1 development run."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from evcf.forecasting.acn_jpl_structured_mixed_diagnostic import (
    DEVELOPMENT_MONTHS,
    EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256,
    EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256,
    FINAL_HOLDOUT_MONTHS,
    HORIZONS_MINUTES,
    StructuredMixedDiagnosticError,
    _load_pair,
    _verify_manifest,
)

_ZONE = ZoneInfo("America/Los_Angeles")
_EPS = 1e-9


def _mae(truth: np.ndarray, prediction: np.ndarray, mask: np.ndarray) -> float | None:
    if not np.any(mask):
        return None
    return float(np.mean(np.abs(prediction[mask] - truth[mask])))


def _pair_metrics(
    truth: np.ndarray,
    s1: np.ndarray,
    equal: np.ndarray,
    mask: np.ndarray,
) -> dict[str, Any]:
    n = int(np.sum(mask))
    if n == 0:
        return {
            "n": 0,
            "S1_mae_a": None,
            "equal_mae_a": None,
            "S1_minus_equal_mae_a": None,
            "S1_vs_equal_improvement_fraction": None,
        }
    s1_mae = float(np.mean(np.abs(s1[mask] - truth[mask])))
    equal_mae = float(np.mean(np.abs(equal[mask] - truth[mask])))
    return {
        "n": n,
        "S1_mae_a": s1_mae,
        "equal_mae_a": equal_mae,
        "S1_minus_equal_mae_a": s1_mae - equal_mae,
        "S1_vs_equal_improvement_fraction": (
            None if equal_mae == 0 else float((equal_mae - s1_mae) / equal_mae)
        ),
    }


def _composition_bins(record: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    total = record["y_true"].astype(np.float64)
    existing = record["existing_truth"].astype(np.float64)
    arrival = record["arrival_truth"].astype(np.float64)
    s1 = record["structured_predictions"].astype(np.float64)
    equal = record["equal_predictions"].astype(np.float64)
    active = total > _EPS
    share = np.zeros_like(total)
    share[active] = arrival[active] / total[active]

    definitions = (
        ("total_zero", ~active),
        ("existing_only", active & (arrival <= _EPS)),
        ("arrival_share_0_25", active & (share > 0.0) & (share <= 0.25)),
        ("arrival_share_25_50", active & (share > 0.25) & (share <= 0.50)),
        ("arrival_share_50_75", active & (share > 0.50) & (share <= 0.75)),
        (
            "arrival_share_75_100",
            active & (share > 0.75) & (existing > _EPS),
        ),
        ("arrival_only", active & (existing <= _EPS)),
    )

    rows: list[dict[str, Any]] = []
    covered = np.zeros(len(total), dtype=bool)
    for label, mask in definitions:
        if np.any(covered & mask):
            raise StructuredMixedDiagnosticError("TRANSITION_BIN_OVERLAP")
        covered |= mask
        metrics = _pair_metrics(total, s1, equal, mask)
        n = metrics["n"]
        rows.append(
            {
                "composition_bin": label,
                **metrics,
                "mean_total_truth_a": (
                    None if n == 0 else float(np.mean(total[mask]))
                ),
                "mean_arrival_share": (
                    None
                    if n == 0 or label == "total_zero"
                    else float(np.mean(share[mask]))
                ),
                "existing_branch_mae_a": _mae(
                    existing,
                    record["existing_predictions"],
                    mask,
                ),
                "arrival_branch_mae_a": _mae(
                    arrival,
                    record["arrival_predictions"],
                    mask,
                ),
            }
        )
    if not np.all(covered):
        raise StructuredMixedDiagnosticError("TRANSITION_BIN_INCOMPLETE")
    return rows


def _merge_records(records: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    keys = set(records[0])
    if any(set(item) != keys for item in records):
        raise StructuredMixedDiagnosticError("PRIVATE_CACHE_SCHEMA_INVALID")
    return {key: np.concatenate([item[key] for item in records]) for key in keys}


def _hour_rows(
    *,
    month: str,
    horizon: int,
    record: dict[str, np.ndarray],
) -> list[dict[str, Any]]:
    hours = np.asarray(
        [
            datetime.fromtimestamp(int(value), timezone.utc).astimezone(_ZONE).hour
            for value in record["issue_times"]
        ],
        dtype=np.int16,
    )
    rows: list[dict[str, Any]] = []
    for hour in range(24):
        mask = hours == hour
        metrics = _pair_metrics(
            record["y_true"],
            record["structured_predictions"],
            record["equal_predictions"],
            mask,
        )
        if metrics["n"] == 0:
            continue
        rows.append(
            {
                "month": month,
                "horizon_minutes": horizon,
                "local_hour": hour,
                **metrics,
            }
        )
    return rows


def _hour_stability(
    hour_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for horizon in HORIZONS_MINUTES:
        for hour in range(24):
            rows = [
                item
                for item in hour_rows
                if item["horizon_minutes"] == horizon
                and item["local_hour"] == hour
            ]
            if not rows:
                continue
            gaps = np.asarray(
                [float(item["S1_minus_equal_mae_a"]) for item in rows],
                dtype=np.float64,
            )
            output.append(
                {
                    "horizon_minutes": horizon,
                    "local_hour": hour,
                    "months_present": len(rows),
                    "months_S1_better": int(np.sum(gaps < 0)),
                    "months_equal": int(np.sum(gaps == 0)),
                    "months_S1_worse": int(np.sum(gaps > 0)),
                    "median_S1_minus_equal_mae_a": float(np.median(gaps)),
                    "min_S1_minus_equal_mae_a": float(np.min(gaps)),
                    "max_S1_minus_equal_mae_a": float(np.max(gaps)),
                }
            )
    return output


def run_structured_transition_diagnostic(
    *,
    baseline_private_run: str | Path,
    structured_private_run: str | Path,
    expected_baseline_manifest_sha256: str = (
        EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256
    ),
    expected_structured_manifest_sha256: str = (
        EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256
    ),
) -> dict[str, Any]:
    baseline_root = Path(baseline_private_run).resolve(strict=True)
    structured_root = Path(structured_private_run).resolve(strict=True)

    baseline_manifest = _verify_manifest(
        baseline_root,
        expected_sha256=expected_baseline_manifest_sha256,
        schema_version="evcf-jpl-development-expert-private-cache/v1",
        list_key="files",
    )
    structured_manifest = _verify_manifest(
        structured_root,
        expected_sha256=expected_structured_manifest_sha256,
        schema_version="evcf-jpl-structured-s1-private-cache/v1",
        list_key="entries",
    )

    records: list[tuple[str, int, dict[str, np.ndarray]]] = []
    hour_rows: list[dict[str, Any]] = []
    for month in DEVELOPMENT_MONTHS:
        for horizon in HORIZONS_MINUTES:
            record = _load_pair(
                baseline_root=baseline_root,
                structured_root=structured_root,
                month=month,
                horizon=horizon,
            )
            records.append((month, horizon, record))
            hour_rows.extend(
                _hour_rows(month=month, horizon=horizon, record=record)
            )

    by_horizon = []
    for horizon in HORIZONS_MINUTES:
        merged = _merge_records(
            [record for _, value, record in records if value == horizon]
        )
        by_horizon.append(
            {
                "horizon_minutes": horizon,
                "composition_bins": _composition_bins(merged),
            }
        )

    by_month_horizon = [
        {
            "month": month,
            "horizon_minutes": horizon,
            "composition_bins": _composition_bins(record),
        }
        for month, horizon, record in records
    ]

    return {
        "schema_version": "evcf-jpl-structured-transition-diagnostic/v1",
        "status": "COMPLETE",
        "analysis_only": True,
        "model_fit_attempted": False,
        "network_requests": False,
        "development_data_accessed": False,
        "holdout_accessed": False,
        "development_months": list(DEVELOPMENT_MONTHS),
        "final_holdout_months": list(FINAL_HOLDOUT_MONTHS),
        "baseline_private_manifest_sha256": expected_baseline_manifest_sha256,
        "structured_private_manifest_sha256": expected_structured_manifest_sha256,
        "baseline_protocol_sha256": baseline_manifest.get("protocol_sha256"),
        "structured_protocol_sha256": structured_manifest.get("protocol_sha256"),
        "composition_by_horizon": by_horizon,
        "composition_by_month_horizon": by_month_horizon,
        "month_horizon_local_hour": hour_rows,
        "local_hour_sign_stability": _hour_stability(hour_rows),
    }
