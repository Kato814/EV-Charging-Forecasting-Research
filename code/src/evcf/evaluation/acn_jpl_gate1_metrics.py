"""Deterministic metrics, paired bootstrap, and Gate rules for JPL Gate 1.

Full issue-time predictions remain local.  The public conversion methods in this
module expose only model-level or local-day aggregate evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from numbers import Integral
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from evcf.forecasting.acn_jpl_gate1_models import PersistencePrediction, PredictionBundle

TIMEZONE_NAME = "America/Los_Angeles"
NOMINAL_208V_KW_PER_AMP = 0.208
BOOTSTRAP_SEED = 20260902
BOOTSTRAP_REPETITIONS = 10_000
BOOTSTRAP_BLOCK_COUNT = 14
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
NEAR_HORIZONS_MINUTES = (15, 30, 60)
LEARNER_ORDER = ("ridge", "hgb")
TIER_ORDER = ("M1", "M2", "M3", "M4")
PERSISTENCE_ORDER = ("last_value", "previous_day", "previous_week")
ADJACENT_TIER_PAIRS = (("M1", "M2"), ("M2", "M3"), ("M3", "M4"))
SCIENTIFIC_CLASSIFICATIONS = (
    "PASS_ACTIVE_SESSION",
    "PASS_SIMPLE_STATE_ONLY",
    "PASS_ACTIVE_SESSION_DROP_M4",
    "FAIL_DIRECTION",
)
EXECUTION_FAIL = "EXECUTION_FAIL"

_ZONE = ZoneInfo(TIMEZONE_NAME)
_EXPECTED_TEST_DAY_COUNTS = (96,) * 13 + (81,)
_EXPECTED_PERSISTENCE_COVERAGE = MappingProxyType(
    {"last_value": 1_329, "previous_day": 1_329, "previous_week": 1_326}
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FILE_URI = re.compile(r"(?i)\bfile:/+")
_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)[a-z]:(?:\\|/(?!/))")
_UNC_ABSOLUTE_PATH = re.compile(r"\\\\[^\\/\s]+[\\/][^\\/\s]+")
_POSIX_ABSOLUTE_PATH = re.compile(r"(?i)(?<![a-z0-9/])/(?!/)(?:[^/\s]+/)*[^/\s]+")
_PRIVATE_ID_TOKEN = re.compile(r"(?i)(?:^|[^a-z0-9])_id(?:$|[^a-z0-9])")
_PUBLIC_FORBIDDEN_COMPACT_TOKENS = (
    "sessionid",
    "userid",
    "anonymoussession",
    "trajectoryref",
    "referencetimes",
    "issuetimes",
    "issuetimeutcs",
    "ytrue",
    "ypred",
    "predictions",
    "parameterhashes",
    "blockindexmatrix",
    "replicatemeans",
)
_GATE_EVIDENCE_SEAL = object()
_GATE_RESULT_SEAL = object()


class ExecutionFailureCode(str, Enum):
    """Fixed, identifier-free execution failures safe for public manifests."""

    DATA_CONTRACT = "DATA_CONTRACT"
    EVALUATION_CONTRACT = "EVALUATION_CONTRACT"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    METRIC_CONTRACT = "METRIC_CONTRACT"
    BOOTSTRAP_CONTRACT = "BOOTSTRAP_CONTRACT"
    REPRODUCIBILITY = "REPRODUCIBILITY"
    PRIVACY = "PRIVACY"
    INCOMPLETE_GATE_EVIDENCE = "INCOMPLETE_GATE_EVIDENCE"
    INVALID_GATE_EVIDENCE = "INVALID_GATE_EVIDENCE"
    NONFINITE_GATE_IMPROVEMENT = "NONFINITE_GATE_IMPROVEMENT"


def _immutable(array: Any, *, dtype: np.dtype[Any] | str | None = None) -> np.ndarray:
    contiguous = np.ascontiguousarray(array, dtype=dtype)
    return np.frombuffer(contiguous.tobytes(order="C"), dtype=contiguous.dtype).reshape(
        contiguous.shape
    )


def _canonical_test_index() -> tuple[np.ndarray, np.ndarray]:
    issue_times: list[int] = []
    day_starts: list[int] = []
    first_day = datetime(2019, 5, 18, tzinfo=_ZONE)
    for offset, row_count in enumerate(_EXPECTED_TEST_DAY_COUNTS):
        day = first_day + timedelta(days=offset)
        day_epoch = int(day.timestamp())
        for position in range(row_count):
            issue_times.append(day_epoch + position * 900)
            day_starts.append(day_epoch)
    return (
        _immutable(issue_times, dtype=np.int64),
        _immutable(day_starts, dtype=np.int64),
    )


_CANONICAL_TEST_ISSUE_TIMES, _CANONICAL_TEST_DAY_STARTS = _canonical_test_index()


def _array_sha256(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        value = np.ascontiguousarray(array)
        digest.update(value.dtype.str.encode("ascii"))
        digest.update(np.asarray(value.shape, dtype="<i8").tobytes(order="C"))
        digest.update(value.tobytes(order="C"))
    return digest.hexdigest()


_CANONICAL_TEST_ROW_SHA256 = _array_sha256(
    _CANONICAL_TEST_ISSUE_TIMES,
    _CANONICAL_TEST_DAY_STARTS,
)


def _strict_horizon(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError("horizon_minutes must be an integer")
    horizon = int(value)
    if horizon not in HORIZONS_MINUTES:
        raise ValueError(f"horizon_minutes must be one of {HORIZONS_MINUTES!r}")
    return horizon


def _local_midnight_epoch(epoch_seconds: int) -> int:
    local = datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(_ZONE)
    return int(datetime.combine(local.date(), time.min, tzinfo=_ZONE).timestamp())


def _local_date_label(epoch_seconds: int) -> str:
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).astimezone(_ZONE).date().isoformat()


def _model_metadata(series: EvaluationSeries) -> dict[str, Any]:
    return {
        "model_kind": series.model_kind,
        "learner": series.learner,
        "tier": series.tier,
        "baseline": series.baseline,
        "horizon_minutes": series.horizon_minutes,
    }


@dataclass(frozen=True, slots=True)
class EvaluationSeries:
    """A local-only, immutable forecast series normalized for evaluation."""

    model_kind: str
    learner: str | None
    tier: str | None
    baseline: str | None
    horizon_minutes: int
    issue_times: np.ndarray
    day_start_utc_s: np.ndarray
    y_true: np.ndarray
    predictions: np.ndarray
    availability: np.ndarray

    def __post_init__(self) -> None:
        if self.model_kind not in ("learned", "persistence"):
            raise ValueError("model_kind must be learned or persistence")
        horizon = _strict_horizon(self.horizon_minutes)
        times = np.asarray(self.issue_times)
        days = np.asarray(self.day_start_utc_s)
        truth = np.asarray(self.y_true)
        predictions = np.asarray(self.predictions)
        availability = np.asarray(self.availability)
        if (
            times.dtype != np.dtype(np.int64)
            or times.ndim != 1
            or not len(times)
            or np.any(np.diff(times) <= 0)
        ):
            raise ValueError("evaluation issue index must be nonempty, increasing, unique int64")
        if np.any(times % 900 != 0):
            raise ValueError("evaluation issue index must remain on the 15-minute grid")
        row_count = len(times)
        if days.dtype != np.dtype(np.int64) or days.shape != (row_count,):
            raise ValueError("evaluation day starts must be an aligned int64 vector")
        expected_days = np.asarray(
            [_local_midnight_epoch(int(value)) for value in times], dtype=np.int64
        )
        if not np.array_equal(days, expected_days):
            raise ValueError("evaluation day starts must equal local issue-day midnights")
        if truth.shape != (row_count,) or not np.issubdtype(truth.dtype, np.number):
            raise ValueError("evaluation truth must be one aligned numeric vector")
        if predictions.shape != (row_count,) or not np.issubdtype(predictions.dtype, np.number):
            raise ValueError("evaluation predictions must be one aligned numeric vector")
        if availability.dtype != np.dtype(np.bool_) or availability.shape != (row_count,):
            raise ValueError("evaluation availability must be one aligned boolean vector")
        truth = truth.astype(np.float64, copy=False)
        predictions = predictions.astype(np.float64, copy=False)
        if not np.isfinite(truth).all():
            raise ValueError("evaluation truth must be finite for every common test row")
        if not np.array_equal(np.isnan(predictions), ~availability):
            raise ValueError("unavailable rows must be exactly the NaN predictions")
        if not np.isfinite(predictions[availability]).all():
            raise ValueError("available predictions must be finite")

        if self.model_kind == "learned":
            if self.learner not in LEARNER_ORDER or self.tier not in TIER_ORDER:
                raise ValueError("learned series requires a frozen learner and tier")
            if self.baseline is not None:
                raise ValueError("learned series cannot declare a persistence baseline")
            if not bool(np.all(availability)):
                raise ValueError("learned Gate predictions must cover every common test row")
        else:
            if self.learner is not None or self.tier is not None:
                raise ValueError("persistence series cannot declare a learner or tier")
            if self.baseline not in PERSISTENCE_ORDER:
                raise ValueError("persistence series requires a frozen baseline name")

        object.__setattr__(self, "horizon_minutes", horizon)
        object.__setattr__(self, "issue_times", _immutable(times, dtype=np.int64))
        object.__setattr__(self, "day_start_utc_s", _immutable(days, dtype=np.int64))
        object.__setattr__(self, "y_true", _immutable(truth, dtype=np.float64))
        object.__setattr__(self, "predictions", _immutable(predictions, dtype=np.float64))
        object.__setattr__(self, "availability", _immutable(availability, dtype=np.bool_))

    @classmethod
    def create(
        cls,
        *,
        model_kind: str,
        learner: str | None,
        tier: str | None,
        baseline: str | None,
        horizon_minutes: int,
        issue_times: Any,
        day_start_utc_s: Any,
        y_true: Any,
        predictions: Any,
        availability: Any,
    ) -> EvaluationSeries:
        return cls(
            model_kind=model_kind,
            learner=learner,
            tier=tier,
            baseline=baseline,
            horizon_minutes=horizon_minutes,
            issue_times=np.asarray(issue_times),
            day_start_utc_s=np.asarray(day_start_utc_s),
            y_true=np.asarray(y_true),
            predictions=np.asarray(predictions),
            availability=np.asarray(availability),
        )

    @classmethod
    def from_prediction_bundle(cls, bundle: PredictionBundle) -> EvaluationSeries:
        if not isinstance(bundle, PredictionBundle):
            raise TypeError("learned evaluation input must be a PredictionBundle")
        return cls.create(
            model_kind="learned",
            learner=bundle.learner,
            tier=bundle.tier,
            baseline=None,
            horizon_minutes=bundle.horizon_minutes,
            issue_times=bundle.issue_times,
            day_start_utc_s=bundle.day_start_utc_s,
            y_true=bundle.y_true,
            predictions=bundle.predictions,
            availability=np.ones(len(bundle.issue_times), dtype=np.bool_),
        )

    @classmethod
    def from_persistence_prediction(
        cls,
        prediction: PersistencePrediction,
        *,
        y_true: Any,
        day_start_utc_s: Any,
    ) -> EvaluationSeries:
        if not isinstance(prediction, PersistencePrediction):
            raise TypeError("persistence evaluation input must be a PersistencePrediction")
        return cls.create(
            model_kind="persistence",
            learner=None,
            tier=None,
            baseline=prediction.name,
            horizon_minutes=prediction.horizon_minutes,
            issue_times=prediction.issue_times,
            day_start_utc_s=day_start_utc_s,
            y_true=y_true,
            predictions=prediction.predictions,
            availability=prediction.availability,
        )


@dataclass(frozen=True, slots=True)
class ErrorMetrics:
    """Aggregate paired errors for one explicitly declared row scope."""

    n_total: int
    n_available: int
    coverage_ratio: float | None
    mae_a: float | None
    rmse_a: float | None
    wape_ratio: float | None
    wape_status: str
    nominal_208v_reconstructed_mae_kw: float | None
    nominal_208v_reconstructed_rmse_kw: float | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "n_total": self.n_total,
            "n_available": self.n_available,
            "coverage_ratio": self.coverage_ratio,
            "mae_a": self.mae_a,
            "rmse_a": self.rmse_a,
            "wape_ratio": self.wape_ratio,
            "wape_status": self.wape_status,
            "nominal_208v_reconstructed_mae_kw": (self.nominal_208v_reconstructed_mae_kw),
            "nominal_208v_reconstructed_rmse_kw": (self.nominal_208v_reconstructed_rmse_kw),
        }


def compute_error_metrics(
    y_true: Any,
    predictions: Any,
    *,
    availability: Any | None = None,
) -> ErrorMetrics:
    """Compute finite paired metrics without implicit missing-value handling."""

    truth = np.asarray(y_true)
    predicted = np.asarray(predictions)
    if truth.ndim != 1 or predicted.shape != truth.shape:
        raise ValueError("truth and predictions must be aligned one-dimensional vectors")
    if not np.issubdtype(truth.dtype, np.number) or not np.issubdtype(predicted.dtype, np.number):
        raise TypeError("truth and predictions must be numeric")
    truth = truth.astype(np.float64, copy=False)
    predicted = predicted.astype(np.float64, copy=False)
    if not np.isfinite(truth).all():
        raise ValueError("truth must be finite")
    if availability is None:
        available = np.ones(len(truth), dtype=np.bool_)
    else:
        available = np.asarray(availability)
        if available.dtype != np.dtype(np.bool_) or available.shape != truth.shape:
            raise ValueError("availability must be an aligned boolean vector")
    if not np.array_equal(np.isnan(predicted), ~available):
        raise ValueError("unavailable rows must be exactly the NaN predictions")
    if not np.isfinite(predicted[available]).all():
        raise ValueError("available predictions must be finite")

    n_total = len(truth)
    n_available = int(np.sum(available))
    coverage = float(n_available / n_total) if n_total else None
    if not n_available:
        return ErrorMetrics(
            n_total=n_total,
            n_available=0,
            coverage_ratio=coverage,
            mae_a=None,
            rmse_a=None,
            wape_ratio=None,
            wape_status="unavailable_no_rows",
            nominal_208v_reconstructed_mae_kw=None,
            nominal_208v_reconstructed_rmse_kw=None,
        )

    paired_truth = truth[available]
    error = predicted[available] - paired_truth
    absolute = np.abs(error)
    mae = float(np.mean(absolute))
    rmse = float(np.sqrt(np.mean(np.square(error))))
    denominator = float(np.sum(np.abs(paired_truth)))
    if denominator == 0.0:
        wape = None
        wape_status = "undefined_zero_actual_absolute_sum"
    else:
        wape = float(np.sum(absolute) / denominator)
        wape_status = "defined"
    return ErrorMetrics(
        n_total=n_total,
        n_available=n_available,
        coverage_ratio=coverage,
        mae_a=mae,
        rmse_a=rmse,
        wape_ratio=wape,
        wape_status=wape_status,
        nominal_208v_reconstructed_mae_kw=NOMINAL_208V_KW_PER_AMP * mae,
        nominal_208v_reconstructed_rmse_kw=NOMINAL_208V_KW_PER_AMP * rmse,
    )


@dataclass(frozen=True, slots=True)
class DailyMetrics:
    local_date: str
    metrics: ErrorMetrics

    def to_public_dict(self) -> dict[str, Any]:
        return {"local_date": self.local_date, **self.metrics.to_public_dict()}


@dataclass(frozen=True, slots=True)
class ScopedMetrics:
    model_kind: str
    learner: str | None
    tier: str | None
    baseline: str | None
    horizon_minutes: int
    overall: ErrorMetrics
    daily: tuple[DailyMetrics, ...]
    weekday: ErrorMetrics
    weekend: ErrorMetrics

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "model_kind": self.model_kind,
            "learner": self.learner,
            "tier": self.tier,
            "baseline": self.baseline,
            "horizon_minutes": self.horizon_minutes,
            "overall": self.overall.to_public_dict(),
            "daily": [value.to_public_dict() for value in self.daily],
            "weekday": self.weekday.to_public_dict(),
            "weekend": self.weekend.to_public_dict(),
            "grouping": "America/Los_Angeles issue-date; weekday/weekend are micro-averages",
        }


def evaluate_scopes(series: EvaluationSeries) -> ScopedMetrics:
    """Evaluate overall, each issue day, weekday, and weekend row scopes."""

    if not isinstance(series, EvaluationSeries):
        raise TypeError("scoped metrics require an EvaluationSeries")
    days = np.unique(series.day_start_utc_s)
    daily = tuple(
        DailyMetrics(
            local_date=_local_date_label(int(day)),
            metrics=compute_error_metrics(
                series.y_true[series.day_start_utc_s == day],
                series.predictions[series.day_start_utc_s == day],
                availability=series.availability[series.day_start_utc_s == day],
            ),
        )
        for day in days
    )
    weekday_mask = np.asarray(
        [
            datetime.fromtimestamp(int(day), timezone.utc).astimezone(_ZONE).weekday() < 5
            for day in series.day_start_utc_s
        ],
        dtype=np.bool_,
    )

    def scoped(mask: np.ndarray) -> ErrorMetrics:
        return compute_error_metrics(
            series.y_true[mask],
            series.predictions[mask],
            availability=series.availability[mask],
        )

    return ScopedMetrics(
        **_model_metadata(series),
        overall=compute_error_metrics(
            series.y_true,
            series.predictions,
            availability=series.availability,
        ),
        daily=daily,
        weekday=scoped(weekday_mask),
        weekend=scoped(~weekday_mask),
    )


@dataclass(frozen=True, slots=True)
class DailyPeakMetric:
    local_date: str
    n_total: int
    n_available: int
    status: str
    peak_amplitude_error_a: float | None
    peak_time_error_minutes: float | None
    actual_peak_target_time_utc_s: int | None
    predicted_peak_target_time_utc_s: int | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "local_date": self.local_date,
            "n_total": self.n_total,
            "n_available": self.n_available,
            "status": self.status,
            "peak_amplitude_error_a": self.peak_amplitude_error_a,
            "peak_time_error_minutes": self.peak_time_error_minutes,
        }


@dataclass(frozen=True, slots=True)
class PeakRampMetrics:
    model_kind: str
    learner: str | None
    tier: str | None
    baseline: str | None
    horizon_minutes: int
    daily_peak: tuple[DailyPeakMetric, ...]
    complete_peak_days: int
    mean_daily_peak_amplitude_error_a: float | None
    mean_daily_peak_time_error_minutes: float | None
    ramp_pair_count: int
    ramp_mae_a: float | None
    max_ramp_error_a: float | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "model_kind": self.model_kind,
            "learner": self.learner,
            "tier": self.tier,
            "baseline": self.baseline,
            "horizon_minutes": self.horizon_minutes,
            "daily_peak": [value.to_public_dict() for value in self.daily_peak],
            "complete_peak_days": self.complete_peak_days,
            "mean_daily_peak_amplitude_error_a": self.mean_daily_peak_amplitude_error_a,
            "mean_daily_peak_time_error_minutes": self.mean_daily_peak_time_error_minutes,
            "ramp_pair_count": self.ramp_pair_count,
            "ramp_mae_a": self.ramp_mae_a,
            "max_ramp_error_a": self.max_ramp_error_a,
            "peak_scope": "formal common issue rows grouped by local issue-date",
            "ramp_scope": "same local issue-date, exact 15-minute adjacency, both rows available",
        }


def compute_peak_ramp_metrics(series: EvaluationSeries) -> PeakRampMetrics:
    """Compute fail-safe formal-day peak metrics and eligible adjacent ramps."""

    if not isinstance(series, EvaluationSeries):
        raise TypeError("peak/ramp metrics require an EvaluationSeries")
    daily: list[DailyPeakMetric] = []
    for day in np.unique(series.day_start_utc_s):
        rows = np.flatnonzero(series.day_start_utc_s == day)
        available = series.availability[rows]
        local_date = _local_date_label(int(day))
        if not bool(np.all(available)):
            daily.append(
                DailyPeakMetric(
                    local_date=local_date,
                    n_total=len(rows),
                    n_available=int(np.sum(available)),
                    status="incomplete_prediction_day",
                    peak_amplitude_error_a=None,
                    peak_time_error_minutes=None,
                    actual_peak_target_time_utc_s=None,
                    predicted_peak_target_time_utc_s=None,
                )
            )
            continue
        actual = series.y_true[rows]
        predicted = series.predictions[rows]
        actual_position = int(np.argmax(actual))
        predicted_position = int(np.argmax(predicted))
        target_times = series.issue_times[rows] + series.horizon_minutes * 60 - 15 * 60
        actual_target = int(target_times[actual_position])
        predicted_target = int(target_times[predicted_position])
        daily.append(
            DailyPeakMetric(
                local_date=local_date,
                n_total=len(rows),
                n_available=len(rows),
                status="defined",
                peak_amplitude_error_a=float(abs(float(np.max(predicted)) - float(np.max(actual)))),
                peak_time_error_minutes=abs(predicted_target - actual_target) / 60.0,
                actual_peak_target_time_utc_s=actual_target,
                predicted_peak_target_time_utc_s=predicted_target,
            )
        )

    peak_amplitude = [
        value.peak_amplitude_error_a for value in daily if value.peak_amplitude_error_a is not None
    ]
    peak_time = [
        value.peak_time_error_minutes
        for value in daily
        if value.peak_time_error_minutes is not None
    ]
    eligible = (
        (np.diff(series.issue_times) == 900)
        & (series.day_start_utc_s[1:] == series.day_start_utc_s[:-1])
        & series.availability[1:]
        & series.availability[:-1]
    )
    positions = np.flatnonzero(eligible) + 1
    if len(positions):
        actual_ramp = series.y_true[positions] - series.y_true[positions - 1]
        predicted_ramp = series.predictions[positions] - series.predictions[positions - 1]
        ramp_errors = np.abs(predicted_ramp - actual_ramp)
        ramp_mae = float(np.mean(ramp_errors))
        max_ramp = float(np.max(ramp_errors))
    else:
        ramp_mae = None
        max_ramp = None
    return PeakRampMetrics(
        **_model_metadata(series),
        daily_peak=tuple(daily),
        complete_peak_days=len(peak_amplitude),
        mean_daily_peak_amplitude_error_a=(
            float(np.mean(peak_amplitude)) if peak_amplitude else None
        ),
        mean_daily_peak_time_error_minutes=(float(np.mean(peak_time)) if peak_time else None),
        ramp_pair_count=len(positions),
        ramp_mae_a=ramp_mae,
        max_ramp_error_a=max_ramp,
    )


@dataclass(frozen=True, slots=True)
class DailyPairedError:
    local_date: str
    n_rows: int
    parent_mae_a: float
    child_mae_a: float
    absolute_error_delta_a: float

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "local_date": self.local_date,
            "n_rows": self.n_rows,
            "parent_mae_a": self.parent_mae_a,
            "child_mae_a": self.child_mae_a,
            "absolute_error_delta_a": self.absolute_error_delta_a,
        }


@dataclass(frozen=True, slots=True)
class TierComparison:
    """Local paired error evidence for one adjacent tier comparison."""

    learner: str
    parent_tier: str
    child_tier: str
    horizon_minutes: int
    issue_times: np.ndarray
    day_start_utc_s: np.ndarray
    absolute_error_delta_a: np.ndarray
    parent_mae_a: float
    child_mae_a: float
    mean_absolute_error_delta_a: float
    relative_improvement_percent: float
    daily: tuple[DailyPairedError, ...]

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.learner, self.parent_tier, self.child_tier, self.horizon_minutes)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "learner": self.learner,
            "parent_tier": self.parent_tier,
            "child_tier": self.child_tier,
            "horizon_minutes": self.horizon_minutes,
            "n_rows": len(self.issue_times),
            "parent_mae_a": self.parent_mae_a,
            "child_mae_a": self.child_mae_a,
            "mean_absolute_error_delta_a": self.mean_absolute_error_delta_a,
            "relative_improvement_percent": self.relative_improvement_percent,
            "delta_direction": "positive means child tier has lower absolute error",
        }

    def daily_public_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "learner": self.learner,
                "parent_tier": self.parent_tier,
                "child_tier": self.child_tier,
                "horizon_minutes": self.horizon_minutes,
                **value.to_public_dict(),
            }
            for value in self.daily
        ]


def compare_adjacent_tiers(
    parent: EvaluationSeries,
    child: EvaluationSeries,
) -> TierComparison:
    """Build exact paired absolute-error evidence; positive delta favors child."""

    if not isinstance(parent, EvaluationSeries) or not isinstance(child, EvaluationSeries):
        raise TypeError("tier comparison inputs must be EvaluationSeries objects")
    if parent.model_kind != "learned" or child.model_kind != "learned":
        raise ValueError("Gate tier comparisons require complete learned predictions")
    if parent.learner != child.learner:
        raise ValueError("tier comparison learners differ")
    if (parent.tier, child.tier) not in ADJACENT_TIER_PAIRS:
        raise ValueError("tier comparison must use one frozen adjacent parent/child pair")
    if parent.horizon_minutes != child.horizon_minutes:
        raise ValueError("tier comparison horizons differ")
    if not np.array_equal(parent.issue_times, child.issue_times):
        raise ValueError("tier comparison issue row identity differs")
    if not np.array_equal(parent.day_start_utc_s, child.day_start_utc_s):
        raise ValueError("tier comparison local-day identity differs")
    if not np.array_equal(parent.y_true, child.y_true):
        raise ValueError("tier comparison truth differs")
    if not bool(np.all(parent.availability)) or not bool(np.all(child.availability)):
        raise ValueError("Gate tier comparison requires complete paired predictions")

    parent_absolute = np.abs(parent.predictions - parent.y_true)
    child_absolute = np.abs(child.predictions - child.y_true)
    delta = parent_absolute - child_absolute
    parent_mae = float(np.mean(parent_absolute))
    child_mae = float(np.mean(child_absolute))
    if not math.isfinite(parent_mae) or parent_mae <= 0:
        raise ValueError("tier comparison parent MAE must be finite and positive")
    daily: list[DailyPairedError] = []
    for day in np.unique(parent.day_start_utc_s):
        mask = parent.day_start_utc_s == day
        parent_day = float(np.mean(parent_absolute[mask]))
        child_day = float(np.mean(child_absolute[mask]))
        daily.append(
            DailyPairedError(
                local_date=_local_date_label(int(day)),
                n_rows=int(np.sum(mask)),
                parent_mae_a=parent_day,
                child_mae_a=child_day,
                absolute_error_delta_a=parent_day - child_day,
            )
        )
    mean_delta = float(np.mean(delta))
    return TierComparison(
        learner=str(parent.learner),
        parent_tier=str(parent.tier),
        child_tier=str(child.tier),
        horizon_minutes=parent.horizon_minutes,
        issue_times=_immutable(parent.issue_times, dtype=np.int64),
        day_start_utc_s=_immutable(parent.day_start_utc_s, dtype=np.int64),
        absolute_error_delta_a=_immutable(delta, dtype=np.float64),
        parent_mae_a=parent_mae,
        child_mae_a=child_mae,
        mean_absolute_error_delta_a=mean_delta,
        relative_improvement_percent=100.0 * mean_delta / parent_mae,
        daily=tuple(daily),
    )


@dataclass(frozen=True, slots=True)
class BootstrapPlan:
    """The one frozen 14-day PCG64 resampling matrix shared by all comparisons."""

    seed: int
    repetitions: int
    day_start_utc_s: np.ndarray
    block_index_matrix: np.ndarray

    def __post_init__(self) -> None:
        if self.seed != BOOTSTRAP_SEED:
            raise ValueError(f"bootstrap seed must be {BOOTSTRAP_SEED}")
        if self.repetitions != BOOTSTRAP_REPETITIONS:
            raise ValueError("bootstrap repetitions must be exactly 10,000")
        days = np.asarray(self.day_start_utc_s)
        matrix = np.asarray(self.block_index_matrix)
        if (
            days.dtype != np.dtype(np.int64)
            or days.shape != (BOOTSTRAP_BLOCK_COUNT,)
            or np.any(np.diff(days) <= 0)
        ):
            raise ValueError("bootstrap plan requires exactly 14 ordered unique local days")
        expected_dates = tuple(f"2019-05-{day:02d}" for day in range(18, 32))
        if tuple(_local_date_label(int(day)) for day in days) != expected_dates:
            raise ValueError("bootstrap blocks must be local dates 2019-05-18 through 2019-05-31")
        if matrix.dtype != np.dtype(np.int64) or matrix.shape != (
            BOOTSTRAP_REPETITIONS,
            BOOTSTRAP_BLOCK_COUNT,
        ):
            raise ValueError("bootstrap block matrix must have int64 shape (10000, 14)")
        expected = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED)).integers(
            0,
            BOOTSTRAP_BLOCK_COUNT,
            size=(BOOTSTRAP_REPETITIONS, BOOTSTRAP_BLOCK_COUNT),
            endpoint=False,
            dtype=np.int64,
        )
        if not np.array_equal(matrix, expected):
            raise ValueError("bootstrap block matrix differs from frozen PCG64 draws")
        object.__setattr__(self, "day_start_utc_s", _immutable(days, dtype=np.int64))
        object.__setattr__(self, "block_index_matrix", _immutable(matrix, dtype=np.int64))

    @classmethod
    def create(
        cls,
        day_start_utc_s: Any,
        *,
        repetitions: int = BOOTSTRAP_REPETITIONS,
        seed: int = BOOTSTRAP_SEED,
    ) -> BootstrapPlan:
        raw_days = np.asarray(day_start_utc_s)
        if raw_days.dtype != np.dtype(np.int64) or raw_days.ndim != 1:
            raise ValueError("bootstrap day input must be a one-dimensional int64 vector")
        days = np.unique(raw_days)
        generator = np.random.Generator(np.random.PCG64(seed))
        matrix = generator.integers(
            0,
            BOOTSTRAP_BLOCK_COUNT,
            size=(repetitions, BOOTSTRAP_BLOCK_COUNT),
            endpoint=False,
            dtype=np.int64,
        )
        return cls(
            seed=seed,
            repetitions=repetitions,
            day_start_utc_s=days,
            block_index_matrix=matrix,
        )

    @property
    def matrix_sha256(self) -> str:
        little_endian = np.asarray(self.block_index_matrix, dtype="<i8")
        return hashlib.sha256(little_endian.tobytes(order="C")).hexdigest()

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "generator": "numpy.random.Generator(PCG64)",
            "seed": self.seed,
            "repetitions": self.repetitions,
            "block_unit": "America/Los_Angeles issue-date",
            "block_count": len(self.day_start_utc_s),
            "blocks_drawn_per_repetition": BOOTSTRAP_BLOCK_COUNT,
            "shared_block_sha256": self.matrix_sha256,
            "pooled_statistic": "mean paired absolute-error delta over all sampled block rows",
            "quantile_method": "linear",
        }


@dataclass(frozen=True, slots=True)
class BootstrapInterval:
    learner: str
    parent_tier: str
    child_tier: str
    horizon_minutes: int
    point_delta_a: float
    ci_lower_a: float
    ci_upper_a: float
    seed: int
    repetitions: int
    block_count: int
    matrix_sha256: str

    def __post_init__(self) -> None:
        if self.learner not in LEARNER_ORDER:
            raise ValueError("bootstrap interval requires a frozen learner")
        if (self.parent_tier, self.child_tier) not in ADJACENT_TIER_PAIRS:
            raise ValueError("bootstrap interval requires one adjacent tier pair")
        object.__setattr__(self, "horizon_minutes", _strict_horizon(self.horizon_minutes))
        numeric = (self.point_delta_a, self.ci_lower_a, self.ci_upper_a)
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in numeric):
            raise TypeError("bootstrap interval endpoints must be numeric")
        if not all(math.isfinite(float(value)) for value in numeric):
            raise ValueError("bootstrap interval endpoints must be finite")
        if float(self.ci_lower_a) > float(self.ci_upper_a):
            raise ValueError("bootstrap interval lower endpoint exceeds upper endpoint")
        if self.seed != BOOTSTRAP_SEED:
            raise ValueError(f"bootstrap interval seed must be {BOOTSTRAP_SEED}")
        if self.repetitions != BOOTSTRAP_REPETITIONS:
            raise ValueError("bootstrap interval repetitions must be exactly 10,000")
        if self.block_count != BOOTSTRAP_BLOCK_COUNT:
            raise ValueError("bootstrap interval must use exactly 14 day blocks")
        if not isinstance(self.matrix_sha256, str) or not _SHA256.fullmatch(self.matrix_sha256):
            raise ValueError("bootstrap interval matrix hash must be lowercase SHA-256")
        object.__setattr__(self, "point_delta_a", float(self.point_delta_a))
        object.__setattr__(self, "ci_lower_a", float(self.ci_lower_a))
        object.__setattr__(self, "ci_upper_a", float(self.ci_upper_a))

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.learner, self.parent_tier, self.child_tier, self.horizon_minutes)

    @property
    def nominal_208v_point_delta_kw(self) -> float:
        return NOMINAL_208V_KW_PER_AMP * self.point_delta_a

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "learner": self.learner,
            "parent_tier": self.parent_tier,
            "child_tier": self.child_tier,
            "horizon_minutes": self.horizon_minutes,
            "point_delta_a": self.point_delta_a,
            "ci_lower_a": self.ci_lower_a,
            "ci_upper_a": self.ci_upper_a,
            "nominal_208v_point_delta_kw": self.nominal_208v_point_delta_kw,
            "nominal_208v_ci_lower_kw": NOMINAL_208V_KW_PER_AMP * self.ci_lower_a,
            "nominal_208v_ci_upper_kw": NOMINAL_208V_KW_PER_AMP * self.ci_upper_a,
            "delta_direction": "positive means child tier has lower absolute error",
            "seed": self.seed,
            "repetitions": self.repetitions,
            "block_count": self.block_count,
            "shared_block_sha256": self.matrix_sha256,
            "confidence_level": 0.95,
            "quantile_method": "linear",
        }


def bootstrap_tier_comparison(
    comparison: TierComparison,
    plan: BootstrapPlan,
) -> BootstrapInterval:
    """Apply the shared plan to one paired comparison using pooled sampled rows."""

    if not isinstance(comparison, TierComparison) or not isinstance(plan, BootstrapPlan):
        raise TypeError("paired bootstrap requires a TierComparison and BootstrapPlan")
    comparison_days = np.unique(comparison.day_start_utc_s)
    if not np.array_equal(comparison_days, plan.day_start_utc_s):
        raise ValueError("paired comparison must contain the exact shared 14 day blocks")
    daily_sums = np.asarray(
        [
            float(np.sum(comparison.absolute_error_delta_a[comparison.day_start_utc_s == day]))
            for day in plan.day_start_utc_s
        ],
        dtype=np.float64,
    )
    daily_counts = np.asarray(
        [int(np.sum(comparison.day_start_utc_s == day)) for day in plan.day_start_utc_s],
        dtype=np.int64,
    )
    if np.any(daily_counts <= 0):
        raise ValueError("every bootstrap day block must contain paired rows")
    indexes = plan.block_index_matrix
    sampled_sums = np.sum(daily_sums[indexes], axis=1)
    sampled_counts = np.sum(daily_counts[indexes], axis=1)
    replicates = sampled_sums / sampled_counts
    if replicates.shape != (BOOTSTRAP_REPETITIONS,) or not np.isfinite(replicates).all():
        raise ValueError("bootstrap replicate means are non-finite or incomplete")
    lower, upper = np.quantile(replicates, [0.025, 0.975], method="linear")
    return BootstrapInterval(
        learner=comparison.learner,
        parent_tier=comparison.parent_tier,
        child_tier=comparison.child_tier,
        horizon_minutes=comparison.horizon_minutes,
        point_delta_a=comparison.mean_absolute_error_delta_a,
        ci_lower_a=float(lower),
        ci_upper_a=float(upper),
        seed=plan.seed,
        repetitions=plan.repetitions,
        block_count=len(plan.day_start_utc_s),
        matrix_sha256=plan.matrix_sha256,
    )


@dataclass(frozen=True, slots=True, init=False)
class GateEvidence:
    """Sealed unrounded HGB evidence derived only from canonical formal records."""

    horizons_minutes: tuple[int, int, int]
    hgb_mae_by_tier: Mapping[str, np.ndarray]
    m3_vs_m2_ci_lower: np.ndarray
    m3_daily_absolute_error_delta: np.ndarray
    local_dates: tuple[str, ...]
    hgb_row_identity_sha256: str
    comparison_suite_sha256: str
    matrix_sha256: str
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("GateEvidence is derived only by evaluate_gate1 from canonical evidence")


def _validate_gate_evidence(evidence: GateEvidence) -> None:
    if not isinstance(evidence, GateEvidence) or getattr(evidence, "_seal", None) is not (
        _GATE_EVIDENCE_SEAL
    ):
        raise ValueError("Gate evidence is not sealed canonical evidence")
    if evidence.horizons_minutes != NEAR_HORIZONS_MINUTES:
        raise ValueError("Gate evidence horizons must be exactly 15/30/60 minutes")
    if tuple(evidence.hgb_mae_by_tier) != TIER_ORDER:
        raise ValueError("Gate evidence must contain HGB M1-M4 MAE in canonical order")
    for tier in TIER_ORDER:
        values = np.asarray(evidence.hgb_mae_by_tier[tier])
        if values.dtype != np.dtype(np.float64) or values.shape != (3,):
            raise ValueError("Gate evidence MAE arrays differ from the sealed schema")
        if not np.isfinite(values).all() or np.any(values < 0.0):
            raise ValueError("Gate evidence MAE arrays must be finite and nonnegative")
    for tier in ("M1", "M2", "M3"):
        if np.any(evidence.hgb_mae_by_tier[tier] <= 0.0):
            raise ValueError("every Gate parent MAE must be finite and positive")
    if (
        evidence.m3_vs_m2_ci_lower.shape != (3,)
        or not np.isfinite(evidence.m3_vs_m2_ci_lower).all()
    ):
        raise ValueError("Gate CI evidence is incomplete or non-finite")
    if (
        evidence.m3_daily_absolute_error_delta.shape != (14, 3)
        or not np.isfinite(evidence.m3_daily_absolute_error_delta).all()
    ):
        raise ValueError("Gate daily evidence must contain 14 complete local dates")
    expected_dates = tuple(f"2019-05-{day:02d}" for day in range(18, 32))
    if evidence.local_dates != expected_dates:
        raise ValueError("Gate evidence local-date identity differs from the frozen test period")
    if evidence.hgb_row_identity_sha256 != _CANONICAL_TEST_ROW_SHA256:
        raise ValueError("Gate evidence row identity differs from the canonical test cohort")
    for digest in (
        evidence.comparison_suite_sha256,
        evidence.matrix_sha256,
    ):
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("Gate evidence provenance must use lowercase SHA-256")


def _seal_gate_evidence(
    *,
    hgb_mae_by_tier: Mapping[str, np.ndarray],
    m3_vs_m2_ci_lower: np.ndarray,
    m3_daily_absolute_error_delta: np.ndarray,
    comparison_suite_sha256: str,
    matrix_sha256: str,
) -> GateEvidence:
    evidence = object.__new__(GateEvidence)
    object.__setattr__(evidence, "horizons_minutes", NEAR_HORIZONS_MINUTES)
    object.__setattr__(
        evidence,
        "hgb_mae_by_tier",
        MappingProxyType(
            {tier: _immutable(hgb_mae_by_tier[tier], dtype=np.float64) for tier in TIER_ORDER}
        ),
    )
    object.__setattr__(
        evidence,
        "m3_vs_m2_ci_lower",
        _immutable(m3_vs_m2_ci_lower, dtype=np.float64),
    )
    object.__setattr__(
        evidence,
        "m3_daily_absolute_error_delta",
        _immutable(m3_daily_absolute_error_delta, dtype=np.float64),
    )
    object.__setattr__(
        evidence,
        "local_dates",
        tuple(f"2019-05-{day:02d}" for day in range(18, 32)),
    )
    object.__setattr__(evidence, "hgb_row_identity_sha256", _CANONICAL_TEST_ROW_SHA256)
    object.__setattr__(evidence, "comparison_suite_sha256", comparison_suite_sha256)
    object.__setattr__(evidence, "matrix_sha256", matrix_sha256)
    object.__setattr__(evidence, "_seal", _GATE_EVIDENCE_SEAL)
    _validate_gate_evidence(evidence)
    return evidence


@dataclass(frozen=True, slots=True)
class GateDecision:
    classification: str
    execution_ok: bool
    blocking_issues: tuple[str, ...]
    m2_diagnostic_mean_delta_a: float | None
    m2_diagnostic_improves: bool | None
    m3_improvement_percent: tuple[float, float, float] | None
    m3_gain_horizon_count: int | None
    m3_no_degradation: bool | None
    m3_directional_ci: bool | None
    m3_winning_days: int | None
    m3_pass: bool | None
    m4_improvement_percent: tuple[float, float, float] | None
    m4_gain_horizon_count: int | None
    m4_no_degradation: bool | None
    m4_keep: bool | None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "execution_ok": self.execution_ok,
            "blocking_issues": list(self.blocking_issues),
            "near_horizons_minutes": list(NEAR_HORIZONS_MINUTES),
            "m2_classification_only_diagnostic": {
                "mean_mae_delta_a": self.m2_diagnostic_mean_delta_a,
                "improves": self.m2_diagnostic_improves,
                "rule": (
                    "strictly positive unrounded equal-weight mean of HGB "
                    "15/30/60-minute pooled MAE(M1)-MAE(M2); no added threshold"
                ),
            },
            "m3": {
                "improvement_percent": (
                    list(self.m3_improvement_percent)
                    if self.m3_improvement_percent is not None
                    else None
                ),
                "gain_horizon_count": self.m3_gain_horizon_count,
                "no_degradation": self.m3_no_degradation,
                "directional_ci": self.m3_directional_ci,
                "winning_days": self.m3_winning_days,
                "pass": self.m3_pass,
                "thresholds": {
                    "gain_percent": 3.0,
                    "minimum_gain_horizons": 2,
                    "maximum_regression_percent": 2.0,
                    "minimum_winning_days": 10,
                    "directional_ci_rule": "at least one lower endpoint strictly greater than zero",
                },
            },
            "m4": {
                "improvement_percent": (
                    list(self.m4_improvement_percent)
                    if self.m4_improvement_percent is not None
                    else None
                ),
                "gain_horizon_count": self.m4_gain_horizon_count,
                "no_degradation": self.m4_no_degradation,
                "keep": self.m4_keep,
                "thresholds": {
                    "gain_percent": 1.0,
                    "minimum_gain_horizons": 2,
                    "maximum_regression_percent": 2.0,
                },
            },
        }


def _normalize_failure_codes(
    codes: Sequence[ExecutionFailureCode],
) -> tuple[ExecutionFailureCode, ...]:
    if isinstance(codes, (str, bytes)):
        raise TypeError("execution failures must be fixed ExecutionFailureCode values")
    normalized: list[ExecutionFailureCode] = []
    for code in codes:
        if not isinstance(code, ExecutionFailureCode):
            raise TypeError("execution failures must be fixed ExecutionFailureCode values")
        if code not in normalized:
            normalized.append(code)
    return tuple(normalized)


def _execution_failure(codes: Sequence[ExecutionFailureCode]) -> GateDecision:
    normalized = _normalize_failure_codes(codes)
    return GateDecision(
        classification=EXECUTION_FAIL,
        execution_ok=False,
        blocking_issues=tuple(code.value for code in normalized),
        m2_diagnostic_mean_delta_a=None,
        m2_diagnostic_improves=None,
        m3_improvement_percent=None,
        m3_gain_horizon_count=None,
        m3_no_degradation=None,
        m3_directional_ci=None,
        m3_winning_days=None,
        m3_pass=None,
        m4_improvement_percent=None,
        m4_gain_horizon_count=None,
        m4_no_degradation=None,
        m4_keep=None,
    )


def classify_gate(
    evidence: GateEvidence | None,
    *,
    execution_failures: Sequence[ExecutionFailureCode] = (),
) -> GateDecision:
    """Apply the frozen Gate with execution failure taking unconditional precedence."""

    if execution_failures:
        return _execution_failure(execution_failures)
    if evidence is None:
        return _execution_failure((ExecutionFailureCode.INCOMPLETE_GATE_EVIDENCE,))
    try:
        _validate_gate_evidence(evidence)
    except (TypeError, ValueError, AttributeError):
        return _execution_failure((ExecutionFailureCode.INVALID_GATE_EVIDENCE,))

    mae = evidence.hgb_mae_by_tier
    m2_diagnostic = float(np.mean(mae["M1"]) - np.mean(mae["M2"]))
    m2_improves = m2_diagnostic > 0.0
    m3_improvement = 100.0 * (mae["M2"] - mae["M3"]) / mae["M2"]
    m4_improvement = 100.0 * (mae["M3"] - mae["M4"]) / mae["M3"]
    if not np.isfinite(m3_improvement).all() or not np.isfinite(m4_improvement).all():
        return _execution_failure((ExecutionFailureCode.NONFINITE_GATE_IMPROVEMENT,))
    m3_gain_count = int(np.sum(m3_improvement >= 3.0))
    m3_no_degradation = bool(np.all(m3_improvement >= -2.0))
    m3_directional_ci = bool(np.any(evidence.m3_vs_m2_ci_lower > 0.0))
    daily_mean_delta = np.mean(evidence.m3_daily_absolute_error_delta, axis=1)
    winning_days = int(np.sum(daily_mean_delta > 0.0))
    m3_pass = bool(
        m3_gain_count >= 2 and m3_no_degradation and (m3_directional_ci or winning_days >= 10)
    )
    m4_gain_count = int(np.sum(m4_improvement >= 1.0))
    m4_no_degradation = bool(np.all(m4_improvement >= -2.0))
    m4_keep = bool(m4_gain_count >= 2 and m4_no_degradation)
    if m3_pass:
        classification = "PASS_ACTIVE_SESSION" if m4_keep else "PASS_ACTIVE_SESSION_DROP_M4"
    else:
        classification = "PASS_SIMPLE_STATE_ONLY" if m2_improves else "FAIL_DIRECTION"
    return GateDecision(
        classification=classification,
        execution_ok=True,
        blocking_issues=(),
        m2_diagnostic_mean_delta_a=m2_diagnostic,
        m2_diagnostic_improves=m2_improves,
        m3_improvement_percent=tuple(float(value) for value in m3_improvement),
        m3_gain_horizon_count=m3_gain_count,
        m3_no_degradation=m3_no_degradation,
        m3_directional_ci=m3_directional_ci,
        m3_winning_days=winning_days,
        m3_pass=m3_pass,
        m4_improvement_percent=tuple(float(value) for value in m4_improvement),
        m4_gain_horizon_count=m4_gain_count,
        m4_no_degradation=m4_no_degradation,
        m4_keep=m4_keep,
    )


ModelKey = tuple[str, str | None, str | None, str | None, int]


def _series_key(series: EvaluationSeries) -> ModelKey:
    return (
        series.model_kind,
        series.learner,
        series.tier,
        series.baseline,
        series.horizon_minutes,
    )


def _expected_series_keys() -> tuple[ModelKey, ...]:
    learned = tuple(
        ("learned", learner, tier, None, horizon)
        for learner in LEARNER_ORDER
        for tier in TIER_ORDER
        for horizon in HORIZONS_MINUTES
    )
    persistence = tuple(
        ("persistence", None, None, baseline, horizon)
        for baseline in PERSISTENCE_ORDER
        for horizon in HORIZONS_MINUTES
    )
    return learned + persistence


_EXPECTED_SERIES_KEYS = _expected_series_keys()
_EXPECTED_COMPARISON_KEYS = tuple(
    (learner, parent_tier, child_tier, horizon)
    for learner in LEARNER_ORDER
    for parent_tier, child_tier in ADJACENT_TIER_PAIRS
    for horizon in HORIZONS_MINUTES
)


def _normalize_evaluation_series(
    records: Sequence[EvaluationSeries | PredictionBundle]
    | Mapping[Any, EvaluationSeries | PredictionBundle],
) -> tuple[EvaluationSeries, ...]:
    if isinstance(records, Mapping):
        raw_records = tuple(records.values())
    elif isinstance(records, Sequence) and not isinstance(records, (str, bytes)):
        raw_records = tuple(records)
    else:
        raise TypeError("formal evaluation input must be a sequence or mapping of model records")
    normalized: list[EvaluationSeries] = []
    for record in raw_records:
        if isinstance(record, EvaluationSeries):
            normalized.append(record)
        elif isinstance(record, PredictionBundle):
            normalized.append(EvaluationSeries.from_prediction_bundle(record))
        else:
            raise TypeError(
                "formal evaluation records must be EvaluationSeries or PredictionBundle objects"
            )
    return tuple(normalized)


def _canonical_series_map(
    records: Sequence[EvaluationSeries | PredictionBundle]
    | Mapping[Any, EvaluationSeries | PredictionBundle],
) -> tuple[tuple[EvaluationSeries, ...], Mapping[ModelKey, EvaluationSeries]]:
    normalized = _normalize_evaluation_series(records)
    by_key: dict[ModelKey, EvaluationSeries] = {}
    for series in normalized:
        key = _series_key(series)
        if key in by_key:
            raise ValueError("formal evaluation contains a duplicate model-horizon record")
        by_key[key] = series
    if set(by_key) != set(_EXPECTED_SERIES_KEYS):
        raise ValueError(
            "formal evaluation requires the complete canonical 55 model-horizon records"
        )
    ordered = tuple(by_key[key] for key in _EXPECTED_SERIES_KEYS)
    for series in ordered:
        if not np.array_equal(
            series.issue_times, _CANONICAL_TEST_ISSUE_TIMES
        ) or not np.array_equal(series.day_start_utc_s, _CANONICAL_TEST_DAY_STARTS):
            raise ValueError(
                "formal evaluation series must use the exact canonical 1,329 test-row identity"
            )
        if series.model_kind == "persistence":
            expected_coverage = _EXPECTED_PERSISTENCE_COVERAGE[str(series.baseline)]
            if int(np.sum(series.availability)) != expected_coverage:
                raise ValueError("persistence coverage differs from the frozen formal baseline")
    for horizon in HORIZONS_MINUTES:
        reference = by_key[("learned", "ridge", "M1", None, horizon)].y_true
        for key in _EXPECTED_SERIES_KEYS:
            if key[-1] == horizon and not np.array_equal(by_key[key].y_true, reference):
                raise ValueError("formal evaluation truth differs within one horizon")
    return ordered, MappingProxyType(by_key)


def _comparison_suite_sha256(comparisons: Sequence[TierComparison]) -> str:
    digest = hashlib.sha256()
    for comparison in comparisons:
        digest.update(
            json.dumps(
                comparison.key,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        )
        for array in (
            comparison.issue_times,
            comparison.day_start_utc_s,
            comparison.absolute_error_delta_a,
        ):
            value = np.ascontiguousarray(array)
            digest.update(value.dtype.str.encode("ascii"))
            digest.update(np.asarray(value.shape, dtype="<i8").tobytes(order="C"))
            digest.update(value.tobytes(order="C"))
        digest.update(
            np.asarray(
                (
                    comparison.parent_mae_a,
                    comparison.child_mae_a,
                    comparison.mean_absolute_error_delta_a,
                    comparison.relative_improvement_percent,
                ),
                dtype="<f8",
            ).tobytes(order="C")
        )
    return digest.hexdigest()


def _same_bootstrap_interval(left: BootstrapInterval, right: BootstrapInterval) -> bool:
    return left.to_public_dict() == right.to_public_dict()


def _derive_gate_evidence(
    comparisons: tuple[TierComparison, ...],
    intervals: tuple[BootstrapInterval, ...],
    plan: BootstrapPlan,
) -> GateEvidence:
    comparison_map = {value.key: value for value in comparisons}
    interval_map = {value.key: value for value in intervals}
    if (
        len(comparison_map) != 30
        or len(interval_map) != 30
        or tuple(value.key for value in comparisons) != _EXPECTED_COMPARISON_KEYS
        or tuple(value.key for value in intervals) != _EXPECTED_COMPARISON_KEYS
    ):
        raise ValueError("Gate evidence requires all 30 canonical comparisons and intervals")
    expected_dates = tuple(f"2019-05-{day:02d}" for day in range(18, 32))
    for key in _EXPECTED_COMPARISON_KEYS:
        comparison = comparison_map[key]
        interval = interval_map[key]
        if not np.array_equal(comparison.issue_times, _CANONICAL_TEST_ISSUE_TIMES):
            raise ValueError("tier comparison row identity differs from the canonical cohort")
        if not np.array_equal(comparison.day_start_utc_s, _CANONICAL_TEST_DAY_STARTS):
            raise ValueError("tier comparison day identity differs from the canonical cohort")
        if tuple(value.local_date for value in comparison.daily) != expected_dates:
            raise ValueError("tier comparison does not contain the exact 14 local dates")
        if tuple(value.n_rows for value in comparison.daily) != _EXPECTED_TEST_DAY_COUNTS:
            raise ValueError("tier comparison daily row counts differ from the canonical cohort")
        expected_interval = bootstrap_tier_comparison(comparison, plan)
        if not _same_bootstrap_interval(interval, expected_interval):
            raise ValueError("bootstrap interval differs from its same-source tier comparison")

    hgb_mae: dict[str, list[float]] = {tier: [] for tier in TIER_ORDER}
    ci_lower: list[float] = []
    daily_columns: list[np.ndarray] = []
    for horizon in NEAR_HORIZONS_MINUTES:
        m1_m2 = comparison_map[("hgb", "M1", "M2", horizon)]
        m2_m3 = comparison_map[("hgb", "M2", "M3", horizon)]
        m3_m4 = comparison_map[("hgb", "M3", "M4", horizon)]
        if m1_m2.child_mae_a != m2_m3.parent_mae_a:
            raise ValueError("HGB M2 MAE differs across adjacent same-source comparisons")
        if m2_m3.child_mae_a != m3_m4.parent_mae_a:
            raise ValueError("HGB M3 MAE differs across adjacent same-source comparisons")
        hgb_mae["M1"].append(m1_m2.parent_mae_a)
        hgb_mae["M2"].append(m1_m2.child_mae_a)
        hgb_mae["M3"].append(m2_m3.child_mae_a)
        hgb_mae["M4"].append(m3_m4.child_mae_a)
        interval = interval_map[("hgb", "M2", "M3", horizon)]
        ci_lower.append(interval.ci_lower_a)
        daily_columns.append(
            np.asarray(
                [value.absolute_error_delta_a for value in m2_m3.daily],
                dtype=np.float64,
            )
        )
    return _seal_gate_evidence(
        hgb_mae_by_tier={
            tier: np.asarray(values, dtype=np.float64) for tier, values in hgb_mae.items()
        },
        m3_vs_m2_ci_lower=np.asarray(ci_lower, dtype=np.float64),
        m3_daily_absolute_error_delta=np.column_stack(daily_columns),
        comparison_suite_sha256=_comparison_suite_sha256(comparisons),
        matrix_sha256=plan.matrix_sha256,
    )


@dataclass(frozen=True, slots=True)
class Gate1EvaluationResult:
    """Local formal result; publication must pass the same-source rebuild gate."""

    evaluation_series: tuple[EvaluationSeries, ...]
    scoped_metrics: tuple[ScopedMetrics, ...]
    peak_ramp_metrics: tuple[PeakRampMetrics, ...]
    comparisons: tuple[TierComparison, ...]
    bootstrap_plan: BootstrapPlan
    bootstrap_intervals: tuple[BootstrapInterval, ...]
    gate_evidence: GateEvidence
    gate_decision: GateDecision
    execution_failures: tuple[ExecutionFailureCode, ...]
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _GATE_RESULT_SEAL:
            raise TypeError("Gate1EvaluationResult must be created by evaluate_gate1")


def evaluate_gate1(
    evaluation_records: Sequence[EvaluationSeries | PredictionBundle]
    | Mapping[Any, EvaluationSeries | PredictionBundle],
    *,
    bootstrap_plan: BootstrapPlan | None = None,
    execution_failures: Sequence[ExecutionFailureCode] = (),
) -> Gate1EvaluationResult:
    """Evaluate the sole complete frozen Gate 1 cohort from canonical local records."""

    failures = _normalize_failure_codes(execution_failures)
    ordered_series, series_map = _canonical_series_map(evaluation_records)
    if bootstrap_plan is None:
        plan = BootstrapPlan.create(_CANONICAL_TEST_DAY_STARTS)
    elif isinstance(bootstrap_plan, BootstrapPlan):
        plan = bootstrap_plan
    else:
        raise TypeError("formal evaluation bootstrap plan must be a BootstrapPlan")
    if not np.array_equal(plan.day_start_utc_s, np.unique(_CANONICAL_TEST_DAY_STARTS)):
        raise ValueError("formal evaluation bootstrap plan differs from the canonical 14 days")

    scoped_metrics = tuple(evaluate_scopes(series) for series in ordered_series)
    peak_ramp_metrics = tuple(compute_peak_ramp_metrics(series) for series in ordered_series)
    comparisons = tuple(
        compare_adjacent_tiers(
            series_map[("learned", learner, parent_tier, None, horizon)],
            series_map[("learned", learner, child_tier, None, horizon)],
        )
        for learner in LEARNER_ORDER
        for parent_tier, child_tier in ADJACENT_TIER_PAIRS
        for horizon in HORIZONS_MINUTES
    )
    intervals = tuple(bootstrap_tier_comparison(comparison, plan) for comparison in comparisons)
    evidence = _derive_gate_evidence(comparisons, intervals, plan)
    decision = classify_gate(evidence, execution_failures=failures)
    return Gate1EvaluationResult(
        evaluation_series=ordered_series,
        scoped_metrics=scoped_metrics,
        peak_ramp_metrics=peak_ramp_metrics,
        comparisons=comparisons,
        bootstrap_plan=plan,
        bootstrap_intervals=intervals,
        gate_evidence=evidence,
        gate_decision=decision,
        execution_failures=failures,
        _seal=_GATE_RESULT_SEAL,
    )


def _gate_evidence_validation_payload(evidence: GateEvidence) -> dict[str, Any]:
    _validate_gate_evidence(evidence)
    return {
        "horizons_minutes": list(evidence.horizons_minutes),
        "hgb_mae_by_tier": {tier: evidence.hgb_mae_by_tier[tier].tolist() for tier in TIER_ORDER},
        "m3_vs_m2_ci_lower": evidence.m3_vs_m2_ci_lower.tolist(),
        "m3_daily_absolute_error_delta": evidence.m3_daily_absolute_error_delta.tolist(),
        "local_dates": list(evidence.local_dates),
        "hgb_row_identity_sha256": evidence.hgb_row_identity_sha256,
        "comparison_suite_sha256": evidence.comparison_suite_sha256,
        "matrix_sha256": evidence.matrix_sha256,
    }


def _result_validation_payload(result: Gate1EvaluationResult) -> dict[str, Any]:
    if not isinstance(result, Gate1EvaluationResult) or result._seal is not _GATE_RESULT_SEAL:
        raise TypeError("public metrics require a formal Gate1EvaluationResult")
    return {
        "series_keys": [list(_series_key(value)) for value in result.evaluation_series],
        "scoped": [value.to_public_dict() for value in result.scoped_metrics],
        "peak_ramp": [value.to_public_dict() for value in result.peak_ramp_metrics],
        "comparisons": [
            {
                "summary": value.to_public_dict(),
                "daily": value.daily_public_rows(),
            }
            for value in result.comparisons
        ],
        "bootstrap_plan": result.bootstrap_plan.to_public_dict(),
        "bootstrap_intervals": [value.to_public_dict() for value in result.bootstrap_intervals],
        "gate_evidence": _gate_evidence_validation_payload(result.gate_evidence),
        "gate_decision": result.gate_decision.to_public_dict(),
        "execution_failures": [value.value for value in result.execution_failures],
    }


def _verified_same_source_result(result: Gate1EvaluationResult) -> Gate1EvaluationResult:
    try:
        submitted = _result_validation_payload(result)
        regenerated = evaluate_gate1(
            result.evaluation_series,
            bootstrap_plan=result.bootstrap_plan,
            execution_failures=result.execution_failures,
        )
        expected = _result_validation_payload(regenerated)
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "public result is incomplete or differs from the same-source canonical evaluation"
        ) from exc
    if submitted != expected:
        raise ValueError(
            "public result is incomplete or differs from the same-source canonical evaluation"
        )
    return regenerated


def _scoped_sort_key(value: ScopedMetrics) -> tuple[Any, ...]:
    learner_position = LEARNER_ORDER.index(value.learner) if value.learner else 99
    tier_position = TIER_ORDER.index(value.tier) if value.tier else 99
    baseline_position = PERSISTENCE_ORDER.index(value.baseline) if value.baseline else 99
    return (
        0 if value.model_kind == "learned" else 1,
        learner_position,
        tier_position,
        baseline_position,
        value.horizon_minutes,
    )


def _comparison_sort_key(value: TierComparison | BootstrapInterval) -> tuple[int, int, int]:
    return (
        LEARNER_ORDER.index(value.learner),
        ADJACENT_TIER_PAIRS.index((value.parent_tier, value.child_tier)),
        HORIZONS_MINUTES.index(value.horizon_minutes),
    )


def _assert_public_key(key: str, *, path: str) -> None:
    lowered = key.casefold()
    compact = re.sub(r"[^a-z0-9]", "", lowered)
    if lowered == "_id" or any(
        fragment in compact for fragment in _PUBLIC_FORBIDDEN_COMPACT_TOKENS
    ):
        raise ValueError(f"{path} contains a forbidden private identifier key")


def _assert_public_string(value: str, *, path: str) -> None:
    compact = re.sub(r"[^a-z0-9]", "", value.casefold())
    if _PRIVATE_ID_TOKEN.search(value) or any(
        fragment in compact for fragment in _PUBLIC_FORBIDDEN_COMPACT_TOKENS
    ):
        raise ValueError(f"{path} contains a forbidden private identifier")
    if _FILE_URI.search(value):
        raise ValueError(f"{path} contains a forbidden local file URI")
    if _WINDOWS_ABSOLUTE_PATH.search(value):
        raise ValueError(f"{path} contains a Windows absolute path")
    if _UNC_ABSOLUTE_PATH.search(value):
        raise ValueError(f"{path} contains a UNC absolute path")
    if _POSIX_ABSOLUTE_PATH.search(value):
        raise ValueError(f"{path} contains a POSIX absolute path")


def _assert_public_plain(value: Any, *, path: str = "payload") -> None:
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str):
            _assert_public_string(value, path=path)
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite public number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_public_plain(item, path=f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} contains a non-string public key")
            _assert_public_key(key, path=f"{path}.key")
            _assert_public_plain(item, path=f"{path}.{key}")
        return
    raise TypeError(f"{path} contains a non-JSON public value of type {type(value).__name__}")


def assert_public_payload_safe(payload: Any) -> None:
    """Reject local arrays, private identifiers, and local absolute paths."""

    _assert_public_plain(payload)


def build_public_aggregate_payload(result: Gate1EvaluationResult) -> dict[str, Any]:
    """Build aggregates only after a complete same-source formal rebuild."""

    verified = _verified_same_source_result(result)
    ordered_comparisons = sorted(verified.comparisons, key=_comparison_sort_key)
    ordered_intervals = sorted(verified.bootstrap_intervals, key=_comparison_sort_key)
    ordered_scoped = sorted(verified.scoped_metrics, key=_scoped_sort_key)
    peak_lookup = {
        (
            value.model_kind,
            value.learner,
            value.tier,
            value.baseline,
            value.horizon_minutes,
        ): value
        for value in verified.peak_ramp_metrics
    }
    ordered_peak = [
        peak_lookup[key]
        for key in sorted(
            peak_lookup,
            key=lambda key: (
                0 if key[0] == "learned" else 1,
                LEARNER_ORDER.index(key[1]) if key[1] else 99,
                TIER_ORDER.index(key[2]) if key[2] else 99,
                PERSISTENCE_ORDER.index(key[3]) if key[3] else 99,
                HORIZONS_MINUTES.index(key[4]),
            ),
        )
    ]
    payload: dict[str, Any] = {
        "schema_version": "acn-jpl-gate1-public-metrics/v1",
        "units": {
            "primary": "A",
            "nominal_reconstruction": "kW at fixed 0.208 kW/A; not directly measured power",
            "wape": "dimensionless ratio",
        },
        "metrics_by_horizon": [value.to_public_dict() for value in ordered_scoped],
        "tier_comparisons": [value.to_public_dict() for value in ordered_comparisons],
        "daily_paired_errors": [
            row for value in ordered_comparisons for row in value.daily_public_rows()
        ],
        "bootstrap": {
            "plan": verified.bootstrap_plan.to_public_dict(),
            "intervals": [value.to_public_dict() for value in ordered_intervals],
        },
        "peak_ramp_metrics": [value.to_public_dict() for value in ordered_peak],
        "gate": verified.gate_decision.to_public_dict(),
        "privacy": {
            "aggregate_only": True,
            "full_test_values_published": False,
            "bootstrap_draws_published": False,
            "local_paths_published": False,
            "private_identifiers_published": False,
        },
    }
    assert_public_payload_safe(payload)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return json.loads(encoded)


__all__ = [
    "BOOTSTRAP_REPETITIONS",
    "BOOTSTRAP_SEED",
    "BootstrapInterval",
    "BootstrapPlan",
    "DailyMetrics",
    "DailyPairedError",
    "DailyPeakMetric",
    "ErrorMetrics",
    "EvaluationSeries",
    "ExecutionFailureCode",
    "Gate1EvaluationResult",
    "GateDecision",
    "GateEvidence",
    "PeakRampMetrics",
    "ScopedMetrics",
    "TierComparison",
    "assert_public_payload_safe",
    "bootstrap_tier_comparison",
    "build_public_aggregate_payload",
    "classify_gate",
    "compare_adjacent_tiers",
    "compute_error_metrics",
    "compute_peak_ramp_metrics",
    "evaluate_gate1",
    "evaluate_scopes",
]
