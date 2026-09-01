"""Frozen model-selection and rolling-origin contracts for JPL Gate 1.

This module owns only deterministic CPU baselines.  Row timestamps remain
indexes, preprocessing is re-fitted from the eligible training rows, model
parameters are selected once on the frozen validation interval, and each test
day receives one midnight refit without clipping or calibration.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from numbers import Integral
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from evcf.forecasting.acn_jpl_gate1_contracts import (
    expand_hgb_grid,
    parse_time_split_boundaries,
    validate_gate1_config,
)
from evcf.forecasting.acn_jpl_gate1_data import (
    Gate1Snapshot,
    verified_snapshot_provenance,
)
from evcf.forecasting.acn_jpl_gate1_features import (
    FeatureBlock,
    canonical_feature_schema,
    feature_block_content_sha256,
    validate_feature_block_schema,
    verified_feature_block_provenance,
)

MODEL_SEED = 20260901
BOOTSTRAP_SEED = 20260902
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
TIER_ORDER = ("M1", "M2", "M3", "M4")
LEARNER_ORDER = ("ridge", "hgb")
PERSISTENCE_ORDER = ("last_value", "previous_day", "previous_week")
TIMEZONE_NAME = "America/Los_Angeles"
_ZONE = ZoneInfo(TIMEZONE_NAME)
_SHA256_HEX_LENGTH = 64
_FORMAL_EXECUTION_SCHEMA = "acn-jpl-gate1-formal-model-task/v1"
_CANONICAL_FEATURE_SCHEMAS = MappingProxyType(
    {tier: canonical_feature_schema(tier) for tier in TIER_ORDER}
)
_EXPECTED_RAW_DIMENSIONS = MappingProxyType(
    {tier: len(_CANONICAL_FEATURE_SCHEMAS[tier][0]) for tier in TIER_ORDER}
)
_EXPECTED_INDICATOR_COUNTS = MappingProxyType(
    {tier: int(np.sum(_CANONICAL_FEATURE_SCHEMAS[tier][1])) for tier in TIER_ORDER}
)
_EXPECTED_INPUT_DIMENSIONS = MappingProxyType(
    {tier: _EXPECTED_RAW_DIMENSIONS[tier] + _EXPECTED_INDICATOR_COUNTS[tier] for tier in TIER_ORDER}
)
_EXPECTED_COHORT_COUNTS = (1_248, 276, 1_329)
_EXPECTED_TEST_DAY_COUNTS = (96,) * 13 + (81,)
_EXPECTED_SELECTION_COUNTS = MappingProxyType(
    {
        15: (1_248, 276),
        30: (1_247, 275),
        60: (1_245, 273),
        120: (1_241, 269),
        240: (1_233, 261),
    }
)
_EXPECTED_FIRST_ROLLING_COUNTS = MappingProxyType(
    {15: 1_524, 30: 1_523, 60: 1_521, 120: 1_517, 240: 1_509}
)
_EXPECTED_LAST_ROLLING_COUNTS = MappingProxyType(
    {15: 2_772, 30: 2_771, 60: 2_769, 120: 2_765, 240: 2_757}
)
_EXPECTED_PERSISTENCE_COVERAGE = MappingProxyType(
    {"last_value": 1_329, "previous_day": 1_329, "previous_week": 1_326}
)
_FORBIDDEN_FEATURE_NAMES = frozenset(
    {
        "issue_time_utc_s",
        "issue_index",
        "anonymous_session_index",
        "trajectory_ref",
    }
)


class _Estimator(Protocol):
    def fit(self, x: np.ndarray, y: np.ndarray) -> _Estimator: ...

    def predict(self, x: np.ndarray) -> np.ndarray: ...


EstimatorFactory = Callable[[str, Mapping[str, Any]], _Estimator]
PreprocessorFactory = Callable[[str], Any]


def _immutable(array: Any, *, dtype: np.dtype[Any] | str | None = None) -> np.ndarray:
    contiguous = np.ascontiguousarray(array, dtype=dtype)
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype).reshape(
        contiguous.shape
    )


def _strict_integer(value: Any, context: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{context} must be an integer")
    result = int(value)
    if positive and result <= 0:
        raise ValueError(f"{context} must be positive")
    return result


def _strict_horizon(value: Any) -> int:
    horizon = _strict_integer(value, "horizon_minutes", positive=True)
    if horizon not in HORIZONS_MINUTES:
        raise ValueError(f"horizon_minutes must be one of {HORIZONS_MINUTES!r}")
    return horizon


def _strict_learner(value: Any) -> str:
    if value not in LEARNER_ORDER:
        raise ValueError(f"learner must be one of {LEARNER_ORDER!r}")
    return str(value)


def _strict_tier(value: Any) -> str:
    if value not in TIER_ORDER:
        raise ValueError(f"tier must be one of {TIER_ORDER!r}")
    return str(value)


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ValueError("model parameters must be finite canonical JSON values") from exc
    decoded = json.loads(encoded)
    if decoded != value:
        raise ValueError("model parameters changed under canonical JSON encoding")
    return encoded


def _decode_parameter_json(value: bytes) -> Mapping[str, Any]:
    decoded = json.loads(value.decode("ascii"))
    if type(decoded) is not dict:
        raise ValueError("candidate parameters must decode to a mapping")
    return MappingProxyType(decoded)


def _parameter_sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _validate_sha256(value: Any, context: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_HEX_LENGTH:
        raise ValueError(f"{context} must be a lowercase SHA-256 hex digest")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{context} must be a lowercase SHA-256 hex digest")
    return value


def _require_model_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Delegate the complete runtime contract to the authoritative config module."""

    if not isinstance(config, Mapping):
        raise TypeError("config must be a frozen Gate 1 mapping")
    return validate_gate1_config(config)


def _row_indexes(rows: Any, row_count: int, context: str) -> np.ndarray:
    raw = np.asarray(rows)
    if raw.ndim != 1 or not np.issubdtype(raw.dtype, np.integer):
        raise TypeError(f"{context} must be a one-dimensional integer row index")
    result = raw.astype(np.int64, copy=False)
    if not len(result):
        raise ValueError(f"{context} must not be empty")
    if np.any(result < 0) or np.any(result >= row_count):
        raise ValueError(f"{context} contains an out-of-range row")
    if np.any(np.diff(result) <= 0):
        raise ValueError(f"{context} must be strictly increasing and unique")
    return result


def _local_midnight_epoch(epoch_seconds: int) -> int:
    local = datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(_ZONE)
    midnight = datetime.combine(local.date(), time.min, tzinfo=_ZONE)
    return int(midnight.timestamp())


def _local_date_label(epoch_seconds: int) -> str:
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(_ZONE).date().isoformat()


def _split_provenance_sha256(
    config_json: bytes,
    arrays: Sequence[np.ndarray],
) -> str:
    digest = hashlib.sha256()
    digest.update(config_json)
    for array in arrays:
        value = np.ascontiguousarray(array)
        digest.update(value.dtype.str.encode("ascii"))
        digest.update(np.asarray(value.shape, dtype=np.int64).tobytes())
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Gate1TimeSplit:
    """Self-validating row identities for the sole frozen PDT protocol."""

    issue_times: np.ndarray
    train_rows: np.ndarray
    validation_rows: np.ndarray
    test_rows: np.ndarray
    _test_day_starts: np.ndarray
    _test_day_row_values: tuple[np.ndarray, ...]
    _validation_start_utc_s: int
    _test_start_utc_s: int
    _config_json: bytes
    _frozen_provenance_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self._config_json, bytes):
            raise TypeError("split config provenance must be canonical JSON bytes")
        try:
            decoded = json.loads(self._config_json.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("split config provenance is invalid") from exc
        canonical = _require_model_config(decoded)
        config_payload = {key: canonical[key] for key in canonical if key != "hgb_grid"}
        config_json = _canonical_json_bytes(config_payload)
        if config_json != self._config_json:
            raise ValueError("split config provenance differs from the full frozen contract")

        times = np.asarray(self.issue_times)
        if times.dtype != np.dtype(np.int64) or times.ndim != 1:
            raise ValueError("issue-time index must be a one-dimensional int64 array")
        if len(times) != sum(_EXPECTED_COHORT_COUNTS) or np.any(np.diff(times) <= 0):
            raise ValueError("frozen issue-time index must contain 2,853 unique increasing rows")
        if np.any(times % 900 != 0):
            raise ValueError("issue-time index must remain on the frozen 15-minute UTC grid")

        parsed = parse_time_split_boundaries(canonical["time_split"])
        train_start = int(parsed["initial_train"]["start_local"].timestamp())
        validation_start = int(parsed["validation"]["start_local"].timestamp())
        test_start = int(parsed["rolling_test"]["start_local"].timestamp())
        test_end = int(parsed["rolling_test"]["end_local_exclusive"].timestamp())
        expected_train = np.flatnonzero((times >= train_start) & (times < validation_start)).astype(
            np.int64
        )
        expected_validation = np.flatnonzero(
            (times >= validation_start) & (times < test_start)
        ).astype(np.int64)
        expected_test = np.flatnonzero((times >= test_start) & (times < test_end)).astype(np.int64)
        rows = tuple(
            np.asarray(value) for value in (self.train_rows, self.validation_rows, self.test_rows)
        )
        if any(value.dtype != np.dtype(np.int64) or value.ndim != 1 for value in rows):
            raise ValueError("split cohort rows must be one-dimensional int64 arrays")
        if not all(
            np.array_equal(actual, expected)
            for actual, expected in zip(
                rows, (expected_train, expected_validation, expected_test), strict=True
            )
        ):
            raise ValueError("split cohorts differ from the frozen half-open boundaries")
        if tuple(len(value) for value in rows) != _EXPECTED_COHORT_COUNTS:
            raise ValueError("split cohort counts differ from 1248/276/1329")
        covered = np.concatenate(rows)
        if not np.array_equal(np.sort(covered), np.arange(len(times), dtype=np.int64)):
            raise ValueError("split cohorts overlap or do not cover the complete issue index")

        day_values = np.asarray(
            [_local_midnight_epoch(int(times[row])) for row in expected_test], dtype=np.int64
        )
        expected_day_starts = np.unique(day_values)
        expected_day_rows = tuple(
            expected_test[day_values == day].astype(np.int64) for day in expected_day_starts
        )
        actual_day_starts = np.asarray(self._test_day_starts)
        actual_day_rows = tuple(np.asarray(value) for value in self._test_day_row_values)
        if actual_day_starts.dtype != np.dtype(np.int64) or actual_day_starts.ndim != 1:
            raise ValueError("test day starts must be a one-dimensional int64 array")
        if not np.array_equal(actual_day_starts, expected_day_starts) or len(
            actual_day_rows
        ) != len(expected_day_rows):
            raise ValueError("test day blocks differ from the frozen local-day partition")
        if not all(
            actual.dtype == np.dtype(np.int64)
            and actual.ndim == 1
            and np.array_equal(actual, expected)
            for actual, expected in zip(actual_day_rows, expected_day_rows, strict=True)
        ):
            raise ValueError("test day row blocks are inconsistent with the test cohort")
        expected_days = tuple(
            int(datetime(2019, 5, day, tzinfo=_ZONE).timestamp()) for day in range(18, 32)
        )
        if (
            tuple(int(value) for value in expected_day_starts) != expected_days
            or tuple(len(value) for value in expected_day_rows) != _EXPECTED_TEST_DAY_COUNTS
        ):
            raise ValueError("test split must contain the exact 14 frozen local-day blocks")
        if self._validation_start_utc_s != validation_start or self._test_start_utc_s != test_start:
            raise ValueError("split boundary fields differ from the frozen config")

        immutable_times = _immutable(times, dtype=np.int64)
        immutable_rows = tuple(_immutable(value, dtype=np.int64) for value in rows)
        immutable_days = _immutable(actual_day_starts, dtype=np.int64)
        immutable_day_rows = tuple(_immutable(value, dtype=np.int64) for value in actual_day_rows)
        provenance_arrays = (
            immutable_times,
            *immutable_rows,
            immutable_days,
            *immutable_day_rows,
        )
        expected_provenance = _split_provenance_sha256(config_json, provenance_arrays)
        if self._frozen_provenance_sha256 != expected_provenance:
            raise ValueError("split frozen provenance digest is inconsistent")
        object.__setattr__(self, "issue_times", immutable_times)
        object.__setattr__(self, "train_rows", immutable_rows[0])
        object.__setattr__(self, "validation_rows", immutable_rows[1])
        object.__setattr__(self, "test_rows", immutable_rows[2])
        object.__setattr__(self, "_test_day_starts", immutable_days)
        object.__setattr__(self, "_test_day_row_values", immutable_day_rows)

        for horizon in HORIZONS_MINUTES:
            selection_counts = (
                len(self.selection_fit_rows(horizon)),
                len(self.validation_score_rows(horizon)),
            )
            if selection_counts != _EXPECTED_SELECTION_COUNTS[horizon]:
                raise ValueError(
                    f"horizon {horizon} selection row counts differ from the frozen protocol"
                )
            rolling = self.rolling_fit_rows(horizon)
            if (
                len(next(iter(rolling.values()))) != _EXPECTED_FIRST_ROLLING_COUNTS[horizon]
                or len(next(reversed(rolling.values()))) != _EXPECTED_LAST_ROLLING_COUNTS[horizon]
            ):
                raise ValueError(
                    f"horizon {horizon} rolling-fit row counts differ from the frozen protocol"
                )

    @classmethod
    def from_config(
        cls,
        issue_times: Any,
        config: Mapping[str, Any],
    ) -> Gate1TimeSplit:
        canonical = _require_model_config(config)
        times = np.asarray(issue_times)
        if times.dtype != np.dtype(np.int64) or times.ndim != 1:
            raise ValueError("issue-time index must be a one-dimensional int64 array")
        parsed = parse_time_split_boundaries(canonical["time_split"])
        train_start = int(parsed["initial_train"]["start_local"].timestamp())
        validation_start = int(parsed["validation"]["start_local"].timestamp())
        test_start = int(parsed["rolling_test"]["start_local"].timestamp())
        test_end = int(parsed["rolling_test"]["end_local_exclusive"].timestamp())
        train = np.flatnonzero((times >= train_start) & (times < validation_start)).astype(np.int64)
        validation = np.flatnonzero((times >= validation_start) & (times < test_start)).astype(
            np.int64
        )
        test = np.flatnonzero((times >= test_start) & (times < test_end)).astype(np.int64)
        day_values = np.asarray(
            [_local_midnight_epoch(int(times[row])) for row in test], dtype=np.int64
        )
        day_starts = np.unique(day_values)
        day_rows = tuple(test[day_values == day].astype(np.int64) for day in day_starts)
        config_payload = {key: canonical[key] for key in canonical if key != "hgb_grid"}
        config_json = _canonical_json_bytes(config_payload)
        immutable_values = (
            _immutable(times, dtype=np.int64),
            _immutable(train, dtype=np.int64),
            _immutable(validation, dtype=np.int64),
            _immutable(test, dtype=np.int64),
            _immutable(day_starts, dtype=np.int64),
            *(_immutable(value, dtype=np.int64) for value in day_rows),
        )
        provenance = _split_provenance_sha256(config_json, immutable_values)
        return cls(
            issue_times=immutable_values[0],
            train_rows=immutable_values[1],
            validation_rows=immutable_values[2],
            test_rows=immutable_values[3],
            _test_day_starts=immutable_values[4],
            _test_day_row_values=tuple(immutable_values[5:]),
            _validation_start_utc_s=validation_start,
            _test_start_utc_s=test_start,
            _config_json=config_json,
            _frozen_provenance_sha256=provenance,
        )

    @property
    def config(self) -> dict[str, Any]:
        """Return a fresh fully validated config in authoritative declaration order."""

        return _require_model_config(json.loads(self._config_json.decode("ascii")))

    @property
    def frozen_provenance_sha256(self) -> str:
        return self._frozen_provenance_sha256

    @property
    def test_day_rows(self) -> Mapping[int, np.ndarray]:
        return MappingProxyType(
            {
                int(day): rows
                for day, rows in zip(self._test_day_starts, self._test_day_row_values, strict=True)
            }
        )

    def label_availability_times(self, horizon_minutes: int) -> np.ndarray:
        horizon = _strict_horizon(horizon_minutes)
        return _immutable(self.issue_times + horizon * 60, dtype=np.int64)

    def selection_fit_rows(self, horizon_minutes: int) -> np.ndarray:
        availability = self.label_availability_times(horizon_minutes)
        result = self.train_rows[availability[self.train_rows] <= self._validation_start_utc_s]
        return _immutable(result, dtype=np.int64)

    def validation_score_rows(self, horizon_minutes: int) -> np.ndarray:
        availability = self.label_availability_times(horizon_minutes)
        result = self.validation_rows[availability[self.validation_rows] <= self._test_start_utc_s]
        return _immutable(result, dtype=np.int64)

    def rolling_fit_rows(self, horizon_minutes: int) -> Mapping[int, np.ndarray]:
        availability = self.label_availability_times(horizon_minutes)
        result: dict[int, np.ndarray] = {}
        all_rows = np.arange(len(self.issue_times), dtype=np.int64)
        for day_start in self._test_day_starts:
            eligible = all_rows[(self.issue_times < day_start) & (availability <= day_start)]
            result[int(day_start)] = _immutable(eligible, dtype=np.int64)
        return MappingProxyType(result)


def _schema_tier(block: FeatureBlock) -> str:
    return validate_feature_block_schema(block)


class _SchemaBoundPreprocessor:
    def __init__(self) -> None:
        self._feature_names: tuple[str, ...] | None = None
        self._nullable_mask: np.ndarray | None = None
        self._tier: str | None = None

    @property
    def input_dimension(self) -> int:
        if self._tier is None:
            raise RuntimeError("preprocessor has not been fitted")
        return _EXPECTED_INPUT_DIMENSIONS[self._tier]

    def _bind_schema(self, block: FeatureBlock) -> str:
        tier = _schema_tier(block)
        self._tier = tier
        self._feature_names = block.feature_names
        self._nullable_mask = _immutable(block.nullable_mask, dtype=np.bool_)
        return tier

    def _validate_schema(
        self,
        feature_names: Sequence[str],
        nullable_mask: Any,
    ) -> tuple[str, np.ndarray]:
        names = tuple(feature_names)
        nullable = np.asarray(nullable_mask)
        if nullable.dtype != np.dtype(np.bool_) or nullable.shape != (len(names),):
            raise ValueError("feature nullable-mask schema is invalid")
        if self._feature_names is not None and (
            names != self._feature_names or not np.array_equal(nullable, self._nullable_mask)
        ):
            raise ValueError("transform feature schema differs from the fitted schema")
        raw_dimension = len(names)
        matches = [
            tier
            for tier, dimension in _EXPECTED_RAW_DIMENSIONS.items()
            if dimension == raw_dimension
        ]
        if len(matches) != 1:
            raise ValueError("feature schema differs from the canonical M1-M4 dimensions")
        tier = matches[0]
        if self._tier != tier:
            raise ValueError("transform feature tier differs from the fitted canonical schema")
        return tier, nullable


class RidgePreprocessor(_SchemaBoundPreprocessor):
    """Training-only median imputation, fixed indicators, and standardization."""

    def __init__(self) -> None:
        super().__init__()
        self._medians: np.ndarray | None = None
        self._means: np.ndarray | None = None
        self._scales: np.ndarray | None = None

    @property
    def medians(self) -> np.ndarray:
        if self._medians is None:
            raise RuntimeError("preprocessor has not been fitted")
        return self._medians

    @property
    def means(self) -> np.ndarray:
        if self._means is None:
            raise RuntimeError("preprocessor has not been fitted")
        return self._means

    @property
    def scales(self) -> np.ndarray:
        if self._scales is None:
            raise RuntimeError("preprocessor has not been fitted")
        return self._scales

    def fit(self, feature_block: FeatureBlock, rows: Any) -> RidgePreprocessor:
        tier = self._bind_schema(feature_block)
        fit_rows = _row_indexes(rows, len(feature_block.issue_times), "Ridge fit rows")
        raw = np.asarray(feature_block.values[fit_rows], dtype=np.float64)
        if np.any(np.isinf(raw)):
            raise ValueError("Ridge fit features contain infinity")
        all_nan = np.all(np.isnan(raw), axis=0)
        if np.any(all_nan):
            position = int(np.flatnonzero(all_nan)[0])
            raise ValueError(
                f"Ridge fit feature is all-NaN/all missing: {feature_block.feature_names[position]}"
            )
        medians = np.asarray(
            [np.median(column[np.isfinite(column)]) for column in raw.T], dtype=np.float64
        )
        filled = np.where(np.isnan(raw), medians, raw)
        indicators = np.isnan(raw[:, feature_block.nullable_mask]).astype(np.float64)
        encoded = np.concatenate((filled, indicators), axis=1)
        if encoded.shape[1] != _EXPECTED_INPUT_DIMENSIONS[tier]:
            raise AssertionError("Ridge encoded dimension drift")
        means = np.mean(encoded, axis=0)
        scales = np.std(encoded, axis=0, ddof=0)
        scales[scales == 0.0] = 1.0
        if (
            not np.isfinite(medians).all()
            or not np.isfinite(means).all()
            or not np.isfinite(scales).all()
        ):
            raise ValueError("Ridge preprocessing statistics are non-finite")
        self._medians = _immutable(medians, dtype=np.float64)
        self._means = _immutable(means, dtype=np.float64)
        self._scales = _immutable(scales, dtype=np.float64)
        return self

    def transform(self, feature_block: FeatureBlock, rows: Any) -> np.ndarray:
        if self._medians is None or self._means is None or self._scales is None:
            raise RuntimeError("Ridge preprocessor must be fitted before transform")
        self._validate_schema(feature_block.feature_names, feature_block.nullable_mask)
        selected = _row_indexes(rows, len(feature_block.issue_times), "Ridge transform rows")
        raw = np.asarray(feature_block.values[selected], dtype=np.float64)
        if np.any(np.isinf(raw)):
            raise ValueError("Ridge transform features contain infinity")
        filled = np.where(np.isnan(raw), self._medians, raw)
        indicators = np.isnan(raw[:, feature_block.nullable_mask]).astype(np.float64)
        encoded = np.concatenate((filled, indicators), axis=1)
        transformed = (encoded - self._means) / self._scales
        if transformed.shape[1] != self.input_dimension or not np.isfinite(transformed).all():
            raise ValueError("Ridge transform produced an invalid encoded matrix")
        return _immutable(transformed, dtype=np.float64)


class HGBPreprocessor(_SchemaBoundPreprocessor):
    """Schema-only HGB transform that preserves raw NaN and appends indicators."""

    def fit(self, feature_block: FeatureBlock, rows: Any) -> HGBPreprocessor:
        self._bind_schema(feature_block)
        _row_indexes(rows, len(feature_block.issue_times), "HGB fit rows")
        return self

    def transform_values(
        self,
        values: Any,
        *,
        feature_names: Sequence[str],
        nullable_mask: Any,
    ) -> np.ndarray:
        tier, nullable = self._validate_schema(feature_names, nullable_mask)
        raw = np.asarray(values, dtype=np.float64)
        if raw.ndim != 2 or raw.shape[1] != len(feature_names):
            raise ValueError("HGB transform values do not match the feature schema")
        if np.any(np.isinf(raw)):
            raise ValueError("HGB transform features contain infinite values")
        indicators = np.isnan(raw[:, nullable]).astype(np.float64)
        encoded = np.concatenate((raw, indicators), axis=1)
        if encoded.shape[1] != _EXPECTED_INPUT_DIMENSIONS[tier]:
            raise AssertionError("HGB encoded dimension drift")
        return _immutable(encoded, dtype=np.float64)

    def transform(self, feature_block: FeatureBlock, rows: Any) -> np.ndarray:
        if self._feature_names is None:
            raise RuntimeError("HGB preprocessor must be fitted before transform")
        selected = _row_indexes(rows, len(feature_block.issue_times), "HGB transform rows")
        return self.transform_values(
            feature_block.values[selected],
            feature_names=feature_block.feature_names,
            nullable_mask=feature_block.nullable_mask,
        )


def _ridge_parameters(alpha: float) -> dict[str, Any]:
    return {
        "alpha": alpha,
        "copy_X": True,
        "fit_intercept": True,
        "max_iter": None,
        "positive": False,
        "random_state": MODEL_SEED,
        "solver": "cholesky",
        "tol": 0.0001,
    }


def _hgb_parameters(varying: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "categorical_features": None,
        "early_stopping": False,
        "interaction_cst": None,
        "l2_regularization": varying["l2_regularization"],
        "learning_rate": varying["learning_rate"],
        "loss": "squared_error",
        "max_bins": 255,
        "max_depth": None,
        "max_features": 1.0,
        "max_iter": 300,
        "max_leaf_nodes": varying["max_leaf_nodes"],
        "min_samples_leaf": varying["min_samples_leaf"],
        "monotonic_cst": None,
        "n_iter_no_change": 10,
        "quantile": None,
        "random_state": MODEL_SEED,
        "scoring": "loss",
        "tol": 1e-7,
        "validation_fraction": 0.1,
        "verbose": 0,
        "warm_start": False,
    }


def _frozen_candidates_without_config(learner: str) -> tuple[Mapping[str, Any], ...]:
    learner_name = _strict_learner(learner)
    if learner_name == "ridge":
        raw = [_ridge_parameters(alpha) for alpha in (0.1, 1, 10, 100)]
    else:
        raw = [
            _hgb_parameters(
                {
                    "learning_rate": learning_rate,
                    "max_leaf_nodes": max_leaf_nodes,
                    "min_samples_leaf": min_samples_leaf,
                    "l2_regularization": l2_regularization,
                }
            )
            for learning_rate in (0.03, 0.08)
            for max_leaf_nodes in (15, 31)
            for min_samples_leaf in (20, 50)
            for l2_regularization in (0, 1)
        ]
    return tuple(MappingProxyType(candidate) for candidate in raw)


def frozen_model_candidates(
    learner: str, config: Mapping[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    """Return the complete effective parameter grid in frozen declaration order."""

    canonical_config = _require_model_config(config)
    learner_name = _strict_learner(learner)
    candidates = _frozen_candidates_without_config(learner_name)
    if learner_name == "ridge":
        config_alphas = tuple(canonical_config["ridge"]["alpha"])
        if tuple(candidate["alpha"] for candidate in candidates) != config_alphas:
            raise ValueError("effective Ridge candidates differ from config")
    else:
        varying = expand_hgb_grid(canonical_config["hgb"])
        for effective, declared in zip(candidates, varying, strict=True):
            for key in (
                "learning_rate",
                "max_leaf_nodes",
                "min_samples_leaf",
                "l2_regularization",
                "max_iter",
                "early_stopping",
                "loss",
                "random_state",
                "categorical_features",
            ):
                if effective[key] != declared[key]:
                    raise ValueError("effective HGB candidates differ from config")
    return candidates


def make_frozen_estimator(
    learner: str, params: Mapping[str, Any]
) -> Ridge | HistGradientBoostingRegressor:
    """Instantiate one frozen CPU estimator after exact parameter validation."""

    learner_name = _strict_learner(learner)
    candidate_json = _canonical_json_bytes(dict(params))
    expected_json = tuple(
        _canonical_json_bytes(dict(candidate))
        for candidate in _frozen_candidates_without_config(learner_name)
    )
    if candidate_json not in expected_json:
        raise ValueError("estimator parameters are not one frozen candidate")
    decoded = json.loads(candidate_json.decode("ascii"))
    if learner_name == "ridge":
        return Ridge(**decoded)
    return HistGradientBoostingRegressor(**decoded)


def _feature_schema_sha256(block: FeatureBlock) -> str:
    tier = validate_feature_block_schema(block)
    payload = {
        "tier": tier,
        "feature_names": list(block.feature_names),
        "nullable_mask": [bool(value) for value in block.nullable_mask],
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _feature_block_sha256(block: FeatureBlock) -> str:
    return feature_block_content_sha256(block)


def _snapshot_target(
    snapshot: Gate1Snapshot,
    split: Gate1TimeSplit,
    horizon_minutes: int,
) -> tuple[np.ndarray, str]:
    """Bind one label column to its verified snapshot, issue index, and horizon."""

    if not isinstance(snapshot, Gate1Snapshot):
        raise TypeError("model target source must be a verified Gate1Snapshot")
    horizon = _strict_horizon(horizon_minutes)
    config = split.config
    if snapshot.data_snapshot_sha256 != config["data_snapshot_sha256"]:
        raise ValueError("target snapshot SHA differs from the frozen config")
    snapshot_issue_times = np.asarray(snapshot.issue_times)
    if snapshot_issue_times.dtype != np.dtype(np.int64) or snapshot_issue_times.ndim != 1:
        raise ValueError("target snapshot issue index must retain its verified int64 dtype")
    if not np.array_equal(snapshot_issue_times, split.issue_times):
        raise ValueError("target snapshot and split must share the exact ordered issue index")
    horizons = np.asarray(snapshot.horizons)
    if horizons.dtype != np.dtype(np.int16) or horizons.ndim != 1:
        raise ValueError("target snapshot horizons must retain their verified int16 dtype")
    if tuple(int(value) for value in horizons) != HORIZONS_MINUTES:
        raise ValueError("target snapshot horizons differ from the frozen declaration")
    labels = np.asarray(snapshot.labels)
    if labels.dtype != np.dtype(np.float32):
        raise ValueError("target snapshot labels must retain their verified float32 dtype")
    if labels.shape != (len(split.issue_times), len(HORIZONS_MINUTES)):
        raise ValueError("target snapshot labels must align with all issue rows and horizons")
    if not np.isfinite(labels).all():
        raise ValueError("target snapshot labels must be complete finite numeric values")
    position = HORIZONS_MINUTES.index(horizon)
    values = _immutable(labels[:, position], dtype=np.float64)
    digest = hashlib.sha256()
    digest.update(snapshot.data_snapshot_sha256.encode("ascii"))
    digest.update(split.frozen_provenance_sha256.encode("ascii"))
    digest.update(np.asarray([horizon], dtype=np.int16).tobytes())
    digest.update(values.tobytes(order="C"))
    return values, digest.hexdigest()


@dataclass(frozen=True, slots=True)
class SelectionRecord:
    """Immutable validation evidence for one learner, tier, and horizon."""

    learner: str
    tier: str
    horizon_minutes: int
    candidate_parameter_json: tuple[bytes, ...]
    candidate_validation_mae: np.ndarray
    selected_candidate_index: int
    selection_fit_count: int
    validation_score_count: int
    data_snapshot_sha256: str
    split_provenance_sha256: str
    target_sha256: str
    feature_schema_sha256: str
    feature_block_sha256: str

    def __post_init__(self) -> None:
        learner = _strict_learner(self.learner)
        _strict_tier(self.tier)
        _strict_horizon(self.horizon_minutes)
        expected = tuple(
            _canonical_json_bytes(dict(candidate))
            for candidate in _frozen_candidates_without_config(learner)
        )
        actual = tuple(bytes(value) for value in self.candidate_parameter_json)
        if actual != expected:
            raise ValueError(
                f"{learner} candidate budget or declaration order differs from the frozen grid"
            )
        scores = np.asarray(self.candidate_validation_mae)
        if scores.dtype != np.dtype(np.float64) or scores.shape != (len(expected),):
            raise ValueError(
                "candidate validation MAE must be a float64 vector matching the budget"
            )
        if not np.isfinite(scores).all() or np.any(scores < 0):
            raise ValueError("candidate validation MAE must be finite and nonnegative")
        selected = _strict_integer(self.selected_candidate_index, "selected candidate index")
        if selected < 0 or selected >= len(scores):
            raise ValueError("selected candidate index is outside the frozen grid")
        expected_selected = min(
            range(len(scores)), key=lambda position: (scores[position], position)
        )
        if selected != expected_selected:
            raise ValueError("selected candidate must be the first minimum validation MAE")
        if _strict_integer(self.selection_fit_count, "selection fit count", positive=True) <= 0:
            raise AssertionError("unreachable")
        if (
            _strict_integer(self.validation_score_count, "validation score count", positive=True)
            <= 0
        ):
            raise AssertionError("unreachable")
        _validate_sha256(self.data_snapshot_sha256, "selection data snapshot")
        _validate_sha256(self.split_provenance_sha256, "selection split provenance")
        _validate_sha256(self.target_sha256, "selection target provenance")
        _validate_sha256(self.feature_schema_sha256, "selection feature schema")
        _validate_sha256(self.feature_block_sha256, "selection feature block")
        object.__setattr__(self, "learner", learner)
        object.__setattr__(self, "tier", str(self.tier))
        object.__setattr__(self, "horizon_minutes", int(self.horizon_minutes))
        object.__setattr__(self, "candidate_parameter_json", actual)
        object.__setattr__(self, "candidate_validation_mae", _immutable(scores, dtype=np.float64))

    @classmethod
    def create(
        cls,
        *,
        learner: str,
        tier: str,
        horizon_minutes: int,
        candidate_params: Sequence[Mapping[str, Any]],
        candidate_validation_mae: Sequence[float] | np.ndarray,
        selected_candidate_index: int,
        selection_fit_count: int,
        validation_score_count: int,
        data_snapshot_sha256: str,
        split_provenance_sha256: str,
        target_sha256: str,
        feature_schema_sha256: str,
        feature_block_sha256: str,
    ) -> SelectionRecord:
        parameter_json = tuple(_canonical_json_bytes(dict(params)) for params in candidate_params)
        return cls(
            learner=learner,
            tier=tier,
            horizon_minutes=horizon_minutes,
            candidate_parameter_json=parameter_json,
            candidate_validation_mae=np.asarray(candidate_validation_mae, dtype=np.float64),
            selected_candidate_index=selected_candidate_index,
            selection_fit_count=selection_fit_count,
            validation_score_count=validation_score_count,
            data_snapshot_sha256=data_snapshot_sha256,
            split_provenance_sha256=split_provenance_sha256,
            target_sha256=target_sha256,
            feature_schema_sha256=feature_schema_sha256,
            feature_block_sha256=feature_block_sha256,
        )

    @property
    def candidate_params(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(_decode_parameter_json(value) for value in self.candidate_parameter_json)

    @property
    def selected_params(self) -> Mapping[str, Any]:
        return _decode_parameter_json(self.candidate_parameter_json[self.selected_candidate_index])

    @property
    def selected_param_sha256(self) -> str:
        return _parameter_sha256_bytes(self.candidate_parameter_json[self.selected_candidate_index])


@dataclass(frozen=True, slots=True)
class PredictionBundle:
    """Immutable, local-only issue-indexed rolling predictions for one task."""

    learner: str
    tier: str
    horizon_minutes: int
    issue_times: np.ndarray
    y_true: np.ndarray
    predictions: np.ndarray
    day_start_utc_s: np.ndarray
    parameter_hashes: np.ndarray

    def __post_init__(self) -> None:
        learner = _strict_learner(self.learner)
        tier = _strict_tier(self.tier)
        horizon = _strict_horizon(self.horizon_minutes)
        times = np.asarray(self.issue_times)
        truth = np.asarray(self.y_true)
        predictions = np.asarray(self.predictions)
        days = np.asarray(self.day_start_utc_s)
        hashes = np.asarray(self.parameter_hashes)
        row_count = len(times) if times.ndim == 1 else -1
        if times.dtype != np.dtype(np.int64) or row_count <= 0 or np.any(np.diff(times) <= 0):
            raise ValueError("prediction issue index must be nonempty, unique, increasing int64")
        if truth.shape != (row_count,) or predictions.shape != (row_count,):
            raise ValueError("prediction truth and values must align with the issue index")
        if not np.issubdtype(truth.dtype, np.number) or not np.issubdtype(
            predictions.dtype, np.number
        ):
            raise TypeError("prediction truth and values must be numeric")
        if not np.isfinite(truth).all() or not np.isfinite(predictions).all():
            raise ValueError("prediction truth and values must be finite")
        if days.dtype != np.dtype(np.int64) or days.shape != (row_count,):
            raise ValueError("prediction local-day starts must be an aligned int64 vector")
        if hashes.shape != (row_count,) or hashes.dtype.kind != "S":
            raise ValueError("prediction parameter hashes must be an aligned bytes vector")
        decoded_hashes = tuple(value.decode("ascii") for value in hashes)
        for value in decoded_hashes:
            _validate_sha256(value, "prediction parameter hash")
        if len(set(decoded_hashes)) != 1:
            raise ValueError("prediction parameter hash must remain constant throughout testing")
        expected_days = np.asarray(
            [_local_midnight_epoch(int(value)) for value in times], dtype=np.int64
        )
        if not np.array_equal(days, expected_days):
            raise ValueError("prediction day index must equal each issue time's local midnight")
        object.__setattr__(self, "learner", learner)
        object.__setattr__(self, "tier", tier)
        object.__setattr__(self, "horizon_minutes", horizon)
        object.__setattr__(self, "issue_times", _immutable(times, dtype=np.int64))
        object.__setattr__(self, "y_true", _immutable(truth, dtype=np.float64))
        object.__setattr__(self, "predictions", _immutable(predictions, dtype=np.float64))
        object.__setattr__(self, "day_start_utc_s", _immutable(days, dtype=np.int64))
        object.__setattr__(self, "parameter_hashes", _immutable(hashes, dtype="S64"))

    @classmethod
    def create(
        cls,
        *,
        learner: str,
        tier: str,
        horizon_minutes: int,
        issue_times: Any,
        y_true: Any,
        predictions: Any,
        day_start_utc_s: Any,
        selected_param_sha256: str,
    ) -> PredictionBundle:
        digest = _validate_sha256(selected_param_sha256, "selected parameter hash")
        row_count = len(np.asarray(issue_times))
        hashes = np.full(row_count, digest.encode("ascii"), dtype="S64")
        return cls(
            learner=learner,
            tier=tier,
            horizon_minutes=horizon_minutes,
            issue_times=np.asarray(issue_times, dtype=np.int64),
            y_true=np.asarray(y_true, dtype=np.float64),
            predictions=np.asarray(predictions, dtype=np.float64),
            day_start_utc_s=np.asarray(day_start_utc_s, dtype=np.int64),
            parameter_hashes=hashes,
        )


@dataclass(frozen=True, slots=True)
class PersistencePrediction:
    """Immutable persistence result with explicit availability and reference index."""

    name: str
    horizon_minutes: int
    issue_times: np.ndarray
    predictions: np.ndarray
    availability: np.ndarray
    reference_times: np.ndarray

    def __post_init__(self) -> None:
        if self.name not in PERSISTENCE_ORDER:
            raise ValueError("unknown persistence baseline")
        horizon = _strict_horizon(self.horizon_minutes)
        times = np.asarray(self.issue_times)
        predictions = np.asarray(self.predictions)
        available = np.asarray(self.availability)
        references = np.asarray(self.reference_times)
        if times.dtype != np.dtype(np.int64) or times.ndim != 1 or not len(times):
            raise ValueError("persistence issue index must be a nonempty int64 vector")
        if np.any(np.diff(times) <= 0):
            raise ValueError("persistence issue index must be strictly increasing and unique")
        if np.any(times % 900 != 0):
            raise ValueError("persistence issue index must remain on the 15-minute UTC grid")
        if predictions.shape != times.shape or references.shape != times.shape:
            raise ValueError("persistence values and references must align with issue times")
        if available.dtype != np.dtype(np.bool_) or available.shape != times.shape:
            raise ValueError("persistence availability must be an aligned boolean vector")
        if not np.array_equal(np.isnan(predictions), ~available):
            raise ValueError("persistence unavailable rows must be exactly the NaN predictions")
        if not np.isfinite(predictions[available]).all():
            raise ValueError("available persistence predictions must be finite")
        if references.dtype != np.dtype(np.int64):
            raise ValueError("persistence reference index must be int64")
        if self.name == "last_value":
            expected_references = times - 900
        else:
            days = 1 if self.name == "previous_day" else 7
            expected_references = np.asarray(
                [_calendar_shift_epoch(int(issue + horizon * 60 - 900), days) for issue in times],
                dtype=np.int64,
            )
        if not np.array_equal(references, expected_references):
            raise ValueError("persistence reference formula differs from the frozen baseline")
        object.__setattr__(self, "name", str(self.name))
        object.__setattr__(self, "horizon_minutes", horizon)
        object.__setattr__(self, "issue_times", _immutable(times, dtype=np.int64))
        object.__setattr__(self, "predictions", _immutable(predictions, dtype=np.float64))
        object.__setattr__(self, "availability", _immutable(available, dtype=np.bool_))
        object.__setattr__(self, "reference_times", _immutable(references, dtype=np.int64))


def _formal_implementation_sha256() -> str:
    digest = hashlib.sha256()
    source_root = Path(__file__).resolve().parent
    for name in (
        "acn_jpl_gate1_contracts.py",
        "acn_jpl_gate1_data.py",
        "acn_jpl_gate1_features.py",
        "acn_jpl_gate1_models.py",
    ):
        payload = (source_root / name).read_bytes()
        digest.update(name.encode("ascii"))
        digest.update(np.asarray([len(payload)], dtype=np.int64).tobytes())
        digest.update(payload)
    return digest.hexdigest()


def _selection_result_sha256(record: SelectionRecord) -> str:
    digest = hashlib.sha256()
    identity = {
        "learner": record.learner,
        "tier": record.tier,
        "horizon_minutes": record.horizon_minutes,
        "selected_candidate_index": record.selected_candidate_index,
        "selection_fit_count": record.selection_fit_count,
        "validation_score_count": record.validation_score_count,
        "data_snapshot_sha256": record.data_snapshot_sha256,
        "split_provenance_sha256": record.split_provenance_sha256,
        "target_sha256": record.target_sha256,
        "feature_schema_sha256": record.feature_schema_sha256,
        "feature_block_sha256": record.feature_block_sha256,
    }
    digest.update(_canonical_json_bytes(identity))
    for candidate in record.candidate_parameter_json:
        digest.update(np.asarray([len(candidate)], dtype=np.int64).tobytes())
        digest.update(candidate)
    scores = np.ascontiguousarray(record.candidate_validation_mae, dtype=np.float64)
    digest.update(scores.tobytes(order="C"))
    return digest.hexdigest()


def _prediction_result_sha256(bundle: PredictionBundle) -> str:
    digest = hashlib.sha256()
    digest.update(
        _canonical_json_bytes(
            {
                "learner": bundle.learner,
                "tier": bundle.tier,
                "horizon_minutes": bundle.horizon_minutes,
            }
        )
    )
    for array in (
        bundle.issue_times,
        bundle.y_true,
        bundle.predictions,
        bundle.day_start_utc_s,
        bundle.parameter_hashes,
    ):
        value = np.ascontiguousarray(array)
        digest.update(value.dtype.str.encode("ascii"))
        digest.update(np.asarray(value.shape, dtype=np.int64).tobytes())
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


def _formal_execution_contract(
    selection: SelectionRecord,
    prediction: PredictionBundle,
) -> dict[str, Any]:
    if (
        prediction.learner,
        prediction.tier,
        prediction.horizon_minutes,
    ) != (selection.learner, selection.tier, selection.horizon_minutes):
        raise ValueError("formal selection and prediction task identities differ")
    hashes = {value.decode("ascii") for value in prediction.parameter_hashes}
    if hashes != {selection.selected_param_sha256}:
        raise ValueError("formal prediction does not use one fixed selected parameter hash")
    emitted = np.ascontiguousarray(prediction.predictions, dtype=np.float64)
    emitted_sha256 = hashlib.sha256()
    emitted_sha256.update(emitted.dtype.str.encode("ascii"))
    emitted_sha256.update(np.asarray(emitted.shape, dtype=np.int64).tobytes())
    emitted_sha256.update(emitted.tobytes(order="C"))
    return {
        "schema_version": _FORMAL_EXECUTION_SCHEMA,
        "task": {
            "learner": selection.learner,
            "tier": selection.tier,
            "horizon_minutes": selection.horizon_minutes,
        },
        "selection_policy": "unrounded_validation_mae_first_declared_tie",
        "test_parameter_policy": "fixed_selected_sha256",
        "test_refit_policy": "one_refit_per_local_midnight",
        "test_refit_count": len(np.unique(prediction.day_start_utc_s)),
        "prediction_emission": {
            "source": "direct_estimator_predict_output",
            "values_sha256": emitted_sha256.hexdigest(),
            "postprocessing_operations": [],
        },
    }


def _formal_result_seal_payload(
    *,
    implementation_sha256: str,
    config_sha256: str,
    snapshot_provenance_sha256: str,
    split_provenance_sha256: str,
    feature_encoding_sha256: str,
    target_sha256: str,
    selection_sha256: str,
    prediction_sha256: str,
    execution_contract_json: bytes,
) -> bytes:
    return _canonical_json_bytes(
        {
            "schema_version": _FORMAL_EXECUTION_SCHEMA,
            "implementation_sha256": implementation_sha256,
            "config_sha256": config_sha256,
            "snapshot_provenance_sha256": snapshot_provenance_sha256,
            "split_provenance_sha256": split_provenance_sha256,
            "feature_encoding_sha256": feature_encoding_sha256,
            "target_sha256": target_sha256,
            "selection_sha256": selection_sha256,
            "prediction_sha256": prediction_sha256,
            "execution_contract": json.loads(execution_contract_json.decode("ascii")),
        }
    )


@dataclass(frozen=True, slots=True, init=False)
class FormalModelTaskResult:
    """Cross-process formal result issued only by :func:`run_model_task`."""

    selection_record: SelectionRecord
    prediction_bundle: PredictionBundle
    implementation_sha256: str
    config_sha256: str
    snapshot_provenance_sha256: str
    split_provenance_sha256: str
    feature_encoding_sha256: str
    target_sha256: str
    selection_sha256: str
    prediction_sha256: str
    execution_contract_json: bytes
    execution_sha256: str

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("FormalModelTaskResult can only be issued by run_model_task")

    def __reduce_ex__(self, _protocol: int) -> tuple[Any, tuple[tuple[Any, ...]]]:
        _validate_formal_model_task_result(self)
        state = tuple(getattr(self, name) for name in self.__slots__)
        return _restore_formal_model_task_result, (state,)

    def __setstate__(self, _state: Any) -> None:
        raise TypeError("formal task state can only be restored by the checkpoint verifier")

    @property
    def execution_contract(self) -> Mapping[str, Any]:
        return MappingProxyType(json.loads(self.execution_contract_json.decode("ascii")))


def _validate_formal_model_task_result(result: FormalModelTaskResult) -> None:
    if type(result) is not FormalModelTaskResult:
        raise TypeError("formal model validation requires an exact FormalModelTaskResult")
    if not isinstance(result.selection_record, SelectionRecord) or not isinstance(
        result.prediction_bundle, PredictionBundle
    ):
        raise TypeError("formal task result must contain immutable model result objects")
    immutable_arrays = (
        result.selection_record.candidate_validation_mae,
        result.prediction_bundle.issue_times,
        result.prediction_bundle.y_true,
        result.prediction_bundle.predictions,
        result.prediction_bundle.day_start_utc_s,
        result.prediction_bundle.parameter_hashes,
    )
    if any(value.flags.writeable for value in immutable_arrays):
        raise ValueError("formal task result arrays must remain immutable")
    for context, value in (
        ("formal implementation", result.implementation_sha256),
        ("formal config", result.config_sha256),
        ("formal snapshot", result.snapshot_provenance_sha256),
        ("formal split", result.split_provenance_sha256),
        ("formal feature encoding", result.feature_encoding_sha256),
        ("formal target", result.target_sha256),
        ("formal selection", result.selection_sha256),
        ("formal prediction", result.prediction_sha256),
        ("formal execution", result.execution_sha256),
    ):
        _validate_sha256(value, context)
    if result.implementation_sha256 != _formal_implementation_sha256():
        raise ValueError("formal task implementation provenance has changed")
    if result.split_provenance_sha256 != result.selection_record.split_provenance_sha256:
        raise ValueError("formal task split differs from its selection record")
    if result.target_sha256 != result.selection_record.target_sha256:
        raise ValueError("formal task target differs from its selection record")
    if result.selection_sha256 != _selection_result_sha256(result.selection_record):
        raise ValueError("formal task selection content differs from its seal")
    if result.prediction_sha256 != _prediction_result_sha256(result.prediction_bundle):
        raise ValueError("formal task prediction content differs from its seal")
    expected_contract = _formal_execution_contract(
        result.selection_record, result.prediction_bundle
    )
    if result.execution_contract_json != _canonical_json_bytes(expected_contract):
        raise ValueError("formal task execution contract differs from its sealed result")
    payload = _formal_result_seal_payload(
        implementation_sha256=result.implementation_sha256,
        config_sha256=result.config_sha256,
        snapshot_provenance_sha256=result.snapshot_provenance_sha256,
        split_provenance_sha256=result.split_provenance_sha256,
        feature_encoding_sha256=result.feature_encoding_sha256,
        target_sha256=result.target_sha256,
        selection_sha256=result.selection_sha256,
        prediction_sha256=result.prediction_sha256,
        execution_contract_json=result.execution_contract_json,
    )
    if result.execution_sha256 != hashlib.sha256(payload).hexdigest():
        raise ValueError("formal task execution seal is inconsistent")


def verified_formal_model_task_provenance(result: FormalModelTaskResult) -> str:
    """Revalidate a formal task after checkpoint/process transport."""

    if not isinstance(result, FormalModelTaskResult):
        raise TypeError("formal model provenance requires a FormalModelTaskResult")
    _validate_formal_model_task_result(result)
    return result.execution_sha256


def _freeze_formal_task_results(
    value: Sequence[FormalModelTaskResult],
) -> tuple[FormalModelTaskResult, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError("manifest task_results must be a sequence of formal results")
    results = tuple(value)
    if any(type(result) is not FormalModelTaskResult for result in results):
        raise TypeError("manifest accepts only exact FormalModelTaskResult objects")
    return results


def _restore_formal_model_task_result(
    state: tuple[Any, ...],
) -> FormalModelTaskResult:
    """Private pickle/joblib reconstruction with full content revalidation."""

    if not isinstance(state, tuple) or len(state) != len(FormalModelTaskResult.__slots__):
        raise ValueError("formal task checkpoint field count is invalid")
    checkpoint_selection, checkpoint_prediction = state[:2]
    if not isinstance(checkpoint_selection, SelectionRecord) or not isinstance(
        checkpoint_prediction, PredictionBundle
    ):
        raise TypeError("formal task checkpoint contains invalid result objects")
    selection = SelectionRecord(
        learner=checkpoint_selection.learner,
        tier=checkpoint_selection.tier,
        horizon_minutes=checkpoint_selection.horizon_minutes,
        candidate_parameter_json=checkpoint_selection.candidate_parameter_json,
        candidate_validation_mae=checkpoint_selection.candidate_validation_mae,
        selected_candidate_index=checkpoint_selection.selected_candidate_index,
        selection_fit_count=checkpoint_selection.selection_fit_count,
        validation_score_count=checkpoint_selection.validation_score_count,
        data_snapshot_sha256=checkpoint_selection.data_snapshot_sha256,
        split_provenance_sha256=checkpoint_selection.split_provenance_sha256,
        target_sha256=checkpoint_selection.target_sha256,
        feature_schema_sha256=checkpoint_selection.feature_schema_sha256,
        feature_block_sha256=checkpoint_selection.feature_block_sha256,
    )
    prediction = PredictionBundle(
        learner=checkpoint_prediction.learner,
        tier=checkpoint_prediction.tier,
        horizon_minutes=checkpoint_prediction.horizon_minutes,
        issue_times=checkpoint_prediction.issue_times,
        y_true=checkpoint_prediction.y_true,
        predictions=checkpoint_prediction.predictions,
        day_start_utc_s=checkpoint_prediction.day_start_utc_s,
        parameter_hashes=checkpoint_prediction.parameter_hashes,
    )
    result = object.__new__(FormalModelTaskResult)
    for name, value in zip(
        FormalModelTaskResult.__slots__,
        (selection, prediction, *state[2:]),
        strict=True,
    ):
        object.__setattr__(result, name, value)
    _validate_formal_model_task_result(result)
    return result


def _calendar_shift_epoch(epoch_seconds: int, days: int) -> int:
    local = datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(_ZONE)
    shifted_date = local.date() - timedelta(days=days)
    shifted = datetime.combine(shifted_date, local.timetz().replace(tzinfo=None), tzinfo=_ZONE)
    return int(shifted.timestamp())


def persistence_predictions(
    snapshot: Gate1Snapshot,
    rows: Any,
    *,
    horizon_minutes: int,
) -> Mapping[str, PersistencePrediction]:
    """Evaluate the three exact-bin persistence baselines without fallback."""

    if not isinstance(snapshot, Gate1Snapshot):
        raise TypeError("persistence input must be a Gate1Snapshot")
    horizon = _strict_horizon(horizon_minutes)
    selected_rows = _row_indexes(rows, len(snapshot.issue_times), "persistence rows")
    issue_times = np.asarray(snapshot.issue_times[selected_rows], dtype=np.int64)
    station_times = np.asarray(snapshot.station_times)
    station_values = np.asarray(snapshot.station_current_mean_a)
    station_valid = np.asarray(snapshot.station_valid_90)
    if station_times.dtype != np.dtype(np.int64) or station_times.ndim != 1:
        raise ValueError("station index must be a one-dimensional int64 vector")
    if not len(station_times) or np.any(np.diff(station_times) <= 0):
        raise ValueError("station index must be strictly increasing and unique")
    if station_values.shape != station_times.shape or station_valid.shape != station_times.shape:
        raise ValueError("station values and validity must align with station index")
    if station_valid.dtype != np.dtype(np.bool_):
        raise ValueError("station valid90 must be boolean")

    references: dict[str, np.ndarray] = {
        "last_value": issue_times - 900,
        "previous_day": np.asarray(
            [_calendar_shift_epoch(int(issue + horizon * 60 - 900), 1) for issue in issue_times],
            dtype=np.int64,
        ),
        "previous_week": np.asarray(
            [_calendar_shift_epoch(int(issue + horizon * 60 - 900), 7) for issue in issue_times],
            dtype=np.int64,
        ),
    }
    output: dict[str, PersistencePrediction] = {}
    for name in PERSISTENCE_ORDER:
        reference = references[name]
        positions = np.searchsorted(station_times, reference)
        exists = positions < len(station_times)
        safe_positions = np.minimum(positions, len(station_times) - 1)
        exists &= station_times[safe_positions] == reference
        available = exists.copy()
        available[exists] &= station_valid[safe_positions[exists]]
        available[exists] &= np.isfinite(station_values[safe_positions[exists]])
        prediction = np.full(len(reference), np.nan, dtype=np.float64)
        prediction[available] = station_values[safe_positions[available]]
        output[name] = PersistencePrediction(
            name=name,
            horizon_minutes=horizon,
            issue_times=issue_times,
            predictions=prediction,
            availability=available.astype(np.bool_),
            reference_times=reference,
        )
    return MappingProxyType(output)


def _require_block_split_identity(feature_block: FeatureBlock, split: Gate1TimeSplit) -> str:
    if not isinstance(split, Gate1TimeSplit):
        raise TypeError("model split must be a frozen Gate1TimeSplit")
    split.__post_init__()
    tier = _schema_tier(feature_block)
    if not np.array_equal(feature_block.issue_times, split.issue_times):
        raise ValueError("feature block and time split must share the exact ordered row index")
    return tier


def _default_preprocessor_factory(learner: str) -> RidgePreprocessor | HGBPreprocessor:
    return RidgePreprocessor() if learner == "ridge" else HGBPreprocessor()


def _select_model_params_with_factories(
    *,
    learner: str,
    tier: str,
    horizon_minutes: int,
    feature_block: FeatureBlock,
    snapshot: Gate1Snapshot,
    split: Gate1TimeSplit,
    config: Mapping[str, Any],
    estimator_factory: EstimatorFactory,
    preprocessor_factory: PreprocessorFactory,
) -> SelectionRecord:
    """Injection seam for focused tests; formal callers use the public wrapper."""

    learner_name = _strict_learner(learner)
    tier_name = _strict_tier(tier)
    horizon = _strict_horizon(horizon_minutes)
    canonical_config = _require_model_config(config)
    split_config = split.config
    if _canonical_json_bytes(canonical_config) != _canonical_json_bytes(split_config):
        raise ValueError("model config differs from the split's frozen config provenance")
    actual_tier = _require_block_split_identity(feature_block, split)
    if actual_tier != tier_name:
        raise ValueError("declared tier differs from the feature-block schema")
    values, target_sha256 = _snapshot_target(snapshot, split, horizon)
    fit_rows = split.selection_fit_rows(horizon)
    score_rows = split.validation_score_rows(horizon)
    processor = preprocessor_factory(learner_name)
    try:
        processor.fit(feature_block, fit_rows)
        x_fit = processor.transform(feature_block, fit_rows)
        x_score = processor.transform(feature_block, score_rows)
    except Exception as exc:
        raise RuntimeError(
            f"{learner_name} {tier_name} horizon {horizon} preprocessing failed"
        ) from exc
    candidates = frozen_model_candidates(learner_name, canonical_config)
    scores = np.empty(len(candidates), dtype=np.float64)
    for position, params in enumerate(candidates):
        try:
            estimator = estimator_factory(learner_name, params)
            estimator.fit(x_fit, values[fit_rows])
            prediction = np.asarray(estimator.predict(x_score), dtype=np.float64)
        except Exception as exc:
            raise RuntimeError(
                f"{learner_name} candidate {position} failed for {tier_name} horizon {horizon}"
            ) from exc
        if prediction.shape != (len(score_rows),) or not np.isfinite(prediction).all():
            raise ValueError(
                f"{learner_name} candidate {position} produced non-finite or misaligned validation output"
            )
        score = float(np.mean(np.abs(prediction - values[score_rows])))
        if not math.isfinite(score):
            raise ValueError(f"{learner_name} candidate {position} validation MAE is non-finite")
        scores[position] = score
    selected = min(range(len(scores)), key=lambda position: (scores[position], position))
    return SelectionRecord.create(
        learner=learner_name,
        tier=tier_name,
        horizon_minutes=horizon,
        candidate_params=candidates,
        candidate_validation_mae=scores,
        selected_candidate_index=selected,
        selection_fit_count=len(fit_rows),
        validation_score_count=len(score_rows),
        data_snapshot_sha256=snapshot.data_snapshot_sha256,
        split_provenance_sha256=split.frozen_provenance_sha256,
        target_sha256=target_sha256,
        feature_schema_sha256=_feature_schema_sha256(feature_block),
        feature_block_sha256=_feature_block_sha256(feature_block),
    )


def select_model_params(
    *,
    learner: str,
    tier: str,
    horizon_minutes: int,
    feature_block: FeatureBlock,
    snapshot: Gate1Snapshot,
    split: Gate1TimeSplit,
    config: Mapping[str, Any],
) -> SelectionRecord:
    """Evaluate every frozen candidate on its snapshot-bound validation target."""

    return _select_model_params_with_factories(
        learner=learner,
        tier=tier,
        horizon_minutes=horizon_minutes,
        feature_block=feature_block,
        snapshot=snapshot,
        split=split,
        config=config,
        estimator_factory=make_frozen_estimator,
        preprocessor_factory=_default_preprocessor_factory,
    )


def _rolling_origin_predict_with_factories(
    *,
    feature_block: FeatureBlock,
    snapshot: Gate1Snapshot,
    split: Gate1TimeSplit,
    selection: SelectionRecord,
    estimator_factory: EstimatorFactory,
    preprocessor_factory: PreprocessorFactory,
) -> PredictionBundle:
    """Injection seam for rolling tests; formal callers use the public wrapper."""

    if not isinstance(selection, SelectionRecord):
        raise TypeError("rolling prediction requires an immutable SelectionRecord")
    tier = _require_block_split_identity(feature_block, split)
    if tier != selection.tier:
        raise ValueError("selection tier differs from the rolling feature block")
    horizon = selection.horizon_minutes
    target_values, target_sha256 = _snapshot_target(snapshot, split, horizon)
    if selection.data_snapshot_sha256 != snapshot.data_snapshot_sha256:
        raise ValueError("selection data snapshot differs from the rolling snapshot")
    if selection.split_provenance_sha256 != split.frozen_provenance_sha256:
        raise ValueError("selection split provenance differs from the rolling split")
    if selection.target_sha256 != target_sha256:
        raise ValueError("selection target provenance differs from the rolling target")
    if selection.feature_schema_sha256 != _feature_schema_sha256(feature_block):
        raise ValueError("selection feature schema differs from the rolling feature block")
    if selection.feature_block_sha256 != _feature_block_sha256(feature_block):
        raise ValueError("selection feature block provenance differs from the rolling block")
    expected_selection_counts = (
        len(split.selection_fit_rows(horizon)),
        len(split.validation_score_rows(horizon)),
    )
    if (selection.selection_fit_count, selection.validation_score_count) != (
        expected_selection_counts
    ):
        raise ValueError("selection row counts differ from the frozen split")
    selected_params = selection.selected_params
    if _parameter_sha256_bytes(_canonical_json_bytes(dict(selected_params))) != (
        selection.selected_param_sha256
    ):
        raise ValueError("selected parameter hash is inconsistent")

    issue_parts: list[np.ndarray] = []
    truth_parts: list[np.ndarray] = []
    prediction_parts: list[np.ndarray] = []
    day_parts: list[np.ndarray] = []
    rolling_rows = split.rolling_fit_rows(horizon)
    for day_start, day_rows in split.test_day_rows.items():
        fit_rows = rolling_rows[day_start]
        availability = split.label_availability_times(horizon)
        if np.any(split.issue_times[fit_rows] >= day_start) or np.any(
            availability[fit_rows] > day_start
        ):
            raise ValueError("rolling fit rows violate the issue/label availability embargo")
        if np.intersect1d(fit_rows, day_rows).size:
            raise ValueError("current-day rows entered the midnight rolling fit")
        processor = preprocessor_factory(selection.learner)
        try:
            processor.fit(feature_block, fit_rows)
            x_fit = processor.transform(feature_block, fit_rows)
            x_day = processor.transform(feature_block, day_rows)
            estimator = estimator_factory(selection.learner, selected_params)
            estimator.fit(x_fit, target_values[fit_rows])
            prediction = np.asarray(estimator.predict(x_day), dtype=np.float64)
        except Exception as exc:
            raise RuntimeError(
                f"rolling fit failed for {selection.learner} {tier} horizon {horizon} "
                f"on {_local_date_label(day_start)}"
            ) from exc
        if prediction.shape != (len(day_rows),) or not np.isfinite(prediction).all():
            raise ValueError("rolling model produced non-finite or misaligned predictions")
        issue_parts.append(split.issue_times[day_rows])
        truth_parts.append(target_values[day_rows])
        prediction_parts.append(prediction)
        day_parts.append(np.full(len(day_rows), day_start, dtype=np.int64))

    issue_times = np.concatenate(issue_parts)
    if not np.array_equal(issue_times, split.issue_times[split.test_rows]):
        raise ValueError("rolling prediction rows differ from the frozen test row identity")
    return PredictionBundle.create(
        learner=selection.learner,
        tier=tier,
        horizon_minutes=horizon,
        issue_times=issue_times,
        y_true=np.concatenate(truth_parts),
        predictions=np.concatenate(prediction_parts),
        day_start_utc_s=np.concatenate(day_parts),
        selected_param_sha256=selection.selected_param_sha256,
    )


def rolling_origin_predict(
    *,
    feature_block: FeatureBlock,
    snapshot: Gate1Snapshot,
    split: Gate1TimeSplit,
    selection: SelectionRecord,
) -> PredictionBundle:
    """Refit one fixed selected model per local test day without test-time injection."""

    return _rolling_origin_predict_with_factories(
        feature_block=feature_block,
        snapshot=snapshot,
        split=split,
        selection=selection,
        estimator_factory=make_frozen_estimator,
        preprocessor_factory=_default_preprocessor_factory,
    )


def _make_formal_model_task_runner() -> Callable[..., FormalModelTaskResult]:
    """Close formal execution over the fixed implementations, outside test seams."""

    select_implementation = _select_model_params_with_factories
    rolling_implementation = _rolling_origin_predict_with_factories
    estimator_implementation = make_frozen_estimator
    preprocessor_implementation = _default_preprocessor_factory
    config_validator = _require_model_config
    snapshot_verifier = verified_snapshot_provenance
    feature_verifier = verified_feature_block_provenance

    def run_model_task(
        *,
        learner: str,
        tier: str,
        horizon_minutes: int,
        feature_block: FeatureBlock,
        snapshot: Gate1Snapshot,
        split: Gate1TimeSplit,
        config: Mapping[str, Any],
    ) -> FormalModelTaskResult:
        """Run one formal canonical task with no injectable implementation surface."""

        canonical_config = config_validator(config)
        learner_name = _strict_learner(learner)
        tier_name = _strict_tier(tier)
        horizon = _strict_horizon(horizon_minutes)
        if not isinstance(split, Gate1TimeSplit):
            raise TypeError("formal model task split must be a Gate1TimeSplit")
        split.__post_init__()
        if _canonical_json_bytes(canonical_config) != _canonical_json_bytes(split.config):
            raise ValueError("formal model task config differs from the frozen split")
        snapshot_provenance_sha256 = snapshot_verifier(snapshot)
        feature_encoding_sha256 = feature_verifier(
            feature_block,
            snapshot,
            tier=tier_name,
        )

        selection = select_implementation(
            learner=learner_name,
            tier=tier_name,
            horizon_minutes=horizon,
            feature_block=feature_block,
            snapshot=snapshot,
            split=split,
            config=canonical_config,
            estimator_factory=estimator_implementation,
            preprocessor_factory=preprocessor_implementation,
        )
        prediction = rolling_implementation(
            feature_block=feature_block,
            snapshot=snapshot,
            split=split,
            selection=selection,
            estimator_factory=estimator_implementation,
            preprocessor_factory=preprocessor_implementation,
        )
        implementation_sha256 = _formal_implementation_sha256()
        config_sha256 = hashlib.sha256(_canonical_json_bytes(canonical_config)).hexdigest()
        selection_sha256 = _selection_result_sha256(selection)
        prediction_sha256 = _prediction_result_sha256(prediction)
        execution_contract_json = _canonical_json_bytes(
            _formal_execution_contract(selection, prediction)
        )
        payload = _formal_result_seal_payload(
            implementation_sha256=implementation_sha256,
            config_sha256=config_sha256,
            snapshot_provenance_sha256=snapshot_provenance_sha256,
            split_provenance_sha256=split.frozen_provenance_sha256,
            feature_encoding_sha256=feature_encoding_sha256,
            target_sha256=selection.target_sha256,
            selection_sha256=selection_sha256,
            prediction_sha256=prediction_sha256,
            execution_contract_json=execution_contract_json,
        )
        result = object.__new__(FormalModelTaskResult)
        state = (
            selection,
            prediction,
            implementation_sha256,
            config_sha256,
            snapshot_provenance_sha256,
            split.frozen_provenance_sha256,
            feature_encoding_sha256,
            selection.target_sha256,
            selection_sha256,
            prediction_sha256,
            execution_contract_json,
            hashlib.sha256(payload).hexdigest(),
        )
        for name, value in zip(FormalModelTaskResult.__slots__, state, strict=True):
            object.__setattr__(result, name, value)
        _validate_formal_model_task_result(result)
        return result

    return run_model_task


run_model_task = _make_formal_model_task_runner()
run_model_task.__qualname__ = "run_model_task"
del _make_formal_model_task_runner


def _feature_dimensions_from_blocks(
    value: Mapping[str, FeatureBlock],
    split: Gate1TimeSplit,
) -> dict[str, dict[str, int]]:
    if tuple(value) != TIER_ORDER:
        raise ValueError("feature blocks must use the complete canonical M1-M4 order")
    result: dict[str, dict[str, int]] = {}
    for tier in TIER_ORDER:
        block = value[tier]
        validate_feature_block_schema(block, tier=tier)
        if not np.array_equal(block.issue_times, split.issue_times):
            raise ValueError(f"{tier} feature block differs from the frozen split issue index")
        expected = {
            "raw": _EXPECTED_RAW_DIMENSIONS[tier],
            "indicators": _EXPECTED_INDICATOR_COUNTS[tier],
            "input": _EXPECTED_INPUT_DIMENSIONS[tier],
        }
        actual = {
            "raw": int(block.values.shape[1]),
            "indicators": int(np.sum(block.nullable_mask)),
            "input": int(block.values.shape[1] + np.sum(block.nullable_mask)),
        }
        if actual != expected:
            raise ValueError(f"{tier} feature dimensions differ from the frozen schema")
        result[tier] = actual
    return result


def _persistence_coverage_from_results(
    value: Mapping[int, Mapping[str, PersistencePrediction]],
    snapshot: Gate1Snapshot,
    split: Gate1TimeSplit,
) -> dict[str, dict[str, int]]:
    if tuple(value) != HORIZONS_MINUTES:
        raise ValueError("persistence results must use the complete canonical horizon order")
    result: dict[str, dict[str, int]] = {baseline: {} for baseline in PERSISTENCE_ORDER}
    for horizon in HORIZONS_MINUTES:
        per_horizon = value[horizon]
        if tuple(per_horizon) != PERSISTENCE_ORDER:
            raise ValueError("persistence results must use the complete canonical baseline order")
        recomputed = persistence_predictions(snapshot, split.test_rows, horizon_minutes=horizon)
        for baseline in PERSISTENCE_ORDER:
            actual = per_horizon[baseline]
            expected_result = recomputed[baseline]
            if not isinstance(actual, PersistencePrediction):
                raise TypeError("persistence manifest inputs must be PersistencePrediction objects")
            if actual.name != baseline or actual.horizon_minutes != horizon:
                raise ValueError("persistence result identity differs from its manifest key")
            for field in ("issue_times", "availability", "reference_times"):
                if not np.array_equal(getattr(actual, field), getattr(expected_result, field)):
                    raise ValueError(f"persistence {baseline} {field} differs from recomputation")
            if not np.array_equal(actual.predictions, expected_result.predictions, equal_nan=True):
                raise ValueError(f"persistence {baseline} predictions differ from recomputation")
            count = int(np.sum(actual.availability))
            if count != _EXPECTED_PERSISTENCE_COVERAGE[baseline]:
                raise ValueError(
                    f"{baseline} horizon {horizon} availability must equal "
                    f"{_EXPECTED_PERSISTENCE_COVERAGE[baseline]}"
                )
            result[baseline][str(horizon)] = count
    return result


def build_model_selection_manifest(
    *,
    config: Mapping[str, Any],
    snapshot: Gate1Snapshot,
    split: Gate1TimeSplit,
    feature_blocks: Mapping[str, FeatureBlock],
    task_results: Sequence[FormalModelTaskResult],
    persistence_by_horizon: Mapping[int, Mapping[str, PersistencePrediction]],
) -> dict[str, Any]:
    """Certify aggregate-only output from all 40 formal model-task results."""

    frozen_task_results = _freeze_formal_task_results(task_results)

    canonical_config = _require_model_config(config)
    if not isinstance(split, Gate1TimeSplit):
        raise TypeError("manifest split must be a Gate1TimeSplit")
    split.__post_init__()
    if _canonical_json_bytes(canonical_config) != _canonical_json_bytes(split.config):
        raise ValueError("manifest config differs from the split's frozen provenance")
    config_sha256 = hashlib.sha256(_canonical_json_bytes(canonical_config)).hexdigest()
    snapshot_provenance_sha256 = verified_snapshot_provenance(snapshot)
    implementation_sha256 = _formal_implementation_sha256()
    if snapshot.data_snapshot_sha256 != canonical_config["data_snapshot_sha256"]:
        raise ValueError("manifest snapshot differs from the frozen config")
    target_provenance = {
        str(horizon): _snapshot_target(snapshot, split, horizon)[1] for horizon in HORIZONS_MINUTES
    }
    dimensions = _feature_dimensions_from_blocks(feature_blocks, split)
    feature_schema_provenance = {
        tier: _feature_schema_sha256(feature_blocks[tier]) for tier in TIER_ORDER
    }
    feature_block_provenance = {
        tier: _feature_block_sha256(feature_blocks[tier]) for tier in TIER_ORDER
    }
    feature_encoding_provenance = {
        tier: verified_feature_block_provenance(
            feature_blocks[tier],
            snapshot,
            tier=tier,
        )
        for tier in TIER_ORDER
    }
    row_index_used_as_feature = any(
        name in _FORBIDDEN_FEATURE_NAMES
        for block in feature_blocks.values()
        for name in block.feature_names
    )
    if row_index_used_as_feature:
        raise ValueError("row identity or session identifier entered the model feature schema")
    persistence = _persistence_coverage_from_results(persistence_by_horizon, snapshot, split)
    canonical_tasks = [
        (learner, tier, horizon)
        for learner in LEARNER_ORDER
        for tier in TIER_ORDER
        for horizon in HORIZONS_MINUTES
    ]
    formal_map: dict[tuple[str, str, int], FormalModelTaskResult] = {}
    selection_map: dict[tuple[str, str, int], SelectionRecord] = {}
    prediction_map: dict[tuple[str, str, int], PredictionBundle] = {}
    for result in frozen_task_results:
        _validate_formal_model_task_result(result)
        record = result.selection_record
        bundle = result.prediction_bundle
        key = (record.learner, record.tier, record.horizon_minutes)
        if key in formal_map:
            raise ValueError("manifest contains a duplicate formal model task")
        if (bundle.learner, bundle.tier, bundle.horizon_minutes) != key:
            raise ValueError("formal task selection and prediction identities differ")
        if result.implementation_sha256 != implementation_sha256:
            raise ValueError("formal task implementation differs from the manifest runtime")
        if result.config_sha256 != config_sha256:
            raise ValueError("formal task config differs from the manifest config")
        if result.snapshot_provenance_sha256 != snapshot_provenance_sha256:
            raise ValueError("formal task snapshot seal differs from the manifest snapshot")
        if result.split_provenance_sha256 != split.frozen_provenance_sha256:
            raise ValueError("formal task split differs from the manifest split")
        if result.feature_encoding_sha256 != feature_encoding_provenance[record.tier]:
            raise ValueError(
                "formal task feature encoding differs from the manifest encoder output"
            )
        if result.target_sha256 != target_provenance[str(record.horizon_minutes)]:
            raise ValueError("formal task target differs from the manifest target")
        formal_map[key] = result
        selection_map[key] = record
        prediction_map[key] = bundle
    if list(formal_map) != canonical_tasks:
        raise ValueError("manifest requires all 40 formal tasks in complete canonical order")

    selection_items: list[dict[str, Any]] = []
    execution_contracts = {key: formal_map[key].execution_contract for key in canonical_tasks}
    test_time_retuning = any(
        contract["test_parameter_policy"] != "fixed_selected_sha256"
        for contract in execution_contracts.values()
    )
    prediction_postprocessing = {
        str(operation)
        for contract in execution_contracts.values()
        for operation in contract["prediction_emission"]["postprocessing_operations"]
    }
    test_prediction_clipping = "clipping" in prediction_postprocessing
    test_prediction_calibration = "calibration" in prediction_postprocessing
    canonical_test_times = split.issue_times[split.test_rows]
    common_row_identity = all(
        np.array_equal(prediction_map[key].issue_times, canonical_test_times)
        for key in canonical_tasks
    )
    finite_learning_outputs = all(
        np.isfinite(prediction_map[key].y_true).all()
        and np.isfinite(prediction_map[key].predictions).all()
        and np.isfinite(selection_map[key].candidate_validation_mae).all()
        for key in canonical_tasks
    )
    parameter_hash_constant = all(
        len(np.unique(prediction_map[key].parameter_hashes)) == 1 for key in canonical_tasks
    )
    if not common_row_identity:
        raise ValueError("test-refit bundles do not share the canonical test row identity")
    if not finite_learning_outputs:
        raise ValueError("manifest model results contain non-finite learning outputs")
    if not parameter_hash_constant:
        raise ValueError("manifest model results changed parameters during testing")
    truth_by_horizon: dict[int, np.ndarray] = {}
    for key in canonical_tasks:
        record = selection_map[key]
        bundle = prediction_map[key]
        horizon = record.horizon_minutes
        target_values, target_sha256 = _snapshot_target(snapshot, split, horizon)
        if record.data_snapshot_sha256 != snapshot.data_snapshot_sha256:
            raise ValueError("selection snapshot provenance differs from the manifest snapshot")
        if record.split_provenance_sha256 != split.frozen_provenance_sha256:
            raise ValueError("selection split provenance differs from the manifest split")
        if record.target_sha256 != target_provenance[str(horizon)] or (
            target_sha256 != target_provenance[str(horizon)]
        ):
            raise ValueError("selection target provenance differs from the snapshot label column")
        if record.feature_schema_sha256 != feature_schema_provenance[record.tier]:
            raise ValueError("selection feature schema differs from the actual feature block")
        if record.feature_block_sha256 != feature_block_provenance[record.tier]:
            raise ValueError("selection feature block provenance differs from the manifest block")
        result = formal_map[key]
        if result.selection_sha256 != _selection_result_sha256(record):
            raise ValueError("formal selection seal differs from the manifest record")
        if result.prediction_sha256 != _prediction_result_sha256(bundle):
            raise ValueError("formal prediction seal differs from the manifest bundle")
        expected_counts = (
            len(split.selection_fit_rows(horizon)),
            len(split.validation_score_rows(horizon)),
        )
        if (record.selection_fit_count, record.validation_score_count) != expected_counts:
            raise ValueError("selection manifest row counts differ from the split")
        if not np.array_equal(bundle.issue_times, canonical_test_times):
            raise ValueError("test-refit bundle row identity differs from the common test rows")
        if not np.array_equal(bundle.y_true, target_values[split.test_rows]):
            raise ValueError("test-refit truth differs from the snapshot-bound horizon target")
        if horizon in truth_by_horizon:
            if not np.array_equal(bundle.y_true, truth_by_horizon[horizon]):
                raise ValueError(
                    "test-refit truth differs across learners or tiers for one horizon"
                )
        else:
            truth_by_horizon[horizon] = bundle.y_true
        hashes = {value.decode("ascii") for value in bundle.parameter_hashes}
        if hashes != {record.selected_param_sha256}:
            raise ValueError("test-refit parameter hash differs from validation selection")
        unique_days = np.unique(bundle.day_start_utc_s)
        if len(unique_days) != 14:
            raise ValueError("each model task must contain exactly 14 midnight refits")
        execution_contract = execution_contracts[key]
        if execution_contract["test_refit_count"] != len(unique_days):
            raise ValueError("formal execution refit count differs from the prediction bundle")
        candidates = []
        for position, (params, score) in enumerate(
            zip(record.candidate_params, record.candidate_validation_mae, strict=True)
        ):
            candidates.append(
                {
                    "declaration_index": position,
                    "parameters": dict(params),
                    "validation_mae_a": float(score),
                }
            )
        selection_items.append(
            {
                "learner": record.learner,
                "tier": record.tier,
                "horizon_minutes": horizon,
                "selection_fit_count": record.selection_fit_count,
                "validation_score_count": record.validation_score_count,
                "candidates": candidates,
                "selected_candidate_index": record.selected_candidate_index,
                "selected_parameters": dict(record.selected_params),
                "selected_parameter_sha256": record.selected_param_sha256,
                "test_refits": {
                    "count": len(unique_days),
                    "unique_parameter_sha256": sorted(hashes),
                    "retuned_during_test": (
                        execution_contract["test_parameter_policy"] != "fixed_selected_sha256"
                    ),
                },
                "formal_execution_sha256": result.execution_sha256,
            }
        )

    row_counts: dict[str, Any] = {}
    for horizon in HORIZONS_MINUTES:
        rolling = split.rolling_fit_rows(horizon)
        row_counts[str(horizon)] = {
            "selection_fit": len(split.selection_fit_rows(horizon)),
            "validation_score": len(split.validation_score_rows(horizon)),
            "rolling_fit_by_local_date": {
                _local_date_label(day): len(rows) for day, rows in rolling.items()
            },
        }
    manifest: dict[str, Any] = {
        "schema_version": "acn-jpl-gate1-model-selection/v1",
        "model_seed": MODEL_SEED,
        "target": {
            "name": "station_current_mean_a",
            "formula": "mean current over [issue + horizon - 15 min, issue + horizon)",
            "label_availability": "issue + horizon",
            "unit": "A",
        },
        "cohort_counts": {
            "initial_train": len(split.train_rows),
            "validation": len(split.validation_rows),
            "rolling_test": len(split.test_rows),
            "rolling_test_local_days": len(split.test_day_rows),
        },
        "horizon_row_counts": row_counts,
        "candidate_budgets": {
            learner: len(frozen_model_candidates(learner, canonical_config))
            for learner in LEARNER_ORDER
        },
        "candidate_grids": {
            learner: [
                dict(candidate) for candidate in frozen_model_candidates(learner, canonical_config)
            ]
            for learner in LEARNER_ORDER
        },
        "provenance": {
            "data_snapshot_sha256": snapshot.data_snapshot_sha256,
            "snapshot_verification_sha256": snapshot_provenance_sha256,
            "split_sha256": split.frozen_provenance_sha256,
            "config_sha256": config_sha256,
            "formal_implementation_sha256": implementation_sha256,
            "target_sha256_by_horizon": target_provenance,
            "feature_schema_sha256_by_tier": feature_schema_provenance,
            "feature_block_sha256_by_tier": feature_block_provenance,
            "feature_encoding_sha256_by_tier": feature_encoding_provenance,
        },
        "preprocessing": {
            "ridge": (
                "fit-row medians; impute all raw NaN; append fixed nullable indicators; "
                "fit-row standardization of the complete encoded matrix"
            ),
            "hgb": "preserve raw NaN; append the same fixed nullable indicators; no scaling",
            "all_nan_ridge_column": "execution failure",
            "tier_dimensions": dimensions,
            "statistics_published": False,
        },
        "persistence": {
            "semantics": {
                "last_value": "exact station bin at issue - 15 min",
                "previous_day": (
                    "target-bin start shifted back one America/Los_Angeles calendar day"
                ),
                "previous_week": (
                    "target-bin start shifted back seven America/Los_Angeles calendar days"
                ),
                "missing_policy": "unavailable without fallback or imputation",
            },
            "available_test_rows": persistence,
        },
        "test_refit_count_per_task": next(
            iter({int(contract["test_refit_count"]) for contract in execution_contracts.values()})
        ),
        "selections": selection_items,
        "audits": {
            "common_row_identity": common_row_identity,
            "per_horizon_tier_row_identity": len(truth_by_horizon) == len(HORIZONS_MINUTES),
            "test_parameter_hash_constant": parameter_hash_constant,
            "test_time_retuning": test_time_retuning,
            "test_prediction_clipping": test_prediction_clipping,
            "test_prediction_calibration": test_prediction_calibration,
            "finite_learning_outputs": finite_learning_outputs,
            "row_index_used_as_feature": row_index_used_as_feature,
            "full_test_values_published": False,
            "model_objects_published": False,
            "fitted_transform_statistics_published": False,
            "local_paths_published": False,
        },
    }
    json.dumps(manifest, allow_nan=False, sort_keys=True)
    return manifest
