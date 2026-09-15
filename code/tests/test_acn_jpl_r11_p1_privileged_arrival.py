from __future__ import annotations

import inspect

import numpy as np
import pytest

from evcf.forecasting.acn_jpl_r11_p1_privileged_arrival import (
    AUXILIARY_WEIGHT,
    DEEP_SEEDS,
    IMPLEMENTATION_PATHS,
    LONG_HORIZONS,
    LongFoldPrediction,
    count_trainable_parameters,
    decide,
    make_p1_tcn,
)
from evcf.forecasting.acn_jpl_r11_s0_common import DEVELOPMENT_MONTHS
from evcf.forecasting.acn_jpl_r11_s0_models import FoldPrediction


def _hgb_records(mae: float = 10.0) -> tuple[FoldPrediction, ...]:
    records = []
    for index, month in enumerate(DEVELOPMENT_MONTHS):
        truth = np.full((2, 5), 100.0, dtype=np.float64)
        prediction = truth + mae
        records.append(
            FoldPrediction(
                month=month,
                issue_times=np.asarray([index * 10 + 1, index * 10 + 2], dtype=np.int64),
                local_days=np.asarray([18, 19], dtype=np.int16),
                y_true=truth,
                predictions=prediction,
                best_epoch=0,
                wall_seconds=0.0,
            )
        )
    return tuple(records)


def _seed_summary(pooled: float, horizon_values: tuple[float, float, float], month: float):
    return {
        "pooled": {"mae_a": pooled},
        "by_horizon": [
            {"horizon_minutes": horizon, "mae_a": value}
            for horizon, value in zip(LONG_HORIZONS, horizon_values, strict=True)
        ],
        "by_month": [
            {"month": name, "mae_a": month}
            for name in DEVELOPMENT_MONTHS
        ],
    }


def test_p1_contract_is_long_horizon_arrival_supervision():
    assert LONG_HORIZONS == (60, 120, 240)
    assert AUXILIARY_WEIGHT == 0.5
    assert "code/src/evcf/forecasting/acn_jpl_structured_mechanism_probe.py" in IMPLEMENTATION_PATHS
    assert "docs/JPL_R11_P1_HORIZON_TARGETED_PRIVILEGED_ARRIVAL_PROTOCOL_20260915.md" in (
        IMPLEMENTATION_PATHS
    )


def test_p1_model_has_identical_total_and_arrival_heads_and_station_only_forward():
    torch = pytest.importorskip("torch")
    model = make_p1_tcn(torch)
    assert count_trainable_parameters(model) > 0
    assert tuple(model.total_head.state_dict()) == tuple(model.arrival_head.state_dict())
    forward_parameters = tuple(inspect.signature(model.forward).parameters)
    assert forward_parameters == ("history", "issue_context", "target_context")
    history = torch.zeros((2, 96, 2), dtype=torch.float32)
    issue = torch.zeros((2, 5), dtype=torch.float32)
    target = torch.zeros((2, 3, 6), dtype=torch.float32)
    total, arrival = model(history, issue, target)
    assert total.shape == (2, 3)
    assert arrival.shape == (2, 3)


def test_decision_pass_requires_stable_privileged_gain_and_absolute_value():
    hgb = _hgb_records(mae=10.0)
    arm_b = {
        seed: _seed_summary(9.0 + offset, (9.0, 9.0, 9.0), 9.0)
        for seed, offset in zip(DEEP_SEEDS, (0.0, 0.02, -0.02), strict=True)
    }
    arm_c = {
        seed: _seed_summary(8.8 + offset, (8.8, 8.8, 8.8), 8.8)
        for seed, offset in zip(DEEP_SEEDS, (0.0, 0.01, -0.01), strict=True)
    }
    hybrid = {
        seed: {"pooled": {"mae_a": 9.5 + offset}}
        for seed, offset in zip(DEEP_SEEDS, (0.0, 0.01, -0.01), strict=True)
    }
    decision, support = decide(
        hgb_records=hgb,
        arm_b_seeds=arm_b,
        arm_c_seeds=arm_c,
        arm_c_hybrid_seeds=hybrid,
    )
    assert decision == "PASS_PRIVILEGED_ARRIVAL_SUPERVISION"
    assert support["long_horizon_wins"] == 3
    assert support["month_wins"] == 4
    assert support["paired_seed_wins"] == 3


def test_decision_stop_when_privileged_arm_does_not_improve_control():
    hgb = _hgb_records(mae=10.0)
    arm_b = {seed: _seed_summary(9.0, (9.0, 9.0, 9.0), 9.0) for seed in DEEP_SEEDS}
    arm_c = {seed: _seed_summary(9.1, (9.1, 9.1, 9.1), 9.1) for seed in DEEP_SEEDS}
    hybrid = {seed: {"pooled": {"mae_a": 9.6}} for seed in DEEP_SEEDS}
    decision, _support = decide(
        hgb_records=hgb,
        arm_b_seeds=arm_b,
        arm_c_seeds=arm_c,
        arm_c_hybrid_seeds=hybrid,
    )
    assert decision == "STOP_PRIVILEGED_SUPERVISION_ROUTE"


def test_long_prediction_container_is_aggregate_only():
    prediction = LongFoldPrediction(
        month="2019-01",
        issue_times=np.asarray([1], dtype=np.int64),
        local_days=np.asarray([18], dtype=np.int16),
        y_true=np.ones((1, 3), dtype=np.float64),
        predictions=np.ones((1, 3), dtype=np.float64),
        best_epoch=1,
        wall_seconds=0.1,
    )
    assert prediction.predictions.shape == (1, 3)
    assert not hasattr(prediction, "session_ids")
    assert not hasattr(prediction, "arrival_truth")
