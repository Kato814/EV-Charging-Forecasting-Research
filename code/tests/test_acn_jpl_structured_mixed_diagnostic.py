from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from evcf.forecasting.acn_jpl_structured_mixed_diagnostic import (
    DEVELOPMENT_MONTHS,
    HORIZONS_MINUTES,
    DiagnosticIdentity,
    StructuredMixedDiagnosticError,
    run_structured_mixed_diagnostic,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, DiagnosticIdentity]:
    structured_parent = tmp_path / "structured"
    baseline_parent = tmp_path / "baseline"
    structured_root = structured_parent / "run_fixture"
    baseline_root = baseline_parent / "run_fixture"
    structured_root.mkdir(parents=True)
    baseline_root.mkdir(parents=True)

    issue_times = np.asarray([1, 2, 3, 4], dtype=np.int64)
    day_starts = np.asarray([0, 0, 0, 0], dtype=np.int64)
    existing_truth = np.asarray([10.0, 10.0, 10.0, 10.0], dtype=np.float64)
    arrival_truth = np.asarray([0.0, 2.0, 5.0, 10.0], dtype=np.float64)
    y_true = existing_truth + arrival_truth
    existing_predictions = np.asarray([9.0, 11.0, 8.0, 12.0], dtype=np.float64)
    arrival_predictions = np.asarray([1.0, 1.0, 7.0, 8.0], dtype=np.float64)
    structured_predictions = existing_predictions + arrival_predictions
    m3_predictions = y_true + 1.0
    equal_predictions = y_true + 0.5
    m2_predictions = y_true + 2.0

    baseline_entries: list[dict[str, str]] = []
    structured_entries: list[dict[str, str]] = []
    for month in DEVELOPMENT_MONTHS:
        for horizon in HORIZONS_MINUTES:
            name = f"{month}_h{horizon:03d}.npz"
            baseline_path = baseline_root / name
            structured_path = structured_root / name
            np.savez_compressed(
                baseline_path,
                issue_times=issue_times,
                day_start_utc_s=day_starts,
                y_true=y_true,
                m2_predictions=m2_predictions,
                m3_predictions=m3_predictions,
                equal_predictions=equal_predictions,
            )
            np.savez_compressed(
                structured_path,
                issue_times=issue_times,
                day_start_utc_s=day_starts,
                y_true=y_true,
                existing_truth=existing_truth,
                arrival_truth=arrival_truth,
                existing_predictions=existing_predictions,
                arrival_predictions=arrival_predictions,
                structured_predictions=structured_predictions,
            )
            baseline_entries.append({"name": name, "sha256": _sha256(baseline_path)})
            structured_entries.append(
                {"name": name, "sha256": _sha256(structured_path)}
            )

    baseline_manifest = {
        "schema_version": "evcf-jpl-development-expert-private-cache/v1",
        "protocol_sha256": "c" * 64,
        "code_commit": "d" * 40,
        "source_model_selection_sha256": "e" * 64,
        "holdout_accessed": False,
        "gate_trained": False,
        "files": sorted(baseline_entries, key=lambda item: item["name"]),
    }
    baseline_manifest_path = baseline_root / "private_manifest.json"
    baseline_manifest_path.write_text(
        json.dumps(baseline_manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )
    baseline_sha = _sha256(baseline_manifest_path)

    structured_protocol_sha = "a" * 64
    structured_code_commit = "b" * 40
    structured_manifest = {
        "schema_version": "evcf-jpl-structured-s1-private-cache/v1",
        "protocol_sha256": structured_protocol_sha,
        "code_commit": structured_code_commit,
        "source_private_manifest_sha256": baseline_sha,
        "entries": sorted(structured_entries, key=lambda item: item["name"]),
    }
    structured_manifest_path = structured_root / "private_manifest.json"
    structured_manifest_path.write_text(
        json.dumps(structured_manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )
    structured_sha = _sha256(structured_manifest_path)
    identity = DiagnosticIdentity(
        structured_protocol_sha256=structured_protocol_sha,
        structured_code_commit=structured_code_commit,
        structured_private_manifest_sha256=structured_sha,
        baseline_private_manifest_sha256=baseline_sha,
    )
    return structured_parent, baseline_parent, identity


def test_mixed_diagnostic_is_read_only_and_aggregates_residual_interaction(
    tmp_path: Path,
) -> None:
    structured_parent, baseline_parent, identity = _write_fixture(tmp_path)
    result = run_structured_mixed_diagnostic(
        authorized=True,
        structured_private_parent=structured_parent,
        baseline_private_parent=baseline_parent,
        identity=identity,
    )
    assert result["status"] == "COMPLETE"
    assert result["decision_context"] == "MIXED_STRUCTURED_SIGNAL"
    assert result["holdout_accessed"] is False
    assert result["training_performed"] is False
    assert result["model_parameters_changed"] is False
    assert result["row_level_output"] is False
    assert result["future_truth_used_as_model_input"] is False
    assert len(result["month_horizon_cells"]) == 20
    assert len(result["pooled_by_horizon"]) == 5
    first = result["pooled_by_horizon"][0]
    interaction = first["residual_interaction"]
    assert interaction["same_sign_fraction"] == pytest.approx(0.0)
    assert interaction["opposite_sign_fraction"] == pytest.approx(1.0)
    assert interaction["cancellation_fraction_of_branch_absolute_error"] == pytest.approx(
        1.0
    )
    assert first["S1_vs_equal"]["improvement_fraction"] == pytest.approx(1.0)
    assert first["truth_composition"]["arrival_fraction"] == pytest.approx(17.0 / 57.0)
    bins = {item["state_bin"] for item in first["realized_arrival_state_bins"]}
    assert "arrival_lt_10pct" in bins
    assert "arrival_ge_60pct" in bins


def test_mixed_diagnostic_rejects_tampered_structured_cache(tmp_path: Path) -> None:
    structured_parent, baseline_parent, identity = _write_fixture(tmp_path)
    target = structured_parent / "run_fixture" / "2019-01_h015.npz"
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(StructuredMixedDiagnosticError, match="STRUCTURED_CACHE_INVALID"):
        run_structured_mixed_diagnostic(
            authorized=True,
            structured_private_parent=structured_parent,
            baseline_private_parent=baseline_parent,
            identity=identity,
        )


def test_mixed_diagnostic_requires_explicit_authorization(tmp_path: Path) -> None:
    structured_parent, baseline_parent, identity = _write_fixture(tmp_path)
    with pytest.raises(
        StructuredMixedDiagnosticError,
        match="MIXED_DIAGNOSTIC_NOT_AUTHORIZED",
    ):
        run_structured_mixed_diagnostic(
            authorized=False,
            structured_private_parent=structured_parent,
            baseline_private_parent=baseline_parent,
            identity=identity,
        )
