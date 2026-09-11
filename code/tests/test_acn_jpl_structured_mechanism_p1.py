from __future__ import annotations

from types import MappingProxyType

import numpy as np
import pytest

from evcf.forecasting.acn_jpl_development_experts import MonthData
from evcf.forecasting.acn_jpl_structured_baseline import _CleanCurrentSession
from evcf.forecasting.acn_jpl_structured_mechanism_p1 import (
    DEFAULT_PROTOCOL_PATH,
    HORIZONS_MINUTES,
    MechanismP1Error,
    _FoldPreprocessor,
    _IndexedSession,
    _SessionFeatureTable,
    _branch_decision,
    _build_contribution_index,
    _build_month_targets,
    _fit_continuation,
    _fit_gamma_mark,
    _fit_poisson_count,
    _primary_decision,
    load_mechanism_p1_protocol,
    run_mechanism_p1,
)


def _metric(mae: float) -> dict[str, float]:
    return {"mae_a": mae}


def test_protocol_freezes_primary_candidate_and_sixty_min_guard() -> None:
    protocol = load_mechanism_p1_protocol(DEFAULT_PROTOCOL_PATH)
    assert protocol.test_start_local_day == 18
    assert protocol.branch_min_horizon_wins == 3
    assert protocol.branch_min_month_wins == 3
    assert protocol.pass_min_horizon_wins == 3
    assert protocol.pass_min_month_wins == 3
    assert protocol.pass_max_horizon_degradation_fraction == pytest.approx(0.05)


def test_preprocessor_keeps_empty_features_and_fixed_indicators() -> None:
    raw_train = np.asarray(
        [
            [np.nan, 1.0, np.nan],
            [np.nan, 2.0, 3.0],
            [np.nan, 3.0, 4.0],
        ],
        dtype=np.float64,
    )
    raw_test = np.asarray([[np.nan, np.nan, 5.0]], dtype=np.float64)
    preprocessor = _FoldPreprocessor(np.asarray([0, 2], dtype=np.int64))
    train = preprocessor.fit_transform(raw_train)
    test = preprocessor.transform(raw_test)
    assert train.shape == (3, 5)
    assert test.shape == (1, 5)
    assert np.isfinite(train).all()
    assert np.isfinite(test).all()


@pytest.mark.parametrize(("label", "expected"), [(0.0, 0.0), (1.0, 1.0)])
def test_continuation_single_class_uses_frozen_constant(
    label: float,
    expected: float,
) -> None:
    x_train = np.zeros((4, 14), dtype=np.float64)
    y_train = np.full(4, label, dtype=np.float64)
    x_test = np.ones((2, 14), dtype=np.float64)
    prediction, fit_count = _fit_continuation(x_train, y_train, x_test)
    assert fit_count == 0
    assert np.array_equal(prediction, np.full(2, expected))


def test_gamma_and_poisson_degenerate_rules_are_deterministic() -> None:
    x_train = np.zeros((3, 3), dtype=np.float64)
    x_test = np.ones((2, 3), dtype=np.float64)
    indicators = np.asarray([], dtype=np.int64)

    zero_mark, mark_fits = _fit_gamma_mark(
        x_train,
        np.zeros(3),
        x_test,
        indicator_columns=indicators,
    )
    assert mark_fits == 0
    assert np.array_equal(zero_mark, np.zeros(2))

    single_mark, mark_fits = _fit_gamma_mark(
        x_train,
        np.asarray([0.0, 7.5, 0.0]),
        x_test,
        indicator_columns=indicators,
    )
    assert mark_fits == 0
    assert np.array_equal(single_mark, np.full(2, 7.5))

    count, count_fits = _fit_poisson_count(
        x_train,
        np.zeros(3),
        x_test,
        indicator_columns=indicators,
    )
    assert count_fits == 0
    assert np.array_equal(count, np.zeros(2))


def _session(
    index: int,
    connection: int,
    disconnect: int,
    value: float,
) -> _IndexedSession:
    current = _CleanCurrentSession(
        connection_utc_s=connection,
        disconnect_utc_s=disconnect,
        starts=np.asarray([connection], dtype=np.int64),
        ends=np.asarray([disconnect], dtype=np.int64),
        values=np.asarray([value], dtype=np.float64),
    )
    return _IndexedSession(
        session_index=index,
        connection_utc_s=connection,
        disconnect_utc_s=disconnect,
        current=current,
    )


def test_session_and_arrival_targets_reconstruct_exact_components() -> None:
    issue_times = np.asarray([1_000, 3_000], dtype=np.int64)
    sessions = (
        _session(0, 0, 20_000, 10.0),
        _session(1, 2_000, 20_000, 20.0),
    )
    contribution_index = _build_contribution_index(
        sessions=sessions,
        issue_times=issue_times,
    )

    labels = np.zeros((2, len(HORIZONS_MINUTES)), dtype=np.float64)
    for row, issue in enumerate(issue_times):
        for column, horizon in enumerate(HORIZONS_MINUTES):
            start = int(issue) + horizon * 60 - 900
            labels[row, column] = sum(
                item[2] for item in contribution_index.get(start, ())
            )

    data = MonthData(
        month="2019-01",
        issue_times=issue_times,
        labels=labels,
        blocks=MappingProxyType({}),
        processed_snapshot_sha256="0" * 64,
    )
    session_table = _SessionFeatureTable(
        issue_indices=np.asarray([0, 1, 1], dtype=np.int64),
        issue_times=np.asarray([1_000, 3_000, 3_000], dtype=np.int64),
        session_indices=np.asarray([0, 0, 1], dtype=np.int64),
        raw_features=np.zeros((3, 14), dtype=np.float64),
    )

    targets = _build_month_targets(
        data=data,
        session_table=session_table,
        contributions=contribution_index,
    )
    assert np.allclose(
        targets.existing_total + targets.arrival_total,
        labels,
        rtol=0,
        atol=1e-6,
    )
    assert np.allclose(
        targets.arrival_count * targets.arrival_mark,
        targets.arrival_total,
        rtol=0,
        atol=1e-6,
    )
    for column in range(len(HORIZONS_MINUTES)):
        reconstructed = np.zeros(2)
        np.add.at(
            reconstructed,
            session_table.issue_indices,
            targets.session_contribution[:, column],
        )
        assert np.allclose(
            reconstructed,
            targets.existing_total[:, column],
            rtol=0,
            atol=1e-6,
        )


def _bundle(
    p1: float,
    equal: float,
    s1: float,
    p1_existing: float = 4.0,
    s1_existing: float = 5.0,
    p1_arrival: float = 4.0,
    s1_arrival: float = 5.0,
) -> dict[str, dict[str, float]]:
    return {
        "P1-EA": _metric(p1),
        "equal": _metric(equal),
        "S1": _metric(s1),
        "P1_existing": _metric(p1_existing),
        "S1_existing": _metric(s1_existing),
        "P1_arrival": _metric(p1_arrival),
        "S1_arrival": _metric(s1_arrival),
    }


def test_frozen_branch_and_primary_decisions() -> None:
    protocol = load_mechanism_p1_protocol(DEFAULT_PROTOCOL_PATH)
    pooled = _bundle(8.0, 10.0, 9.0)
    by_horizon = [
        {"horizon_minutes": horizon, "metrics": _bundle(8.0, 10.0, 9.0)}
        for horizon in HORIZONS_MINUTES
    ]
    by_month = [
        {"month": month, "metrics": _bundle(8.0, 10.0, 9.0)}
        for month in ("2019-01", "2019-04", "2019-07", "2019-10")
    ]

    existing, _ = _branch_decision(
        pooled=pooled,
        by_horizon=by_horizon,
        by_month=by_month,
        new_key="P1_existing",
        old_key="S1_existing",
        min_horizon_wins=3,
        min_month_wins=3,
    )
    arrival, _ = _branch_decision(
        pooled=pooled,
        by_horizon=by_horizon,
        by_month=by_month,
        new_key="P1_arrival",
        old_key="S1_arrival",
        min_horizon_wins=3,
        min_month_wins=3,
    )
    decision, evidence = _primary_decision(
        protocol=protocol,
        pooled=pooled,
        by_horizon=by_horizon,
        by_month=by_month,
        existing_branch_decision=existing,
        arrival_branch_decision=arrival,
    )
    assert existing == "STABLE_COMPONENT_SIGNAL"
    assert arrival == "STABLE_COMPONENT_SIGNAL"
    assert decision == "PASS_MECHANISM_PROBE"
    assert evidence["sixty_min_better_than_equal"] is True

    mixed_horizon = [
        {
            "horizon_minutes": horizon,
            "metrics": _bundle(
                11.0 if horizon == 60 else 8.0,
                10.0,
                9.0,
            ),
        }
        for horizon in HORIZONS_MINUTES
    ]
    decision, _ = _primary_decision(
        protocol=protocol,
        pooled=pooled,
        by_horizon=mixed_horizon,
        by_month=by_month,
        existing_branch_decision=existing,
        arrival_branch_decision=arrival,
    )
    assert decision == "MIXED_MECHANISM_PROBE"

    stop_pooled = _bundle(
        11.0,
        10.0,
        9.0,
        p1_existing=6.0,
        s1_existing=5.0,
        p1_arrival=6.0,
        s1_arrival=5.0,
    )
    stop_horizon = [
        {"horizon_minutes": horizon, "metrics": stop_pooled}
        for horizon in HORIZONS_MINUTES
    ]
    stop_month = [
        {"month": month, "metrics": stop_pooled}
        for month in ("2019-01", "2019-04", "2019-07", "2019-10")
    ]
    decision, _ = _primary_decision(
        protocol=protocol,
        pooled=stop_pooled,
        by_horizon=stop_horizon,
        by_month=stop_month,
        existing_branch_decision="NO_COMPONENT_SIGNAL",
        arrival_branch_decision="NO_COMPONENT_SIGNAL",
    )
    assert decision == "STOP_MECHANISM_ROUTE"


def test_holdout_path_fails_closed_before_any_fit(tmp_path) -> None:
    interim = tmp_path / "interim"
    processed = tmp_path / "processed"
    baseline = tmp_path / "baseline"
    s1 = tmp_path / "s1"
    for path in (interim, processed, baseline, s1):
        path.mkdir()
    (processed / "2019-03").mkdir()

    with pytest.raises(MechanismP1Error, match="HOLDOUT_PATH_PRESENT"):
        run_mechanism_p1(
            authorized=True,
            interim_root=interim,
            processed_root=processed,
            baseline_private_root=baseline,
            s1_private_root=s1,
            private_output_root=tmp_path / "output",
            code_commit="0" * 40,
            repo_root=tmp_path,
        )
