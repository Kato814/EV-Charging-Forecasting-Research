from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from evcf.evaluation.acn_jpl_gate1_metrics import (
    BootstrapPlan,
    EvaluationSeries,
    GateEvidence,
    bootstrap_tier_comparison,
    build_public_aggregate_payload,
    classify_gate,
    compare_adjacent_tiers,
    compute_error_metrics,
    compute_peak_ramp_metrics,
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


def test_evaluation_and_gate_factories_do_not_coerce_schema_types() -> None:
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
    with pytest.raises(TypeError, match="integer"):
        GateEvidence.create(
            horizons_minutes=(15.0, 30, 60),
            hgb_mae_by_tier={tier: (1.0, 1.0, 1.0) for tier in ("M1", "M2", "M3", "M4")},
            m3_vs_m2_ci_lower=(0.1, 0.1, 0.1),
            m3_daily_absolute_error_delta=np.ones((14, 3)),
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


def _gate_evidence(
    *,
    m1: tuple[float, float, float] = (101.0, 101.0, 101.0),
    m2: tuple[float, float, float] = (100.0, 100.0, 100.0),
    m3_improvement: tuple[float, float, float] = (3.0, 3.0, -2.0),
    m4_improvement: tuple[float, float, float] = (1.1, 1.1, -1.9),
    ci_lower: tuple[float, float, float] = (0.1, -1.0, -1.0),
    winning_days: int = 0,
) -> GateEvidence:
    m2_array = np.asarray(m2, dtype=np.float64)
    m3 = m2_array * (1.0 - np.asarray(m3_improvement) / 100.0)
    m4 = m3 * (1.0 - np.asarray(m4_improvement) / 100.0)
    daily = np.zeros((14, 3), dtype=np.float64)
    daily[:winning_days] = 1.0
    return GateEvidence.create(
        horizons_minutes=NEAR_HORIZONS,
        hgb_mae_by_tier={"M1": m1, "M2": m2, "M3": m3, "M4": m4},
        m3_vs_m2_ci_lower=ci_lower,
        m3_daily_absolute_error_delta=daily,
    )


def test_gate_exact_thresholds_and_active_session_classes() -> None:
    active = classify_gate(_gate_evidence())
    assert active.classification == "PASS_ACTIVE_SESSION"
    assert active.m3_pass is True
    assert active.m4_keep is True
    assert active.m3_improvement_percent == pytest.approx((3.0, 3.0, -2.0))
    assert active.m4_improvement_percent == pytest.approx((1.1, 1.1, -1.9))

    drop = classify_gate(_gate_evidence(m4_improvement=(1.1, 0.999999, -1.9)))
    assert drop.classification == "PASS_ACTIVE_SESSION_DROP_M4"
    assert drop.m3_pass is True
    assert drop.m4_keep is False

    degraded = classify_gate(_gate_evidence(m3_improvement=(3.0, 3.0, -2.000001)))
    assert degraded.m3_pass is False
    assert degraded.classification == "PASS_SIMPLE_STATE_ONLY"

    exact_m4_boundary = classify_gate(
        GateEvidence.create(
            horizons_minutes=NEAR_HORIZONS,
            hgb_mae_by_tier={
                "M1": (105.0, 105.0, 105.0),
                "M2": (104.0, 104.0, 102.0),
                "M3": (100.0, 100.0, 100.0),
                "M4": (99.0, 99.0, 102.0),
            },
            m3_vs_m2_ci_lower=(0.1, -1.0, -1.0),
            m3_daily_absolute_error_delta=np.zeros((14, 3)),
        )
    )
    assert exact_m4_boundary.m4_improvement_percent == (1.0, 1.0, -2.0)
    assert exact_m4_boundary.m4_keep is True


def test_gate_directional_ci_and_winning_day_boundaries() -> None:
    negative_ci = classify_gate(_gate_evidence(ci_lower=(-2.0, -1.0, -0.1), winning_days=9))
    assert negative_ci.m3_directional_ci is False
    assert negative_ci.m3_winning_days == 9
    assert negative_ci.m3_pass is False

    touching_zero = classify_gate(_gate_evidence(ci_lower=(0.0, -1.0, -1.0), winning_days=9))
    assert touching_zero.m3_directional_ci is False
    assert touching_zero.m3_pass is False

    ten_days = classify_gate(_gate_evidence(ci_lower=(0.0, -1.0, -1.0), winning_days=10))
    assert ten_days.m3_winning_days == 10
    assert ten_days.m3_pass is True


def test_simple_state_is_sign_only_hgb_near_mean_and_ties_do_not_pass() -> None:
    simple = classify_gate(
        _gate_evidence(
            m1=(100.0, 100.0, 100.0),
            m2=(99.999999, 99.999999, 99.999999),
            m3_improvement=(0.0, 0.0, 0.0),
            ci_lower=(0.0, 0.0, 0.0),
        )
    )
    assert simple.m2_diagnostic_mean_delta_a > 0
    assert simple.m2_diagnostic_improves is True
    assert simple.classification == "PASS_SIMPLE_STATE_ONLY"

    tied = classify_gate(
        _gate_evidence(
            m1=(100.0, 100.0, 100.0),
            m2=(100.0, 100.0, 100.0),
            m3_improvement=(0.0, 0.0, 0.0),
            ci_lower=(0.0, 0.0, 0.0),
        )
    )
    assert tied.m2_diagnostic_mean_delta_a == 0.0
    assert tied.m2_diagnostic_improves is False
    assert tied.classification == "FAIL_DIRECTION"

    worse = classify_gate(
        _gate_evidence(
            m1=(99.0, 99.0, 99.0),
            m2=(100.0, 100.0, 100.0),
            m3_improvement=(0.0, 0.0, 0.0),
            ci_lower=(0.0, 0.0, 0.0),
            m4_improvement=(50.0, 50.0, 50.0),
        )
    )
    assert worse.classification == "FAIL_DIRECTION"


def test_execution_fail_has_precedence_and_nonpositive_parent_fails_closed() -> None:
    failed = classify_gate(None, execution_failures=("DATA_CONTRACT",))
    assert failed.classification == "EXECUTION_FAIL"
    assert failed.execution_ok is False
    assert failed.blocking_issues == ("DATA_CONTRACT",)

    incomplete = classify_gate(None)
    assert incomplete.classification == "EXECUTION_FAIL"
    assert incomplete.blocking_issues == ("INCOMPLETE_GATE_EVIDENCE",)

    with pytest.raises(ValueError, match="positive"):
        GateEvidence.create(
            horizons_minutes=NEAR_HORIZONS,
            hgb_mae_by_tier={
                "M1": (1.0, 1.0, 1.0),
                "M2": (0.0, 1.0, 1.0),
                "M3": (1.0, 1.0, 1.0),
                "M4": (1.0, 1.0, 1.0),
            },
            m3_vs_m2_ci_lower=(0.1, 0.1, 0.1),
            m3_daily_absolute_error_delta=np.ones((14, 3)),
        )


def _contains_array(value: Any) -> bool:
    if isinstance(value, np.ndarray):
        return True
    if isinstance(value, dict):
        return any(_contains_array(key) or _contains_array(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_array(item) for item in value)
    return False


def test_public_payload_is_aggregate_only_json_and_contains_no_local_indexes() -> None:
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
    scoped = [evaluate_scopes(parent), evaluate_scopes(child)]
    peak_ramp = [compute_peak_ramp_metrics(parent), compute_peak_ramp_metrics(child)]
    comparison = compare_adjacent_tiers(parent, child)
    plan = BootstrapPlan.create(day_starts)
    interval = bootstrap_tier_comparison(comparison, plan)
    decision = classify_gate(_gate_evidence())
    payload = build_public_aggregate_payload(
        scoped_metrics=scoped,
        peak_ramp_metrics=peak_ramp,
        comparisons=[comparison],
        bootstrap_plan=plan,
        bootstrap_intervals=[interval],
        gate_decision=decision,
    )

    assert _contains_array(payload) is False
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    lowered = encoded.lower()
    for forbidden in (
        "sessionid",
        "userid",
        "anonymous_session",
        "reference_times",
        "issue_times",
        "predictions",
        "block_index_matrix",
        "replicate_means",
        "c:\\\\",
        "/home/",
    ):
        assert forbidden not in lowered
    assert payload == build_public_aggregate_payload(
        scoped_metrics=scoped,
        peak_ramp_metrics=peak_ramp,
        comparisons=[comparison],
        bootstrap_plan=plan,
        bootstrap_intervals=[interval],
        gate_decision=decision,
    )
