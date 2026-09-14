"""Read-only R6-O0 component-oracle replacement diagnostic for JPL/ACN."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
EXPECTED_ROWS_BY_MONTH = {
    "2019-01": 1305,
    "2019-04": 1180,
    "2019-07": 1294,
    "2019-10": 1296,
}
EXPECTED_ROWS_PER_HORIZON = 5075
EXPECTED_TOTAL_RECORDS = 25375
EXPECTED_S1_PRIVATE_MANIFEST_SHA256 = (
    "562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1"
)
EXPECTED_S1_PROTOCOL_SHA256 = (
    "74af85044d12f3c68fe4156e6ad1ae67b6e5486b47aecd5637cd67d6539c1902"
)
EXPECTED_S1_CACHE_SCHEMA = "evcf-jpl-structured-s1-private-cache/v1"
SOURCE_R5_STATUS_SHA256 = (
    "d3c820d90cb4d54a56f50bd9d1293aa1a3e53da50d3418ddb34abc6fa6a8a196"
)
SOURCE_R5_DECISION = "STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE"
PROTOCOL_MERGE_COMMIT = "256c6fd9edf8d15700c25bfc916596c9adc342b4"

_RECONSTRUCTION_TOLERANCE_A = 1e-6
_SIGN_EPS_A = 1e-12
_CANCELLATION_NEGATIVE_TOLERANCE_A = 1e-10

_REQUIRED_KEYS = {
    "issue_times",
    "day_start_utc_s",
    "y_true",
    "existing_truth",
    "arrival_truth",
    "existing_predictions",
    "arrival_predictions",
    "structured_predictions",
}

IMPLEMENTATION_PATHS = (
    "docs/JPL_R6_O0_COMPONENT_ORACLE_PROTOCOL_20260914.md",
    "code/src/evcf/forecasting/acn_jpl_r6_o0_component_oracle.py",
    "scripts/run_jpl_r6_o0_component_oracle.py",
)


class R6O0Error(RuntimeError):
    """Static identifier-free failure safe for aggregate reporting."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = (
            reason_code
            if isinstance(reason_code, str)
            and reason_code
            and reason_code.replace("_", "").isalnum()
            else "UNEXPECTED_ERROR"
        )
        super().__init__(self.reason_code)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_semantic_verify(code_commit: str, *, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or len(code_commit) != 40:
        raise R6O0Error("IMPLEMENTATION_DRIFT")
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
        raise R6O0Error("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R6O0Error("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode:
            raise R6O0Error("IMPLEMENTATION_DRIFT")
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
        raise R6O0Error("IMPLEMENTATION_DRIFT")


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
        or _sha256_file(manifest_path) != EXPECTED_S1_PRIVATE_MANIFEST_SHA256
    ):
        raise R6O0Error("S1_PRIVATE_CACHE_IDENTITY_INVALID")
    try:
        document = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise R6O0Error("S1_PRIVATE_CACHE_IDENTITY_INVALID") from exc
    if (
        not isinstance(document, Mapping)
        or set(document)
        != {
            "schema_version",
            "protocol_sha256",
            "code_commit",
            "source_private_manifest_sha256",
            "entries",
        }
        or document.get("schema_version") != EXPECTED_S1_CACHE_SCHEMA
        or document.get("protocol_sha256") != EXPECTED_S1_PROTOCOL_SHA256
        or not isinstance(document.get("code_commit"), str)
        or len(document["code_commit"]) != 40
    ):
        raise R6O0Error("S1_PRIVATE_CACHE_IDENTITY_INVALID")
    entries = document.get("entries")
    expected = _expected_names()
    if not isinstance(entries, list) or len(entries) != len(expected):
        raise R6O0Error("S1_PRIVATE_CACHE_IDENTITY_INVALID")
    seen: set[str] = set()
    for entry in entries:
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"name", "sha256"}
            or not isinstance(entry["name"], str)
            or not isinstance(entry["sha256"], str)
            or len(entry["sha256"]) != 64
        ):
            raise R6O0Error("S1_PRIVATE_CACHE_IDENTITY_INVALID")
        name = entry["name"]
        path = root / name
        if (
            name in seen
            or name not in expected
            or not path.is_file()
            or path.is_symlink()
            or _sha256_file(path) != entry["sha256"]
        ):
            raise R6O0Error("S1_PRIVATE_CACHE_IDENTITY_INVALID")
        seen.add(name)
    if seen != expected:
        raise R6O0Error("S1_PRIVATE_CACHE_IDENTITY_INVALID")
    return document


def _load_task(root: Path, month: str, horizon: int) -> dict[str, np.ndarray]:
    if month not in DEVELOPMENT_MONTHS or horizon not in HORIZONS_MINUTES:
        raise R6O0Error("TASK_IDENTITY_INVALID")
    path = root / f"{month}_h{horizon:03d}.npz"
    try:
        with np.load(path, allow_pickle=False) as archive:
            if set(archive.files) != _REQUIRED_KEYS:
                raise R6O0Error("S1_PRIVATE_CACHE_SCHEMA_INVALID")
            arrays = {key: np.asarray(archive[key]) for key in _REQUIRED_KEYS}
    except R6O0Error:
        raise
    except (OSError, ValueError) as exc:
        raise R6O0Error("S1_PRIVATE_CACHE_SCHEMA_INVALID") from exc

    expected_n = EXPECTED_ROWS_BY_MONTH[month]
    issue_times = arrays["issue_times"]
    day_starts = arrays["day_start_utc_s"]
    if (
        issue_times.dtype != np.dtype(np.int64)
        or day_starts.dtype != np.dtype(np.int64)
        or issue_times.shape != (expected_n,)
        or day_starts.shape != (expected_n,)
        or np.any(np.diff(issue_times) <= 0)
        or np.any(issue_times % 900 != 0)
    ):
        raise R6O0Error("S1_PRIVATE_CACHE_SCHEMA_INVALID")
    for key in _REQUIRED_KEYS - {"issue_times", "day_start_utc_s"}:
        value = arrays[key]
        if value.shape != (expected_n,) or not np.isfinite(value).all():
            raise R6O0Error("S1_PRIVATE_CACHE_SCHEMA_INVALID")

    if not (
        np.allclose(
            arrays["existing_truth"] + arrays["arrival_truth"],
            arrays["y_true"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
        and np.allclose(
            arrays["existing_predictions"] + arrays["arrival_predictions"],
            arrays["structured_predictions"],
            rtol=0.0,
            atol=_RECONSTRUCTION_TOLERANCE_A,
        )
    ):
        raise R6O0Error("S1_COMPONENT_RECONSTRUCTION_INVALID")
    return arrays


def _metrics(truth: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    if (
        truth.ndim != 1
        or prediction.shape != truth.shape
        or not len(truth)
        or not np.isfinite(truth).all()
        or not np.isfinite(prediction).all()
    ):
        raise R6O0Error("METRIC_INVALID")
    error = prediction - truth
    absolute = np.abs(error)
    denominator = float(np.sum(np.abs(truth)))
    return {
        "n": len(truth),
        "mae_a": float(np.mean(absolute)),
        "rmse_a": float(np.sqrt(np.mean(np.square(error)))),
        "wape_ratio": None if denominator <= 0.0 else float(np.sum(absolute) / denominator),
        "negative_prediction_count": int(np.sum(prediction < 0.0)),
    }


def _pearson(left: np.ndarray, right: np.ndarray) -> float | None:
    if left.shape != right.shape or left.ndim != 1 or not len(left):
        raise R6O0Error("INTERACTION_INVALID")
    left_std = float(np.std(left, ddof=0))
    right_std = float(np.std(right, ddof=0))
    if left_std <= _SIGN_EPS_A or right_std <= _SIGN_EPS_A:
        return None
    value = float(np.corrcoef(left, right)[0, 1])
    if not np.isfinite(value):
        raise R6O0Error("INTERACTION_INVALID")
    return value


def _interaction(existing_error: np.ndarray, arrival_error: np.ndarray) -> dict[str, Any]:
    if (
        existing_error.shape != arrival_error.shape
        or existing_error.ndim != 1
        or not len(existing_error)
        or not np.isfinite(existing_error).all()
        or not np.isfinite(arrival_error).all()
    ):
        raise R6O0Error("INTERACTION_INVALID")
    existing_nonzero = np.abs(existing_error) > _SIGN_EPS_A
    arrival_nonzero = np.abs(arrival_error) > _SIGN_EPS_A
    both = existing_nonzero & arrival_nonzero
    reinforcement = both & (np.sign(existing_error) == np.sign(arrival_error))
    cancellation = both & (np.sign(existing_error) != np.sign(arrival_error))
    zero_involved = ~both
    total_error = existing_error + arrival_error
    cancellation_amount = (
        np.abs(existing_error) + np.abs(arrival_error) - np.abs(total_error)
    )
    minimum = float(np.min(cancellation_amount))
    if minimum < -_CANCELLATION_NEGATIVE_TOLERANCE_A:
        raise R6O0Error("INTERACTION_INVALID")
    cancellation_amount = np.maximum(cancellation_amount, 0.0)
    denominator = float(np.sum(np.abs(existing_error) + np.abs(arrival_error)))
    n = len(existing_error)
    return {
        "n": n,
        "reinforcement_count": int(np.sum(reinforcement)),
        "cancellation_count": int(np.sum(cancellation)),
        "zero_involved_count": int(np.sum(zero_involved)),
        "reinforcement_fraction": float(np.mean(reinforcement)),
        "cancellation_fraction": float(np.mean(cancellation)),
        "zero_involved_fraction": float(np.mean(zero_involved)),
        "mean_cancellation_amount_a": float(np.mean(cancellation_amount)),
        "median_cancellation_amount_a": float(np.median(cancellation_amount)),
        "total_cancellation_share": (
            None if denominator <= 0.0 else float(np.sum(cancellation_amount) / denominator)
        ),
        "mean_abs_existing_error_a": float(np.mean(np.abs(existing_error))),
        "mean_abs_arrival_error_a": float(np.mean(np.abs(arrival_error))),
        "branch_error_pearson": _pearson(existing_error, arrival_error),
    }


def _record(month: str, horizon: int, arrays: Mapping[str, np.ndarray]) -> dict[str, Any]:
    truth = np.asarray(arrays["y_true"], dtype=np.float64)
    existing_truth = np.asarray(arrays["existing_truth"], dtype=np.float64)
    arrival_truth = np.asarray(arrays["arrival_truth"], dtype=np.float64)
    existing_prediction = np.asarray(arrays["existing_predictions"], dtype=np.float64)
    arrival_prediction = np.asarray(arrays["arrival_predictions"], dtype=np.float64)
    s1 = np.asarray(arrays["structured_predictions"], dtype=np.float64)
    oracle_existing = existing_truth + arrival_prediction
    oracle_arrival = existing_prediction + arrival_truth
    existing_error = existing_prediction - existing_truth
    arrival_error = arrival_prediction - arrival_truth
    if not np.allclose(
        s1 - truth,
        existing_error + arrival_error,
        rtol=0.0,
        atol=_RECONSTRUCTION_TOLERANCE_A,
    ):
        raise R6O0Error("S1_COMPONENT_RECONSTRUCTION_INVALID")
    return {
        "month": month,
        "horizon": horizon,
        "truth": truth,
        "s1": s1,
        "oracle_existing": oracle_existing,
        "oracle_arrival": oracle_arrival,
        "existing_error": existing_error,
        "arrival_error": arrival_error,
    }


def _summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise R6O0Error("AGGREGATION_INVALID")
    truth = np.concatenate([np.asarray(item["truth"]) for item in records])
    s1 = np.concatenate([np.asarray(item["s1"]) for item in records])
    oracle_existing = np.concatenate(
        [np.asarray(item["oracle_existing"]) for item in records]
    )
    oracle_arrival = np.concatenate(
        [np.asarray(item["oracle_arrival"]) for item in records]
    )
    existing_error = np.concatenate(
        [np.asarray(item["existing_error"]) for item in records]
    )
    arrival_error = np.concatenate(
        [np.asarray(item["arrival_error"]) for item in records]
    )
    s1_metrics = _metrics(truth, s1)
    oracle_existing_metrics = _metrics(truth, oracle_existing)
    oracle_arrival_metrics = _metrics(truth, oracle_arrival)
    s1_mae = float(s1_metrics["mae_a"])
    existing_gain = s1_mae - float(oracle_existing_metrics["mae_a"])
    arrival_gain = s1_mae - float(oracle_arrival_metrics["mae_a"])
    return {
        "S1": s1_metrics,
        "OracleExisting": oracle_existing_metrics,
        "OracleArrival": oracle_arrival_metrics,
        "gains": {
            "G_existing_a": existing_gain,
            "G_arrival_a": arrival_gain,
            "g_existing_ratio": None if s1_mae <= 0.0 else existing_gain / s1_mae,
            "g_arrival_ratio": None if s1_mae <= 0.0 else arrival_gain / s1_mae,
        },
        "interaction": _interaction(existing_error, arrival_error),
    }


def decide(
    pooled: Mapping[str, Any],
    by_horizon: Sequence[Mapping[str, Any]],
    by_month: Sequence[Mapping[str, Any]],
) -> tuple[str, dict[str, Any]]:
    if len(by_horizon) != 5 or len(by_month) != 4:
        raise R6O0Error("AGGREGATION_INVALID")

    pooled_existing = float(pooled["gains"]["G_existing_a"])
    pooled_arrival = float(pooled["gains"]["G_arrival_a"])

    arrival_gt_h = sum(
        float(item["gains"]["G_arrival_a"]) > float(item["gains"]["G_existing_a"])
        for item in by_horizon
    )
    arrival_gt_m = sum(
        float(item["gains"]["G_arrival_a"]) > float(item["gains"]["G_existing_a"])
        for item in by_month
    )
    existing_gt_h = sum(
        float(item["gains"]["G_existing_a"]) > float(item["gains"]["G_arrival_a"])
        for item in by_horizon
    )
    existing_gt_m = sum(
        float(item["gains"]["G_existing_a"]) > float(item["gains"]["G_arrival_a"])
        for item in by_month
    )
    positive_arrival_h = sum(
        float(item["gains"]["G_arrival_a"]) > 0.0 for item in by_horizon
    )
    positive_arrival_m = sum(
        float(item["gains"]["G_arrival_a"]) > 0.0 for item in by_month
    )
    positive_existing_h = sum(
        float(item["gains"]["G_existing_a"]) > 0.0 for item in by_horizon
    )
    positive_existing_m = sum(
        float(item["gains"]["G_existing_a"]) > 0.0 for item in by_month
    )

    support = {
        "pooled_G_existing_a": pooled_existing,
        "pooled_G_arrival_a": pooled_arrival,
        "arrival_gain_gt_existing_gain_horizons": arrival_gt_h,
        "arrival_gain_gt_existing_gain_months": arrival_gt_m,
        "existing_gain_gt_arrival_gain_horizons": existing_gt_h,
        "existing_gain_gt_arrival_gain_months": existing_gt_m,
        "positive_arrival_gain_horizons": positive_arrival_h,
        "positive_arrival_gain_months": positive_arrival_m,
        "positive_existing_gain_horizons": positive_existing_h,
        "positive_existing_gain_months": positive_existing_m,
    }

    arrival_dominant = (
        pooled_arrival > pooled_existing
        and pooled_arrival > 0.0
        and arrival_gt_h >= 4
        and arrival_gt_m >= 3
        and positive_arrival_h >= 4
        and positive_arrival_m >= 3
    )
    if arrival_dominant:
        return "ARRIVAL_COMPONENT_ORACLE_DOMINANT", support

    existing_dominant = (
        pooled_existing > pooled_arrival
        and pooled_existing > 0.0
        and existing_gt_h >= 4
        and existing_gt_m >= 3
        and positive_existing_h >= 4
        and positive_existing_m >= 3
    )
    if existing_dominant:
        return "EXISTING_COMPONENT_ORACLE_DOMINANT", support

    if pooled_existing <= 0.0 and pooled_arrival <= 0.0:
        return "CANCELLATION_DOMINATED_COMPONENT_ERRORS", support
    return "MIXED_COMPONENT_ORACLE_SIGNAL", support


def run_r6_o0(
    *,
    authorized: bool,
    s1_private_root: str | Path,
    code_commit: str,
    repo_root: str | Path = ".",
) -> dict[str, Any]:
    if authorized is not True:
        raise R6O0Error("R6_O0_NOT_AUTHORIZED")
    repo = Path(repo_root).resolve(strict=True)
    s1_root = Path(s1_private_root).resolve(strict=True)
    _git_semantic_verify(code_commit, repo_root=repo)
    manifest = _verify_manifest(s1_root)

    records: list[dict[str, Any]] = []
    for month in DEVELOPMENT_MONTHS:
        for horizon in HORIZONS_MINUTES:
            arrays = _load_task(s1_root, month, horizon)
            records.append(_record(month, horizon, arrays))

    if sum(len(item["truth"]) for item in records) != EXPECTED_TOTAL_RECORDS:
        raise R6O0Error("ROW_COUNT_INVALID")

    pooled = _summary(records)
    by_horizon = []
    for horizon in HORIZONS_MINUTES:
        selected = [item for item in records if item["horizon"] == horizon]
        summary = _summary(selected)
        if int(summary["S1"]["n"]) != EXPECTED_ROWS_PER_HORIZON:
            raise R6O0Error("ROW_COUNT_INVALID")
        by_horizon.append({"horizon_minutes": horizon, **summary})

    by_month = []
    for month in DEVELOPMENT_MONTHS:
        selected = [item for item in records if item["month"] == month]
        summary = _summary(selected)
        expected = EXPECTED_ROWS_BY_MONTH[month] * len(HORIZONS_MINUTES)
        if int(summary["S1"]["n"]) != expected:
            raise R6O0Error("ROW_COUNT_INVALID")
        by_month.append({"month": month, **summary})

    cells = [
        {
            "month": item["month"],
            "horizon_minutes": item["horizon"],
            **_summary([item]),
        }
        for item in records
    ]
    decision, support = decide(pooled, by_horizon, by_month)

    after = _verify_manifest(s1_root)
    if after != manifest:
        raise R6O0Error("S1_PRIVATE_CACHE_CHANGED")

    return {
        "schema_version": "evcf-jpl-r6-o0-component-oracle-summary/v1",
        "status": "COMPLETE",
        "decision": decision,
        "decision_support": support,
        "code_commit": code_commit,
        "protocol_merge_commit": PROTOCOL_MERGE_COMMIT,
        "source_s1_private_manifest_sha256": EXPECTED_S1_PRIVATE_MANIFEST_SHA256,
        "source_s1_protocol_sha256": EXPECTED_S1_PROTOCOL_SHA256,
        "source_s1_code_commit": manifest["code_commit"],
        "source_r5_status_sha256": SOURCE_R5_STATUS_SHA256,
        "source_r5_decision": SOURCE_R5_DECISION,
        "scientific_decisions_unchanged": True,
        "pooled_overall": pooled,
        "pooled_by_horizon": by_horizon,
        "pooled_by_month": by_month,
        "month_horizon_cells": cells,
        "record_count": EXPECTED_TOTAL_RECORDS,
        "fit_count": 0,
        "model_fit_attempted": False,
        "hyperparameter_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "row_filtering": False,
        "raw_or_processed_data_accessed": False,
        "r5_private_predictions_accessed": False,
        "holdout_accessed": False,
        "s1_private_cache_unchanged": True,
    }
