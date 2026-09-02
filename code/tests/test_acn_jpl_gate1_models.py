from __future__ import annotations

import copy
import inspect
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from evcf.forecasting.acn_jpl_gate1_contracts import load_gate1_config
from evcf.forecasting.acn_jpl_gate1_data import (
    Gate1Snapshot,
    verified_snapshot_provenance,
)
from evcf.forecasting.acn_jpl_gate1_features import (
    FeatureBlock,
    canonical_feature_schema,
    verified_feature_block_provenance,
)
from evcf.forecasting.acn_jpl_gate1_models import (
    FormalModelTaskResult,
    Gate1TimeSplit,
    HGBPreprocessor,
    PersistencePrediction,
    PredictionBundle,
    RidgePreprocessor,
    SelectionRecord,
    _feature_block_sha256,
    _feature_schema_sha256,
    _freeze_formal_task_results,
    _persistence_coverage_from_results,
    _rolling_origin_predict_with_factories,
    _select_model_params_with_factories,
    _snapshot_target,
    build_model_selection_manifest,
    frozen_model_candidates,
    make_frozen_estimator,
    persistence_predictions,
    rolling_origin_predict,
    run_model_task,
    select_model_params,
    verified_formal_model_task_provenance,
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
    feature_names, nullable = canonical_feature_schema(tier)
    raw_dimension = len(feature_names)
    generator = np.random.default_rng(seed)
    values = generator.normal(size=(len(issue_times), raw_dimension))
    nullable_positions = np.flatnonzero(nullable)
    if len(nullable_positions):
        values[::17, nullable_positions[0]] = np.nan
    return FeatureBlock(
        issue_times=issue_times,
        values=values,
        feature_names=feature_names,
        nullable_mask=nullable,
    )


def _target(issue_times: np.ndarray) -> np.ndarray:
    return 10.0 + np.sin(np.arange(len(issue_times), dtype=np.float64) / 13.0)


def _model_snapshot(
    issue_times: np.ndarray,
    config: Mapping[str, Any],
    *,
    labels: np.ndarray | None = None,
) -> Gate1Snapshot:
    row_count = len(issue_times)
    if labels is None:
        base = _target(issue_times)
        labels = np.column_stack(
            [base + position * 100.0 for position, _horizon in enumerate(HORIZONS)]
        )
    station_times = np.arange(
        _epoch("2019-05-10T00:00:00-07:00"),
        _epoch("2019-06-02T00:00:00-07:00"),
        900,
        dtype=np.int64,
    )
    station_values = 12.0 + np.sin(np.arange(len(station_times), dtype=np.float64) / 31.0)
    station_valid = np.ones(len(station_times), dtype=np.bool_)
    unavailable_previous_week = {
        _epoch("2019-05-15T19:30:00-07:00"),
        _epoch("2019-05-15T19:45:00-07:00"),
        _epoch("2019-05-15T20:00:00-07:00"),
    }
    station_valid[np.isin(station_times, tuple(unavailable_previous_week))] = False
    return Gate1Snapshot(
        data_snapshot_sha256=str(config["data_snapshot_sha256"]),
        artifact_sha256={},
        issue_times=issue_times,
        horizons=np.asarray(HORIZONS, dtype=np.int16),
        labels=np.asarray(labels, dtype=np.float32),
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


def test_time_split_has_no_count_bypass_and_revalidates_replaced_state(
    split: Gate1TimeSplit,
) -> None:
    assert "require_frozen_counts" not in inspect.signature(Gate1TimeSplit.from_config).parameters
    with pytest.raises(ValueError, match="split|train|cohort|provenance"):
        replace(split, train_rows=split.train_rows[1:])


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda value: value.__setitem__("schema_version", "mutated/v0"), "schema_version|frozen"),
        (lambda value: value.__setitem__("data_snapshot_sha256", "0" * 64), "snapshot|frozen"),
        (lambda value: value.__setitem__("windows_minutes", [5, 15, 30]), "windows|frozen"),
        (lambda value: value.__setitem__("bounded_hold_seconds", 13), "hold|frozen"),
        (lambda value: value.__setitem__("unexpected", True), "keys|unexpected|frozen"),
    ],
)
def test_model_split_reuses_the_complete_frozen_config_contract(
    config: Mapping[str, Any], mutation: Any, expected: str
) -> None:
    changed = copy.deepcopy(dict(config))
    mutation(changed)
    with pytest.raises(ValueError, match=expected):
        Gate1TimeSplit.from_config(_formal_issue_times(), changed)


def test_runtime_config_accepts_read_only_mapping(
    config: Mapping[str, Any],
) -> None:
    read_only = MappingProxyType(copy.deepcopy(dict(config)))
    rebuilt = Gate1TimeSplit.from_config(_formal_issue_times(), read_only)
    assert rebuilt.frozen_provenance_sha256
    assert len(frozen_model_candidates("hgb", read_only)) == 16


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
    with pytest.raises(ValueError, match=f"all-NaN|all missing|{block.feature_names[4]}"):
        RidgePreprocessor().fit(all_nan_block, np.arange(5))

    hgb = HGBPreprocessor().fit(block, np.arange(5))
    encoded = hgb.transform(block, np.arange(8))
    assert hgb.input_dimension == 391
    first_nullable = int(np.flatnonzero(block.nullable_mask)[0])
    assert np.isnan(encoded[0, first_nullable]) == np.isnan(block.values[0, first_nullable])
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
        hgb.transform_values(
            np.full((1, RAW_DIMENSIONS["M3"]), np.inf),
            feature_names=block.feature_names,
            nullable_mask=block.nullable_mask,
        )


def test_preprocessors_require_exact_canonical_feature_names_and_nullable_positions() -> None:
    times = np.arange(8, dtype=np.int64) + 1
    block = _block("M2", times)
    changed_names = FeatureBlock(
        times,
        block.values,
        ("not_the_canonical_first_feature",) + block.feature_names[1:],
        block.nullable_mask,
    )
    with pytest.raises(ValueError, match="canonical|feature names|schema"):
        RidgePreprocessor().fit(changed_names, np.arange(5))

    shifted_nullable = block.nullable_mask.copy()
    old_position = int(np.flatnonzero(shifted_nullable)[0])
    shifted_nullable[old_position] = False
    shifted_nullable[0] = True
    changed_nullable = FeatureBlock(
        times,
        block.values,
        block.feature_names,
        shifted_nullable,
    )
    with pytest.raises(ValueError, match="canonical|nullable|schema"):
        HGBPreprocessor().fit(changed_nullable, np.arange(5))


def test_formal_model_api_binds_snapshot_and_hides_test_factories() -> None:
    select_parameters = inspect.signature(select_model_params).parameters
    rolling_parameters = inspect.signature(rolling_origin_predict).parameters
    task_parameters = inspect.signature(run_model_task).parameters
    assert "snapshot" in select_parameters
    assert "target" not in select_parameters
    assert "snapshot" in rolling_parameters
    assert "target" not in rolling_parameters
    assert "snapshot" in task_parameters
    assert "target" not in task_parameters
    assert "estimator_factory" not in task_parameters
    assert "preprocessor_factory" not in task_parameters


def test_snapshot_target_requires_verified_index_and_horizon_dtypes(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    snapshot = _model_snapshot(split.issue_times, config)
    with pytest.raises(ValueError, match="issue.*int64|index.*dtype"):
        _snapshot_target(
            replace(snapshot, issue_times=snapshot.issue_times.astype(float)), split, 15
        )
    with pytest.raises(ValueError, match="horizon.*int16|horizon.*dtype"):
        _snapshot_target(replace(snapshot, horizons=snapshot.horizons.astype(float)), split, 15)
    with pytest.raises(ValueError, match="label.*float32|label.*dtype"):
        _snapshot_target(replace(snapshot, labels=snapshot.labels.astype(np.float64)), split, 15)


def test_manifest_api_requires_actual_blocks_persistence_and_formal_results() -> None:
    parameters = inspect.signature(build_model_selection_manifest).parameters
    assert "feature_blocks" in parameters
    assert "persistence_by_horizon" in parameters
    assert "task_results" in parameters
    assert "selections" not in parameters
    assert "predictions" not in parameters
    assert "feature_dimensions" not in parameters
    assert "persistence_coverage" not in parameters
    assert inspect.signature(run_model_task).return_annotation in {
        "FormalModelTaskResult",
        FormalModelTaskResult,
    }


def test_synthetic_snapshot_and_manual_results_are_not_formally_sealed(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    snapshot = _model_snapshot(split.issue_times, config)
    with pytest.raises(ValueError, match="verified|loader|seal"):
        verified_snapshot_provenance(snapshot)
    with pytest.raises(TypeError):
        FormalModelTaskResult()  # type: ignore[call-arg]
    forged = object.__new__(FormalModelTaskResult)
    with pytest.raises(TypeError, match="checkpoint verifier"):
        forged.__setstate__((object(), object()))
    with pytest.raises(TypeError, match="FormalModelTaskResult"):
        verified_formal_model_task_provenance((object(), object()))  # type: ignore[arg-type]


def test_formal_task_sequence_is_materialized_once_before_type_validation() -> None:
    class ChangingSequence(Sequence[FormalModelTaskResult]):
        def __init__(self) -> None:
            self.iteration_count = 0

        def __len__(self) -> int:
            return 0

        def __getitem__(self, _index: int) -> FormalModelTaskResult:
            raise IndexError

        def __iter__(self):  # type: ignore[no-untyped-def]
            self.iteration_count += 1
            return iter(()) if self.iteration_count == 1 else iter((object(),))

    changing = ChangingSequence()
    assert _freeze_formal_task_results(changing) == ()
    assert changing.iteration_count == 1
    with pytest.raises(TypeError, match="FormalModelTaskResult"):
        _freeze_formal_task_results([object()])  # type: ignore[list-item]


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


def _preprocessor_factory(learner: str) -> RidgePreprocessor | HGBPreprocessor:
    return RidgePreprocessor() if learner == "ridge" else HGBPreprocessor()


def _record(
    *,
    learner: str,
    tier: str,
    horizon: int,
    feature_block: FeatureBlock,
    snapshot: Gate1Snapshot,
    split: Gate1TimeSplit,
    config: Mapping[str, Any],
    scores: np.ndarray | list[float] | None = None,
) -> SelectionRecord:
    candidates = frozen_model_candidates(learner, config)
    if scores is None:
        scores = np.linspace(1.0, 2.0, len(candidates))
    _values, target_sha256 = _snapshot_target(snapshot, split, horizon)
    return SelectionRecord.create(
        learner=learner,
        tier=tier,
        horizon_minutes=horizon,
        candidate_params=candidates,
        candidate_validation_mae=scores,
        selected_candidate_index=int(np.argmin(scores)),
        selection_fit_count=len(split.selection_fit_rows(horizon)),
        validation_score_count=len(split.validation_score_rows(horizon)),
        data_snapshot_sha256=snapshot.data_snapshot_sha256,
        split_provenance_sha256=split.frozen_provenance_sha256,
        target_sha256=target_sha256,
        feature_schema_sha256=_feature_schema_sha256(feature_block),
        feature_block_sha256=_feature_block_sha256(feature_block),
    )


def test_full_candidate_budgets_ties_and_canonical_hash(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    block = _block("M1", split.issue_times)
    snapshot = _model_snapshot(split.issue_times, config)
    ridge_calls: list[tuple[int, int]] = []
    hgb_calls: list[tuple[int, int]] = []

    ridge_record = _select_model_params_with_factories(
        learner="ridge",
        tier="M1",
        horizon_minutes=15,
        feature_block=block,
        snapshot=snapshot,
        split=split,
        config=config,
        estimator_factory=lambda _learner, _params: _ConstantEstimator(3.0, ridge_calls),
        preprocessor_factory=_preprocessor_factory,
    )
    hgb_record = _select_model_params_with_factories(
        learner="hgb",
        tier="M1",
        horizon_minutes=15,
        feature_block=block,
        snapshot=snapshot,
        split=split,
        config=config,
        estimator_factory=lambda _learner, _params: _ConstantEstimator(3.0, hgb_calls),
        preprocessor_factory=_preprocessor_factory,
    )

    assert len(ridge_calls) == 4
    assert len(hgb_calls) == 16
    assert all(call == (1_248, 1_248) for call in ridge_calls + hgb_calls)
    assert ridge_record.selected_candidate_index == 0
    assert hgb_record.selected_candidate_index == 0
    expected_15_minute_mae = np.mean(
        np.abs(snapshot.labels[split.validation_score_rows(15), 0].astype(np.float64) - 3.0)
    )
    expected_240_minute_mae = np.mean(
        np.abs(snapshot.labels[split.validation_score_rows(15), 4].astype(np.float64) - 3.0)
    )
    assert ridge_record.candidate_validation_mae[0] == expected_15_minute_mae
    assert ridge_record.candidate_validation_mae[0] != expected_240_minute_mae
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
            data_snapshot_sha256=snapshot.data_snapshot_sha256,
            split_provenance_sha256=split.frozen_provenance_sha256,
            target_sha256=_snapshot_target(snapshot, split, 15)[1],
            feature_schema_sha256=_feature_schema_sha256(block),
            feature_block_sha256=_feature_block_sha256(block),
        )


def test_selection_executes_every_candidate_or_fails(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    block = _block("M1", split.issue_times)
    snapshot = _model_snapshot(split.issue_times, config)
    calls = 0

    def factory(_learner: str, _params: Mapping[str, Any]) -> _ConstantEstimator:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("intentional candidate failure")
        return _ConstantEstimator(1.0, [])

    with pytest.raises(RuntimeError, match="candidate 2"):
        _select_model_params_with_factories(
            learner="ridge",
            tier="M1",
            horizon_minutes=30,
            feature_block=block,
            snapshot=snapshot,
            split=split,
            config=config,
            estimator_factory=factory,
            preprocessor_factory=_preprocessor_factory,
        )
    assert calls == 3


def test_rolling_refits_once_per_day_without_retuning_or_clipping(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    block = _block("M1", split.issue_times)
    snapshot = _model_snapshot(split.issue_times, config)
    target = snapshot.labels[:, HORIZONS.index(60)]
    selected = _record(
        learner="ridge",
        tier="M1",
        horizon=60,
        feature_block=block,
        snapshot=snapshot,
        split=split,
        config=config,
        scores=[4.0, 3.0, 2.0, 1.0],
    )
    calls: list[tuple[int, int]] = []
    factory_parameters: list[dict[str, Any]] = []

    def factory(learner: str, params: Mapping[str, Any]) -> _ConstantEstimator:
        assert learner == "ridge"
        factory_parameters.append(dict(params))
        return _ConstantEstimator(-2.5, calls)

    result = _rolling_origin_predict_with_factories(
        feature_block=block,
        snapshot=snapshot,
        split=split,
        selection=selected,
        estimator_factory=factory,
        preprocessor_factory=_preprocessor_factory,
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

    repeat = _rolling_origin_predict_with_factories(
        feature_block=block,
        snapshot=snapshot,
        split=split,
        selection=selected,
        estimator_factory=factory,
        preprocessor_factory=_preprocessor_factory,
    )
    np.testing.assert_array_equal(result.predictions, repeat.predictions)


def test_rolling_nonfinite_prediction_is_execution_failure(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    block = _block("M1", split.issue_times)
    snapshot = _model_snapshot(split.issue_times, config)
    selected = _record(
        learner="hgb",
        tier="M1",
        horizon=15,
        feature_block=block,
        snapshot=snapshot,
        split=split,
        config=config,
        scores=np.arange(16, dtype=np.float64),
    )
    with pytest.raises(ValueError, match="non-finite"):
        _rolling_origin_predict_with_factories(
            feature_block=block,
            snapshot=snapshot,
            split=split,
            selection=selected,
            estimator_factory=lambda _learner, _params: _ConstantEstimator(np.nan, []),
            preprocessor_factory=_preprocessor_factory,
        )


def test_selection_and_midnight_refit_ignore_unavailable_labels(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    block = _block("M1", split.issue_times)
    target = _target(split.issue_times)
    labels = np.column_stack([target + position * 100.0 for position in range(len(HORIZONS))])
    snapshot = _model_snapshot(split.issue_times, config, labels=labels)
    poisoned_test = target.copy()
    poisoned_test[split.test_rows] += 1e9
    poisoned_test_labels = labels.copy()
    poisoned_test_labels[:, 0] = poisoned_test
    poisoned_test_snapshot = _model_snapshot(split.issue_times, config, labels=poisoned_test_labels)
    factory = lambda _learner, _params: _MeanEstimator()
    baseline_selection = _select_model_params_with_factories(
        learner="ridge",
        tier="M1",
        horizon_minutes=15,
        feature_block=block,
        snapshot=snapshot,
        split=split,
        config=config,
        estimator_factory=factory,
        preprocessor_factory=_preprocessor_factory,
    )
    poisoned_selection = _select_model_params_with_factories(
        learner="ridge",
        tier="M1",
        horizon_minutes=15,
        feature_block=block,
        snapshot=poisoned_test_snapshot,
        split=split,
        config=config,
        estimator_factory=factory,
        preprocessor_factory=_preprocessor_factory,
    )
    np.testing.assert_array_equal(
        baseline_selection.candidate_validation_mae,
        poisoned_selection.candidate_validation_mae,
    )

    first_day_rows = next(iter(split.test_day_rows.values()))
    poisoned_day = target.copy()
    poisoned_day[first_day_rows] += 1e9
    poisoned_day_labels = labels.copy()
    poisoned_day_labels[:, 0] = poisoned_day
    poisoned_day_snapshot = _model_snapshot(split.issue_times, config, labels=poisoned_day_labels)
    poisoned_day_selection = _select_model_params_with_factories(
        learner="ridge",
        tier="M1",
        horizon_minutes=15,
        feature_block=block,
        snapshot=poisoned_day_snapshot,
        split=split,
        config=config,
        estimator_factory=factory,
        preprocessor_factory=_preprocessor_factory,
    )
    baseline_roll = _rolling_origin_predict_with_factories(
        feature_block=block,
        snapshot=snapshot,
        split=split,
        selection=baseline_selection,
        estimator_factory=factory,
        preprocessor_factory=_preprocessor_factory,
    )
    poisoned_roll = _rolling_origin_predict_with_factories(
        feature_block=block,
        snapshot=poisoned_day_snapshot,
        split=split,
        selection=poisoned_day_selection,
        estimator_factory=factory,
        preprocessor_factory=_preprocessor_factory,
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
    feature_block: FeatureBlock,
    snapshot: Gate1Snapshot,
) -> SelectionRecord:
    return _record(
        learner=learner,
        tier=tier,
        horizon=horizon,
        feature_block=feature_block,
        snapshot=snapshot,
        split=split,
        config=config,
    )


def _dummy_prediction(
    record: SelectionRecord, split: Gate1TimeSplit, snapshot: Gate1Snapshot
) -> PredictionBundle:
    test_rows = split.test_rows
    target = snapshot.labels[:, HORIZONS.index(record.horizon_minutes)]
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


def test_manifest_rejects_manual_records_bundles_and_unsealed_inputs(
    split: Gate1TimeSplit, config: Mapping[str, Any]
) -> None:
    snapshot = _model_snapshot(split.issue_times, config)
    feature_blocks = {tier: _block(tier, split.issue_times) for tier in TIERS}
    records = [
        _dummy_record(
            learner,
            tier,
            horizon,
            config,
            split,
            feature_blocks[tier],
            snapshot,
        )
        for learner in LEARNERS
        for tier in TIERS
        for horizon in HORIZONS
    ]
    predictions = [_dummy_prediction(record, split, snapshot) for record in records]
    persistence_by_horizon = {
        horizon: persistence_predictions(snapshot, split.test_rows, horizon_minutes=horizon)
        for horizon in HORIZONS
    }
    assert not isinstance(records[0], FormalModelTaskResult)
    assert not isinstance(predictions[0], FormalModelTaskResult)
    with pytest.raises(TypeError, match="unexpected keyword"):
        build_model_selection_manifest(
            config=config,
            snapshot=snapshot,
            split=split,
            feature_blocks=feature_blocks,
            selections=records,  # type: ignore[call-arg]
            predictions=predictions,  # type: ignore[call-arg]
            persistence_by_horizon=persistence_by_horizon,
        )
    with pytest.raises(TypeError, match="FormalModelTaskResult"):
        build_model_selection_manifest(
            config=config,
            snapshot=snapshot,
            split=split,
            feature_blocks=feature_blocks,
            task_results=list(zip(records, predictions, strict=True)),  # type: ignore[arg-type]
            persistence_by_horizon=persistence_by_horizon,
        )
    with pytest.raises(ValueError, match="verified|loader|seal"):
        build_model_selection_manifest(
            config=config,
            snapshot=snapshot,
            split=split,
            feature_blocks=feature_blocks,
            task_results=[],
            persistence_by_horizon=persistence_by_horizon,
        )

    forged_persistence = dict(persistence_by_horizon)
    forged_horizon = dict(forged_persistence[15])
    original = forged_horizon["last_value"]
    forged_predictions = original.predictions.copy()
    forged_predictions[0] += 1.0
    forged_horizon["last_value"] = PersistencePrediction(
        name=original.name,
        horizon_minutes=original.horizon_minutes,
        issue_times=original.issue_times,
        predictions=forged_predictions,
        availability=original.availability,
        reference_times=original.reference_times,
    )
    forged_persistence[15] = forged_horizon
    with pytest.raises(ValueError, match="persistence.*recomputation"):
        _persistence_coverage_from_results(forged_persistence, snapshot, split)

    changed_blocks = dict(feature_blocks)
    changed_values = feature_blocks["M1"].values.copy()
    changed_values[:, 0] += 1.0
    changed_blocks["M1"] = FeatureBlock(
        issue_times=feature_blocks["M1"].issue_times,
        values=changed_values,
        feature_names=feature_blocks["M1"].feature_names,
        nullable_mask=feature_blocks["M1"].nullable_mask,
    )
    with pytest.raises(ValueError, match="verified|encoder|seal"):
        verified_feature_block_provenance(changed_blocks["M1"], snapshot, tier="M1")


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


@pytest.mark.parametrize("case", ("unsorted", "off_grid", "reference_dtype", "formula"))
def test_persistence_prediction_rejects_invalid_index_and_reference_provenance(case: str) -> None:
    issue = _epoch("2019-05-18T01:00:00-07:00")
    issue_times = np.asarray([issue, issue + 900], dtype=np.int64)
    references: np.ndarray = issue_times - 900
    if case == "unsorted":
        issue_times = issue_times[::-1].copy()
        references = issue_times - 900
    elif case == "off_grid":
        issue_times = issue_times.copy()
        issue_times[1] += 1
        references = issue_times - 900
    elif case == "reference_dtype":
        references = references.astype(np.float64)
    elif case == "formula":
        references = references.copy()
        references[0] -= 900
    with pytest.raises(ValueError, match="issue|grid|reference|formula|int64"):
        PersistencePrediction(
            name="last_value",
            horizon_minutes=15,
            issue_times=issue_times,
            predictions=np.ones(2, dtype=np.float64),
            availability=np.ones(2, dtype=np.bool_),
            reference_times=references,
        )
