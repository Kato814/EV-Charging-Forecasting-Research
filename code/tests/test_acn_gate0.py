from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from evcf.data.acn_api import (
    ACNAuthenticationError,
    ACNClient,
    ACNQuery,
    download_sessions,
    parse_iso_datetime,
)
from evcf.data.acn_audit import audit_sessions, online_session_snapshot


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("HTTP failure")


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.auth: tuple[str, str] | None = None
        self.headers: dict[str, str] = {}

    def get(self, url: str, *, params: Any = None, timeout: Any = None) -> FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return self.responses.pop(0)


def stamp(hour: int, minute: int = 0) -> str:
    return f"Mon, 01 Jan 2024 {hour:02d}:{minute:02d}:00 GMT"


def session_record(session_id: str = "s1") -> dict[str, Any]:
    return {
        "_id": f"id-{session_id}",
        "sessionID": session_id,
        "siteID": "caltech",
        "stationID": "CA-1",
        "spaceID": "A1",
        "clusterID": "garage",
        "timezone": "America/Los_Angeles",
        "connectionTime": stamp(8),
        "disconnectTime": stamp(12),
        "doneChargingTime": stamp(11),
        "kWhDelivered": 12.0,
        "chargingCurrent": {
            "timestamps": [stamp(8), stamp(8, 5), stamp(8, 10)],
            "values": [16.0, 16.0, 15.0],
        },
        "pilotSignal": {
            "timestamps": [stamp(8), stamp(8, 5), stamp(8, 10)],
            "values": [32.0, 32.0, 32.0],
        },
        "userInputs": [
            {
                "modifiedAt": stamp(8, 2),
                "requestedDeparture": stamp(12),
                "kWhRequested": 15.0,
            },
            {
                "modifiedAt": stamp(10),
                "requestedDeparture": stamp(13),
                "kWhRequested": 20.0,
            },
        ],
    }


def test_query_requires_timezone_and_uses_half_open_window() -> None:
    naive_start = parse_iso_datetime("2024-01-01T00:00:00Z").replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        ACNQuery(
            site="caltech",
            start=naive_start,
            end=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
    query = ACNQuery(
        site="caltech",
        start=parse_iso_datetime("2024-01-01T00:00:00Z"),
        end=parse_iso_datetime("2024-01-02T00:00:00+00:00"),
    )
    assert "connectionTime >=" in query.condition
    assert "connectionTime <" in query.condition
    assert "connectionTime <=" not in query.condition


def test_client_follows_relative_next_links_and_uses_basic_auth() -> None:
    fake = FakeSession(
        [
            FakeResponse(
                {
                    "_items": [session_record("s1")],
                    "_links": {"next": {"href": "sessions/caltech?page=2"}},
                    "_meta": {"total": 2},
                }
            ),
            FakeResponse(
                {
                    "_items": [session_record("s2")],
                    "_links": {},
                    "_meta": {"total": 2},
                }
            ),
        ]
    )
    client = ACNClient("secret-token", session=fake)  # type: ignore[arg-type]
    query = ACNQuery(
        site="caltech",
        start=parse_iso_datetime("2024-01-01T00:00:00Z"),
        end=parse_iso_datetime("2024-01-02T00:00:00Z"),
    )
    assert [item["sessionID"] for item in client.iter_sessions(query)] == ["s1", "s2"]
    assert fake.auth == ("secret-token", "")
    assert fake.calls[1]["url"].endswith("/api/v1/sessions/caltech?page=2")
    assert "secret-token" not in json.dumps(fake.calls)


def test_download_is_atomic_and_manifest_never_contains_token() -> None:
    fake = FakeSession(
        [
            FakeResponse(
                {
                    "_items": [session_record("s1")],
                    "_links": {},
                    "_meta": {"total": 1},
                }
            )
        ]
    )
    client = ACNClient("do-not-store-me", session=fake)  # type: ignore[arg-type]
    query = ACNQuery(
        site="caltech",
        start=parse_iso_datetime("2024-01-01T00:00:00Z"),
        end=parse_iso_datetime("2024-01-02T00:00:00Z"),
    )
    with TemporaryDirectory() as temporary:
        output = Path(temporary) / "sessions.jsonl"
        result = download_sessions(client, query, output)
        assert result.record_count == 1
        assert result.complete
        assert output.exists()
        assert not output.with_suffix(".jsonl.partial").exists()
        manifest_text = result.manifest_path.read_text(encoding="utf-8")
        assert "do-not-store-me" not in manifest_text
        manifest = json.loads(manifest_text)
        assert manifest["authentication"]["token_stored"] is False
        assert manifest["sha256"] == result.sha256


def test_audit_and_online_snapshot_enforce_issue_time_boundary() -> None:
    record = session_record()
    report = audit_sessions([record, record])
    assert report.record_count == 2
    assert report.duplicate_session_ids == ["s1"]
    assert report.sessions_with_charging_current == 2
    assert report.sessions_with_requested_energy == 2
    assert any("not a direct active-power" in warning for warning in report.semantic_warnings)

    issue_time = datetime(2024, 1, 1, 8, 7, tzinfo=timezone.utc)
    snapshot = online_session_snapshot(record, issue_time)
    assert snapshot is not None
    assert "disconnectTime" not in snapshot
    assert "doneChargingTime" not in snapshot
    assert "kWhDelivered" not in snapshot
    assert snapshot["chargingCurrent"]["values"] == [16.0, 16.0]
    assert len(snapshot["userInputs"]) == 1


def test_missing_environment_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACN_API_TOKEN", raising=False)
    with pytest.raises(ACNAuthenticationError, match="Missing ACN_API_TOKEN"):
        ACNClient.from_env()
