from __future__ import annotations

import gzip
import hashlib
import importlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest
from evcf.data.acn_api import ACNQuery
from evcf.data.acn_jpl_full_month_ts import FULL_MONTH_DATASET_ID
from evcf.data.acn_jpl_gate0 import (
    ACN_OFFICIAL_SOURCE,
    JPL_ANALYSIS_START,
    JPL_DAILY_DATASET_ID,
    JPL_TIMEZONE,
    chunk_paths,
    jpl_analysis_windows,
)


def _gzip_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with (
        path.open("wb") as raw_handle,
        gzip.GzipFile(fileobj=raw_handle, mode="wb", mtime=0) as zipped,
    ):
        for record in records:
            zipped.write(
                (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
            )


def _stamp(value: datetime) -> str:
    return format_datetime(value.astimezone(timezone.utc), usegmt=True)


def _record(index: int, *, connection: datetime, disconnect: datetime) -> dict[str, object]:
    return {
        "_id": f"fixture-object-{index:04d}",
        "sessionID": f"fixture-session-{index:04d}",
        "connectionTime": _stamp(connection),
        "disconnectTime": _stamp(disconnect),
    }


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _synthetic_raw_root(tmp_path: Path) -> Path:
    raw_root = tmp_path / "synthetic-raw"
    next_index = 1
    windows = list(jpl_analysis_windows())
    for day_index, window in enumerate(windows):
        count = 1614 if day_index == 0 else 1
        records = []
        for _ in range(count):
            connection = window.utc_start + timedelta(hours=1)
            records.append(
                _record(
                    next_index,
                    connection=connection,
                    disconnect=connection + timedelta(hours=1),
                )
            )
            next_index += 1
        data_path, manifest_path = chunk_paths(raw_root, "timeseries", window)
        _gzip_jsonl(data_path, records)
        query = ACNQuery(
            site="jpl",
            start=window.local_start,
            end=window.local_end,
            timeseries=True,
        )
        _write_manifest(
            manifest_path,
            {
                "schema_version": "acn-jpl-daily-chunk/v1",
                "dataset_id": JPL_DAILY_DATASET_ID,
                "source": ACN_OFFICIAL_SOURCE,
                "site": "jpl",
                "timezone": JPL_TIMEZONE,
                "local_start_inclusive": window.local_start.isoformat(),
                "local_end_exclusive": window.local_end.isoformat(),
                "utc_start_inclusive": window.utc_start.isoformat(),
                "utc_end_exclusive": window.utc_end.isoformat(),
                "query_condition": query.condition,
                "endpoint": query.endpoint,
                "output_file": data_path.name,
                "record_count": count,
                "remote_total_reported": count,
                "complete_for_query": True,
                "downloaded_at_utc": "2019-06-02T00:00:00+00:00",
                "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
                "token_stored": False,
            },
        )

    carry_connection = JPL_ANALYSIS_START.astimezone(timezone.utc) - timedelta(minutes=30)
    carry_disconnect = JPL_ANALYSIS_START.astimezone(timezone.utc) + timedelta(minutes=30)
    carry_record = _record(
        0,
        connection=carry_connection,
        disconnect=carry_disconnect,
    )
    carry_data = raw_root / "timeseries" / "carry_in" / "carry_in.jsonl.gz"
    carry_manifest = raw_root / "manifests" / "carry_in" / "carry_in.manifest.json"
    _gzip_jsonl(carry_data, [carry_record])
    carry_query = ACNQuery(
        site="jpl",
        start=carry_connection,
        end=JPL_ANALYSIS_START,
        timeseries=True,
        session_id=str(carry_record["sessionID"]),
    )
    _write_manifest(
        carry_manifest,
        {
            "schema_version": "acn-jpl-full-month-carry-in/v1",
            "dataset_id": FULL_MONTH_DATASET_ID,
            "source": ACN_OFFICIAL_SOURCE,
            "endpoint": carry_query.endpoint,
            "site": "jpl",
            "timezone": JPL_TIMEZONE,
            "local_start_inclusive": carry_query.start_utc.astimezone(
                JPL_ANALYSIS_START.tzinfo
            ).isoformat(),
            "local_end_exclusive": JPL_ANALYSIS_START.isoformat(),
            "utc_start_inclusive": carry_query.start_utc.isoformat(),
            "utc_end_exclusive": carry_query.end_utc.isoformat(),
            "_id": carry_record["_id"],
            "sessionID": carry_record["sessionID"],
            "query_condition": carry_query.condition,
            "output_file": carry_data.name,
            "record_count": 1,
            "remote_total_reported": 1,
            "complete_for_query": True,
            "downloaded_at_utc": "2019-06-02T00:00:00+00:00",
            "sha256": hashlib.sha256(carry_data.read_bytes()).hexdigest(),
            "token_stored": False,
        },
    )
    state = raw_root / "state" / "acquisition.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}\n", encoding="utf-8")
    logs = raw_root / "logs"
    logs.mkdir()
    (logs / "first.log").write_text("{}\n", encoding="utf-8")
    (logs / "second.log").write_text("{}\n", encoding="utf-8")
    return raw_root


def _fixture_contract(module: object, raw_root: Path, *, pin_digest: bool = True) -> object:
    snapshot = module.canonical_inventory(raw_root)  # type: ignore[attr-defined]
    return replace(
        module.FROZEN_RAW_CONTRACT,  # type: ignore[attr-defined]
        total_bytes=snapshot.total_bytes if pin_digest else None,
        inventory_sha256=snapshot.digest if pin_digest else None,
    )


def _safe_public_contents(module: object) -> dict[str, bytes | str]:
    contents: dict[str, bytes | str] = {}
    for name in module.PUBLIC_ARTIFACT_NAMES:  # type: ignore[attr-defined]
        if name.endswith(".json"):
            contents[name] = '{"schema_version":"aggregate/v1"}\n'
        elif name.endswith(".csv"):
            contents[name] = "count\n0\n"
        elif name.endswith((".yaml", ".yml")):
            contents[name] = "allowed_fields: []\n"
        elif name.endswith(".md"):
            contents[name] = "Aggregate-only report.\n"
        else:
            contents[name] = ""
    return contents


def test_inventory_digest_uses_canonical_relative_path_size_and_hash(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "β.txt").write_bytes("充电".encode())
    (tmp_path / "z.bin").write_bytes(b"z")

    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    snapshot = module.canonical_inventory(tmp_path)

    rows = []
    for relative_path, data in (("nested/β.txt", "充电".encode()), ("z.bin", b"z")):
        rows.append(f"{relative_path}\t{len(data)}\t{hashlib.sha256(data).hexdigest()}\n")
    expected_payload = "".join(rows).encode("utf-8")

    assert snapshot.file_count == 2
    assert snapshot.total_bytes == len("充电".encode()) + 1
    assert [entry.relative_path for entry in snapshot.entries] == ["nested/β.txt", "z.bin"]
    assert snapshot.digest == hashlib.sha256(expected_payload).hexdigest()
    assert snapshot.algorithm == (
        "sha256(ordinal-sorted UTF-8 relative_path<TAB>size<TAB>file_sha256<LF>; final LF)"
    )


def test_raw_snapshot_validates_closed_counts_and_full_month_manifests(tmp_path: Path) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    raw_root = _synthetic_raw_root(tmp_path)

    result = module.validate_raw_snapshot(
        raw_root,
        contract=_fixture_contract(module, raw_root),
    )

    assert result.inventory.file_count == 67
    assert result.manifest_count == 32
    assert result.day_count == 31
    assert result.carry_count == 1
    assert result.day_record_count == 1644
    assert result.carry_record_count == 1
    assert result.total_record_count == 1645


def test_validated_raw_iterator_is_carry_first_then_ordinal_day_order(tmp_path: Path) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    raw_root = _synthetic_raw_root(tmp_path)
    contract = _fixture_contract(module, raw_root)

    records = list(module.iter_validated_raw_records(raw_root, contract=contract))

    assert len(records) == 1645
    assert records[0].ordinal == 0
    assert records[0].chunk_kind == "carry_in"
    assert records[0].local_date is None
    assert records[1].ordinal == 1
    assert records[1].chunk_kind == "day"
    assert records[1].local_date == "2019-05-01"
    assert records[-1].local_date == "2019-05-31"
    assert "fixture-session" not in repr(records[0])


def test_manifest_remote_total_mismatch_fails_closed_before_iteration(tmp_path: Path) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    raw_root = _synthetic_raw_root(tmp_path)
    manifest_path = raw_root / "manifests" / "timeseries" / "2019-05-31.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["remote_total_reported"] = 2
    _write_manifest(manifest_path, manifest)

    iterator = module.iter_validated_raw_records(
        raw_root,
        contract=_fixture_contract(module, raw_root, pin_digest=False),
    )
    with pytest.raises(module.RawSnapshotError, match="remote total"):
        next(iterator)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "wrong/v1", "contract"),
        ("_id", "wrong-private-object", "contract"),
        ("sha256", "0" * 64, "hash"),
        ("record_count", 2, "record count"),
        ("downloaded_at_utc", "not-a-time", "timestamp"),
    ],
)
def test_carry_manifest_corruption_fails_closed(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    raw_root = _synthetic_raw_root(tmp_path)
    manifest_path = raw_root / "manifests" / "carry_in" / "carry_in.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    _write_manifest(manifest_path, manifest)

    with pytest.raises(module.RawSnapshotError, match=message):
        module.validate_raw_snapshot(
            raw_root,
            contract=_fixture_contract(module, raw_root, pin_digest=False),
        )


def test_invalid_carry_gzip_fails_closed(tmp_path: Path) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    raw_root = _synthetic_raw_root(tmp_path)
    data_path = raw_root / "timeseries" / "carry_in" / "carry_in.jsonl.gz"
    data_path.write_bytes(b"not-gzip")

    with pytest.raises(module.RawSnapshotError, match="gzip JSONL"):
        module.validate_raw_snapshot(
            raw_root,
            contract=_fixture_contract(module, raw_root, pin_digest=False),
        )


def test_before_after_raw_inventory_compare_is_exact_and_fails_closed(tmp_path: Path) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    source = raw_root / "source.bin"
    source.write_bytes(b"before")
    before = module.canonical_inventory(raw_root)

    module.assert_raw_snapshot_unchanged(before, module.canonical_inventory(raw_root))
    source.write_bytes(b"change")

    with pytest.raises(module.RawSnapshotChangedError, match="changed"):
        module.assert_raw_snapshot_unchanged(before, module.canonical_inventory(raw_root))


def test_atomic_writers_reject_raw_targets_and_write_canonical_payloads(tmp_path: Path) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    local_root = tmp_path / "interim"

    with pytest.raises(module.UnsafeWriteTargetError, match="raw root"):
        module.atomic_write_json(raw_root / "forbidden.json", {"unsafe": True}, raw_root=raw_root)
    assert not (raw_root / "forbidden.json").exists()

    destination = local_root / "manifest.json"
    module.atomic_write_json(destination, {"z": 1, "a": "充电"}, raw_root=raw_root)

    assert destination.read_bytes() == '{\n  "a": "充电",\n  "z": 1\n}\n'.encode()
    assert list(local_root.glob("*.partial-*")) == []


def test_atomic_write_failure_preserves_previous_file_and_removes_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    destination = tmp_path / "processed" / "data.bin"
    destination.parent.mkdir()
    destination.write_bytes(b"previous")

    def fail_replace(source: object, target: object) -> None:
        del source, target
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="synthetic replace"):
        module.atomic_write_bytes(destination, b"replacement", raw_root=raw_root)

    assert destination.read_bytes() == b"previous"
    assert list(destination.parent.glob(".data.bin.partial-*")) == []


def test_public_validator_accepts_only_the_declared_closed_safe_payload() -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    contents = _safe_public_contents(module)
    contents["cleaning_qa.json"] = (
        json.dumps(
            {
                "schema_version": "aggregate/v1",
                "status": "PASS",
                "dataset_id": "D0001-jpl-2019-05-full-ts",
                "source": "https://acn-api.caltech.edu/",
                "record_count": 1645,
                "token_emitted": False,
                "note": "Only aggregate values are published; no authorization is granted.",
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()

    module.validate_public_artifacts(contents)

    assert module.PUBLIC_ARTIFACT_NAMES == (
        "cleaning_qa.json",
        "cleaning_sensitivity.json",
        "boundary_current_audit.json",
        "power_semantics_audit.json",
        "power_semantics_decision.md",
        "station_15min_qa.json",
        "issue_snapshot_qa.json",
        "leakage_audit.json",
        "feature_whitelist.yaml",
        "feature_blacklist.yaml",
        "data_snapshot_manifest.json",
        "run_manifest.json",
        "SHA256SUMS",
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"sessionID": "fixture-private-session-1"},
        {"safe": "private-object-123"},
        {"access_token": "fixture-secret-value"},
        {"safe": "Authorization: Bearer abcdefghijklmnop"},
        {"hostname": "fixture-host"},
        {"username": "fixture-user"},
        {"safe": r"C:\\Users\\fixture-user\\raw\\data.json"},
        {"safe": "/opt/private/raw/data.json"},
        {"safe": "/tmp"},
        {"safe": "/"},
        {"safe": "/数据/file"},
    ],
)
def test_public_validator_rejects_private_material(payload: dict[str, object]) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    contents = _safe_public_contents(module)
    contents["cleaning_qa.json"] = (json.dumps(payload) + "\n").encode()

    with pytest.raises(module.PublicPrivacyError):
        module.validate_public_artifacts(contents)


def test_public_validator_rejects_unexpected_files() -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    contents = _safe_public_contents(module)
    contents["unexpected.json"] = b"{}\n"

    with pytest.raises(module.PublicPrivacyError, match="unexpected files"):
        module.validate_public_artifacts(contents)


def test_public_validator_rejects_large_payloads_and_collections() -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    contents = _safe_public_contents(module)
    contents["power_semantics_decision.md"] = b"x" * (2 * 1024 * 1024 + 1)
    with pytest.raises(module.PublicPrivacyError, match="size limit"):
        module.validate_public_artifacts(contents)

    contents = _safe_public_contents(module)
    contents["cleaning_qa.json"] = json.dumps({"aggregate": list(range(1001))}).encode()
    with pytest.raises(module.PublicPrivacyError, match="collection"):
        module.validate_public_artifacts(contents)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("feature_whitelist.yaml", "sessionID: redacted\n"),
        ("feature_whitelist.yaml", "{sessionID: redacted}\n"),
        ("feature_whitelist.yaml", "access_token: redacted\n"),
        ("power_semantics_decision.md", "hostname: redacted\n"),
    ],
)
def test_public_validator_rejects_private_field_names_in_non_json_text(
    name: str,
    text: str,
) -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    contents = _safe_public_contents(module)
    contents[name] = text

    with pytest.raises(module.PublicPrivacyError, match="private field|credential"):
        module.validate_public_artifacts(contents)


def test_public_validator_allows_safe_aggregate_text_and_declarations() -> None:
    module = importlib.import_module("evcf.data.acn_jpl_preparation")
    contents = _safe_public_contents(module)
    contents["feature_whitelist.yaml"] = (
        "token_emitted: false # verified negative declaration\naggregate_values_count: 1645\n"
    )
    contents["power_semantics_decision.md"] = (
        "Only aggregate values are published; no authorization is granted.\n"
    )

    module.validate_public_artifacts(contents)
