from __future__ import annotations

import evcf.forecasting.acn_jpl_r4_information_sufficiency_gate as r4
import pytest


def test_supported_aggregate_publishes_frozen_distance_support_summaries():
    records = [
        {
            "d_level_a": 10.0,
            "d_m2_a": 9.0,
            "d_m3_a": 8.0,
            "y_abs_a": 40.0,
            "distance_ratio": 0.50,
            "candidate_count": 12,
            "test_third_m3_distance": 1.0,
            "historical_q95_m3_distance": 2.0,
        },
        {
            "d_level_a": 20.0,
            "d_m2_a": 18.0,
            "d_m3_a": 16.0,
            "y_abs_a": 80.0,
            "distance_ratio": 0.75,
            "candidate_count": 20,
            "test_third_m3_distance": 3.0,
            "historical_q95_m3_distance": 4.0,
        },
    ]

    metrics = r4._aggregate(records)

    assert metrics is not None
    assert metrics["candidate_count_min"] == 12
    assert metrics["candidate_count_mean"] == pytest.approx(16.0)
    assert metrics["candidate_count_median"] == pytest.approx(16.0)
    assert metrics["candidate_count_max"] == 20
    assert metrics["test_third_m3_distance_mean"] == pytest.approx(2.0)
    assert metrics["test_third_m3_distance_median"] == pytest.approx(2.0)
    assert metrics["test_third_m3_distance_p95"] == pytest.approx(3.0)
    assert metrics["historical_q95_m3_distance_mean"] == pytest.approx(3.0)
    assert metrics["historical_q95_m3_distance_median"] == pytest.approx(3.0)
    assert metrics["historical_q95_m3_distance_p95"] == pytest.approx(4.0)
    assert metrics["distance_ratio_mean"] == pytest.approx(0.625)
    assert metrics["distance_ratio_median"] == pytest.approx(0.625)
    assert metrics["distance_ratio_p95"] == pytest.approx(0.75)


def test_distance_support_summary_rejects_invalid_candidate_count():
    record = {
        "candidate_count": r4.MIN_CANDIDATES - 1,
        "test_third_m3_distance": 1.0,
        "historical_q95_m3_distance": 2.0,
    }

    with pytest.raises(r4.R4I0Error, match="DISTANCE_SUPPORT_SUMMARY_INVALID"):
        r4._distance_support_summary([record])
