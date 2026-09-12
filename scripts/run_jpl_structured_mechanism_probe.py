"""CLI for the frozen JPL P1 structured mechanism probe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

import evcf.forecasting.acn_jpl_structured_mechanism_probe as _probe

MechanismProbeError = _probe.MechanismProbeError


def _failure(reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "evcf-jpl-structured-mechanism-p1-summary/v1",
        "status": "INCOMPLETE",
        "reason_code": reason_code,
        "holdout_accessed": False,
        "hyperparameter_search": False,
        "prediction_clipping": False,
        "prediction_calibration": False,
        "neural_survival_trained": False,
        "neural_tpp_trained": False,
        "gate_trained": False,
    }


def _install_diagnostic_counters() -> None:
    """Add reporting denominators without changing any prediction or metric value."""

    original_continuation = _probe._continuation_metrics
    original_arrival = _probe._arrival_metrics

    def continuation_with_count(
        truth: np.ndarray,
        probability: np.ndarray,
    ) -> dict[str, Any]:
        result = original_continuation(truth, probability)
        result["positive_n"] = int(np.sum(truth > 0))
        return result

    def arrival_with_count(
        count_truth: np.ndarray,
        count_prediction: np.ndarray,
        mark_truth: np.ndarray,
        mark_prediction: np.ndarray,
    ) -> dict[str, Any]:
        result = original_arrival(
            count_truth,
            count_prediction,
            mark_truth,
            mark_prediction,
        )
        result["positive_mark_n"] = int(np.sum(mark_truth > 0))
        return result

    _probe._continuation_metrics = continuation_with_count
    _probe._arrival_metrics = arrival_with_count


def _weighted_mean(
    rows: list[tuple[float | None, int]],
) -> float | None:
    usable = [(float(value), int(weight)) for value, weight in rows if value is not None and weight > 0]
    total_weight = sum(weight for _, weight in usable)
    if total_weight == 0:
        return None
    return float(sum(value * weight for value, weight in usable) / total_weight)


def _pool_probe_cells(cells: list[dict[str, Any]]) -> dict[str, Any]:
    continuation_n = sum(int(cell["continuation"]["n"]) for cell in cells)
    continuation_positive_n = sum(
        int(cell["continuation"].get("positive_n", 0)) for cell in cells
    )
    calibration: list[dict[str, Any]] = []
    for decile in range(10):
        entries = [
            row
            for cell in cells
            for row in cell["continuation"]["calibration"]
            if int(row["decile"]) == decile
        ]
        n = sum(int(row["n"]) for row in entries)
        if n == 0:
            continue
        calibration.append(
            {
                "decile": decile,
                "n": n,
                "mean_probability": float(
                    sum(float(row["mean_probability"]) * int(row["n"]) for row in entries)
                    / n
                ),
                "observed_rate": float(
                    sum(float(row["observed_rate"]) * int(row["n"]) for row in entries)
                    / n
                ),
            }
        )

    test_rows = sum(int(cell["test_rows"]) for cell in cells)
    arrival_positive_n = sum(
        int(cell["arrival_process"].get("positive_mark_n", 0)) for cell in cells
    )
    return {
        "continuation": {
            "n": continuation_n,
            "positive_n": continuation_positive_n,
            "brier": _weighted_mean(
                [
                    (cell["continuation"]["brier"], int(cell["continuation"]["n"]))
                    for cell in cells
                ]
            ),
            "log_loss": _weighted_mean(
                [
                    (cell["continuation"]["log_loss"], int(cell["continuation"]["n"]))
                    for cell in cells
                ]
            ),
            "positive_mark_mae_a": _weighted_mean(
                [
                    (
                        cell["continuation"]["positive_mark_mae_a"],
                        int(cell["continuation"].get("positive_n", 0)),
                    )
                    for cell in cells
                ]
            ),
            "calibration": calibration,
        },
        "arrival_process": {
            "n": test_rows,
            "positive_mark_n": arrival_positive_n,
            "count_mae": _weighted_mean(
                [
                    (cell["arrival_process"]["count_mae"], int(cell["test_rows"]))
                    for cell in cells
                ]
            ),
            "poisson_deviance": _weighted_mean(
                [
                    (
                        cell["arrival_process"]["poisson_deviance"],
                        int(cell["test_rows"]),
                    )
                    for cell in cells
                ]
            ),
            "positive_mark_mae_a": _weighted_mean(
                [
                    (
                        cell["arrival_process"]["positive_mark_mae_a"],
                        int(cell["arrival_process"].get("positive_mark_n", 0)),
                    )
                    for cell in cells
                ]
            ),
        },
    }


def _attach_pooled_probe_diagnostics(
    public: dict[str, Any],
    months: tuple[Any, ...],
) -> None:
    cells = [
        {"month": month["month"], **horizon}
        for month in months
        for horizon in month["horizons"]
    ]
    public["probe_diagnostics_pooled_overall"] = _pool_probe_cells(cells)
    public["probe_diagnostics_by_horizon"] = [
        {
            "horizon_minutes": horizon,
            **_pool_probe_cells(
                [cell for cell in cells if int(cell["horizon_minutes"]) == horizon]
            ),
        }
        for horizon in _probe.HORIZONS_MINUTES
    ]
    public["probe_diagnostics_by_month"] = [
        {
            "month": month,
            **_pool_probe_cells([cell for cell in cells if cell["month"] == month]),
        }
        for month in _probe.DEVELOPMENT_MONTHS
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interim-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--baseline-private-run", type=Path, required=True)
    parser.add_argument("--structured-private-run", type=Path, required=True)
    parser.add_argument("--private-output-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--authorize-mechanism-probe", action="store_true")
    args = parser.parse_args()

    if not args.authorize_mechanism_probe:
        print(json.dumps(_failure("MECHANISM_PROBE_NOT_AUTHORIZED"), sort_keys=True))
        return 2
    try:
        _install_diagnostic_counters()
        result = _probe.run_structured_mechanism_probe(
            authorized=True,
            interim_root=args.interim_root,
            processed_root=args.processed_root,
            baseline_private_run=args.baseline_private_run,
            structured_private_run=args.structured_private_run,
            private_output_root=args.private_output_root,
            code_commit=args.code_commit,
            repo_root=args.repo_root,
        )
    except MechanismProbeError as exc:
        print(json.dumps(_failure(exc.reason_code), sort_keys=True))
        return 2
    except (OSError, ValueError):
        print(json.dumps(_failure("UNEXPECTED_ERROR"), sort_keys=True))
        return 2
    public = result.to_public_dict()
    _attach_pooled_probe_diagnostics(public, result.month_summaries)
    print(json.dumps(public, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
