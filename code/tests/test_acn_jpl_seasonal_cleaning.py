from __future__ import annotations

import copy
import importlib
import math
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any

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


def _seasonal_documents(
    *,
    policy: object | None = None,
    raw_record: dict[str, object] | None = None,
    empty_series: bool = False,
    boundary_points: bool = False,
) -> dict[str, Any]:
    cleaning = importlib.import_module("evcf.data.acn_jpl_cleaning")
    preparation = importlib.import_module("evcf.data.acn_jpl_gate1_prep")
    modes = _modes()
    selected_policy = policy or cleaning.cleaning_policy_from_sampling_modes(modes)
    raw = copy.deepcopy(raw_record) if raw_record is not None else _raw_record()
    if empty_series:
        raw["chargingCurrent"] = {"timestamps": [], "current": []}
        raw["pilotSignal"] = {"timestamps": [], "pilot": []}
    if boundary_points:
        base = datetime(2019, 2, 1, 8, tzinfo=timezone.utc)
        raw["chargingCurrent"] = {
            "timestamps": [_stamp(base, value) for value in (-10, 0, 10, 20, 100)],
            "current": [1.0, 1.0, 2.0, 3.0, 1.0],
        }
    cleaned = clean_session(raw, session_index=0, policy=selected_policy)
    accumulator = preparation.CleaningAccumulator(selected_policy)
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
    return {
        "module": preparation,
        "config": config,
        "modes": modes,
        "policy": selected_policy,
        "cleaning_qa": qa,
        "cleaning_sensitivity": preparation.build_seasonal_cleaning_sensitivity(
            accumulator
        ),
        "boundary_audit": accumulator.boundary_current_audit(),
    }


def _validate(documents: Mapping[str, Any]) -> None:
    documents["module"].validate_seasonal_cleaning_documents(
        cleaning_qa=documents["cleaning_qa"],
        cleaning_sensitivity=documents["cleaning_sensitivity"],
        boundary_audit=documents["boundary_audit"],
        config=documents["config"],
        modes=documents["modes"],
        policy=documents["policy"],
        expected_sessions=1,
    )


def _set_path(root: object, path: tuple[str | int, ...], value: object) -> None:
    target = root
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]


def _leaf_paths(
    value: object,
    predicate: Callable[[object], bool],
    prefix: tuple[str | int, ...] = (),
) -> list[tuple[str | int, ...]]:
    paths: list[tuple[str | int, ...]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            paths.extend(_leaf_paths(child, predicate, (*prefix, str(key))))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            paths.extend(_leaf_paths(child, predicate, (*prefix, index)))
    elif predicate(value):
        paths.append(prefix)
    return paths


def _mutation_is_accepted(
    documents: Mapping[str, Any],
    document_name: str,
    path: tuple[str | int, ...],
    value: object,
) -> bool:
    mutated = dict(documents)
    mutated[document_name] = copy.deepcopy(documents[document_name])
    _set_path(mutated[document_name], path, value)
    try:
        _validate(mutated)
    except (TypeError, ValueError):
        return False
    return True


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
        config=config,
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
            config=config,
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
            config=config,
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
            config=config,
            modes=modes,
            policy=policy,
            expected_sessions=1,
        )


@pytest.mark.parametrize(
    "field",
    (
        "month",
        "timezone",
        "local_start_inclusive",
        "local_end_exclusive",
        "utc_start_inclusive",
        "utc_end_exclusive",
    ),
)
def test_validator_binds_every_analysis_window_field_to_canonical_config(
    field: str,
) -> None:
    documents = _seasonal_documents()
    documents["cleaning_qa"]["analysis_window"][field] = "wrong"

    with pytest.raises(ValueError, match="analysis window"):
        _validate(documents)


def test_validator_rejects_a_noncanonical_or_nonseasonal_month_config() -> None:
    documents = _seasonal_documents()
    documents["config"] = replace(documents["config"], month="2019-08")
    with pytest.raises(ValueError, match="canonical seasonal month"):
        _validate(documents)

    documents = _seasonal_documents()
    documents["config"] = jpl_month_config("2019-05")
    with pytest.raises(ValueError, match="canonical seasonal month"):
        _validate(documents)


@pytest.mark.parametrize(
    "policy_change",
    (
        {"locf_mode_multiplier": 4},
        {"locf_cap_s": 120},
        {"boundary_sensitivity_s": 90},
        {
            "locf_mode_multiplier": 4,
            "locf_cap_s": 120,
            "boundary_sensitivity_s": 90,
        },
    ),
)
def test_validator_rejects_nonfrozen_policy_even_when_documents_are_self_consistent(
    policy_change: dict[str, int],
) -> None:
    cleaning = importlib.import_module("evcf.data.acn_jpl_cleaning")
    policy = cleaning.CleaningPolicy(
        current_mode_s=10,
        pilot_mode_s=30,
        **policy_change,
    )
    documents = _seasonal_documents(policy=policy)

    with pytest.raises(ValueError, match="fixed 3x/60s/60s policy"):
        _validate(documents)


def test_zero_denominators_use_only_the_declared_null_or_zero_conventions() -> None:
    documents = _seasonal_documents(empty_series=True)

    _validate(documents)

    assert documents["cleaning_qa"]["current"]["retained_sample_rate"] is None
    assert documents["cleaning_sensitivity"]["last_write_wins"]["current"][
        "relative_value_hours_change"
    ] is None
    assert documents["boundary_audit"]["current_integral_share"] == 0.0


def test_signed_boundary_distribution_with_positive_points_is_valid() -> None:
    documents = _seasonal_documents(boundary_points=True)

    _validate(documents)

    distribution = documents["boundary_audit"]["signed_distance_seconds"]
    assert distribution["count"] == 2
    assert distribution["minimum"] < 0 < distribution["maximum"]


def test_retained_samples_respect_the_cleaner_duplicate_conflict_upper_bound() -> None:
    raw = _raw_record()
    base = datetime(2019, 2, 1, 8, tzinfo=timezone.utc)
    raw["chargingCurrent"] = {
        "timestamps": [
            _stamp(base, 0),
            _stamp(base, 0),
            _stamp(base, 10),
            _stamp(base, 10),
            _stamp(base, 10),
            _stamp(base, 20),
            "not-a-timestamp",
            _stamp(base, 30),
            _stamp(base, 100),
        ],
        "current": [1.0, 1.0, 2.0, 2.0, 3.0, 4.0, 5.0, "bad", 6.0],
    }
    documents = _seasonal_documents(raw_record=raw)
    produced = documents["cleaning_qa"]["current"]

    _validate(documents)
    assert {
        name: produced[name]
        for name in (
            "raw_samples",
            "retained_samples",
            "invalid_timestamps",
            "invalid_values",
            "exact_duplicate_extras",
            "conflicting_timestamps",
        )
    } == {
        "raw_samples": 9,
        "retained_samples": 2,
        "invalid_timestamps": 1,
        "invalid_values": 1,
        "exact_duplicate_extras": 2,
        "conflicting_timestamps": 1,
    }

    produced["retained_samples"] = 4
    produced["retained_sample_rate"] = 4 / 9
    with pytest.raises(ValueError, match="counts are inconsistent"):
        _validate(documents)


def test_user_input_counts_form_the_exact_cleaner_partition() -> None:
    documents = _seasonal_documents()
    produced = documents["cleaning_qa"]["user_inputs"]

    _validate(documents)
    assert produced["sanitized_revision_count"] + produced[
        "unparseable_modified_count"
    ] == produced["raw_revision_count"]

    produced["raw_revision_count"] = 2
    with pytest.raises(ValueError, match="user-input truncation"):
        _validate(documents)


def test_negative_pilot_value_hours_produced_by_the_cleaner_are_valid() -> None:
    raw = _raw_record()
    raw["pilotSignal"]["pilot"] = [-6.0, -6.0, -6.0]  # type: ignore[index]
    documents = _seasonal_documents(raw_record=raw)

    _validate(documents)

    assert documents["cleaning_qa"]["pilot"]["bounded_value_hours"] < 0
    assert all(
        report["value_hours"] < 0
        for report in documents["cleaning_sensitivity"]["hold_thresholds"][
            "pilot"
        ].values()
    )
    assert documents["cleaning_sensitivity"]["last_write_wins"]["pilot"][
        "value_hours"
    ] < 0
    assert documents["cleaning_sensitivity"]["boundary_plus_minus_60_seconds"][
        "pilot"
    ]["value_hours"] < 0


def test_every_statistical_leaf_rejects_nonfinite_or_wrong_types() -> None:
    documents = _seasonal_documents()
    accepted: list[str] = []
    for document_name in ("cleaning_qa", "cleaning_sensitivity", "boundary_audit"):
        document = documents[document_name]
        numeric_paths = _leaf_paths(
            document,
            lambda value: (
                value is None
                or (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                )
            ),
        )
        boolean_paths = _leaf_paths(document, lambda value: isinstance(value, bool))
        for path in numeric_paths:
            for invalid in ("not-numeric", True, math.nan, math.inf):
                if _mutation_is_accepted(documents, document_name, path, invalid):
                    accepted.append(f"{document_name}:{path!r}={invalid!r}")
        for path in boolean_paths:
            if _mutation_is_accepted(documents, document_name, path, 1):
                accepted.append(f"{document_name}:{path!r}=1")

    assert accepted == []


def test_every_unsigned_statistical_leaf_rejects_negative_values() -> None:
    documents = _seasonal_documents()
    accepted: list[str] = []
    for document_name in ("cleaning_qa", "cleaning_sensitivity", "boundary_audit"):
        document = documents[document_name]
        numeric_paths = _leaf_paths(
            document,
            lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
        )
        for path in numeric_paths:
            signed_pilot_value_hours = "pilot" in path and path[-1] in (
                "bounded_value_hours",
                "value_hours",
            )
            if (
                "signed_distance_seconds" in path
                or path[-1] == "relative_value_hours_change"
                or signed_pilot_value_hours
            ):
                continue
            current = document
            for part in path:
                current = current[part]  # type: ignore[index]
            invalid = -1 if isinstance(current, int) else -0.5
            if _mutation_is_accepted(documents, document_name, path, invalid):
                accepted.append(f"{document_name}:{path!r}")

    assert accepted == []


@pytest.mark.parametrize(
    ("document_name", "path", "invalid"),
    (
        ("cleaning_qa", ("current", "exact_duplicate_extras"), "1"),
        ("cleaning_qa", ("current", "conflicting_timestamps"), -1),
        ("cleaning_qa", ("user_inputs",), None),
        ("cleaning_qa", ("user_inputs", "raw_revision_count"), None),
        (
            "cleaning_sensitivity",
            ("hold_thresholds", "current", "10", "coverage"),
            "0.5",
        ),
        (
            "cleaning_sensitivity",
            ("hold_thresholds", "current", "10", "coverage"),
            None,
        ),
        (
            "cleaning_sensitivity",
            ("hold_thresholds", "current", "10", "value_hours"),
            "0.1",
        ),
        (
            "cleaning_sensitivity",
            ("hold_thresholds", "current", "10", "value_hours"),
            None,
        ),
        ("boundary_audit", ("positive_points_excluded",), -1),
        ("boundary_audit", ("positive_points_excluded",), None),
        ("boundary_audit", ("current_integral_share",), -0.1),
        ("boundary_audit", ("current_integral_share",), None),
    ),
)
def test_required_spec_mutations_fail_closed(
    document_name: str,
    path: tuple[str | int, ...],
    invalid: object,
) -> None:
    documents = _seasonal_documents()

    assert not _mutation_is_accepted(documents, document_name, path, invalid)


@pytest.mark.parametrize(
    ("document_name", "path", "invalid"),
    (
        ("cleaning_qa", ("current", "retained_samples"), 4),
        ("cleaning_qa", ("current", "retained_sample_rate"), 0.5),
        ("cleaning_qa", ("current", "invalid_timestamps"), 4),
        ("cleaning_qa", ("current", "conflict_affected_sessions"), 1),
        ("cleaning_qa", ("user_inputs", "sanitized_revision_count"), 2),
        ("cleaning_qa", ("retrospective_done_time", "parsed_count"), 0),
        ("cleaning_qa", ("sampling_interval", "current_positive_delta_count"), 3),
        (
            "cleaning_qa",
            ("sampling_interval", "current_distinct_positive_delta_count"),
            2,
        ),
        (
            "cleaning_qa",
            ("sampling_interval", "current_top_delta_counts"),
            [[11, 2]],
        ),
        ("cleaning_qa", ("current", "bounded_observation_coverage"), 0.0),
        (
            "cleaning_sensitivity",
            ("hold_thresholds", "current", "10", "observed_seconds"),
            91,
        ),
        (
            "cleaning_sensitivity",
            ("hold_thresholds", "current", "30", "coverage"),
            0.5,
        ),
        (
            "cleaning_sensitivity",
            ("last_write_wins", "current", "relative_value_hours_change"),
            0.25,
        ),
        ("boundary_audit", ("signed_distance_seconds", "count"), 1),
        ("boundary_audit", ("before_connection_count",), 1),
        ("boundary_audit", ("sessions_affected",), 1),
        ("boundary_audit", ("current_integral_share",), 0.5),
        ("boundary_audit", ("excluded_positive_ampere_seconds",), 999.0),
    ),
)
def test_provable_cross_relations_fail_closed(
    document_name: str,
    path: tuple[str | int, ...],
    invalid: object,
) -> None:
    documents = _seasonal_documents()

    assert not _mutation_is_accepted(documents, document_name, path, invalid)
