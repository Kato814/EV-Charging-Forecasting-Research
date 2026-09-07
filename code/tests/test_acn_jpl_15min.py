from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest
from evcf.data.acn_jpl_15min import (
    AggregationPolicy,
    aggregate_station_15min,
    build_local_15min_grid,
)
from evcf.data.acn_jpl_month_config import SEASONAL_MONTHS, jpl_month_config

LA = ZoneInfo("America/Los_Angeles")


def _epoch(value: datetime) -> int:
    return int(value.timestamp())


def _series(times: list[datetime], values: list[float]) -> dict[str, object]:
    return {
        "timestamps_utc_s": [_epoch(value) for value in times],
        "values": values,
    }


def _session(
    connection: datetime,
    disconnect: datetime,
    *,
    current_times: list[datetime],
    current_values: list[float],
    pilot_times: list[datetime] | None = None,
    pilot_values: list[float] | None = None,
) -> dict[str, object]:
    return {
        "connection_utc_s": _epoch(connection),
        "disconnect_utc_s": _epoch(disconnect),
        "current": _series(current_times, current_values),
        "pilot": _series(
            current_times if pilot_times is None else pilot_times,
            current_values if pilot_values is None else pilot_values,
        ),
    }


def test_may_local_grid_has_2976_dst_safe_bins() -> None:
    start = datetime(2019, 5, 1, tzinfo=LA)
    end = datetime(2019, 6, 1, tzinfo=LA)

    grid = build_local_15min_grid(start, end)

    assert len(grid) == 2976
    assert grid[0].start_utc == datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    assert grid[-1].end_utc == datetime(2019, 6, 1, 7, tzinfo=timezone.utc)
    assert grid[0].local_date == "2019-05-01"
    assert grid[0].quarter_hour_index == 0
    assert grid[-1].local_date == "2019-05-31"
    assert grid[-1].quarter_hour_index == 95


@pytest.mark.parametrize(
    ("month", "expected_bins"),
    tuple(zip(SEASONAL_MONTHS, (2688, 2976, 2884), strict=True)),
)
def test_seasonal_grid_is_a_continuous_physical_utc_grid(
    month: str,
    expected_bins: int,
) -> None:
    config = jpl_month_config(month)

    grid = build_local_15min_grid(config.local_start, config.local_end)

    assert len(grid) == expected_bins == config.expected_bins
    assert grid[0].start_utc == config.utc_start
    assert grid[-1].end_utc == config.utc_end
    assert all(
        right.start_utc - left.start_utc == timedelta(seconds=900) for left, right in pairwise(grid)
    )


def test_november_fall_back_keeps_eight_physical_one_am_bins() -> None:
    config = jpl_month_config("2019-11")

    grid = build_local_15min_grid(config.local_start, config.local_end)
    repeated_hour = [
        interval
        for interval in grid
        if interval.local_date == "2019-11-03" and interval.timestamp_local.hour == 1
    ]

    assert len(grid) == 30 * 96 + 4
    assert len(repeated_hour) == 8
    assert {interval.timestamp_local.utcoffset() for interval in repeated_hour} == {
        timedelta(hours=-7),
        timedelta(hours=-8),
    }
    assert all(
        interval.end_utc - interval.start_utc == timedelta(seconds=900)
        for interval in repeated_hour
    )
    assert [interval.quarter_hour_index for interval in repeated_hour] == [
        4,
        5,
        6,
        7,
        4,
        5,
        6,
        7,
    ]
    assert [interval.timestamp_local.fold for interval in repeated_hour] == [0] * 4 + [1] * 4


def test_november_aggregation_publishes_explicit_physical_grid_qa() -> None:
    config = jpl_month_config("2019-11")

    result = aggregate_station_15min(
        [],
        start_utc=config.utc_start,
        end_utc=config.utc_end,
        policy=AggregationPolicy(max_hold_seconds=12),
        grid_policy=config.grid_policy,
    )

    assert result.qa["expected_bins"] == 2884
    assert result.qa["grid_policy"] == "continuous_physical_utc"
    assert result.qa["dst_fold_extra_bins"] == 4
    assert result.qa["repeated_local_quarter_count"] == 4
    assert result.qa["time_weighted_integral_status"] == "PASS"
    for threshold in (80, 90, 95):
        valid = result.qa[f"valid_bins_at_{threshold}"]
        assert valid / result.qa["generated_bins"] == 1.0
        assert 1 - valid / result.qa["generated_bins"] == 0.0
        assert result.qa[f"valid_bin_rate_at_{threshold}"] == 1.0
        assert result.qa[f"missing_bin_rate_at_{threshold}"] == 0.0


def test_current_and_pilot_use_independent_bounded_holds() -> None:
    start = datetime(2019, 2, 1, 8, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)
    session = _session(
        start,
        end,
        current_times=[start],
        current_values=[2.0],
        pilot_times=[start],
        pilot_values=[8.0],
    )

    result = aggregate_station_15min(
        [session],
        start_utc=start,
        end_utc=end,
        policy=AggregationPolicy(max_hold_seconds=3, pilot_max_hold_seconds=12),
    )

    assert result.rows[0]["observed_coverage_ratio"] == pytest.approx(3 / 900, abs=1e-8)
    assert result.rows[0]["pilot_observed_coverage_ratio"] == pytest.approx(12 / 900, abs=1e-8)


def test_legacy_aggregation_qa_does_not_gain_seasonal_grid_fields() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    result = aggregate_station_15min(
        [],
        start_utc=start,
        end_utc=start + timedelta(minutes=15),
        policy=AggregationPolicy(max_hold_seconds=12),
    )

    assert {
        "grid_policy",
        "dst_fold_extra_bins",
        "repeated_local_quarter_count",
        "time_weighted_integral_status",
    }.isdisjoint(result.qa)


def test_time_weighted_current_is_not_a_sample_average_and_gap_is_uncovered() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)
    session = _session(
        start,
        end,
        current_times=[start, start + timedelta(seconds=100)],
        current_values=[10.0, 20.0],
    )

    result = aggregate_station_15min(
        [session],
        start_utc=start,
        end_utc=end,
        policy=AggregationPolicy(max_hold_seconds=800),
        grid_policy="continuous_physical_utc",
    )

    row = result.rows[0]
    assert row["station_current_mean_a"] == pytest.approx(17000 / 900)
    assert row["station_current_mean_a"] != pytest.approx(15.0)
    assert row["observed_coverage_ratio"] == pytest.approx(1.0)
    assert row["valid_bin_80"] is True
    assert row["valid_bin_90"] is True
    assert row["valid_bin_95"] is True
    assert result.qa["time_weighted_integral_status"] == "PASS"


def test_partial_observation_is_not_published_as_main_mean() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)
    session = _session(
        start,
        end,
        current_times=[start],
        current_values=[10.0],
    )

    result = aggregate_station_15min(
        [session],
        start_utc=start,
        end_utc=end,
        policy=AggregationPolicy(max_hold_seconds=12),
    )

    assert result.rows[0]["observed_coverage_ratio"] == pytest.approx(12 / 900)
    assert result.rows[0]["station_current_mean_a"] is None
    assert result.rows[0]["station_current_peak_a"] is None


def test_partial_pilot_observation_is_explicitly_missing() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)
    sample_times = [start + timedelta(seconds=offset) for offset in range(0, 900, 10)]
    session = _session(
        start,
        end,
        current_times=sample_times,
        current_values=[2.0] * len(sample_times),
        pilot_times=[start],
        pilot_values=[8.0],
    )

    result = aggregate_station_15min(
        [session],
        start_utc=start,
        end_utc=end,
        policy=AggregationPolicy(max_hold_seconds=10),
    )

    row = result.rows[0]
    assert row["observed_coverage_ratio"] == 1.0
    assert row["pilot_observed_coverage_ratio"] == pytest.approx(10 / 900)
    assert row["pilot_sum_a"] is None
    assert row["pilot_mean_a"] is None


def test_no_observation_is_missing_while_empty_station_is_zero() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(minutes=30)
    connected_without_observations = _session(
        start,
        start + timedelta(minutes=15),
        current_times=[],
        current_values=[],
    )

    result = aggregate_station_15min(
        [connected_without_observations],
        start_utc=start,
        end_utc=end,
        policy=AggregationPolicy(max_hold_seconds=12),
    )

    first, second = result.rows
    assert first["station_current_mean_a"] is None
    assert first["station_current_peak_a"] is None
    assert first["observed_coverage_ratio"] == 0.0
    assert second["station_current_mean_a"] == 0.0
    assert second["station_current_peak_a"] == 0.0
    assert second["observed_coverage_ratio"] == 1.0


def test_carry_in_contributes_but_disconnect_boundary_does_not() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)
    sample_times = [start + timedelta(seconds=offset) for offset in range(0, 900, 10)]
    carry = _session(
        start - timedelta(hours=1),
        end,
        current_times=sample_times + [end],
        current_values=[2.0] * len(sample_times) + [999.0],
    )

    result = aggregate_station_15min(
        [carry],
        start_utc=start,
        end_utc=end,
        policy=AggregationPolicy(max_hold_seconds=10),
    )

    row = result.rows[0]
    assert row["arrival_count"] == 0
    assert row["disconnect_count"] == 0
    assert row["station_current_mean_a"] == pytest.approx(2.0)
    assert row["station_current_peak_a"] == pytest.approx(2.0)
    assert row["observed_coverage_ratio"] == pytest.approx(1.0)


def test_active_thresholds_and_coverage_sensitivities_are_explicit() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)
    sample_times = [start + timedelta(seconds=offset) for offset in range(0, 900, 10)]
    low = _session(
        start,
        end,
        current_times=sample_times,
        current_values=[0.5] * len(sample_times),
    )

    result = aggregate_station_15min(
        [low],
        start_utc=start,
        end_utc=end,
        policy=AggregationPolicy(max_hold_seconds=10, main_active_threshold_a=0.1),
    )

    row = result.rows[0]
    assert row["active_charging_session_count"] == 1
    assert row["active_charging_session_count_gt_1a"] == 0
    assert row["valid_bin_80"] is True
    assert row["valid_bin_90"] is True
    assert row["valid_bin_95"] is True
    assert result.qa["active_threshold_sensitivity"]["main_threshold_a"] == 0.1
    assert result.qa["active_threshold_sensitivity"]["comparison_threshold_a"] == 1.0


@pytest.mark.parametrize("missing_branch", ["current", "pilot", "both"])
@pytest.mark.parametrize("observed_count", [10, 20])
def test_known_missing_branch_cannot_hide_in_high_concurrency_coverage(
    missing_branch: str,
    observed_count: int,
) -> None:
    start = datetime(2019, 2, 1, 8, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)
    times = [start + timedelta(seconds=offset) for offset in range(0, 900, 60)]
    observed = _session(
        start,
        end,
        current_times=times,
        current_values=[10.0] * 15,
        pilot_times=times,
        pilot_values=[12.0] * 15,
    )
    missing = _session(
        start,
        end,
        current_times=[] if missing_branch in ("current", "both") else times,
        current_values=[] if missing_branch in ("current", "both") else [10.0] * 15,
        pilot_times=[] if missing_branch in ("pilot", "both") else times,
        pilot_values=[] if missing_branch in ("pilot", "both") else [12.0] * 15,
    )
    result = aggregate_station_15min(
        [observed] * observed_count + [missing],
        start_utc=start,
        end_utc=end,
        policy=AggregationPolicy(max_hold_seconds=60),
        enforce_known_incomplete_current=True,
    )
    row = result.rows[0]
    missing_current = missing_branch in ("current", "both")
    missing_pilot = missing_branch in ("pilot", "both")
    assert row["connected_session_count"] == observed_count + 1
    assert row["arrival_count"] == observed_count + 1
    assert row["observed_coverage_ratio"] >= 0.90
    assert row["pilot_observed_coverage_ratio"] >= 0.90
    assert row["known_incomplete_current"] is missing_current
    assert row["known_incomplete_pilot"] is missing_pilot
    assert row["valid_bin_90"] is not missing_current
    assert row["station_current_mean_a"] == (
        None if missing_current else 10.0 * (observed_count + 1)
    )
    assert row["station_current_peak_a"] == (
        None if missing_current else 10.0 * (observed_count + 1)
    )
    assert row["pilot_sum_a"] == (None if missing_pilot else 12.0 * (observed_count + 1))
    assert row["pilot_mean_a"] == (None if missing_pilot else 12.0)
    assert result.qa["coverage_only_valid_bins_at_90"] == 1
    assert result.qa["known_incomplete_current_excluded_bins_at_90"] == int(missing_current)
    assert result.qa["known_incomplete_current_bins"] == int(missing_current)
    assert result.qa["known_incomplete_pilot_bins"] == int(missing_pilot)
    assert result.qa["valid_bins_at_90"] == int(not missing_current)
    for threshold in (80, 90, 95):
        coverage_passes = row["observed_coverage_ratio"] >= threshold / 100
        assert row[f"valid_bin_{threshold}"] is (coverage_passes and not missing_current)
        assert result.qa[f"coverage_only_valid_bins_at_{threshold}"] == int(coverage_passes)
        assert result.qa[f"known_incomplete_current_excluded_bins_at_{threshold}"] == int(
            coverage_passes and missing_current
        )


def test_known_missing_is_half_open_preserves_carry_in_and_is_not_observed_zero() -> None:
    start = datetime(2019, 2, 1, 8, tzinfo=timezone.utc)
    missing = _session(
        start - timedelta(hours=1),
        start + timedelta(minutes=15),
        current_times=[],
        current_values=[],
    )
    observed_zero = _session(
        start + timedelta(minutes=15),
        start + timedelta(minutes=30),
        current_times=[start + timedelta(minutes=15)],
        current_values=[0.0],
    )
    result = aggregate_station_15min(
        [missing, observed_zero],
        start_utc=start,
        end_utc=start + timedelta(minutes=45),
        policy=AggregationPolicy(max_hold_seconds=900),
        enforce_known_incomplete_current=True,
    )
    unknown, zero, empty = result.rows
    assert [row["known_incomplete_current"] for row in result.rows] == [True, False, False]
    assert unknown["station_current_mean_a"] is None
    assert unknown["connected_session_count"] == 1
    assert unknown["observed_coverage_ratio"] == 0.0
    assert unknown["arrival_count"] == 0
    assert zero["station_current_mean_a"] == 0.0
    assert zero["connected_session_count"] == 1
    assert zero["observed_coverage_ratio"] == 1.0
    assert zero["disconnect_count"] == 1
    assert empty["station_current_mean_a"] == 0.0
    assert empty["connected_session_count"] == 0
    assert empty["known_incomplete_pilot"] is False


def test_known_missing_uses_integral_state_and_not_future_samples_for_labels() -> None:
    start = datetime(2019, 2, 1, 8, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)
    session = _session(start, end, current_times=[end], current_values=[999.0])
    session["current"]["main_integral"] = {"observed_seconds": 0}
    session["pilot"]["main_integral"] = {"observed_seconds": 0}
    result = aggregate_station_15min(
        [session],
        start_utc=start,
        end_utc=end,
        policy=AggregationPolicy(max_hold_seconds=60),
        enforce_known_incomplete_current=True,
    )
    assert result.rows[0]["known_incomplete_current"] is True
    assert result.rows[0]["station_current_mean_a"] is None


def test_opt_in_preserves_anomaly_free_numeric_output_and_may_default_schema() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(minutes=15)
    session = _session(start, end, current_times=[start], current_values=[2.0])
    kwargs = {
        "start_utc": start,
        "end_utc": end,
        "policy": AggregationPolicy(max_hold_seconds=900),
    }
    legacy = aggregate_station_15min([session], **kwargs)
    explicit_default = aggregate_station_15min(
        [session], **kwargs, enforce_known_incomplete_current=False
    )
    seasonal = aggregate_station_15min([session], **kwargs, enforce_known_incomplete_current=True)
    assert explicit_default == legacy
    assert {key: seasonal.rows[0][key] for key in legacy.rows[0]} == legacy.rows[0]
    assert "known_incomplete_current" not in legacy.rows[0]
    assert "known_incomplete_current_bins" not in legacy.qa
    for threshold in (80, 90, 95):
        assert seasonal.qa[f"valid_bins_at_{threshold}"] == legacy.qa[f"valid_bins_at_{threshold}"]


@pytest.mark.parametrize("value", [None, 0, 1, "true"])
def test_known_missing_opt_in_requires_boolean(value: object) -> None:
    start = datetime(2019, 2, 1, 8, tzinfo=timezone.utc)
    with pytest.raises(TypeError, match="enforce_known_incomplete_current"):
        aggregate_station_15min(
            [],
            start_utc=start,
            end_utc=start + timedelta(minutes=15),
            policy=AggregationPolicy(max_hold_seconds=60),
            enforce_known_incomplete_current=value,
        )


def test_required_schema_and_summary_are_deterministic() -> None:
    start = datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    end = start + timedelta(minutes=30)
    result = aggregate_station_15min(
        [],
        start_utc=start,
        end_utc=end,
        policy=AggregationPolicy(max_hold_seconds=12),
    )

    required = {
        "timestamp_utc",
        "timestamp_local",
        "local_date",
        "quarter_hour_index",
        "day_of_week",
        "is_weekend",
        "station_current_mean_a",
        "station_current_peak_a",
        "connected_session_count",
        "active_charging_session_count",
        "active_charging_session_count_gt_1a",
        "pilot_sum_a",
        "pilot_mean_a",
        "arrival_count",
        "disconnect_count",
        "observed_coverage_ratio",
        "pilot_observed_coverage_ratio",
        "valid_bin_90",
        "valid_bin_80",
        "valid_bin_95",
    }
    assert set(result.rows[0]) == required
    assert result.qa["generated_bins"] == 2
    assert result.qa["valid_bins_at_90"] == 2
    assert result.qa["missing_bin_rate"] == 0.0
    assert result.qa["longest_missing_run"] == 0
    assert (
        result.rows
        == aggregate_station_15min(
            [],
            start_utc=start,
            end_utc=end,
            policy=AggregationPolicy(max_hold_seconds=12),
        ).rows
    )
