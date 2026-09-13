from __future__ import annotations

import copy

import evcf.forecasting.acn_jpl_r4_d2_query_geometry_regime as d2
import numpy as np
import pytest


def _record(*, d_level: float = 10.0, d_m3: float = 8.0) -> dict[str, float | int]:
    return {
        "C_Level": 1.0,
        "C_M3": 3.0,
        "QE_Level": 4.0,
        "QE_M3": 2.0,
        "Q3_Level": 5.0,
        "Q3_M3": 3.0,
        "D_Level": d_level,
        "D_M3": d_m3,
        "O_Level_M3": 1,
    }


def test_geometry_score_is_frozen_target_free_balance_plus_diagnostic_outcome():
    first = d2.geometry_scores(_record(d_level=10.0, d_m3=8.0))
    second = d2.geometry_scores(_record(d_level=100.0, d_m3=1.0))

    expected_current = (3.0 - 1.0) / (3.0 + 1.0 + d2.SCORE_EPS)
    expected_session = (4.0 - 2.0) / (4.0 + 2.0 + d2.SCORE_EPS)
    expected_full = (5.0 - 3.0) / (5.0 + 3.0 + d2.SCORE_EPS)
    assert first["S_current"] == pytest.approx(expected_current)
    assert first["S_session"] == pytest.approx(expected_session)
    assert first["S_full"] == pytest.approx(expected_full)
    assert first["B"] == pytest.approx(expected_session - expected_current)
    assert second["B"] == pytest.approx(first["B"])
    assert first["A"] == pytest.approx(2.0)
    assert second["A"] == pytest.approx(99.0)


def test_pooled_quartiles_use_higher_and_fixed_boundary_assignment():
    records = [{"B": float(value)} for value in range(8)]
    cuts = d2.pooled_quartile_cutpoints(records)

    assert cuts == (2.0, 4.0, 6.0)
    assert d2.assign_quartile(2.0, cuts) == "Q1"
    assert d2.assign_quartile(3.0, cuts) == "Q2"
    assert d2.assign_quartile(4.0, cuts) == "Q2"
    assert d2.assign_quartile(5.0, cuts) == "Q3"
    assert d2.assign_quartile(6.0, cuts) == "Q3"
    assert d2.assign_quartile(7.0, cuts) == "Q4"


def test_spearman_rank_association_handles_direction_and_ties():
    assert d2.spearman_rho([1.0, 2.0, 3.0], [10.0, 20.0, 30.0]) == pytest.approx(1.0)
    assert d2.spearman_rho([1.0, 2.0, 3.0], [30.0, 20.0, 10.0]) == pytest.approx(-1.0)
    tied = d2.spearman_rho([1.0, 1.0, 2.0, 3.0], [0.0, 0.0, 1.0, 2.0])
    assert tied == pytest.approx(1.0)
    assert d2.spearman_rho([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_regime_aggregation_reuses_supplied_cutpoints_and_reports_extremes():
    records = []
    for index, (balance, advantage) in enumerate(
        [(-3.0, -2.0), (-2.0, -1.0), (-1.0, 0.0), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]
    ):
        records.append(
            {
                "B": balance,
                "A": advantage,
                "S_current": 0.2,
                "S_session": 0.3,
                "S_full": 0.4,
                "O_Level_M3": index % 4,
            }
        )
    metrics = d2.aggregate_regime(records, (-1.0, 0.0, 1.0))

    assert metrics is not None
    assert metrics["records"] == 6
    assert metrics["bins"]["Q1"]["records"] == 3
    assert metrics["bins"]["Q2"]["records"] == 0
    assert metrics["bins"]["Q3"]["records"] == 1
    assert metrics["bins"]["Q4"]["records"] == 2
    assert metrics["Q4_minus_Q1_mean_A"] > 0.0
    assert metrics["Q4_minus_Q1_m3_advantage_fraction"] > 0.0


def _public_fixture() -> tuple[dict[str, object], dict[str, object]]:
    aggregate = {
        "pooled_overall": {"records": 4, "value": 1.0},
        "pooled_by_horizon": [{"horizon_minutes": 15, "records": 4, "value": 1.0}],
        "pooled_by_month": [{"month": "2019-01", "records": 4, "value": 1.0}],
        "month_horizon_cells": [
            {"month": "2019-01", "horizon_minutes": 15, "records": 4, "value": 1.0}
        ],
    }
    public: dict[str, object] = {
        "status": "COMPLETE",
        "d1_protocol_merge_commit": "d1-protocol",
        "source_r4_status_sha256": "r4-status",
        "source_r4_code_commit": "r4-code",
        "source_r4_decision": d2.SOURCE_R4_DECISION,
        "scientific_decision_unchanged": True,
        "r4_replay_verified": True,
        "fit_count": 0,
        "holdout_accessed": False,
        "preprocessor_fit_count": 11,
        **copy.deepcopy(aggregate),
    }
    reference: dict[str, object] = {
        "d1_protocol_merge_commit": "d1-protocol",
        "source_r4_status_sha256": "r4-status",
        "source_r4_code_commit": "r4-code",
        "preprocessor_fit_count": 11,
        "pooled_records": 4,
        "aggregate_sha256": d2.aggregate_sha256(public),
    }
    return public, reference


def test_d1_replay_digest_accepts_exact_and_rejects_any_aggregate_drift():
    public, reference = _public_fixture()
    d2.assert_d1_replay_matches(public, reference)

    drifted = copy.deepcopy(public)
    drifted["pooled_overall"]["value"] = 1.000000000001
    with pytest.raises(d2.R4D2Error, match="D1_REPLAY_MISMATCH"):
        d2.assert_d1_replay_matches(drifted, reference)


def test_passive_record_capture_restores_d1_aggregate(monkeypatch, tmp_path):
    original = d2.d1.aggregate_geometry
    fake_records = []
    for value in range(4):
        record = {key: float(value + 1) for key in d2.d1._CONTINUOUS_KEYS}
        record.update({"O_Level_M2": 0, "O_Level_M3": 1, "O_M2_M3": 2})
        fake_records.append(record)

    def fake_run_diagnostic(**_kwargs):
        pooled = d2.d1.aggregate_geometry(fake_records)
        assert pooled is not None
        return {"status": "COMPLETE", "pooled_overall": pooled}

    monkeypatch.setattr(d2.d1, "run_diagnostic", fake_run_diagnostic)
    public, captured = d2._run_d1_and_capture_records(
        interim=tmp_path,
        processed=tmp_path,
        code_commit="0" * 40,
        repo=tmp_path,
        expected_records=4,
    )

    assert public["status"] == "COMPLETE"
    assert len(captured) == 4
    assert d2.d1.aggregate_geometry is original


def test_r4_d2_contract_keeps_holdout_sealed_and_model_fit_zero():
    assert d2.SOURCE_R4_DECISION == "MIXED_STATE_ALIASING_SIGNAL"
    assert set(d2.d1.r4.DEVELOPMENT_MONTHS).isdisjoint(d2.d1.r4.FINAL_HOLDOUT_MONTHS)
    assert d2.SCORE_EPS == 1e-12
    assert d2.QUANTILE_PROBABILITIES == (0.25, 0.50, 0.75)
