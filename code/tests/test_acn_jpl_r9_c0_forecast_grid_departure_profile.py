from __future__ import annotations

import numpy as np
import pytest
from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock, canonical_feature_schema
from evcf.forecasting.acn_jpl_r9_c0_forecast_grid_departure_profile import (
    PROFILE_ENCODED_WIDTH,
    PROFILE_RAW_WIDTH,
    R9C0Error,
    _forecast_grid_profile_block,
    decide_r9,
    run_r9_c0,
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
    m2_values[:, connected_position] = [14.0, 0.0]
    m2 = FeatureBlock(issue_times, m2_values, m2_names, m2_nullable)

    m3_values = np.zeros((2, len(m3_names)), dtype=np.float64)
    m3_values[:, : len(m2_names)] = m2_values
    count_position = m3_names.index(
        "m3_requested_departure_minutes_from_issue_count"
    )
    missing_position = m3_names.index(
        "m3_requested_departure_minutes_from_issue_missing_count"
    )
    m3_values[:, count_position] = [13.0, 0.0]
    m3_values[:, missing_position] = [1.0, 0.0]
    m3 = FeatureBlock(issue_times, m3_values, m3_names, m3_nullable)

    values: tuple[object, ...] = (
        None,
        -5.0,
        0.0,
        5.0,
        15.0,
        20.0,
        30.0,
        45.0,
        60.0,
        90.0,
        120.0,
        180.0,
        240.0,
        300.0,
    )
    groups = (
        tuple({"requested_departure_minutes_from_issue": value} for value in values),
        (),
    )
    return m2, m3, groups


def test_forecast_grid_profile_uses_exact_frozen_bins_and_width() -> None:
    m2, m3, groups = _blocks_and_groups()
    block = _forecast_grid_profile_block(m2, m3, groups)
    assert block.values.shape == (2, PROFILE_RAW_WIDTH)
    assert block.values.shape[1] + int(np.sum(block.nullable_mask)) == PROFILE_ENCODED_WIDTH
    assert block.feature_names[-9:] == (
        "requested_departure_observed_count",
        "requested_departure_missing_count",
        "requested_departure_overdue_count",
        "requested_departure_bin_0_15_count",
        "requested_departure_bin_15_30_count",
        "requested_departure_bin_30_60_count",
        "requested_departure_bin_60_120_count",
        "requested_departure_bin_120_240_count",
        "requested_departure_beyond_240_count",
    )
    assert not np.any(block.nullable_mask[-9:])
    assert np.array_equal(
        block.values[:, -9:],
        np.asarray(
            [
                [13.0, 1.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 1.0],
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ]
        ),
    )


def test_forecast_grid_profile_boundaries_are_left_open_right_closed() -> None:
    m2, m3, groups = _blocks_and_groups()
    block = _forecast_grid_profile_block(m2, m3, groups)
    profile = block.values[0, -9:]
    assert profile[2] == 2.0  # -5 and 0 are overdue.
    assert profile[3] == 2.0  # 5 and 15.
    assert profile[4] == 2.0  # 20 and 30.
    assert profile[5] == 2.0  # 45 and 60.
    assert profile[6] == 2.0  # 90 and 120.
    assert profile[7] == 2.0  # 180 and 240.
    assert profile[8] == 1.0  # 300.
    assert profile[0] == np.sum(profile[2:])


def test_forecast_grid_profile_rejects_canonical_availability_mismatch() -> None:
    m2, m3, groups = _blocks_and_groups()
    values = np.array(m3.values, copy=True)
    count_position = m3.feature_names.index(
        "m3_requested_departure_minutes_from_issue_count"
    )
    values[0, count_position] = 12.0
    drifted = FeatureBlock(m3.issue_times, values, m3.feature_names, m3.nullable_mask)
    with pytest.raises(R9C0Error, match="PROFILE_IDENTITY_INVALID"):
        _forecast_grid_profile_block(m2, drifted, groups)


def _summary(
    *,
    departure: float,
    profile: float,
    r8: float,
    total_departure: float,
    total_profile: float,
    total_r8: float,
    s1: float,
    equal: float,
) -> dict[str, object]:
    def metric(value: float) -> dict[str, float]:
        return {"mae_a": value}

    return {
        "arrival": {
            "BaseM2": metric(departure + 1.0),
            "DepartureAvailability": metric(departure + 0.5),
            "DepartureAug": metric(departure),
            "HorizonExposure": metric(r8),
            "ForecastGridProfile": metric(profile),
        },
        "total": {
            "S1": metric(s1),
            "Equal": metric(equal),
            "TotalAvailability": metric(total_departure + 0.5),
            "TotalDeparture": metric(total_departure),
            "TotalHorizonExposure": metric(total_r8),
            "TotalForecastGridProfile": metric(total_profile),
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


def test_decision_pass_forecast_grid_departure_profile() -> None:
    pooled = _summary(
        departure=10.0,
        profile=9.0,
        r8=10.5,
        total_departure=12.0,
        total_profile=11.0,
        total_r8=12.5,
        s1=13.0,
        equal=14.0,
    )
    by_horizon, by_month = _uniform_axes(pooled)
    decision, support = decide_r9(pooled, by_horizon, by_month)
    assert decision == "PASS_FORECAST_GRID_DEPARTURE_PROFILE"
    assert support["component_horizon_wins_vs_DepartureAug"] == 5
    assert support["component_long_horizon_wins_vs_DepartureAug"] == 3
    assert support["total_month_wins_vs_TotalDeparture"] == 4


def test_decision_stop_departure_representation_refinement() -> None:
    pooled = _summary(
        departure=10.0,
        profile=10.5,
        r8=10.8,
        total_departure=12.0,
        total_profile=12.5,
        total_r8=12.8,
        s1=13.0,
        equal=14.0,
    )
    by_horizon, by_month = _uniform_axes(pooled)
    decision, support = decide_r9(pooled, by_horizon, by_month)
    assert decision == "STOP_DEPARTURE_REPRESENTATION_REFINEMENT"
    assert support["component_horizon_wins_vs_DepartureAug"] == 0
    assert support["component_month_wins_vs_DepartureAug"] == 0


def test_decision_mixed_when_improvement_is_not_stable_enough() -> None:
    pooled = _summary(
        departure=10.0,
        profile=9.8,
        r8=10.5,
        total_departure=12.0,
        total_profile=11.8,
        total_r8=12.5,
        s1=13.0,
        equal=14.0,
    )
    win = _summary(
        departure=10.0,
        profile=9.5,
        r8=10.5,
        total_departure=12.0,
        total_profile=11.5,
        total_r8=12.5,
        s1=13.0,
        equal=14.0,
    )
    lose = _summary(
        departure=10.0,
        profile=10.2,
        r8=10.5,
        total_departure=12.0,
        total_profile=12.2,
        total_r8=12.5,
        s1=13.0,
        equal=14.0,
    )
    by_horizon = [
        {"horizon_minutes": 15, **win},
        {"horizon_minutes": 30, **win},
        {"horizon_minutes": 60, **win},
        {"horizon_minutes": 120, **lose},
        {"horizon_minutes": 240, **lose},
    ]
    by_month = [
        {"month": "2019-01", **win},
        {"month": "2019-04", **win},
        {"month": "2019-07", **lose},
        {"month": "2019-10", **lose},
    ]
    decision, support = decide_r9(pooled, by_horizon, by_month)
    assert decision == "MIXED_FORECAST_GRID_DEPARTURE_PROFILE_SIGNAL"
    assert support["component_horizon_wins_vs_DepartureAug"] == 3
    assert support["component_month_wins_vs_DepartureAug"] == 2


def test_unauthorized_run_stops_before_path_access() -> None:
    with pytest.raises(R9C0Error, match="R9_C0_NOT_AUTHORIZED"):
        run_r9_c0(
            authorized=False,
            interim_root="does-not-exist/interim",
            processed_root="does-not-exist/processed",
            r8_private_run="does-not-exist/r8",
            private_output_root="does-not-exist/output",
            code_commit="0" * 40,
            repo_root="does-not-exist/repo",
        )
