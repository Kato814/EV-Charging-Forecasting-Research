from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
import sys
from datetime import datetime
from pathlib import Path

import evcf.forecasting.acn_jpl_r1_mixed_diagnostic as diag
import numpy as np
import pytest


def _write_json(path: Path, value: object) -> str:
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    entries, records = [], []
    monkeypatch.setattr(diag, "EXPECTED_N", {m: 4 for m in diag.MONTHS})
    for month in diag.MONTHS:
        year, mo = map(int, month.split("-"))
        start = int(datetime(year, mo, 18, tzinfo=diag.ZONE).timestamp())
        issues = np.asarray([start, start + 900, start + 86400, start + 87300], dtype=np.int64)
        days = np.asarray([start, start, start + 86400, start + 86400], dtype=np.int64)
        for horizon in diag.HORIZONS:
            truth = np.full(4, 10.0)
            values = {
                "issue_times": issues, "day_start_utc_s": days, "y_true": truth,
                "m2_predictions": truth + 2, "m3_predictions": truth + 4,
                "equal_predictions": truth + 3, "s1_predictions": truth + 1,
                "r1_control_predictions": truth + np.asarray([1., 3., 1., 3.]),
                "r1_joint_predictions": truth + np.asarray([0., 1., 4., 1.]),
            }
            name = f"{month}_h{horizon:03d}.npz"
            stream = io.BytesIO()
            np.savez_compressed(stream, **values)
            raw = stream.getvalue()
            (root / name).write_bytes(raw)
            entries.append({"name": name, "sha256": hashlib.sha256(raw).hexdigest()})
            arrays = diag._load_arrays(raw, month)
            records.append({"month": month, "horizon_minutes": horizon, "arrays": arrays})
    manifest = {
        "schema_version": "evcf-jpl-r1-joint-state-private-cache/v1", "code_commit": diag.R1_COMMIT,
        "source_baseline_private_manifest_sha256": diag.BASELINE_SHA256,
        "source_structured_private_manifest_sha256": diag.S1_SHA256,
        "holdout_accessed": False, "hyperparameter_search": False, "entries": entries,
    }
    monkeypatch.setattr(
        diag, "R1_MANIFEST_SHA256", _write_json(root / "private_manifest.json", manifest)
    )
    reference = {
        "source_r1_status_sha256": "synthetic-test-only",
        "month_horizon": [{"month": r["month"], "horizon_minutes": r["horizon_minutes"],
                           **diag._pooled([r])} for r in records],
        "pooled_overall": diag._pooled(records),
        "pooled_by_horizon": [{"horizon_minutes": h,
                              **diag._pooled([r for r in records if r["horizon_minutes"] == h])}
                             for h in diag.HORIZONS],
        "pooled_by_month": [{"month": m, **diag._pooled([r for r in records if r["month"] == m])}
                            for m in diag.MONTHS],
    }
    ref = tmp_path / "reference.json"
    monkeypatch.setattr(diag, "REFERENCE_SHA256", _write_json(ref, reference))
    return root, ref, records


def test_complete_readonly_reconstruction_and_progress(fixture, monkeypatch):
    root, ref, _ = fixture
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    original_open = Path.open

    def guarded_open(path, mode="r", *args, **kwargs):
        if path.is_relative_to(root) and any(letter in mode for letter in "wax+"):
            pytest.fail("Diagnostic tried to mutate an input")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    progress = []
    result = diag.run_diagnostic(r1_private_run=root, reference_path=ref,
                                 progress=lambda *args: progress.append(args))
    assert result["status"] == "COMPLETE"
    assert result["scientific_decision_unchanged"] == "MIXED_JOINT_STATE_SIGNAL"
    assert result["model_fit_attempted"] is False and result["fit_count"] == 0
    assert result["raw_interim_processed_accessed"] is False
    assert result["holdout_accessed"] is False
    assert result["r1_private_cache_unchanged"] is True
    assert result["n_forecast_records"] == 80
    assert result["n_unique_issue_times"] == 16
    assert result["n_unique_local_days"] == 8
    assert len(result["month_horizon"]) == 20
    assert len(result["cross_month_hourly_consistency"]) == 120
    assert len(progress) == 61
    assert any(event[0] == "ANALYZE" and event[1] == 1 for event in progress)
    assert before == {p.name: p.read_bytes() for p in root.iterdir()}
    # Closed-form arithmetic assertions independent of the reporting helper.
    first = result["month_horizon"][0]
    assert first["overall"]["mae_a"]["R1_Joint"] == 1.5
    assert first["overall"]["mae_a"]["R1_Control"] == 2.0
    delta = first["overall"]["paired"]["R1_Control"]
    assert delta["mean_loss_delta_a"] == -0.5
    assert delta["sum_loss_delta_a"] == -2
    assert delta["gross_improvement_a"] == 5
    assert delta["gross_worsening_a"] == 3
    assert delta["row_wins"] == 3 and delta["row_losses"] == 1
    summary = first["daily_summary"]["paired"]["R1_Control"]
    assert summary["day_wins"] == 1 and summary["day_losses"] == 1
    assert summary["positive_net_daily_excess_a"] == 1
    assert summary["top1_day_share_of_positive_net_daily_excess"] == 1
    assert first["hourly"][7] == {"local_hour": 7, "n": 0, "mae_a": None, "paired": None}
    assert '"issue_times"' not in json.dumps(result)
    assert '"y_true"' not in json.dumps(result)
    json.dumps(result, allow_nan=False)


def test_corruption_rejected_before_npz_read(fixture, monkeypatch):
    root, ref, _ = fixture
    target = root / "2019-01_h015.npz"
    target.write_bytes(target.read_bytes() + b"corrupt")
    monkeypatch.setattr(diag.np, "load", lambda *args, **kwargs: pytest.fail("Unchecked NPZ load"))
    with pytest.raises(diag.R1DiagnosticError, match="HASH_MISMATCH"):
        diag.run_diagnostic(r1_private_run=root, reference_path=ref)


def test_extra_holdout_filename_never_opened(fixture, monkeypatch):
    root, ref, _ = fixture
    forbidden = root / "2019-03_h015.npz"
    forbidden.write_bytes(b"Do not open")
    original = Path.read_bytes

    def read(path):
        if path == forbidden:
            pytest.fail("Holdout file opened")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(diag.R1DiagnosticError, match="TOPOLOGY_INVALID"):
        diag.run_diagnostic(r1_private_run=root, reference_path=ref)


def test_accepted_metric_mismatch_is_not_a_new_result(fixture, monkeypatch):
    root, ref, _ = fixture
    value = json.loads(ref.read_text())
    value["month_horizon"][0]["R1_Joint"]["mae_a"] += 0.01
    monkeypatch.setattr(diag, "REFERENCE_SHA256", _write_json(ref, value))
    with pytest.raises(diag.R1DiagnosticError, match="RECONSTRUCTION_MISMATCH"):
        diag.run_diagnostic(r1_private_run=root, reference_path=ref)


@pytest.mark.parametrize("mutation", ["time_month", "duplicate_time", "wrong_day", "nan", "equal"])
def test_row_contract_errors(fixture, mutation):
    _, _, records = fixture
    arrays = {k: v.copy() for k, v in records[0]["arrays"].items() if k in diag.REQUIRED_ARRAYS}
    if mutation == "time_month":
        arrays["issue_times"] += 86400 * 60
    elif mutation == "duplicate_time":
        arrays["issue_times"][1] = arrays["issue_times"][0]
    elif mutation == "wrong_day":
        arrays["day_start_utc_s"][0] += 900
    elif mutation == "nan":
        arrays["r1_joint_predictions"][0] = np.nan
    else:
        arrays["equal_predictions"][0] += 1
    stream = io.BytesIO()
    np.savez_compressed(stream, **arrays)
    with pytest.raises(diag.R1DiagnosticError):
        diag._load_arrays(stream.getvalue(), "2019-01")


def test_symlink_cache_rejected(fixture, tmp_path):
    root, ref, _ = fixture
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks not supported in test environment")
    with pytest.raises(diag.R1DiagnosticError, match="LINKED_PATH"):
        diag.run_diagnostic(r1_private_run=linked, reference_path=ref)


def test_mutation_during_analysis_rejected(fixture):
    root, ref, _ = fixture

    def progress(stage, done, total, cell):
        if stage == "ANALYZE" and done == 20:
            path = root / "2019-01_h015.npz"
            path.write_bytes(path.read_bytes() + b"tampered")

    with pytest.raises(diag.R1DiagnosticError, match="HASH_MISMATCH"):
        diag.run_diagnostic(r1_private_run=root, reference_path=ref, progress=progress)


def test_module_has_no_model_or_network_imports():
    tree = ast.parse(Path(diag.__file__).read_text())
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
    assert not any(name.startswith(("sklearn", "torch", "requests", "evcf", "urllib", "socket"))
                   for name in imported)


def _launcher():
    path = (Path(__file__).resolve().parents[2]
            / "scripts/evcf_r1_mixed_diagnostic_launcher_template.py")
    spec = importlib.util.spec_from_file_location("test_r1_launcher", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_launcher_progress_is_immediate_and_separate(capsys):
    launcher = _launcher()
    progress = launcher.Progress()
    progress.emit("ANALYZE", 1, 20, "2019-01_h015")
    captured = capsys.readouterr()
    assert "DONE=1/20" in captured.err and captured.out == ""
    progress.finish()
    assert progress.stages[-1]["stage"] == "ANALYZE"


def test_launcher_unreleased_template_cannot_run(monkeypatch, capsys):
    launcher = _launcher()
    monkeypatch.setattr(sys, "argv", ["launcher", "--repo", ".", "--authorize-r1-diagnostic"])
    assert launcher.main() == 2
    assert "UNRELEASED_TEMPLATE" in capsys.readouterr().out


def test_public_schema_rejects_raw_records():
    launcher = _launcher()
    with pytest.raises(launcher.LauncherError, match="PUBLIC_FIELD"):
        launcher._check_public({"issue_times": [1]})
    with pytest.raises(launcher.LauncherError, match="PUBLIC_NONFINITE"):
        launcher._check_public({"metric": float("nan")})
