from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
from evcf.forecasting.r11_s0_contracts import DEVELOPMENT_MONTHS, HORIZONS_MINUTES
from evcf.forecasting.r11_s0_training import _aggregate_single_prediction_set

_ZONE = ZoneInfo("America/Los_Angeles")


def _issue(month: str, day: int) -> int:
    year, month_number = (int(value) for value in month.split("-"))
    local = datetime(year, month_number, day, 12, 0, tzinfo=_ZONE)
    return int(local.astimezone(timezone.utc).timestamp())


def test_aggregate_output_contains_frozen_month_horizon_day_and_negative_summaries():
    truths = {}
    predictions = {}
    issues = {}
    for month_index, month in enumerate(DEVELOPMENT_MONTHS):
        base = float(month_index + 1)
        truths[month] = np.asarray(
            [
                [base + h for h in range(len(HORIZONS_MINUTES))],
                [base + 1.0 + h for h in range(len(HORIZONS_MINUTES))],
            ],
            dtype=np.float64,
        )
        predictions[month] = truths[month].copy()
        issues[month] = np.asarray([_issue(month, 18), _issue(month, 19)], dtype=np.int64)
    predictions["2019-01"][0, 0] = -1.0

    summary = _aggregate_single_prediction_set(truths, predictions, issues)

    assert set(summary) == {
        "pooled",
        "by_month",
        "by_horizon",
        "month_horizon",
        "local_day_pooled_over_horizon",
    }
    assert set(summary["month_horizon"]) == set(DEVELOPMENT_MONTHS)
    assert set(summary["month_horizon"]["2019-01"]) == set(HORIZONS_MINUTES)
    assert len(summary["local_day_pooled_over_horizon"]) == 8
    assert summary["pooled"]["negative_prediction_count"] == 1
    assert summary["pooled"]["negative_prediction_fraction"] > 0.0
