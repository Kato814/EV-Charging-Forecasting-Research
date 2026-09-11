"""Read-only diagnostics for the completed JPL structured S1 development run."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
TIMEZONE_NAME = "America/Los_Angeles"
_ZONE = ZoneInfo(TIMEZONE_NAME)

EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256 = (
    "2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd"
)
EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256 = (
    "562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1"
)
_RECONSTRUCTION_TOLERANCE_A = 1e-6
_ZERO_TOLERANCE_A = 1e-9


class StructuredMixedDiagnosticError(RuntimeError):
    """Static path-free failure code safe for aggregate reporting."""

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


def _expected_names() -> set[str]:
    return {
        f"{month}_h{horizon:03d}.npz"
        for month in DEVELOPMENT_MONTHS
        for horizon in HORIZONS_MINUTES
    }


def _verify_manifest(
    root: Path,
    *,
    expected_sha256: str,
    schema_version: str,
    list_key: str,
) -> Mapping[str, Any]:
    manifest = root / "private_manifest.json"
    if (
        not root.is_dir()
        or root.is_symlink()
        or not manifest.is_file()
        or manifest.is_symlink()
        or _sha256_file(manifest) != expected_sha256
    ):
        raise StructuredMixedDiagnosticError("PRIVATE_CACHE_IDENTITY_INVALID")
    try:
        document = json.loads(manifest.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StructuredMixedDiagnosticError("PRIVATE_CACHE_IDENTITY_INVALID") from exc

    entries = document.get(list_key)
    if document.get("schema_version") != schema_version or not isinstance(entries, list):
        raise StructuredMixedDiagnosticError("PRIVATE_CACHE_IDENTITY_INVALID")

    expected = _expected_names()
    seen: set[str] = set()
    for item in entries:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"name", "sha256"}
            or not isinstance(item["name"], str)
            or not isinstance(item["sha256"], str)
        ):
            raise StructuredMixedDiagnosticError("PRIVATE_CACHE_IDENTITY_INVALID")
        name = item["name"]
        path = root / name
        if (
            name in seen
            or name not in expected
            or not path.is_file()
            or path.is_symlink()
            or _sha256_file(path) != item["sha256"]
        ):
            raise StructuredMixedDiagnosticError("PRIVATE_CACHE_IDENTITY_INVALID")
        seen.add(name)
    if seen != expected:
        raise StructuredMixedDiagnosticError("PRIVATE_CACHE_IDENTITY_INVALID")
    return document


def _load_npz(path: Path, required: set[str]) -> dict[str, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != required:
                raise StructuredMixedDiagnosticError("PRIVATE_CACHE_SCHEMA_INVALID")
            arrays = {name: np.asarray(archive[name]) for name in required}
    except (OSError, ValueError) as exc:
        raise StructuredMixedDiagnosticError("PRIVATE_CACHE_SCHEMA_INVALID") from exc
    return arrays


def _load_pair(
    *,
    baseline_root: Path,
    structured_root: Path,
    month: str,
    horizon: int,
) -> dict[str, np.ndarray]:
    baseline = _load_npz(
        baseline_root / f"{month}_h{horizon:03d}.npz",
        {
            "issue_times",
            "day_start_utc_s",
            "y_true",
            "m2_predictions",
            "m3_predictions",
            "equal_predictions",
        },
    )
    structured = _load_npz(
        structured_root / f"{month}_h{horizon:03d}.npz",
        {
            "issue_times",
            "day_start_utc_s",
            "y_true",
            "existing_truth",
            "arrival_truth",
            "existing_predictions",
            "arrival_predictions",
            "structured_predictions",
        },
    )
    n = len(structured["y_true"])
    required_shape = (n,)
    if n == 0 or any(array.shape != required_shape for array in structured.values()):
        raise StructuredMixedDiagnosticError("PRIVATE_CACHE_SCHEMA_INVALID")
    if any(array.shape != required_shape for array in baseline.values()):
        raise StructuredMixedDiagnosticError("PRIVATE_CACHE_SCHEMA_INVALID")
    if not (
        np.array_equal(baseline["issue_times"], structured["issue_times"])
        and np.array_equal(
            baseline["day_start_utc_s"], structured["day_start_utc_s"]
        )
        and np.allclose(
            baseline["y_true"],
            structured["y_true"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
        and np.allclose(
            structured["existing_truth"] + structured["arrival_truth"],
            structured["y_true"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
        and np.allclose(
            structured["existing_predictions"] + structured["arrival_predictions"],
            structured["structured_predictions"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise StructuredMixedDiagnosticError("COMMON_ROW_IDENTITY_INVALID")
    numeric = [
        value
        for key, value in {**baseline, **structured}.items()
        if key not in {"issue_times", "day_start_utc_s"}
    ]
    if not all(np.isfinite(array).all() for array in numeric):
        raise StructuredMixedDiagnosticError("PRIVATE_CACHE_SCHEMA_INVALID")
    if (
        np.any(structured["existing_truth"] < -_ZERO_TOLERANCE_A)
        or np.any(structured["arrival_truth"] < -_ZERO_TOLERANCE_A)
        or np.any(structured["y_true"] < -_ZERO_TOLERANCE_A)
    ):
        raise StructuredMixedDiagnosticError("PRIVATE_CACHE_SCHEMA_INVALID")
    return {**baseline, **structured}


def _metric(truth: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    error = prediction - truth
    absolute = np.abs(error)
    denominator = float(np.sum(np.abs(truth)))
    return {
        "mae_a": float(np.mean(absolute)),
        "rmse_a": float(np.sqrt(np.mean(np.square(error)))),
        "bias_a": float(np.mean(error)),
        "wape_ratio": None
        if denominator <= _ZERO_TOLERANCE_A
        else float(np.sum(absolute) / denominator),
        "negative_prediction_fraction": float(np.mean(prediction < 0)),
    }


def _conditional_pair(
    truth: np.ndarray,
    s1: np.ndarray,
    equal: np.ndarray,
    mask: np.ndarray,
) -> dict[str, Any]:
    count = int(np.sum(mask))
    if count == 0:
        return {"n": 0, "S1_mae_a": None, "equal_mae_a": None}
    return {
        "n": count,
        "S1_mae_a": float(np.mean(np.abs(s1[mask] - truth[mask]))),
        "equal_mae_a": float(np.mean(np.abs(equal[mask] - truth[mask]))),
    }


def _residual_cosine(
    existing_truth: np.ndarray,
    arrival_truth: np.ndarray,
    existing_prediction: np.ndarray,
    arrival_prediction: np.ndarray,
) -> float | None:
    e_existing = existing_prediction - existing_truth
    e_arrival = arrival_prediction - arrival_truth
    denominator = float(
        math.sqrt(
            float(np.dot(e_existing, e_existing))
            * float(np.dot(e_arrival, e_arrival))
        )
    )
    if denominator <= 0:
        return None
    return float(np.dot(e_existing, e_arrival) / denominator)


def _positive_stats(values: np.ndarray) -> dict[str, Any]:
    positive = values[values > _ZERO_TOLERANCE_A]
    if positive.size == 0:
        return {
            "n": 0,
            "mean_a": None,
            "median_a": None,
            "p90_a": None,
        }
    return {
        "n": int(positive.size),
        "mean_a": float(np.mean(positive)),
        "median_a": float(np.median(positive)),
        "p90_a": float(np.quantile(positive, 0.90)),
    }


def _summarize(records: list[dict[str, np.ndarray]]) -> dict[str, Any]:
    arrays = {
        key: np.concatenate([record[key] for record in records])
        for key in records[0]
    }
    truth = arrays["y_true"]
    existing_truth = arrays["existing_truth"]
    arrival_truth = arrays["arrival_truth"]
    existing_prediction = arrays["existing_predictions"]
    arrival_prediction = arrays["arrival_predictions"]
    s1 = arrays["structured_predictions"]
    equal = arrays["equal_predictions"]

    total_sum = float(np.sum(truth))
    existing_sum = float(np.sum(existing_truth))
    arrival_sum = float(np.sum(arrival_truth))
    arrival_zero = arrival_truth <= _ZERO_TOLERANCE_A
    arrival_positive = ~arrival_zero
    existing_zero = existing_truth <= _ZERO_TOLERANCE_A

    equal_mae = float(np.mean(np.abs(equal - truth)))
    s1_mae = float(np.mean(np.abs(s1 - truth)))
    return {
        "n": int(truth.size),
        "truth_composition": {
            "existing_share": None if total_sum <= 0 else existing_sum / total_sum,
            "arrival_share": None if total_sum <= 0 else arrival_sum / total_sum,
            "existing_zero_fraction": float(np.mean(existing_zero)),
            "arrival_zero_fraction": float(np.mean(arrival_zero)),
            "arrival_positive_stats": _positive_stats(arrival_truth),
        },
        "metrics": {
            "existing_branch": _metric(existing_truth, existing_prediction),
            "arrival_branch": _metric(arrival_truth, arrival_prediction),
            "S1": _metric(truth, s1),
            "equal": _metric(truth, equal),
        },
        "S1_vs_equal_improvement_fraction": (
            None if equal_mae == 0 else float((equal_mae - s1_mae) / equal_mae)
        ),
        "branch_residual_cosine": _residual_cosine(
            existing_truth,
            arrival_truth,
            existing_prediction,
            arrival_prediction,
        ),
        "conditional_on_arrival_truth": {
            "zero": _conditional_pair(
                truth,
                s1,
                equal,
                arrival_zero,
            ),
            "positive": _conditional_pair(
                truth,
                s1,
                equal,
                arrival_positive,
            ),
        },
    }


def _hourly_summary(records: list[dict[str, np.ndarray]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    all_issue = np.concatenate([record["issue_times"] for record in records])
    truth = np.concatenate([record["y_true"] for record in records])
    s1 = np.concatenate([record["structured_predictions"] for record in records])
    equal = np.concatenate([record["equal_predictions"] for record in records])
    hours = np.asarray(
        [
            datetime.fromtimestamp(int(value), timezone.utc)
            .astimezone(_ZONE)
            .hour
            for value in all_issue
        ],
        dtype=np.int16,
    )
    for hour in range(24):
        mask = hours == hour
        n = int(np.sum(mask))
        if n == 0:
            continue
        s1_mae = float(np.mean(np.abs(s1[mask] - truth[mask])))
        equal_mae = float(np.mean(np.abs(equal[mask] - truth[mask])))
        rows.append(
            {
                "local_hour": hour,
                "n": n,
                "S1_mae_a": s1_mae,
                "equal_mae_a": equal_mae,
                "S1_minus_equal_mae_a": s1_mae - equal_mae,
            }
        )
    return rows


def _daily_extremes(records: list[tuple[str, int, dict[str, np.ndarray]]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for month, horizon, record in records:
        truth = record["y_true"]
        s1 = record["structured_predictions"]
        equal = record["equal_predictions"]
        for day in np.unique(record["day_start_utc_s"]):
            mask = record["day_start_utc_s"] == day
            n = int(np.sum(mask))
            s1_mae = float(np.mean(np.abs(s1[mask] - truth[mask])))
            equal_mae = float(np.mean(np.abs(equal[mask] - truth[mask])))
            local_date = (
                datetime.fromtimestamp(int(day), timezone.utc)
                .astimezone(_ZONE)
                .date()
                .isoformat()
            )
            rows.append(
                {
                    "month": month,
                    "horizon_minutes": horizon,
                    "local_date": local_date,
                    "n": n,
                    "S1_mae_a": s1_mae,
                    "equal_mae_a": equal_mae,
                    "S1_minus_equal_mae_a": s1_mae - equal_mae,
                }
            )
    ordered = sorted(rows, key=lambda item: item["S1_minus_equal_mae_a"])
    return {
        "largest_improvements": ordered[:10],
        "largest_degradations": list(reversed(ordered[-10:])),
    }


def run_structured_mixed_diagnostic(
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

    all_records: list[tuple[str, int, dict[str, np.ndarray]]] = []
    for month in DEVELOPMENT_MONTHS:
        for horizon in HORIZONS_MINUTES:
            all_records.append(
                (
                    month,
                    horizon,
                    _load_pair(
                        baseline_root=baseline_root,
                        structured_root=structured_root,
                        month=month,
                        horizon=horizon,
                    ),
                )
            )

    by_horizon = []
    for horizon in HORIZONS_MINUTES:
        records = [
            record for _, value, record in all_records if value == horizon
        ]
        by_horizon.append(
            {
                "horizon_minutes": horizon,
                **_summarize(records),
                "by_local_hour": _hourly_summary(records),
            }
        )

    by_month = []
    for month in DEVELOPMENT_MONTHS:
        records = [
            record for value, _, record in all_records if value == month
        ]
        by_month.append({"month": month, **_summarize(records)})

    month_horizon = [
        {
            "month": month,
            "horizon_minutes": horizon,
            **_summarize([record]),
        }
        for month, horizon, record in all_records
    ]

    return {
        "schema_version": "evcf-jpl-structured-s1-mixed-diagnostic/v1",
        "status": "COMPLETE",
        "analysis_only": True,
        "model_fit_attempted": False,
        "network_requests": False,
        "development_months": list(DEVELOPMENT_MONTHS),
        "final_holdout_months": list(FINAL_HOLDOUT_MONTHS),
        "holdout_accessed": False,
        "baseline_private_manifest_sha256": expected_baseline_manifest_sha256,
        "structured_private_manifest_sha256": expected_structured_manifest_sha256,
        "baseline_protocol_sha256": baseline_manifest.get("protocol_sha256"),
        "structured_protocol_sha256": structured_manifest.get("protocol_sha256"),
        "pooled_by_horizon": by_horizon,
        "pooled_by_month": by_month,
        "month_horizon": month_horizon,
        "daily_extremes": _daily_extremes(all_records),
    }
