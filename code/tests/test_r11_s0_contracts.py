from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from evcf.forecasting.r11_s0_contracts import (
    CONTEXT_LENGTH,
    EXPECTED_TEST_ORIGINS,
    PARAMETER_BAND,
    R11S0ContractError,
    assert_authorized_month,
    assert_test_origin_counts,
    validate_parameter_count,
)
from evcf.forecasting.r11_s0_data import (
    MonthStationView,
    chronological_rows,
    encode_fold,
    issue_calendar_context,
    target_calendar_context,
)

_ZONE = ZoneInfo("America/Los_Angeles")


def _issue(local_text: str) -> int:
    local = datetime.strptime(local_text, "%Y-%m-%d %H:%M").replace(tzinfo=_ZONE)
    return int(local.astimezone(timezone.utc).timestamp())


def _view(month: str, days: range) -> MonthStationView:
    issues = np.asarray([_issue(f"{month}-{day:02d} 12:00") for day in days], dtype=np.int64)
    n = issues.size
    values = np.zeros((n, 201), dtype=np.float64)
    for row in range(n):
        values[row, :CONTEXT_LENGTH] = np.arange(CONTEXT_LENGTH, dtype=np.float64) + row
        values[row, CONTEXT_LENGTH : 2 * CONTEXT_LENGTH] = 1.0
    labels = np.stack(
        [np.arange(1, 6, dtype=np.float64) + row for row in range(n)], axis=0
    )
    return MonthStationView(month, issues, labels, values)


def _views() -> dict[str, MonthStationView]:
    return {
        "2019-01": _view("2019-01", range(1, 20)),
        "2019-04": _view("2019-04", range(1, 20)),
        "2019-07": _view("2019-07", range(1, 20)),
        "2019-10": _view("2019-10", range(1, 20)),
    }


def test_holdout_and_test_identity_fail_closed():
    assert_authorized_month("2019-01")
    with pytest.raises(R11S0ContractError, match="FINAL_HOLDOUT_ACCESS_PROHIBITED"):
        assert_authorized_month("2019-03")
    assert_test_origin_counts(dict(EXPECTED_TEST_ORIGINS))
    wrong = dict(EXPECTED_TEST_ORIGINS)
    wrong["2019-10"] -= 1
    with pytest.raises(R11S0ContractError, match="FROZEN_TEST_ORIGIN_IDENTITY_MISMATCH"):
        assert_test_origin_counts(wrong)


def test_parameter_band_is_frozen():
    validate_parameter_count(PARAMETER_BAND[0])
    validate_parameter_count(PARAMETER_BAND[1])
    with pytest.raises(R11S0ContractError):
        validate_parameter_count(PARAMETER_BAND[0] - 1)
    with pytest.raises(R11S0ContractError):
        validate_parameter_count(PARAMETER_BAND[1] + 1)


def test_chronology_uses_full_history_earlier_months_and_current_day_bands():
    views = _views()
    fold = chronological_rows(views, "2019-07")
    train_months = [month for month, _row in fold.train]
    assert train_months.count("2019-01") == 18
    assert train_months.count("2019-04") == 18
    assert train_months.count("2019-07") == 13
    assert len(fold.validation) == 3
    assert len(fold.test) == 2
    assert all(month == "2019-07" for month, _row in fold.validation + fold.test)


def test_current_month_complete_five_horizon_labels_are_required_before_cutoff():
    views = _views()
    july = views["2019-07"]
    issue_values = [
        *[_issue(f"2019-07-{day:02d} 12:00") for day in range(1, 15)],
        _issue("2019-07-14 23:00"),
        *[_issue(f"2019-07-{day:02d} 12:00") for day in range(15, 18)],
        _issue("2019-07-17 23:00"),
        *[_issue(f"2019-07-{day:02d} 12:00") for day in range(18, 20)],
    ]
    extra_issues = np.asarray(issue_values, dtype=np.int64)
    extra_values = np.vstack([july.m2_values, july.m2_values[-1], july.m2_values[-1]])
    extra_labels = np.vstack([july.labels, july.labels[-1], july.labels[-1]])
    views["2019-07"] = MonthStationView("2019-07", extra_issues, extra_labels, extra_values)
    fold = chronological_rows(views, "2019-07")
    train_issues = {
        int(views[month].issue_times[row])
        for month, row in fold.train
        if month == "2019-07"
    }
    validation_issues = {
        int(views[month].issue_times[row])
        for month, row in fold.validation
        if month == "2019-07"
    }
    assert _issue("2019-07-14 23:00") not in train_issues
    assert _issue("2019-07-17 23:00") not in validation_issues


def test_calendar_context_has_frozen_shapes_and_horizon_code():
    issue = _issue("2019-07-18 12:00")
    assert issue_calendar_context(issue).shape == (5,)
    target = target_calendar_context(issue)
    assert target.shape == (5, 6)
    assert np.allclose(target[:, -1], np.asarray([15, 30, 60, 120, 240]) / 240.0)


def test_encode_fold_uses_train_only_scaling_and_station_channels():
    views = _views()
    encoded = encode_fold(views, "2019-01")
    assert encoded.train_history.shape[1:] == (96, 2)
    assert encoded.validation_target.shape[1] == 5
    assert encoded.test_target_context.shape[1:] == (5, 6)
    assert encoded.train_issue_context.shape[1] == 5
    assert np.isfinite(encoded.train_history).all()
    assert np.isfinite(encoded.validation_history).all()
    assert np.isfinite(encoded.test_history).all()
