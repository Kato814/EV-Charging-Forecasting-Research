from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from evcf.data.acn_api import ACNQuery
from evcf.data.acn_jpl_full_month_ts import (
    FullMonthAuthorizationError,
    FullMonthMetadataError,
    run_full_month_timeseries,
)
from evcf.data.acn_jpl_gate0 import jpl_analysis_windows

ZONE = ZoneInfo("America/Los_Angeles")
TOKEN = "fixture-secret-token"


def _stamp(value: datetime) -> str:
    return format_datetime(value.astimezone(timezone.utc), usegmt=True)


def _record(index: int, connection: datetime) -> dict[str, Any]:
    return {
        "_id": f"private-object-{index:04d}",
        "sessionID": f"private-session-{index:04d}",
        "connectionTime": _stamp(connection),
        "disconnectTime": _stamp(connection + timedelta(hours=1)),
    }


def _production_scope_records() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    local_connection = datetime(2019, 5, 2, 8, tzinfo=ZONE)
    records = [_record(index, local_connection) for index in range(1644)]
    carry = {
        "_id": "private-carry-object",
        "sessionID": "private-carry-session",
        # This is in May under UTC boundaries, but April 30 in Los Angeles.
        "connectionTime": "Wed, 01 May 2019 00:30:00 GMT",
        "disconnectTime": "Wed, 01 May 2019 08:00:00 GMT",
    }
    records.append(carry)
    return records, carry


def _write_legacy_metadata(directory: Path, records: list[dict[str, Any]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    complete_record_count = 33_638
    complete_file_count = 42
    assert len(records) <= complete_record_count
    filler_count = complete_record_count - len(records)
    filler_base, filler_remainder = divmod(filler_count, complete_file_count)
    filler = {
        "connectionTime": "Mon, 01 Jan 2018 08:00:00 GMT",
        "disconnectTime": "Mon, 01 Jan 2018 09:00:00 GMT",
    }
    first_path: Path | None = None
    for index in range(complete_file_count):
        data_path = directory / f"jpl-history-{index:03d}.jsonl.gz"
        if first_path is None:
            first_path = data_path
        file_records = records if index == 0 else []
        file_filler_count = filler_base + int(index < filler_remainder)
        with gzip.open(data_path, "wt", encoding="utf-8", newline="\n") as handle:
            for record in file_records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            filler_line = json.dumps(filler, sort_keys=True) + "\n"
            for _ in range(file_filler_count):
                handle.write(filler_line)
        record_count = len(file_records) + file_filler_count
        manifest = {
            "schema_version": 1,
            "endpoint": "sessions/jpl",
            "site": "jpl",
            "mode": "metadata",
            "record_count": record_count,
            "source_total": record_count,
            "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        }
        data_path.with_name(data_path.name + ".manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
    assert first_path is not None
    return first_path


def _page(items: list[dict[str, Any]], total: int) -> dict[str, Any]:
    return {"_items": items, "_links": {}, "_meta": {"total": total}}


class FullRunClient:
    def __init__(
        self,
        carry: dict[str, Any],
        *,
        carry_total: int = 1,
        carry_response: dict[str, Any] | None = None,
    ) -> None:
        self.token = TOKEN
        self.carry = carry
        self.carry_total = carry_total
        self.carry_response = carry_response or carry
        self.queries: list[ACNQuery] = []

    def iter_pages(self, query: ACNQuery):  # type: ignore[no-untyped-def]
        self.queries.append(query)
        if query.session_id is not None:
            yield _page([self.carry_response], self.carry_total)
            return
        day = query.start.astimezone(ZONE).date().isoformat()
        yield _page([{"_id": f"daily-{day}", "sessionID": f"daily-{day}"}], 1)


class NoNetworkClient:
    token = TOKEN

    def iter_pages(self, query: ACNQuery):  # type: ignore[no-untyped-def]
        raise AssertionError(f"resume unexpectedly queried {query.endpoint}")


def _complete_daily_runner(
    client: Any,
    root: Path,
    windows: Any,
    *,
    endpoint: str,
) -> dict[str, Any]:
    del client, root
    materialized = list(windows)
    assert endpoint == "timeseries"
    return {
        "pending_days": [],
        "completed_days": [window.day_key for window in materialized],
        "failed_days": [],
        "last_success": materialized[-1].day_key,
        "retry_count": 0,
    }


@pytest.mark.parametrize("authorized", [False, None, 1, "true"])
def test_authorization_fails_closed_before_metadata_client_or_file_access(
    tmp_path: Path,
    authorized: object,
) -> None:
    client_calls = 0
    runner_calls = 0

    def client_factory() -> Any:
        nonlocal client_calls
        client_calls += 1
        raise AssertionError("client must not be constructed")

    def runner(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal runner_calls
        runner_calls += 1
        raise AssertionError("runner must not be called")

    raw_root = tmp_path / "raw-must-not-exist"
    metadata_root = tmp_path / "metadata-must-not-be-read"
    with pytest.raises(FullMonthAuthorizationError, match="explicit authorization"):
        run_full_month_timeseries(
            authorized=authorized,  # type: ignore[arg-type]
            metadata_root=metadata_root,
            raw_root=raw_root,
            client_factory=client_factory,
            daily_runner=runner,
        )

    assert client_calls == 0
    assert runner_calls == 0
    assert not raw_root.exists()
    assert not metadata_root.exists()


def test_metadata_scope_filters_1644_local_sessions_from_1645_utc_sessions(
    tmp_path: Path,
) -> None:
    records, carry = _production_scope_records()
    metadata_root = tmp_path / "metadata"
    _write_legacy_metadata(metadata_root, records)
    client = FullRunClient(carry)

    result = run_full_month_timeseries(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=tmp_path / "raw",
        client_factory=lambda: client,
        daily_runner=_complete_daily_runner,
    )

    assert result["metadata"] == {
        "file_count": 42,
        "valid_manifest_count": 42,
        "source_record_count": 33638,
        "analysis_session_count": 1644,
        "utc_month_session_count": 1645,
        "carry_in_session_count": 1,
        "inventory_digest": result["metadata"]["inventory_digest"],
    }
    assert len(result["metadata"]["inventory_digest"]) == 64
    assert result["status"] == "COMPLETE"
    assert len(client.queries) == 1


def test_wrong_metadata_count_or_legacy_manifest_fails_before_client(
    tmp_path: Path,
) -> None:
    records, _ = _production_scope_records()
    metadata_root = tmp_path / "metadata"
    data_path = _write_legacy_metadata(metadata_root, records[:-2] + [records[-1]])
    client_calls = 0

    def client_factory() -> Any:
        nonlocal client_calls
        client_calls += 1
        raise AssertionError("client must not be constructed")

    with pytest.raises(FullMonthMetadataError, match="1644"):
        run_full_month_timeseries(
            authorized=True,
            metadata_root=metadata_root,
            raw_root=tmp_path / "raw-count",
            client_factory=client_factory,
        )
    assert client_calls == 0
    assert not (tmp_path / "raw-count").exists()

    records, _ = _production_scope_records()
    _write_legacy_metadata(metadata_root, records)
    manifest_path = data_path.with_name(data_path.name + ".manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["endpoint"] = "sessions/caltech"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FullMonthMetadataError, match="legacy manifest"):
        run_full_month_timeseries(
            authorized=True,
            metadata_root=metadata_root,
            raw_root=tmp_path / "raw-manifest",
            client_factory=client_factory,
        )
    assert client_calls == 0
    assert not (tmp_path / "raw-manifest").exists()

    manifest["endpoint"] = "sessions/jpl"
    manifest["record_count"] = float(manifest["record_count"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FullMonthMetadataError, match="legacy manifest"):
        run_full_month_timeseries(
            authorized=True,
            metadata_root=metadata_root,
            raw_root=tmp_path / "raw-float-manifest",
            client_factory=client_factory,
        )
    assert client_calls == 0
    assert not (tmp_path / "raw-float-manifest").exists()


@pytest.mark.parametrize("missing", ["data", "manifest"])
def test_incomplete_42_file_inventory_fails_before_client(
    tmp_path: Path,
    missing: str,
) -> None:
    records, _ = _production_scope_records()
    metadata_root = tmp_path / "metadata"
    data_path = _write_legacy_metadata(metadata_root, records)
    target = (
        data_path if missing == "data" else data_path.with_name(data_path.name + ".manifest.json")
    )
    target.unlink()
    client_calls = 0

    def client_factory() -> Any:
        nonlocal client_calls
        client_calls += 1
        raise AssertionError("client must not be constructed")

    with pytest.raises(FullMonthMetadataError, match="42 complete metadata files"):
        run_full_month_timeseries(
            authorized=True,
            metadata_root=metadata_root,
            raw_root=tmp_path / "raw",
            client_factory=client_factory,
        )
    assert client_calls == 0
    assert not (tmp_path / "raw").exists()


def test_full_run_uses_31_daily_queries_exact_carry_query_and_private_resume(
    tmp_path: Path,
) -> None:
    records, carry = _production_scope_records()
    metadata_root = tmp_path / "metadata"
    raw_root = tmp_path / "raw"
    _write_legacy_metadata(metadata_root, records)
    first_client = FullRunClient(carry)

    first = run_full_month_timeseries(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=raw_root,
        client_factory=lambda: first_client,
        downloaded_at_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    windows = list(jpl_analysis_windows())
    assert first["status"] == "COMPLETE"
    assert first["daily"] == {
        "requested_days": 31,
        "completed_days": 31,
        "pending_days": 0,
        "failed_days": 0,
        "retry_count": 0,
        "serial": True,
    }
    assert len(first_client.queries) == 32
    daily_queries = first_client.queries[:31]
    assert all(query.endpoint == "sessions/jpl/ts" for query in daily_queries)
    assert all(query.session_id is None for query in daily_queries)
    assert [(query.start_utc, query.end_utc) for query in daily_queries] == [
        (window.utc_start, window.utc_end) for window in windows
    ]
    carry_query = first_client.queries[-1]
    assert carry_query.endpoint == "sessions/jpl/ts"
    assert carry_query.session_id == carry["sessionID"]
    assert carry_query.start_utc == datetime(2019, 5, 1, 0, 30, tzinfo=timezone.utc)
    assert carry_query.start_utc < datetime(2019, 5, 1, 7, tzinfo=timezone.utc)
    assert carry_query.end_utc == datetime(2019, 6, 1, 7, tzinfo=timezone.utc)
    assert carry_query.condition.endswith('sessionID == "private-carry-session"')

    public_text = json.dumps(first, ensure_ascii=False)
    for private_value in (TOKEN, carry["_id"], carry["sessionID"]):
        assert private_value not in public_text
    assert str(raw_root.resolve()) not in public_text
    assert str(metadata_root.resolve()) not in public_text
    assert "query_condition" not in public_text
    assert '"sessionID"' not in public_text
    assert '"_id"' not in public_text

    progress_text = (raw_root / "state" / "progress.json").read_text(encoding="utf-8")
    assert TOKEN not in progress_text
    assert json.loads(progress_text)["endpoints"]["timeseries"]["completed_days"] == [
        window.day_key for window in windows
    ]
    daily_manifests = sorted((raw_root / "manifests" / "timeseries").glob("*.json"))
    assert len(daily_manifests) == 31
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["token_stored"] is False
        for path in daily_manifests
    )

    carry_manifest_path = raw_root / "manifests" / "carry_in" / "carry_in.manifest.json"
    carry_manifest_text = carry_manifest_path.read_text(encoding="utf-8")
    carry_manifest = json.loads(carry_manifest_text)
    assert carry_manifest["sessionID"] == carry["sessionID"]
    assert carry_manifest["_id"] == carry["_id"]
    assert carry_manifest["token_stored"] is False
    assert TOKEN not in carry_manifest_text
    assert not list(raw_root.rglob("*.partial"))

    resumed = run_full_month_timeseries(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=raw_root,
        client_factory=NoNetworkClient,
    )
    assert resumed["status"] == "COMPLETE"
    assert resumed["carry_in"]["status"] == "SKIPPED"

    carry_data_path = raw_root / "timeseries" / "carry_in" / "carry_in.jsonl.gz"
    carry_data_path.write_bytes(b"corrupt carry-in gzip")
    repair_client = FullRunClient(carry)
    repaired = run_full_month_timeseries(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=raw_root,
        client_factory=lambda: repair_client,
    )
    assert repaired["status"] == "COMPLETE"
    assert repaired["carry_in"]["status"] == "DOWNLOADED"
    assert len(repair_client.queries) == 1
    assert repair_client.queries[0].session_id == carry["sessionID"]
    assert not list(raw_root.rglob("*.partial"))


@pytest.mark.parametrize("tamper", ["count", "float-count", "query", "json", "token"])
def test_bad_carry_in_artifact_redownloads_only_the_carry_in(
    tmp_path: Path,
    tamper: str,
) -> None:
    records, carry = _production_scope_records()
    metadata_root = tmp_path / "metadata"
    raw_root = tmp_path / "raw"
    _write_legacy_metadata(metadata_root, records)
    first_client = FullRunClient(carry)
    first = run_full_month_timeseries(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=raw_root,
        client_factory=lambda: first_client,
        daily_runner=_complete_daily_runner,
    )
    assert first["status"] == "COMPLETE"

    data_path = raw_root / "timeseries" / "carry_in" / "carry_in.jsonl.gz"
    manifest_path = raw_root / "manifests" / "carry_in" / "carry_in.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tamper == "count":
        manifest["record_count"] = True
    elif tamper == "float-count":
        manifest["record_count"] = 1.0
    elif tamper == "query":
        manifest["query_condition"] = "forged exact-session query"
    elif tamper == "json":
        with gzip.open(data_path, "wt", encoding="utf-8") as handle:
            handle.write("not-json\n")
        manifest["sha256"] = hashlib.sha256(data_path.read_bytes()).hexdigest()
    else:
        manifest["token_stored"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    repair_client = FullRunClient(carry)
    repaired = run_full_month_timeseries(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=raw_root,
        client_factory=lambda: repair_client,
        daily_runner=_complete_daily_runner,
    )

    assert repaired["status"] == "COMPLETE"
    assert repaired["carry_in"]["status"] == "DOWNLOADED"
    assert len(repair_client.queries) == 1
    assert repair_client.queries[0].session_id == carry["sessionID"]


@pytest.mark.parametrize("mismatch", ["total", "identifier"])
def test_carry_in_remote_total_and_identifier_mismatch_fail(
    tmp_path: Path,
    mismatch: str,
) -> None:
    records, carry = _production_scope_records()
    metadata_root = tmp_path / "metadata"
    _write_legacy_metadata(metadata_root, records)
    wrong = dict(carry)
    wrong["_id"] = "wrong-object"
    client = (
        FullRunClient(carry, carry_total=2)
        if mismatch == "total"
        else FullRunClient(carry, carry_response=wrong)
    )

    result = run_full_month_timeseries(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=tmp_path / "raw",
        client_factory=lambda: client,
        daily_runner=_complete_daily_runner,
    )

    assert result["status"] == "INCOMPLETE"
    assert result["carry_in"]["status"] == "FAILED"
    assert result["carry_in"]["complete_for_query"] is False
    if mismatch == "total":
        assert result["carry_in"]["remote_total_reported"] == 2
    assert len(client.queries) == 1
    assert TOKEN not in json.dumps(result)


def test_daily_failure_prevents_carry_in_attempt(tmp_path: Path) -> None:
    records, carry = _production_scope_records()
    metadata_root = tmp_path / "metadata"
    _write_legacy_metadata(metadata_root, records)
    carry_calls = 0

    def incomplete_runner(
        client: Any,
        root: Path,
        windows: Any,
        *,
        endpoint: str,
    ) -> dict[str, Any]:
        del client, root, endpoint
        days = [window.day_key for window in windows]
        return {
            "pending_days": [],
            "completed_days": days[:-1],
            "failed_days": days[-1:],
            "last_success": days[-2],
            "retry_count": 1,
        }

    def carry_downloader(*args: Any, **kwargs: Any) -> Any:
        nonlocal carry_calls
        carry_calls += 1
        raise AssertionError("carry-in must wait for all 31 daily chunks")

    result = run_full_month_timeseries(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=tmp_path / "raw",
        client_factory=lambda: FullRunClient(carry),
        daily_runner=incomplete_runner,
        carry_downloader=carry_downloader,
    )

    assert result["status"] == "INCOMPLETE"
    assert result["daily"]["completed_days"] == 30
    assert result["carry_in"]["status"] == "NOT_RUN"
    assert carry_calls == 0


def test_public_result_whitelists_injected_carry_fields(tmp_path: Path) -> None:
    records, carry = _production_scope_records()
    metadata_root = tmp_path / "metadata"
    _write_legacy_metadata(metadata_root, records)

    class UnsafeInjectedResult:
        status = "SKIPPED"
        record_count = 1
        remote_total_reported = 1
        complete_for_query = True

        def public_dict(self) -> dict[str, Any]:
            return {
                "status": self.status,
                "record_count": self.record_count,
                "remote_total_reported": self.remote_total_reported,
                "complete_for_query": self.complete_for_query,
                "sessionID": carry["sessionID"],
                "query_condition": "private exact query",
                "raw_root": str(tmp_path.resolve()),
            }

    result = run_full_month_timeseries(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=tmp_path / "raw",
        client_factory=lambda: FullRunClient(carry),
        daily_runner=_complete_daily_runner,
        carry_downloader=lambda *args: UnsafeInjectedResult(),  # type: ignore[arg-type]
    )

    assert result["status"] == "COMPLETE"
    assert result["carry_in"] == {
        "status": "SKIPPED",
        "record_count": 1,
        "remote_total_reported": 1,
        "complete_for_query": True,
    }
    serialized = json.dumps(result)
    assert carry["sessionID"] not in serialized
    assert "query_condition" not in serialized
    assert str(tmp_path.resolve()) not in serialized
