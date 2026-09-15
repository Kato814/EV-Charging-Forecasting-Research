"""Station-only data construction for the frozen JPL R11-S0 screen."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from zoneinfo import ZoneInfo

import numpy as np

from evcf.forecasting.acn_jpl_development_experts import MonthData
from evcf.forecasting.acn_jpl_r11_s0_common import (
    CONTEXT_LENGTH,
    DEVELOPMENT_MONTHS,
    EXPECTED_TEST_ORIGINS,
    HORIZONS_MINUTES,
    MAX_HORIZON_MINUTES,
    TARGET_CONTEXT_WIDTH,
    TEST_START_LOCAL_DAY,
    TIMEZONE_NAME,
    TRAIN_LAST_LOCAL_DAY,
    VALIDATION_FIRST_LOCAL_DAY,
    VALIDATION_LAST_LOCAL_DAY,
    R11S0Error,
)

_ZONE = ZoneInfo(TIMEZONE_NAME)


@dataclass(frozen=True, slots=True)
class StationMonthData:
    month: str
    issue_times: np.ndarray
    local_days: np.ndarray
    history_raw: np.ndarray
    history_mask: np.ndarray
    issue_context: np.ndarray
    target_context: np.ndarray
    labels: np.ndarray


@dataclass(frozen=True, slots=True)
class FoldScaler:
    history_mean: float
    history_scale: float
    target_mean: float
    target_scale: float


@dataclass(frozen=True, slots=True)
class StationFold:
    month: str
    train_history: np.ndarray
    train_issue_context: np.ndarray
    train_target_context: np.ndarray
    train_labels: np.ndarray
    validation_history: np.ndarray
    validation_issue_context: np.ndarray
    validation_target_context: np.ndarray
    validation_labels: np.ndarray
    test_history: np.ndarray
    test_issue_context: np.ndarray
    test_target_context: np.ndarray
    test_labels: np.ndarray
    test_issue_times: np.ndarray
    test_local_days: np.ndarray
    scaler: FoldScaler


def _local_datetime(epoch: int) -> datetime:
    return datetime.fromtimestamp(int(epoch), timezone.utc).astimezone(_ZONE)


def _month_start(month: str) -> int:
    year, number = (int(value) for value in month.split("-"))
    return int(datetime(year, number, 1, tzinfo=_ZONE).timestamp())


def _day_start(month: str, day: int) -> int:
    year, number = (int(value) for value in month.split("-"))
    return int(datetime(year, number, day, tzinfo=_ZONE).timestamp())


def _cyclic(values: np.ndarray, period: float) -> tuple[np.ndarray, np.ndarray]:
    angle = 2.0 * math.pi * np.asarray(values, dtype=np.float64) / period
    return np.sin(angle), np.cos(angle)


def calendar_context(issue_times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    issue_times = np.asarray(issue_times, dtype=np.int64)
    local = tuple(_local_datetime(value) for value in issue_times)
    minute = np.asarray([dt.hour * 60 + dt.minute for dt in local], dtype=np.float64)
    dow = np.asarray([dt.weekday() for dt in local], dtype=np.float64)
    tod_sin, tod_cos = _cyclic(minute, 1440.0)
    dow_sin, dow_cos = _cyclic(dow, 7.0)
    issue = np.column_stack((tod_sin, tod_cos, dow_sin, dow_cos, (dow >= 5).astype(float)))
    target = np.empty((len(issue_times), len(HORIZONS_MINUTES), TARGET_CONTEXT_WIDTH))
    for position, horizon in enumerate(HORIZONS_MINUTES):
        target_local = tuple(_local_datetime(value + horizon * 60) for value in issue_times)
        target_minute = np.asarray(
            [dt.hour * 60 + dt.minute for dt in target_local], dtype=np.float64
        )
        target_dow = np.asarray([dt.weekday() for dt in target_local], dtype=np.float64)
        ts, tc = _cyclic(target_minute, 1440.0)
        ds, dc = _cyclic(target_dow, 7.0)
        target[:, position] = np.column_stack(
            (
                ts,
                tc,
                ds,
                dc,
                (target_dow >= 5).astype(float),
                np.full(len(issue_times), horizon / 240.0),
            )
        )
    return issue, target


def station_month_from_frozen_data(data: MonthData) -> StationMonthData:
    block = data.blocks["M2"]
    names = tuple(block.feature_names)
    history_names = tuple(
        f"history_station_current_mean_a_lag_{lag:03d}" for lag in range(96, 0, -1)
    )
    mask_names = tuple(f"history_observed_mask_lag_{lag:03d}" for lag in range(96, 0, -1))
    if names[:96] != history_names or names[96:192] != mask_names:
        raise R11S0Error("STATION_FEATURE_CONTRACT_INVALID")
    history = np.asarray(block.values[:, :96], dtype=np.float64)
    mask = np.asarray(block.values[:, 96:192], dtype=np.float64)
    if history.shape != (len(data.issue_times), CONTEXT_LENGTH) or mask.shape != history.shape:
        raise R11S0Error("STATION_FEATURE_CONTRACT_INVALID")
    if not np.isfinite(mask).all() or np.any((mask != 0.0) & (mask != 1.0)):
        raise R11S0Error("HISTORY_MASK_INVALID")
    observed = mask.astype(bool)
    if np.any(observed & ~np.isfinite(history)) or np.any(np.isinf(history)):
        raise R11S0Error("HISTORY_VALUE_INVALID")
    labels = np.asarray(data.labels, dtype=np.float64)
    if labels.shape != (len(data.issue_times), 5) or not np.isfinite(labels).all():
        raise R11S0Error("TARGET_INVALID")
    issue_context, target_context = calendar_context(data.issue_times)
    return StationMonthData(
        month=data.month,
        issue_times=np.asarray(data.issue_times, dtype=np.int64),
        local_days=np.asarray([_local_datetime(value).day for value in data.issue_times], dtype=np.int16),
        history_raw=history,
        history_mask=mask,
        issue_context=issue_context,
        target_context=target_context,
        labels=labels,
    )


def _history_eligible(data: StationMonthData) -> np.ndarray:
    return data.issue_times >= _month_start(data.month) + 24 * 60 * 60


def fit_scaler(history: np.ndarray, mask: np.ndarray, labels: np.ndarray) -> FoldScaler:
    observed = mask.astype(bool)
    values = history[observed]
    targets = np.asarray(labels, dtype=np.float64).reshape(-1)
    if not len(values) or not np.isfinite(values).all() or not np.isfinite(targets).all():
        raise R11S0Error("NORMALIZATION_INVALID")
    history_scale = float(np.std(values))
    target_scale = float(np.std(targets))
    return FoldScaler(
        history_mean=float(np.mean(values)),
        history_scale=history_scale if history_scale > 1e-8 else 1.0,
        target_mean=float(np.mean(targets)),
        target_scale=target_scale if target_scale > 1e-8 else 1.0,
    )


def transform_history(history: np.ndarray, mask: np.ndarray, scaler: FoldScaler) -> np.ndarray:
    observed = mask.astype(bool)
    standardized = np.zeros_like(history, dtype=np.float64)
    standardized[observed] = (history[observed] - scaler.history_mean) / scaler.history_scale
    result = np.stack((standardized, mask.astype(np.float64)), axis=-1)
    if result.shape[-2:] != (96, 2) or not np.isfinite(result).all():
        raise R11S0Error("NORMALIZATION_INVALID")
    return result.astype(np.float32)


def _concat(months: Sequence[StationMonthData], rows: Sequence[np.ndarray]):
    values = []
    for attribute in ("history_raw", "history_mask", "issue_context", "target_context", "labels"):
        values.append(
            np.concatenate(
                [getattr(month, attribute)[idx] for month, idx in zip(months, rows, strict=True)]
            )
        )
    return tuple(values)


def build_station_folds(months: Sequence[StationMonthData]) -> tuple[StationFold, ...]:
    by_name = {month.month: month for month in months}
    if tuple(by_name) != DEVELOPMENT_MONTHS:
        raise R11S0Error("DEVELOPMENT_MONTH_IDENTITY_INVALID")
    output: list[StationFold] = []
    for position, month_name in enumerate(DEVELOPMENT_MONTHS):
        current = by_name[month_name]
        train_cutoff = _day_start(month_name, 15)
        test_cutoff = _day_start(month_name, 18)
        eligible = _history_eligible(current)
        current_train = np.flatnonzero(
            eligible
            & (current.local_days <= TRAIN_LAST_LOCAL_DAY)
            & (current.issue_times + MAX_HORIZON_MINUTES * 60 <= train_cutoff)
        ).astype(np.int64)
        validation = np.flatnonzero(
            eligible
            & (current.local_days >= VALIDATION_FIRST_LOCAL_DAY)
            & (current.local_days <= VALIDATION_LAST_LOCAL_DAY)
            & (current.issue_times + MAX_HORIZON_MINUTES * 60 <= test_cutoff)
        ).astype(np.int64)
        test = np.flatnonzero(current.local_days >= TEST_START_LOCAL_DAY).astype(np.int64)
        if len(test) != EXPECTED_TEST_ORIGINS[month_name]:
            raise R11S0Error("TEST_ORIGIN_IDENTITY_INVALID")
        if not len(current_train) or not len(validation) or not len(test):
            raise R11S0Error("CHRONOLOGY_INVALID")
        train_months: list[StationMonthData] = []
        train_rows: list[np.ndarray] = []
        for earlier_name in DEVELOPMENT_MONTHS[:position]:
            historical = by_name[earlier_name]
            idx = np.flatnonzero(_history_eligible(historical)).astype(np.int64)
            if not len(idx):
                raise R11S0Error("CHRONOLOGY_INVALID")
            train_months.append(historical)
            train_rows.append(idx)
        train_months.append(current)
        train_rows.append(current_train)
        h_raw, h_mask, train_issue, train_target, train_labels = _concat(train_months, train_rows)
        scaler = fit_scaler(h_raw, h_mask, train_labels)
        if np.max(current.issue_times[current_train] + MAX_HORIZON_MINUTES * 60) > train_cutoff:
            raise R11S0Error("TEMPORAL_LEAKAGE")
        if np.max(current.issue_times[validation] + MAX_HORIZON_MINUTES * 60) > test_cutoff:
            raise R11S0Error("TEMPORAL_LEAKAGE")
        output.append(
            StationFold(
                month=month_name,
                train_history=transform_history(h_raw, h_mask, scaler),
                train_issue_context=train_issue.astype(np.float32),
                train_target_context=train_target.astype(np.float32),
                train_labels=train_labels,
                validation_history=transform_history(
                    current.history_raw[validation], current.history_mask[validation], scaler
                ),
                validation_issue_context=current.issue_context[validation].astype(np.float32),
                validation_target_context=current.target_context[validation].astype(np.float32),
                validation_labels=current.labels[validation],
                test_history=transform_history(
                    current.history_raw[test], current.history_mask[test], scaler
                ),
                test_issue_context=current.issue_context[test].astype(np.float32),
                test_target_context=current.target_context[test].astype(np.float32),
                test_labels=current.labels[test],
                test_issue_times=current.issue_times[test],
                test_local_days=current.local_days[test],
                scaler=scaler,
            )
        )
    return tuple(output)
