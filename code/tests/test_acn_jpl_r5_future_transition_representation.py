from __future__ import annotations

import evcf.forecasting.acn_jpl_r5_future_transition_representation as r5
import numpy as np
import pytest


def test_transition_scaling_is_centered_and_roundtrips():
    current = np.asarray([10.0, 20.0, 30.0])
    transitions = np.asarray(
        [
            [1.0, 2.0, 3.0, 4.0, 5.0],
            [2.0, 4.0, 6.0, 8.0, 10.0],
            [3.0, 6.0, 9.0, 12.0, 15.0],
        ]
    )
    labels = current[:, None] + transitions
    location, scale, q = r5.transition_location_scale(labels, current)
    assert np.allclose(location, np.asarray([2.0, 4.0, 6.0, 8.0, 10.0]))
    assert np.all(scale >= 1.0)
    rebuilt = r5.reconstruct_load(current, location, scale, q)
    assert np.allclose(rebuilt, labels)


def test_rolling_train_rows_require_complete_240_min_future_before_cutoff():
    cutoff = 10_000
    times = np.asarray([cutoff - 20_000, cutoff - 14_400, cutoff - 14_399, cutoff - 1])
    rows = r5.rolling_train_rows(times, cutoff)
    assert np.array_equal(rows, np.asarray([0, 1]))


def test_batch_partitions_never_leave_singleton():
    assert r5.batch_partitions(256) == ((0, 256),)
    assert r5.batch_partitions(257) == ((0, 257),)
    assert r5.batch_partitions(513) == ((0, 256), (256, 513))
    assert all(stop - start >= 2 for start, stop in r5.batch_partitions(770))


def test_architecture_and_route_boundaries_are_frozen():
    assert r5.architecture_spec() == (391, 128, 32, 64, 5)
    assert r5.GEOMETRY_WEIGHT == pytest.approx(0.25)
    assert r5.EPOCHS == 80
    assert r5.BATCH_SIZE == 256
    assert set(r5.DEVELOPMENT_MONTHS).isdisjoint(r5.FINAL_HOLDOUT_MONTHS)


def _metrics(mae: float) -> dict[str, float]:
    return {"mae_a": mae}


def test_decision_pass_stop_and_mixed_are_predeclared():
    pooled = {
        "Direct": _metrics(10.0),
        "FTAR": _metrics(9.0),
        "M3": _metrics(10.2),
        "Equal": _metrics(9.5),
        "S1": _metrics(9.4),
    }
    by_horizon = [
        {"Direct": _metrics(10.0), "FTAR": _metrics(value)}
        for value in (9.0, 9.1, 9.2, 10.1, 9.3)
    ]
    by_month = [
        {"Direct": _metrics(10.0), "FTAR": _metrics(value)}
        for value in (9.0, 9.1, 9.2, 10.1)
    ]
    geometry = {"Direct_spearman": 0.2, "FTAR_spearman": 0.4}
    decision, _ = r5.decide(pooled, by_horizon, by_month, geometry)
    assert decision == "PASS_FUTURE_TRANSITION_GEOMETRY"

    pooled_stop = dict(pooled)
    pooled_stop["FTAR"] = _metrics(10.0)
    decision_stop, _ = r5.decide(pooled_stop, by_horizon, by_month, geometry)
    assert decision_stop == "STOP_FUTURE_TRANSITION_GEOMETRY_ROUTE"

    pooled_mixed = dict(pooled)
    pooled_mixed["Equal"] = _metrics(8.5)
    pooled_mixed["S1"] = _metrics(8.7)
    decision_mixed, _ = r5.decide(pooled_mixed, by_horizon, by_month, geometry)
    assert decision_mixed == "MIXED_FUTURE_TRANSITION_GEOMETRY"


def test_geometry_audit_uses_only_pairs_within_each_daily_refit():
    def block(day: int, offset: float) -> r5.DailyPrediction:
        issue = np.asarray([day + 1, day + 2, day + 3], dtype=np.int64)
        q = np.asarray(
            [
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [1.0, 1.0, 1.0, 1.0, 1.0],
                [2.0, 2.0, 2.0, 2.0, 2.0],
            ]
        )
        latent = np.column_stack([np.arange(3, dtype=float) + offset] * r5.LATENT_WIDTH)
        zeros = np.zeros((3, 5), dtype=float)
        return r5.DailyPrediction(
            issue_times=issue,
            day_start=day,
            truth=zeros,
            direct=zeros,
            ftar=zeros,
            q_truth=q,
            direct_latent=latent,
            ftar_latent=latent,
        )

    month = r5.MonthPrediction(
        month="2019-01",
        issue_times=np.asarray([1, 2, 3, 11, 12, 13], dtype=np.int64),
        day_starts=np.asarray([0, 0, 0, 10, 10, 10], dtype=np.int64),
        truth=np.zeros((6, 5)),
        direct=np.zeros((6, 5)),
        ftar=np.zeros((6, 5)),
        daily=(block(0, 0.0), block(10, 1000.0)),
        fit_count=4,
    )
    pooled, rows = r5.geometry_audit([month])
    assert rows[0]["available_same_refit_pairs"] == 6
    assert pooled["retained_pairs"] == 6
    assert pooled["Direct_spearman"] == pytest.approx(1.0)
    assert pooled["FTAR_spearman"] == pytest.approx(1.0)


def test_nullable_issue_current_fill_is_training_only_contract():
    raw = np.asarray([1.0, np.nan, 3.0])
    filled = r5.fill_issue_current(raw, 2.0)
    assert np.array_equal(filled, np.asarray([1.0, 2.0, 3.0]))


def test_standardized_distance_geometry_loss_is_scale_and_shift_invariant():
    latent = np.asarray([1.0, 2.0, 4.0, 8.0])
    future = 3.0 * latent + 7.0
    assert r5.standardized_distance_mse(latent, future) < 1e-10
