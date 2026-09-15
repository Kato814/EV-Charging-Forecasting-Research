"""Aggregate-only data construction for the frozen R11-S0 protocol."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np

from evcf.forecasting.r11_s0_contracts import (
    CONTEXT_LENGTH,
    DEVELOPMENT_MONTHS,
    HISTORY_CHANNELS,
    HORIZONS_MINUTES,
    R11S0ContractError,
    assert_authorized_month,
)

_ZONE = ZoneInfo("America/Los_Angeles")
_HISTORY_VALUE_SLICE = slice(0, CONTEXT_LENGTH)
_HISTORY_MASK_SLICE = slice(CONTEXT_LENGTH, 2 * CONTEXT_LENGTH)
_MAX_HORIZON_SECONDS = max(HORIZONS_MINUTES) * 60


@dataclass(frozen=True, slots=True)
class MonthStationView:
    month: str
    issue_times: np.ndarray
    labels: np.ndarray
    m2_values: np.ndarray

    def validate(self) -> None:
        assert_authorized_month(self.month)
        n = self.issue_times.shape[0]
        if self.issue_times.dtype != np.dtype(np.int64) or self.issue_times.shape != (n,):
            raise R11S0ContractError("INVALID_ISSUE_TIMES")
        if self.labels.shape != (n, len(HORIZONS_MINUTES)):
            raise R11S0ContractError("INVALID_LABEL_SHAPE")
        if self.m2_values.ndim != 2 or self.m2_values.shape[0] != n or self.m2_values.shape[1] < 195:
            raise R11S0ContractError("INVALID_M2_SHAPE")
        if not np.isfinite(self.labels).all():
            raise R11S0ContractError("NONFINITE_LABEL")
        if np.any(self.labels < 0):
            raise R11S0ContractError("NEGATIVE_LABEL")


@dataclass(frozen=True, slots=True)
class FoldRows:
    train: tuple[tuple[str, int], ...]
    validation: tuple[tuple[str, int], ...]
    test: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ScalarStandardizer:
    mean: float
    scale: float

    def transform(self, value: np.ndarray) -> np.ndarray:
        return (np.asarray(value, dtype=np.float64) - self.mean) / self.scale

    def inverse(self, value: np.ndarray) -> np.ndarray:
        return np.asarray(value, dtype=np.float64) * self.scale + self.mean


@dataclass(frozen=True, slots=True)
class EncodedFold:
    train_history: np.ndarray
    train_issue_context: np.ndarray
    train_target_context: np.ndarray
    train_target: np.ndarray
    validation_history: np.ndarray
    validation_issue_context: np.ndarray
    validation_target_context: np.ndarray
    validation_target: np.ndarray
    test_history: np.ndarray
    test_issue_context: np.ndarray
    test_target_context: np.ndarray
    test_target: np.ndarray
    test_issue_times: np.ndarray
    history_standardizer: ScalarStandardizer
    target_standardizer: ScalarStandardizer


def _local_datetime(issue_time_utc_s: int, horizon_minutes: int = 0) -> datetime:
    return datetime.fromtimestamp(
        int(issue_time_utc_s) + 60 * int(horizon_minutes), timezone.utc
    ).astimezone(_ZONE)


def _month_local_midnight_epoch(month: str, day: int) -> int:
    try:
        year_text, month_text = month.split("-")
        value = datetime(int(year_text), int(month_text), day, tzinfo=_ZONE)
    except (TypeError, ValueError) as exc:
        raise R11S0ContractError("INVALID_MONTH_BOUNDARY") from exc
    return int(value.timestamp())


def _cyclic(index: float, period: float) -> tuple[float, float]:
    phase = 2.0 * np.pi * index / period
    return float(np.sin(phase)), float(np.cos(phase))


def issue_calendar_context(issue_time_utc_s: int) -> np.ndarray:
    local = _local_datetime(issue_time_utc_s)
    tod = local.hour * 60.0 + local.minute
    tod_sin, tod_cos = _cyclic(tod, 1440.0)
    dow_sin, dow_cos = _cyclic(float(local.weekday()), 7.0)
    return np.asarray(
        [tod_sin, tod_cos, dow_sin, dow_cos, float(local.weekday() >= 5)],
        dtype=np.float32,
    )


def target_calendar_context(issue_time_utc_s: int) -> np.ndarray:
    rows: list[list[float]] = []
    for horizon in HORIZONS_MINUTES:
        local = _local_datetime(issue_time_utc_s, horizon)
        tod = local.hour * 60.0 + local.minute
        tod_sin, tod_cos = _cyclic(tod, 1440.0)
        dow_sin, dow_cos = _cyclic(float(local.weekday()), 7.0)
        rows.append(
            [
                tod_sin,
                tod_cos,
                dow_sin,
                dow_cos,
                float(local.weekday() >= 5),
                horizon / 240.0,
            ]
        )
    return np.asarray(rows, dtype=np.float32)


def chronological_rows(views: dict[str, MonthStationView], target_month: str) -> FoldRows:
    if tuple(views) != DEVELOPMENT_MONTHS:
        raise R11S0ContractError("DEVELOPMENT_MONTH_ORDER_INVALID")
    assert_authorized_month(target_month)
    target_position = DEVELOPMENT_MONTHS.index(target_month)
    train_cutoff = _month_local_midnight_epoch(target_month, 15)
    validation_cutoff = _month_local_midnight_epoch(target_month, 18)
    train: list[tuple[str, int]] = []
    validation: list[tuple[str, int]] = []
    test: list[tuple[str, int]] = []
    for position, month in enumerate(DEVELOPMENT_MONTHS):
        view = views[month]
        view.validate()
        if position > target_position:
            continue
        for index, issue_value in enumerate(view.issue_times):
            issue = int(issue_value)
            if position < target_position:
                train.append((month, index))
                continue
            day = _local_datetime(issue).day
            if day <= 14:
                if issue + _MAX_HORIZON_SECONDS <= train_cutoff:
                    train.append((month, index))
            elif day <= 17:
                if issue + _MAX_HORIZON_SECONDS <= validation_cutoff:
                    validation.append((month, index))
            else:
                test.append((month, index))
    if not train or not validation or not test:
        raise R11S0ContractError("EMPTY_CHRONOLOGICAL_PARTITION")
    if any(
        int(views[month].issue_times[row]) + _MAX_HORIZON_SECONDS > train_cutoff
        for month, row in train
        if month == target_month
    ):
        raise R11S0ContractError("TRAIN_LABEL_LEAKAGE")
    if any(
        int(views[month].issue_times[row]) + _MAX_HORIZON_SECONDS > validation_cutoff
        for month, row in validation
    ):
        raise R11S0ContractError("VALIDATION_LABEL_LEAKAGE")
    return FoldRows(tuple(train), tuple(validation), tuple(test))


def _raw_history(view: MonthStationView, row: int) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(view.m2_values[row, _HISTORY_VALUE_SLICE], dtype=np.float64)
    mask = np.asarray(view.m2_values[row, _HISTORY_MASK_SLICE], dtype=np.float64)
    if values.shape != (CONTEXT_LENGTH,) or mask.shape != (CONTEXT_LENGTH,):
        raise R11S0ContractError("INVALID_HISTORY_SHAPE")
    if not np.isfinite(mask).all() or np.any((mask != 0.0) & (mask != 1.0)):
        raise R11S0ContractError("INVALID_HISTORY_MASK")
    observed = mask == 1.0
    if np.any(~np.isfinite(values[observed])):
        raise R11S0ContractError("NONFINITE_OBSERVED_HISTORY")
    return values, mask


def _fit_history_standardizer(
    views: dict[str, MonthStationView], rows: Iterable[tuple[str, int]]
) -> ScalarStandardizer:
    observed_values: list[np.ndarray] = []
    for month, row in rows:
        values, mask = _raw_history(views[month], row)
        observed_values.append(values[mask == 1.0])
    flat = np.concatenate(observed_values) if observed_values else np.asarray([], dtype=np.float64)
    if flat.size == 0:
        raise R11S0ContractError("NO_OBSERVED_TRAIN_HISTORY")
    mean = float(np.mean(flat))
    scale = float(np.std(flat))
    if not np.isfinite(mean) or not np.isfinite(scale):
        raise R11S0ContractError("INVALID_HISTORY_STANDARDIZER")
    if scale <= 1e-12:
        scale = 1.0
    return ScalarStandardizer(mean, scale)


def _fit_target_standardizer(
    views: dict[str, MonthStationView], rows: Iterable[tuple[str, int]]
) -> ScalarStandardizer:
    arrays = [np.asarray(views[month].labels[row], dtype=np.float64) for month, row in rows]
    flat = np.concatenate(arrays) if arrays else np.asarray([], dtype=np.float64)
    if flat.size == 0 or not np.isfinite(flat).all():
        raise R11S0ContractError("INVALID_TARGET_STANDARDIZER")
    mean = float(np.mean(flat))
    scale = float(np.std(flat))
    if scale <= 1e-12:
        scale = 1.0
    return ScalarStandardizer(mean, scale)


def _encode_rows(
    views: dict[str, MonthStationView],
    rows: tuple[tuple[str, int], ...],
    history_standardizer: ScalarStandardizer,
    target_standardizer: ScalarStandardizer,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    histories: list[np.ndarray] = []
    issue_contexts: list[np.ndarray] = []
    target_contexts: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    issues: list[int] = []
    for month, row in rows:
        view = views[month]
        values, mask = _raw_history(view, row)
        safe_values = np.where(mask == 1.0, values, history_standardizer.mean)
        standardized = history_standardizer.transform(safe_values)
        standardized[mask == 0.0] = 0.0
        histories.append(np.stack((standardized, mask), axis=1).astype(np.float32))
        issue = int(view.issue_times[row])
        issue_contexts.append(issue_calendar_context(issue))
        target_contexts.append(target_calendar_context(issue))
        targets.append(target_standardizer.transform(view.labels[row]).astype(np.float32))
        issues.append(issue)
    return (
        np.stack(histories),
        np.stack(issue_contexts),
        np.stack(target_contexts),
        np.stack(targets),
        np.asarray(issues, dtype=np.int64),
    )


def encode_fold(views: dict[str, MonthStationView], target_month: str) -> EncodedFold:
    rows = chronological_rows(views, target_month)
    history_standardizer = _fit_history_standardizer(views, rows.train)
    target_standardizer = _fit_target_standardizer(views, rows.train)
    train = _encode_rows(views, rows.train, history_standardizer, target_standardizer)
    validation = _encode_rows(views, rows.validation, history_standardizer, target_standardizer)
    test = _encode_rows(views, rows.test, history_standardizer, target_standardizer)
    return EncodedFold(
        train_history=train[0],
        train_issue_context=train[1],
        train_target_context=train[2],
        train_target=train[3],
        validation_history=validation[0],
        validation_issue_context=validation[1],
        validation_target_context=validation[2],
        validation_target=validation[3],
        test_history=test[0],
        test_issue_context=test[1],
        test_target_context=test[2],
        test_target=test[3],
        test_issue_times=test[4],
        history_standardizer=history_standardizer,
        target_standardizer=target_standardizer,
    )


def view_from_month_data(month_data: object) -> MonthStationView:
    """Extract only aggregate-history fields from a frozen ``MonthData`` object."""

    try:
        month = str(month_data.month)
        issue_times = np.asarray(month_data.issue_times)
        labels = np.asarray(month_data.labels)
        m2_values = np.asarray(month_data.blocks["M2"].values)
    except (AttributeError, KeyError, TypeError) as exc:
        raise R11S0ContractError("MONTH_DATA_INVALID") from exc
    view = MonthStationView(month, issue_times, labels, m2_values)
    view.validate()
    return view
