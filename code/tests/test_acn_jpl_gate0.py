from __future__ import annotations

import gzip
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import date, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import requests
from evcf.data import acn_jpl_gate0 as gate0_module
from evcf.data.acn_api import ACNClient, ACNDataError
from evcf.data.acn_jpl_gate0 import (
    JPL_ACQUISITION_END,
    JPL_ACQUISITION_START,
    IncompleteChunkError,
    chunk_paths,
    classify_session,
    detect_duplicate_identifiers,
    download_day_chunk,
    iter_local_day_windows,
    jpl_acquisition_windows,
    jpl_analysis_windows,
    run_daily_chunks,
    validate_chunk,
)


class FakeClient:
    def __init__(self, page_batches: list[list[dict[str, Any]]]) -> None:
        self.page_batches = page_batches
        self.queries: list[Any] = []

    def iter_pages(self, query: Any):
        self.queries.append(query)
        if not self.page_batches:
            raise AssertionError("iter_pages must not be called")
        yield from deepcopy(self.page_batches.pop(0))


def page(items: list[dict[str, Any]], *, total: int | None) -> dict[str, Any]:
    result: dict[str, Any] = {"_items": items, "_links": {}}
    if total is not None:
        result["_meta"] = {"total": total}
    return result


def test_fixed_jpl_acquisition_window_uses_local_half_open_days() -> None:
    windows = list(jpl_acquisition_windows())

    assert len(windows) == 38
    assert windows[0].local_start == JPL_ACQUISITION_START
    assert windows[-1].local_end == JPL_ACQUISITION_END
    assert windows[0].utc_start.isoformat() == "2019-04-24T07:00:00+00:00"
    assert windows[-1].utc_end.isoformat() == "2019-06-01T07:00:00+00:00"
    assert all(left.local_end == right.local_start for left, right in pairwise(windows))


def test_jpl_analysis_windows_are_exactly_the_31_local_may_days() -> None:
    windows = list(jpl_analysis_windows())

    assert len(windows) == 31
    assert windows[0].local_start == JPL_ACQUISITION_START.replace(day=1, month=5)
    assert windows[-1].local_end == JPL_ACQUISITION_END
    assert windows[0].utc_start.isoformat() == "2019-05-01T07:00:00+00:00"
    assert windows[-1].utc_end.isoformat() == "2019-06-01T07:00:00+00:00"
    assert all(window.local_start.tzinfo is not None for window in windows)
    assert all(left.local_end == right.local_start for left, right in pairwise(windows))


def test_local_day_windows_respect_spring_and_fall_dst_duration() -> None:
    spring = list(
        iter_local_day_windows(
            date(2024, 3, 10),
            date(2024, 3, 11),
            timezone_name="America/Los_Angeles",
        )
    )
    fall = list(
        iter_local_day_windows(
            date(2024, 11, 3),
            date(2024, 11, 4),
            timezone_name="America/Los_Angeles",
        )
    )

    assert (spring[0].utc_end - spring[0].utc_start).total_seconds() == 23 * 3600
    assert (fall[0].utc_end - fall[0].utc_start).total_seconds() == 25 * 3600
    assert spring[0].local_start.astimezone(timezone.utc) == spring[0].utc_start
    assert fall[0].local_end.astimezone(timezone.utc) == fall[0].utc_end


def test_session_roles_separate_analysis_connections_and_buffer_carry_in() -> None:
    analysis = {
        "connectionTime": "Wed, 01 May 2019 07:00:00 GMT",
        "disconnectTime": "Wed, 01 May 2019 08:00:00 GMT",
    }
    carry_in = {
        "connectionTime": "Tue, 30 Apr 2019 23:00:00 GMT",
        "disconnectTime": "Wed, 01 May 2019 07:01:00 GMT",
    }
    ends_at_boundary = {
        "connectionTime": "Tue, 30 Apr 2019 23:00:00 GMT",
        "disconnectTime": "Wed, 01 May 2019 07:00:00 GMT",
    }
    outside_acquisition_buffer = {
        "connectionTime": "Tue, 23 Apr 2019 23:00:00 GMT",
        "disconnectTime": "Wed, 01 May 2019 09:00:00 GMT",
    }

    assert classify_session(analysis).analysis_session
    assert not classify_session(analysis).carry_in
    assert classify_session(carry_in).carry_in
    assert not classify_session(carry_in).analysis_session
    assert not classify_session(ends_at_boundary).carry_in
    assert not classify_session(outside_acquisition_buffer).carry_in


def test_duplicate_detection_reports_counts_without_returning_identifiers() -> None:
    records = [
        {"_id": "private-a", "sessionID": "session-a"},
        {"_id": "private-a", "sessionID": "session-b"},
        {"_id": "private-c", "sessionID": "session-b"},
        {"_id": "private-a", "sessionID": None},
    ]

    duplicates = detect_duplicate_identifiers(records)

    assert duplicates.duplicate_id_records == 2
    assert duplicates.duplicate_session_id_records == 1
    assert "private-a" not in repr(duplicates)
    assert "session-b" not in repr(duplicates)


def test_download_day_chunk_uses_iter_pages_and_writes_complete_gzip_manifest(
    tmp_path: Path,
) -> None:
    records = [
        {"_id": "id-1", "sessionID": "s-1", "unicode": "充电"},
        {"_id": "id-2", "sessionID": "s-2", "value": 2},
    ]
    client = FakeClient([[page(records[:1], total=2), page(records[1:], total=2)]])
    window = next(jpl_acquisition_windows())

    result = download_day_chunk(client, tmp_path, window, endpoint="metadata")

    assert result.status == "downloaded"
    assert result.record_count == 2
    assert result.remote_total_reported == 2
    assert result.complete_for_query
    assert len(client.queries) == 1
    query = client.queries[0]
    assert query.endpoint == "sessions/jpl"
    assert query.start_utc == window.utc_start
    assert query.end_utc == window.utc_end
    assert "connectionTime <" in query.condition
    assert "connectionTime <=" not in query.condition

    expected_data, expected_manifest = chunk_paths(tmp_path, "metadata", window)
    assert result.data_path == expected_data
    assert result.manifest_path == expected_manifest
    assert not result.data_path.with_suffix(result.data_path.suffix + ".partial").exists()
    with gzip.open(result.data_path, "rt", encoding="utf-8") as handle:
        stored_records = [json.loads(line) for line in handle]
    assert stored_records == records

    manifest_text = result.manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    required = {
        "schema_version",
        "dataset_id",
        "source",
        "endpoint",
        "site",
        "timezone",
        "local_start_inclusive",
        "local_end_exclusive",
        "utc_start_inclusive",
        "utc_end_exclusive",
        "query_condition",
        "record_count",
        "remote_total_reported",
        "complete_for_query",
        "downloaded_at_utc",
        "sha256",
        "token_stored",
    }
    assert required <= manifest.keys()
    assert manifest["endpoint"] == "sessions/jpl"
    assert manifest["site"] == "jpl"
    assert manifest["timezone"] == "America/Los_Angeles"
    assert manifest["local_end_exclusive"] == window.local_end.isoformat()
    assert manifest["utc_end_exclusive"] == window.utc_end.isoformat()
    assert manifest["record_count"] == 2
    assert manifest["remote_total_reported"] == 2
    assert manifest["complete_for_query"] is True
    assert manifest["token_stored"] is False
    assert manifest["sha256"] == hashlib.sha256(result.data_path.read_bytes()).hexdigest()
    assert "sentinel-secret-token" not in manifest_text
    assert validate_chunk(
        result.data_path,
        result.manifest_path,
        window=window,
        endpoint="metadata",
    ).valid


def test_valid_chunk_is_skipped_without_calling_client(tmp_path: Path) -> None:
    window = next(jpl_acquisition_windows())
    first_client = FakeClient([[page([{"_id": "id-1", "sessionID": "s-1"}], total=1)]])
    first = download_day_chunk(first_client, tmp_path, window, endpoint="timeseries")
    no_call_client = FakeClient([])

    second = download_day_chunk(no_call_client, tmp_path, window, endpoint="timeseries")

    assert first.data_path == second.data_path
    assert second.status == "skipped"
    assert no_call_client.queries == []


def test_hash_mismatch_and_incomplete_manifest_force_clean_rewrite(tmp_path: Path) -> None:
    window = next(jpl_acquisition_windows())
    initial = download_day_chunk(
        FakeClient([[page([{"_id": "old"}], total=1)]]),
        tmp_path,
        window,
        endpoint="metadata",
    )
    initial.data_path.write_bytes(b"corrupt gzip bytes")
    replacement = {"_id": "replacement", "nested": {"b": 2, "a": 1}}

    rewritten = download_day_chunk(
        FakeClient([[page([replacement], total=1)]]),
        tmp_path,
        window,
        endpoint="metadata",
    )

    assert rewritten.status == "downloaded"
    assert validate_chunk(
        rewritten.data_path,
        rewritten.manifest_path,
        window=window,
        endpoint="metadata",
    ).valid
    with gzip.open(rewritten.data_path, "rt", encoding="utf-8") as handle:
        assert json.loads(handle.readline()) == replacement

    manifest = json.loads(rewritten.manifest_path.read_text(encoding="utf-8"))
    manifest["complete_for_query"] = False
    rewritten.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    final_client = FakeClient([[page([replacement], total=1)]])
    final = download_day_chunk(final_client, tmp_path, window, endpoint="metadata")
    assert final.status == "downloaded"
    assert len(final_client.queries) == 1


def test_missing_remote_total_is_never_declared_complete(tmp_path: Path) -> None:
    window = next(jpl_acquisition_windows())

    with pytest.raises(IncompleteChunkError, match="remote total"):
        download_day_chunk(
            FakeClient([[page([{"_id": "id-1"}], total=None)]]),
            tmp_path,
            window,
            endpoint="metadata",
        )

    data_path, manifest_path = chunk_paths(tmp_path, "metadata", window)
    assert not data_path.exists()
    assert not manifest_path.exists()
    assert not data_path.with_suffix(data_path.suffix + ".partial").exists()


def test_public_chunk_dataclasses_never_serialize_private_identifiers(
    tmp_path: Path,
) -> None:
    window = next(jpl_analysis_windows())
    private_record = {
        "_id": "sentinel-private-object",
        "sessionID": "sentinel-private-session",
    }
    result = download_day_chunk(
        FakeClient([[page([private_record], total=1)]]),
        tmp_path,
        window,
        endpoint="timeseries",
    )
    validation = validate_chunk(
        result.data_path,
        result.manifest_path,
        window=window,
        endpoint="timeseries",
    )

    for public_dataclass in (result, validation):
        payload = asdict(public_dataclass)
        serialized = json.dumps(payload, default=str)
        assert "sentinel-private-object" not in serialized
        assert "sentinel-private-session" not in serialized
        assert "identity" not in serialized


@pytest.mark.parametrize("remote_total", [None, 2])
def test_incomplete_daily_redownload_preserves_existing_canonical_pair(
    tmp_path: Path,
    remote_total: int | None,
) -> None:
    window = next(jpl_analysis_windows())
    initial = download_day_chunk(
        FakeClient([[page([{"_id": "old", "sessionID": "old-session"}], total=1)]]),
        tmp_path,
        window,
        endpoint="timeseries",
    )
    manifest = json.loads(initial.manifest_path.read_text(encoding="utf-8"))
    manifest["complete_for_query"] = False
    initial.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    old_data = initial.data_path.read_bytes()
    old_manifest = initial.manifest_path.read_bytes()

    with pytest.raises(IncompleteChunkError, match="remote total"):
        download_day_chunk(
            FakeClient([[page([{"_id": "new", "sessionID": "new-session"}], total=remote_total)]]),
            tmp_path,
            window,
            endpoint="timeseries",
        )

    assert initial.data_path.read_bytes() == old_data
    assert initial.manifest_path.read_bytes() == old_manifest
    assert not initial.data_path.with_suffix(initial.data_path.suffix + ".partial").exists()


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("schema_version", "wrong-schema/v9"),
        ("site", "caltech"),
        ("timezone", "UTC"),
        ("local_start_inclusive", "2019-04-25T00:00:00-07:00"),
        ("local_end_exclusive", "2019-04-26T00:00:00-07:00"),
        ("utc_start_inclusive", "2019-04-25T07:00:00+00:00"),
        ("utc_end_exclusive", "2019-04-26T07:00:00+00:00"),
        ("query_condition", "connectionTime >= forged"),
        ("endpoint", "sessions/jpl/ts"),
    ],
)
def test_validate_chunk_rejects_manifest_for_wrong_window_or_endpoint(
    tmp_path: Path,
    field: str,
    tampered_value: str,
) -> None:
    window = next(jpl_acquisition_windows())
    result = download_day_chunk(
        FakeClient([[page([{"_id": "id-1"}], total=1)]]),
        tmp_path,
        window,
        endpoint="metadata",
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest[field] = tampered_value
    result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    validation = validate_chunk(
        result.data_path,
        result.manifest_path,
        window=window,
        endpoint="metadata",
    )

    assert not validation.valid
    assert validation.reason == f"manifest {field} does not match expected query"


@pytest.mark.parametrize(
    ("field", "tampered_value"),
    [
        ("source", None),
        ("source", "untrusted mirror"),
        ("dataset_id", "D9999"),
        ("output_file", "forged.jsonl.gz"),
        ("downloaded_at_utc", None),
        ("downloaded_at_utc", "2026-01-01T00:00:00"),
        ("downloaded_at_utc", "2026-01-01T08:00:00+08:00"),
        ("downloaded_at_utc", "not-a-timestamp"),
        ("downloaded_at_utc", True),
    ],
)
def test_validate_chunk_rejects_invalid_provenance_manifest_fields(
    tmp_path: Path,
    field: str,
    tampered_value: object,
) -> None:
    window = next(jpl_analysis_windows())
    result = download_day_chunk(
        FakeClient([[page([{"_id": "id-1", "sessionID": "session-1"}], total=1)]]),
        tmp_path,
        window,
        endpoint="timeseries",
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    if tampered_value is None:
        manifest.pop(field)
    else:
        manifest[field] = tampered_value
    result.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    validation = validate_chunk(
        result.data_path,
        result.manifest_path,
        window=window,
        endpoint="timeseries",
    )

    assert not validation.valid


def test_resume_redownloads_only_daily_chunk_with_invalid_provenance(
    tmp_path: Path,
) -> None:
    windows = list(jpl_analysis_windows())[:2]
    initial_client = FakeClient(
        [
            [page([{"_id": "id-1", "sessionID": "session-1"}], total=1)],
            [page([{"_id": "id-2", "sessionID": "session-2"}], total=1)],
        ]
    )
    initial = run_daily_chunks(
        initial_client,
        tmp_path,
        windows,
        endpoint="timeseries",
    )
    assert initial["completed_days"] == [window.day_key for window in windows]

    _, first_manifest_path = chunk_paths(tmp_path, "timeseries", windows[0])
    first_manifest = json.loads(first_manifest_path.read_text(encoding="utf-8"))
    first_manifest.pop("source")
    first_manifest_path.write_text(json.dumps(first_manifest), encoding="utf-8")

    repair_client = FakeClient([[page([{"_id": "id-1", "sessionID": "session-1"}], total=1)]])
    repaired = run_daily_chunks(
        repair_client,
        tmp_path,
        windows,
        endpoint="timeseries",
    )

    assert repaired["completed_days"] == [window.day_key for window in windows]
    assert len(repair_client.queries) == 1
    assert repair_client.queries[0].start_utc == windows[0].utc_start


def test_progress_tracks_failure_and_resume_without_storing_error_secrets(
    tmp_path: Path,
) -> None:
    windows = list(jpl_acquisition_windows())[:3]

    class FailingMiddleClient:
        def __init__(self) -> None:
            self.calls = 0

        def iter_pages(self, query: Any):
            self.calls += 1
            if self.calls == 2:
                raise ACNDataError("request failed: sentinel-secret-token")
            yield page([{"_id": f"id-{self.calls}"}], total=1)

    first_client = FailingMiddleClient()
    first_progress = run_daily_chunks(
        first_client,
        tmp_path,
        windows,
        endpoint="metadata",
    )

    progress_path = tmp_path / "state" / "progress.json"
    assert first_client.calls == 2
    progress_document = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress_document["endpoints"]["metadata"] == first_progress
    assert progress_document["schema_version"] == "acn-jpl-progress/v3"
    assert first_progress["schema_version"] == "acn-jpl-progress/v2"
    assert first_progress["pending_days"] == [windows[2].day_key]
    assert first_progress["completed_days"] == [windows[0].day_key]
    assert first_progress["failed_days"] == [windows[1].day_key]
    assert first_progress["failure_reasons"] == {windows[1].day_key: "ACN_DATA_ERROR"}
    assert first_progress["stop_reason"] == "ACN_DATA_ERROR"
    assert first_progress["last_success"] == windows[0].day_key
    assert first_progress["retry_count"] == 1
    assert not progress_path.with_suffix(".json.partial").exists()
    assert "sentinel-secret-token" not in progress_path.read_text(encoding="utf-8")

    resume_client = FakeClient(
        [
            [page([{"_id": "recovered"}], total=1)],
            [page([{"_id": "third-day"}], total=1)],
        ]
    )
    resumed = run_daily_chunks(
        resume_client,
        tmp_path,
        windows,
        endpoint="metadata",
    )

    assert len(resume_client.queries) == 2
    assert resumed["pending_days"] == []
    assert resumed["completed_days"] == [window.day_key for window in windows]
    assert resumed["failed_days"] == []
    assert resumed["failure_reasons"] == {}
    assert resumed["stop_reason"] is None
    assert resumed["last_success"] == windows[-1].day_key
    assert resumed["retry_count"] == 1


def test_incomplete_remote_total_is_recorded_as_failed_for_retry(tmp_path: Path) -> None:
    window = next(jpl_acquisition_windows())

    progress = run_daily_chunks(
        FakeClient([[page([{"_id": "id-1"}], total=None)]]),
        tmp_path,
        [window],
        endpoint="metadata",
    )

    assert progress["completed_days"] == []
    assert progress["failed_days"] == [window.day_key]
    assert progress["failure_reasons"] == {window.day_key: "INCOMPLETE_RESPONSE"}
    assert progress["stop_reason"] == "INCOMPLETE_RESPONSE"
    assert progress["retry_count"] == 1


def test_progress_preserves_metadata_when_timeseries_runs(tmp_path: Path) -> None:
    window = next(jpl_acquisition_windows())
    metadata = run_daily_chunks(
        FakeClient([[page([{"_id": "metadata"}], total=1)]]),
        tmp_path,
        [window],
        endpoint="metadata",
    )
    timeseries = run_daily_chunks(
        FakeClient([[page([{"_id": "timeseries"}], total=1)]]),
        tmp_path,
        [window],
        endpoint="timeseries",
    )

    progress = json.loads((tmp_path / "state" / "progress.json").read_text(encoding="utf-8"))
    assert progress["endpoints"]["metadata"] == metadata
    assert progress["endpoints"]["timeseries"] == timeseries
    assert progress["endpoints"]["metadata"]["completed_days"] == [window.day_key]
    assert progress["endpoints"]["timeseries"]["completed_days"] == [window.day_key]

    metadata_resume = FakeClient([])
    resumed = run_daily_chunks(
        metadata_resume,
        tmp_path,
        [window],
        endpoint="metadata",
    )
    final_progress = json.loads((tmp_path / "state" / "progress.json").read_text(encoding="utf-8"))
    assert resumed["completed_days"] == [window.day_key]
    assert metadata_resume.queries == []
    assert final_progress["endpoints"]["timeseries"] == timeseries


def test_acn_client_retry_adapter_is_bounded_and_honors_retry_after() -> None:
    session = ACNClient._build_session()
    retry = session.get_adapter("https://").max_retries

    assert retry.total == 5
    assert retry.status == 5
    assert retry.connect == 5
    assert retry.read == 5
    assert set(retry.status_forcelist) == {429, 500, 502, 503, 504}
    assert retry.respect_retry_after_header is True


def test_validate_chunk_treats_non_utf8_manifest_as_invalid(tmp_path: Path) -> None:
    window = next(jpl_acquisition_windows())
    result = download_day_chunk(
        FakeClient([[page([{"_id": "id-1"}], total=1)]]),
        tmp_path,
        window,
        endpoint="metadata",
    )
    result.manifest_path.write_bytes(b"\xff\xfe\x80")

    validation = validate_chunk(
        result.data_path,
        result.manifest_path,
        window=window,
        endpoint="metadata",
    )

    assert not validation.valid
    assert validation.reason == "manifest is not valid JSON"


def test_non_utf8_progress_is_ignored_and_rebuilt(tmp_path: Path) -> None:
    window = next(jpl_acquisition_windows())
    progress_path = tmp_path / "state" / "progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_bytes(b"\xff\xfe\x80")

    progress = run_daily_chunks(
        FakeClient([[page([{"_id": "id-1"}], total=1)]]),
        tmp_path,
        [window],
        endpoint="metadata",
    )

    assert progress["completed_days"] == [window.day_key]
    rebuilt = json.loads(progress_path.read_text(encoding="utf-8"))
    assert rebuilt["endpoints"]["metadata"] == progress


def test_retry_checkpoint_never_persists_day_as_pending_and_failed(
    tmp_path: Path,
) -> None:
    window = next(jpl_acquisition_windows())

    class FailingClient:
        def iter_pages(self, query: Any):
            raise ACNDataError("transient failure")
            yield  # pragma: no cover

    first = run_daily_chunks(
        FailingClient(),
        tmp_path,
        [window],
        endpoint="metadata",
    )
    assert first["failed_days"] == [window.day_key]
    assert first["failure_reasons"] == {window.day_key: "ACN_DATA_ERROR"}

    class InterruptingClient:
        def iter_pages(self, query: Any):
            raise KeyboardInterrupt
            yield  # pragma: no cover

    with pytest.raises(KeyboardInterrupt):
        run_daily_chunks(
            InterruptingClient(),
            tmp_path,
            [window],
            endpoint="metadata",
        )

    persisted = json.loads((tmp_path / "state" / "progress.json").read_text(encoding="utf-8"))[
        "endpoints"
    ]["metadata"]
    assert persisted["pending_days"] == [window.day_key]
    assert persisted["failed_days"] == []
    assert set(persisted["pending_days"]).isdisjoint(persisted["failed_days"])


def test_expected_network_failure_stops_and_uses_nonsecret_reason(tmp_path: Path) -> None:
    windows = list(jpl_analysis_windows())[:2]

    class NetworkClient:
        calls = 0

        def iter_pages(self, query: Any):
            self.calls += 1
            raise requests.Timeout("sentinel-secret-token")
            yield  # pragma: no cover

    client = NetworkClient()
    progress = run_daily_chunks(client, tmp_path, windows, endpoint="timeseries")

    assert client.calls == 1
    assert progress["failed_days"] == [windows[0].day_key]
    assert progress["pending_days"] == [windows[1].day_key]
    assert progress["failure_reasons"] == {windows[0].day_key: "NETWORK_ERROR"}
    assert progress["stop_reason"] == "NETWORK_ERROR"
    assert "sentinel-secret-token" not in (tmp_path / "state" / "progress.json").read_text(
        encoding="utf-8"
    )


def test_unexpected_error_is_checkpointed_then_reraised_without_secret(
    tmp_path: Path,
) -> None:
    windows = list(jpl_analysis_windows())[:2]

    class BuggyClient:
        calls = 0

        def iter_pages(self, query: Any):
            self.calls += 1
            raise RuntimeError("program bug: sentinel-secret-token")
            yield  # pragma: no cover

    client = BuggyClient()
    with pytest.raises(RuntimeError, match="program bug"):
        run_daily_chunks(client, tmp_path, windows, endpoint="timeseries")

    assert client.calls == 1
    persisted_text = (tmp_path / "state" / "progress.json").read_text(encoding="utf-8")
    persisted = json.loads(persisted_text)["endpoints"]["timeseries"]
    assert persisted["failed_days"] == [windows[0].day_key]
    assert persisted["pending_days"] == [windows[1].day_key]
    assert persisted["failure_reasons"] == {windows[0].day_key: "UNEXPECTED_ERROR"}
    assert persisted["stop_reason"] == "UNEXPECTED_ERROR"
    assert "sentinel-secret-token" not in persisted_text


def test_resume_skips_prevalidated_window_without_calling_downloader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = next(jpl_analysis_windows())
    download_day_chunk(
        FakeClient([[page([{"_id": "existing"}], total=1)]]),
        tmp_path,
        window,
        endpoint="timeseries",
    )
    downloader_calls = 0

    def forbidden_downloader(*args: Any, **kwargs: Any) -> Any:
        nonlocal downloader_calls
        downloader_calls += 1
        raise AssertionError("prevalidated window must be skipped")

    monkeypatch.setattr(gate0_module, "download_day_chunk", forbidden_downloader)
    progress = run_daily_chunks(FakeClient([]), tmp_path, [window], endpoint="timeseries")

    assert downloader_calls == 0
    assert progress["completed_days"] == [window.day_key]
    assert progress["failed_days"] == []


def test_unexpected_validation_disk_error_is_checkpointed_then_reraised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = next(jpl_analysis_windows())

    def disk_failure(*args: Any, **kwargs: Any) -> Any:
        raise OSError("disk failure: sentinel-secret-token")

    monkeypatch.setattr(gate0_module, "validate_chunk", disk_failure)
    with pytest.raises(OSError, match="disk failure"):
        run_daily_chunks(FakeClient([]), tmp_path, [window], endpoint="timeseries")

    progress_text = (tmp_path / "state" / "progress.json").read_text(encoding="utf-8")
    progress = json.loads(progress_text)["endpoints"]["timeseries"]
    assert progress["failed_days"] == [window.day_key]
    assert progress["failure_reasons"] == {window.day_key: "UNEXPECTED_ERROR"}
    assert progress["stop_reason"] == "UNEXPECTED_ERROR"
    assert "sentinel-secret-token" not in progress_text
