from __future__ import annotations

import numpy as np
import pytest
from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock
from evcf.forecasting.acn_jpl_r7_d1_departure_attribution import (
    AVAILABILITY_ENCODED_WIDTH,
    AVAILABILITY_RAW_WIDTH,
    R7D1Error,
    _availability_block,
    decide_attribution,
    run_r7_d1,
)


def _blocks() -> tuple[FeatureBlock, FeatureBlock]:
    issue_times = np.asarray([900, 1800], dtype=np.int64)
    m2_names = tuple(f"m2_{index:03d}" for index in range(201))
    m2_values = np.zeros((2, 201), dtype=np.float64)
    m2_nullable = np.zeros(201, dtype=np.bool_)
    m2_nullable[-3:] = True
    m2 = FeatureBlock(issue_times, m2_values, m2_names, m2_nullable)

    extra_names = [f"extra_{index:03d}" for index in range(110)]
    extra_names[3] = "m3_requested_departure_minutes_from_issue_count"
    extra_names[9] = "m3_requested_departure_minutes_from_issue_missing_count"
    m3_names = m2_names + tuple(extra_names)
    m3_values = np.concatenate(
        (m2_values, np.zeros((2, 110), dtype=np.float64)), axis=1
    )
    m3_values[:, 204] = [2.0, 3.0]
    m3_values[:, 210] = [1.0, 0.0]
    m3_nullable = np.concatenate(
        (m2_nullable, np.zeros(110, dtype=np.bool_))
    )
    m3 = FeatureBlock(issue_times, m3_values, m3_names, m3_nullable)
    return m2, m3


def test_availability_block_contains_only_count_and_missing_count() -> None:
    m2, m3 = _blocks()
    block = _availability_block(m2, m3)
    assert block.values.shape == (2, AVAILABILITY_RAW_WIDTH)
    assert block.values.shape[1] + int(np.sum(block.nullable_mask)) == AVAILABILITY_ENCODED_WIDTH
    assert block.feature_names[-2:] == (
        "m3_requested_departure_minutes_from_issue_count",
        "m3_requested_departure_minutes_from_issue_missing_count",
    )
    assert not np.any(block.nullable_mask[-2:])
    assert np.array_equal(block.values[:, -2:], np.asarray([[2.0, 1.0], [3.0, 0.0]]))
    assert not any(
        token in name
        for name in block.feature_names[-2:]
        for token in ("mean", "std", "minimum", "maximum", "p25", "p50", "p75")
    )


def test_availability_block_rejects_nullable_availability_field() -> None:
    m2, m3 = _blocks()
    nullable = np.array(m3.nullable_mask, copy=True)
    count_position = m3.feature_names.index(
        "m3_requested_departure_minutes_from_issue_count"
    )
    nullable[count_position] = True
    drifted = FeatureBlock(m3.issue_times, m3.values, m3.feature_names, nullable)
    with pytest.raises(R7D1Error, match="AVAILABILITY_FEATURE_SCHEMA_INVALID"):
        _availability_block(m2, drifted)


def test_availability_block_rejects_m2_prefix_drift() -> None:
    m2, m3 = _blocks()
    values = np.array(m3.values, copy=True)
    values[0, 0] = 1.0
    drifted = FeatureBlock(m3.issue_times, values, m3.feature_names, m3.nullable_mask)
    with pytest.raises(R7D1Error, match="FEATURE_ALIGNMENT_INVALID"):
        _availability_block(m2, drifted)


def _summary(
    base: float,
    availability: float,
    departure: float,
    s1: float,
    equal: float,
    availability_total: float,
    departure_total: float,
) -> dict[str, object]:
    def metric(value: float) -> dict[str, float]:
        return {"mae_a": value}

    return {
        "arrival": {
            "BaseM2": metric(base),
            "DepartureAvailability": metric(availability),
            "DepartureAug": metric(departure),
        },
        "total": {
            "S1": metric(s1),
            "Equal": metric(equal),
            "TotalAvailability": metric(availability_total),
            "TotalDeparture": metric(departure_total),
        },
    }


def _axes(item: dict[str, object]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    by_horizon = [
        {"horizon_minutes": horizon, **item}
        for horizon in (15, 30, 60, 120, 240)
    ]
    by_month = [
        {"month": month, **item}
        for month in ("2019-01", "2019-04", "2019-07", "2019-10")
    ]
    return by_horizon, by_month


def test_decision_timing_distribution_incremental_signal() -> None:
    pooled = _summary(10.0, 9.0, 8.0, 12.0, 13.0, 11.0, 10.0)
    by_horizon, by_month = _axes(pooled)
    decision, support = decide_attribution(pooled, by_horizon, by_month)
    assert decision == "TIMING_DISTRIBUTION_INCREMENTAL_SIGNAL"
    assert support["departure_component_horizon_wins_vs_Availability"] == 5
    assert support["departure_total_month_wins_vs_Availability"] == 4


def test_decision_availability_proxy_sufficient_signal() -> None:
    pooled = _summary(10.0, 9.0, 9.5, 12.0, 13.0, 11.0, 11.5)
    by_horizon, by_month = _axes(pooled)
    decision, support = decide_attribution(pooled, by_horizon, by_month)
    assert decision == "AVAILABILITY_PROXY_SUFFICIENT_SIGNAL"
    assert support["availability_component_horizon_wins_vs_BaseM2"] == 5
    assert support["departure_component_horizon_wins_vs_Availability"] == 0


def test_decision_timing_fails_when_one_horizon_degrades_more_than_five_percent() -> None:
    pooled = _summary(10.0, 9.0, 8.8, 12.0, 13.0, 11.0, 10.8)
    good = _summary(10.0, 9.0, 8.8, 12.0, 13.0, 11.0, 10.8)
    bad = _summary(10.0, 9.0, 9.6, 12.0, 13.0, 11.0, 11.7)
    by_horizon = [
        {"horizon_minutes": 15, **bad},
        *[
            {"horizon_minutes": horizon, **good}
            for horizon in (30, 60, 120, 240)
        ],
    ]
    by_month = [
        {"month": month, **good}
        for month in ("2019-01", "2019-04", "2019-07", "2019-10")
    ]
    decision, support = decide_attribution(pooled, by_horizon, by_month)
    assert decision == "AVAILABILITY_PROXY_SUFFICIENT_SIGNAL"
    assert support["max_departure_component_horizon_degradation_vs_Availability"] > 0.05


def test_decision_mixed_when_neither_attribution_is_stable() -> None:
    pooled = _summary(10.0, 10.2, 10.3, 12.0, 13.0, 12.3, 12.4)
    by_horizon, by_month = _axes(pooled)
    decision, _ = decide_attribution(pooled, by_horizon, by_month)
    assert decision == "MIXED_DEPARTURE_ATTRIBUTION_SIGNAL"


def test_unauthorized_run_stops_before_path_access() -> None:
    with pytest.raises(R7D1Error, match="R7_D1_NOT_AUTHORIZED"):
        run_r7_d1(
            authorized=False,
            interim_root="does-not-exist/interim",
            processed_root="does-not-exist/processed",
            r7_private_run="does-not-exist/r7",
            private_output_root="does-not-exist/output",
            code_commit="0" * 40,
            repo_root="does-not-exist/repo",
        )
