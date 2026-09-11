"""Read-only residual diagnostic for the completed JPL structured S1 development run.

The diagnostic consumes only the already-persisted development prediction caches from
M2/M3/Equal and S1. It performs no model fitting, does not read raw/interim/processed
data, and never touches the final holdout months. Public output is aggregate only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
_RECONSTRUCTION_TOLERANCE_A = 1e-6
_ZERO_TOLERANCE_A = 1e-12

EXPECTED_STRUCTURED_PROTOCOL_SHA256 = (
    "74af85044d12f3c68fe4156e6ad1ae67b6e5486b47aecd5637cd67d6539c1902"
)
EXPECTED_STRUCTURED_CODE_COMMIT = "8853d17c5a567a8458e0f638eec90cd31b0dab82"
EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256 = (
    "562035b678b75865a54c7f68794b5f4907ea9696100c531498720eb943e570f1"
)
EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256 = (
    "2c2ff4f05081b5227f948165a1b7b78eee80430f2c9be590510d0acf8c34f8dd"
)


class StructuredMixedDiagnosticError(RuntimeError):
    """Static failure code for the read-only MIXED diagnostic."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class DiagnosticIdentity:
    structured_protocol_sha256: str
    structured_code_commit: str
    structured_private_manifest_sha256: str
    baseline_private_manifest_sha256: str


DEFAULT_IDENTITY = DiagnosticIdentity(
    structured_protocol_sha256=EXPECTED_STRUCTURED_PROTOCOL_SHA256,
    structured_code_commit=EXPECTED_STRUCTURED_CODE_COMMIT,
    structured_private_manifest_sha256=EXPECTED_STRUCTURED_PRIVATE_MANIFEST_SHA256,
    baseline_private_manifest_sha256=EXPECTED_BASELINE_PRIVATE_MANIFEST_SHA256,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _expected_names() -> set[str]:
    return {
        f"{month}_h{horizon:03d}.npz"
        for month in DEVELOPMENT_MONTHS
        for horizon in HORIZONS_MINUTES
    }


def _load_json(path: Path, reason_code: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise StructuredMixedDiagnosticError(reason_code)
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StructuredMixedDiagnosticError(reason_code) from exc
    if not isinstance(value, Mapping):
        raise StructuredMixedDiagnosticError(reason_code)
    return value


def discover_run_by_manifest_sha(
    parent: str | Path,
    *,
    expected_manifest_sha256: str,
) -> Path:
    root = Path(parent).resolve(strict=True)
    if root.is_symlink():
        raise StructuredMixedDiagnosticError("PRIVATE_PARENT_INVALID")
    matches: list[Path] = []
    for candidate in sorted(root.glob("run_*")):
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        manifest = candidate / "private_manifest.json"
        if manifest.is_file() and not manifest.is_symlink():
            try:
                digest = _sha256_file(manifest)
            except OSError:
                continue
            if digest == expected_manifest_sha256:
                matches.append(candidate)
    if len(matches) != 1:
        raise StructuredMixedDiagnosticError("PRIVATE_RUN_NOT_UNIQUE")
    return matches[0]


def _verify_file_entries(
    root: Path,
    entries: object,
    *,
    name_key: str,
    reason_code: str,
) -> None:
    expected = _expected_names()
    if not isinstance(entries, list) or len(entries) != len(expected):
        raise StructuredMixedDiagnosticError(reason_code)
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, Mapping):
            raise StructuredMixedDiagnosticError(reason_code)
        name = item.get(name_key)
        digest = item.get("sha256")
        if (
            not isinstance(name, str)
            or name not in expected
            or name in seen
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise StructuredMixedDiagnosticError(reason_code)
        path = root / name
        if (
            not path.is_file()
            or path.is_symlink()
            or _sha256_file(path) != digest
        ):
            raise StructuredMixedDiagnosticError(reason_code)
        seen.add(name)
    if seen != expected:
        raise StructuredMixedDiagnosticError(reason_code)


def _verify_structured_root(
    root: Path,
    *,
    identity: DiagnosticIdentity,
) -> Mapping[str, Any]:
    manifest_path = root / "private_manifest.json"
    if _sha256_file(manifest_path) != identity.structured_private_manifest_sha256:
        raise StructuredMixedDiagnosticError("STRUCTURED_CACHE_INVALID")
    document = _load_json(manifest_path, "STRUCTURED_CACHE_INVALID")
    if (
        document.get("schema_version") != "evcf-jpl-structured-s1-private-cache/v1"
        or document.get("protocol_sha256") != identity.structured_protocol_sha256
        or document.get("code_commit") != identity.structured_code_commit
        or document.get("source_private_manifest_sha256")
        != identity.baseline_private_manifest_sha256
    ):
        raise StructuredMixedDiagnosticError("STRUCTURED_CACHE_INVALID")
    _verify_file_entries(
        root,
        document.get("entries"),
        name_key="name",
        reason_code="STRUCTURED_CACHE_INVALID",
    )
    return document


def _verify_baseline_root(
    root: Path,
    *,
    identity: DiagnosticIdentity,
) -> Mapping[str, Any]:
    manifest_path = root / "private_manifest.json"
    if _sha256_file(manifest_path) != identity.baseline_private_manifest_sha256:
        raise StructuredMixedDiagnosticError("BASELINE_CACHE_INVALID")
    document = _load_json(manifest_path, "BASELINE_CACHE_INVALID")
    if (
        document.get("schema_version")
        != "evcf-jpl-development-expert-private-cache/v1"
        or document.get("holdout_accessed") is not False
        or document.get("gate_trained") is not False
    ):
        raise StructuredMixedDiagnosticError("BASELINE_CACHE_INVALID")
    _verify_file_entries(
        root,
        document.get("files"),
        name_key="name",
        reason_code="BASELINE_CACHE_INVALID",
    )
    return document


def _load_npz(path: Path, expected_keys: set[str], reason_code: str) -> dict[str, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as payload:
            if set(payload.files) != expected_keys:
                raise StructuredMixedDiagnosticError(reason_code)
            arrays = {key: np.asarray(payload[key]) for key in payload.files}
    except StructuredMixedDiagnosticError:
        raise
    except (OSError, ValueError) as exc:
        raise StructuredMixedDiagnosticError(reason_code) from exc
    return arrays


def _validate_vector(value: np.ndarray, *, dtype: np.dtype[Any] | None = None) -> None:
    if value.ndim != 1 or not len(value):
        raise StructuredMixedDiagnosticError("CACHE_ARRAY_INVALID")
    if dtype is not None and value.dtype != dtype:
        raise StructuredMixedDiagnosticError("CACHE_ARRAY_INVALID")
    if np.issubdtype(value.dtype, np.floating) and not np.isfinite(value).all():
        raise StructuredMixedDiagnosticError("CACHE_ARRAY_INVALID")


def _load_pair(
    *,
    structured_root: Path,
    baseline_root: Path,
    month: str,
    horizon: int,
) -> dict[str, np.ndarray]:
    name = f"{month}_h{horizon:03d}.npz"
    structured = _load_npz(
        structured_root / name,
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
        "STRUCTURED_CACHE_INVALID",
    )
    baseline = _load_npz(
        baseline_root / name,
        {
            "issue_times",
            "day_start_utc_s",
            "y_true",
            "m2_predictions",
            "m3_predictions",
            "equal_predictions",
        },
        "BASELINE_CACHE_INVALID",
    )
    for key in ("issue_times", "day_start_utc_s"):
        _validate_vector(structured[key], dtype=np.dtype(np.int64))
        _validate_vector(baseline[key], dtype=np.dtype(np.int64))
    float_keys = (
        "y_true",
        "existing_truth",
        "arrival_truth",
        "existing_predictions",
        "arrival_predictions",
        "structured_predictions",
    )
    for key in float_keys:
        _validate_vector(structured[key], dtype=np.dtype(np.float64))
    for key in ("y_true", "m2_predictions", "m3_predictions", "equal_predictions"):
        _validate_vector(baseline[key], dtype=np.dtype(np.float64))
    n = len(structured["issue_times"])
    if any(len(value) != n for value in structured.values()) or any(
        len(value) != n for value in baseline.values()
    ):
        raise StructuredMixedDiagnosticError("CACHE_ARRAY_INVALID")
    if not (
        np.array_equal(structured["issue_times"], baseline["issue_times"])
        and np.array_equal(structured["day_start_utc_s"], baseline["day_start_utc_s"])
        and np.allclose(
            structured["y_true"],
            baseline["y_true"],
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
    if np.any(structured["existing_truth"] < 0) or np.any(
        structured["arrival_truth"] < 0
    ):
        raise StructuredMixedDiagnosticError("CACHE_ARRAY_INVALID")
    return {**structured, **{f"baseline_{key}": value for key, value in baseline.items()}}


def _mae(truth: np.ndarray, prediction: np.ndarray) -> float:
    return float(np.mean(np.abs(prediction - truth)))


def _wape(truth: np.ndarray, prediction: np.ndarray) -> float | None:
    denominator = float(np.sum(np.abs(truth)))
    if denominator <= _ZERO_TOLERANCE_A:
        return None
    return float(np.sum(np.abs(prediction - truth)) / denominator)


def _branch_metrics(truth: np.ndarray, prediction: np.ndarray) -> dict[str, Any]:
    error = prediction - truth
    return {
        "mae_a": _mae(truth, prediction),
        "wape_ratio": _wape(truth, prediction),
        "signed_bias_a": float(np.mean(error)),
        "negative_prediction_fraction": float(np.mean(prediction < 0)),
    }


def _correlation(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 2 or float(np.std(left)) <= _ZERO_TOLERANCE_A or float(
        np.std(right)
    ) <= _ZERO_TOLERANCE_A:
        return None
    return float(np.corrcoef(left, right)[0, 1])


def _residual_interaction(
    existing_truth: np.ndarray,
    existing_prediction: np.ndarray,
    arrival_truth: np.ndarray,
    arrival_prediction: np.ndarray,
) -> dict[str, Any]:
    existing_error = existing_prediction - existing_truth
    arrival_error = arrival_prediction - arrival_truth
    total_error = existing_error + arrival_error
    branch_absolute = np.abs(existing_error) + np.abs(arrival_error)
    cancellation = branch_absolute - np.abs(total_error)
    denominator = float(np.sum(branch_absolute))
    product = existing_error * arrival_error
    return {
        "residual_pearson_correlation": _correlation(existing_error, arrival_error),
        "same_sign_fraction": float(np.mean(product > 0)),
        "opposite_sign_fraction": float(np.mean(product < 0)),
        "zero_product_fraction": float(np.mean(product == 0)),
        "mean_cancellation_a": float(np.mean(cancellation)),
        "cancellation_fraction_of_branch_absolute_error": (
            None if denominator == 0 else float(np.sum(cancellation) / denominator)
        ),
    }


def _comparison(
    truth: np.ndarray,
    candidate: np.ndarray,
    reference: np.ndarray,
) -> dict[str, Any]:
    candidate_absolute = np.abs(candidate - truth)
    reference_absolute = np.abs(reference - truth)
    reference_mae = float(np.mean(reference_absolute))
    candidate_mae = float(np.mean(candidate_absolute))
    return {
        "candidate_mae_a": candidate_mae,
        "reference_mae_a": reference_mae,
        "improvement_fraction": (
            None
            if reference_mae == 0
            else float((reference_mae - candidate_mae) / reference_mae)
        ),
        "candidate_row_win_fraction": float(
            np.mean(candidate_absolute < reference_absolute)
        ),
        "row_tie_fraction": float(np.mean(candidate_absolute == reference_absolute)),
        "mean_reference_minus_candidate_absolute_error_a": float(
            np.mean(reference_absolute - candidate_absolute)
        ),
    }


def _truth_composition(
    existing_truth: np.ndarray,
    arrival_truth: np.ndarray,
) -> dict[str, float | None]:
    existing_sum = float(np.sum(existing_truth))
    arrival_sum = float(np.sum(arrival_truth))
    total = existing_sum + arrival_sum
    if total <= _ZERO_TOLERANCE_A:
        return {"existing_fraction": None, "arrival_fraction": None}
    return {
        "existing_fraction": existing_sum / total,
        "arrival_fraction": arrival_sum / total,
    }


def _state_bin_summary(record: Mapping[str, np.ndarray]) -> list[dict[str, Any]]:
    truth = record["y_true"]
    arrival_truth = record["arrival_truth"]
    positive = truth > _ZERO_TOLERANCE_A
    share = np.zeros_like(truth)
    share[positive] = np.clip(arrival_truth[positive] / truth[positive], 0.0, 1.0)
    definitions = (
        ("zero_total", ~positive),
        ("arrival_lt_10pct", positive & (share < 0.10)),
        ("arrival_10_to_30pct", positive & (share >= 0.10) & (share < 0.30)),
        ("arrival_30_to_60pct", positive & (share >= 0.30) & (share < 0.60)),
        ("arrival_ge_60pct", positive & (share >= 0.60)),
    )
    rows: list[dict[str, Any]] = []
    for label, mask in definitions:
        if not np.any(mask):
            continue
        s1 = record["structured_predictions"][mask]
        equal = record["baseline_equal_predictions"][mask]
        m3 = record["baseline_m3_predictions"][mask]
        local_truth = truth[mask]
        rows.append(
            {
                "state_bin": label,
                "n": int(np.sum(mask)),
                "mean_realized_arrival_fraction": (
                    None if label == "zero_total" else float(np.mean(share[mask]))
                ),
                "S1_mae_a": _mae(local_truth, s1),
                "equal_mae_a": _mae(local_truth, equal),
                "M3_mae_a": _mae(local_truth, m3),
                "S1_vs_equal": _comparison(local_truth, s1, equal),
                "S1_vs_M3": _comparison(local_truth, s1, m3),
            }
        )
    return rows


def _summarize_record(record: Mapping[str, np.ndarray]) -> dict[str, Any]:
    return {
        "n": len(record["y_true"]),
        "truth_composition": _truth_composition(
            record["existing_truth"], record["arrival_truth"]
        ),
        "existing_branch": _branch_metrics(
            record["existing_truth"], record["existing_predictions"]
        ),
        "arrival_branch": _branch_metrics(
            record["arrival_truth"], record["arrival_predictions"]
        ),
        "residual_interaction": _residual_interaction(
            record["existing_truth"],
            record["existing_predictions"],
            record["arrival_truth"],
            record["arrival_predictions"],
        ),
        "S1_vs_equal": _comparison(
            record["y_true"],
            record["structured_predictions"],
            record["baseline_equal_predictions"],
        ),
        "S1_vs_M3": _comparison(
            record["y_true"],
            record["structured_predictions"],
            record["baseline_m3_predictions"],
        ),
        "realized_arrival_state_bins": _state_bin_summary(record),
    }


def _concatenate(records: list[Mapping[str, np.ndarray]]) -> dict[str, np.ndarray]:
    if not records:
        raise StructuredMixedDiagnosticError("DIAGNOSTIC_EMPTY")
    keys = tuple(records[0])
    if any(tuple(record) != keys for record in records[1:]):
        raise StructuredMixedDiagnosticError("CACHE_ARRAY_INVALID")
    return {key: np.concatenate([record[key] for record in records]) for key in keys}


def run_structured_mixed_diagnostic(
    *,
    authorized: bool,
    structured_private_parent: str | Path,
    baseline_private_parent: str | Path,
    identity: DiagnosticIdentity = DEFAULT_IDENTITY,
) -> dict[str, Any]:
    if authorized is not True:
        raise StructuredMixedDiagnosticError("MIXED_DIAGNOSTIC_NOT_AUTHORIZED")
    structured_root = discover_run_by_manifest_sha(
        structured_private_parent,
        expected_manifest_sha256=identity.structured_private_manifest_sha256,
    )
    baseline_root = discover_run_by_manifest_sha(
        baseline_private_parent,
        expected_manifest_sha256=identity.baseline_private_manifest_sha256,
    )
    _verify_structured_root(structured_root, identity=identity)
    _verify_baseline_root(baseline_root, identity=identity)

    records: dict[tuple[str, int], dict[str, np.ndarray]] = {}
    cells: list[dict[str, Any]] = []
    for month in DEVELOPMENT_MONTHS:
        for horizon in HORIZONS_MINUTES:
            record = _load_pair(
                structured_root=structured_root,
                baseline_root=baseline_root,
                month=month,
                horizon=horizon,
            )
            records[(month, horizon)] = record
            cells.append(
                {
                    "month": month,
                    "horizon_minutes": horizon,
                    **_summarize_record(record),
                }
            )

    pooled_by_horizon = [
        {
            "horizon_minutes": horizon,
            **_summarize_record(
                _concatenate(
                    [records[(month, horizon)] for month in DEVELOPMENT_MONTHS]
                )
            ),
        }
        for horizon in HORIZONS_MINUTES
    ]
    pooled_by_month = [
        {
            "month": month,
            **_summarize_record(
                _concatenate(
                    [records[(month, horizon)] for horizon in HORIZONS_MINUTES]
                )
            ),
        }
        for month in DEVELOPMENT_MONTHS
    ]
    overall = _summarize_record(
        _concatenate(
            [records[(month, horizon)] for month in DEVELOPMENT_MONTHS for horizon in HORIZONS_MINUTES]
        )
    )
    return {
        "schema_version": "evcf-jpl-structured-s1-mixed-diagnostic/v1",
        "status": "COMPLETE",
        "decision_context": "MIXED_STRUCTURED_SIGNAL",
        "development_months": list(DEVELOPMENT_MONTHS),
        "final_holdout_months": list(FINAL_HOLDOUT_MONTHS),
        "holdout_accessed": False,
        "training_performed": False,
        "model_parameters_changed": False,
        "row_level_output": False,
        "future_truth_used_as_model_input": False,
        "diagnostic_only_future_truth_conditioning": True,
        "structured_protocol_sha256": identity.structured_protocol_sha256,
        "structured_code_commit": identity.structured_code_commit,
        "structured_private_manifest_sha256": identity.structured_private_manifest_sha256,
        "baseline_private_manifest_sha256": identity.baseline_private_manifest_sha256,
        "month_horizon_cells": cells,
        "pooled_by_horizon": pooled_by_horizon,
        "pooled_by_month": pooled_by_month,
        "pooled_overall": overall,
    }


__all__ = [
    "DEFAULT_IDENTITY",
    "DEVELOPMENT_MONTHS",
    "FINAL_HOLDOUT_MONTHS",
    "HORIZONS_MINUTES",
    "DiagnosticIdentity",
    "StructuredMixedDiagnosticError",
    "discover_run_by_manifest_sha",
    "run_structured_mixed_diagnostic",
]
