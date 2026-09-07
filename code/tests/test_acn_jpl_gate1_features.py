from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import evcf.forecasting.acn_jpl_gate1_features as features
import numpy as np
import pytest
from evcf.forecasting.acn_jpl_gate1_data import (
    CausalSessionSeries,
    Gate1Snapshot,
    verify_and_load_snapshot,
)
from evcf.forecasting.acn_jpl_gate1_features import (
    M3_SESSION_FIELDS,
    FeatureBlock,
    M4FeatureAccumulator,
    build_feature_blocks,
    causal_session_trajectory_statistics,
    encode_m1,
    encode_m2,
    encode_m3,
    encode_m4,
    feature_encoding_manifest,
    fixed_pool,
    verified_feature_block_provenance,
)


def _m3_row(issue: int, session: int, **updates: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "issue_index": 8_000 + session,
        "issue_time_utc_s": issue,
        "anonymous_session_index": session,
        "elapsed_connection_s": 100,
        "elapsed_charging_time_proxy_s": 20,
        "current_current_a": 1.0,
        "recent_current_mean_a": 0.8,
        "recent_current_peak_a": 1.2,
        "recent_current_observed_ratio": 0.5,
        "cumulative_current_ah": 0.25,
        "cumulative_current_observed_ratio": 0.75,
        "current_pilot_a": 8.0,
        "user_input_modified_utc_s": issue - 1,
        "requested_departure_minutes_from_issue": 60.0,
        "known_kwh_requested": 10.0,
    }
    row.update(updates)
    return row


def _m4_ref(issue: int, session: int) -> dict[str, Any]:
    return {
        "issue_index": 9_000 + session,
        "issue_time_utc_s": issue,
        "anonymous_session_index": session,
        "current_start_offset_inclusive": 123,
        "current_end_offset_exclusive": 456,
        "pilot_start_offset_inclusive": 234,
        "pilot_end_offset_exclusive": 567,
        "min_visible_timestamp_utc_s": issue - 3_600,
        "max_visible_timestamp_utc_s": issue,
        "partial_current_trajectory_ref": "cleaned_current_prefix",
        "partial_pilot_trajectory_ref": "cleaned_pilot_prefix",
    }


def _series(
    session: int,
    current_times: list[int] | tuple[int, ...] = (),
    current_values: list[float] | tuple[float, ...] = (),
    pilot_times: list[int] | tuple[int, ...] = (),
    pilot_values: list[float] | tuple[float, ...] = (),
) -> CausalSessionSeries:
    return CausalSessionSeries(
        anonymous_session_index=session,
        current_timestamps_utc_s=np.asarray(current_times, dtype=np.int64),
        current_values_a=np.asarray(current_values, dtype=np.float64),
        pilot_timestamps_utc_s=np.asarray(pilot_times, dtype=np.int64),
        pilot_values_a=np.asarray(pilot_values, dtype=np.float64),
    )


def _snapshot() -> Gate1Snapshot:
    issue_times = np.asarray([1_000, 1_900, 2_800], dtype=np.int64)
    history = np.tile(np.arange(96, dtype=np.float32), (3, 1))
    history[2, 0] = np.nan
    mask = np.ones((3, 96), dtype=np.bool_)
    mask[2, 0] = False
    calendar = np.asarray([[0, 0, 0], [1, 1, 0], [2, 6, 1]], dtype=np.int16)

    group_1 = (
        _m3_row(issue_times[1], 1, current_current_a=0.0, current_pilot_a=6.0),
        _m3_row(issue_times[1], 2, current_current_a=0.1, current_pilot_a=7.0),
        _m3_row(issue_times[1], 3, current_current_a=0.100001, current_pilot_a=8.0),
    )
    group_2 = (
        _m3_row(
            issue_times[2],
            4,
            current_current_a=None,
            recent_current_mean_a=None,
            recent_current_peak_a=None,
            current_pilot_a=None,
            requested_departure_minutes_from_issue=None,
            known_kwh_requested=None,
        ),
    )
    m3_by_issue = ((), group_1, group_2)
    m3_rows = tuple(row for group in m3_by_issue for row in group)
    legacy = ((), (_m4_ref(issue_times[1], 3),), ())
    return Gate1Snapshot(
        data_snapshot_sha256="a" * 64,
        artifact_sha256={},
        issue_times=issue_times,
        horizons=np.asarray([15, 30, 60, 120, 240], dtype=np.int16),
        labels=np.zeros((3, 5), dtype=np.float32),
        m1_history=history,
        m1_history_mask=mask,
        m1_calendar=calendar,
        m2_current_state=np.asarray(
            [
                [0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                [3.0, 1.0, 0.200001, 1.0, 21.0, 7.0],
                [1.0, 0.0, np.nan, 0.0, np.nan, np.nan],
            ],
            dtype=np.float32,
        ),
        m3_rows=m3_rows,
        m4_rows=tuple(row for group in legacy for row in group),
        m3_by_issue_time=m3_by_issue,
        m4_by_issue_time=legacy,
        station_times=np.asarray([], dtype=np.int64),
        station_current_mean_a=np.asarray([], dtype=np.float32),
        station_valid_90=np.asarray([], dtype=np.bool_),
    )


def _consume_snapshot(accumulator: M4FeatureAccumulator, snapshot: Gate1Snapshot) -> None:
    for position, (issue, rows) in enumerate(
        zip(snapshot.issue_times, snapshot.m3_by_issue_time, strict=True)
    ):
        for row in rows:
            accumulator(position, int(issue), _series(int(row["anonymous_session_index"])))


def test_fixed_pool_order_and_empty_missing_semantics() -> None:
    np.testing.assert_allclose(
        fixed_pool([1.0, None, 3.0], total_count=3),
        [2.0, 4.0, 2.0, 1.0, 1.0, 3.0, 1.5, 2.0, 2.5, 1.0],
    )
    empty = fixed_pool([], total_count=0)
    np.testing.assert_array_equal(empty[[0, 1, 9]], [0.0, 0.0, 0.0])
    assert np.isnan(empty[2:9]).all()
    missing = fixed_pool([None, np.nan], total_count=2)
    np.testing.assert_array_equal(missing[[0, 1, 9]], [0.0, 0.0, 2.0])
    assert np.isnan(missing[2:9]).all()


def test_fixed_pool_singleton_mixed_quantiles_and_validation() -> None:
    np.testing.assert_allclose(
        fixed_pool([4.0], total_count=1),
        [1.0, 4.0, 4.0, 0.0, 4.0, 4.0, 4.0, 4.0, 4.0, 0.0],
    )
    np.testing.assert_allclose(
        fixed_pool([1.0, 2.0, 5.0, None], total_count=4)[6:9],
        [1.5, 2.0, 3.5],
    )
    for bad in ([1.0, np.inf], [True], [False, 1.0]):
        with pytest.raises((TypeError, ValueError)):
            fixed_pool(bad, total_count=len(bad))
    with pytest.raises(ValueError, match="length"):
        fixed_pool([1.0], total_count=2)


def test_feature_block_is_immutable_and_validates_contract() -> None:
    block = FeatureBlock(
        issue_times=np.asarray([1, 2], dtype=np.int64),
        values=np.asarray([[1.0], [2.0]]),
        feature_names=("x",),
        nullable_mask=np.asarray([False]),
    )
    assert not block.issue_times.flags.writeable
    assert not block.values.flags.writeable
    assert not block.nullable_mask.flags.writeable
    with pytest.raises(ValueError):
        block.values.setflags(write=True)
    with pytest.raises(ValueError, match="feature_names"):
        FeatureBlock(np.asarray([1], dtype=np.int64), np.zeros((1, 2)), ("x",), np.zeros(2, bool))


def test_m1_order_mask_dimension_and_index_exclusion() -> None:
    block = encode_m1(_snapshot())

    assert block.values.shape == (3, 195)
    assert block.feature_names[:3] == (
        "history_station_current_mean_a_lag_096",
        "history_station_current_mean_a_lag_095",
        "history_station_current_mean_a_lag_094",
    )
    assert block.feature_names[95] == "history_station_current_mean_a_lag_001"
    assert block.feature_names[96] == "history_observed_mask_lag_096"
    assert block.feature_names[191] == "history_observed_mask_lag_001"
    assert block.feature_names[-3:] == ("quarter_hour_index", "day_of_week", "is_weekend")
    np.testing.assert_array_equal(block.values[0, :96], np.arange(96))
    np.testing.assert_array_equal(block.values[2, 96:192], _snapshot().m1_history_mask[2])
    assert not block.nullable_mask.any()
    forbidden = {
        "issue_time_utc_s",
        "issue_index",
        "anonymous_session_index",
        "offset",
        "partial_current_trajectory_ref",
        "user_input_modified_utc_s",
    }
    assert forbidden.isdisjoint(block.feature_names)


def test_m2_no_connection_partial_and_strict_active_threshold() -> None:
    snapshot = _snapshot()
    block = encode_m2(snapshot, encode_m1(snapshot), validate_against_m3=True)

    assert block.values.shape == (3, 201)
    assert block.feature_names[-6:] == (
        "connected_session_count",
        "active_charging_session_count",
        "station_current_a",
        "station_current_observed_ratio",
        "pilot_sum_a",
        "pilot_mean_a",
    )
    np.testing.assert_array_equal(block.values[0, -6:], [0, 0, 0, 1, 0, 0])
    assert np.isnan(block.values[2, [-4, -2, -1]]).all()
    assert block.nullable_mask.sum() == 3
    assert block.values[1, -5] == 1.0  # only 0.100001 is strictly greater than 0.1 A

    drift = snapshot.m2_current_state.copy()
    drift[1, 1] = 2
    with pytest.raises(ValueError, match="active"):
        encode_m2(replace(snapshot, m2_current_state=drift), validate_against_m3=True)


def test_m3_fixed_field_and_pool_order_empty_groups_and_dimensions() -> None:
    snapshot = _snapshot()
    m2 = encode_m2(snapshot, validate_against_m3=True)
    block = encode_m3(snapshot, m2)

    assert len(M3_SESSION_FIELDS) == 11
    assert block.values.shape == (3, 311)
    assert block.nullable_mask.sum() == 80
    assert block.feature_names[:201] == m2.feature_names
    assert block.feature_names[201:211] == tuple(
        f"m3_{M3_SESSION_FIELDS[0]}_{pool}" for pool in features.FIXED_POOL_STAT_NAMES
    )
    for field_index in range(11):
        start = 201 + field_index * 10
        np.testing.assert_array_equal(block.values[0, [start, start + 1, start + 9]], 0.0)
        assert np.isnan(block.values[0, start + 2 : start + 9]).all()
    forbidden = {
        "issue_time_utc_s",
        "issue_index",
        "anonymous_session_index",
        "current_start_offset_inclusive",
        "partial_current_trajectory_ref",
        "user_input_modified_utc_s",
    }
    assert forbidden.isdisjoint(block.feature_names)


def test_cumulative_tier_prefixes_and_raw_dimensions() -> None:
    snapshot = _snapshot()
    accumulator = M4FeatureAccumulator(issue_count=3)
    _consume_snapshot(accumulator, snapshot)
    blocks = build_feature_blocks(snapshot, accumulator)

    assert tuple(blocks) == ("M1", "M2", "M3", "M4")
    assert {tier: block.values.shape[1] for tier, block in blocks.items()} == {
        "M1": 195,
        "M2": 201,
        "M3": 311,
        "M4": 671,
    }
    assert {tier: int(block.nullable_mask.sum()) for tier, block in blocks.items()} == {
        "M1": 0,
        "M2": 3,
        "M3": 80,
        "M4": 332,
    }
    for parent, child in zip(("M1", "M2", "M3"), ("M2", "M3", "M4"), strict=True):
        width = blocks[parent].values.shape[1]
        assert blocks[child].feature_names[:width] == blocks[parent].feature_names
        np.testing.assert_allclose(
            blocks[child].values[:, :width], blocks[parent].values, equal_nan=True
        )


def test_seasonal_feature_blocks_need_no_m4_accumulator_or_material() -> None:
    blocks = build_feature_blocks(_snapshot(), tiers=("M1", "M2", "M3"))
    manifest = feature_encoding_manifest(blocks)

    assert tuple(blocks) == ("M1", "M2", "M3")
    assert manifest["tier_order"] == ["M1", "M2", "M3"]
    assert {
        tier: (
            spec["raw_dimension"],
            spec["missing_indicator_dimension"],
            spec["encoded_dimension"],
        )
        for tier, spec in manifest["tiers"].items()
    } == {
        "M1": (195, 0, 195),
        "M2": (201, 3, 204),
        "M3": (311, 80, 391),
    }
    assert "m4" not in json.dumps(manifest, sort_keys=True).lower()


def test_seasonal_feature_blocks_never_access_an_optional_accumulator() -> None:
    class PoisonAccumulator:
        def __getattribute__(self, name: str) -> Any:
            raise AssertionError(f"seasonal encoding accessed accumulator attribute {name}")

    blocks = build_feature_blocks(
        _snapshot(),
        PoisonAccumulator(),  # type: ignore[arg-type]
        tiers=("M1", "M2", "M3"),
    )

    assert tuple(blocks) == ("M1", "M2", "M3")


def test_default_feature_tiers_fail_closed_without_m4_accumulator() -> None:
    with pytest.raises(TypeError, match="M4.*Accumulator"):
        build_feature_blocks(_snapshot())


def test_missing_m4_accumulator_is_rejected_before_snapshot_access() -> None:
    with pytest.raises(TypeError, match="M4.*Accumulator"):
        build_feature_blocks(object())  # type: ignore[arg-type]


def test_m4_weighted_hold_slope_joint_gap_and_issue_poison() -> None:
    issue = 1_000
    original = _series(
        7,
        current_times=[695, 707, 990, 1_000],
        current_values=[0.05, 0.2, 0.0, 999.0],
        pilot_times=[698, 708, 995, 1_000],
        pilot_values=[0.3, 0.1, 0.4, 999.0],
    )
    poisoned = _series(
        7,
        current_times=[695, 707, 990, 1_000],
        current_values=[0.05, 0.2, 0.0, -999_999.0],
        pilot_times=[698, 708, 995, 1_000],
        pilot_values=[0.3, 0.1, 0.4, -999_999.0],
    )

    stats = causal_session_trajectory_statistics(original, issue)[0]
    poisoned_stats = causal_session_trajectory_statistics(poisoned, issue)[0]
    np.testing.assert_allclose(stats, poisoned_stats, equal_nan=True)
    assert stats[0] == pytest.approx(2.75 / 29)
    assert stats[1] == pytest.approx(0.2)
    assert stats[2] == pytest.approx(0.0)
    assert stats[3] == pytest.approx(0.09034877590740624)
    assert stats[4] == pytest.approx(-0.05 * 60 / 295)
    assert stats[5] == pytest.approx(19 / 29)
    assert stats[6] == pytest.approx(29 / 300)
    assert stats[7] == pytest.approx(2.75 / 24)
    assert stats[8] == pytest.approx(0.4)


@pytest.mark.parametrize(
    ("timestamp", "coverage"), [(688, 0.0), (689, 1.0), (700, 12.0), (1_000, 0.0)]
)
def test_m4_start_minus_12_start_minus_11_start_and_issue_boundaries(
    timestamp: int, coverage: float
) -> None:
    stats = causal_session_trajectory_statistics(
        _series(1, current_times=[timestamp], current_values=[2.0]), 1_000
    )[0]
    assert stats[6] == pytest.approx(coverage / 300)
    if coverage:
        assert stats[0] == 2.0
    else:
        assert np.isnan(stats[:6]).all()


def test_m4_next_sample_caps_hold_and_single_point_slope_is_missing() -> None:
    stats = causal_session_trajectory_statistics(
        _series(1, current_times=[700, 705], current_values=[1.0, 3.0]), 1_000
    )[0]
    assert stats[0] == pytest.approx(41 / 17)
    assert stats[6] == pytest.approx(17 / 300)
    assert stats[4] == pytest.approx(24.0)

    singleton = causal_session_trajectory_statistics(
        _series(1, current_times=[700], current_values=[1.0]), 1_000
    )[0]
    assert np.isnan(singleton[4])


def test_m4_weighted_population_std_is_numerically_stable() -> None:
    constant = causal_session_trajectory_statistics(
        _series(
            1,
            current_times=[700, 705, 712],
            current_values=[14.2102464, 14.2102464, 14.2102464],
        ),
        1_000,
    )[0]
    assert constant[3] == pytest.approx(0.0, abs=1e-12)

    large_offset = causal_session_trajectory_statistics(
        _series(
            1,
            current_times=[700, 712],
            current_values=[100_000_000.0, 100_000_001.0],
        ),
        1_000,
    )[0]
    assert large_offset[3] == pytest.approx(0.5, abs=1e-12)


@pytest.mark.parametrize(("window_position", "window_minutes"), tuple(enumerate((5, 15, 30, 60))))
def test_m4_all_frozen_window_boundaries(window_position: int, window_minutes: int) -> None:
    issue = 10_000
    start = issue - window_minutes * 60
    at_start = causal_session_trajectory_statistics(
        _series(1, current_times=[start], current_values=[2.0]), issue
    )[window_position]
    before_start = causal_session_trajectory_statistics(
        _series(1, current_times=[start - 11], current_values=[2.0]), issue
    )[window_position]
    assert at_start[6] == pytest.approx(12 / (window_minutes * 60))
    assert before_start[6] == pytest.approx(1 / (window_minutes * 60))


def test_m4_nonzero_is_not_the_active_threshold_and_gap_requires_joint_coverage() -> None:
    issue = 1_000
    stats = causal_session_trajectory_statistics(
        _series(
            1,
            current_times=[700, 712, 724, 736],
            current_values=[0.0, 0.05, 0.1, -0.25],
            pilot_times=[900],
            pilot_values=[8.0],
        ),
        issue,
    )[0]
    assert stats[5] == pytest.approx(3 / 4)
    assert np.isnan(stats[7:9]).all()


def test_m4_rejects_malicious_future_nonfinite_bool_and_array_drift() -> None:
    with pytest.raises(ValueError, match="later than issue"):
        causal_session_trajectory_statistics(
            _series(1, current_times=[1_001], current_values=[1.0]), 1_000
        )
    with pytest.raises(ValueError, match="finite"):
        causal_session_trajectory_statistics(
            _series(1, current_times=[999], current_values=[np.inf]), 1_000
        )
    bad_bool = CausalSessionSeries(
        anonymous_session_index=1,
        current_timestamps_utc_s=np.asarray([True]),
        current_values_a=np.asarray([1.0]),
        pilot_timestamps_utc_s=np.asarray([], dtype=np.int64),
        pilot_values_a=np.asarray([], dtype=np.float64),
    )
    with pytest.raises((TypeError, ValueError)):
        causal_session_trajectory_statistics(bad_bool, 1_000)
    with pytest.raises(ValueError, match="length"):
        causal_session_trajectory_statistics(
            _series(1, current_times=[999], current_values=[]), 1_000
        )


def test_m4_accumulator_includes_inactive_connected_and_reuses_each_pair_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    calls = 0
    original = features._causal_session_multiwindow_statistics

    def spy(series: CausalSessionSeries, issue_time_utc_s: int) -> np.ndarray:
        nonlocal calls
        calls += 1
        return original(series, issue_time_utc_s)

    monkeypatch.setattr(features, "_causal_session_multiwindow_statistics", spy)
    accumulator = M4FeatureAccumulator(issue_count=3)
    _consume_snapshot(accumulator, snapshot)
    extension = accumulator.encode(snapshot)

    assert calls == len(snapshot.m3_rows) == accumulator.computed_pair_count == 4
    assert accumulator.peak_temporary_session_count == 3
    assert extension.shape == (3, 360)
    # All four connected sessions had empty current series. The current-mean pool
    # therefore records them as missing, while observed-ratio pools finite zeros.
    assert extension[1, 0] == 0
    assert extension[1, 9] == 3
    observed_ratio_start = 6 * 10
    np.testing.assert_array_equal(
        extension[1, observed_ratio_start + np.asarray([0, 1, 2, 9])],
        [3.0, 0.0, 0.0, 0.0],
    )


@pytest.mark.parametrize("problem", ["duplicate", "missing", "order", "issue"])
def test_m4_consumer_rejects_duplicate_missing_order_and_issue(problem: str) -> None:
    snapshot = _snapshot()
    accumulator = M4FeatureAccumulator(issue_count=3)
    rows = snapshot.m3_by_issue_time[1]
    if problem == "duplicate":
        accumulator(1, 1_900, _series(1))
        with pytest.raises(ValueError, match="duplicate"):
            accumulator(1, 1_900, _series(1))
        return
    if problem == "order":
        accumulator(2, 2_800, _series(4))
        with pytest.raises(ValueError, match="order"):
            accumulator(1, 1_900, _series(1))
        return
    if problem == "issue":
        accumulator(1, 1_901, _series(1))
        with pytest.raises(ValueError, match="issue"):
            accumulator.encode(snapshot)
        return
    for row in rows[:-1]:
        accumulator(1, 1_900, _series(int(row["anonymous_session_index"])))
    accumulator(2, 2_800, _series(4))
    with pytest.raises(ValueError, match="connected"):
        accumulator.encode(snapshot)


def test_m4_legacy_active_reference_audit_is_exact_and_threshold_is_strict() -> None:
    snapshot = _snapshot()
    accumulator = M4FeatureAccumulator(issue_count=3)
    _consume_snapshot(accumulator, snapshot)
    accumulator.encode(snapshot)

    wrong_legacy = ((), (_m4_ref(1_900, 2), _m4_ref(1_900, 3)), ())
    wrong = replace(
        snapshot,
        m4_by_issue_time=wrong_legacy,
        m4_rows=tuple(row for group in wrong_legacy for row in group),
    )
    second = M4FeatureAccumulator(issue_count=3)
    _consume_snapshot(second, wrong)
    with pytest.raises(ValueError, match="active-only"):
        second.encode(wrong)


def test_m4_cached_encoding_reaudits_connected_set_and_snapshot_provenance() -> None:
    snapshot = _snapshot()
    accumulator = M4FeatureAccumulator(issue_count=3)
    _consume_snapshot(accumulator, snapshot)
    first = accumulator.encode(snapshot)
    np.testing.assert_allclose(accumulator.encode(snapshot), first, equal_nan=True)

    reduced_groups = (
        snapshot.m3_by_issue_time[0],
        snapshot.m3_by_issue_time[1][:-1],
        snapshot.m3_by_issue_time[2],
    )
    reduced = replace(
        snapshot,
        m3_by_issue_time=reduced_groups,
        m3_rows=tuple(row for group in reduced_groups for row in group),
    )
    with pytest.raises(ValueError, match="connected"):
        accumulator.encode(reduced)

    second = M4FeatureAccumulator(issue_count=3)
    _consume_snapshot(second, snapshot)
    second.encode(snapshot)
    with pytest.raises(ValueError, match="provenance"):
        second.encode(replace(snapshot, data_snapshot_sha256="b" * 64))


def _changed_block(block: FeatureBlock, *, column: int = 0) -> FeatureBlock:
    values = block.values.copy()
    values[0, column] += 1.0
    return FeatureBlock(block.issue_times, values, block.feature_names, block.nullable_mask)


def test_custom_parent_blocks_cannot_bypass_snapshot_source_contracts() -> None:
    snapshot = _snapshot()
    m1 = encode_m1(snapshot)
    with pytest.raises(ValueError, match="M1"):
        encode_m2(snapshot, _changed_block(m1))

    m2 = encode_m2(snapshot, validate_against_m3=True)
    with pytest.raises(ValueError, match="M2"):
        encode_m3(snapshot, _changed_block(m2))

    drifted_state = snapshot.m2_current_state.copy()
    drifted_state[1, 1] = 2.0
    with pytest.raises(ValueError, match="active"):
        encode_m3(replace(snapshot, m2_current_state=drifted_state), m2)

    m3 = encode_m3(snapshot, m2)
    accumulator = M4FeatureAccumulator(issue_count=3)
    _consume_snapshot(accumulator, snapshot)
    with pytest.raises(ValueError, match="M3"):
        encode_m4(snapshot, accumulator, _changed_block(m3))


def test_manifest_is_json_safe_path_free_and_records_all_dimensions() -> None:
    snapshot = _snapshot()
    accumulator = M4FeatureAccumulator(issue_count=3)
    _consume_snapshot(accumulator, snapshot)
    blocks = build_feature_blocks(snapshot, accumulator)
    manifest = feature_encoding_manifest(blocks)
    encoded = json.dumps(manifest, sort_keys=True, allow_nan=False)

    assert manifest["schema_version"] == "acn-jpl-gate1-feature-encoding/v1"
    assert {
        tier: (
            spec["raw_dimension"],
            spec["missing_indicator_dimension"],
            spec["encoded_dimension"],
        )
        for tier, spec in manifest["tiers"].items()
    } == {
        "M1": (195, 0, 195),
        "M2": (201, 3, 204),
        "M3": (311, 80, 391),
        "M4": (671, 332, 1003),
    }
    assert "issue_time_utc_s" not in encoded
    assert "anonymous_session_index" not in encoded
    assert "partial_current_trajectory_ref" not in encoded
    assert "\\" not in encoded
    assert ":/" not in encoded
    for tier in manifest["tiers"].values():
        assert len(tier["features"]) == tier["raw_dimension"]
        assert [item["position"] for item in tier["features"]] == list(range(tier["raw_dimension"]))
        assert all(
            set(item) == {"position", "name", "formula", "unit", "nullable"}
            for item in tier["features"]
        )
        indicators = tier["missing_indicators"]
        assert [item["position"] for item in indicators] == list(
            range(tier["raw_dimension"], tier["encoded_dimension"])
        )
        assert all(
            set(item) == {"position", "name", "source_feature", "formula", "unit"}
            for item in indicators
        )
        assert all(item["formula"] == "1 if source is missing else 0" for item in indicators)
        assert all(item["unit"] == "1" for item in indicators)


def test_manifest_freezes_pooling_trajectory_ordering_and_privacy_semantics() -> None:
    snapshot = _snapshot()
    accumulator = M4FeatureAccumulator(issue_count=3)
    _consume_snapshot(accumulator, snapshot)
    manifest = feature_encoding_manifest(build_feature_blocks(snapshot, accumulator))

    pooling = manifest["pooling_contract"]
    assert pooling["statistic_order"] == list(features.FIXED_POOL_STAT_NAMES)
    assert pooling["count"]["formula"] == "number of finite values"
    assert pooling["sum"]["empty_value"] == 0.0
    assert pooling["standard_deviation"]["ddof"] == 0
    assert pooling["quantiles"] == {
        "probabilities": [0.25, 0.5, 0.75],
        "method": "linear",
    }
    assert pooling["missing_count"]["formula"] == "total count minus finite count"
    assert pooling["empty_or_all_missing"] == {
        "count": 0,
        "sum": 0.0,
        "mean_std_minimum_maximum_quantiles": None,
        "missing_count": "total count",
    }

    trajectory = manifest["trajectory_contract"]
    assert trajectory["windows_minutes"] == [5, 15, 30, 60]
    assert trajectory["window_interval"] == "[origin - window, origin)"
    assert trajectory["hold"] == {
        "method": "left-continuous",
        "cap_seconds": 12,
        "next_sample_also_ends_hold": True,
    }
    assert trajectory["sample_at_origin"] == "excluded"
    assert trajectory["current_mean"]["denominator"] == "covered current seconds"
    assert trajectory["current_standard_deviation"] == {
        "formula": "time-weighted population standard deviation of held current",
        "denominator": "covered current seconds",
        "ddof": 0,
    }
    assert trajectory["current_nonzero_fraction"] == {
        "formula": "covered seconds with nonzero held current divided by coverage",
        "condition": "held current != 0.0 A",
        "denominator": "covered current seconds",
    }
    assert trajectory["current_maximum"]["formula"].startswith("maximum held current")
    assert trajectory["current_minimum"]["formula"].startswith("minimum held current")
    assert trajectory["current_observed_ratio"]["denominator"] == "full window seconds"
    assert trajectory["slope"] == {
        "formula": "(last current - first current) * 60 / (last timestamp - first timestamp)",
        "minimum_distinct_timestamps": 2,
        "unit": "A/min",
    }
    assert trajectory["gap"] == {
        "definition": "pilot - current",
        "coverage": "joint held coverage",
        "weighted_mean_denominator": "joint-covered seconds",
        "maximum": "maximum over joint-covered seconds",
        "negative_values_clipped": False,
    }

    assert manifest["ordering_contract"] == {
        "M1": "history oldest-to-newest, masks oldest-to-newest, calendar",
        "M2": "M1 then aggregate state",
        "M3": "M2 then field then pool statistic",
        "M4": "M3 then window then session statistic then pool statistic",
    }
    assert manifest["privacy_audit"] == {
        "status": "PASS",
        "row_index_used_as_model_feature": False,
        "structural_join_keys_used_as_model_features": False,
        "single_session_values_published": False,
        "local_paths_published": False,
    }
    assert manifest["legacy_active_reference_audit"] == {
        "role": "audit only",
        "threshold_a": 0.1,
        "comparison": "finite current strictly greater than threshold",
        "model_cohort": "all connected sessions",
        "identifiers_published": False,
    }
    assert "current_nonzero_fraction" in manifest["m4_session_statistic_order"]
    assert not any("gt_0_1a" in item["name"] for item in manifest["tiers"]["M4"]["features"])


def test_manifest_rejects_fake_schema_index_mask_and_nonprefix_blocks() -> None:
    snapshot = _snapshot()
    accumulator = M4FeatureAccumulator(issue_count=3)
    _consume_snapshot(accumulator, snapshot)
    canonical = dict(build_feature_blocks(snapshot, accumulator))

    m1 = canonical["M1"]
    extra_values = np.column_stack((m1.values, np.zeros(len(m1.issue_times))))
    extra = FeatureBlock(
        m1.issue_times,
        extra_values,
        m1.feature_names + ("fake_column",),
        np.append(m1.nullable_mask, False),
    )
    bad_width = dict(canonical)
    bad_width["M1"] = extra

    m2 = canonical["M2"]
    swapped_names = list(m2.feature_names)
    swapped_names[-1], swapped_names[-2] = swapped_names[-2], swapped_names[-1]
    bad_order = dict(canonical)
    bad_order["M2"] = FeatureBlock(
        m2.issue_times, m2.values, tuple(swapped_names), m2.nullable_mask
    )

    wrong_mask = m2.nullable_mask.copy()
    wrong_mask[-1] = False
    bad_mask = dict(canonical)
    bad_mask["M2"] = FeatureBlock(m2.issue_times, m2.values, m2.feature_names, wrong_mask)

    m3 = canonical["M3"]
    bad_index = dict(canonical)
    bad_index["M3"] = FeatureBlock(
        m3.issue_times + 1, m3.values, m3.feature_names, m3.nullable_mask
    )

    bad_prefix = dict(canonical)
    bad_prefix["M4"] = _changed_block(canonical["M4"])

    wrong_tier_order = {
        "M2": canonical["M2"],
        "M1": canonical["M1"],
        "M3": canonical["M3"],
        "M4": canonical["M4"],
    }
    for malformed in (
        bad_width,
        bad_order,
        bad_mask,
        bad_index,
        bad_prefix,
        wrong_tier_order,
    ):
        with pytest.raises(ValueError):
            feature_encoding_manifest(malformed)


def test_real_jpl_feature_encoding_is_complete_when_present() -> None:
    processed = Path("data/processed/acn/jpl/2019-05")
    interim = Path("data/interim/acn/jpl/2019-05")
    if not (processed / "data_snapshot_manifest.json").is_file():
        pytest.skip("local ignored JPL snapshot is absent")

    accumulator = M4FeatureAccumulator()
    snapshot = verify_and_load_snapshot(processed, interim, causal_prefix_consumer=accumulator)
    blocks = build_feature_blocks(snapshot, accumulator)

    provenance = {
        tier: verified_feature_block_provenance(block, snapshot, tier=tier)
        for tier, block in blocks.items()
    }
    assert len(set(provenance.values())) == 4
    changed = replace(blocks["M1"], values=blocks["M1"].values.copy())
    with pytest.raises(ValueError, match="verified|seal|encoder"):
        verified_feature_block_provenance(changed, snapshot, tier="M1")

    assert len(snapshot.m3_rows) == accumulator.computed_pair_count == 43_506
    assert len(snapshot.m4_rows) == 22_427
    assert accumulator.peak_temporary_session_count <= 52
    assert sum(not group for group in snapshot.m3_by_issue_time) == 699
    assert {tier: block.values.shape for tier, block in blocks.items()} == {
        "M1": (2_853, 195),
        "M2": (2_853, 201),
        "M3": (2_853, 311),
        "M4": (2_853, 671),
    }
    train = slice(0, 1_248)
    for block in blocks.values():
        nullable = block.values[train][:, block.nullable_mask]
        assert np.all(np.isfinite(nullable).any(axis=0))


def test_synthetic_feature_blocks_cannot_claim_verified_encoder_provenance() -> None:
    snapshot = _snapshot()
    accumulator = M4FeatureAccumulator(issue_count=3)
    _consume_snapshot(accumulator, snapshot)
    blocks = build_feature_blocks(snapshot, accumulator)
    for tier, block in blocks.items():
        with pytest.raises(ValueError, match="verified|seal|loader"):
            verified_feature_block_provenance(block, snapshot, tier=tier)


def test_m4_encoder_rejects_polymorphic_accumulator_override() -> None:
    class ForgedAccumulator(M4FeatureAccumulator):
        def encode(self, snapshot: Gate1Snapshot) -> np.ndarray:
            return np.zeros((len(snapshot.issue_times), 360), dtype=np.float64)

    snapshot = _snapshot()
    accumulator = ForgedAccumulator(issue_count=3)
    _consume_snapshot(accumulator, snapshot)
    with pytest.raises(TypeError, match="exact|M4FeatureAccumulator"):
        encode_m4(snapshot, accumulator)
