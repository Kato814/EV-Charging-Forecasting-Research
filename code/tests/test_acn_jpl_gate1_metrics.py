from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from evcf.evaluation.acn_jpl_gate1_metrics import (
    BootstrapPlan,
    EvaluationSeries,
    ExecutionFailureCode,
    Gate1EvaluationResult,
    GateEvidence,
    assert_public_payload_safe,
    bootstrap_tier_comparison,
    build_public_aggregate_payload,
    classify_gate,
    compare_adjacent_tiers,
    compute_error_metrics,
    compute_peak_ramp_metrics,
    evaluate_gate1,
    evaluate_scopes,
)
from evcf.forecasting.acn_jpl_gate1_models import PersistencePrediction, PredictionBundle

ZONE = ZoneInfo("America/Los_Angeles")
HORIZONS = (15, 30, 60, 120, 240)
NEAR_HORIZONS = (15, 30, 60)


def _epoch(local_iso: str) -> int:
    return int(datetime.fromisoformat(local_iso).timestamp())


def _formal_small_index(*, rows_per_day: int = 2, final_day_rows: int | None = None):
    times: list[int] = []
    day_starts: list[int] = []
    for offset in range(14):
        day = datetime(2019, 5, 18, tzinfo=ZONE) + timedelta(days=offset)
        count = final_day_rows if offset == 13 and final_day_rows is not None else rows_per_day
        for position in range(count):
            times.append(int((day + timedelta(minutes=15 * position)).timestamp()))
            day_starts.append(int(day.timestamp()))
    return np.asarray(times, dtype=np.int64), np.asarray(day_starts, dtype=np.int64)


def _learned_series(
    tier: str,
    predictions: np.ndarray,
    *,
    learner: str = "hgb",
    horizon: int = 15,
    y_true: np.ndarray | None = None,
    issue_times: np.ndarray | None = None,
    day_starts: np.ndarray | None = None,
) -> EvaluationSeries:
    if issue_times is None or day_starts is None:
        issue_times, day_starts = _formal_small_index()
    if y_true is None:
        y_true = np.ones(len(issue_times), dtype=np.float64)
    bundle = PredictionBundle.create(
        learner=learner,
        tier=tier,
        horizon_minutes=horizon,
        issue_times=issue_times,
        y_true=y_true,
        predictions=predictions,
        day_start_utc_s=day_starts,
        selected_param_sha256="a" * 64,
    )
    return EvaluationSeries.from_prediction_bundle(bundle)


def _canonical_evaluation_series(
    *,
    hgb_mae_by_tier: dict[str, tuple[float, float, float, float, float]] | None = None,
    m3_daily_delta_by_horizon: dict[int, np.ndarray] | None = None,
) -> tuple[EvaluationSeries, ...]:
    """Build the complete 55-series frozen test cohort without fitting models."""

    issue_times, day_starts = _formal_small_index(rows_per_day=96, final_day_rows=81)
    hgb_mae = hgb_mae_by_tier or {
        "M1": (101.0, 101.0, 101.0, 101.0, 101.0),
        "M2": (100.0, 100.0, 100.0, 100.0, 100.0),
        "M3": (97.0, 97.0, 102.0, 99.0, 99.0),
        "M4": (95.0, 95.0, 103.0, 98.0, 98.0),
    }
    output: list[EvaluationSeries] = []
    unique_days = np.unique(day_starts)
    for learner in ("ridge", "hgb"):
        for tier_index, tier in enumerate(("M1", "M2", "M3", "M4")):
            for horizon_index, horizon in enumerate(HORIZONS):
                truth = np.full(len(issue_times), 1_000.0 + horizon, dtype=np.float64)
                if learner == "hgb":
                    errors = np.full(
                        len(issue_times), hgb_mae[tier][horizon_index], dtype=np.float64
                    )
                    if (
                        tier == "M3"
                        and m3_daily_delta_by_horizon is not None
                        and horizon in m3_daily_delta_by_horizon
                    ):
                        daily_delta = np.asarray(m3_daily_delta_by_horizon[horizon])
                        assert daily_delta.shape == (14,)
                        parent_error = hgb_mae["M2"][horizon_index]
                        for day, delta in zip(unique_days, daily_delta, strict=True):
                            errors[day_starts == day] = parent_error - float(delta)
                else:
                    errors = np.full(
                        len(issue_times),
                        110.0 - 2.0 * tier_index + horizon_index,
                        dtype=np.float64,
                    )
                output.append(
                    _learned_series(
                        tier,
                        truth + errors,
                        learner=learner,
                        horizon=horizon,
                        y_true=truth,
                        issue_times=issue_times,
                        day_starts=day_starts,
                    )
                )

    for baseline_index, baseline in enumerate(("last_value", "previous_day", "previous_week")):
        for horizon in HORIZONS:
            truth = np.full(len(issue_times), 1_000.0 + horizon, dtype=np.float64)
            available = np.ones(len(issue_times), dtype=np.bool_)
            if baseline == "previous_week":
                available[:3] = False
            predictions = truth + 120.0 + baseline_index
            predictions[~available] = np.nan
            output.append(
                EvaluationSeries.create(
                    model_kind="persistence",
                    learner=None,
                    tier=None,
                    baseline=baseline,
                    horizon_minutes=horizon,
                    issue_times=issue_times,
                    day_start_utc_s=day_starts,
                    y_true=truth,
                    predictions=predictions,
                    availability=available,
                )
            )
    return tuple(output)


@pytest.fixture(scope="module")
def canonical_result() -> Gate1EvaluationResult:
    return evaluate_gate1(_canonical_evaluation_series())


def test_exact_error_metrics_zero_wape_and_nominal_208v() -> None:
    metrics = compute_error_metrics(
        np.asarray([0.0, 2.0]),
        np.asarray([1.0, 4.0]),
    )

    assert metrics.n_total == 2
    assert metrics.n_available == 2
    assert metrics.coverage_ratio == 1.0
    assert metrics.mae_a == pytest.approx(1.5)
    assert metrics.rmse_a == pytest.approx(math.sqrt(2.5))
    assert metrics.wape_ratio == pytest.approx(1.5)
    assert metrics.wape_status == "defined"
    assert metrics.nominal_208v_reconstructed_mae_kw == pytest.approx(0.208 * 1.5)
    assert metrics.nominal_208v_reconstructed_rmse_kw == pytest.approx(0.208 * math.sqrt(2.5))

    zero = compute_error_metrics(np.zeros(2), np.asarray([1.0, -1.0]))
    assert zero.mae_a == 1.0
    assert zero.wape_ratio is None
    assert zero.wape_status == "undefined_zero_actual_absolute_sum"
    json.dumps(zero.to_public_dict(), allow_nan=False, sort_keys=True)


def test_error_metrics_exclude_only_explicit_unavailable_rows() -> None:
    metrics = compute_error_metrics(
        np.asarray([1.0, 2.0, 3.0]),
        np.asarray([2.0, np.nan, 7.0]),
        availability=np.asarray([True, False, True]),
    )

    assert metrics.n_total == 3
    assert metrics.n_available == 2
    assert metrics.coverage_ratio == pytest.approx(2 / 3)
    assert metrics.mae_a == pytest.approx(2.5)
    with pytest.raises(ValueError, match="unavailable|NaN"):
        compute_error_metrics(np.ones(2), np.asarray([1.0, np.nan]))
    with pytest.raises(ValueError, match="exactly"):
        compute_error_metrics(
            np.ones(2),
            np.asarray([1.0, 2.0]),
            availability=np.asarray([True, False]),
        )


def test_daily_weekday_weekend_are_issue_day_micro_averages() -> None:
    issue_times, day_starts = _formal_small_index(rows_per_day=2, final_day_rows=1)
    y_true = np.ones(len(issue_times), dtype=np.float64)
    errors = np.arange(1, len(issue_times) + 1, dtype=np.float64)
    series = _learned_series(
        "M1",
        y_true + errors,
        y_true=y_true,
        issue_times=issue_times,
        day_starts=day_starts,
    )
    scoped = evaluate_scopes(series)

    weekday = np.asarray(
        [
            datetime.fromtimestamp(int(day), timezone.utc).astimezone(ZONE).weekday() < 5
            for day in day_starts
        ]
    )
    assert len(scoped.daily) == 14
    assert scoped.weekday.n_total == 19
    assert scoped.weekend.n_total == 8
    assert scoped.weekday.mae_a == pytest.approx(float(np.mean(errors[weekday])))
    assert scoped.weekend.mae_a == pytest.approx(float(np.mean(errors[~weekday])))
    assert scoped.overall.mae_a == pytest.approx(float(np.mean(errors)))
    assert scoped.daily[-1].metrics.n_total == 1


def test_persistence_series_keeps_unavailable_rows_explicit() -> None:
    issue_times = np.asarray(
        [
            _epoch("2019-05-18T00:00:00-07:00"),
            _epoch("2019-05-18T00:15:00-07:00"),
            _epoch("2019-05-18T00:30:00-07:00"),
        ],
        dtype=np.int64,
    )
    day_starts = np.full(3, _epoch("2019-05-18T00:00:00-07:00"), dtype=np.int64)
    persistence = PersistencePrediction(
        name="previous_week",
        horizon_minutes=15,
        issue_times=issue_times,
        predictions=np.asarray([2.0, np.nan, 4.0]),
        availability=np.asarray([True, False, True]),
        reference_times=issue_times - 7 * 86_400,
    )
    series = EvaluationSeries.from_persistence_prediction(
        persistence,
        y_true=np.asarray([1.0, 99.0, 3.0]),
        day_start_utc_s=day_starts,
    )
    metrics = evaluate_scopes(series)

    assert metrics.overall.n_available == 2
    assert metrics.overall.mae_a == 1.0
    assert metrics.daily[0].metrics.coverage_ratio == pytest.approx(2 / 3)
    assert "reference" not in json.dumps(metrics.to_public_dict()).lower()


def test_evaluation_factory_does_not_coerce_schema_types() -> None:
    issue_times, day_starts = _formal_small_index()
    values = np.ones(len(issue_times))
    with pytest.raises(ValueError, match="int64"):
        EvaluationSeries.create(
            model_kind="learned",
            learner="hgb",
            tier="M1",
            baseline=None,
            horizon_minutes=15,
            issue_times=issue_times.astype(np.float64),
            day_start_utc_s=day_starts,
            y_true=values,
            predictions=values,
            availability=np.ones(len(issue_times), dtype=np.bool_),
        )
    with pytest.raises(ValueError, match="boolean"):
        EvaluationSeries.create(
            model_kind="learned",
            learner="hgb",
            tier="M1",
            baseline=None,
            horizon_minutes=15,
            issue_times=issue_times,
            day_start_utc_s=day_starts,
            y_true=values,
            predictions=values,
            availability=np.ones(len(issue_times), dtype=np.int64),
        )


def test_peak_uses_earliest_target_bin_and_ramp_never_crosses_boundaries() -> None:
    issue_times = np.asarray(
        [
            _epoch("2019-05-18T00:00:00-07:00"),
            _epoch("2019-05-18T00:15:00-07:00"),
            _epoch("2019-05-18T00:30:00-07:00"),
            _epoch("2019-05-18T01:00:00-07:00"),
            _epoch("2019-05-19T00:00:00-07:00"),
            _epoch("2019-05-19T00:15:00-07:00"),
        ],
        dtype=np.int64,
    )
    day_starts = np.asarray(
        [_epoch("2019-05-18T00:00:00-07:00")] * 4 + [_epoch("2019-05-19T00:00:00-07:00")] * 2,
        dtype=np.int64,
    )
    y_true = np.asarray([1.0, 5.0, 5.0, 0.0, 1.0, 2.0])
    predictions = np.asarray([7.0, 7.0, 1.0, 0.0, 1.0, 4.0])
    series = _learned_series(
        "M2",
        predictions,
        horizon=60,
        y_true=y_true,
        issue_times=issue_times,
        day_starts=day_starts,
    )
    result = compute_peak_ramp_metrics(series)

    first = result.daily_peak[0]
    assert first.peak_amplitude_error_a == 2.0
    assert first.peak_time_error_minutes == 15.0
    assert first.actual_peak_target_time_utc_s == issue_times[1] + 60 * 60 - 900
    assert first.predicted_peak_target_time_utc_s == issue_times[0] + 60 * 60 - 900
    # Day one contributes two contiguous pairs; the 30-minute gap is excluded.
    # Day two contributes one pair; the day boundary is excluded.
    assert result.ramp_pair_count == 3
    expected = np.asarray([4.0, 6.0, 2.0])
    assert result.ramp_mae_a == pytest.approx(float(np.mean(expected)))
    assert result.max_ramp_error_a == 6.0


def test_incomplete_prediction_day_has_no_peak_metric_and_breaks_ramps() -> None:
    issue_times, day_starts = _formal_small_index()
    y_true = np.ones(len(issue_times), dtype=np.float64)
    predictions = y_true.copy()
    available = np.ones(len(issue_times), dtype=np.bool_)
    available[3] = False
    predictions[3] = np.nan
    series = EvaluationSeries.create(
        model_kind="persistence",
        learner=None,
        tier=None,
        baseline="previous_week",
        horizon_minutes=15,
        issue_times=issue_times,
        day_start_utc_s=day_starts,
        y_true=y_true,
        predictions=predictions,
        availability=available,
    )
    result = compute_peak_ramp_metrics(series)

    assert result.complete_peak_days == 13
    assert result.daily_peak[1].status == "incomplete_prediction_day"
    assert result.daily_peak[1].peak_amplitude_error_a is None
    assert result.ramp_pair_count == 13


def test_adjacent_tier_comparison_is_paired_and_positive_means_child_wins() -> None:
    issue_times, day_starts = _formal_small_index()
    y_true = np.full(len(issue_times), 10.0)
    parent = _learned_series(
        "M2",
        np.full(len(issue_times), 12.0),
        y_true=y_true,
        issue_times=issue_times,
        day_starts=day_starts,
    )
    child = _learned_series(
        "M3",
        np.full(len(issue_times), 11.0),
        y_true=y_true,
        issue_times=issue_times,
        day_starts=day_starts,
    )
    comparison = compare_adjacent_tiers(parent, child)

    assert comparison.parent_mae_a == 2.0
    assert comparison.child_mae_a == 1.0
    assert comparison.mean_absolute_error_delta_a == 1.0
    assert comparison.relative_improvement_percent == 50.0
    assert len(comparison.daily) == 14
    assert all(day.absolute_error_delta_a == 1.0 for day in comparison.daily)

    wrong_truth = _learned_series(
        "M3",
        np.full(len(issue_times), 11.0),
        y_true=y_true + 1.0,
        issue_times=issue_times,
        day_starts=day_starts,
    )
    with pytest.raises(ValueError, match="truth"):
        compare_adjacent_tiers(parent, wrong_truth)

    perfect_parent = _learned_series(
        "M2",
        y_true,
        y_true=y_true,
        issue_times=issue_times,
        day_starts=day_starts,
    )
    with pytest.raises(ValueError, match="positive"):
        compare_adjacent_tiers(perfect_parent, child)


def test_shared_bootstrap_plan_has_exact_pcg64_matrix_and_stable_sha() -> None:
    _, day_starts = _formal_small_index()
    plan = BootstrapPlan.create(day_starts)

    assert plan.seed == 20260902
    assert plan.repetitions == 10_000
    assert plan.block_index_matrix.shape == (10_000, 14)
    assert plan.block_index_matrix[0].tolist() == [1, 12, 5, 8, 5, 2, 2, 13, 5, 11, 7, 7, 1, 8]
    assert plan.block_index_matrix[1].tolist() == [5, 12, 0, 2, 5, 9, 7, 9, 11, 3, 5, 10, 12, 1]
    assert plan.matrix_sha256 == "f61ba0b64c50f61e6b0215c20472616b291e877eb089fd963dc021239864ebfd"
    assert BootstrapPlan.create(day_starts).matrix_sha256 == plan.matrix_sha256
    public = plan.to_public_dict()
    assert "matrix" not in public
    assert "block_index_matrix" not in json.dumps(public)

    with pytest.raises(ValueError, match="10,000|10000"):
        BootstrapPlan.create(day_starts, repetitions=9999)
    with pytest.raises(ValueError, match="20260902"):
        BootstrapPlan.create(day_starts, seed=1)


def test_bootstrap_uses_pooled_rows_and_linear_percentiles() -> None:
    issue_times, day_starts = _formal_small_index(rows_per_day=3, final_day_rows=1)
    y_true = np.zeros(len(issue_times), dtype=np.float64)
    parent_errors = np.zeros(len(issue_times), dtype=np.float64)
    parent_errors[day_starts == day_starts[0]] = 10.0
    parent = _learned_series(
        "M1",
        parent_errors,
        learner="ridge",
        y_true=y_true,
        issue_times=issue_times,
        day_starts=day_starts,
    )
    child = _learned_series(
        "M2",
        np.zeros(len(issue_times)),
        learner="ridge",
        y_true=y_true,
        issue_times=issue_times,
        day_starts=day_starts,
    )
    comparison = compare_adjacent_tiers(parent, child)
    plan = BootstrapPlan.create(day_starts)
    interval = bootstrap_tier_comparison(comparison, plan)

    unique_days = plan.day_start_utc_s
    sums = np.asarray(
        [comparison.absolute_error_delta_a[day_starts == day].sum() for day in unique_days]
    )
    counts = np.asarray([(day_starts == day).sum() for day in unique_days])
    expected_replicates = sums[plan.block_index_matrix].sum(axis=1) / counts[
        plan.block_index_matrix
    ].sum(axis=1)
    expected = np.quantile(expected_replicates, [0.025, 0.975], method="linear")

    assert interval.point_delta_a == pytest.approx(float(np.mean(parent_errors)))
    assert interval.ci_lower_a == pytest.approx(float(expected[0]))
    assert interval.ci_upper_a == pytest.approx(float(expected[1]))
    assert interval.matrix_sha256 == plan.matrix_sha256
    assert interval.nominal_208v_point_delta_kw == pytest.approx(0.208 * interval.point_delta_a)


def _hgb_errors(
    *,
    m1: tuple[float, float, float] = (101.0, 101.0, 101.0),
    m2: tuple[float, float, float] = (100.0, 100.0, 100.0),
    m3: tuple[float, float, float] = (97.0, 97.0, 102.0),
    m4: tuple[float, float, float] = (95.0, 95.0, 103.0),
) -> dict[str, tuple[float, float, float, float, float]]:
    return {
        "M1": (*m1, 101.0, 101.0),
        "M2": (*m2, 100.0, 100.0),
        "M3": (*m3, 99.0, 99.0),
        "M4": (*m4, 98.0, 98.0),
    }


def _rebuild_series(
    series: EvaluationSeries,
    *,
    issue_times: np.ndarray,
    day_starts: np.ndarray,
    y_true: np.ndarray,
    predictions: np.ndarray,
    availability: np.ndarray,
) -> EvaluationSeries:
    return EvaluationSeries.create(
        model_kind=series.model_kind,
        learner=series.learner,
        tier=series.tier,
        baseline=series.baseline,
        horizon_minutes=series.horizon_minutes,
        issue_times=issue_times,
        day_start_utc_s=day_starts,
        y_true=y_true,
        predictions=predictions,
        availability=availability,
    )


def test_gate_evidence_cannot_be_created_from_anonymous_arrays() -> None:
    assert not hasattr(GateEvidence, "create")
    with pytest.raises(TypeError, match="evaluate_gate1|canonical"):
        GateEvidence()  # type: ignore[call-arg]


def test_formal_evaluation_seals_complete_canonical_evidence(
    canonical_result: Gate1EvaluationResult,
) -> None:
    assert len(canonical_result.evaluation_series) == 55
    assert len(canonical_result.scoped_metrics) == 55
    assert len(canonical_result.peak_ramp_metrics) == 55
    assert len(canonical_result.comparisons) == 30
    assert len(canonical_result.bootstrap_intervals) == 30
    assert canonical_result.gate_evidence.matrix_sha256 == (
        canonical_result.bootstrap_plan.matrix_sha256
    )
    assert canonical_result.gate_evidence.hgb_row_identity_sha256
    assert canonical_result.gate_evidence.comparison_suite_sha256
    assert canonical_result.gate_decision.classification == "PASS_ACTIVE_SESSION"
    learned_peak = next(
        item
        for item in canonical_result.peak_ramp_metrics
        if item.learner == "hgb" and item.tier == "M1" and item.horizon_minutes == 15
    )
    assert learned_peak.complete_peak_days == 14
    assert learned_peak.daily_peak[-1].n_total == 81
    assert learned_peak.daily_peak[-1].status == "defined"


def test_formal_evaluation_rejects_missing_or_replaced_canonical_test_rows() -> None:
    original = _canonical_evaluation_series()
    keep = np.arange(len(original[0].issue_times)) != 1
    missing = tuple(
        _rebuild_series(
            series,
            issue_times=series.issue_times[keep],
            day_starts=series.day_start_utc_s[keep],
            y_true=series.y_true[keep],
            predictions=series.predictions[keep],
            availability=series.availability[keep],
        )
        for series in original
    )
    with pytest.raises(ValueError, match="canonical.*row|1,329|1329"):
        evaluate_gate1(missing)

    replace_position = 13 * 96 + 40
    replacement_time = original[0].issue_times[-1] + 900
    keep = np.arange(len(original[0].issue_times)) != replace_position
    replaced = tuple(
        _rebuild_series(
            series,
            issue_times=np.append(series.issue_times[keep], replacement_time),
            day_starts=np.append(series.day_start_utc_s[keep], series.day_start_utc_s[-1]),
            y_true=np.append(series.y_true[keep], series.y_true[-1]),
            predictions=np.append(series.predictions[keep], series.predictions[-1]),
            availability=np.append(series.availability[keep], series.availability[-1]),
        )
        for series in original
    )
    with pytest.raises(ValueError, match="canonical.*row|identity"):
        evaluate_gate1(replaced)


def test_gate_exact_thresholds_and_active_session_classes() -> None:
    active = evaluate_gate1(_canonical_evaluation_series()).gate_decision
    assert active.classification == "PASS_ACTIVE_SESSION"
    assert active.m3_pass is True
    assert active.m4_keep is True
    assert active.m3_improvement_percent == pytest.approx((3.0, 3.0, -2.0))
    assert active.m4_improvement_percent == pytest.approx(
        (100.0 * 2.0 / 97.0, 100.0 * 2.0 / 97.0, -100.0 / 102.0)
    )

    drop_errors = _hgb_errors(m4=(97.0 * (1.0 - 0.00999999), 97.0 * (1.0 - 0.00999999), 103.0))
    drop = evaluate_gate1(_canonical_evaluation_series(hgb_mae_by_tier=drop_errors)).gate_decision
    assert drop.classification == "PASS_ACTIVE_SESSION_DROP_M4"
    assert drop.m3_pass is True
    assert drop.m4_keep is False

    degraded = evaluate_gate1(
        _canonical_evaluation_series(hgb_mae_by_tier=_hgb_errors(m3=(97.0, 97.0, 102.000001)))
    ).gate_decision
    assert degraded.m3_pass is False
    assert degraded.classification == "PASS_SIMPLE_STATE_ONLY"

    exact_m4_boundary = evaluate_gate1(
        _canonical_evaluation_series(
            hgb_mae_by_tier=_hgb_errors(
                m1=(105.0, 105.0, 105.0),
                m2=(104.0, 104.0, 102.0),
                m3=(100.0, 100.0, 100.0),
                m4=(99.0, 99.0, 102.0),
            )
        )
    ).gate_decision
    assert exact_m4_boundary.m4_improvement_percent == (1.0, 1.0, -2.0)
    assert exact_m4_boundary.m4_keep is True


def test_gate_directional_ci_and_winning_day_boundaries() -> None:
    touching_pattern = np.zeros(14, dtype=np.float64)
    touching_pattern[:3] = 14.0
    touching = evaluate_gate1(
        _canonical_evaluation_series(
            m3_daily_delta_by_horizon={
                15: touching_pattern,
                30: touching_pattern,
                60: np.full(14, -2.0),
            }
        )
    )
    m3_intervals = {
        item.horizon_minutes: item
        for item in touching.bootstrap_intervals
        if item.learner == "hgb"
        and item.parent_tier == "M2"
        and item.child_tier == "M3"
        and item.horizon_minutes in NEAR_HORIZONS
    }
    assert m3_intervals[15].ci_lower_a == 0.0
    assert touching.gate_decision.m3_directional_ci is False
    assert touching.gate_decision.m3_winning_days == 3
    assert touching.gate_decision.m3_pass is False

    ten_wins = np.full(14, -30.0)
    ten_wins[:10] = 20.0
    ten_days = evaluate_gate1(
        _canonical_evaluation_series(
            m3_daily_delta_by_horizon={
                15: ten_wins,
                30: ten_wins,
                60: np.full(14, -2.0),
            }
        )
    ).gate_decision
    assert ten_days.m3_directional_ci is False
    assert ten_days.m3_winning_days == 10
    assert ten_days.m3_pass is True


def test_simple_state_is_sign_only_hgb_near_mean_and_ties_do_not_pass() -> None:
    simple = evaluate_gate1(
        _canonical_evaluation_series(
            hgb_mae_by_tier=_hgb_errors(
                m1=(100.0, 100.0, 100.0),
                m2=(99.999999, 99.999999, 99.999999),
                m3=(99.999999, 99.999999, 99.999999),
                m4=(99.999999, 99.999999, 99.999999),
            )
        )
    ).gate_decision
    assert simple.m2_diagnostic_mean_delta_a > 0
    assert simple.m2_diagnostic_improves is True
    assert simple.classification == "PASS_SIMPLE_STATE_ONLY"

    tied = evaluate_gate1(
        _canonical_evaluation_series(
            hgb_mae_by_tier=_hgb_errors(
                m1=(100.0, 100.0, 100.0),
                m2=(100.0, 100.0, 100.0),
                m3=(100.0, 100.0, 100.0),
                m4=(100.0, 100.0, 100.0),
            )
        )
    ).gate_decision
    assert tied.m2_diagnostic_mean_delta_a == 0.0
    assert tied.m2_diagnostic_improves is False
    assert tied.classification == "FAIL_DIRECTION"

    worse = evaluate_gate1(
        _canonical_evaluation_series(
            hgb_mae_by_tier=_hgb_errors(
                m1=(99.0, 99.0, 99.0),
                m2=(100.0, 100.0, 100.0),
                m3=(100.0, 100.0, 100.0),
                m4=(50.0, 50.0, 50.0),
            )
        )
    ).gate_decision
    assert worse.classification == "FAIL_DIRECTION"


def test_execution_fail_has_precedence_and_nonpositive_parent_fails_closed() -> None:
    failed = classify_gate(
        None,
        execution_failures=(ExecutionFailureCode.DATA_CONTRACT,),
    )
    assert failed.classification == "EXECUTION_FAIL"
    assert failed.execution_ok is False
    assert failed.blocking_issues == ("DATA_CONTRACT",)

    with pytest.raises(TypeError, match="ExecutionFailureCode"):
        classify_gate(None, execution_failures=("USER_ID_12345",))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ExecutionFailureCode("USER_ID_12345")

    incomplete = classify_gate(None)
    assert incomplete.classification == "EXECUTION_FAIL"
    assert incomplete.blocking_issues == ("INCOMPLETE_GATE_EVIDENCE",)

    with pytest.raises(ValueError, match="positive"):
        evaluate_gate1(
            _canonical_evaluation_series(hgb_mae_by_tier=_hgb_errors(m2=(0.0, 1.0, 1.0)))
        )


def _contains_array(value: Any) -> bool:
    if isinstance(value, np.ndarray):
        return True
    if isinstance(value, dict):
        return any(_contains_array(key) or _contains_array(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_array(item) for item in value)
    return False


def test_public_payload_requires_complete_same_source_result(
    canonical_result: Gate1EvaluationResult,
) -> None:
    payload = build_public_aggregate_payload(canonical_result)

    assert _contains_array(payload) is False
    assert len(payload["metrics_by_horizon"]) == 55
    assert len(payload["peak_ramp_metrics"]) == 55
    assert len(payload["tier_comparisons"]) == 30
    assert len(payload["bootstrap"]["intervals"]) == 30
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    lowered = encoded.lower()
    for forbidden in (
        "sessionid",
        "userid",
        "user_id",
        '"_id"',
        "anonymous_session",
        "trajectory_ref",
        "reference_times",
        "issue_times",
        "issue_time_utc_s",
        "y_true",
        "y_pred",
        "predictions",
        "parameter_hashes",
        "block_index_matrix",
        "replicate_means",
        "c:\\\\",
        "\\\\server\\share",
        "/home/",
        "/tmp/",
        "/root/",
    ):
        assert forbidden not in lowered
    assert payload == build_public_aggregate_payload(canonical_result)


def test_public_builder_rejects_incomplete_or_contradictory_result(
    canonical_result: Gate1EvaluationResult,
) -> None:
    incomplete = replace(canonical_result, scoped_metrics=())
    with pytest.raises(ValueError, match="complete|55|same-source"):
        build_public_aggregate_payload(incomplete)

    duplicated = replace(
        canonical_result,
        bootstrap_intervals=(
            canonical_result.bootstrap_intervals[0],
            canonical_result.bootstrap_intervals[0],
            *canonical_result.bootstrap_intervals[2:],
        ),
    )
    with pytest.raises(ValueError, match="complete|duplicate|same-source"):
        build_public_aggregate_payload(duplicated)

    first = canonical_result.bootstrap_intervals[0]
    forged_interval = replace(
        first,
        point_delta_a=first.point_delta_a + 1.0,
        ci_lower_a=first.ci_lower_a + 1.0,
        ci_upper_a=first.ci_upper_a + 1.0,
    )
    contradictory = replace(
        canonical_result,
        bootstrap_intervals=(forged_interval, *canonical_result.bootstrap_intervals[1:]),
    )
    with pytest.raises(ValueError, match="same-source|bootstrap|canonical"):
        build_public_aggregate_payload(contradictory)

    contradictory_gate = replace(
        canonical_result,
        gate_decision=replace(canonical_result.gate_decision, classification="FAIL_DIRECTION"),
    )
    with pytest.raises(ValueError, match="same-source|Gate|canonical"):
        build_public_aggregate_payload(contradictory_gate)


@pytest.mark.parametrize(
    "unsafe",
    [
        {"user_id": "123"},
        {"_id": "private"},
        {"note": "source _id=private"},
        {"trajectory_ref": "private"},
        {"issue_time_utc_s": 1_557_000_000},
        {"y_true": [1.0]},
        {"y_pred": [1.0]},
        {"parameter_hashes": ["a" * 64]},
        {"note": r"log=C:\private\run.json"},
        {"note": r"artifact(C:\private\run.json)"},
        {"note": r"\\server\share\run.json"},
        {"note": "artifact=/tmp/run.json"},
        {"note": "artifact(/tmp/run.json)"},
        {"note": "artifact=/root/run.json"},
        {"note": "artifact=/var/tmp/run.json"},
    ],
)
def test_public_privacy_scanner_rejects_identifiers_arrays_and_paths(
    unsafe: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="forbidden|path|private"):
        assert_public_payload_safe(unsafe)


def test_public_privacy_scanner_does_not_treat_https_as_a_local_path() -> None:
    assert_public_payload_safe({"source": "https://example.com/a"})
