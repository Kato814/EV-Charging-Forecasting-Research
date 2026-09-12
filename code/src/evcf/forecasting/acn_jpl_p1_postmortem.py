"""Read-only post-mortem for the completed JPL P1 mechanism probe.

This module never fits a model. It only verifies and summarizes the accepted
P1 private cache so the frozen STOP_MECHANISM_ROUTE decision can be audited.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
EXPECTED_P1_PRIVATE_MANIFEST_SHA256 = (
    "df222c4731f3c3192735a6df2ccd2f692f1ea6d640a7954706e7bca17f51580f"
)
EXPECTED_P1_CODE_COMMIT = "dac9d18596d8e3ba766e02f83b21d60e650e5957"
_ZONE = ZoneInfo("America/Los_Angeles")
_TOL = 1e-6

_REQUIRED_KEYS = {
    "issue_times",
    "day_start_utc_s",
    "y_true",
    "existing_truth",
    "arrival_truth",
    "m2_predictions",
    "m3_predictions",
    "equal_predictions",
    "s1_existing_predictions",
    "s1_arrival_predictions",
    "s1_predictions",
    "p1_e_predictions",
    "p1_a_predictions",
    "p1_eonly_predictions",
    "p1_aonly_predictions",
    "p1_ea_predictions",
}


class P1PostmortemError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _sha256(path: Path) -> str:
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


def _verify_manifest(root: Path) -> Mapping[str, Any]:
    manifest_path = root / "private_manifest.json"
    if (
        not root.is_dir()
        or root.is_symlink()
        or not manifest_path.is_file()
        or manifest_path.is_symlink()
        or _sha256(manifest_path) != EXPECTED_P1_PRIVATE_MANIFEST_SHA256
    ):
        raise P1PostmortemError("P1_PRIVATE_CACHE_IDENTITY_INVALID")
    try:
        doc = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise P1PostmortemError("P1_PRIVATE_CACHE_IDENTITY_INVALID") from exc
    entries = doc.get("entries")
    if (
        doc.get("schema_version")
        != "evcf-jpl-structured-mechanism-p1-private-cache/v1"
        or doc.get("code_commit") != EXPECTED_P1_CODE_COMMIT
        or doc.get("holdout_accessed") is not False
        or doc.get("hyperparameter_search") is not False
        or not isinstance(entries, list)
    ):
        raise P1PostmortemError("P1_PRIVATE_CACHE_IDENTITY_INVALID")
    expected = _expected_names()
    seen: set[str] = set()
    for entry in entries:
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"name", "sha256"}
            or not isinstance(entry["name"], str)
            or not isinstance(entry["sha256"], str)
        ):
            raise P1PostmortemError("P1_PRIVATE_CACHE_IDENTITY_INVALID")
        name = entry["name"]
        path = root / name
        if (
            name in seen
            or name not in expected
            or not path.is_file()
            or path.is_symlink()
            or _sha256(path) != entry["sha256"]
        ):
            raise P1PostmortemError("P1_PRIVATE_CACHE_IDENTITY_INVALID")
        seen.add(name)
    if seen != expected:
        raise P1PostmortemError("P1_PRIVATE_CACHE_IDENTITY_INVALID")
    return doc


def _load(root: Path, month: str, horizon: int) -> dict[str, np.ndarray]:
    path = root / f"{month}_h{horizon:03d}.npz"
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != _REQUIRED_KEYS:
                raise P1PostmortemError("P1_PRIVATE_CACHE_SCHEMA_INVALID")
            arrays = {key: np.asarray(archive[key]) for key in _REQUIRED_KEYS}
    except P1PostmortemError:
        raise
    except (OSError, ValueError) as exc:
        raise P1PostmortemError("P1_PRIVATE_CACHE_SCHEMA_INVALID") from exc
    n = len(arrays["issue_times"])
    if n == 0 or any(value.shape != (n,) for value in arrays.values()):
        raise P1PostmortemError("P1_PRIVATE_CACHE_SCHEMA_INVALID")
    if not all(np.isfinite(value).all() for value in arrays.values()):
        raise P1PostmortemError("P1_PRIVATE_CACHE_SCHEMA_INVALID")
    if not (
        np.allclose(
            arrays["existing_truth"] + arrays["arrival_truth"],
            arrays["y_true"],
            rtol=0.0,
            atol=_TOL,
        )
        and np.allclose(
            arrays["s1_existing_predictions"] + arrays["s1_arrival_predictions"],
            arrays["s1_predictions"],
            rtol=0.0,
            atol=_TOL,
        )
        and np.allclose(
            arrays["p1_e_predictions"] + arrays["p1_a_predictions"],
            arrays["p1_ea_predictions"],
            rtol=0.0,
            atol=_TOL,
        )
        and np.allclose(
            arrays["p1_e_predictions"] + arrays["s1_arrival_predictions"],
            arrays["p1_eonly_predictions"],
            rtol=0.0,
            atol=_TOL,
        )
        and np.allclose(
            arrays["s1_existing_predictions"] + arrays["p1_a_predictions"],
            arrays["p1_aonly_predictions"],
            rtol=0.0,
            atol=_TOL,
        )
    ):
        raise P1PostmortemError("P1_PRIVATE_CACHE_IDENTITY_INVALID")
    if np.any(arrays["arrival_truth"] < -_TOL) or np.any(
        arrays["p1_a_predictions"] < 0
    ):
        raise P1PostmortemError("P1_PRIVATE_CACHE_SCHEMA_INVALID")
    return arrays


def _quantiles(values: np.ndarray) -> dict[str, float]:
    return {
        "q50": float(np.quantile(values, 0.50)),
        "q90": float(np.quantile(values, 0.90)),
        "q95": float(np.quantile(values, 0.95)),
        "q99": float(np.quantile(values, 0.99)),
        "q999": float(np.quantile(values, 0.999)),
        "max": float(np.max(values)),
    }


def _error_concentration(error: np.ndarray) -> dict[str, float]:
    absolute = np.sort(np.abs(error))[::-1]
    total = float(np.sum(absolute))
    if total <= 0:
        return {"top1": 0.0, "top5": 0.0, "top10": 0.0, "top1pct": 0.0}
    n = len(absolute)
    return {
        "top1": float(np.sum(absolute[:1]) / total),
        "top5": float(np.sum(absolute[: min(5, n)]) / total),
        "top10": float(np.sum(absolute[: min(10, n)]) / total),
        "top1pct": float(np.sum(absolute[: max(1, int(np.ceil(n * 0.01)))]) / total),
    }


def _threshold_counts(values: np.ndarray) -> dict[str, int]:
    return {
        "gt_100a": int(np.sum(values > 100.0)),
        "gt_500a": int(np.sum(values > 500.0)),
        "gt_1000a": int(np.sum(values > 1000.0)),
        "gt_5000a": int(np.sum(values > 5000.0)),
        "gt_10000a": int(np.sum(values > 10000.0)),
    }


def _local_parts(issue_times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    dates: list[str] = []
    hours: list[int] = []
    for raw in issue_times:
        local = datetime.fromtimestamp(int(raw), timezone.utc).astimezone(_ZONE)
        dates.append(local.date().isoformat())
        hours.append(local.hour)
    return np.asarray(dates, dtype=object), np.asarray(hours, dtype=np.int16)


def _summarize_one(
    month: str, horizon: int, arrays: Mapping[str, np.ndarray]
) -> dict[str, Any]:
    truth = arrays["arrival_truth"]
    prediction = arrays["p1_a_predictions"]
    error = prediction - truth
    dates, hours = _local_parts(arrays["issue_times"])

    by_hour: list[dict[str, Any]] = []
    for hour in range(24):
        mask = hours == hour
        if not np.any(mask):
            continue
        local_error = error[mask]
        local_pred = prediction[mask]
        by_hour.append(
            {
                "local_hour": hour,
                "n": int(np.sum(mask)),
                "p1_a_mae_a": float(np.mean(np.abs(local_error))),
                "p1_a_max_prediction_a": float(np.max(local_pred)),
                "p1_a_q99_prediction_a": float(np.quantile(local_pred, 0.99)),
            }
        )

    order = np.argsort(np.abs(error))[::-1]
    top_rows: list[dict[str, Any]] = []
    for index in order[:10]:
        top_rows.append(
            {
                "local_date": str(dates[index]),
                "local_hour": int(hours[index]),
                "p1_a_prediction_a": float(prediction[index]),
                "arrival_truth_a": float(truth[index]),
                "absolute_error_a": float(abs(error[index])),
            }
        )
    return {
        "month": month,
        "horizon_minutes": horizon,
        "n": len(truth),
        "p1_a_prediction_quantiles_a": _quantiles(prediction),
        "arrival_truth_quantiles_a": _quantiles(truth),
        "absolute_error_quantiles_a": _quantiles(np.abs(error)),
        "threshold_counts": _threshold_counts(prediction),
        "absolute_error_concentration": _error_concentration(error),
        "by_local_hour": by_hour,
        "top_extreme_rows": top_rows,
    }


def run_p1_postmortem(*, p1_private_run: str | Path) -> dict[str, Any]:
    root = Path(p1_private_run).resolve(strict=True)
    _verify_manifest(root)
    records: list[tuple[str, int, dict[str, np.ndarray]]] = []
    for month in DEVELOPMENT_MONTHS:
        for horizon in HORIZONS_MINUTES:
            records.append((month, horizon, _load(root, month, horizon)))

    summaries = [_summarize_one(month, horizon, arrays) for month, horizon, arrays in records]

    all_truth = np.concatenate([arrays["arrival_truth"] for _, _, arrays in records])
    all_prediction = np.concatenate(
        [arrays["p1_a_predictions"] for _, _, arrays in records]
    )
    all_error = all_prediction - all_truth

    worst_cells = sorted(
        (
            {
                "month": item["month"],
                "horizon_minutes": item["horizon_minutes"],
                "local_hour": hour["local_hour"],
                "n": hour["n"],
                "p1_a_mae_a": hour["p1_a_mae_a"],
                "p1_a_max_prediction_a": hour["p1_a_max_prediction_a"],
            }
            for item in summaries
            for hour in item["by_local_hour"]
        ),
        key=lambda row: row["p1_a_mae_a"],
        reverse=True,
    )[:20]

    return {
        "schema_version": "evcf-jpl-p1-readonly-postmortem/v1",
        "status": "COMPLETE",
        "analysis_only": True,
        "model_fit_attempted": False,
        "raw_or_processed_data_accessed": False,
        "holdout_accessed": False,
        "network_requests": False,
        "development_months": list(DEVELOPMENT_MONTHS),
        "final_holdout_months": list(FINAL_HOLDOUT_MONTHS),
        "p1_private_manifest_sha256": EXPECTED_P1_PRIVATE_MANIFEST_SHA256,
        "p1_code_commit": EXPECTED_P1_CODE_COMMIT,
        "overall_arrival_branch": {
            "n": len(all_truth),
            "p1_a_mae_a": float(np.mean(np.abs(all_error))),
            "prediction_quantiles_a": _quantiles(all_prediction),
            "truth_quantiles_a": _quantiles(all_truth),
            "threshold_counts": _threshold_counts(all_prediction),
            "absolute_error_concentration": _error_concentration(all_error),
        },
        "month_horizon": summaries,
        "worst_month_horizon_hours": worst_cells,
        "scientific_decision_unchanged": "STOP_MECHANISM_ROUTE",
    }


__all__ = [
    "DEVELOPMENT_MONTHS",
    "FINAL_HOLDOUT_MONTHS",
    "HORIZONS_MINUTES",
    "P1PostmortemError",
    "run_p1_postmortem",
]
