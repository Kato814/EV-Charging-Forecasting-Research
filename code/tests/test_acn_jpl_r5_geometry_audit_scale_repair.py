from __future__ import annotations

import evcf.forecasting.acn_jpl_r5_future_transition_representation as base
import evcf.forecasting.acn_jpl_r5_future_transition_representation_compat as compat
import numpy as np


def _block(scale: float, shift: float = 0.0) -> base.DailyPrediction:
    issue = np.asarray([1, 2, 3], dtype=np.int64)
    q = np.asarray(
        [
            [0.0, 0.0, 0.0, 0.0, 0.0],
            [1.0, 1.0, 1.0, 1.0, 1.0],
            [2.0, 2.0, 2.0, 2.0, 2.0],
        ]
    )
    latent_scalar = shift + scale * np.asarray([0.0, 1.0, 2.0])
    latent = np.column_stack([latent_scalar] * base.LATENT_WIDTH)
    zeros = np.zeros((3, 5), dtype=float)
    return base.DailyPrediction(
        issue_times=issue,
        day_start=0,
        truth=zeros,
        direct=zeros,
        ftar=zeros,
        q_truth=q,
        direct_latent=latent,
        ftar_latent=latent,
    )


def test_daily_distance_standardization_removes_positive_affine_latent_scale():
    direct_a, ftar_a, future_a = compat.standardized_same_refit_pair_distances(_block(1.0))
    direct_b, ftar_b, future_b = compat.standardized_same_refit_pair_distances(
        _block(17.0, 1000.0)
    )
    assert np.allclose(direct_a, direct_b)
    assert np.allclose(ftar_a, ftar_b)
    assert np.allclose(future_a, future_b)


def test_repaired_geometry_audit_never_creates_cross_refit_pairs():
    first = _block(1.0)
    second_raw = _block(7.0, 5000.0)
    second = base.DailyPrediction(
        issue_times=second_raw.issue_times + 10,
        day_start=10,
        truth=second_raw.truth,
        direct=second_raw.direct,
        ftar=second_raw.ftar,
        q_truth=second_raw.q_truth,
        direct_latent=second_raw.direct_latent,
        ftar_latent=second_raw.ftar_latent,
    )
    month = base.MonthPrediction(
        month="2019-01",
        issue_times=np.asarray([1, 2, 3, 11, 12, 13], dtype=np.int64),
        day_starts=np.asarray([0, 0, 0, 10, 10, 10], dtype=np.int64),
        truth=np.zeros((6, 5)),
        direct=np.zeros((6, 5)),
        ftar=np.zeros((6, 5)),
        daily=(first, second),
        fit_count=4,
    )
    pooled, rows = compat.geometry_audit([month])
    assert rows[0]["available_same_refit_pairs"] == 6
    assert pooled["retained_pairs"] == 6
    assert pooled["daily_distance_standardization"] is True
