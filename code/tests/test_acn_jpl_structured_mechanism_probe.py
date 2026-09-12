from __future__ import annotations

from datetime import datetime
from types import MappingProxyType
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from evcf.forecasting.acn_jpl_development_experts import MonthData
from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock, canonical_feature_schema
from evcf.forecasting.acn_jpl_structured_mechanism_probe import (
    _CurrentSession,
    _a_targets,
    _branch_signal,
    _build_contributions,
    _component_labels,
    _fit_arrival_count,
    _fit_continuation,
    _fit_positive_mark,
    _fit_transform_a,
    _fit_transform_e,
    _predict_horizon,
    _primary_decision,
)

_ZONE = ZoneInfo("America/Los_Angeles")


def _epoch(day: int, hour: int) -> int:
    return int(datetime(2019, 1, day, hour, tzinfo=_ZONE).timestamp())


def test_contribution_identity_and_arrival_count_mark() -> None:
    session0 = _CurrentSession(
        session_index=0,
        connection_utc_s=_epoch(1, 0),
        disconnect_utc_s=_epoch(1, 4),
        starts=np.asarray([_epoch(1, 0)], dtype=np.int64),
        ends=np.asarray([_epoch(1, 4)], dtype=np.int64),
        values=np.asarray([10.0], dtype=np.float64),
    )
    session1 = _CurrentSession(
        session_index=1,
        connection_utc_s=_epoch(1, 1),
        disconnect_utc_s=_epoch(1, 4),
        starts=np.asarray([_epoch(1, 1)], dtype=np.int64),
        ends=np.asarray([_epoch(1, 4)], dtype=np.int64),
        values=np.asarray([6.0], dtype=np.float64),
    )
    issue_times = np.asarray([_epoch(1, 0)], dtype=np.int64)
    total = np.asarray([[10.0, 10.0, 10.0, 16.0, 16.0]], dtype=np.float64)
    contributions = _build_contributions((session0, session1), issue_times)
    existing, arrival, _session_maps = _component_labels(
        issue_times=issue_times,
        total_labels=total,
        contributions=contributions,
    )
    assert existing[0].tolist() == pytest.approx([10.0, 10.0, 10.0, 10.0, 10.0])
    assert arrival[0].tolist() == pytest.approx([0.0, 0.0, 0.0, 6.0, 6.0])
    count, mark = _a_targets(
        issue_times=issue_times,
        arrival_labels=arrival,
        contributions=contributions,
        horizon_position=3,
    )
    assert count.tolist() == [1.0]
    assert mark.tolist() == pytest.approx([6.0])


def test_preprocessing_and_degenerate_rules() -> None:
    e_train = np.zeros((4, 14), dtype=np.float64)
    e_test = np.zeros((2, 14), dtype=np.float64)
    e_train[0, 1] = np.nan
    e_test[0, 1] = np.nan
    x_train, x_test = _fit_transform_e(e_train, e_test)
    assert x_train.shape == (4, 25)
    assert x_test.shape == (2, 25)
    assert np.isfinite(x_train).all()
    assert np.isfinite(x_test).all()

    names, nullable = canonical_feature_schema("M2")
    values = np.zeros((6, len(names)), dtype=np.float64)
    values[0, nullable] = np.nan
    block = FeatureBlock(
        np.arange(6, dtype=np.int64) + 1,
        values,
        names,
        nullable,
    )
    a_train, a_test = _fit_transform_a(
        block.values,
        block.nullable_mask,
        np.asarray([0, 1, 2, 3], dtype=np.int64),
        np.asarray([4, 5], dtype=np.int64),
    )
    assert a_train.shape[1] == 204
    assert a_test.shape[1] == 204

    probability, fits, constants = _fit_continuation(
        x_train,
        np.zeros(4, dtype=np.float64),
        x_test,
    )
    assert fits == 0 and constants == 1
    assert probability.tolist() == [0.0, 0.0]

    mark, fits, constants = _fit_positive_mark(
        x_train,
        np.asarray([0.0, 3.5, 0.0, 0.0]),
        np.asarray([False, True, False, False]),
        x_test,
    )
    assert fits == 0 and constants == 1
    assert mark.tolist() == [3.5, 3.5]

    count, fits, constants = _fit_arrival_count(
        a_train,
        np.zeros(4, dtype=np.float64),
        a_test,
    )
    assert fits == 0 and constants == 1
    assert count.tolist() == [0.0, 0.0]


def test_rolling_probe_produces_aligned_nonnegative_predictions() -> None:
    issue_times = np.asarray(
        [_epoch(day, hour) for day in range(1, 5) for hour in (0, 6, 12, 18)],
        dtype=np.int64,
    )
    names, nullable = canonical_feature_schema("M2")
    values = np.zeros((len(issue_times), len(names)), dtype=np.float64)
    values[:, 0] = np.arange(len(issue_times), dtype=np.float64)
    block = FeatureBlock(issue_times, values, names, nullable)
    data = MonthData(
        month="2019-01",
        issue_times=issue_times,
        labels=np.zeros((len(issue_times), 5), dtype=np.float64),
        blocks=MappingProxyType({"M2": block}),
        processed_snapshot_sha256="x" * 64,
    )
    e_raw_groups = tuple(
        np.asarray(
            [
                [
                    float(index),
                    0.0,
                    5.0,
                    5.0,
                    5.0,
                    1.0,
                    1.0,
                    1.0,
                    6.0,
                    np.nan,
                    np.nan,
                    0.0,
                    0.0,
                    0.0,
                ]
            ],
            dtype=np.float64,
        )
        for index in range(len(issue_times))
    )
    e_label_groups = tuple(
        np.asarray([2.0 if index % 2 else 0.0], dtype=np.float64)
        for index in range(len(issue_times))
    )
    existing = np.zeros((len(issue_times), 5), dtype=np.float64)
    existing[:, 2] = np.asarray([group[0] for group in e_label_groups])
    counts = np.asarray([float(index % 3) for index in range(len(issue_times))])
    marks = np.where(counts > 0, 1.5 + 0.1 * np.arange(len(issue_times)), 0.0)
    arrival = np.zeros((len(issue_times), 5), dtype=np.float64)
    arrival[:, 2] = counts * marks

    result = _predict_horizon(
        data=data,
        existing_labels=existing,
        arrival_labels=arrival,
        e_raw_groups=e_raw_groups,
        e_label_groups=e_label_groups,
        arrival_counts=counts,
        arrival_marks=marks,
        horizon_minutes=60,
        test_start_local_day=3,
    )
    assert len(result.issue_times) == 8
    assert np.all(result.e_predictions >= 0)
    assert np.all(result.a_predictions >= 0)
    assert np.all(result.continuation_probability >= 0)
    assert np.all(result.continuation_probability <= 1)


def test_frozen_decisions() -> None:
    assert (
        _branch_signal(
            pooled_new=9.0,
            pooled_old=10.0,
            horizon_wins=3,
            month_wins=3,
        )
        == "STABLE_COMPONENT_SIGNAL"
    )
    assert (
        _primary_decision(
            ea_pooled=8.0,
            equal_pooled=9.0,
            s1_pooled=8.5,
            horizon_wins=4,
            month_wins=3,
            max_horizon_degradation=0.02,
            h60_mae=7.0,
            h60_equal=7.5,
            e_signal="STABLE_COMPONENT_SIGNAL",
            a_signal="STABLE_COMPONENT_SIGNAL",
        )
        == "PASS_MECHANISM_PROBE"
    )
    assert (
        _primary_decision(
            ea_pooled=9.2,
            equal_pooled=9.0,
            s1_pooled=9.3,
            horizon_wins=2,
            month_wins=2,
            max_horizon_degradation=0.06,
            h60_mae=8.0,
            h60_equal=7.5,
            e_signal="MIXED_COMPONENT_SIGNAL",
            a_signal="NO_COMPONENT_SIGNAL",
        )
        == "MIXED_MECHANISM_PROBE"
    )
    assert (
        _primary_decision(
            ea_pooled=10.0,
            equal_pooled=9.0,
            s1_pooled=9.5,
            horizon_wins=1,
            month_wins=1,
            max_horizon_degradation=0.10,
            h60_mae=9.0,
            h60_equal=8.0,
            e_signal="NO_COMPONENT_SIGNAL",
            a_signal="NO_COMPONENT_SIGNAL",
        )
        == "STOP_MECHANISM_ROUTE"
    )
