from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

import evcf.forecasting.acn_jpl_p1_postmortem as postmortem


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_fixture(root: Path) -> str:
    root.mkdir()
    entries: list[dict[str, str]] = []
    base_time = 1_600_000_000
    for month_index, month in enumerate(postmortem.DEVELOPMENT_MONTHS):
        for horizon_index, horizon in enumerate(postmortem.HORIZONS_MINUTES):
            issue = np.asarray(
                [base_time, base_time + 900, base_time + 1800], dtype=np.int64
            )
            day = np.asarray([base_time - 3600] * 3, dtype=np.int64)
            existing = np.asarray([10.0, 11.0, 12.0], dtype=np.float64)
            arrival = np.asarray([0.0, 2.0, 4.0], dtype=np.float64)
            y = existing + arrival
            s1_e = existing + np.asarray([1.0, -1.0, 0.5])
            s1_a = arrival + np.asarray([0.5, -0.5, 1.0])
            p1_e = existing + np.asarray([0.4, -0.4, 0.2])
            p1_a = arrival + np.asarray(
                [
                    1.0,
                    2.0,
                    500.0 if month_index == 3 and horizon_index == 1 else 3.0,
                ]
            )
            arrays = {
                "issue_times": issue,
                "day_start_utc_s": day,
                "y_true": y,
                "existing_truth": existing,
                "arrival_truth": arrival,
                "m2_predictions": y + 2.0,
                "m3_predictions": y + 1.0,
                "equal_predictions": y + 1.5,
                "s1_existing_predictions": s1_e,
                "s1_arrival_predictions": s1_a,
                "s1_predictions": s1_e + s1_a,
                "p1_e_predictions": p1_e,
                "p1_a_predictions": p1_a,
                "p1_eonly_predictions": p1_e + s1_a,
                "p1_aonly_predictions": s1_e + p1_a,
                "p1_ea_predictions": p1_e + p1_a,
            }
            name = f"{month}_h{horizon:03d}.npz"
            path = root / name
            np.savez_compressed(path, **arrays)
            entries.append({"name": name, "sha256": _sha256(path)})
    manifest = {
        "schema_version": "evcf-jpl-structured-mechanism-p1-private-cache/v1",
        "code_commit": postmortem.EXPECTED_P1_CODE_COMMIT,
        "source_expert_protocol_sha256": "test",
        "source_structured_protocol_sha256": "test",
        "source_baseline_private_manifest_sha256": "test",
        "source_structured_private_manifest_sha256": "test",
        "holdout_accessed": False,
        "hyperparameter_search": False,
        "entries": sorted(entries, key=lambda item: item["name"]),
    }
    manifest_path = root / "private_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return _sha256(manifest_path)


def test_readonly_postmortem_finds_extreme_and_preserves_stop(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "p1"
    manifest_sha = _write_fixture(root)
    monkeypatch.setattr(
        postmortem, "EXPECTED_P1_PRIVATE_MANIFEST_SHA256", manifest_sha
    )
    result = postmortem.run_p1_postmortem(p1_private_run=root)
    assert result["status"] == "COMPLETE"
    assert result["analysis_only"] is True
    assert result["model_fit_attempted"] is False
    assert result["raw_or_processed_data_accessed"] is False
    assert result["holdout_accessed"] is False
    assert result["scientific_decision_unchanged"] == "STOP_MECHANISM_ROUTE"
    assert result["overall_arrival_branch"]["threshold_counts"]["gt_100a"] == 1
    worst = result["worst_month_horizon_hours"][0]
    assert worst["month"] == "2019-10"
    assert worst["horizon_minutes"] == 30


def test_readonly_postmortem_rejects_identity_mismatch(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "p1"
    _write_fixture(root)
    target = root / "2019-01_h015.npz"
    with np.load(target, allow_pickle=False) as archive:
        arrays = {name: np.asarray(archive[name]) for name in archive.files}
    arrays["p1_ea_predictions"] = arrays["p1_ea_predictions"] + 1.0
    np.savez_compressed(target, **arrays)

    manifest_path = root / "private_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    for entry in manifest["entries"]:
        if entry["name"] == target.name:
            entry["sha256"] = _sha256(target)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
        newline="\n",
    )
    monkeypatch.setattr(
        postmortem,
        "EXPECTED_P1_PRIVATE_MANIFEST_SHA256",
        _sha256(manifest_path),
    )
    try:
        postmortem.run_p1_postmortem(p1_private_run=root)
    except postmortem.P1PostmortemError as exc:
        assert exc.reason_code == "P1_PRIVATE_CACHE_IDENTITY_INVALID"
    else:
        raise AssertionError("identity mismatch must fail")
