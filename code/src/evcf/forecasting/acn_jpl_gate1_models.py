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
from types import MappingProxyType
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from evcf.forecasting.acn_jpl_gate1_contracts import (
    expand_hgb_grid,
    parse_time_split_boundaries,
)
from evcf.forecasting.acn_jpl_gate1_data import Gate1Snapshot
from evcf.forecasting.acn_jpl_gate1_features import FeatureBlock

MODEL_SEED = 20260901
BOOTSTRAP_SEED = 20260902
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
TIER_ORDER = ("M1", "M2", "M3", "M4")
LEARNER_ORDER = ("ridge", "hgb")
PERSISTENCE_ORDER = ("last_value", "previous_day", "previous_week")
TIMEZONE_NAME = "America/Los_Angeles"
_ZONE = ZoneInfo(TIMEZONE_NAME)
_SHA256_HEX_LENGTH = 64
_EXPECTED_RAW_DIMENSIONS = MappingProxyType({"M1": 195, "M2": 201, "M3": 311, "M4": 671})
_EXPECTED_INDICATOR_COUNTS = MappingProxyType({"M1": 0, "M2": 3, "M3": 80, "M4": 332})
_EXPECTED_INPUT_DIMENSIONS = MappingProxyType({"M1": 195, "M2": 204, "M3": 391, "M4": 1003})
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


def _require_model_config(config: Mapping[str, Any]) -> None:
    if not isinstance(config, Mapping):
        raise TypeError("config must be a frozen Gate 1 mapping")
    if config.get("target") != "station_current_mean_a":
        raise ValueError("config target differs from the frozen current target")
    if tuple(config.get("horizons_minutes", ())) != HORIZONS_MINUTES:
        raise ValueError("config horizons differ from the frozen Gate 1 horizons")
    if config.get("seeds") != {"model": MODEL_SEED, "bootstrap": BOOTSTRAP_SEED}:
        raise ValueError("config seeds differ from the frozen Gate 1 seeds")
    if config.get("bootstrap_repetitions") != 10_000:
        raise ValueError("config bootstrap repetitions differ from the frozen protocol")
    ridge = config.get("ridge")
    if not isinstance(ridge, Mapping) or tuple(ridge.get("alpha", ())) != (0.1, 1, 10, 100):
        raise ValueError("config Ridge grid differs from the frozen four candidates")
    hgb = config.get("hgb")
    if not isinstance(hgb, Mapping):
        raise TypeError("config HGB grid must be a mapping")
    expanded = expand_hgb_grid(hgb)
    if len(expanded) != 16:
        raise ValueError("config HGB grid differs from the frozen 16 candidates")
    if "hgb_grid" in config and list(config["hgb_grid"]) != expanded:
        raise ValueError("config expanded HGB grid differs from its frozen declaration")
    parsed = parse_time_split_boundaries(config.get("time_split"))
    expected_epochs = (
        1_556_780_400,
        1_557_903_600,
        1_558_162_800,
        1_559_372_400,
    )
    actual_epochs = (
        int(parsed["initial_train"]["start_local"].timestamp()),
        int(parsed["initial_train"]["end_local_exclusive"].timestamp()),
        int(parsed["validation"]["end_local_exclusive"].timestamp()),
        int(parsed["rolling_test"]["end_local_exclusive"].timestamp()),
    )
    if actual_epochs != expected_epochs:
        raise ValueError("config time boundaries differ from the frozen May 2019 protocol")


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


@dataclass(frozen=True, slots=True)
class Gate1TimeSplit:
    """Immutable row identities for the frozen PDT rolling-origin protocol."""

    issue_times: np.ndarray
    train_rows: np.ndarray
    validation_rows: np.ndarray
    test_rows: np.ndarray
    _test_day_starts: np.ndarray
    _test_day_row_values: tuple[np.ndarray, ...]
    _validation_start_utc_s: int
    _test_start_utc_s: int
    _config_json: bytes

    @classmethod
    def from_config(
        cls,
        issue_times: Any,
        config: Mapping[str, Any],
        *,
        require_frozen_counts: bool = True,
    ) -> Gate1TimeSplit:
        _require_model_config(config)
        times = np.asarray(issue_times)
        if times.dtype != np.dtype(np.int64) or times.ndim != 1:
            raise ValueError("issue-time index must be a one-dimensional int64 array")
        if not len(times) or np.any(np.diff(times) <= 0):
            raise ValueError("issue-time index must be strictly increasing and unique")
        if np.any(times % 900 != 0):
            raise ValueError("issue-time index must remain on the frozen 15-minute UTC grid")
        parsed = parse_time_split_boundaries(config["time_split"])
        train_start = int(parsed["initial_train"]["start_local"].timestamp())
        validation_start = int(parsed["validation"]["start_local"].timestamp())
        test_start = int(parsed["rolling_test"]["start_local"].timestamp())
        test_end = int(parsed["rolling_test"]["end_local_exclusive"].timestamp())
        train = np.flatnonzero((times >= train_start) & (times < validation_start)).astype(np.int64)
        validation = np.flatnonzero((times >= validation_start) & (times < test_start)).astype(
            np.int64
        )
        test = np.flatnonzero((times >= test_start) & (times < test_end)).astype(np.int64)
        covered = np.concatenate((train, validation, test))
        if len(covered) != len(times) or not np.array_equal(
            np.sort(covered), np.arange(len(times))
        ):
            raise ValueError("issue-time rows must be fully covered by the three half-open cohorts")

        day_values = np.asarray(
            [_local_midnight_epoch(int(times[row])) for row in test], dtype=np.int64
        )
        day_starts = np.unique(day_values)
        day_rows = tuple(_immutable(test[day_values == day], dtype=np.int64) for day in day_starts)
        if require_frozen_counts:
            actual_counts = (len(train), len(validation), len(test))
            if actual_counts != _EXPECTED_COHORT_COUNTS:
                raise ValueError(
                    "frozen split must contain exactly 2,853 rows as 1248/276/1329; "
                    f"found {actual_counts!r}"
                )
            if len(day_starts) != 14 or tuple(len(rows) for rows in day_rows) != (
                _EXPECTED_TEST_DAY_COUNTS
            ):
                raise ValueError("frozen test split must contain the exact 14 local-day row blocks")
            expected_days = tuple(
                int(datetime(2019, 5, day, tzinfo=_ZONE).timestamp()) for day in range(18, 32)
            )
            if tuple(int(value) for value in day_starts) != expected_days:
                raise ValueError(
                    "frozen test split must cover local dates 2019-05-18 through 2019-05-31"
                )

        config_payload = {key: value for key, value in config.items() if key != "hgb_grid"}
        result = cls(
            issue_times=_immutable(times, dtype=np.int64),
            train_rows=_immutable(train, dtype=np.int64),
            validation_rows=_immutable(validation, dtype=np.int64),
            test_rows=_immutable(test, dtype=np.int64),
            _test_day_starts=_immutable(day_starts, dtype=np.int64),
            _test_day_row_values=day_rows,
            _validation_start_utc_s=validation_start,
            _test_start_utc_s=test_start,
            _config_json=_canonical_json_bytes(config_payload),
        )
        if require_frozen_counts:
            for horizon in HORIZONS_MINUTES:
                selection_counts = (
                    len(result.selection_fit_rows(horizon)),
                    len(result.validation_score_rows(horizon)),
                )
                if selection_counts != _EXPECTED_SELECTION_COUNTS[horizon]:
                    raise ValueError(
                        f"horizon {horizon} selection row counts differ from the frozen protocol"
                    )
                rolling = result.rolling_fit_rows(horizon)
                if (
                    len(next(iter(rolling.values()))) != _EXPECTED_FIRST_ROLLING_COUNTS[horizon]
                    or len(next(reversed(rolling.values())))
                    != _EXPECTED_LAST_ROLLING_COUNTS[horizon]
                ):
                    raise ValueError(
                        f"horizon {horizon} rolling-fit row counts differ from the frozen protocol"
                    )
        return result

    @property
    def config(self) -> dict[str, Any]:
        """Return a fresh JSON-decoded copy of the path-free frozen config."""

        payload = json.loads(self._config_json.decode("ascii"))
        hgb = payload["hgb"]
        payload["hgb"] = {
            key: hgb[key]
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
            )
        }
        return payload

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
    if not isinstance(block, FeatureBlock):
        raise TypeError("preprocessing input must be a FeatureBlock")
    raw_dimension = block.values.shape[1]
    matching = [
        tier for tier, dimension in _EXPECTED_RAW_DIMENSIONS.items() if dimension == raw_dimension
    ]
    if len(matching) != 1:
        raise ValueError("feature block raw dimension is outside the frozen M1-M4 schema")
    tier = matching[0]
    if int(np.sum(block.nullable_mask)) != _EXPECTED_INDICATOR_COUNTS[tier]:
        raise ValueError(f"{tier} nullable-mask count differs from the frozen schema")
    lowered = {name.lower() for name in block.feature_names}
    if lowered & _FORBIDDEN_FEATURE_NAMES:
        raise ValueError("feature schema contains a forbidden structural index")
    if any("trajectory_ref" in name.lower() for name in block.feature_names):
        raise ValueError("feature schema contains a forbidden trajectory reference")
    return tier


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
        raw_dimension = len(names)
        matches = [
            tier
            for tier, dimension in _EXPECTED_RAW_DIMENSIONS.items()
            if dimension == raw_dimension
        ]
        if len(matches) != 1 or int(np.sum(nullable)) != _EXPECTED_INDICATOR_COUNTS[matches[0]]:
            raise ValueError("feature schema differs from the frozen M1-M4 dimensions")
        tier = matches[0]
        if self._feature_names is not None and (
            names != self._feature_names or not np.array_equal(nullable, self._nullable_mask)
        ):
            raise ValueError("transform feature schema differs from the fitted schema")
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

    _require_model_config(config)
    learner_name = _strict_learner(learner)
    candidates = _frozen_candidates_without_config(learner_name)
    if learner_name == "ridge":
        config_alphas = tuple(config["ridge"]["alpha"])
        if tuple(candidate["alpha"] for candidate in candidates) != config_alphas:
            raise ValueError("effective Ridge candidates differ from config")
    else:
        varying = expand_hgb_grid(config["hgb"])
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
        _strict_horizon(self.horizon_minutes)
        times = np.asarray(self.issue_times)
        predictions = np.asarray(self.predictions)
        available = np.asarray(self.availability)
        references = np.asarray(self.reference_times)
        if times.dtype != np.dtype(np.int64) or times.ndim != 1 or not len(times):
            raise ValueError("persistence issue index must be a nonempty int64 vector")
        if predictions.shape != times.shape or references.shape != times.shape:
            raise ValueError("persistence values and references must align with issue times")
        if available.dtype != np.dtype(np.bool_) or available.shape != times.shape:
            raise ValueError("persistence availability must be an aligned boolean vector")
        if not np.array_equal(np.isnan(predictions), ~available):
            raise ValueError("persistence unavailable rows must be exactly the NaN predictions")
        if not np.isfinite(predictions[available]).all():
            raise ValueError("available persistence predictions must be finite")
        object.__setattr__(self, "issue_times", _immutable(times, dtype=np.int64))
        object.__setattr__(self, "predictions", _immutable(predictions, dtype=np.float64))
        object.__setattr__(self, "availability", _immutable(available, dtype=np.bool_))
        object.__setattr__(self, "reference_times", _immutable(references, dtype=np.int64))


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


def _target_vector(target: Any, row_count: int) -> np.ndarray:
    values = np.asarray(target)
    if (
        values.ndim != 1
        or values.shape != (row_count,)
        or not np.issubdtype(values.dtype, np.number)
    ):
        raise ValueError("target must be one numeric vector aligned to the feature block")
    values = values.astype(np.float64, copy=False)
    if not np.isfinite(values).all():
        raise ValueError("target must be finite for the complete common row universe")
    return values


def _require_block_split_identity(feature_block: FeatureBlock, split: Gate1TimeSplit) -> str:
    tier = _schema_tier(feature_block)
    if not np.array_equal(feature_block.issue_times, split.issue_times):
        raise ValueError("feature block and time split must share the exact ordered row index")
    return tier


def _default_preprocessor_factory(learner: str) -> RidgePreprocessor | HGBPreprocessor:
    return RidgePreprocessor() if learner == "ridge" else HGBPreprocessor()


def select_model_params(
    *,
    learner: str,
    tier: str,
    horizon_minutes: int,
    feature_block: FeatureBlock,
    target: Any,
    split: Gate1TimeSplit,
    config: Mapping[str, Any],
    estimator_factory: EstimatorFactory = make_frozen_estimator,
    preprocessor_factory: PreprocessorFactory = _default_preprocessor_factory,
) -> SelectionRecord:
    """Evaluate every frozen candidate on the embargo-safe validation rows."""

    learner_name = _strict_learner(learner)
    tier_name = _strict_tier(tier)
    horizon = _strict_horizon(horizon_minutes)
    actual_tier = _require_block_split_identity(feature_block, split)
    if actual_tier != tier_name:
        raise ValueError("declared tier differs from the feature-block schema")
    values = _target_vector(target, len(split.issue_times))
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
    candidates = frozen_model_candidates(learner_name, config)
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
    )


def rolling_origin_predict(
    *,
    feature_block: FeatureBlock,
    target: Any,
    split: Gate1TimeSplit,
    selection: SelectionRecord,
    estimator_factory: EstimatorFactory = make_frozen_estimator,
    preprocessor_factory: PreprocessorFactory = _default_preprocessor_factory,
) -> PredictionBundle:
    """Refit fixed selected parameters once per local test day and predict that day."""

    if not isinstance(selection, SelectionRecord):
        raise TypeError("rolling prediction requires an immutable SelectionRecord")
    tier = _require_block_split_identity(feature_block, split)
    if tier != selection.tier:
        raise ValueError("selection tier differs from the rolling feature block")
    target_values = _target_vector(target, len(split.issue_times))
    horizon = selection.horizon_minutes
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


def run_model_task(
    *,
    learner: str,
    tier: str,
    horizon_minutes: int,
    feature_block: FeatureBlock,
    target: Any,
    split: Gate1TimeSplit,
    config: Mapping[str, Any],
    estimator_factory: EstimatorFactory = make_frozen_estimator,
    preprocessor_factory: PreprocessorFactory = _default_preprocessor_factory,
) -> tuple[SelectionRecord, PredictionBundle]:
    """Run one canonical outer-parallel task; all work inside remains serial."""

    selection = select_model_params(
        learner=learner,
        tier=tier,
        horizon_minutes=horizon_minutes,
        feature_block=feature_block,
        target=target,
        split=split,
        config=config,
        estimator_factory=estimator_factory,
        preprocessor_factory=preprocessor_factory,
    )
    bundle = rolling_origin_predict(
        feature_block=feature_block,
        target=target,
        split=split,
        selection=selection,
        estimator_factory=estimator_factory,
        preprocessor_factory=preprocessor_factory,
    )
    return selection, bundle


def _validate_feature_dimensions(
    value: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    if tuple(value) != TIER_ORDER:
        raise ValueError("feature dimensions must use the complete canonical M1-M4 order")
    result: dict[str, dict[str, int]] = {}
    for tier in TIER_ORDER:
        item = value[tier]
        if set(item) != {"raw", "indicators", "input"}:
            raise ValueError(f"{tier} feature dimensions must contain raw/indicators/input only")
        expected = {
            "raw": _EXPECTED_RAW_DIMENSIONS[tier],
            "indicators": _EXPECTED_INDICATOR_COUNTS[tier],
            "input": _EXPECTED_INPUT_DIMENSIONS[tier],
        }
        actual = {
            "raw": _strict_integer(item["raw"], f"{tier} raw", positive=True),
            "indicators": _strict_integer(item["indicators"], f"{tier} indicators"),
            "input": _strict_integer(item["input"], f"{tier} input", positive=True),
        }
        if actual["indicators"] < 0:
            raise ValueError(f"{tier} indicators must be nonnegative")
        if actual != expected:
            raise ValueError(f"{tier} feature dimensions differ from the frozen schema")
        result[tier] = actual
    return result


def _validate_persistence_coverage(
    value: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    if tuple(value) != PERSISTENCE_ORDER:
        raise ValueError("persistence coverage must use the complete canonical baseline order")
    result: dict[str, dict[str, int]] = {}
    for baseline in PERSISTENCE_ORDER:
        per_horizon = value[baseline]
        if set(per_horizon) != {str(horizon) for horizon in HORIZONS_MINUTES}:
            raise ValueError("persistence coverage must contain all five horizon keys")
        expected = _EXPECTED_PERSISTENCE_COVERAGE[baseline]
        result[baseline] = {}
        for horizon in HORIZONS_MINUTES:
            count = _strict_integer(
                per_horizon[str(horizon)], f"{baseline} horizon {horizon} coverage"
            )
            if count != expected:
                raise ValueError(f"{baseline} horizon {horizon} availability must equal {expected}")
            result[baseline][str(horizon)] = count
    return result


def build_model_selection_manifest(
    *,
    config: Mapping[str, Any],
    split: Gate1TimeSplit,
    selections: Sequence[SelectionRecord],
    predictions: Sequence[PredictionBundle],
    feature_dimensions: Mapping[str, Mapping[str, Any]],
    persistence_coverage: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the complete aggregate-only model-selection manifest."""

    _require_model_config(config)
    if not isinstance(split, Gate1TimeSplit):
        raise TypeError("manifest split must be a Gate1TimeSplit")
    dimensions = _validate_feature_dimensions(feature_dimensions)
    persistence = _validate_persistence_coverage(persistence_coverage)
    canonical_tasks = [
        (learner, tier, horizon)
        for learner in LEARNER_ORDER
        for tier in TIER_ORDER
        for horizon in HORIZONS_MINUTES
    ]
    selection_map: dict[tuple[str, str, int], SelectionRecord] = {}
    for record in selections:
        if not isinstance(record, SelectionRecord):
            raise TypeError("manifest selections must be SelectionRecord objects")
        key = (record.learner, record.tier, record.horizon_minutes)
        if key in selection_map:
            raise ValueError("manifest contains a duplicate selection task")
        selection_map[key] = record
    prediction_map: dict[tuple[str, str, int], PredictionBundle] = {}
    for bundle in predictions:
        if not isinstance(bundle, PredictionBundle):
            raise TypeError("manifest test refits must be PredictionBundle objects")
        key = (bundle.learner, bundle.tier, bundle.horizon_minutes)
        if key in prediction_map:
            raise ValueError("manifest contains a duplicate test-refit task")
        prediction_map[key] = bundle
    if list(selection_map) != canonical_tasks or list(prediction_map) != canonical_tasks:
        raise ValueError("manifest requires all 40 tasks in complete canonical order")

    selection_items: list[dict[str, Any]] = []
    canonical_test_times = split.issue_times[split.test_rows]
    truth_by_horizon: dict[int, np.ndarray] = {}
    for key in canonical_tasks:
        record = selection_map[key]
        bundle = prediction_map[key]
        horizon = record.horizon_minutes
        expected_counts = (
            len(split.selection_fit_rows(horizon)),
            len(split.validation_score_rows(horizon)),
        )
        if (record.selection_fit_count, record.validation_score_count) != expected_counts:
            raise ValueError("selection manifest row counts differ from the split")
        if not np.array_equal(bundle.issue_times, canonical_test_times):
            raise ValueError("test-refit bundle row identity differs from the common test rows")
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
                    "retuned_during_test": False,
                },
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
        "candidate_budgets": {"ridge": 4, "hgb": 16},
        "candidate_grids": {
            learner: [dict(candidate) for candidate in frozen_model_candidates(learner, config)]
            for learner in LEARNER_ORDER
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
        "test_refit_count_per_task": 14,
        "selections": selection_items,
        "audits": {
            "common_row_identity": "PASS",
            "per_horizon_tier_row_identity": "PASS",
            "test_parameter_hash_constant": "PASS",
            "test_time_retuning": False,
            "test_prediction_clipping": False,
            "test_prediction_calibration": False,
            "finite_learning_outputs": "PASS",
            "row_index_used_as_feature": False,
            "full_test_values_published": False,
            "model_objects_published": False,
            "fitted_transform_statistics_published": False,
            "local_paths_published": False,
        },
    }
    json.dumps(manifest, allow_nan=False, sort_keys=True)
    return manifest
