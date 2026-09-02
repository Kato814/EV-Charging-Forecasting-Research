from __future__ import annotations

import copy
import importlib
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
from evcf.data.acn_jpl_cleaning import (
    SamplingMode,
    SamplingModes,
    clean_session,
)
from evcf.data.acn_jpl_month_config import jpl_month_config


def _stamp(base: datetime, seconds: int) -> str:
    return format_datetime(base + timedelta(seconds=seconds), usegmt=True)


def _raw_record() -> dict[str, object]:
    base = datetime(2019, 2, 1, 8, tzinfo=timezone.utc)
    return {
        "connectionTime": _stamp(base, 0),
        "disconnectTime": _stamp(base, 90),
        "spaceID": "AG-1F01",
        "chargingCurrent": {
            "timestamps": [_stamp(base, value) for value in (0, 10, 20)],
            "current": [1.0, 2.0, 3.0],
        },
        "pilotSignal": {
            "timestamps": [_stamp(base, value) for value in (0, 30, 60)],
            "pilot": [6.0, 6.0, 6.0],
        },
        "doneChargingTime": _stamp(base, 80),
        "kWhDelivered": 0.5,
        "userInputs": [
            {
                "modifiedAt": _stamp(base, 5),
                "requestedDeparture": _stamp(base, 3600),
                "kWhRequested": 1.0,
            }
        ],
    }


def _modes(current: int = 10, pilot: int = 30) -> SamplingModes:
    return SamplingModes(
        current=SamplingMode("chargingCurrent", current, 2, ((current, 2),)),
        pilot=SamplingMode("pilotSignal", pilot, 2, ((pilot, 2),)),
    )


def test_policy_uses_each_month_mode_and_caps_each_hold_independently() -> None:
    module = importlib.import_module("evcf.data.acn_jpl_cleaning")

    policy = module.cleaning_policy_from_sampling_modes(_modes())

    assert policy.current_mode_s == 10
    assert policy.pilot_mode_s == 30
    assert policy.hold_cap_for("chargingCurrent") == 30
    assert policy.hold_cap_for("pilotSignal") == 60
    assert policy.boundary_sensitivity_s == 60


def test_optional_may_mode_requirement_does_not_freeze_seasonal_modes() -> None:
    module = importlib.import_module("evcf.data.acn_jpl_cleaning")

    assert module.cleaning_policy_from_sampling_modes(_modes()).current_mode_s == 10
    with pytest.raises(ValueError, match="audited 4-second modes"):
        module.cleaning_policy_from_sampling_modes(_modes(), required_mode_seconds=4)

    may = module.cleaning_policy_from_sampling_modes(
        _modes(current=4, pilot=4),
        required_mode_seconds=4,
    )
    assert may.to_local_dict() == {
        "current_mode_s": 4,
        "pilot_mode_s": 4,
        "locf_mode_multiplier": 3,
        "locf_cap_s": 60,
        "boundary_sensitivity_s": 60,
    }


def test_seasonal_cleaning_documents_are_closed_and_raw_is_unchanged() -> None:
    cleaning = importlib.import_module("evcf.data.acn_jpl_cleaning")
    preparation = importlib.import_module("evcf.data.acn_jpl_gate1_prep")
    modes = _modes()
    policy = cleaning.cleaning_policy_from_sampling_modes(modes)
    raw = _raw_record()
    before = copy.deepcopy(raw)
    cleaned = clean_session(raw, session_index=0, policy=policy)
    accumulator = preparation.CleaningAccumulator(policy)
    accumulator.add(cleaned, raw)
    config = jpl_month_config("2019-02")

    qa = preparation.build_cleaning_qa(
        accumulator,
        modes=modes,
        expected_sessions=1,
        analysis_window={
            "month": config.month,
            "timezone": config.timezone_name,
            "local_start_inclusive": config.local_start.isoformat(),
            "local_end_exclusive": config.local_end.isoformat(),
            "utc_start_inclusive": config.utc_start.isoformat(),
            "utc_end_exclusive": config.utc_end.isoformat(),
        },
    )
    sensitivity = preparation.build_seasonal_cleaning_sensitivity(accumulator)
    boundary = accumulator.boundary_current_audit()
    preparation.validate_seasonal_cleaning_documents(
        cleaning_qa=qa,
        cleaning_sensitivity=sensitivity,
        boundary_audit=boundary,
        modes=modes,
        policy=policy,
        expected_sessions=1,
    )

    assert raw == before
    assert qa["sampling_interval"]["main_current_hold_seconds"] == 30
    assert qa["sampling_interval"]["main_pilot_hold_seconds"] == 60
    assert sensitivity["main_hold_seconds"] == {"current": 30, "pilot": 60}
    assert sensitivity["hold_thresholds_seconds"] == {
        "current": [10, 30, 60],
        "pilot": [30, 60],
    }
    assert set(qa) == {
        "schema_version",
        "status",
        "sessions_processed",
        "expected_sessions",
        "timezone_policy",
        "interval_rule",
        "sampling_interval",
        "duplicate_policy",
        "current",
        "pilot",
        "user_inputs",
        "retrospective_done_time",
        "raw_modified",
        "analysis_window",
    }

    malformed = copy.deepcopy(qa)
    malformed["unexpected"] = 1
    with pytest.raises(ValueError, match="unexpected fields"):
        preparation.validate_seasonal_cleaning_documents(
            cleaning_qa=malformed,
            cleaning_sensitivity=sensitivity,
            boundary_audit=boundary,
            modes=modes,
            policy=policy,
            expected_sessions=1,
        )

    nested_malformed = copy.deepcopy(qa)
    nested_malformed["timezone_policy"]["private_extra"] = True
    with pytest.raises(ValueError, match="unexpected fields"):
        preparation.validate_seasonal_cleaning_documents(
            cleaning_qa=nested_malformed,
            cleaning_sensitivity=sensitivity,
            boundary_audit=boundary,
            modes=modes,
            policy=policy,
            expected_sessions=1,
        )

    sensitivity_malformed = copy.deepcopy(sensitivity)
    sensitivity_malformed["last_write_wins"]["current"]["private_extra"] = True
    with pytest.raises(ValueError, match="unexpected fields"):
        preparation.validate_seasonal_cleaning_documents(
            cleaning_qa=qa,
            cleaning_sensitivity=sensitivity_malformed,
            boundary_audit=boundary,
            modes=modes,
            policy=policy,
            expected_sessions=1,
        )
