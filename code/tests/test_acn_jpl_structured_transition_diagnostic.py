from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from evcf.forecasting.acn_jpl_structured_mixed_diagnostic import (
    DEVELOPMENT_MONTHS,
    HORIZONS_MINUTES,
)
from evcf.forecasting.acn_jpl_structured_transition_diagnostic import (
    run_structured_transition_diagnostic,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_fixture(root: Path, *, structured: bool) -> str:
    root.mkdir()
    entries: list[dict[str, str]] = []
    issue_times = np.asarray(
        [
            1_600_000_000,
            1_600_000_900,
            1_600_001_800,
            1_600_002_700,
            1_600_003_600,
            1_600_004_500,
            1_600_005_400,
        ],
        dtype=np.int64,
    )
    day_start = np.full(7, 1_599_984_000, dtype=np.int64)
    existing_truth = np.asarray([0.0, 10.0, 9.0, 6.0, 4.0, 1.0, 0.0])
    arrival_truth = np.asarray([0.0, 0.0, 1.0, 4.0, 6.0, 9.0, 10.0])
    y_true = existing_truth + arrival_truth

    for month in DEVELOPMENT_MONTHS:
        for horizon in HORIZONS_MINUTES:
            name = f"{month}_h{horizon:03d}.npz"
            path = root / name
            if structured:
                existing_prediction = existing_truth + 0.5
                arrival_prediction = arrival_truth - 0.25
                structured_prediction = existing_prediction + arrival_prediction
                np.savez_compressed(
                    path,
                    issue_times=issue_times,
                    day_start_utc_s=day_start,
                    y_true=y_true,
                    existing_truth=existing_truth,
                    arrival_truth=arrival_truth,
                    existing_predictions=existing_prediction,
                    arrival_predictions=arrival_prediction,
                    structured_predictions=structured_prediction,
                )
            else:
                np.savez_compressed(
                    path,
                    issue_times=issue_times,
                    day_start_utc_s=day_start,
                    y_true=y_true,
                    m2_predictions=y_true + 1.0,
                    m3_predictions=y_true - 1.0,
                    equal_predictions=y_true + 0.75,
                )
            entries.append({"name": name, "sha256": _sha256(path)})

    if structured:
        manifest = {
            "schema_version": "evcf-jpl-structured-s1-private-cache/v1",
            "protocol_sha256": "structured-test",
            "code_commit": "test",
            "source_private_manifest_sha256": "baseline-test",
            "entries": entries,
        }
    else:
        manifest = {
            "schema_version": "evcf-jpl-development-expert-private-cache/v1",
            "protocol_sha256": "baseline-test",
            "source_model_selection_sha256": "selection-test",
            "holdout_accessed": False,
            "gate_trained": False,
            "files": entries,
        }
    manifest_path = root / "private_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return _sha256(manifest_path)


def test_transition_diagnostic_partitions_composition_and_stays_read_only(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline"
    structured = tmp_path / "structured"
    baseline_sha = _write_fixture(baseline, structured=False)
    structured_sha = _write_fixture(structured, structured=True)

    result = run_structured_transition_diagnostic(
        baseline_private_run=baseline,
        structured_private_run=structured,
        expected_baseline_manifest_sha256=baseline_sha,
        expected_structured_manifest_sha256=structured_sha,
    )

    assert result["status"] == "COMPLETE"
    assert result["analysis_only"] is True
    assert result["model_fit_attempted"] is False
    assert result["development_data_accessed"] is False
    assert result["holdout_accessed"] is False

    first = result["composition_by_horizon"][0]
    bins = {item["composition_bin"]: item for item in first["composition_bins"]}
    assert sum(item["n"] for item in bins.values()) == 28
    assert bins["total_zero"]["n"] == 4
    assert bins["existing_only"]["n"] == 4
    assert bins["arrival_share_0_25"]["n"] == 4
    assert bins["arrival_share_25_50"]["n"] == 4
    assert bins["arrival_share_50_75"]["n"] == 4
    assert bins["arrival_share_75_100"]["n"] == 4
    assert bins["arrival_only"]["n"] == 4
    assert bins["arrival_share_25_50"]["mean_arrival_share"] == pytest.approx(0.4)


def test_transition_diagnostic_reports_four_month_hour_stability(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    structured = tmp_path / "structured"
    baseline_sha = _write_fixture(baseline, structured=False)
    structured_sha = _write_fixture(structured, structured=True)

    result = run_structured_transition_diagnostic(
        baseline_private_run=baseline,
        structured_private_run=structured,
        expected_baseline_manifest_sha256=baseline_sha,
        expected_structured_manifest_sha256=structured_sha,
    )

    stability = result["local_hour_sign_stability"]
    assert stability
    assert all(item["months_present"] == 4 for item in stability)
    assert all(
        item["months_S1_better"]
        + item["months_equal"]
        + item["months_S1_worse"]
        == 4
        for item in stability
    )
