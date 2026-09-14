from __future__ import annotations

import numpy as np
import pytest

from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock, canonical_feature_schema
from evcf.forecasting.acn_jpl_r8_c0_horizon_departure_exposure import (
    HORIZON_EXPOSURE_ENCODED_WIDTH,
    HORIZON_EXPOSURE_RAW_WIDTH,
    R8C0Error,
    _horizon_exposure_block,
    decide_r8,
    run_r8_c0,
)


def _blocks_and_groups() -> tuple[
    FeatureBlock,
    FeatureBlock,
    tuple[tuple[dict[str, object], ...], ...],
]:
    issue_times = np.asarray([900, 1800], dtype=np.int64)
    m2_names, m2_nullable = canonical_feature_schema("M2")
    m3_names, m3_nullable = canonical_feature_schema("M3")
    m2_values = np.zeros((2, len(m2_names)), dtype=np.float64)
    connected_position = m2_names.index("connected_session_count")
    m2_values[:, connected_position] = [4.0, 2.0]
    m2 = FeatureBlock(issue_times, m2_values, m2_names, m2_nullable)

    m3_values = np.zeros((2, len(m3_names)), dtype=np.float64)
    m3_values[:, : len(m2_names)] = m2_values
    count_position = m3_names.index(
        "m3_requested_departure_minutes_from_issue_count"
    )
    missing_position = m3_names.index(
        "m3_requested_departure_minutes_from_issue_missing_count"
    )
    m3_values[:, count_position] = [3.0, 2.0]
    m3_values[:, missing_position] = [1.0, 0.0]
    m3 = FeatureBlock(issue_times, m3_values, m3_names, m3_nullable)

    groups = (
        (
            {"requested_departure_minutes_from_issue": None},
            {"requested_departure_minutes_from_issue": -5.0},
            {"requested_departure_minutes_from_issue": 10.0},
            {"requested_departure_minutes_from_issue": 70.0},
        ),
        (
            {"requested_departure_minutes_from_issue": 30.0},
            {"requested_departure_minutes_from_issue": 90.0},
        ),
    )
    return m2, m3, groups


def test_horizon_exposure_block_uses_only_four_frozen_counts() -> None:
    m2, m3, groups = _blocks_and_groups()
    block = _horizon_exposure_block(m2, m3, groups, horizon_minutes=60)
    assert block.values.shape == (2, HORIZON_EXPOSURE_RAW_WIDTH)
    assert (
        block.values.shape[1] + int(np.sum(block.nullable_mask))
        == HORIZON_EXPOSURE_ENCODED_WIDTH
    )
    assert block.feature_names[-4:] == (
        "requested_departure_observed_count",
        "requested_departure_missing_count",
        "requested_departure_overdue_count",
        "requested_departure_due_within_horizon_count",
    )
    assert not np.any(block.nullable_mask[-4:])
    assert np.array_equal(
        block.values[:, -4:],
        np.asarray([[3.0, 1.0, 1.0, 1.0], [2.0, 0.0, 0.0, 1.0]]),
    )


def test_horizon_exposure_count_changes_only_with_frozen_horizon_rule() -> None:
    m2, m3, groups = _blocks_and_groups()
    block_60 = _horizon_exposure_block(m2, m3, groups, horizon_minutes=60)
    block_120 = _horizon_exposure_block(m2, m3, groups, horizon_minutes=120)
    assert np.array_equal(block_60.values[:, -4:-1], block_120.values[:, -4:-1])
    assert np.array_equal(block_60.values[:, -1], np.asarray([1.0, 1.0]))
    assert np.array_equal(block_120.values[:, -1], np.asarray([2.0, 2.0]))


def test_horizon_exposure_rejects_canonical_availability_mismatch() -> None:
    m2, m3, groups = _blocks_and_groups()
    values = np.array(m3.values, copy=True)
    count_position = m3.feature_names.index(
        "m3_requested_departure_minutes_from_issue_count"
    )
    values[0, count_position] = 2.0
    drifted = FeatureBlock(m3.issue_times, values, m3.feature_names, m3.nullable_mask)
    with pytest.raises(R8C0Error, match="HORIZON_EXPOSURE_IDENTITY_INVALID"):
        _horizon_exposure_block(m2, drifted, groups, horizon_minutes=60)


def _summary(
    *,
    departure: float,
    exposure: float,
    availability: float,
    total_departure: float,
    total_exposure: float,
    total_availability: float,
    s1: float,
    equal: float,
) -> dict[str, object]:
    def metric(value: float) -> dict[str, float]:
        return {"mae_a": value}

    return {
        "arrival": {
            "BaseM2": metric(availability + 1.0),
            "DepartureAvailability": metric(availability),
            "DepartureAug": metric(departure),
            "HorizonExposure": metric(exposure),
        },
        "total": {
            "S1": metric(s1),
            "Equal": metric(equal),
            "TotalAvailability": metric(total_availability),
            "TotalDeparture": metric(total_departure),
            "TotalHorizonExposure": metric(total_exposure),
        },
    }


def _uniform_axes(
    item: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    by_horizon = [
        {"horizon_minutes": horizon, **item}
        for horizon in (15, 30, 60, 120, 240)
    ]
    by_month = [
        {"month": month, **item}
        for month in ("2019-01", "2019-04", "2019-07", "2019-10")
    ]
    return by_horizon, by_month


def test_decision_pass_horizon_aligned_departure_exposure() -> None:
    pooled = _summary(
        departure=10.0,
        exposure=9.0,
        availability=11.0,
        total_departure=12.0,
        total_exposure=11.0,
        total_availability=12.5,
        s1=13.0,
        equal=14.0,
    )
    by_horizon, by_month = _uniform_axes(pooled)
    decision, support = decide_r8(pooled, by_horizon, by_month)
    assert decision == "PASS_HORIZON_ALIGNED_DEPARTURE_EXPOSURE"
    assert support["component_horizon_wins_vs_DepartureAug"] == 5
    assert support["component_long_horizon_wins_vs_DepartureAug"] == 3
    assert support["total_month_wins_vs_TotalDeparture"] == 4


def test_decision_no_stable_horizon_aligned_advantage() -> None:
    pooled = _summary(
        departure=10.0,
        exposure=10.5,
        availability=11.0,
        total_departure=12.0,
        total_exposure=12.5,
        total_availability=13.0,
        s1=13.5,
        equal=14.0,
    )
    by_horizon, by_month = _uniform_axes(pooled)
    decision, support = decide_r8(pooled, by_horizon, by_month)
    assert decision == "NO_STABLE_HORIZON_ALIGNED_ADVANTAGE"
    assert support["component_horizon_wins_vs_DepartureAug"] == 0
    assert support["total_month_wins_vs_TotalDeparture"] == 0


def test_decision_mixed_when_pooled_improves_without_stability() -> None:
    pooled = _summary(
        departure=10.0,
        exposure=9.8,
        availability=10.5,
        total_departure=12.0,
        total_exposure=11.8,
        total_availability=12.5,
        s1=13.0,
        equal=13.5,
    )
    win = _summary(
        departure=10.0,
        exposure=9.5,
        availability=10.5,
        total_departure=12.0,
        total_exposure=11.5,
        total_availability=12.5,
        s1=13.0,
        equal=13.5,
    )
    lose = _summary(
        departure=10.0,
        exposure=10.2,
        availability=10.5,
        total_departure=12.0,
        total_exposure=12.2,
        total_availability=12.5,
        s1=13.0,
        equal=13.5,
    )
    by_horizon = [
        {"horizon_minutes": 15, **win},
        {"horizon_minutes": 30, **win},
        {"horizon_minutes": 60, **lose},
        {"horizon_minutes": 120, **lose},
        {"horizon_minutes": 240, **lose},
    ]
    by_month = [
        {"month": "2019-01", **win},
        {"month": "2019-04", **win},
        {"month": "2019-07", **lose},
        {"month": "2019-10", **lose},
    ]
    decision, _ = decide_r8(pooled, by_horizon, by_month)
    assert decision == "MIXED_HORIZON_ALIGNED_DEPARTURE_EXPOSURE_SIGNAL"


def test_unauthorized_run_stops_before_path_access() -> None:
    with pytest.raises(R8C0Error, match="R8_C0_NOT_AUTHORIZED"):
        run_r8_c0(
            authorized=False,
            interim_root="does-not-exist/interim",
            processed_root="does-not-exist/processed",
            r7_d1_private_run="does-not-exist/r7-d1",
            private_output_root="does-not-exist/output",
            code_commit="0" * 40,
            repo_root="does-not-exist/repo",
        )
