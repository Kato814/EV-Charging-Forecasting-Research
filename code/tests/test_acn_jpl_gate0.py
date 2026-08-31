from __future__ import annotations

import gzip
import hashlib
import json
from copy import deepcopy
from datetime import date, timezone
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from evcf.data.acn_api import ACNClient
from evcf.data.acn_jpl_gate0 import (
    JPL_ACQUISITION_END,
    JPL_ACQUISITION_START,
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

    result = download_day_chunk(
        FakeClient([[page([{"_id": "id-1"}], total=None)]]),
        tmp_path,
        window,
        endpoint="metadata",
    )

    assert result.remote_total_reported is None
    assert not result.complete_for_query
    validation = validate_chunk(
        result.data_path,
        result.manifest_path,
        window=window,
        endpoint="metadata",
    )
    assert not validation.valid
    assert validation.reason == "manifest is not complete for query"


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
                raise RuntimeError("request failed: sentinel-secret-token")
            yield page([{"_id": f"id-{self.calls}"}], total=1)

    first_client = FailingMiddleClient()
    first_progress = run_daily_chunks(
        first_client,
        tmp_path,
        windows,
        endpoint="metadata",
    )

    progress_path = tmp_path / "state" / "progress.json"
    assert first_client.calls == 3
    progress_document = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress_document["endpoints"]["metadata"] == first_progress
    assert first_progress["pending_days"] == []
    assert first_progress["completed_days"] == [windows[0].day_key, windows[2].day_key]
    assert first_progress["failed_days"] == [windows[1].day_key]
    assert first_progress["last_success"] == windows[2].day_key
    assert first_progress["retry_count"] == 1
    assert not progress_path.with_suffix(".json.partial").exists()
    assert "sentinel-secret-token" not in progress_path.read_text(encoding="utf-8")

    resume_client = FakeClient([[page([{"_id": "recovered"}], total=1)]])
    resumed = run_daily_chunks(
        resume_client,
        tmp_path,
        windows,
        endpoint="metadata",
    )

    assert len(resume_client.queries) == 1
    assert resumed["pending_days"] == []
    assert resumed["completed_days"] == [window.day_key for window in windows]
    assert resumed["failed_days"] == []
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
            raise RuntimeError("transient failure")
            yield  # pragma: no cover

    first = run_daily_chunks(
        FailingClient(),
        tmp_path,
        [window],
        endpoint="metadata",
    )
    assert first["failed_days"] == [window.day_key]

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
