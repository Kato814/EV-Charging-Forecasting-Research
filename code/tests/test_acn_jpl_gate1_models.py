from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from evcf.forecasting.acn_jpl_gate1_contracts import load_gate1_config
from evcf.forecasting.acn_jpl_gate1_data import Gate1Snapshot
from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock
from evcf.forecasting.acn_jpl_gate1_models import (
    Gate1TimeSplit,
    HGBPreprocessor,
    PredictionBundle,
    RidgePreprocessor,
    SelectionRecord,
    build_model_selection_manifest,
    frozen_model_candidates,
    make_frozen_estimator,
    persistence_predictions,
    rolling_origin_predict,
    select_model_params,
)
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "code/configs/acn_jpl_gate1_pilot_2019-05.yaml"
ZONE = ZoneInfo("America/Los_Angeles")
HORIZONS = (15, 30, 60, 120, 240)
TIERS = ("M1", "M2", "M3", "M4")
LEARNERS = ("ridge", "hgb")
RAW_DIMENSIONS = {"M1": 195, "M2": 201, "M3": 311, "M4": 671}
INDICATOR_COUNTS = {"M1": 0, "M2": 3, "M3": 80, "M4": 332}


def _epoch(local_iso: str) -> int:
    return int(datetime.fromisoformat(local_iso).timestamp())


def _formal_issue_times() -> np.ndarray:
    train = np.arange(
        _epoch("2019-05-02T00:00:00-07:00"),
        _epoch("2019-05-15T00:00:00-07:00"),
        900,
        dtype=np.int64,
    )
    validation_full = np.arange(
        _epoch("2019-05-15T00:00:00-07:00"),
        _epoch("2019-05-18T00:00:00-07:00"),
        900,
        dtype=np.int64,
    )
    validation = validation_full[12:]
    test = np.arange(
        _epoch("2019-05-18T00:00:00-07:00"),
        _epoch("2019-05-18T00:00:00-07:00") + 1_329 * 900,
        900,
        dtype=np.int64,
    )
    result = np.concatenate((train, validation, test))
    assert result.shape == (2_853,)
    return result


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    return load_gate1_config(CONFIG_PATH)


@pytest.fixture(scope="module")
def split(config: Mapping[str, Any]) -> Gate1TimeSplit:
    return Gate1TimeSplit.from_config(_formal_issue_times(), config)


def _block(tier: str, issue_times: np.ndarray, *, seed: int = 3) -> FeatureBlock:
    raw_dimension = RAW_DIMENSIONS[tier]
    indicator_count = INDICATOR_COUNTS[tier]
    generator = np.random.default_rng(seed)
    values = generator.normal(size=(len(issue_times), raw_dimension))
    nullable = np.zeros(raw_dimension, dtype=np.bool_)
    if indicator_count:
        nullable[-indicator_count:] = True
        values[::17, -indicator_count] = np.nan
    return FeatureBlock(
        issue_times=issue_times,
        values=values,
        feature_names=tuple(f"{tier.lower()}_{position:04d}" for position in range(raw_dimension)),
        nullable_mask=nullable,
    )


def _target(issue_times: np.ndarray) -> np.ndarray:
    return 10.0 + np.sin(np.arange(len(issue_times), dtype=np.float64) / 13.0)


def test_frozen_pdt_split_exact_counts_days_and_coverage(split: Gate1TimeSplit) -> None:
    assert len(split.train_rows) == 1_248
    assert len(split.validation_rows) == 276
    assert len(split.test_rows) == 1_329
    assert len(split.test_day_rows) == 14
    assert [len(rows) for rows in split.test_day_rows.values()] == [96] * 13 + [81]
    assert list(split.test_day_rows) == [
        _epoch(f"2019-05-{day:02d}T00:00:00-07:00") for day in range(18, 32)
    ]

    all_rows = np.concatenate((split.train_rows, split.validation_rows, split.test_rows))
    np.testing.assert_array_equal(np.sort(all_rows), np.arange(2_853))
    assert len(np.unique(all_rows)) == 2_853
    with pytest.raises(ValueError, match="2,853|2853"):
        Gate1TimeSplit.from_config(_formal_issue_times()[:-1], split.config)
    off_grid = _formal_issue_times()
    off_grid[100] += 1
    with pytest.raises(ValueError, match="15-minute"):
        Gate1TimeSplit.from_config(off_grid, split.config)


def test_label_availability_and_rolling_fit_rows_are_exact(split: Gate1TimeSplit) -> None:
    expected_selection = {
        15: (1_248, 276),
        30: (1_247, 275),
        60: (1_245, 273),
        120: (1_241, 269),
        240: (1_233, 261),
    }
    expected_first = {15: 1_524, 30: 1_523, 60: 1_521, 120: 1_517, 240: 1_509}
    expected_last = {15: 2_772, 30: 2_771, 60: 2_769, 120: 2_765, 240: 2_757}

    for horizon in HORIZONS:
        availability = split.label_availability_times(horizon)
        np.testing.assert_array_equal(availability, split.issue_times + horizon * 60)
        assert len(split.selection_fit_rows(horizon)) == expected_selection[horizon][0]
        assert len(split.validation_score_rows(horizon)) == expected_selection[horizon][1]
        rolling = split.rolling_fit_rows(horizon)
        assert len(rolling[next(iter(rolling))]) == expected_first[horizon]
        assert len(rolling[next(reversed(rolling))]) == expected_last[horizon]
        for day_start, rows in rolling.items():
            assert np.all(split.issue_times[rows] < day_start)
            assert np.all(availability[rows] <= day_start)
            assert np.intersect1d(rows, split.test_day_rows[day_start]).size == 0
            for _tier in TIERS:
                np.testing.assert_array_equal(rows, split.rolling_fit_rows(horizon)[day_start])


def _station_snapshot(
    issue_times: np.ndarray,
    station_times: np.ndarray,
    station_values: np.ndarray,
    station_valid: np.ndarray,
) -> Gate1Snapshot:
    row_count = len(issue_times)
    return Gate1Snapshot(
        data_snapshot_sha256="a" * 64,
        artifact_sha256={},
        issue_times=issue_times,
        horizons=np.asarray(HORIZONS, dtype=np.int16),
        labels=np.zeros((row_count, len(HORIZONS)), dtype=np.float64),
        m1_history=np.zeros((row_count, 96), dtype=np.float64),
        m1_history_mask=np.ones((row_count, 96), dtype=np.bool_),
        m1_calendar=np.zeros((row_count, 3), dtype=np.int16),
        m2_current_state=np.zeros((row_count, 6), dtype=np.float64),
        m3_rows=(),
        m4_rows=(),
        m3_by_issue_time=tuple(() for _ in range(row_count)),
        m4_by_issue_time=tuple(() for _ in range(row_count)),
        station_times=station_times,
        station_current_mean_a=station_values,
        station_valid_90=station_valid,
    )


def test_persistence_uses_exact_station_bins_and_never_falls_back() -> None:
    issue = _epoch("2019-05-18T01:00:00-07:00")
    last = issue - 900
    target_start = issue + 60 * 60 - 900
    previous_day = _epoch("2019-05-17T01:45:00-07:00")
    previous_week = _epoch("2019-05-11T01:45:00-07:00")
    earlier = last - 900
    station_times = np.asarray(sorted([earlier, last, previous_day, previous_week]), dtype=np.int64)
    station_values = np.asarray([float(value % 101) for value in station_times], dtype=np.float64)
    station_valid = np.ones(len(station_times), dtype=np.bool_)
    station_valid[np.flatnonzero(station_times == last)[0]] = False
    snapshot = _station_snapshot(
        np.asarray([issue], dtype=np.int64), station_times, station_values, station_valid
    )

    predictions = persistence_predictions(snapshot, np.asarray([0]), horizon_minutes=60)
    assert tuple(predictions) == ("last_value", "previous_day", "previous_week")
    last_result = predictions["last_value"]
    assert last_result.reference_times[0] == last
    assert not last_result.availability[0]
    assert np.isnan(last_result.predictions[0])
    assert station_times[np.flatnonzero(station_times == earlier)[0]] == earlier
    assert predictions["previous_day"].reference_times[0] == previous_day
    assert predictions["previous_week"].reference_times[0] == previous_week
    assert predictions["previous_day"].availability[0]
    assert predictions["previous_week"].availability[0]
    assert target_start == _epoch("2019-05-18T01:45:00-07:00")

    poisoned_values = station_values.copy()
    poisoned_values[np.flatnonzero(station_times == previous_week)[0]] = np.inf
    poisoned = _station_snapshot(
        np.asarray([issue], dtype=np.int64), station_times, poisoned_values, station_valid
    )
    result = persistence_predictions(poisoned, np.asarray([0]), horizon_minutes=60)
    assert not result["previous_week"].availability[0]
    assert np.isnan(result["previous_week"].predictions[0])


def test_ridge_preprocessing_is_training_only_fixed_and_dimensioned() -> None:
    times = np.arange(12, dtype=np.int64) + 10
    block = _block("M2", times)
    poisoned = block.values.copy()
    poisoned[7:, 0] = 1e12
    poisoned[7:, -1] = np.nan
    poisoned_block = FeatureBlock(times, poisoned, block.feature_names, block.nullable_mask)
    fit_rows = np.arange(7, dtype=np.int64)

    clean_processor = RidgePreprocessor().fit(block, fit_rows)
    poison_processor = RidgePreprocessor().fit(poisoned_block, fit_rows)
    np.testing.assert_array_equal(clean_processor.medians, poison_processor.medians)
    np.testing.assert_array_equal(clean_processor.means, poison_processor.means)
    np.testing.assert_array_equal(clean_processor.scales, poison_processor.scales)
    assert clean_processor.input_dimension == 204
    transformed = clean_processor.transform(poisoned_block, np.arange(12))
    assert transformed.shape == (12, 204)
    assert np.isfinite(transformed).all()

    constant = block.values.copy()
    constant[:, 0] = 4.0
    constant_block = FeatureBlock(times, constant, block.feature_names, block.nullable_mask)
    constant_processor = RidgePreprocessor().fit(constant_block, fit_rows)
    assert constant_processor.scales[0] == 1.0


def test_preprocessors_fail_closed_on_schema_all_nan_and_infinity() -> None:
    times = np.arange(8, dtype=np.int64) + 1
    block = _block("M3", times)
    all_nan = block.values.copy()
    all_nan[:5, 4] = np.nan
    all_nan_block = FeatureBlock(times, all_nan, block.feature_names, block.nullable_mask)
    with pytest.raises(ValueError, match="all-NaN|all missing|m3_0004"):
        RidgePreprocessor().fit(all_nan_block, np.arange(5))

    hgb = HGBPreprocessor().fit(block, np.arange(5))
    encoded = hgb.transform(block, np.arange(8))
    assert hgb.input_dimension == 391
    assert np.isnan(encoded[0, -INDICATOR_COUNTS["M3"] - 1]) == np.isnan(
        block.values[0, -INDICATOR_COUNTS["M3"] - 1]
    )
    assert np.isnan(encoded[:, : RAW_DIMENSIONS["M3"]]).sum() == np.isnan(block.values).sum()
    assert set(np.unique(encoded[:, RAW_DIMENSIONS["M3"] :])).issubset({0.0, 1.0})

    changed_names = FeatureBlock(
        times,
        block.values,
        ("changed",) + block.feature_names[1:],
        block.nullable_mask,
    )
    with pytest.raises(ValueError, match="schema"):
        hgb.transform(changed_names, np.arange(8))

    with pytest.raises(ValueError, match="infinite|infinity"):
        HGBPreprocessor().transform_values(
            np.full((1, RAW_DIMENSIONS["M3"]), np.inf),
            feature_names=block.feature_names,
            nullable_mask=block.nullable_mask,
        )


class _ConstantEstimator:
    def __init__(self, value: float, calls: list[tuple[int, int]]) -> None:
        self.value = value
        self.calls = calls

    def fit(self, x: np.ndarray, y: np.ndarray) -> _ConstantEstimator:
        self.calls.append((len(x), len(y)))
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.full(len(x), self.value, dtype=np.float64)


class _MeanEstimator:
    def fit(self, x: np.ndarray, y: np.ndarray) -> _MeanEstimator:
        self.value = float(np.mean(y))
        return self

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.full(len(x), self.value, dtype=np.float64)


def test_full_candidate_budgets_ties_and_canonical_hash(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    block = _block("M1", split.issue_times)
    target = _target(split.issue_times)
    ridge_calls: list[tuple[int, int]] = []
    hgb_calls: list[tuple[int, int]] = []

    ridge_record = select_model_params(
        learner="ridge",
        tier="M1",
        horizon_minutes=15,
        feature_block=block,
        target=target,
        split=split,
        config=config,
        estimator_factory=lambda _learner, _params: _ConstantEstimator(3.0, ridge_calls),
    )
    hgb_record = select_model_params(
        learner="hgb",
        tier="M1",
        horizon_minutes=15,
        feature_block=block,
        target=target,
        split=split,
        config=config,
        estimator_factory=lambda _learner, _params: _ConstantEstimator(3.0, hgb_calls),
    )

    assert len(ridge_calls) == 4
    assert len(hgb_calls) == 16
    assert all(call == (1_248, 1_248) for call in ridge_calls + hgb_calls)
    assert ridge_record.selected_candidate_index == 0
    assert hgb_record.selected_candidate_index == 0
    assert ridge_record.selected_params["alpha"] == 0.1
    assert hgb_record.selected_params["learning_rate"] == 0.03
    assert len(ridge_record.selected_param_sha256) == 64
    assert ridge_record.candidate_validation_mae.dtype == np.float64
    with pytest.raises(ValueError, match="candidate budget"):
        SelectionRecord.create(
            learner="ridge",
            tier="M1",
            horizon_minutes=15,
            candidate_params=frozen_model_candidates("ridge", config)[:-1],
            candidate_validation_mae=[1.0, 1.0, 1.0],
            selected_candidate_index=0,
            selection_fit_count=1_248,
            validation_score_count=276,
        )


def test_selection_executes_every_candidate_or_fails(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    block = _block("M1", split.issue_times)
    calls = 0

    def factory(_learner: str, _params: Mapping[str, Any]) -> _ConstantEstimator:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("intentional candidate failure")
        return _ConstantEstimator(1.0, [])

    with pytest.raises(RuntimeError, match="candidate 2"):
        select_model_params(
            learner="ridge",
            tier="M1",
            horizon_minutes=30,
            feature_block=block,
            target=_target(split.issue_times),
            split=split,
            config=config,
            estimator_factory=factory,
        )
    assert calls == 3


def test_rolling_refits_once_per_day_without_retuning_or_clipping(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    block = _block("M1", split.issue_times)
    target = _target(split.issue_times)
    selected = SelectionRecord.create(
        learner="ridge",
        tier="M1",
        horizon_minutes=60,
        candidate_params=frozen_model_candidates("ridge", config),
        candidate_validation_mae=[4.0, 3.0, 2.0, 1.0],
        selected_candidate_index=3,
        selection_fit_count=1_245,
        validation_score_count=273,
    )
    calls: list[tuple[int, int]] = []
    factory_parameters: list[dict[str, Any]] = []

    def factory(learner: str, params: Mapping[str, Any]) -> _ConstantEstimator:
        assert learner == "ridge"
        factory_parameters.append(dict(params))
        return _ConstantEstimator(-2.5, calls)

    result = rolling_origin_predict(
        feature_block=block,
        target=target,
        split=split,
        selection=selected,
        estimator_factory=factory,
    )
    assert len(calls) == 14
    assert [count for count, _ in calls] == [1_521 + 96 * day for day in range(14)]
    assert len(factory_parameters) == 14
    assert all(params == selected.selected_params for params in factory_parameters)
    assert np.all(result.predictions == -2.5)
    assert len(np.unique(result.parameter_hashes)) == 1
    assert np.unique(result.parameter_hashes)[0].decode() == selected.selected_param_sha256
    np.testing.assert_array_equal(result.issue_times, split.issue_times[split.test_rows])
    np.testing.assert_array_equal(result.y_true, target[split.test_rows])
    with pytest.raises(ValueError):
        result.predictions[0] = 0.0

    repeat = rolling_origin_predict(
        feature_block=block,
        target=target,
        split=split,
        selection=selected,
        estimator_factory=factory,
    )
    np.testing.assert_array_equal(result.predictions, repeat.predictions)


def test_rolling_nonfinite_prediction_is_execution_failure(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    selected = SelectionRecord.create(
        learner="hgb",
        tier="M1",
        horizon_minutes=15,
        candidate_params=frozen_model_candidates("hgb", config),
        candidate_validation_mae=np.arange(16, dtype=np.float64),
        selected_candidate_index=0,
        selection_fit_count=1_248,
        validation_score_count=276,
    )
    with pytest.raises(ValueError, match="non-finite"):
        rolling_origin_predict(
            feature_block=_block("M1", split.issue_times),
            target=_target(split.issue_times),
            split=split,
            selection=selected,
            estimator_factory=lambda _learner, _params: _ConstantEstimator(np.nan, []),
        )


def test_selection_and_midnight_refit_ignore_unavailable_labels(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    block = _block("M1", split.issue_times)
    target = _target(split.issue_times)
    poisoned_test = target.copy()
    poisoned_test[split.test_rows] += 1e9
    factory = lambda _learner, _params: _MeanEstimator()
    baseline_selection = select_model_params(
        learner="ridge",
        tier="M1",
        horizon_minutes=15,
        feature_block=block,
        target=target,
        split=split,
        config=config,
        estimator_factory=factory,
    )
    poisoned_selection = select_model_params(
        learner="ridge",
        tier="M1",
        horizon_minutes=15,
        feature_block=block,
        target=poisoned_test,
        split=split,
        config=config,
        estimator_factory=factory,
    )
    np.testing.assert_array_equal(
        baseline_selection.candidate_validation_mae,
        poisoned_selection.candidate_validation_mae,
    )

    first_day_rows = next(iter(split.test_day_rows.values()))
    poisoned_day = target.copy()
    poisoned_day[first_day_rows] += 1e9
    baseline_roll = rolling_origin_predict(
        feature_block=block,
        target=target,
        split=split,
        selection=baseline_selection,
        estimator_factory=factory,
    )
    poisoned_roll = rolling_origin_predict(
        feature_block=block,
        target=poisoned_day,
        split=split,
        selection=baseline_selection,
        estimator_factory=factory,
    )
    np.testing.assert_array_equal(
        baseline_roll.predictions[: len(first_day_rows)],
        poisoned_roll.predictions[: len(first_day_rows)],
    )


def test_real_sklearn_ridge_and_hgb_smoke(config: Mapping[str, Any]) -> None:
    generator = np.random.default_rng(20260901)
    x = generator.normal(size=(40, 5))
    y = x[:, 0] - 0.5 * x[:, 1]
    ridge = make_frozen_estimator("ridge", frozen_model_candidates("ridge", config)[0])
    hgb = make_frozen_estimator("hgb", frozen_model_candidates("hgb", config)[0])
    assert isinstance(ridge, Ridge)
    assert isinstance(hgb, HistGradientBoostingRegressor)
    assert hgb.categorical_features is None
    assert hgb.early_stopping is False
    for estimator in (ridge, hgb):
        prediction = estimator.fit(x, y).predict(x[:3])
        assert prediction.shape == (3,)
        assert np.isfinite(prediction).all()
        repeated = (
            make_frozen_estimator(
                "ridge" if isinstance(estimator, Ridge) else "hgb",
                frozen_model_candidates("ridge" if isinstance(estimator, Ridge) else "hgb", config)[
                    0
                ],
            )
            .fit(x, y)
            .predict(x[:3])
        )
        np.testing.assert_array_equal(prediction, repeated)


def _dummy_record(
    learner: str,
    tier: str,
    horizon: int,
    config: Mapping[str, Any],
    split: Gate1TimeSplit,
) -> SelectionRecord:
    candidates = frozen_model_candidates(learner, config)
    return SelectionRecord.create(
        learner=learner,
        tier=tier,
        horizon_minutes=horizon,
        candidate_params=candidates,
        candidate_validation_mae=np.linspace(1.0, 2.0, len(candidates)),
        selected_candidate_index=0,
        selection_fit_count=len(split.selection_fit_rows(horizon)),
        validation_score_count=len(split.validation_score_rows(horizon)),
    )


def _dummy_prediction(
    record: SelectionRecord, split: Gate1TimeSplit, target: np.ndarray
) -> PredictionBundle:
    test_rows = split.test_rows
    day_starts = np.empty(len(test_rows), dtype=np.int64)
    for day, rows in split.test_day_rows.items():
        positions = np.searchsorted(test_rows, rows)
        day_starts[positions] = day
    return PredictionBundle.create(
        learner=record.learner,
        tier=record.tier,
        horizon_minutes=record.horizon_minutes,
        issue_times=split.issue_times[test_rows],
        y_true=target[test_rows],
        predictions=target[test_rows] - 0.1,
        day_start_utc_s=day_starts,
        selected_param_sha256=record.selected_param_sha256,
    )


def test_manifest_is_complete_aggregate_only_and_fail_closed(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    target = _target(split.issue_times)
    records = [
        _dummy_record(learner, tier, horizon, config, split)
        for learner in LEARNERS
        for tier in TIERS
        for horizon in HORIZONS
    ]
    predictions = [_dummy_prediction(record, split, target) for record in records]
    coverage = {
        baseline: {
            str(horizon): 1_329 if baseline != "previous_week" else 1_326 for horizon in HORIZONS
        }
        for baseline in ("last_value", "previous_day", "previous_week")
    }
    manifest = build_model_selection_manifest(
        config=config,
        split=split,
        selections=records,
        predictions=predictions,
        feature_dimensions={
            tier: {
                "raw": RAW_DIMENSIONS[tier],
                "indicators": INDICATOR_COUNTS[tier],
                "input": RAW_DIMENSIONS[tier] + INDICATOR_COUNTS[tier],
            }
            for tier in TIERS
        },
        persistence_coverage=coverage,
    )
    assert manifest["schema_version"] == "acn-jpl-gate1-model-selection/v1"
    assert len(manifest["selections"]) == 40
    assert manifest["candidate_budgets"] == {"ridge": 4, "hgb": 16}
    assert manifest["test_refit_count_per_task"] == 14
    encoded = json.dumps(manifest, sort_keys=True, allow_nan=False)
    assert "C:\\\\" not in encoded
    assert "/home/" not in encoded
    assert "predictions" not in encoded.lower()
    assert "preprocessor_statistics" not in encoded
    assert "issue_times" not in manifest

    with pytest.raises(ValueError, match="40|complete"):
        build_model_selection_manifest(
            config=config,
            split=split,
            selections=records[:-1],
            predictions=predictions[:-1],
            feature_dimensions=manifest["preprocessing"]["tier_dimensions"],
            persistence_coverage=coverage,
        )

    changed_truth = predictions[5].y_true.copy()
    changed_truth[0] += 1.0
    inconsistent = list(predictions)
    inconsistent[5] = PredictionBundle.create(
        learner=predictions[5].learner,
        tier=predictions[5].tier,
        horizon_minutes=predictions[5].horizon_minutes,
        issue_times=predictions[5].issue_times,
        y_true=changed_truth,
        predictions=predictions[5].predictions,
        day_start_utc_s=predictions[5].day_start_utc_s,
        selected_param_sha256=records[5].selected_param_sha256,
    )
    with pytest.raises(ValueError, match="truth differs"):
        build_model_selection_manifest(
            config=config,
            split=split,
            selections=records,
            predictions=inconsistent,
            feature_dimensions=manifest["preprocessing"]["tier_dimensions"],
            persistence_coverage=coverage,
        )


def test_prediction_bundle_rejects_mixed_parameter_hashes() -> None:
    issue_times = np.asarray([1, 2], dtype=np.int64)
    with pytest.raises(ValueError, match="parameter hash"):
        PredictionBundle(
            learner="ridge",
            tier="M1",
            horizon_minutes=15,
            issue_times=issue_times,
            y_true=np.ones(2),
            predictions=np.ones(2),
            day_start_utc_s=np.asarray([0, 0], dtype=np.int64),
            parameter_hashes=np.asarray([b"a" * 64, b"b" * 64], dtype="S64"),
        )


def test_local_calendar_shift_survives_dst_boundary() -> None:
    origin_local = datetime(2019, 3, 11, 1, 0, tzinfo=ZONE)
    issue = int(origin_local.timestamp())
    expected_reference = int(datetime(2019, 3, 10, 1, 45, tzinfo=ZONE).timestamp())
    station_times = np.asarray([issue - 900, expected_reference], dtype=np.int64)
    order = np.argsort(station_times)
    station_times = station_times[order]
    snapshot = _station_snapshot(
        np.asarray([issue], dtype=np.int64),
        station_times,
        np.asarray([4.0, 7.0], dtype=np.float64)[order],
        np.ones(2, dtype=np.bool_),
    )
    result = persistence_predictions(snapshot, np.asarray([0]), horizon_minutes=60)
    assert result["previous_day"].reference_times[0] == expected_reference
    assert issue + 60 * 60 - 900 - expected_reference == 23 * 60 * 60
