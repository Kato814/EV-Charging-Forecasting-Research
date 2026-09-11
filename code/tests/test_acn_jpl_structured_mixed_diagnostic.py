from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from evcf.forecasting.acn_jpl_structured_mixed_diagnostic import (
    DEVELOPMENT_MONTHS,
    HORIZONS_MINUTES,
    StructuredMixedDiagnosticError,
    run_structured_mixed_diagnostic,
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
    issue_times = np.asarray([1_600_000_000, 1_600_000_900], dtype=np.int64)
    day_start = np.asarray([1_599_984_000, 1_599_984_000], dtype=np.int64)

    for month_index, month in enumerate(DEVELOPMENT_MONTHS):
        for horizon_index, horizon in enumerate(HORIZONS_MINUTES):
            existing_truth = np.asarray(
                [10.0 + month_index, 5.0 + horizon_index], dtype=np.float64
            )
            arrival_truth = np.asarray(
                [0.0, 2.0 + horizon_index], dtype=np.float64
            )
            y_true = existing_truth + arrival_truth
            name = f"{month}_h{horizon:03d}.npz"
            path = root / name

            if structured:
                existing_prediction = existing_truth + np.asarray(
                    [1.0, -1.0], dtype=np.float64
                )
                arrival_prediction = arrival_truth + np.asarray(
                    [-0.5, 0.5], dtype=np.float64
                )
                np.savez_compressed(
                    path,
                    issue_times=issue_times,
                    day_start_utc_s=day_start,
                    y_true=y_true,
                    existing_truth=existing_truth,
                    arrival_truth=arrival_truth,
                    existing_predictions=existing_prediction,
                    arrival_predictions=arrival_prediction,
                    structured_predictions=existing_prediction + arrival_prediction,
                )
            else:
                np.savez_compressed(
                    path,
                    issue_times=issue_times,
                    day_start_utc_s=day_start,
                    y_true=y_true,
                    m2_predictions=y_true + np.asarray([2.0, -2.0]),
                    m3_predictions=y_true + np.asarray([1.5, -1.5]),
                    equal_predictions=y_true + np.asarray([1.75, -1.75]),
                )
            entries.append({"name": name, "sha256": _sha256(path)})

    if structured:
        manifest = {
            "schema_version": "evcf-jpl-structured-s1-private-cache/v1",
            "protocol_sha256": "structured-protocol-test",
            "code_commit": "test",
            "source_private_manifest_sha256": "baseline-test",
            "entries": entries,
        }
    else:
        manifest = {
            "schema_version": "evcf-jpl-development-expert-private-cache/v1",
            "protocol_sha256": "baseline-protocol-test",
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


def test_structured_mixed_diagnostic_is_read_only_and_aggregates(tmp_path: Path) -> None:
    baseline_root = tmp_path / "baseline"
    structured_root = tmp_path / "structured"
    baseline_sha = _write_fixture(baseline_root, structured=False)
    structured_sha = _write_fixture(structured_root, structured=True)

    result = run_structured_mixed_diagnostic(
        baseline_private_run=baseline_root,
        structured_private_run=structured_root,
        expected_baseline_manifest_sha256=baseline_sha,
        expected_structured_manifest_sha256=structured_sha,
    )

    assert result["status"] == "COMPLETE"
    assert result["analysis_only"] is True
    assert result["model_fit_attempted"] is False
    assert result["network_requests"] is False
    assert result["holdout_accessed"] is False
    assert len(result["pooled_by_horizon"]) == 5
    first = result["pooled_by_horizon"][0]
    assert first["n"] == 8
    assert first["truth_composition"]["arrival_zero_fraction"] == pytest.approx(0.5)
    assert first["conditional_on_arrival_truth"]["zero"]["n"] == 4
    assert first["conditional_on_arrival_truth"]["positive"]["n"] == 4


def test_structured_mixed_diagnostic_rejects_component_mismatch(tmp_path: Path) -> None:
    baseline_root = tmp_path / "baseline"
    structured_root = tmp_path / "structured"
    baseline_sha = _write_fixture(baseline_root, structured=False)
    _write_fixture(structured_root, structured=True)

    target = structured_root / "2019-01_h015.npz"
    with np.load(target, allow_pickle=False) as archive:
        arrays = {name: np.asarray(archive[name]) for name in archive.files}
    arrays["arrival_truth"] = arrays["arrival_truth"] + 1.0
    np.savez_compressed(target, **arrays)

    manifest_path = structured_root / "private_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    for entry in manifest["entries"]:
        if entry["name"] == target.name:
            entry["sha256"] = _sha256(target)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
        newline="\n",
    )
    structured_sha = _sha256(manifest_path)

    with pytest.raises(
        StructuredMixedDiagnosticError,
        match="COMMON_ROW_IDENTITY_INVALID",
    ):
        run_structured_mixed_diagnostic(
            baseline_private_run=baseline_root,
            structured_private_run=structured_root,
            expected_baseline_manifest_sha256=baseline_sha,
            expected_structured_manifest_sha256=structured_sha,
        )
