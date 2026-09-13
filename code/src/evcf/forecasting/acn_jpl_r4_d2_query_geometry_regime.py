"""Read-only R4-D2 query-level geometry-regime diagnostic."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

import evcf.forecasting.acn_jpl_r4_d1_state_geometry_diagnostic as d1

SOURCE_D1_STATUS_SHA256 = "522af0c71236ad3da7d8de006875394420f702aa650613660e619d8dd0048c94"
SOURCE_D1_CODE_COMMIT = "51048259f8d9c61f324db07e05ded0a3c2f9d48e"
SOURCE_R4_DECISION = "MIXED_STATE_ALIASING_SIGNAL"
D2_PROTOCOL_MERGE_COMMIT = "61f00f9293d012d599d4c2f8417fc9ea7a53a58e"
ACCEPTED_REFERENCE_RELATIVE = PurePosixPath(
    "code/configs/acn_jpl_r4_d1_accepted_reference_20260913.json"
)
SCORE_EPS = 1e-12
QUANTILE_PROBABILITIES = (0.25, 0.50, 0.75)
BIN_NAMES = ("Q1", "Q2", "Q3", "Q4")

IMPLEMENTATION_PATHS = (
    "docs/JPL_R4_D2_QUERY_GEOMETRY_REGIME_PROTOCOL_20260913.md",
    str(ACCEPTED_REFERENCE_RELATIVE),
    "code/src/evcf/forecasting/acn_jpl_r4_d1_state_geometry_diagnostic.py",
    "code/src/evcf/forecasting/acn_jpl_r4_d2_query_geometry_regime.py",
    "scripts/run_jpl_r4_d2_query_geometry_regime.py",
)

Progress = Callable[[str], None]


class R4D2Error(RuntimeError):
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
        raise R4D2Error("IMPLEMENTATION_DRIFT")
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
        raise R4D2Error("IMPLEMENTATION_DRIFT")
    for relative in IMPLEMENTATION_PATHS:
        path = repo_root / PurePosixPath(relative)
        if not path.is_file() or path.is_symlink():
            raise R4D2Error("IMPLEMENTATION_DRIFT")
        exists = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if exists.returncode:
            raise R4D2Error("IMPLEMENTATION_DRIFT")
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
        raise R4D2Error("IMPLEMENTATION_DRIFT")


def load_accepted_reference(repo_root: Path) -> Mapping[str, Any]:
    path = repo_root / ACCEPTED_REFERENCE_RELATIVE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R4D2Error("ACCEPTED_REFERENCE_INVALID") from exc
    if not isinstance(payload, dict):
        raise R4D2Error("ACCEPTED_REFERENCE_INVALID")
    required = {
        "schema_version",
        "source_status_sha256",
        "code_commit",
        "d1_protocol_merge_commit",
        "source_r4_status_sha256",
        "source_r4_code_commit",
        "source_r4_decision",
        "preprocessor_fit_count",
        "pooled_records",
        "aggregate_sha256",
    }
    if not required.issubset(payload):
        raise R4D2Error("ACCEPTED_REFERENCE_INVALID")
    if payload["schema_version"] != "evcf-jpl-r4-d1-accepted-reference/v1":
        raise R4D2Error("ACCEPTED_REFERENCE_INVALID")
    if payload["source_status_sha256"] != SOURCE_D1_STATUS_SHA256:
        raise R4D2Error("ACCEPTED_REFERENCE_INVALID")
    if payload["code_commit"] != SOURCE_D1_CODE_COMMIT:
        raise R4D2Error("ACCEPTED_REFERENCE_INVALID")
    if payload["source_r4_decision"] != SOURCE_R4_DECISION:
        raise R4D2Error("ACCEPTED_REFERENCE_INVALID")
    digest = payload["aggregate_sha256"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise R4D2Error("ACCEPTED_REFERENCE_INVALID")
    return payload


def _aggregate_payload(public: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "pooled_overall",
        "pooled_by_horizon",
        "pooled_by_month",
        "month_horizon_cells",
    )
    if any(key not in public for key in keys):
        raise R4D2Error("D1_REPLAY_MISMATCH")
    return {key: public[key] for key in keys}


def aggregate_sha256(public: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            _aggregate_payload(public),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise R4D2Error("D1_REPLAY_MISMATCH") from exc
    return hashlib.sha256(encoded).hexdigest()


def assert_d1_replay_matches(
    actual_public: Mapping[str, Any], reference: Mapping[str, Any]
) -> None:
    checks = (
        actual_public.get("status") == "COMPLETE",
        actual_public.get("d1_protocol_merge_commit") == reference["d1_protocol_merge_commit"],
        actual_public.get("source_r4_status_sha256") == reference["source_r4_status_sha256"],
        actual_public.get("source_r4_code_commit") == reference["source_r4_code_commit"],
        actual_public.get("source_r4_decision") == SOURCE_R4_DECISION,
        actual_public.get("scientific_decision_unchanged") is True,
        actual_public.get("r4_replay_verified") is True,
        actual_public.get("fit_count") == 0,
        actual_public.get("holdout_accessed") is False,
        actual_public.get("preprocessor_fit_count") == reference["preprocessor_fit_count"],
        int(actual_public["pooled_overall"]["records"]) == int(reference["pooled_records"]),
        aggregate_sha256(actual_public) == reference["aggregate_sha256"],
    )
    if not all(checks):
        raise R4D2Error("D1_REPLAY_MISMATCH")


def _run_d1_and_capture_records(
    *,
    interim: Path,
    processed: Path,
    code_commit: str,
    repo: Path,
    expected_records: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run the exact D1 implementation while passively capturing its pooled record list."""

    original_aggregate = d1.aggregate_geometry
    captured: list[dict[str, Any]] | None = None

    def capture(records: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
        nonlocal captured
        result = original_aggregate(records)
        if captured is None and result is not None and result.get("records") == expected_records:
            captured = [dict(item) for item in records]
        return result

    d1.aggregate_geometry = capture
    try:
        public = d1.run_diagnostic(
            interim_root=interim,
            processed_root=processed,
            code_commit=code_commit,
            repo_root=repo,
            progress=None,
        )
    except d1.R4D1Error as exc:
        raise R4D2Error(exc.reason_code) from exc
    finally:
        d1.aggregate_geometry = original_aggregate

    if captured is None or len(captured) != expected_records:
        raise R4D2Error("D1_RECORD_CAPTURE_INVALID")
    return public, captured


def geometry_scores(record: Mapping[str, Any]) -> dict[str, float]:
    try:
        c_level = float(record["C_Level"])
        c_m3 = float(record["C_M3"])
        qe_level = float(record["QE_Level"])
        qe_m3 = float(record["QE_M3"])
        q3_level = float(record["Q3_Level"])
        q3_m3 = float(record["Q3_M3"])
        d_level = float(record["D_Level"])
        d_m3 = float(record["D_M3"])
    except (KeyError, TypeError, ValueError) as exc:
        raise R4D2Error("SCORE_INPUT_INVALID") from exc
    values = (c_level, c_m3, qe_level, qe_m3, q3_level, q3_m3, d_level, d_m3)
    if not all(math.isfinite(value) and value >= 0.0 for value in values):
        raise R4D2Error("SCORE_INPUT_INVALID")

    s_current = (c_m3 - c_level) / (c_m3 + c_level + SCORE_EPS)
    s_session = (qe_level - qe_m3) / (qe_level + qe_m3 + SCORE_EPS)
    s_full = (q3_level - q3_m3) / (q3_level + q3_m3 + SCORE_EPS)
    result = {
        "S_current": float(s_current),
        "S_session": float(s_session),
        "S_full": float(s_full),
        "B": float(s_session - s_current),
        "A": float(d_level - d_m3),
    }
    if not all(math.isfinite(value) for value in result.values()):
        raise R4D2Error("SCORE_INVALID")
    return result


def _continuous_summary(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or not len(array) or not np.isfinite(array).all():
        raise R4D2Error("REGIME_AGGREGATE_INVALID")
    return {"mean": float(np.mean(array)), "median": float(np.median(array))}


def _average_ranks(values: Sequence[float]) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or len(array) < 2 or not np.isfinite(array).all():
        raise R4D2Error("ASSOCIATION_INVALID")
    order = np.argsort(array, kind="mergesort")
    sorted_values = array[order]
    ranks = np.empty(len(array), dtype=np.float64)
    start = 0
    while start < len(array):
        stop = start + 1
        while stop < len(array) and sorted_values[stop] == sorted_values[start]:
            stop += 1
        ranks[order[start:stop]] = 0.5 * (start + stop - 1) + 1.0
        start = stop
    return ranks


def spearman_rho(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        raise R4D2Error("ASSOCIATION_INVALID")
    left_ranks = _average_ranks(left)
    right_ranks = _average_ranks(right)
    left_centered = left_ranks - float(np.mean(left_ranks))
    right_centered = right_ranks - float(np.mean(right_ranks))
    denominator = math.sqrt(
        float(np.dot(left_centered, left_centered))
        * float(np.dot(right_centered, right_centered))
    )
    if denominator <= 0.0 or not math.isfinite(denominator):
        return None
    rho = float(np.dot(left_centered, right_centered) / denominator)
    if not math.isfinite(rho):
        raise R4D2Error("ASSOCIATION_INVALID")
    return max(-1.0, min(1.0, rho))


def pooled_quartile_cutpoints(
    records: Sequence[Mapping[str, Any]],
) -> tuple[float, float, float]:
    values = np.asarray([float(item["B"]) for item in records], dtype=np.float64)
    if values.ndim != 1 or len(values) < 4 or not np.isfinite(values).all():
        raise R4D2Error("QUARTILE_INVALID")
    cuts = np.asarray(
        np.quantile(values, QUANTILE_PROBABILITIES, method="higher"), dtype=np.float64
    )
    if cuts.shape != (3,) or not np.isfinite(cuts).all() or np.any(np.diff(cuts) < 0.0):
        raise R4D2Error("QUARTILE_INVALID")
    return tuple(float(value) for value in cuts)


def assign_quartile(value: float, cutpoints: Sequence[float]) -> str:
    if len(cutpoints) != 3:
        raise R4D2Error("QUARTILE_INVALID")
    q25, q50, q75 = (float(item) for item in cutpoints)
    score = float(value)
    if not all(math.isfinite(item) for item in (score, q25, q50, q75)) or not (
        q25 <= q50 <= q75
    ):
        raise R4D2Error("QUARTILE_INVALID")
    if score <= q25:
        return "Q1"
    if score <= q50:
        return "Q2"
    if score <= q75:
        return "Q3"
    return "Q4"


def _bin_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "records": 0,
            "B": None,
            "S_current": None,
            "S_session": None,
            "S_full": None,
            "A": None,
            "m3_advantage_fraction": None,
            "O_Level_M3_mean": None,
        }
    advantages = np.asarray([float(item["A"]) for item in records], dtype=np.float64)
    if not np.isfinite(advantages).all():
        raise R4D2Error("REGIME_AGGREGATE_INVALID")
    return {
        "records": len(records),
        "B": _continuous_summary([float(item["B"]) for item in records]),
        "S_current": _continuous_summary([float(item["S_current"]) for item in records]),
        "S_session": _continuous_summary([float(item["S_session"]) for item in records]),
        "S_full": _continuous_summary([float(item["S_full"]) for item in records]),
        "A": _continuous_summary(advantages.tolist()),
        "m3_advantage_fraction": float(np.mean(advantages > 0.0)),
        "O_Level_M3_mean": float(
            np.mean(np.asarray([int(item["O_Level_M3"]) for item in records], dtype=np.float64))
        ),
    }


def aggregate_regime(
    records: Sequence[Mapping[str, Any]], cutpoints: Sequence[float]
) -> dict[str, Any] | None:
    if not records:
        return None
    bins: dict[str, list[Mapping[str, Any]]] = {name: [] for name in BIN_NAMES}
    for item in records:
        bins[assign_quartile(float(item["B"]), cutpoints)].append(item)
    summaries = {name: _bin_summary(bins[name]) for name in BIN_NAMES}
    q1 = summaries["Q1"]
    q4 = summaries["Q4"]
    mean_delta = None
    fraction_delta = None
    if q1["records"] and q4["records"]:
        mean_delta = float(q4["A"]["mean"] - q1["A"]["mean"])
        fraction_delta = float(
            q4["m3_advantage_fraction"] - q1["m3_advantage_fraction"]
        )
    return {
        "records": len(records),
        "spearman_B_A": spearman_rho(
            [float(item["B"]) for item in records],
            [float(item["A"]) for item in records],
        ),
        "bins": summaries,
        "Q4_minus_Q1_mean_A": mean_delta,
        "Q4_minus_Q1_m3_advantage_fraction": fraction_delta,
    }


def _attach_scores(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        item.update(geometry_scores(record))
        scored.append(item)
    return scored


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
        progress("R4_D2_STAGE=REPLAY_D1_AND_CAPTURE_RECORDS")
    public_d1, records = _run_d1_and_capture_records(
        interim=interim,
        processed=processed,
        code_commit=code_commit,
        repo=repo,
        expected_records=int(reference["pooled_records"]),
    )
    assert_d1_replay_matches(public_d1, reference)

    scored = _attach_scores(records)
    cutpoints = pooled_quartile_cutpoints(scored)
    pooled = aggregate_regime(scored, cutpoints)

    by_horizon = []
    for horizon in d1.r4.HORIZONS_MINUTES:
        metrics = aggregate_regime(
            [item for item in scored if item["horizon_minutes"] == horizon], cutpoints
        )
        by_horizon.append({"horizon_minutes": horizon, **({} if metrics is None else metrics)})
    by_month = []
    for month in d1.r4.DEVELOPMENT_MONTHS:
        metrics = aggregate_regime(
            [item for item in scored if item["month"] == month], cutpoints
        )
        by_month.append({"month": month, **({} if metrics is None else metrics)})
    cells = []
    for month in d1.r4.DEVELOPMENT_MONTHS:
        for horizon in d1.r4.HORIZONS_MINUTES:
            metrics = aggregate_regime(
                [
                    item
                    for item in scored
                    if item["month"] == month and item["horizon_minutes"] == horizon
                ],
                cutpoints,
            )
            cells.append(
                {
                    "month": month,
                    "horizon_minutes": horizon,
                    **({} if metrics is None else metrics),
                }
            )

    return {
        "schema_version": "evcf-jpl-r4-d2-query-geometry-regime-summary/v1",
        "status": "COMPLETE",
        "code_commit": code_commit,
        "d2_protocol_merge_commit": D2_PROTOCOL_MERGE_COMMIT,
        "source_d1_status_sha256": SOURCE_D1_STATUS_SHA256,
        "source_d1_code_commit": SOURCE_D1_CODE_COMMIT,
        "source_r4_decision": SOURCE_R4_DECISION,
        "scientific_decision_unchanged": True,
        "d1_replay_verified": True,
        "score_eps": SCORE_EPS,
        "quartile_method": "higher",
        "quartile_cutpoints": {
            "q25": cutpoints[0],
            "q50": cutpoints[1],
            "q75": cutpoints[2],
        },
        "pooled_overall": pooled,
        "pooled_by_horizon": by_horizon,
        "pooled_by_month": by_month,
        "month_horizon_cells": cells,
        "fit_count": 0,
        "model_fit_attempted": False,
        "forecast_model_fit_attempted": False,
        "gate_fit_attempted": False,
        "classifier_fit_attempted": False,
        "regressor_fit_attempted": False,
        "holdout_accessed": False,
        "reference_models_retrained": False,
        "alternate_analog_rule": False,
        "metric_learning": False,
        "pca_or_feature_selection": False,
        "target_informed_scoring": False,
        "calendar_month_gating": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
    }
