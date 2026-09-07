from __future__ import annotations

import json
from dataclasses import replace
from datetime import timezone
from pathlib import Path
from typing import Any

import evcf.data.acn_jpl_official_reference as official_reference_module
import pytest
from evcf.data.acn_api import ACNClient, ACNQuery, ACNSchemaError
from evcf.data.acn_jpl_gate0 import JPL_ANALYSIS_END, JPL_ANALYSIS_START
from evcf.data.acn_jpl_month_config import MAY_2019, JPLMonthConfig, jpl_month_config
from evcf.data.acn_jpl_official_reference import (
    OfficialLocalMonthTotalResult,
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


def _official_payload(month: JPLMonthConfig, total: object = 17) -> dict[str, object]:
    query = ACNQuery(
        site="jpl",
        start=month.local_start,
        end=month.local_end,
        timeseries=False,
    )
    return {
        "schema_version": "acn-jpl-official-local-month-total/v1",
        "source": "ACN-Data official REST API",
        "endpoint": query.endpoint,
        "site": "jpl",
        "timezone": month.timezone_name,
        "interval_semantics": "[start,end)",
        "local_start_inclusive": month.local_start.isoformat(),
        "local_end_exclusive": month.local_end.isoformat(),
        "utc_start_inclusive": month.utc_start.isoformat(),
        "utc_end_exclusive": month.utc_end.isoformat(),
        "query_condition": query.condition,
        "official_meta_total": total,
        "request_count": 1,
        "response_fields_consumed": ["_meta.total"],
        "token_stored": False,
    }


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
    assert result.is_reference_valid_for(MAY_2019) is True
    assert result.is_live_verified_for(MAY_2019) is True
    assert result.is_verified_for(MAY_2019) is True
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


def test_manual_and_replaced_official_results_are_never_verified(tmp_path: Path) -> None:
    destination = tmp_path / "private" / "official_local_month_total.json"
    destination.parent.mkdir()
    destination.write_text(json.dumps(_official_payload(MAY_2019)), encoding="utf-8")
    forged = OfficialLocalMonthTotalResult(
        total=17,
        reference_path=destination,
        month=MAY_2019.month,
        local_start_inclusive=MAY_2019.local_start.isoformat(),
        local_end_exclusive=MAY_2019.local_end.isoformat(),
        utc_start_inclusive=MAY_2019.utc_start.isoformat(),
        utc_end_exclusive=MAY_2019.utc_end.isoformat(),
        request_count=1,
    )

    assert forged.is_reference_valid_for(MAY_2019) is False
    assert forged.is_live_verified_for(MAY_2019) is False
    assert forged.is_verified_for(MAY_2019) is False
    assert str(destination) not in repr(forged)

    fake = _Session({"_meta": {"total": 17}})
    authentic_path = tmp_path / "authentic.json"
    authentic = probe_official_local_month_total(
        ACNClient("token", session=fake),  # type: ignore[arg-type]
        authentic_path,
    )
    assert authentic.is_reference_valid_for(MAY_2019) is True
    assert authentic.is_live_verified_for(MAY_2019) is True
    assert authentic.is_verified_for(MAY_2019) is True
    assert replace(authentic).is_reference_valid_for(MAY_2019) is False
    assert replace(authentic).is_live_verified_for(MAY_2019) is False
    assert replace(authentic).is_verified_for(MAY_2019) is False
    assert replace(authentic, total=18).is_verified_for(MAY_2019) is False
    assert authentic.is_verified_for(jpl_month_config("2019-08")) is False


def test_strict_loader_verifies_existing_reference_without_network(tmp_path: Path) -> None:
    destination = tmp_path / "official_local_month_total.json"
    destination.write_text(json.dumps(_official_payload(MAY_2019, 23)), encoding="utf-8")

    loaded = official_reference_module.load_verified_official_local_month_total(destination)

    assert loaded.total == 23
    assert loaded.reference_path == destination
    assert loaded.is_reference_valid_for(MAY_2019) is True
    assert loaded.is_live_verified_for(MAY_2019) is False
    assert loaded.is_verified_for(MAY_2019) is False
    assert str(destination) not in repr(loaded)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "schema",
        "source",
        "endpoint",
        "site",
        "timezone",
        "interval",
        "local_start",
        "local_end",
        "utc_start",
        "utc_end",
        "query",
        "bool_total",
        "negative_total",
        "zero_requests",
        "two_requests",
        "bool_requests",
        "response_fields",
        "token_stored",
    ],
)
def test_strict_loader_rejects_incomplete_or_tampered_contract(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = _official_payload(MAY_2019)
    if mutation == "missing":
        payload.pop("source")
    elif mutation == "extra":
        payload["unexpected"] = "field"
    elif mutation == "schema":
        payload["schema_version"] = "v2"
    elif mutation == "source":
        payload["source"] = "untrusted"
    elif mutation == "endpoint":
        payload["endpoint"] = "sessions/caltech"
    elif mutation == "site":
        payload["site"] = "caltech"
    elif mutation == "timezone":
        payload["timezone"] = "UTC"
    elif mutation == "interval":
        payload["interval_semantics"] = "[start,end]"
    elif mutation == "local_start":
        payload["local_start_inclusive"] = MAY_2019.local_start.isoformat() + "Z"
    elif mutation == "local_end":
        payload["local_end_exclusive"] = MAY_2019.local_end.isoformat() + "Z"
    elif mutation == "utc_start":
        payload["utc_start_inclusive"] = MAY_2019.utc_start.isoformat() + "Z"
    elif mutation == "utc_end":
        payload["utc_end_exclusive"] = MAY_2019.utc_end.isoformat() + "Z"
    elif mutation == "query":
        payload["query_condition"] = "tampered"
    elif mutation == "bool_total":
        payload["official_meta_total"] = True
    elif mutation == "negative_total":
        payload["official_meta_total"] = -1
    elif mutation == "zero_requests":
        payload["request_count"] = 0
    elif mutation == "two_requests":
        payload["request_count"] = 2
    elif mutation == "bool_requests":
        payload["request_count"] = True
    elif mutation == "response_fields":
        payload["response_fields_consumed"] = ["_meta.total", "_items"]
    else:
        payload["token_stored"] = True
    destination = tmp_path / f"{mutation}.json"
    destination.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(official_reference_module.OfficialLocalMonthReferenceError):
        official_reference_module.load_verified_official_local_month_total(destination)


def test_strict_loader_rejects_missing_partial_and_wrong_month(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(official_reference_module.OfficialLocalMonthReferenceError):
        official_reference_module.load_verified_official_local_month_total(missing)

    destination = tmp_path / "official_local_month_total.json"
    destination.write_text(json.dumps(_official_payload(MAY_2019)), encoding="utf-8")
    partial = destination.with_suffix(destination.suffix + ".partial")
    partial.write_text("incomplete", encoding="utf-8")
    with pytest.raises(official_reference_module.OfficialLocalMonthReferenceError):
        official_reference_module.load_verified_official_local_month_total(destination)

    partial.unlink()
    with pytest.raises(official_reference_module.OfficialLocalMonthReferenceError):
        official_reference_module.load_verified_official_local_month_total(
            destination,
            month=jpl_month_config("2019-08"),
        )
