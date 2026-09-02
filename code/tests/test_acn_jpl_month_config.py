from __future__ import annotations

import copy
import gzip
import hashlib
import json
import pickle
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import evcf.data.acn_jpl_month_config as month_config_module
import pytest
from evcf.data.acn_jpl_gate0 import LocalDayWindow
from evcf.data.acn_jpl_month_config import (
    EXPECTED_COMPLETE_METADATA_FILE_COUNT,
    EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256,
    EXPECTED_COMPLETE_METADATA_RECORD_COUNT,
    MAY_2019,
    SEASONAL_MONTHS,
    CompleteMetadataError,
    CompleteMetadataSourceEvidence,
    jpl_month_config,
    load_verified_complete_metadata,
    summarize_complete_metadata,
)

ZONE = ZoneInfo("America/Los_Angeles")


def _record(
    index: int,
    connection: datetime,
    disconnect: datetime | None = None,
) -> dict[str, Any]:
    return {
        "_id": f"object-{index}",
        "sessionID": f"session-{index}",
        "connectionTime": connection,
        "disconnectTime": disconnect or connection + timedelta(hours=1),
    }


def _write_test_complete_inventory(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    inventory = hashlib.sha256()
    for index in range(EXPECTED_COMPLETE_METADATA_FILE_COUNT):
        record = _record(
            index,
            MAY_2019.utc_start + timedelta(days=1, minutes=index),
        )
        serializable = {
            **record,
            "connectionTime": format_datetime(record["connectionTime"], usegmt=True),
            "disconnectTime": format_datetime(record["disconnectTime"], usegmt=True),
        }
        data_path = root / f"part-{index:02d}.jsonl.gz"
        with gzip.open(data_path, "wt", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(serializable, sort_keys=True) + "\n")
        raw_sha256 = hashlib.sha256(data_path.read_bytes()).hexdigest()
        manifest = {
            "schema_version": 1,
            "endpoint": "sessions/jpl",
            "site": "jpl",
            "mode": "metadata",
            "record_count": 1,
            "source_total": 1,
            "sha256": raw_sha256,
        }
        data_path.with_name(data_path.name + ".manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        inventory.update(f"{data_path.name}\0{raw_sha256}\0{1}\n".encode())
    return inventory.hexdigest()


def test_seasonal_months_have_fixed_order_and_only_m1_to_m3() -> None:
    assert SEASONAL_MONTHS == ("2019-02", "2019-08", "2019-11")
    assert tuple(jpl_month_config(month).month for month in SEASONAL_MONTHS) == (
        "2019-02",
        "2019-08",
        "2019-11",
    )
    assert all(jpl_month_config(month).tiers == ("M1", "M2", "M3") for month in SEASONAL_MONTHS)


def test_seasonal_month_contracts_use_physical_utc_bins() -> None:
    feb, aug, nov = (jpl_month_config(month) for month in SEASONAL_MONTHS)

    assert feb.local_start.utcoffset() == timedelta(hours=-8)
    assert feb.local_end.utcoffset() == timedelta(hours=-8)
    assert (feb.day_count, feb.expected_bins, feb.expected_scheduled_issue_times) == (
        28,
        2688,
        2577,
    )
    assert aug.local_start.utcoffset() == timedelta(hours=-7)
    assert aug.local_end.utcoffset() == timedelta(hours=-7)
    assert (aug.day_count, aug.expected_bins, aug.expected_scheduled_issue_times) == (
        31,
        2976,
        2865,
    )
    assert (nov.day_count, nov.expected_bins, nov.expected_scheduled_issue_times) == (
        30,
        2884,
        2773,
    )
    assert nov.local_start.utcoffset() == timedelta(hours=-7)
    assert nov.local_end.utcoffset() == timedelta(hours=-8)
    assert nov.utc_end - nov.utc_start == timedelta(hours=721)
    assert nov.grid_policy == "continuous_physical_utc"


@pytest.mark.parametrize("month", (*SEASONAL_MONTHS, "2019-05"))
def test_each_month_uses_half_open_local_boundaries(month: str) -> None:
    config = jpl_month_config(month)
    records = [
        _record(1, config.utc_start),
        _record(2, config.utc_end - timedelta(microseconds=1)),
        _record(3, config.utc_end),
    ]

    scope = summarize_complete_metadata(records, config)

    assert scope.local_month_session_count == 2
    assert {record["sessionID"] for record in scope.local_month_records} == {
        "session-1",
        "session-2",
    }


def test_november_day_windows_preserve_both_fall_back_folds() -> None:
    november = jpl_month_config("2019-11")
    fall_back_day = november.day_windows[2]

    assert len(november.day_windows) == 30
    assert all(isinstance(window, LocalDayWindow) for window in november.day_windows)
    assert fall_back_day.local_start.date().isoformat() == "2019-11-03"
    assert fall_back_day.utc_end - fall_back_day.utc_start == timedelta(hours=25)
    assert november.day_windows[0].local_start == november.local_start
    assert november.day_windows[-1].local_end == november.local_end
    repeated = [
        instant.astimezone(ZONE)
        for instant in (
            datetime(2019, 11, 3, 8, 0, tzinfo=timezone.utc),
            datetime(2019, 11, 3, 9, 0, tzinfo=timezone.utc),
        )
    ]
    assert [(item.hour, item.fold, item.utcoffset()) for item in repeated] == [
        (1, 0, timedelta(hours=-7)),
        (1, 1, timedelta(hours=-8)),
    ]


def test_may_contract_preserves_legacy_bounds_and_physical_grid() -> None:
    may = jpl_month_config("2019-05")

    assert may is MAY_2019
    assert may.timezone_name == "America/Los_Angeles"
    assert may.local_start.isoformat() == "2019-05-01T00:00:00-07:00"
    assert may.local_end.isoformat() == "2019-06-01T00:00:00-07:00"
    assert may.utc_start.isoformat() == "2019-05-01T07:00:00+00:00"
    assert may.utc_end.isoformat() == "2019-06-01T07:00:00+00:00"
    assert (may.day_count, may.expected_bins, may.expected_scheduled_issue_times) == (
        31,
        2976,
        2865,
    )


def test_month_contract_is_frozen_and_rejects_unapproved_months() -> None:
    with pytest.raises(FrozenInstanceError):
        MAY_2019.month = "2019-06"  # type: ignore[misc]
    with pytest.raises(ValueError, match="approved JPL month"):
        jpl_month_config("2019-06")
    with pytest.raises(ValueError, match="YYYY-MM"):
        jpl_month_config("May 2019")


def test_complete_metadata_scope_distinguishes_local_and_utc_months() -> None:
    august = jpl_month_config("2019-08")
    records = [
        _record(1, datetime(2019, 8, 1, 0, 0, tzinfo=timezone.utc)),  # UTC-only left
        _record(2, august.utc_start),  # inclusive local start
        _record(3, datetime(2019, 8, 15, 12, 0, tzinfo=timezone.utc)),
        _record(4, datetime(2019, 9, 1, 0, 0, tzinfo=timezone.utc)),  # local-only right
        _record(5, august.utc_end),  # exclusive local end
        _record(
            6,
            august.utc_start - timedelta(days=2),
            august.utc_start + timedelta(minutes=1),
        ),
        _record(
            7,
            august.utc_start - timedelta(days=1),
            august.utc_start,
        ),
    ]

    scope = summarize_complete_metadata(records, august)

    assert scope.local_month_session_count == 3
    assert scope.utc_month_session_count == 3
    assert scope.left_boundary_count == 1
    assert scope.right_boundary_count == 1
    assert scope.carry_in_session_count == 1
    assert tuple(record["sessionID"] for record in scope.local_month_records) == (
        "session-2",
        "session-3",
        "session-4",
    )
    assert tuple(record["sessionID"] for record in scope.carry_in_records) == ("session-6",)
    assert len(scope.inventory_sha256) == 64
    assert scope.record_inventory_sha256 == scope.inventory_sha256
    assert scope.source_evidence is None
    assert scope.source_inventory_verified is False


@pytest.mark.parametrize("carry_count", [0, 1, 3])
def test_carry_in_uses_strict_half_open_boundary(carry_count: int) -> None:
    february = jpl_month_config("2019-02")
    records = [
        _record(
            index,
            february.utc_start - timedelta(days=index + 1),
            february.utc_start + timedelta(seconds=1),
        )
        for index in range(carry_count)
    ]
    records.extend(
        [
            _record(100, february.utc_start),
            _record(
                101,
                february.utc_start - timedelta(days=1),
                february.utc_start,
            ),
            _record(102, february.utc_end),
        ]
    )

    scope = summarize_complete_metadata(records, february)

    assert scope.local_month_session_count == 1
    assert scope.carry_in_session_count == carry_count


def test_may_scope_preserves_1644_local_1645_utc_and_one_carry_without_constants() -> None:
    local_records = [
        _record(index, datetime(2019, 5, 15, 12, 0, tzinfo=timezone.utc)) for index in range(1644)
    ]
    utc_only = _record(2000, datetime(2019, 5, 1, 0, 0, tzinfo=timezone.utc))
    carry = _record(
        2001,
        MAY_2019.utc_start - timedelta(days=7),
        MAY_2019.utc_start + timedelta(seconds=1),
    )

    scope = summarize_complete_metadata([*local_records, utc_only, carry], MAY_2019)

    assert scope.local_month_session_count == 1644
    assert scope.utc_month_session_count == 1645
    assert scope.left_boundary_count == 1
    assert scope.right_boundary_count == 0
    assert scope.carry_in_session_count == 1


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("_id", None, "_id"),
        ("_id", "", "_id"),
        ("sessionID", None, "sessionID"),
        ("sessionID", "", "sessionID"),
    ],
)
def test_complete_metadata_fails_closed_on_missing_identifiers(
    field: str,
    replacement: object,
    message: str,
) -> None:
    record = _record(1, MAY_2019.utc_start)
    record[field] = replacement

    with pytest.raises(CompleteMetadataError, match=message):
        summarize_complete_metadata([record], MAY_2019)


@pytest.mark.parametrize("field", ["_id", "sessionID"])
def test_complete_metadata_fails_closed_on_duplicate_identifiers(field: str) -> None:
    first = _record(1, MAY_2019.utc_start)
    second = _record(2, MAY_2019.utc_start + timedelta(minutes=1))
    second[field] = first[field]

    with pytest.raises(CompleteMetadataError, match=f"duplicate {field}"):
        summarize_complete_metadata([first, second], MAY_2019)


def test_canonical_inventory_hash_is_order_and_mapping_order_independent() -> None:
    first = _record(1, MAY_2019.utc_start)
    second = _record(2, MAY_2019.utc_start + timedelta(minutes=1))
    reordered_first = dict(reversed(tuple(first.items())))

    forward = summarize_complete_metadata([first, second], MAY_2019)
    reversed_inventory = summarize_complete_metadata([second, reordered_first], MAY_2019)

    assert forward.inventory_sha256 == reversed_inventory.inventory_sha256
    changed = dict(second)
    changed["disconnectTime"] = second["disconnectTime"] + timedelta(seconds=1)
    assert (
        summarize_complete_metadata([first, changed], MAY_2019).inventory_sha256
        != forward.inventory_sha256
    )


def test_production_loader_exposes_frozen_source_contract_and_fails_closed(
    tmp_path: Path,
) -> None:
    assert EXPECTED_COMPLETE_METADATA_FILE_COUNT == 42
    assert EXPECTED_COMPLETE_METADATA_RECORD_COUNT == 33_638
    assert EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256 == (
        "bd15344d22ccc7e6230750e6c0bbba5fa2448b88bf0ebce10eaac3fd63c5a23a"
    )
    evidence = CompleteMetadataSourceEvidence(
        file_count=42,
        valid_manifest_count=42,
        record_count=33_638,
        source_inventory_sha256=EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256,
    )
    assert evidence.source_inventory_sha256 == EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256
    synthetic = summarize_complete_metadata([], MAY_2019)
    assert replace(synthetic, source_evidence=evidence).source_inventory_verified is False

    with pytest.raises(CompleteMetadataError, match="exactly 42"):
        load_verified_complete_metadata(tmp_path, MAY_2019)


def test_verified_scope_is_bound_to_the_exact_summarized_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_digest = _write_test_complete_inventory(tmp_path)
    monkeypatch.setattr(month_config_module, "EXPECTED_COMPLETE_METADATA_RECORD_COUNT", 42)
    monkeypatch.setattr(
        month_config_module,
        "EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256",
        source_digest,
    )
    verified = load_verified_complete_metadata(tmp_path, MAY_2019)

    assert verified.source_inventory_verified is True
    assert verified.is_verified_for(MAY_2019) is True
    assert verified.is_verified_for(jpl_month_config("2019-08")) is False
    assert verified.month == MAY_2019.month
    assert verified.local_start_inclusive == MAY_2019.local_start.isoformat()
    assert verified.local_end_exclusive == MAY_2019.local_end.isoformat()
    assert verified.utc_start_inclusive == MAY_2019.utc_start.isoformat()
    assert verified.utc_end_exclusive == MAY_2019.utc_end.isoformat()
    assert len(verified.config_fingerprint) == 64
    synthetic = summarize_complete_metadata([], MAY_2019)
    assert (
        replace(synthetic, source_evidence=verified.source_evidence).source_inventory_verified
        is False
    )
    assert replace(verified).source_inventory_verified is False
    assert (
        replace(
            verified,
            local_month_session_count=verified.local_month_session_count + 1,
        ).source_inventory_verified
        is False
    )
    assert replace(verified, local_month_records=()).source_inventory_verified is False
    assert replace(verified, record_inventory_sha256="0" * 64).source_inventory_verified is False

    retained_record = verified.local_month_records[0]
    assert isinstance(retained_record, dict)
    retained_record["sessionID"] = "tampered-after-verification"
    assert verified.source_inventory_verified is False


def test_verified_scope_rejects_copy_deepcopy_pickle_and_manual_instances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_digest = _write_test_complete_inventory(tmp_path)
    monkeypatch.setattr(month_config_module, "EXPECTED_COMPLETE_METADATA_RECORD_COUNT", 42)
    monkeypatch.setattr(
        month_config_module,
        "EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256",
        source_digest,
    )
    verified = load_verified_complete_metadata(tmp_path, MAY_2019)
    verifier = getattr(month_config_module, "verify_complete_metadata_scope", None)
    evidence_verifier = getattr(
        month_config_module,
        "verify_complete_metadata_source_evidence",
        None,
    )

    assert callable(verifier)
    assert callable(evidence_verifier)
    assert not hasattr(verified, "__dict__")
    assert verifier(verified, MAY_2019) is True
    assert evidence_verifier(verified.source_evidence) is True
    evidence = verified.source_evidence
    assert evidence is not None
    manual_evidence = CompleteMetadataSourceEvidence(
        file_count=evidence.file_count,
        valid_manifest_count=evidence.valid_manifest_count,
        record_count=evidence.record_count,
        source_inventory_sha256=evidence.source_inventory_sha256,
    )
    object.__setattr__(manual_evidence, "_verification_seal", evidence._verification_seal)
    for copied_evidence in (
        copy.copy(evidence),
        copy.deepcopy(evidence),
        pickle.loads(pickle.dumps(evidence)),
        manual_evidence,
    ):
        assert evidence_verifier(copied_evidence) is False
    for copied in (
        copy.copy(verified),
        copy.deepcopy(verified),
        pickle.loads(pickle.dumps(verified)),
        replace(summarize_complete_metadata([], MAY_2019), source_evidence=verified.source_evidence),
    ):
        assert copied.source_inventory_verified is False
        assert verifier(copied, MAY_2019) is False
    with pytest.raises((AttributeError, TypeError)):
        object.__setattr__(verified, "is_verified_for", lambda _config: True)


def test_production_loader_rejects_replaced_month_config_before_source_scan(
    tmp_path: Path,
) -> None:
    transferred = replace(MAY_2019, month="2019-08")

    assert month_config_module.is_canonical_jpl_month_config(MAY_2019) is True
    assert month_config_module.is_canonical_jpl_month_config(transferred) is False
    with pytest.raises(CompleteMetadataError, match="canonical approved"):
        load_verified_complete_metadata(tmp_path, transferred)
