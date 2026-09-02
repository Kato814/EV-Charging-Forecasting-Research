from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Any

import pytest
from evcf.data.acn_api import ACNClient, ACNSchemaError
from evcf.data.acn_jpl_gate0 import JPL_ANALYSIS_END, JPL_ANALYSIS_START
from evcf.data.acn_jpl_month_config import MAY_2019, jpl_month_config
from evcf.data.acn_jpl_official_reference import (
    probe_official_local_month_total,
)


class _Response:
    status_code = 200

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def json(self) -> dict[str, Any]:
        return self.payload

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.response = _Response(payload)
        self.calls: list[dict[str, Any]] = []
        self.auth: tuple[str, str] | None = None
        self.headers: dict[str, str] = {}

    def get(self, url: str, *, params: Any = None, timeout: Any = None) -> _Response:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return self.response


def test_probe_reads_one_meta_total_and_writes_secret_free_contract(
    tmp_path: Path,
) -> None:
    fake = _Session(
        {
            "_meta": {"total": 1644},
            "_items": [{"sessionID": "must-not-be-consumed-or-written"}],
            "_links": {"next": {"href": "sessions/jpl?page=2"}},
        }
    )
    client = ACNClient("never-persist-this-token", session=fake)  # type: ignore[arg-type]
    destination = tmp_path / "state" / "official_local_month_total.json"

    result = probe_official_local_month_total(client, destination)

    assert result.total == 1644
    assert result.month == "2019-05"
    assert result.local_start_inclusive == JPL_ANALYSIS_START.isoformat()
    assert result.local_end_exclusive == JPL_ANALYSIS_END.isoformat()
    assert result.utc_start_inclusive == MAY_2019.utc_start.isoformat()
    assert result.utc_end_exclusive == MAY_2019.utc_end.isoformat()
    assert result.request_count == 1
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["url"].endswith("/api/v1/sessions/jpl")
    assert call["params"]["max_results"] == 1
    assert "connectionTime >=" in call["params"]["where"]
    assert "connectionTime <" in call["params"]["where"]
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["official_meta_total"] == 1644
    assert payload["request_count"] == 1
    assert payload["response_fields_consumed"] == ["_meta.total"]
    assert payload["local_start_inclusive"] == JPL_ANALYSIS_START.isoformat()
    assert payload["local_end_exclusive"] == JPL_ANALYSIS_END.isoformat()
    assert payload["utc_start_inclusive"] == JPL_ANALYSIS_START.astimezone(timezone.utc).isoformat()
    assert payload["utc_end_exclusive"] == JPL_ANALYSIS_END.astimezone(timezone.utc).isoformat()
    serialized = destination.read_text(encoding="utf-8")
    assert "must-not-be-consumed-or-written" not in serialized
    assert "never-persist-this-token" not in serialized
    assert payload["token_stored"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"_meta": {}},
        {"_meta": {"total": True}},
        {"_meta": {"total": -1}},
        {"_meta": {"total": "1644"}},
    ],
)
def test_probe_rejects_invalid_official_total_without_writing_state(
    tmp_path: Path,
    payload: dict[str, Any],
) -> None:
    fake = _Session(payload)
    client = ACNClient("token", session=fake)  # type: ignore[arg-type]
    destination = tmp_path / "official_local_month_total.json"

    with pytest.raises(ACNSchemaError, match="_meta.total"):
        probe_official_local_month_total(client, destination)

    assert len(fake.calls) == 1
    assert not destination.exists()


def test_probe_refuses_to_overwrite_existing_reference_before_network_call(
    tmp_path: Path,
) -> None:
    fake = _Session({"_meta": {"total": 1644}})
    client = ACNClient("token", session=fake)  # type: ignore[arg-type]
    destination = tmp_path / "official_local_month_total.json"
    destination.write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        probe_official_local_month_total(client, destination)

    assert fake.calls == []


def test_probe_accepts_generic_month_and_still_makes_exactly_one_request(
    tmp_path: Path,
) -> None:
    fake = _Session({"_meta": {"total": 37}})
    client = ACNClient("generic-month-token", session=fake)  # type: ignore[arg-type]
    destination = tmp_path / "official_local_month_total.json"
    august = jpl_month_config("2019-08")

    result = probe_official_local_month_total(client, destination, month=august)

    assert result.total == 37
    assert result.month == "2019-08"
    assert result.local_start_inclusive == august.local_start.isoformat()
    assert result.local_end_exclusive == august.local_end.isoformat()
    assert result.utc_start_inclusive == august.utc_start.isoformat()
    assert result.utc_end_exclusive == august.utc_end.isoformat()
    assert result.request_count == 1
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["params"]["where"] == (
        'connectionTime >= "Thu, 01 Aug 2019 07:00:00 GMT" and '
        'connectionTime < "Sun, 01 Sep 2019 07:00:00 GMT"'
    )
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["timezone"] == august.timezone_name
    assert payload["local_start_inclusive"] == august.local_start.isoformat()
    assert payload["local_end_exclusive"] == august.local_end.isoformat()
    assert payload["utc_start_inclusive"] == august.utc_start.isoformat()
    assert payload["utc_end_exclusive"] == august.utc_end.isoformat()
    assert "generic-month-token" not in destination.read_text(encoding="utf-8")


def test_default_may_reference_bytes_remain_legacy_compatible(tmp_path: Path) -> None:
    fake = _Session({"_meta": {"total": 1644}})
    client = ACNClient("token", session=fake)  # type: ignore[arg-type]
    destination = tmp_path / "official_local_month_total.json"
    expected_query = {
        "endpoint": "sessions/jpl",
        "interval_semantics": "[start,end)",
        "local_end_exclusive": JPL_ANALYSIS_END.isoformat(),
        "local_start_inclusive": JPL_ANALYSIS_START.isoformat(),
        "official_meta_total": 1644,
        "query_condition": (
            'connectionTime >= "Wed, 01 May 2019 07:00:00 GMT" and '
            'connectionTime < "Sat, 01 Jun 2019 07:00:00 GMT"'
        ),
        "request_count": 1,
        "response_fields_consumed": ["_meta.total"],
        "schema_version": "acn-jpl-official-local-month-total/v1",
        "site": "jpl",
        "source": "ACN-Data official REST API",
        "timezone": "America/Los_Angeles",
        "token_stored": False,
        "utc_end_exclusive": JPL_ANALYSIS_END.astimezone(timezone.utc).isoformat(),
        "utc_start_inclusive": JPL_ANALYSIS_START.astimezone(timezone.utc).isoformat(),
    }
    expected_bytes = (json.dumps(expected_query, indent=2, sort_keys=True) + "\n").encode()

    probe_official_local_month_total(client, destination)

    assert MAY_2019.local_start == JPL_ANALYSIS_START
    assert MAY_2019.local_end == JPL_ANALYSIS_END
    assert destination.read_bytes() == expected_bytes


def test_probe_rejects_existing_partial_before_network_call(tmp_path: Path) -> None:
    fake = _Session({"_meta": {"total": 1644}})
    client = ACNClient("token", session=fake)  # type: ignore[arg-type]
    destination = tmp_path / "official_local_month_total.json"
    partial = destination.with_suffix(destination.suffix + ".partial")
    partial.write_text("incomplete", encoding="utf-8")

    with pytest.raises(FileExistsError):
        probe_official_local_month_total(client, destination)

    assert fake.calls == []
    assert not destination.exists()
    assert partial.read_text(encoding="utf-8") == "incomplete"


def test_probe_removes_partial_when_atomic_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Session({"_meta": {"total": 1644}})
    client = ACNClient("write-failure-token", session=fake)  # type: ignore[arg-type]
    destination = tmp_path / "official_local_month_total.json"

    def fail_replace(source: object, target: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("evcf.data.acn_jpl_official_reference.os.replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        probe_official_local_month_total(client, destination)

    assert len(fake.calls) == 1
    assert not destination.exists()
    assert not destination.with_suffix(destination.suffix + ".partial").exists()
