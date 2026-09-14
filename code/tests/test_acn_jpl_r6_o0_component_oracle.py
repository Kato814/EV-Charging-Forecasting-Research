from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from evcf.forecasting import acn_jpl_r6_o0_component_oracle as r6


def _metric_block(existing_gain: float, arrival_gain: float) -> dict[str, object]:
    s1_mae = 10.0
    return {
        "S1": {"mae_a": s1_mae},
        "OracleExisting": {"mae_a": s1_mae - existing_gain},
        "OracleArrival": {"mae_a": s1_mae - arrival_gain},
        "gains": {
            "G_existing_a": existing_gain,
            "G_arrival_a": arrival_gain,
        },
    }


def _task_arrays() -> dict[str, np.ndarray]:
    existing_truth = np.asarray([10.0, 20.0, 30.0])
    arrival_truth = np.asarray([1.0, 2.0, 3.0])
    existing_predictions = np.asarray([12.0, 17.0, 32.0])
    arrival_predictions = np.asarray([0.0, 5.0, 2.0])
    return {
        "issue_times": np.asarray([900, 1800, 2700], dtype=np.int64),
        "day_start_utc_s": np.asarray([0, 0, 0], dtype=np.int64),
        "y_true": existing_truth + arrival_truth,
        "existing_truth": existing_truth,
        "arrival_truth": arrival_truth,
        "existing_predictions": existing_predictions,
        "arrival_predictions": arrival_predictions,
        "structured_predictions": existing_predictions + arrival_predictions,
    }


def _write_task(path: Path, arrays: dict[str, np.ndarray]) -> None:
    np.savez_compressed(path, **arrays)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_record_and_summary_use_frozen_oracle_formulas() -> None:
    arrays = _task_arrays()
    record = r6._record("2019-01", 15, arrays)
    assert np.allclose(
        record["oracle_existing"],
        arrays["existing_truth"] + arrays["arrival_predictions"],
    )
    assert np.allclose(
        record["oracle_arrival"],
        arrays["existing_predictions"] + arrays["arrival_truth"],
    )
    summary = r6._summary([record])
    s1_mae = np.mean(np.abs(arrays["structured_predictions"] - arrays["y_true"]))
    existing_oracle_mae = np.mean(
        np.abs(record["oracle_existing"] - arrays["y_true"])
    )
    arrival_oracle_mae = np.mean(
        np.abs(record["oracle_arrival"] - arrays["y_true"])
    )
    assert summary["S1"]["mae_a"] == pytest.approx(s1_mae)
    assert summary["gains"]["G_existing_a"] == pytest.approx(
        s1_mae - existing_oracle_mae
    )
    assert summary["gains"]["G_arrival_a"] == pytest.approx(
        s1_mae - arrival_oracle_mae
    )


def test_interaction_reports_cancellation_and_reinforcement() -> None:
    existing = np.asarray([5.0, 5.0, -4.0, 0.0])
    arrival = np.asarray([-3.0, 2.0, -1.0, 7.0])
    result = r6._interaction(existing, arrival)
    assert result["cancellation_count"] == 1
    assert result["reinforcement_count"] == 2
    assert result["zero_involved_count"] == 1
    expected = np.abs(existing) + np.abs(arrival) - np.abs(existing + arrival)
    assert result["mean_cancellation_amount_a"] == pytest.approx(float(np.mean(expected)))
    assert result["total_cancellation_share"] == pytest.approx(
        float(np.sum(expected) / np.sum(np.abs(existing) + np.abs(arrival)))
    )


def test_negative_oracle_gain_is_valid_under_error_cancellation() -> None:
    existing_truth = np.zeros(2)
    arrival_truth = np.zeros(2)
    existing_predictions = np.asarray([10.0, -10.0])
    arrival_predictions = np.asarray([-9.0, 9.0])
    arrays = {
        "y_true": np.zeros(2),
        "existing_truth": existing_truth,
        "arrival_truth": arrival_truth,
        "existing_predictions": existing_predictions,
        "arrival_predictions": arrival_predictions,
        "structured_predictions": existing_predictions + arrival_predictions,
    }
    record = r6._record("2019-01", 15, arrays)
    summary = r6._summary([record])
    assert summary["gains"]["G_existing_a"] < 0.0
    assert summary["gains"]["G_arrival_a"] < 0.0


def test_decision_arrival_dominant() -> None:
    pooled = _metric_block(2.0, 6.0)
    horizons = [_metric_block(2.0, 5.0) for _ in range(4)] + [_metric_block(4.0, 3.0)]
    months = [_metric_block(2.0, 5.0) for _ in range(3)] + [_metric_block(4.0, 3.0)]
    decision, support = r6.decide(pooled, horizons, months)
    assert decision == "ARRIVAL_COMPONENT_ORACLE_DOMINANT"
    assert support["arrival_gain_gt_existing_gain_horizons"] == 4
    assert support["arrival_gain_gt_existing_gain_months"] == 3


def test_decision_existing_dominant() -> None:
    pooled = _metric_block(6.0, 2.0)
    horizons = [_metric_block(5.0, 2.0) for _ in range(4)] + [_metric_block(3.0, 4.0)]
    months = [_metric_block(5.0, 2.0) for _ in range(3)] + [_metric_block(3.0, 4.0)]
    decision, _ = r6.decide(pooled, horizons, months)
    assert decision == "EXISTING_COMPONENT_ORACLE_DOMINANT"


def test_decision_cancellation_and_mixed_are_exhaustive() -> None:
    cancellation, _ = r6.decide(
        _metric_block(-1.0, -2.0),
        [_metric_block(-1.0, -2.0) for _ in range(5)],
        [_metric_block(-1.0, -2.0) for _ in range(4)],
    )
    assert cancellation == "CANCELLATION_DOMINATED_COMPONENT_ERRORS"
    mixed, _ = r6.decide(
        _metric_block(1.0, 2.0),
        [_metric_block(1.0, 2.0) for _ in range(3)]
        + [_metric_block(3.0, 1.0) for _ in range(2)],
        [_metric_block(1.0, 2.0) for _ in range(2)]
        + [_metric_block(3.0, 1.0) for _ in range(2)],
    )
    assert mixed == "MIXED_COMPONENT_ORACLE_SIGNAL"


def test_load_task_validates_count_and_reconstruction(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(r6.EXPECTED_ROWS_BY_MONTH, "2019-01", 3)
    path = tmp_path / "2019-01_h015.npz"
    arrays = _task_arrays()
    _write_task(path, arrays)
    loaded = r6._load_task(tmp_path, "2019-01", 15)
    assert np.array_equal(loaded["y_true"], arrays["y_true"])

    broken = dict(arrays)
    broken["structured_predictions"] = arrays["structured_predictions"] + 1.0
    _write_task(path, broken)
    with pytest.raises(r6.R6O0Error, match="S1_COMPONENT_RECONSTRUCTION_INVALID"):
        r6._load_task(tmp_path, "2019-01", 15)


def test_manifest_identity_is_exact_and_detects_file_drift(
    tmp_path: Path, monkeypatch
) -> None:
    entries = []
    for month in r6.DEVELOPMENT_MONTHS:
        for horizon in r6.HORIZONS_MINUTES:
            name = f"{month}_h{horizon:03d}.npz"
            path = tmp_path / name
            path.write_bytes(f"{month}-{horizon}".encode("ascii"))
            entries.append({"name": name, "sha256": _sha(path)})
    manifest = {
        "schema_version": r6.EXPECTED_S1_CACHE_SCHEMA,
        "protocol_sha256": r6.EXPECTED_S1_PROTOCOL_SHA256,
        "code_commit": "a" * 40,
        "source_private_manifest_sha256": "b" * 64,
        "entries": entries,
    }
    manifest_path = tmp_path / "private_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )
    monkeypatch.setattr(r6, "EXPECTED_S1_PRIVATE_MANIFEST_SHA256", _sha(manifest_path))
    verified = r6._verify_manifest(tmp_path)
    assert verified["code_commit"] == "a" * 40

    first = tmp_path / entries[0]["name"]
    first.write_bytes(b"drift")
    with pytest.raises(r6.R6O0Error, match="S1_PRIVATE_CACHE_IDENTITY_INVALID"):
        r6._verify_manifest(tmp_path)


def test_unauthorized_run_stops_before_filesystem_resolution() -> None:
    with pytest.raises(r6.R6O0Error, match="R6_O0_NOT_AUTHORIZED"):
        r6.run_r6_o0(
            authorized=False,
            s1_private_root="definitely-missing",
            code_commit="x",
            repo_root="definitely-missing",
        )
