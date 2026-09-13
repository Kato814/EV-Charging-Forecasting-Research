from __future__ import annotations

import inspect
from types import MappingProxyType

import evcf.forecasting.acn_jpl_r3_control_endogeneity_gate as r3
import numpy as np
import pytest


def _row(current, pilot):
    return {"current_current_a": current, "current_pilot_a": pilot}


def _metric(delta_fraction: float):
    return {
        "pair_records": 100,
        "delta_mae_a": delta_fraction * 10.0,
        "base_mae_a": 10.0,
        "delta_fraction": delta_fraction,
    }


def _aggregate_rows(sign: float, count: int, key: str):
    rows = []
    for index in range(count):
        rows.append(
            {
                key: index,
                "Equal": _metric(sign),
                "S1": _metric(sign),
                "R1_Joint": _metric(sign),
            }
        )
    return rows


def _support(valid_fraction: float = 0.8, pairs: int = 120):
    return [
        {
            "month": month,
            "valid_issue_fraction": valid_fraction,
            "matched_pair_count": pairs,
        }
        for month in r3.DEVELOPMENT_MONTHS
    ]


def test_control_state_uses_only_actual_and_pilot_and_does_not_clip_utilization():
    groups = (
        (_row(8.0, 10.0), _row(4.0, 10.0)),
        (_row(20.0, 10.0), _row(8.0, 10.0)),
        (_row(3.0, None), _row(2.0, 4.0)),
        tuple(),
    )
    station = np.asarray([12.0, 28.0, 5.0, 0.0])
    state = r3.build_control_state(groups, station)
    assert state.valid.tolist() == [True, True, False, False]
    assert state.utilization[0] == pytest.approx(0.6)
    assert state.utilization[1] == pytest.approx(1.4)
    assert state.utilization[1] > 1.0
    assert state.coverage[2] == pytest.approx(0.5)
    assert state.binding_fraction_90[0] == 0.0
    assert state.binding_fraction_90[1] == 1.0


def test_control_state_applies_exact_coverage_and_pilot_sum_floors():
    groups = (
        tuple(_row(1.0, 1.5) for _ in range(4)),
        (_row(1.0, 8.0), _row(1.0, 8.0), _row(None, 8.0), _row(1.0, 8.0)),
        (_row(1.0, 8.0),) * 4 + (_row(None, 8.0),),
    )
    state = r3.build_control_state(groups, np.asarray([4.0, 3.0, 4.0]))
    assert state.pilot_sum_a[0] == pytest.approx(6.0)
    assert state.valid[0]
    assert state.coverage[1] == pytest.approx(0.75)
    assert not state.valid[1]
    assert state.coverage[2] == pytest.approx(0.8)
    assert state.valid[2]


def test_matching_is_deterministic_and_load_level_matched():
    n = 1005
    issues = np.arange(1_600_000_000, 1_600_000_000 + n, dtype=np.int64)
    current = np.linspace(0.0, 100.0, n)
    utilization = 0.2 + 0.6 * ((np.arange(n) * 37) % n) / n
    valid = np.ones(n, dtype=np.bool_)
    first = r3.build_match_pairs(issues, current, utilization, valid)
    second = r3.build_match_pairs(issues, current, utilization, valid)
    assert np.array_equal(first.low_rows, second.low_rows)
    assert np.array_equal(first.high_rows, second.high_rows)
    assert len(first.low_rows) == 500
    assert first.low_u_mean < first.high_u_mean
    assert first.mean_abs_current_gap_a < 1.0


def test_matching_ignores_truth_and_predictions_by_signature():
    parameters = tuple(inspect.signature(r3.build_match_pairs).parameters)
    assert parameters == (
        "issue_times",
        "station_current_a",
        "utilization",
        "valid",
    )


def test_contrast_sign_is_low_minus_high_error():
    issues = np.arange(10, dtype=np.int64)
    current = np.arange(10, dtype=np.float64)
    utilization = np.asarray([0.1, 0.9] * 5)
    valid = np.ones(10, dtype=np.bool_)
    pairs = r3.build_match_pairs(issues, current, utilization, valid)
    y = np.zeros(10)
    pred = np.zeros(10)
    pred[pairs.low_rows] = 10.0
    pred[pairs.high_rows] = 2.0
    metrics, d, b = r3.contrast_metrics(y, pred, pairs)
    assert np.all(d > 0)
    assert np.all(b > 0)
    assert metrics["delta_fraction"] > 0
    assert metrics["low_mae_a"] > metrics["high_mae_a"]


def test_decision_passes_only_when_both_references_are_large_and_stable():
    pooled = {
        "Equal": _metric(0.06),
        "S1": _metric(0.07),
        "R1_Joint": _metric(0.05),
    }
    horizons = _aggregate_rows(0.04, 5, "horizon_minutes")
    for index, row in enumerate(horizons):
        row["horizon_minutes"] = r3.HORIZONS_MINUTES[index]
    months = _aggregate_rows(0.04, 4, "month")
    for index, row in enumerate(months):
        row["month"] = r3.DEVELOPMENT_MONTHS[index]
    cells = []
    for month in r3.DEVELOPMENT_MONTHS:
        for horizon in r3.HORIZONS_MINUTES:
            cells.append(
                {
                    "month": month,
                    "horizon_minutes": horizon,
                    "Equal": _metric(0.04),
                    "S1": _metric(0.04),
                    "R1_Joint": _metric(0.04),
                }
            )
    decision, support = r3.decide(
        overall_valid_issue_fraction=0.8,
        month_support=_support(),
        pooled=pooled,
        by_horizon=horizons,
        by_month=months,
        cells=cells,
    )
    assert decision == "PASS_CONTROL_ENDOGENEITY_SIGNAL"
    assert support["sixty_min_months_both_match_pooled_sign"] == 4


def test_decision_mixed_when_direction_repeats_but_pass_effect_fails():
    pooled = {
        "Equal": _metric(-0.035),
        "S1": _metric(-0.025),
        "R1_Joint": _metric(-0.03),
    }
    horizons = _aggregate_rows(-0.01, 5, "horizon_minutes")
    months = _aggregate_rows(-0.01, 4, "month")
    cells = [
        {
            "month": month,
            "horizon_minutes": horizon,
            "Equal": _metric(-0.01),
            "S1": _metric(-0.01),
            "R1_Joint": _metric(-0.01),
        }
        for month in r3.DEVELOPMENT_MONTHS
        for horizon in r3.HORIZONS_MINUTES
    ]
    decision, _ = r3.decide(
        overall_valid_issue_fraction=0.8,
        month_support=_support(),
        pooled=pooled,
        by_horizon=horizons,
        by_month=months,
        cells=cells,
    )
    assert decision == "MIXED_CONTROL_ENDOGENEITY_SIGNAL"


def test_decision_stops_for_opposite_pooled_directions():
    pooled = {
        "Equal": _metric(0.08),
        "S1": _metric(-0.08),
        "R1_Joint": _metric(0.01),
    }
    horizons = _aggregate_rows(0.02, 5, "horizon_minutes")
    months = _aggregate_rows(0.02, 4, "month")
    decision, support = r3.decide(
        overall_valid_issue_fraction=0.8,
        month_support=_support(),
        pooled=pooled,
        by_horizon=horizons,
        by_month=months,
        cells=tuple(),
    )
    assert decision == "STOP_CONTROL_ENDOGENEITY_ROUTE"
    assert support["stop_reason"] == "POOLED_DIRECTION_UNSTABLE"


def test_decision_stops_for_insufficient_support_before_effect_size():
    pooled = {
        "Equal": _metric(0.5),
        "S1": _metric(0.5),
        "R1_Joint": _metric(0.5),
    }
    horizons = _aggregate_rows(0.5, 5, "horizon_minutes")
    months = _aggregate_rows(0.5, 4, "month")
    decision, support = r3.decide(
        overall_valid_issue_fraction=0.69,
        month_support=_support(),
        pooled=pooled,
        by_horizon=horizons,
        by_month=months,
        cells=tuple(),
    )
    assert decision == "STOP_CONTROL_ENDOGENEITY_ROUTE"
    assert support["stop_reason"] == "INSUFFICIENT_CONTROL_STATE_SUPPORT"


def test_protocol_constants_and_zero_fit_publication_are_frozen():
    assert r3.DEVELOPMENT_MONTHS == ("2019-01", "2019-04", "2019-07", "2019-10")
    assert r3.FINAL_HOLDOUT_MONTHS == ("2019-03", "2019-06", "2019-09", "2019-12")
    assert set(r3.DEVELOPMENT_MONTHS).isdisjoint(r3.FINAL_HOLDOUT_MONTHS)
    assert r3.CONTROL_FIELDS == ("current_current_a", "current_pilot_a")
    assert r3.COVERAGE_FLOOR == 0.80
    assert r3.PILOT_SUM_FLOOR_A == 6.0
    assert r3.CURRENT_LEVEL_BINS == 5
    result = r3.Result(
        code_commit="0" * 40,
        decision="STOP_CONTROL_ENDOGENEITY_ROUTE",
        decision_support=MappingProxyType({}),
        pooled=MappingProxyType({}),
        by_horizon=tuple(),
        by_month=tuple(),
        cells=tuple(),
        month_support=tuple(),
        overall_valid_issue_fraction=0.0,
    ).to_public_dict()
    assert result["fit_count"] == 0
    assert result["model_fit_attempted"] is False
    assert result["reference_models_retrained"] is False
    assert result["holdout_accessed"] is False
    assert result["future_control_predictor"] is False
