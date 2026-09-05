from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any

import pytest
from evcf.data.acn_jpl_cleaning import (
    CleaningPolicy,
    _audit_digest,
    clean_session,
    derive_sampling_modes,
)

BASE = datetime(2019, 2, 1, 8, tzinfo=timezone.utc)
POLICY = CleaningPolicy(current_mode_s=4, pilot_mode_s=4)


def _stamp(seconds: int) -> str:
    return format_datetime(BASE + timedelta(seconds=seconds), usegmt=True)


def _record() -> dict[str, Any]:
    return {
        "_id": "synthetic-object",
        "sessionID": "synthetic-session",
        "siteID": "synthetic-site",
        "stationID": "synthetic-station",
        "spaceID": "synthetic-space",
        "clusterID": "synthetic-cluster",
        "timezone": "America/Los_Angeles",
        "connectionTime": _stamp(0),
        "disconnectTime": _stamp(900),
        "doneChargingTime": _stamp(450),
        "kWhDelivered": 2.5,
        "chargingCurrent": {
            "timestamps": [_stamp(0), _stamp(4), _stamp(8)],
            "current": [1.0, 2.0, 3.0],
        },
        "pilotSignal": {
            "timestamps": [_stamp(0), _stamp(4), _stamp(8)],
            "pilot": [6.0, 6.0, 6.0],
        },
        "userInputs": [
            {
                "modifiedAt": _stamp(1),
                "requestedDeparture": _stamp(800),
                "kWhRequested": 4.0,
            }
        ],
    }


def _metadata(record: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy({
        key: value
        for key, value in record.items()
        if key not in {"chargingCurrent", "pilotSignal"}
    })


def _module() -> Any:
    name = "evcf.data.acn_jpl_invalid_containers"
    assert importlib.util.find_spec(name) is not None, "branchwise cleaner is not implemented"
    return importlib.import_module(name)


@pytest.mark.parametrize(
    ("container", "valid"),
    [
        (None, False),
        ([], False),
        ({}, False),
        ({"timestamps": [], "current": []}, True),
        ({"timestamps": ["bad"], "current": ["bad"]}, True),
        ({"timestamps": [_stamp(0)], "current": []}, False),
        ({"timestamps": (_stamp(0),), "current": [1.0]}, False),
        ({"timestamps": [_stamp(0)], "current": None}, False),
    ],
)
def test_container_contract_matches_existing_cleaner_shapes(
    container: object, valid: bool
) -> None:
    module = _module()
    assert module.series_container_valid({"chargingCurrent": container}, "chargingCurrent") is valid


@pytest.mark.parametrize("invalid_branches", [("current",), ("pilot",), ("current", "pilot")])
def test_invalid_branches_retain_complete_structure_and_other_branch(
    invalid_branches: tuple[str, ...]
) -> None:
    module = _module()
    raw = _record()
    expected = _metadata(raw)
    original = clean_session(raw, session_index=7, policy=POLICY)
    for branch in invalid_branches:
        raw["chargingCurrent" if branch == "current" else "pilotSignal"] = None
    before = copy.deepcopy(raw)

    cleaned = module.clean_branchwise_session(
        raw, expected_metadata=expected, session_index=7, policy=POLICY
    )

    assert raw == before
    structural = {key: value for key, value in cleaned.to_local_dict().items()
                  if key not in {"current", "pilot"}}
    assert structural == {key: value for key, value in original.to_local_dict().items()
                          if key not in {"current", "pilot"}}
    for branch in ("current", "pilot"):
        result = getattr(cleaned, branch)
        if branch not in invalid_branches:
            assert result == getattr(original, branch)
            continue
        assert result.timestamps_utc_s == result.values == result.raw_ordinals == ()
        assert result.main_points() == result.sensitivity_points() == ()
        assert result.boundary_positive_points == ()
        assert result.main_integral.observed_seconds == 0
        assert result.main_integral.eligible_seconds == 900
        assert result.main_integral.coverage == 0.0
        assert result.main_integral.contributions == ()


@pytest.mark.parametrize("source", ["raw", "official"])
@pytest.mark.parametrize(
    ("field", "replacement", "code"),
    [
        ("_id", None, "STRUCTURAL_METADATA_IDENTITY_INVALID"),
        ("sessionID", "different-session", "STRUCTURAL_METADATA_IDENTITY_MISMATCH"),
        ("connectionTime", None, "STRUCTURAL_METADATA_BOUNDS_INVALID"),
        ("disconnectTime", "bad-time", "STRUCTURAL_METADATA_BOUNDS_INVALID"),
        ("connectionTime", "2019-02-01T08:00:00", "STRUCTURAL_METADATA_BOUNDS_INVALID"),
        ("disconnectTime", _stamp(-4), "STRUCTURAL_METADATA_BOUNDS_INVALID"),
        ("disconnectTime", _stamp(0), "STRUCTURAL_METADATA_BOUNDS_INVALID"),
        ("disconnectTime", _stamp(904), "STRUCTURAL_METADATA_BOUNDS_MISMATCH"),
        ("stationID", "different-station", "STRUCTURAL_METADATA_FIELDS_MISMATCH"),
    ],
)
def test_bad_structural_metadata_stops_before_invalid_placeholders(
    source: str, field: str, replacement: object, code: str
) -> None:
    module = _module()
    raw = _record()
    expected = _metadata(raw)
    raw["chargingCurrent"] = None
    (raw if source == "raw" else expected)[field] = replacement

    with pytest.raises(ValueError) as captured:
        module.clean_branchwise_session(
            raw, expected_metadata=expected, session_index=0, policy=POLICY
        )

    assert str(captured.value) == code
    assert captured.value.__suppress_context__ or captured.value.__context__ is None


def test_metadata_bounds_compare_normalized_utc_and_preserve_input_encoding() -> None:
    module = _module()
    raw = _record()
    expected = _metadata(raw)
    raw["connectionTime"] = "2019-02-01T00:00:00-08:00"
    raw["disconnectTime"] = "2019-02-01T00:15:00-08:00"

    assert module.verify_structural_metadata(raw, expected) is None
    assert module.clean_branchwise_session(
        raw, expected_metadata=expected, session_index=0, policy=POLICY
    ).to_local_dict() == clean_session(raw, session_index=0, policy=POLICY).to_local_dict()


def test_missing_official_record_cannot_retain_structure() -> None:
    module = _module()
    with pytest.raises(ValueError, match="^STRUCTURAL_METADATA_MISSING$"):
        module.verify_structural_metadata(_record(), None)


def test_valid_record_uses_exact_original_cleaning_semantics() -> None:
    module = _module()
    raw = _record()
    raw["chargingCurrent"] = {
        "timestamps": [_stamp(-4), _stamp(0), _stamp(0), _stamp(4), _stamp(4), _stamp(8)],
        "current": [3.0, 1.0, 1.0, 2.0, 3.0, -1.0],
    }
    expected = _metadata(raw)

    assert module.clean_branchwise_session(
        raw, expected_metadata=expected, session_index=0, policy=POLICY
    ).to_local_dict() == clean_session(raw, session_index=0, policy=POLICY).to_local_dict()


def test_measured_zero_remains_observed_while_empty_and_invalid_are_unobserved() -> None:
    module = _module()
    raw = _record()
    raw["chargingCurrent"]["current"] = [0.0, 0.0, 0.0]
    expected = _metadata(raw)
    measured = module.clean_branchwise_session(
        raw, expected_metadata=expected, session_index=0, policy=POLICY
    )
    raw["chargingCurrent"] = {"timestamps": [], "current": []}
    empty = module.clean_branchwise_session(
        raw, expected_metadata=expected, session_index=0, policy=POLICY
    )
    raw["chargingCurrent"] = None
    invalid = module.clean_branchwise_session(
        raw, expected_metadata=expected, session_index=0, policy=POLICY
    )

    assert measured.current.main_integral.observed_seconds == 20
    assert measured.current.values == (0.0, 0.0, 0.0)
    assert empty.current.main_integral.observed_seconds == 0
    assert invalid.current.main_integral.observed_seconds == 0
    assert empty.current.values == invalid.current.values == ()


def test_sampling_masks_only_invalid_branch_before_counting_deltas() -> None:
    module = _module()
    complete = _record()
    invalid_current = _record()
    invalid_current["chargingCurrent"] = {
        "timestamps": [_stamp(index) for index in range(10)], "current": [],
    }
    invalid_current["pilotSignal"] = {
        "timestamps": [_stamp(0), _stamp(8), _stamp(16), _stamp(24)],
        "pilot": [6.0] * 4,
    }
    before = copy.deepcopy(invalid_current)
    projected = module.valid_series_record_for_sampling(invalid_current)
    modes = derive_sampling_modes([complete, projected])

    assert invalid_current == before
    assert projected is not invalid_current
    assert projected["chargingCurrent"] == {"timestamps": [], "current": []}
    assert projected["pilotSignal"] == before["pilotSignal"]
    assert modes.current.delta_histogram == ((4, 2),)
    assert modes.pilot.delta_histogram == ((4, 2), (8, 3))
    assert modes.current.mode_seconds == 4
    assert modes.pilot.mode_seconds == 8


def test_invalid_arrays_retain_original_hashes_without_constructing_raw_pairs() -> None:
    module = _module()
    raw = _record()
    raw["chargingCurrent"] = {
        "timestamps": [_stamp(0), _stamp(4), _stamp(8)],
        "current": [1.0, 2.0],
        "shape_context": "synthetic",
    }
    expected = _metadata(raw)
    before_bytes = json.dumps(raw, sort_keys=True).encode()
    cleaned = module.clean_branchwise_session(
        raw, expected_metadata=expected, session_index=0, policy=POLICY
    )
    audit = cleaned.current.audit

    assert audit.raw_samples == 2
    assert audit.raw_order_sha256 == _audit_digest(raw["chargingCurrent"]["timestamps"])
    assert audit.raw_values_sha256 == _audit_digest(raw["chargingCurrent"]["current"])
    assert audit.raw_pairs_sha256 == _audit_digest([
        {"invalid_container": raw["chargingCurrent"], "field_present": True}
    ])
    assert audit.raw_pairs_sha256 != _audit_digest(zip(
        raw["chargingCurrent"]["timestamps"], raw["chargingCurrent"]["current"]
    ))
    assert hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).digest() == (
        hashlib.sha256(before_bytes).digest()
    )


def test_missing_null_and_malformed_raw_containers_have_distinct_provenance() -> None:
    module = _module()
    raw = _record()
    expected = _metadata(raw)
    digests = []
    for value in [None, 3.0, [], {"timestamps": [], "current": None}]:
        raw["chargingCurrent"] = value
        cleaned = module.clean_branchwise_session(
            raw, expected_metadata=expected, session_index=0, policy=POLICY
        )
        digests.append(cleaned.current.audit.raw_pairs_sha256)
    del raw["chargingCurrent"]
    cleaned = module.clean_branchwise_session(
        raw, expected_metadata=expected, session_index=0, policy=POLICY
    )
    digests.append(cleaned.current.audit.raw_pairs_sha256)

    assert len(set(digests)) == 5
