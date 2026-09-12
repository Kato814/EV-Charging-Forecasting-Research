"""Prediction-cache-only failure analysis; never imports a model or refits R1."""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Callable, Mapping
from datetime import datetime, time, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from zipfile import BadZipFile
from zoneinfo import ZoneInfo

import numpy as np

MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
HORIZONS = (15, 30, 60, 120, 240)
FROZEN_DECISION = "MIXED_JOINT_STATE_SIGNAL"
R1_COMMIT = "e01607078431141a1fccdd6a9db5f75ae561bfda"
R1_MANIFEST_SHA256 = "56178b6eac582a7ed844d6f94324a6947580e0f9a42e95cb9307fd78adecfd0f"
REFERENCE_SHA256 = "0c8075eb05c2405769862db72012076fc2f5a019c85a260d5b0315809520c703"
BASELINE_SHA256 = "2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd"
S1_SHA256 = "562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1"
SCHEMA = "evcf-jpl-r1-mixed-diagnostic/v1"
ZONE = ZoneInfo("America/Los_Angeles")
MODEL_KEYS = {
    "M2": "m2_predictions",
    "M3": "m3_predictions",
    "Equal": "equal_predictions",
    "S1": "s1_predictions",
    "R1_Control": "r1_control_predictions",
    "R1_Joint": "r1_joint_predictions",
}
REQUIRED_ARRAYS = {"issue_times", "day_start_utc_s", "y_true", *MODEL_KEYS.values()}
EXPECTED_N = {"2019-01": 1305, "2019-04": 1180, "2019-07": 1294, "2019-10": 1296}
Progress = Callable[[str, int, int, str], None]


class R1DiagnosticError(RuntimeError):
    """Only a static reason code may cross the public reporting boundary."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _emit(progress: Progress | None, stage: str, done: int, total: int, cell: str = "") -> None:
    if progress is not None:
        progress(stage, done, total, cell)


def safe_path(path: Path) -> Path:
    """Reject symlinks and Windows junction/reparse points before resolving."""
    for part in (path, *path.parents):
        if part.is_symlink():
            raise R1DiagnosticError("LINKED_PATH_NOT_ALLOWED")
        if part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400:
            raise R1DiagnosticError("LINKED_PATH_NOT_ALLOWED")
    return path.resolve(strict=True)


def _names() -> list[str]:
    return [f"{m}_h{h:03d}.npz" for m in MONTHS for h in HORIZONS]


def _read_manifest(root: Path) -> dict[str, str]:
    # List names only, not contents of any unapproved entry. No recursive walk.
    expected = {*_names(), "private_manifest.json"}
    if {p.name for p in root.iterdir()} != expected:
        raise R1DiagnosticError("R1_CACHE_TOPOLOGY_INVALID")
    path = root / "private_manifest.json"
    safe_path(path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != R1_MANIFEST_SHA256:
        raise R1DiagnosticError("R1_MANIFEST_IDENTITY_INVALID")
    manifest = json.loads(raw)
    required = {
        "schema_version": "evcf-jpl-r1-joint-state-private-cache/v1",
        "code_commit": R1_COMMIT,
        "source_baseline_private_manifest_sha256": BASELINE_SHA256,
        "source_structured_private_manifest_sha256": S1_SHA256,
        "holdout_accessed": False,
        "hyperparameter_search": False,
    }
    if any(manifest.get(k) != v for k, v in required.items()):
        raise R1DiagnosticError("R1_MANIFEST_IDENTITY_INVALID")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or len(entries) != 20:
        raise R1DiagnosticError("R1_MANIFEST_IDENTITY_INVALID")
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"name", "sha256"}:
            raise R1DiagnosticError("R1_MANIFEST_IDENTITY_INVALID")
        name, sha = entry["name"], entry["sha256"]
        if name not in _names() or name in result:
            raise R1DiagnosticError("R1_MANIFEST_IDENTITY_INVALID")
        if (not isinstance(sha, str) or len(sha) != 64
                or any(c not in "0123456789abcdef" for c in sha)):
            raise R1DiagnosticError("R1_MANIFEST_IDENTITY_INVALID")
        result[name] = sha
    if set(result) != set(_names()):
        raise R1DiagnosticError("R1_MANIFEST_IDENTITY_INVALID")
    return result


def _cache_bytes(root: Path, name: str, sha: str) -> bytes:
    if name not in _names():
        raise R1DiagnosticError("NON_DEVELOPMENT_FILE_REJECTED")
    path = root / name
    safe_path(path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise R1DiagnosticError("R1_CACHE_FILE_HASH_MISMATCH")
    return raw


def _load_arrays(raw: bytes, month: str) -> dict[str, np.ndarray]:
    try:
        # Consume the exact bytes that were hashed; do not reopen an unchecked file.
        with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
            if len(archive.files) != len(REQUIRED_ARRAYS) or set(archive.files) != REQUIRED_ARRAYS:
                raise R1DiagnosticError("R1_ARRAY_SCHEMA_INVALID")
            arrays = {k: np.array(archive[k], copy=True) for k in REQUIRED_ARRAYS}
    except (ValueError, OSError, BadZipFile, EOFError) as exc:
        raise R1DiagnosticError("R1_ARRAY_SCHEMA_INVALID") from exc
    n = EXPECTED_N[month]
    if any(a.shape != (n,) or a.dtype.kind not in "if" for a in arrays.values()):
        raise R1DiagnosticError("R1_ARRAY_SCHEMA_INVALID")
    if any(not np.isfinite(a).all() for a in arrays.values()):
        raise R1DiagnosticError("R1_NONFINITE_ARRAY")
    issues, days = arrays["issue_times"], arrays["day_start_utc_s"]
    if issues.dtype.kind != "i" or days.dtype.kind != "i":
        raise R1DiagnosticError("R1_TIME_IDENTITY_INVALID")
    if np.any(np.diff(issues) <= 0) or np.any(issues % 900):
        raise R1DiagnosticError("R1_TIME_IDENTITY_INVALID")
    dates, hours = [], []
    for issue, day in zip(issues, days, strict=True):
        local = datetime.fromtimestamp(int(issue), timezone.utc).astimezone(ZONE)
        midnight = int(datetime.combine(local.date(), time.min, tzinfo=ZONE).timestamp())
        if local.strftime("%Y-%m") != month or local.day < 18 or midnight != int(day):
            raise R1DiagnosticError("R1_TIME_IDENTITY_INVALID")
        dates.append(local.date().isoformat())
        hours.append(local.hour)
    if np.any(arrays["y_true"] < -1e-9):
        raise R1DiagnosticError("R1_TRUTH_INVALID")
    if not np.allclose(
        arrays["equal_predictions"],
        0.5 * arrays["m2_predictions"] + 0.5 * arrays["m3_predictions"],
        rtol=0, atol=1e-6,
    ):
        raise R1DiagnosticError("EQUAL_RECONSTRUCTION_INVALID")
    arrays["local_date"] = np.asarray(dates)
    arrays["local_hour"] = np.asarray(hours, dtype=np.int16)
    return arrays


def _metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, Any]:
    absolute = np.abs(pred - y)
    denominator = float(np.abs(y).sum())
    return {
        "n": len(y),
        "mae_a": float(absolute.mean()),
        "rmse_a": float(np.sqrt(np.mean(np.square(pred - y)))),
        "wape_ratio": float(absolute.sum() / denominator) if denominator > 0 else None,
        "negative_prediction_count": int(np.sum(pred < 0)),
    }


def _pooled(records: list[dict[str, Any]]) -> dict[str, Any]:
    y = np.concatenate([r["arrays"]["y_true"] for r in records])
    return {
        model: _metrics(y, np.concatenate([r["arrays"][key] for r in records]))
        for model, key in MODEL_KEYS.items()
    }


def _match_metrics(
    actual: Mapping[str, Any], expected: Mapping[str, Any], *, mae_only: bool = False,
) -> None:
    for model in MODEL_KEYS:
        for metric, value in actual[model].items():
            if mae_only and metric not in ("n", "mae_a"):
                continue
            target = expected[model][metric]
            if metric in ("n", "negative_prediction_count") or value is None or target is None:
                ok = value == target
            else:
                ok = math.isclose(value, target, rel_tol=1e-10, abs_tol=1e-8)
            if not ok:
                raise R1DiagnosticError("ACCEPTED_METRIC_RECONSTRUCTION_MISMATCH")


def _cell(arrays: Mapping[str, np.ndarray], mask: np.ndarray) -> dict[str, Any]:
    """Positive loss delta means Joint is worse. An empty cell is never zero-filled."""
    n = int(mask.sum())
    if n == 0:
        return {"n": 0, "mae_a": None, "paired": None}
    truth = arrays["y_true"][mask]
    losses = {m: np.abs(arrays[MODEL_KEYS[m]][mask] - truth)
              for m in ("R1_Joint", "R1_Control", "Equal")}
    paired = {}
    for comparator in ("R1_Control", "Equal"):
        delta = losses["R1_Joint"] - losses[comparator]
        worsening = float(delta[delta > 0].sum())
        improvement = float(-delta[delta < 0].sum())
        total = float(delta.sum())
        if not math.isclose(worsening - improvement, total, rel_tol=1e-10, abs_tol=1e-8):
            raise R1DiagnosticError("LOSS_ACCOUNTING_INVALID")
        paired[comparator] = {
            "mean_loss_delta_a": total / n,
            "sum_loss_delta_a": total,
            "gross_worsening_a": worsening,
            "gross_improvement_a": improvement,
            "row_wins": int(np.sum(delta < 0)),
            "row_ties": int(np.sum(delta == 0)),
            "row_losses": int(np.sum(delta > 0)),
        }
    return {"n": n, "mae_a": {m: float(v.mean()) for m, v in losses.items()}, "paired": paired}


def _daily_summary(daily: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {"n_days": len(daily), "paired": {}}
    for comparator in ("R1_Control", "Equal"):
        means = np.asarray([d["paired"][comparator]["mean_loss_delta_a"] for d in daily])
        sums = np.asarray([d["paired"][comparator]["sum_loss_delta_a"] for d in daily])
        # Concentration uses positive NET daily excess, not deletion or trimmed metrics.
        positive = np.sort(sums[sums > 0])[::-1]
        mass = float(positive.sum())
        out["paired"][comparator] = {
            "day_wins": int(np.sum(means < 0)),
            "day_ties": int(np.sum(means == 0)),
            "day_losses": int(np.sum(means > 0)),
            "unweighted_day_mean_delta_a": float(means.mean()),
            "median_day_delta_a": float(np.median(means)),
            "p10_day_delta_a": float(np.quantile(means, 0.1)),
            "p90_day_delta_a": float(np.quantile(means, 0.9)),
            "positive_net_daily_excess_a": mass,
            "top1_day_share_of_positive_net_daily_excess": float(positive[:1].sum()/mass)
                if mass > 0 else None,
            "top3_day_share_of_positive_net_daily_excess": float(positive[:3].sum()/mass)
                if mass > 0 else None,
        }
    return out


def _check_partition(whole: Mapping[str, Any], cells: list[dict[str, Any]]) -> None:
    if sum(c["n"] for c in cells) != whole["n"]:
        raise R1DiagnosticError("LOSS_PARTITION_INVALID")
    for comparator in ("R1_Control", "Equal"):
        total = sum(c["paired"][comparator]["sum_loss_delta_a"] for c in cells if c["n"])
        expected = whole["paired"][comparator]["sum_loss_delta_a"]
        if not math.isclose(total, expected, rel_tol=1e-10, abs_tol=1e-8):
            raise R1DiagnosticError("LOSS_PARTITION_INVALID")


def _analyze(records: list[dict[str, Any]], progress: Progress | None) -> dict[str, Any]:
    month_horizon = []
    for number, record in enumerate(records, start=1):
        a = record["arrays"]
        whole = _cell(a, np.ones(len(a["y_true"]), dtype=bool))
        daily = [{"local_date": str(d), **_cell(a, a["local_date"] == d)}
                 for d in np.unique(a["local_date"])]
        hourly = [{"local_hour": h, **_cell(a, a["local_hour"] == h)} for h in range(24)]
        _check_partition(whole, daily)
        _check_partition(whole, hourly)
        month_horizon.append({
            "month": record["month"], "horizon_minutes": record["horizon_minutes"],
            "overall": whole, "daily": daily, "hourly": hourly,
            "daily_summary": _daily_summary(daily),
        })
        _emit(progress, "ANALYZE", number, len(records),
              f'{record["month"]}_h{record["horizon_minutes"]:03d}')
    hourly_consistency = []
    for horizon in HORIZONS:
        for hour in range(24):
            cells = [r["hourly"][hour] for r in month_horizon if r["horizon_minutes"] == horizon]
            valid = [c for c in cells if c["n"]]
            paired = {}
            for comparator in ("R1_Control", "Equal"):
                values = [c["paired"][comparator]["mean_loss_delta_a"] for c in valid]
                paired[comparator] = {
                    "month_wins": sum(v < 0 for v in values),
                    "month_ties": sum(v == 0 for v in values),
                    "month_losses": sum(v > 0 for v in values),
                    "median_month_delta_a": float(np.median(values)) if values else None,
                    "pooled_delta_a": sum(c["paired"][comparator]["sum_loss_delta_a"]
                                           for c in valid)/sum(c["n"] for c in valid)
                        if valid else None,
                }
            hourly_consistency.append({"horizon_minutes": horizon, "local_hour": hour,
                                       "n_months_with_data": len(valid), "paired": paired})
    return {"month_horizon": month_horizon, "cross_month_hourly_consistency": hourly_consistency}


def run_diagnostic(
    *, r1_private_run: str | Path, reference_path: str | Path, progress: Progress | None = None,
) -> dict[str, Any]:
    started = perf_counter()
    root = safe_path(Path(r1_private_run))
    reference_raw = safe_path(Path(reference_path)).read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(reference_raw).hexdigest() != REFERENCE_SHA256:
        raise R1DiagnosticError("REFERENCE_IDENTITY_INVALID")
    reference = json.loads(reference_raw)
    entries = _read_manifest(root)
    records: list[dict[str, Any]] = []
    indexes: dict[str, np.ndarray] = {}
    for number, name in enumerate(_names(), start=1):
        month, hpart = name.split("_h")
        horizon = int(hpart[:3])
        arrays = _load_arrays(_cache_bytes(root, name, entries[name]), month)
        if month in indexes and not np.array_equal(indexes[month], arrays["issue_times"]):
            raise R1DiagnosticError("CROSS_HORIZON_ROW_IDENTITY_INVALID")
        indexes[month] = arrays["issue_times"]
        records.append({"month": month, "horizon_minutes": horizon, "arrays": arrays})
        _emit(progress, "READ_VERIFY", number, 20, name[:-4])
    loaded_at = perf_counter()
    pooled = _pooled(records)
    by_horizon = [{"horizon_minutes": h,
                   **_pooled([r for r in records if r["horizon_minutes"] == h])}
                  for h in HORIZONS]
    by_month = [{"month": m, **_pooled([r for r in records if r["month"] == m])} for m in MONTHS]
    cell_reference = {(r["month"], r["horizon_minutes"]): r for r in reference["month_horizon"]}
    for r in records:
        _match_metrics(
            _pooled([r]), cell_reference[(r["month"], r["horizon_minutes"])], mae_only=True
        )
    _match_metrics(pooled, reference["pooled_overall"])
    _emit(progress, "RECONSTRUCT_ACCEPTED_METRICS", 1, 1)
    reconstructed_at = perf_counter()
    analysis = _analyze(records, progress)
    analyzed_at = perf_counter()
    # Verify all input bytes again. No input file is ever opened for writing.
    if _read_manifest(root) != entries:
        raise R1DiagnosticError("R1_CACHE_CHANGED")
    for number, name in enumerate(_names(), start=1):
        _cache_bytes(root, name, entries[name])
        _emit(progress, "FINAL_CACHE_CHECK", number, 20, name[:-4])
    elapsed = perf_counter() - started
    return {
        "schema_version": SCHEMA, "status": "COMPLETE", "reason_code": None,
        "scientific_decision_unchanged": FROZEN_DECISION,
        "analysis_only": True, "model_fit_attempted": False, "fit_count": 0,
        "raw_interim_processed_accessed": False, "holdout_accessed": False,
        "network_requests": False, "row_deletion": False,
        "prediction_clipping": False, "prediction_calibration": False,
        "r1_private_cache_unchanged": True, "accepted_metrics_reconstructed": True,
        "loss_partitions_reconciled": True,
        "reconstruction_scope": "ALL_20_CELL_COUNTS_MAE_AND_ALL_POOLED_METRICS",
        "source_r1_code_commit": R1_COMMIT, "r1_private_manifest_sha256": R1_MANIFEST_SHA256,
        "reference_sha256": REFERENCE_SHA256,
        "source_r1_status_sha256": reference["source_r1_status_sha256"],
        "device": "CPU", "gpu_used": False, "device_reason": "ARRAY_STATISTICS_NO_MODEL_FIT",
        "development_months": list(MONTHS), "horizons_minutes": list(HORIZONS),
        "n_forecast_records": sum(len(r["arrays"]["y_true"]) for r in records),
        "n_unique_issue_times": sum(len(a) for a in indexes.values()),
        "n_unique_local_days": len({str(d) for r in records for d in r["arrays"]["local_date"]}),
        "pooled_overall": pooled, "pooled_by_horizon": by_horizon, "pooled_by_month": by_month,
        **analysis,
        "interpretation": {
            "delta_sign": "POSITIVE_MEANS_JOINT_WORSE",
            "pooled_weighting": "FORECAST_RECORD_WEIGHTED",
            "daily_median_weighting": "EQUAL_WEIGHT_PER_OBSERVED_LOCAL_DAY",
            "tail_concentration": "TOP_DAYS_SHARE_OF_POSITIVE_NET_DAILY_LOSS_EXCESS",
            "pvalues_or_confidence_intervals_computed": False,
            "forecast_records_are_independent_samples": False,
            "hourly_pattern_is_causal_proof": False,
            "feature_support_available": False,
            "new_model_authorized": False,
        },
        "timings_seconds": {
            "read_verify": loaded_at - started,
            "reconstruct": reconstructed_at - loaded_at,
            "analyze": analyzed_at - reconstructed_at,
            "final_cache_check": perf_counter() - analyzed_at,
            "total": elapsed,
        },
    }
