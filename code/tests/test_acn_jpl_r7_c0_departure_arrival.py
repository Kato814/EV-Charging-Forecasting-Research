from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from evcf.forecasting import acn_jpl_r7_c0_departure_arrival as r7
from evcf.forecasting.acn_jpl_development_experts import MonthData
from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock, canonical_feature_schema


def _feature_blocks(rows: int = 4) -> tuple[FeatureBlock, FeatureBlock]:
    issue_times = np.arange(1, rows + 1, dtype=np.int64) * 900
    m2_names, m2_nullable = canonical_feature_schema("M2")
    m3_names, m3_nullable = canonical_feature_schema("M3")
    m2_values = np.zeros((rows, len(m2_names)), dtype=np.float64)
    m3_values = np.zeros((rows, len(m3_names)), dtype=np.float64)
    m3_values[:, : len(m2_names)] = m2_values
    departure_positions = [
        m3_names.index(f"m3_requested_departure_minutes_from_issue_{name}")
        for name in r7._POOL_STAT_NAMES
    ]
    m3_values[0, departure_positions[2]] = np.nan
    return (
        FeatureBlock(issue_times, m2_values, m2_names, m2_nullable),
        FeatureBlock(issue_times, m3_values, m3_names, m3_nullable),
    )


def _metric_block(
    *,
    base_arrival: float,
    departure_arrival: float,
    full_arrival: float,
    s1: float,
    equal: float,
    total_departure: float,
    total_full_m3: float,
) -> dict[str, object]:
    def metric(mae: float) -> dict[str, float]:
        return {"mae_a": mae}

    return {
        "arrival": {
            "BaseM2": metric(base_arrival),
            "DepartureAug": metric(departure_arrival),
            "FullM3": metric(full_arrival),
        },
        "total": {
            "S1": metric(s1),
            "Equal": metric(equal),
            "TotalDeparture": metric(total_departure),
            "TotalFullM3": metric(total_full_m3),
        },
    }


def test_departure_aug_uses_exact_requested_departure_pool_and_width() -> None:
    m2, m3 = _feature_blocks()
    block = r7._departure_aug_block(m2, m3)
    assert block.values.shape == (4, r7.DEPARTURE_RAW_WIDTH)
    assert block.feature_names[: len(m2.feature_names)] == m2.feature_names
    assert block.feature_names[len(m2.feature_names) :] == r7._DEPARTURE_FEATURE_NAMES
    assert int(np.sum(block.nullable_mask)) == 10
    encoded = r7._encode(block, np.arange(4, dtype=np.int64))
    assert encoded.shape == (4, r7.DEPARTURE_ENCODED_WIDTH)
    assert np.isnan(encoded[0, len(m2.feature_names) + 2])
    assert np.isfinite(encoded[:, r7.DEPARTURE_RAW_WIDTH :]).all()


def test_departure_aug_rejects_m2_m3_prefix_drift() -> None:
    m2, m3 = _feature_blocks()
    drift = np.asarray(m3.values).copy()
    drift[0, 0] = 1.0
    bad = FeatureBlock(m3.issue_times, drift, m3.feature_names, m3.nullable_mask)
    with pytest.raises(r7.R7C0Error, match="FEATURE_ALIGNMENT_INVALID"):
        r7._departure_aug_block(m2, bad)


def test_decision_pass_requires_component_and_total_stability() -> None:
    pooled = _metric_block(
        base_arrival=10.0,
        departure_arrival=8.0,
        full_arrival=8.5,
        s1=12.0,
        equal=11.5,
        total_departure=10.0,
        total_full_m3=10.5,
    )
    horizons = []
    for horizon in r7.HORIZONS_MINUTES:
        item = _metric_block(
            base_arrival=10.0,
            departure_arrival=9.0,
            full_arrival=9.0,
            s1=12.0,
            equal=11.5,
            total_departure=11.0,
            total_full_m3=11.0,
        )
        horizons.append({"horizon_minutes": horizon, **item})
    months = [
        {
            "month": month,
            **_metric_block(
                base_arrival=10.0,
                departure_arrival=9.0,
                full_arrival=9.0,
                s1=12.0,
                equal=11.5,
                total_departure=11.0,
                total_full_m3=11.0,
            ),
        }
        for month in r7.DEVELOPMENT_MONTHS
    ]
    decision, secondary, support = r7.decide(pooled, horizons, months)
    assert decision == "PASS_DEPARTURE_STATE_ARRIVAL_SIGNAL"
    assert secondary == "FULL_M3_INCREMENTAL_SIGNAL"
    assert support["arrival_dominant_horizon_wins"] == 3


def test_decision_mixed_when_component_improves_but_total_does_not() -> None:
    pooled = _metric_block(
        base_arrival=10.0,
        departure_arrival=9.0,
        full_arrival=11.0,
        s1=12.0,
        equal=11.5,
        total_departure=12.5,
        total_full_m3=12.5,
    )
    horizons = [
        {
            "horizon_minutes": horizon,
            **_metric_block(
                base_arrival=10.0,
                departure_arrival=9.0,
                full_arrival=11.0,
                s1=12.0,
                equal=11.5,
                total_departure=12.2,
                total_full_m3=12.2,
            ),
        }
        for horizon in r7.HORIZONS_MINUTES
    ]
    months = [
        {
            "month": month,
            **_metric_block(
                base_arrival=10.0,
                departure_arrival=9.0,
                full_arrival=11.0,
                s1=12.0,
                equal=11.5,
                total_departure=12.2,
                total_full_m3=12.2,
            ),
        }
        for month in r7.DEVELOPMENT_MONTHS
    ]
    decision, secondary, _ = r7.decide(pooled, horizons, months)
    assert decision == "MIXED_DEPARTURE_STATE_ARRIVAL_SIGNAL"
    assert secondary == "NO_STABLE_FULL_M3_INCREMENT"


def test_decision_stop_when_neither_pooled_component_nor_total_improves() -> None:
    pooled = _metric_block(
        base_arrival=10.0,
        departure_arrival=10.5,
        full_arrival=10.5,
        s1=12.0,
        equal=11.5,
        total_departure=12.5,
        total_full_m3=12.5,
    )
    horizons = [
        {"horizon_minutes": horizon, **pooled} for horizon in r7.HORIZONS_MINUTES
    ]
    months = [{"month": month, **pooled} for month in r7.DEVELOPMENT_MONTHS]
    decision, secondary, _ = r7.decide(pooled, horizons, months)
    assert decision == "STOP_DEPARTURE_STATE_ARRIVAL_ROUTE"
    assert secondary == "NO_STABLE_FULL_M3_INCREMENT"


def test_record_recombines_candidate_arrival_with_frozen_s1_existing(monkeypatch) -> None:
    monkeypatch.setitem(r7.EXPECTED_ROWS_BY_MONTH, "2019-01", 3)
    issue = np.asarray([900, 1800, 2700], dtype=np.int64)
    days = np.zeros(3, dtype=np.int64)
    existing_truth = np.asarray([10.0, 20.0, 30.0])
    arrival_truth = np.asarray([1.0, 2.0, 3.0])
    existing_pred = np.asarray([11.0, 19.0, 31.0])
    base_arrival = np.asarray([2.0, 1.0, 4.0])
    reference = {
        "issue_times": issue,
        "day_start_utc_s": days,
        "y_true": existing_truth + arrival_truth,
        "existing_truth": existing_truth,
        "arrival_truth": arrival_truth,
        "existing_predictions": existing_pred,
        "arrival_predictions": base_arrival,
        "structured_predictions": existing_pred + base_arrival,
        "equal_predictions": existing_truth + arrival_truth,
    }
    departure = {
        "issue_times": issue,
        "day_starts": days,
        "truth": arrival_truth,
        "predictions": np.asarray([1.5, 2.5, 3.5]),
    }
    full_m3 = {
        "issue_times": issue,
        "day_starts": days,
        "truth": arrival_truth,
        "predictions": np.asarray([1.2, 2.2, 3.2]),
    }
    record = r7._record(
        month="2019-01",
        horizon=15,
        reference=reference,
        departure=departure,
        full_m3=full_m3,
    )
    assert np.allclose(
        record["departure_total"], existing_pred + departure["predictions"]
    )
    assert np.allclose(record["full_m3_total"], existing_pred + full_m3["predictions"])


def test_predict_custom_arm_uses_daily_causal_rolling_rows(monkeypatch) -> None:
    zone = ZoneInfo(r7.TIMEZONE_NAME)
    start = datetime(2019, 1, 1, 12, 0, tzinfo=zone)
    issue_times = np.asarray(
        [int((start + timedelta(days=index)).timestamp()) for index in range(20)],
        dtype=np.int64,
    )
    labels = np.tile(np.arange(1.0, 21.0)[:, None], (1, 5))
    block = FeatureBlock(
        issue_times,
        np.arange(40.0, dtype=np.float64).reshape(20, 2),
        ("x0", "x1"),
        np.asarray([False, False], dtype=np.bool_),
    )
    data = MonthData(
        month="2019-01",
        issue_times=issue_times,
        labels=labels,
        blocks={},
        processed_snapshot_sha256="x" * 64,
    )

    class MeanEstimator:
        def fit(self, x: np.ndarray, y: np.ndarray):
            self.value = float(np.mean(y))
            return self

        def predict(self, x: np.ndarray) -> np.ndarray:
            return np.full(len(x), self.value, dtype=np.float64)

    monkeypatch.setattr(r7, "make_frozen_estimator", lambda learner, params: MeanEstimator())
    result = r7._predict_custom_arm(
        data=data,
        block=block,
        horizon_minutes=15,
        params={},
        encoded_width=2,
        native_thread_limit=1,
    )
    assert result["fit_count"] == 3
    assert len(result["issue_times"]) == 3
    assert np.array_equal(result["truth"], np.asarray([18.0, 19.0, 20.0]))


def test_unauthorized_run_stops_before_path_resolution() -> None:
    with pytest.raises(r7.R7C0Error, match="R7_C0_NOT_AUTHORIZED"):
        r7.run_r7_c0(
            authorized=False,
            interim_root=Path("missing"),
            processed_root=Path("missing"),
            baseline_private_run=Path("missing"),
            structured_private_run=Path("missing"),
            private_output_root=Path("missing"),
            code_commit="x",
            repo_root=Path("missing"),
        )
