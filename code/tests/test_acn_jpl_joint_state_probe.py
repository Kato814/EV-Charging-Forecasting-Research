from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import evcf.forecasting.acn_jpl_joint_state_probe as r1


def _rows() -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for index in range(4):
        row = {
            field: float((position + 1) * (index + 1) + (index % 2) * position)
            for position, field in enumerate(r1.M3_SESSION_FIELDS)
        }
        rows.append(row)
    return rows


def test_pair_features_are_permutation_invariant_and_masks_match() -> None:
    rows = _rows()
    control, joint = r1.pair_features([rows])
    p_control, p_joint = r1.pair_features([[rows[2], rows[0], rows[3], rows[1]]])

    assert control.shape == (1, 55)
    assert joint.shape == (1, 55)
    assert np.array_equal(np.isnan(control), np.isnan(joint))
    assert np.array_equal(np.isnan(control), np.isnan(p_control))
    assert np.allclose(control, p_control, equal_nan=True)
    assert np.allclose(joint, p_joint, equal_nan=True)
    assert np.all(control[np.isfinite(control)] == 0.0)
    assert np.nanmax(np.abs(joint)) <= 1.0


def test_independent_field_permutation_preserves_marginals_but_changes_joint() -> None:
    rows = _rows()
    permuted = [dict(row) for row in rows]
    target = r1.M3_SESSION_FIELDS[1]
    values = [row[target] for row in permuted]
    rotated = values[1:] + values[:1]
    for row, value in zip(permuted, rotated, strict=True):
        row[target] = value

    for field in r1.M3_SESSION_FIELDS:
        assert sorted(row[field] for row in rows) == sorted(row[field] for row in permuted)

    _, original_joint = r1.pair_features([rows])
    _, permuted_joint = r1.pair_features([permuted])
    assert not np.allclose(original_joint, permuted_joint, equal_nan=True)


def _metric(mae: float) -> dict[str, float | int]:
    return {
        "n": 10,
        "mae_a": mae,
        "rmse_a": mae,
        "wape_ratio": mae / 100.0,
        "negative_prediction_count": 0,
    }


def _decision_fixture(*, joint: float, control: float, equal: float) -> dict[str, object]:
    return {
        "M2": _metric(equal + 2),
        "M3": _metric(equal + 1),
        "Equal": _metric(equal),
        "S1": _metric(equal - 0.1),
        "R1_Control": _metric(control),
        "R1_Joint": _metric(joint),
    }


def test_decision_pass_and_stop_are_preregistered() -> None:
    pooled = _decision_fixture(joint=9.0, control=10.0, equal=10.0)
    by_horizon = [
        {"horizon_minutes": horizon, **_decision_fixture(joint=9.0, control=10.0, equal=10.0)}
        for horizon in r1.HORIZONS_MINUTES
    ]
    by_month = [
        {"month": month, **_decision_fixture(joint=9.0, control=10.0, equal=10.0)}
        for month in r1.DEVELOPMENT_MONTHS
    ]
    decision, support = r1.decide(pooled, by_horizon, by_month)
    assert decision == "PASS_JOINT_STATE_SIGNAL"
    assert support["joint_horizon_wins_vs_control"] == 5
    assert support["joint_month_wins_vs_equal"] == 4

    stopped, _ = r1.decide(
        _decision_fixture(joint=10.1, control=10.0, equal=10.0),
        by_horizon,
        by_month,
    )
    assert stopped == "STOP_JOINT_STATE_ROUTE"


def test_holdout_month_is_fail_closed_before_data_load(tmp_path, monkeypatch) -> None:
    interim = tmp_path / "interim"
    processed = tmp_path / "processed"
    baseline = tmp_path / "baseline"
    structured = tmp_path / "structured"
    repo = tmp_path / "repo"
    for path in (interim, processed, baseline, structured, repo):
        path.mkdir()

    monkeypatch.setattr(r1, "_verify_git", lambda *args, **kwargs: None)
    monkeypatch.setattr(r1, "_verify_private_manifest", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        r1,
        "load_development_expert_protocol",
        lambda *args, **kwargs: SimpleNamespace(
            protocol_sha256=r1.EXPECTED_SOURCE_EXPERT_PROTOCOL_SHA256,
            months=(SimpleNamespace(month="2019-03"),),
            test_start_local_day=18,
        ),
    )
    monkeypatch.setattr(r1, "load_selected_hgb_parameters", lambda *args, **kwargs: {})

    with pytest.raises(r1.JointStateProbeError, match="HOLDOUT_ACCESS_ATTEMPT"):
        r1.run_joint_state_probe(
            interim_root=interim,
            processed_root=processed,
            baseline_private_run=baseline,
            structured_private_run=structured,
            private_output_dir=tmp_path / "out",
            code_commit="0" * 40,
            repo_root=repo,
        )
