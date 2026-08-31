from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path
from typing import Any

import pytest
from evcf.data.acn_api import ACNClient, ACNSchemaError
from evcf.data.acn_jpl_gate0 import JPL_ANALYSIS_END, JPL_ANALYSIS_START
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
    assert payload["utc_start_inclusive"] == JPL_ANALYSIS_START.astimezone(
        timezone.utc
    ).isoformat()
    assert payload["utc_end_exclusive"] == JPL_ANALYSIS_END.astimezone(
        timezone.utc
    ).isoformat()
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
