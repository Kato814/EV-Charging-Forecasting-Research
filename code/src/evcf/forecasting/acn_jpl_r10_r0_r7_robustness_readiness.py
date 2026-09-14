"""Frozen zero-fit R10-R0 robustness and holdout-readiness audit for accepted R7."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np

from evcf.forecasting.acn_jpl_structured_mechanism_probe import _load_npz, _verify_private_manifest

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
EXPECTED_ROWS_BY_MONTH = MappingProxyType(
    {"2019-01": 1305, "2019-04": 1180, "2019-07": 1294, "2019-10": 1296}
)
EXPECTED_ROWS_PER_HORIZON = 5075
EXPECTED_RECORD_COUNT = 25_375
SOURCE_R7_D1_STATUS_SHA256 = "48247f4ef47415c65b080584e667e9b2dba9227271ad24d93da51800756b406b"
EXPECTED_R7_D1_PRIVATE_MANIFEST_SHA256 = "0c816334d74173e16df6e58e55de90ca3ed5723a6775e0b6287749afa479e019"
R7_D1_REVIEWED_EXECUTABLE = "2a2384781eeccf122ef43116b604f319e5637bdc"
R7_D1_PROTOCOL_COMMIT = "5532e2f9aca90e03c580d0203aec6b193b71cda3"
SOURCE_R7_C0_STATUS_SHA256 = "deb7fc1700fccd3eb53616bbe2e65de0941b6294d60aec58e4f63953b576bce0"
SOURCE_R9_STATUS_SHA256 = "d3ce58b4272e0b3fea4f11c9774c7b61a11fae443cfbb4f09210e8e22bea6d98"
SOURCE_R9_DECISION = "STOP_DEPARTURE_REPRESENTATION_REFINEMENT"
R10_PROTOCOL_COMMIT = "05dc342d376425c13f09ee68356583223203aae3"
BOOTSTRAP_SEED = 20_260_914
BOOTSTRAP_REPLICATES = 10_000
RECONSTRUCTION_TOLERANCE_A = 1e-6
_EXPECTED_REPLAY = MappingProxyType(
    {"S1": 28.594881529741027, "Equal": 28.91728598859252, "TotalDeparture": 28.435454290098633}
)
_REQUIRED_FIELDS = {
    "issue_times", "day_start_utc_s", "y_true", "arrival_truth",
    "base_arrival_predictions", "availability_arrival_predictions",
    "departure_arrival_predictions", "s1_existing_predictions",
    "s1_predictions", "equal_predictions", "total_availability_predictions",
    "total_departure_predictions",
}


class R10R0Error(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        if not isinstance(reason_code, str) or not reason_code or not reason_code.replace("_", "").isalnum():
            reason_code = "UNEXPECTED_ERROR"
        self.reason_code = reason_code
        super().__init__(reason_code)


def _mae(truth: np.ndarray, pred: np.ndarray) -> float:
    if truth.shape != pred.shape or truth.ndim != 1 or not len(truth):
        raise R10R0Error("METRIC_INVALID")
    if not np.isfinite(truth).all() or not np.isfinite(pred).all():
        raise R10R0Error("METRIC_INVALID")
    return float(np.mean(np.abs(pred - truth)))


def _load_reference(root: Path, month: str, horizon: int) -> dict[str, np.ndarray]:
    try:
        ref = _load_npz(root / f"{month}_h{horizon:03d}.npz", _REQUIRED_FIELDS)
    except Exception as exc:
        raise R10R0Error("R7_D1_PRIVATE_CACHE_SCHEMA_INVALID") from exc
    expected_n = EXPECTED_ROWS_BY_MONTH[month]
    if any(array.shape != (expected_n,) for array in ref.values()):
        raise R10R0Error("R7_D1_PRIVATE_CACHE_SCHEMA_INVALID")
    if (
        ref["issue_times"].dtype != np.dtype(np.int64)
        or ref["day_start_utc_s"].dtype != np.dtype(np.int64)
        or np.any(np.diff(ref["issue_times"]) <= 0)
        or np.any(np.diff(ref["day_start_utc_s"]) < 0)
        or np.any(ref["day_start_utc_s"] > ref["issue_times"])
    ):
        raise R10R0Error("R7_D1_PRIVATE_CACHE_SCHEMA_INVALID")
    if not all(
        np.isfinite(array).all()
        for key, array in ref.items()
        if key not in {"issue_times", "day_start_utc_s"}
    ):
        raise R10R0Error("R7_D1_PRIVATE_CACHE_SCHEMA_INVALID")
    existing = ref["s1_existing_predictions"]
    checks = (
        (existing + ref["base_arrival_predictions"], ref["s1_predictions"]),
        (existing + ref["availability_arrival_predictions"], ref["total_availability_predictions"]),
        (existing + ref["departure_arrival_predictions"], ref["total_departure_predictions"]),
    )
    if not all(np.allclose(left, right, rtol=0.0, atol=RECONSTRUCTION_TOLERANCE_A) for left, right in checks):
        raise R10R0Error("R7_D1_PRIVATE_CACHE_RECONSTRUCTION_INVALID")
    return ref


def _record(month: str, horizon: int, ref: Mapping[str, np.ndarray]) -> dict[str, Any]:
    return {
        "month": month, "horizon": horizon,
        "issue_times": np.asarray(ref["issue_times"], dtype=np.int64),
        "day_starts": np.asarray(ref["day_start_utc_s"], dtype=np.int64),
        "truth": np.asarray(ref["y_true"], dtype=np.float64),
        "candidate": np.asarray(ref["total_departure_predictions"], dtype=np.float64),
        "s1": np.asarray(ref["s1_predictions"], dtype=np.float64),
        "equal": np.asarray(ref["equal_predictions"], dtype=np.float64),
        "arrival_truth": np.asarray(ref["arrival_truth"], dtype=np.float64),
        "base_arrival": np.asarray(ref["base_arrival_predictions"], dtype=np.float64),
        "availability_arrival": np.asarray(ref["availability_arrival_predictions"], dtype=np.float64),
        "departure_arrival": np.asarray(ref["departure_arrival_predictions"], dtype=np.float64),
    }


def _validate_common_rows(records: Sequence[Mapping[str, Any]]) -> None:
    if len(records) != 20:
        raise R10R0Error("COMMON_ROW_IDENTITY_INVALID")
    for month in DEVELOPMENT_MONTHS:
        items = sorted((r for r in records if r["month"] == month), key=lambda r: int(r["horizon"]))
        if tuple(int(r["horizon"]) for r in items) != HORIZONS_MINUTES:
            raise R10R0Error("COMMON_ROW_IDENTITY_INVALID")
        issue = np.asarray(items[0]["issue_times"])
        days = np.asarray(items[0]["day_starts"])
        if not len(np.unique(days)):
            raise R10R0Error("COMMON_ROW_IDENTITY_INVALID")
        if any(not np.array_equal(issue, r["issue_times"]) or not np.array_equal(days, r["day_starts"]) for r in items[1:]):
            raise R10R0Error("COMMON_ROW_IDENTITY_INVALID")


def _cat(records: Sequence[Mapping[str, Any]], key: str) -> np.ndarray:
    return np.concatenate([np.asarray(record[key]) for record in records])


def _total_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        raise R10R0Error("METRIC_INVALID")
    truth = _cat(records, "truth")
    return {
        "n": int(len(truth)),
        "TotalDeparture_mae_a": _mae(truth, _cat(records, "candidate")),
        "S1_mae_a": _mae(truth, _cat(records, "s1")),
        "Equal_mae_a": _mae(truth, _cat(records, "equal")),
    }


def _component_context(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    truth = _cat(records, "arrival_truth")
    return {
        "n": int(len(truth)),
        "BaseM2_mae_a": _mae(truth, _cat(records, "base_arrival")),
        "DepartureAvailability_mae_a": _mae(truth, _cat(records, "availability_arrival")),
        "DepartureAug_mae_a": _mae(truth, _cat(records, "departure_arrival")),
    }


def _assert_replay(pooled: Mapping[str, Any]) -> None:
    observed = {
        "S1": float(pooled["S1_mae_a"]), "Equal": float(pooled["Equal_mae_a"]),
        "TotalDeparture": float(pooled["TotalDeparture_mae_a"]),
    }
    if any(not np.isclose(observed[key], value, rtol=0.0, atol=1e-10) for key, value in _EXPECTED_REPLAY.items()):
        raise R10R0Error("R7_D1_REPLAY_INVALID")


def _relative_degradation(reference: float, candidate: float) -> float:
    if reference <= 0.0 or candidate < 0.0:
        raise R10R0Error("METRIC_INVALID")
    return float((candidate - reference) / reference)


def _daily_audit(records: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, dict[str, np.ndarray]]]:
    _validate_common_rows(records)
    deltas: dict[str, dict[str, np.ndarray]] = {}
    per_month: list[dict[str, Any]] = []
    for month in DEVELOPMENT_MONTHS:
        items = sorted((r for r in records if r["month"] == month), key=lambda r: int(r["horizon"]))
        days = np.unique(np.asarray(items[0]["day_starts"], dtype=np.int64))
        d_s1: list[float] = []
        d_equal: list[float] = []
        for day in days:
            truth = np.concatenate([np.asarray(r["truth"])[np.asarray(r["day_starts"]) == day] for r in items])
            candidate = np.concatenate([np.asarray(r["candidate"])[np.asarray(r["day_starts"]) == day] for r in items])
            s1 = np.concatenate([np.asarray(r["s1"])[np.asarray(r["day_starts"]) == day] for r in items])
            equal = np.concatenate([np.asarray(r["equal"])[np.asarray(r["day_starts"]) == day] for r in items])
            candidate_mae = _mae(truth, candidate)
            d_s1.append(candidate_mae - _mae(truth, s1))
            d_equal.append(candidate_mae - _mae(truth, equal))
        a_s1 = np.asarray(d_s1, dtype=np.float64)
        a_equal = np.asarray(d_equal, dtype=np.float64)
        if not len(a_s1) or not np.isfinite(a_s1).all() or not np.isfinite(a_equal).all():
            raise R10R0Error("DAILY_PAIRING_INVALID")
        deltas[month] = {"vs_S1": a_s1, "vs_Equal": a_equal}
        per_month.append({
            "month": month, "day_count": int(len(a_s1)),
            "wins_vs_S1": int(np.sum(a_s1 < 0.0)), "win_rate_vs_S1": float(np.mean(a_s1 < 0.0)),
            "mean_delta_vs_S1_a": float(np.mean(a_s1)),
            "wins_vs_Equal": int(np.sum(a_equal < 0.0)), "win_rate_vs_Equal": float(np.mean(a_equal < 0.0)),
            "mean_delta_vs_Equal_a": float(np.mean(a_equal)),
        })
    all_s1 = np.concatenate([deltas[m]["vs_S1"] for m in DEVELOPMENT_MONTHS])
    all_equal = np.concatenate([deltas[m]["vs_Equal"] for m in DEVELOPMENT_MONTHS])

    def concentration(delta: np.ndarray) -> float | None:
        gains = np.maximum(-delta, 0.0)
        total = float(np.sum(gains))
        if total == 0.0:
            return None
        return float(np.sum(np.sort(gains)[-min(5, len(gains)):]) / total)

    return ({
        "day_count": int(len(all_s1)),
        "wins_vs_S1": int(np.sum(all_s1 < 0.0)), "win_rate_vs_S1": float(np.mean(all_s1 < 0.0)),
        "mean_delta_vs_S1_a": float(np.mean(all_s1)), "median_delta_vs_S1_a": float(np.median(all_s1)),
        "top5_positive_gain_share_vs_S1": concentration(all_s1),
        "wins_vs_Equal": int(np.sum(all_equal < 0.0)), "win_rate_vs_Equal": float(np.mean(all_equal < 0.0)),
        "mean_delta_vs_Equal_a": float(np.mean(all_equal)), "median_delta_vs_Equal_a": float(np.median(all_equal)),
        "top5_positive_gain_share_vs_Equal": concentration(all_equal), "per_month": per_month,
    }, deltas)


def _leave_one(records: Sequence[Mapping[str, Any]], *, axis: str) -> dict[str, Any]:
    if axis == "month":
        values: Sequence[str | int] = DEVELOPMENT_MONTHS
        key = "omitted_month"
        selector = lambda r, x: r["month"] != x
    elif axis == "horizon":
        values = HORIZONS_MINUTES
        key = "omitted_horizon_minutes"
        selector = lambda r, x: int(r["horizon"]) != x
    else:
        raise R10R0Error("PROTOCOL_INVALID")
    items: list[dict[str, Any]] = []
    for value in values:
        summary = _total_summary([r for r in records if selector(r, value)])
        candidate = float(summary["TotalDeparture_mae_a"])
        s1 = float(summary["S1_mae_a"])
        equal = float(summary["Equal_mae_a"])
        items.append({key: value, **summary, "win_vs_S1": bool(candidate < s1), "win_vs_Equal": bool(candidate < equal)})
    return {
        "aggregates": items,
        "wins_vs_S1": int(sum(bool(item["win_vs_S1"]) for item in items)),
        "wins_vs_Equal": int(sum(bool(item["win_vs_Equal"]) for item in items)),
    }


def _original_stability(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def row(label: str, value: str | int, selected: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        summary = _total_summary(selected)
        candidate, s1, equal = (float(summary[k]) for k in ("TotalDeparture_mae_a", "S1_mae_a", "Equal_mae_a"))
        return {
            label: value, **summary, "win_vs_S1": bool(candidate < s1), "win_vs_Equal": bool(candidate < equal),
            "relative_degradation_vs_S1": _relative_degradation(s1, candidate),
            "relative_degradation_vs_Equal": _relative_degradation(equal, candidate),
        }
    by_month = [row("month", month, [r for r in records if r["month"] == month]) for month in DEVELOPMENT_MONTHS]
    by_horizon = [row("horizon_minutes", horizon, [r for r in records if int(r["horizon"]) == horizon]) for horizon in HORIZONS_MINUTES]
    if any(int(item["n"]) != EXPECTED_ROWS_PER_HORIZON for item in by_horizon):
        raise R10R0Error("COMMON_ROW_IDENTITY_INVALID")
    return {
        "by_month": by_month, "by_horizon": by_horizon,
        "month_wins_vs_S1": int(sum(bool(x["win_vs_S1"]) for x in by_month)),
        "month_wins_vs_Equal": int(sum(bool(x["win_vs_Equal"]) for x in by_month)),
        "horizon_wins_vs_S1": int(sum(bool(x["win_vs_S1"]) for x in by_horizon)),
        "horizon_wins_vs_Equal": int(sum(bool(x["win_vs_Equal"]) for x in by_horizon)),
        "worst_month_relative_degradation_vs_S1": float(max(float(x["relative_degradation_vs_S1"]) for x in by_month)),
        "worst_month_relative_degradation_vs_Equal": float(max(float(x["relative_degradation_vs_Equal"]) for x in by_month)),
        "worst_horizon_relative_degradation_vs_S1": float(max(float(x["relative_degradation_vs_S1"]) for x in by_horizon)),
        "worst_horizon_relative_degradation_vs_Equal": float(max(float(x["relative_degradation_vs_Equal"]) for x in by_horizon)),
    }


def _bootstrap(deltas: Mapping[str, Mapping[str, np.ndarray]]) -> dict[str, Any]:
    rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
    b_s1 = np.zeros(BOOTSTRAP_REPLICATES, dtype=np.float64)
    b_equal = np.zeros(BOOTSTRAP_REPLICATES, dtype=np.float64)
    for month in DEVELOPMENT_MONTHS:
        s1 = np.asarray(deltas[month]["vs_S1"], dtype=np.float64)
        equal = np.asarray(deltas[month]["vs_Equal"], dtype=np.float64)
        indexes = rng.integers(0, len(s1), size=(BOOTSTRAP_REPLICATES, len(s1)))
        b_s1 += np.mean(s1[indexes], axis=1) / 4.0
        b_equal += np.mean(equal[indexes], axis=1) / 4.0

    def desc(values: np.ndarray) -> dict[str, float]:
        q = np.quantile(values, [0.05, 0.50, 0.95], method="linear")
        return {"q05_delta_a": float(q[0]), "q50_delta_a": float(q[1]), "q95_delta_a": float(q[2]), "fraction_delta_below_zero": float(np.mean(values < 0.0))}
    return {"seed": BOOTSTRAP_SEED, "replicates": BOOTSTRAP_REPLICATES, "sampling_unit": "complete_local_day_within_month", "month_weighting": "equal", "quantile_method": "linear", "vs_S1": desc(b_s1), "vs_Equal": desc(b_equal)}


def decide_r10(pooled: Mapping[str, Any], daily: Mapping[str, Any], leave_month: Mapping[str, Any], leave_horizon: Mapping[str, Any], stability: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    candidate, s1, equal = (float(pooled[k]) for k in ("TotalDeparture_mae_a", "S1_mae_a", "Equal_mae_a"))
    day_s1, day_equal = float(daily["win_rate_vs_S1"]), float(daily["win_rate_vs_Equal"])
    lomo_s1, lomo_equal = int(leave_month["wins_vs_S1"]), int(leave_month["wins_vs_Equal"])
    loho_s1, loho_equal = int(leave_horizon["wins_vs_S1"]), int(leave_horizon["wins_vs_Equal"])
    month_s1, month_equal = int(stability["month_wins_vs_S1"]), int(stability["month_wins_vs_Equal"])
    horizon_s1, horizon_equal = int(stability["horizon_wins_vs_S1"]), int(stability["horizon_wins_vs_Equal"])
    worst_s1 = float(stability["worst_month_relative_degradation_vs_S1"])
    worst_equal = float(stability["worst_month_relative_degradation_vs_Equal"])
    fragile = candidate >= s1 or candidate >= equal or lomo_s1 <= 2 or lomo_equal <= 2 or day_s1 < 0.40 or day_equal < 0.40
    ready = (
        not fragile and month_s1 >= 3 and month_equal >= 3 and horizon_s1 >= 3 and horizon_equal >= 3
        and day_s1 >= 0.50 and day_equal >= 0.50 and lomo_s1 == 4 and lomo_equal == 4
        and loho_s1 >= 4 and loho_equal >= 4 and worst_s1 <= 0.05 and worst_equal <= 0.05
    )
    decision = "FRAGILE_DEVELOPMENT_SIGNAL" if fragile else ("READY_FOR_SINGLE_SHOT_HOLDOUT_PROTOCOL" if ready else "MIXED_DEVELOPMENT_ROBUSTNESS")
    support = {
        "pooled_improvement_vs_S1_fraction": float((s1 - candidate) / s1),
        "pooled_improvement_vs_Equal_fraction": float((equal - candidate) / equal),
        "day_win_rate_vs_S1": day_s1, "day_win_rate_vs_Equal": day_equal,
        "leave_one_month_wins_vs_S1": lomo_s1, "leave_one_month_wins_vs_Equal": lomo_equal,
        "leave_one_horizon_wins_vs_S1": loho_s1, "leave_one_horizon_wins_vs_Equal": loho_equal,
        "original_month_wins_vs_S1": month_s1, "original_month_wins_vs_Equal": month_equal,
        "original_horizon_wins_vs_S1": horizon_s1, "original_horizon_wins_vs_Equal": horizon_equal,
        "worst_original_month_relative_degradation_vs_S1": worst_s1,
        "worst_original_month_relative_degradation_vs_Equal": worst_equal,
    }
    return decision, support


def run_r10_r0(*, authorized: bool, r7_d1_private_run: str | Path, code_commit: str) -> dict[str, Any]:
    if authorized is not True:
        raise R10R0Error("R10_R0_NOT_AUTHORIZED")
    source = Path(r7_d1_private_run).resolve(strict=True)
    if not source.is_dir() or source.is_symlink():
        raise R10R0Error("R7_D1_PRIVATE_CACHE_IDENTITY_INVALID")
    try:
        manifest = _verify_private_manifest(source, expected_sha256=EXPECTED_R7_D1_PRIVATE_MANIFEST_SHA256, schema_version="evcf-jpl-r7-d1-private-cache/v1", entries_key="entries")
    except Exception as exc:
        raise R10R0Error("R7_D1_PRIVATE_CACHE_IDENTITY_INVALID") from exc
    if manifest.get("code_commit") != R7_D1_REVIEWED_EXECUTABLE or manifest.get("protocol_commit") != R7_D1_PROTOCOL_COMMIT or manifest.get("source_r7_status_sha256") != SOURCE_R7_C0_STATUS_SHA256:
        raise R10R0Error("R7_D1_PRIVATE_CACHE_IDENTITY_INVALID")
    records = [_record(month, horizon, _load_reference(source, month, horizon)) for month in DEVELOPMENT_MONTHS for horizon in HORIZONS_MINUTES]
    _validate_common_rows(records)
    if sum(len(r["truth"]) for r in records) != EXPECTED_RECORD_COUNT:
        raise R10R0Error("COMMON_ROW_IDENTITY_INVALID")
    pooled = _total_summary(records)
    _assert_replay(pooled)
    daily, deltas = _daily_audit(records)
    leave_month = _leave_one(records, axis="month")
    leave_horizon = _leave_one(records, axis="horizon")
    stability = _original_stability(records)
    decision, support = decide_r10(pooled, daily, leave_month, leave_horizon, stability)
    return {
        "schema_version": "evcf-jpl-r10-r0-summary/v1", "status": "COMPLETE", "decision": decision,
        "decision_support": support, "code_commit": code_commit, "protocol_commit": R10_PROTOCOL_COMMIT,
        "source_r7_d1_status_sha256": SOURCE_R7_D1_STATUS_SHA256,
        "source_r7_d1_private_manifest_sha256": EXPECTED_R7_D1_PRIVATE_MANIFEST_SHA256,
        "source_r7_d1_reviewed_executable": R7_D1_REVIEWED_EXECUTABLE,
        "source_r9_status_sha256": SOURCE_R9_STATUS_SHA256, "source_r9_decision": SOURCE_R9_DECISION,
        "source_r9_decision_unchanged": True, "pooled_total": pooled,
        "pooled_arrival_component_context": _component_context(records), "daily_paired_audit": daily,
        "leave_one_month_out": leave_month, "leave_one_horizon_out": leave_horizon,
        "original_month_horizon_stability": stability, "stratified_day_bootstrap": _bootstrap(deltas),
        "fit_count": 0, "model_fit_attempted": False, "holdout_accessed": False,
        "reference_models_retrained": False, "r7_candidate_retrained": False,
        "hyperparameter_search": False, "feature_search": False, "prediction_clipping": False,
        "prediction_calibration": False, "gate_trained": False, "moe_trained": False,
        "neural_model_trained": False, "survival_model_trained": False, "tpp_model_trained": False,
        "network_data_acquisition": False,
    }
