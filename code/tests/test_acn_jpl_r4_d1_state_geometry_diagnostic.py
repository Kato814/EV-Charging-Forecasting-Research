from __future__ import annotations

import copy

import evcf.forecasting.acn_jpl_r4_d1_state_geometry_diagnostic as d1
from evcf.forecasting.acn_jpl_gate1_features import canonical_feature_schema
import numpy as np
import pytest


def test_m3_extension_indices_are_schema_derived_and_exclude_shared_m2():
    m2_names, _ = canonical_feature_schema("M2")
    m3_names, m3_nullable = canonical_feature_schema("M3")

    indices = d1.m3_extension_encoded_indices(
        m2_feature_names=m2_names,
        m3_feature_names=m3_names,
        m3_nullable_mask=m3_nullable,
    )

    assert len(indices) == d1.EXPECTED_EXTENSION_ENCODED_WIDTH == 187
    assert np.array_equal(indices[:110], np.arange(201, 311))
    assert indices[110] == 314
    assert indices[-1] == 390
    assert not set(range(0, 201)).intersection(indices.tolist())
    assert not {311, 312, 313}.intersection(indices.tolist())


def test_arm_geometry_uses_only_frozen_selected_rows():
    candidate_level = np.asarray([0.0, 1.0, 2.0, 3.0])
    candidate_m2 = np.column_stack((candidate_level, candidate_level * 2.0))
    candidate_m3 = np.column_stack(
        (candidate_level, candidate_level * 2.0, candidate_level * 3.0)
    )
    selected = np.asarray([0, 1, 2], dtype=np.int64)

    current_gap, q2, qe, q3 = d1.arm_geometry(
        selected_rows=selected,
        candidate_level=candidate_level,
        test_level=1.0,
        candidate_m2=candidate_m2,
        test_m2=np.asarray([1.0, 2.0]),
        candidate_m3=candidate_m3,
        test_m3=np.asarray([1.0, 2.0, 3.0]),
        extension_indices=np.asarray([2], dtype=np.int64),
    )

    assert current_gap == pytest.approx(2.0 / 3.0)
    assert q2 >= 0.0
    assert qe == pytest.approx(2.0)
    assert q3 >= 0.0


def test_neighbor_overlap_is_exact_set_intersection():
    assert d1.overlap_count(
        np.asarray([0, 1, 2]),
        np.asarray([2, 3, 4]),
    ) == 1
    assert d1.overlap_count(
        np.asarray([0, 1, 2]),
        np.asarray([0, 1, 2]),
    ) == 3


def test_geometry_aggregate_reports_complete_overlap_distribution():
    record = {key: 1.0 for key in d1._CONTINUOUS_KEYS}
    record.update(
        {
            "O_Level_M2": 0,
            "O_Level_M3": 1,
            "O_M2_M3": 3,
        }
    )
    metrics = d1.aggregate_geometry([record, record])

    assert metrics is not None
    assert metrics["records"] == 2
    assert metrics["geometry"]["current_level_gap"]["M3"]["mean"] == pytest.approx(1.0)
    assert metrics["neighbor_overlap"]["Level_M2"]["fraction_0"] == pytest.approx(1.0)
    assert metrics["neighbor_overlap"]["Level_M3"]["fraction_1"] == pytest.approx(1.0)
    assert metrics["neighbor_overlap"]["M2_M3"]["fraction_3"] == pytest.approx(1.0)
    assert metrics["future_divergence"]["Delta_M3_Level"]["median"] == pytest.approx(
        1.0
    )


def _reference_fixture():
    metrics = {
        "supported_records": 10,
        "G_level_a": 1.0,
        "G_M2_a": 1.1,
        "G_M3_a": 1.05,
        "Y_scale_a": 4.0,
        "skill_M2_vs_Level": -0.1,
        "skill_M3_vs_Level": -0.05,
        "skill_M3_vs_M2": 1.0 - 1.05 / 1.1,
        "normalized_M3_divergence": 1.05 / 4.0,
    }
    support = {
        "oos_origin_horizon_records": 12,
        "supported_origin_horizon_records": 10,
        "pooled_supported_fraction": 10.0 / 12.0,
        "minimum_pooled_supported_fraction": 0.70,
        "minimum_cell_supported_fraction": 0.50,
        "minimum_cell_supported_records": 250,
        "support_pass": True,
    }
    reference = {
        "decision": d1.SOURCE_R4_DECISION,
        "support": support,
        "pooled_overall": metrics,
        "pooled_by_horizon": [{"horizon_minutes": 15, **metrics}],
        "pooled_by_month": [{"month": "2019-01", **metrics}],
        "month_horizon_cells": [
            {
                "month": "2019-01",
                "horizon_minutes": 15,
                "oos_records": 12,
                "supported_records": 10,
                "supported_fraction": 10.0 / 12.0,
                "unsupported_candidate_floor": 0,
                "unsupported_m3_distance": 2,
                "metrics": metrics,
            }
        ],
    }
    public = {
        "status": "COMPLETE",
        "decision": d1.SOURCE_R4_DECISION,
        "fit_count": 0,
        "support": copy.deepcopy(support),
        "pooled_overall": copy.deepcopy(metrics),
        "pooled_by_horizon": [{"horizon_minutes": 15, **copy.deepcopy(metrics)}],
        "pooled_by_month": [{"month": "2019-01", **copy.deepcopy(metrics)}],
        "month_horizon_cells": copy.deepcopy(reference["month_horizon_cells"]),
    }
    return public, reference


def test_replay_gate_accepts_exact_accepted_aggregate():
    public, reference = _reference_fixture()
    d1.assert_r4_replay_matches(public, reference)


def test_replay_gate_rejects_metric_drift():
    public, reference = _reference_fixture()
    public["pooled_overall"]["G_M3_a"] += 1e-6

    with pytest.raises(d1.R4D1Error, match="R4_REPLAY_MISMATCH"):
        d1.assert_r4_replay_matches(public, reference)


def test_r4_d1_remains_zero_fit_and_holdout_sealed_by_contract():
    assert d1.SOURCE_R4_DECISION == "MIXED_STATE_ALIASING_SIGNAL"
    assert set(d1.r4.DEVELOPMENT_MONTHS).isdisjoint(d1.r4.FINAL_HOLDOUT_MONTHS)
    assert d1.REPLAY_ATOL == 1e-12
