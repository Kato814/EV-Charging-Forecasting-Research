from __future__ import annotations

import inspect
from types import MappingProxyType

import evcf.forecasting.acn_jpl_r4_information_sufficiency_gate as r4
import numpy as np
import pytest


def _metrics(
    *,
    m2_skill: float = 0.01,
    m3_skill: float = 0.02,
    m3_m2_skill: float = 0.01,
    norm: float = 0.12,
):
    return {
        "supported_records": 1000,
        "G_level_a": 10.0,
        "G_M2_a": 10.0 * (1.0 - m2_skill),
        "G_M3_a": 10.0 * (1.0 - m3_skill),
        "Y_scale_a": 10.0 * (1.0 - m3_skill) / norm,
        "skill_M2_vs_Level": m2_skill,
        "skill_M3_vs_Level": m3_skill,
        "skill_M3_vs_M2": m3_m2_skill,
        "normalized_M3_divergence": norm,
        "distance_ratio_mean": 0.5,
        "distance_ratio_median": 0.5,
        "distance_ratio_p95": 0.9,
    }


def _horizons(**kwargs):
    return [
        {"horizon_minutes": horizon, **_metrics(**kwargs)}
        for horizon in r4.HORIZONS_MINUTES
    ]


def _months(**kwargs):
    return [
        {"month": month, **_metrics(**kwargs)}
        for month in r4.DEVELOPMENT_MONTHS
    ]


def _support(passed: bool = True):
    return {
        "support_pass": passed,
        "pooled_supported_fraction": 0.9 if passed else 0.4,
    }


def test_rms_distance_and_tie_break_are_deterministic():
    candidates = np.asarray([[0.0, 0.0], [1.0, 1.0], [-1.0, -1.0]])
    distances = r4.rms_distances(np.asarray([0.0, 0.0]), candidates)
    assert distances.tolist() == pytest.approx([0.0, 1.0, 1.0])
    issues = np.asarray([30, 20, 10], dtype=np.int64)
    selected = r4.select_top_k(distances, issues, k=3)
    assert selected.tolist() == [0, 2, 1]


def test_historical_support_threshold_uses_third_neighbor_q95_higher():
    values = np.arange(10, dtype=np.float64).reshape(-1, 1)
    threshold, third = r4.historical_third_neighbor_threshold(values)
    expected = float(np.quantile(third, 0.95, method="higher"))
    assert threshold == expected
    assert len(third) == 10
    assert np.isfinite(third).all()


def test_selection_is_target_independent_and_uses_fixed_k():
    parameters = tuple(inspect.signature(r4.select_analogs).parameters)
    assert parameters == (
        "candidate_issue_times",
        "candidate_level",
        "test_level",
        "candidate_m2",
        "test_m2",
        "candidate_m3",
        "test_m3",
    )
    assert r4.K_ANALOGS == 3
    assert r4.MIN_CANDIDATES == 10
    assert r4.SUPPORT_QUANTILE == 0.95


def test_selection_rejects_too_small_candidate_pool_without_using_targets():
    issues = np.arange(9, dtype=np.int64)
    values = np.arange(9, dtype=np.float64)
    matrix = values.reshape(-1, 1)
    selection = r4.select_analogs(
        candidate_issue_times=issues,
        candidate_level=values,
        test_level=4.5,
        candidate_m2=matrix,
        test_m2=np.asarray([4.5]),
        candidate_m3=matrix,
        test_m3=np.asarray([4.5]),
    )
    assert not selection.supported
    assert selection.candidate_count == 9
    assert len(selection.level_rows) == 0


def test_selection_support_is_calibrated_from_m3_geometry():
    issues = np.arange(10, dtype=np.int64)
    values = np.arange(10, dtype=np.float64)
    m2 = np.column_stack((values, values / 10.0))
    m3 = np.column_stack((values, values / 10.0, values / 100.0))
    selection = r4.select_analogs(
        candidate_issue_times=issues,
        candidate_level=values,
        test_level=4.5,
        candidate_m2=m2,
        test_m2=np.asarray([4.5, 0.45]),
        candidate_m3=m3,
        test_m3=np.asarray([4.5, 0.45, 0.045]),
    )
    assert selection.supported
    assert len(selection.level_rows) == 3
    assert len(selection.m2_rows) == 3
    assert len(selection.m3_rows) == 3
    assert selection.distance_ratio is not None
    assert selection.distance_ratio <= 1.0


def test_analog_divergence_is_mean_absolute_future_difference():
    value = r4.analog_divergence(10.0, np.asarray([8.0, 10.0, 14.0]))
    assert value == pytest.approx(2.0)


def test_aggregate_skills_follow_frozen_definitions():
    records = [
        {
            "d_level_a": 10.0,
            "d_m2_a": 9.0,
            "d_m3_a": 8.0,
            "y_abs_a": 40.0,
            "distance_ratio": 0.5,
        },
        {
            "d_level_a": 20.0,
            "d_m2_a": 18.0,
            "d_m3_a": 16.0,
            "y_abs_a": 80.0,
            "distance_ratio": 0.8,
        },
    ]
    metrics = r4._aggregate(records)
    assert metrics is not None
    assert metrics["skill_M2_vs_Level"] == pytest.approx(0.1)
    assert metrics["skill_M3_vs_Level"] == pytest.approx(0.2)
    assert metrics["normalized_M3_divergence"] == pytest.approx(0.2)


def test_decision_passes_only_when_m2_and_m3_both_fail_to_resolve():
    decision, support = r4.decide(
        support=_support(),
        pooled=_metrics(m2_skill=0.01, m3_skill=0.02, m3_m2_skill=0.01, norm=0.12),
        by_horizon=_horizons(m2_skill=0.01, m3_skill=0.02, m3_m2_skill=0.01, norm=0.12),
        by_month=_months(m2_skill=0.01, m3_skill=0.02, m3_m2_skill=0.01, norm=0.12),
    )
    assert decision == "PASS_STATE_ALIASING_SIGNAL"
    assert support["stop_reason"] is None


def test_decision_stops_when_m2_resolves_even_if_m3_does_not():
    decision, support = r4.decide(
        support=_support(),
        pooled=_metrics(m2_skill=0.12, m3_skill=0.02, m3_m2_skill=-0.1, norm=0.12),
        by_horizon=_horizons(m2_skill=0.06, m3_skill=0.02, m3_m2_skill=-0.04, norm=0.12),
        by_month=_months(m2_skill=0.06, m3_skill=0.02, m3_m2_skill=-0.04, norm=0.12),
    )
    assert decision == "STOP_STATE_ALIASING_ROUTE"
    assert support["stop_reason"] == "M2_STATE_RESOLVES_DIVERGENCE"


def test_decision_stops_when_m3_resolves():
    decision, support = r4.decide(
        support=_support(),
        pooled=_metrics(m2_skill=0.02, m3_skill=0.12, m3_m2_skill=0.1, norm=0.12),
        by_horizon=_horizons(m2_skill=0.02, m3_skill=0.06, m3_m2_skill=0.04, norm=0.12),
        by_month=_months(m2_skill=0.02, m3_skill=0.06, m3_m2_skill=0.04, norm=0.12),
    )
    assert decision == "STOP_STATE_ALIASING_ROUTE"
    assert support["stop_reason"] == "M3_STATE_RESOLVES_DIVERGENCE"


def test_decision_stops_when_m3_future_divergence_is_small():
    decision, support = r4.decide(
        support=_support(),
        pooled=_metrics(m2_skill=0.01, m3_skill=0.02, m3_m2_skill=0.01, norm=0.04),
        by_horizon=_horizons(m2_skill=0.01, m3_skill=0.02, m3_m2_skill=0.01, norm=0.04),
        by_month=_months(m2_skill=0.01, m3_skill=0.02, m3_m2_skill=0.01, norm=0.04),
    )
    assert decision == "STOP_STATE_ALIASING_ROUTE"
    assert support["stop_reason"] == "M3_FUTURE_DIVERGENCE_SMALL"


def test_decision_support_failure_precedes_effect_logic():
    decision, support = r4.decide(
        support=_support(False),
        pooled=None,
        by_horizon=(),
        by_month=(),
    )
    assert decision == "STOP_STATE_ALIASING_ROUTE"
    assert support["stop_reason"] == "INSUFFICIENT_ANALOG_SUPPORT"


def test_decision_mixed_for_intermediate_unstable_result():
    decision, support = r4.decide(
        support=_support(),
        pooled=_metrics(m2_skill=0.06, m3_skill=0.07, m3_m2_skill=0.01, norm=0.12),
        by_horizon=_horizons(m2_skill=0.03, m3_skill=0.03, m3_m2_skill=0.0, norm=0.12),
        by_month=_months(m2_skill=0.03, m3_skill=0.03, m3_m2_skill=0.0, norm=0.12),
    )
    assert decision == "MIXED_STATE_ALIASING_SIGNAL"
    assert support["stop_reason"] is None


def test_protocol_constants_and_zero_fit_publication_are_frozen():
    assert r4.DEVELOPMENT_MONTHS == ("2019-01", "2019-04", "2019-07", "2019-10")
    assert r4.FINAL_HOLDOUT_MONTHS == ("2019-03", "2019-06", "2019-09", "2019-12")
    assert set(r4.DEVELOPMENT_MONTHS).isdisjoint(r4.FINAL_HOLDOUT_MONTHS)
    assert r4.M2_RAW_WIDTH == 201 and r4.M2_ENCODED_WIDTH == 204
    assert r4.M3_RAW_WIDTH == 311 and r4.M3_ENCODED_WIDTH == 391
    assert r4.MIN_POOLED_SUPPORT_FRACTION == 0.70
    assert r4.MIN_CELL_SUPPORT_FRACTION == 0.50
    assert r4.MIN_CELL_SUPPORTED_RECORDS == 250
    result = r4.Result(
        code_commit="0" * 40,
        decision="STOP_STATE_ALIASING_ROUTE",
        decision_support=MappingProxyType({}),
        pooled=None,
        by_horizon=(),
        by_month=(),
        cells=(),
        support=MappingProxyType({}),
        preprocessor_fit_count=0,
    ).to_public_dict()
    assert result["fit_count"] == 0
    assert result["model_fit_attempted"] is False
    assert result["holdout_accessed"] is False
    assert result["target_informed_matching"] is False
    assert result["pca_or_metric_learning"] is False
    assert result["nearest_neighbor_forecast_trained"] is False
