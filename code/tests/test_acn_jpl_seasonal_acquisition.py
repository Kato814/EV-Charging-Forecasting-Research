from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import evcf.data.acn_jpl_month_config as month_config_module
import pytest
from evcf.data.acn_api import ACNClient
from evcf.data.acn_audit import parse_acn_datetime
from evcf.data.acn_jpl_gate0 import _ChunkIdentityInventory
from evcf.data.acn_jpl_month_config import (
    EXPECTED_COMPLETE_METADATA_FILE_COUNT,
    SEASONAL_MONTHS,
    CompleteMetadataScope,
    jpl_month_config,
    load_verified_complete_metadata,
    summarize_complete_metadata,
)
from evcf.data.acn_jpl_official_reference import (
    OfficialLocalMonthTotalResult,
    load_verified_official_local_month_total,
    probe_official_local_month_total,
)
from evcf.data.acn_jpl_seasonal_acquisition import (
    SeasonalAuthorizationError,
    acquire_jpl_month,
    run_seasonal_acquisition,
)


def _record(
    index: int,
    connection: datetime,
    disconnect: datetime | None = None,
) -> dict[str, Any]:
    return {
        "_id": f"private-object-{index:04d}",
        "sessionID": f"private-session-{index:04d}",
        "connectionTime": format_datetime(connection.astimezone(timezone.utc), usegmt=True),
        "disconnectTime": format_datetime(
            (disconnect or connection + timedelta(hours=1)).astimezone(timezone.utc),
            usegmt=True,
        ),
        "chargingCurrent": {"timestamps": [], "current": []},
        "pilotSignal": {"timestamps": [], "pilot": []},
    }


def _verified_scope(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    month: str,
    local_count: int = 3,
    carry_count: int = 0,
) -> CompleteMetadataScope:
    config = jpl_month_config(month)
    records = [
        _record(index, config.utc_start + timedelta(days=index, minutes=1))
        for index in range(local_count)
    ]
    records.extend(
        _record(
            100 + index,
            config.utc_start - timedelta(days=index + 1),
            config.utc_start + timedelta(minutes=index + 1),
        )
        for index in range(carry_count)
    )
    while len(records) < EXPECTED_COMPLETE_METADATA_FILE_COUNT:
        index = 1000 + len(records)
        records.append(
            _record(
                index,
                datetime(2018, 1, 1, tzinfo=timezone.utc) + timedelta(days=index),
            )
        )
    assert len(records) == EXPECTED_COMPLETE_METADATA_FILE_COUNT

    root.mkdir(parents=True)
    inventory = hashlib.sha256()
    for index, record in enumerate(records):
        data_path = root / f"part-{index:02d}.jsonl.gz"
        with gzip.open(data_path, "wt", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
        manifest = {
            "schema_version": 1,
            "endpoint": "sessions/jpl",
            "site": "jpl",
            "mode": "metadata",
            "record_count": 1,
            "source_total": 1,
            "sha256": digest,
        }
        data_path.with_name(data_path.name + ".manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        inventory.update(f"{data_path.name}\0{digest}\0{1}\n".encode())

    monkeypatch.setattr(
        month_config_module,
        "EXPECTED_COMPLETE_METADATA_RECORD_COUNT",
        len(records),
    )
    monkeypatch.setattr(
        month_config_module,
        "EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256",
        inventory.hexdigest(),
    )
    scope = load_verified_complete_metadata(root, config)
    assert scope.is_verified_for(config)
    return scope


class _Response:
    status_code = 200

    def __init__(self, total: int) -> None:
        self._total = total

    def json(self) -> dict[str, Any]:
        return {"_meta": {"total": self._total}}

    def raise_for_status(self) -> None:
        return None


class _OfficialSession:
    def __init__(self, total: int) -> None:
        self.total = total
        self.calls: list[dict[str, Any]] = []
        self.auth: tuple[str, str] | None = None
        self.headers: dict[str, str] = {}

    def get(self, url: str, *, params: Any = None, timeout: Any = None) -> _Response:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return _Response(self.total)


class _LiveProbe:
    def __init__(self, destination: Path, total: int) -> None:
        self.destination = destination
        self.session = _OfficialSession(total)
        self.calls: list[str] = []

    def __call__(self, config: Any) -> Any:
        self.calls.append(config.month)
        return probe_official_local_month_total(
            ACNClient("probe-token", session=self.session),  # type: ignore[arg-type]
            self.destination,
            month=config,
        )


class _CarryClient:
    def __init__(self, scope: CompleteMetadataScope) -> None:
        self.records = {record["sessionID"]: dict(record) for record in scope.carry_in_records}
        self.queries: list[Any] = []

    def iter_pages(self, query: Any) -> Any:
        self.queries.append(query)
        record = self.records[query.session_id]
        yield {"_meta": {"total": 1}, "_items": [record], "_links": {}}


class _FullClient(_CarryClient):
    def __init__(self, scope: CompleteMetadataScope) -> None:
        super().__init__(scope)
        self.local_records = tuple(dict(record) for record in scope.local_month_records)

    def iter_pages(self, query: Any) -> Any:
        self.queries.append(query)
        if query.session_id is not None:
            items = [self.records[query.session_id]]
        else:
            items = [
                record
                for record in self.local_records
                if query.start_utc <= parse_acn_datetime(record["connectionTime"]) < query.end_utc
            ]
        yield {"_meta": {"total": len(items)}, "_items": items, "_links": {}}


def _daily_runner(scope: CompleteMetadataScope, observed: dict[str, Any]) -> Any:
    pairs = tuple((record["_id"], record["sessionID"]) for record in scope.local_month_records)

    def run(
        client: Any,
        root: Path,
        windows: Any,
        *,
        endpoint: str,
        _private_validation_sink: dict[str, _ChunkIdentityInventory],
    ) -> dict[str, Any]:
        ordered = tuple(windows)
        observed["windows"] = ordered
        observed["endpoint"] = endpoint
        for index, window in enumerate(ordered):
            _private_validation_sink[window.day_key] = _ChunkIdentityInventory(
                identifier_pairs=pairs if index == 0 else (),
            )
        return {
            "completed_days": [window.day_key for window in ordered],
            "pending_days": [],
            "failed_days": [],
            "retry_count": 0,
        }

    return run


def test_authorization_stops_before_scope_probe_factory_or_directories(tmp_path: Path) -> None:
    touched: list[str] = []

    class _Scope:
        def is_verified_for(self, config: Any) -> bool:
            touched.append("scope")
            return True

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        touched.append("called")
        raise AssertionError("must stop before side effects")

    raw_root = tmp_path / "must-not-exist"
    with pytest.raises(SeasonalAuthorizationError):
        acquire_jpl_month(
            authorized=False,
            config=jpl_month_config("2019-02"),
            scope=_Scope(),  # type: ignore[arg-type]
            official_probe=forbidden,
            raw_root=raw_root,
            ts_client_factory=forbidden,
        )

    assert touched == []
    assert not raw_root.exists()


def test_unverified_scope_is_rejected_before_live_probe_or_ts_factory(tmp_path: Path) -> None:
    config = jpl_month_config("2019-02")
    unverified = summarize_complete_metadata([], config)
    calls: list[str] = []

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        calls.append("called")
        raise AssertionError("unverified scope must stop")

    result = acquire_jpl_month(
        authorized=True,
        config=config,
        scope=unverified,
        official_probe=forbidden,
        raw_root=tmp_path / "month",
        ts_client_factory=forbidden,
    )

    assert result.status == "METADATA_GATE_FAIL"
    assert result.reason_codes == ("SCOPE_NOT_VERIFIED",)
    assert calls == []
    assert not (tmp_path / "month").exists()


def test_live_official_mismatch_stops_before_ts_factory_and_ts_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = jpl_month_config("2019-02")
    scope = _verified_scope(tmp_path / "metadata", monkeypatch, month=config.month)
    month_root = tmp_path / config.month
    probe = _LiveProbe(month_root / "state" / "official_local_month_total.json", 2)
    factory_calls: list[str] = []

    def forbidden_factory() -> Any:
        factory_calls.append("factory")
        raise AssertionError("count mismatch must stop before /ts client")

    result = acquire_jpl_month(
        authorized=True,
        config=config,
        scope=scope,
        official_probe=probe,
        raw_root=month_root,
        ts_client_factory=forbidden_factory,
    )

    assert scope.local_month_session_count == 3
    assert result.status == "METADATA_GATE_FAIL"
    assert result.reason_codes == ("OFFICIAL_TOTAL_MISMATCH",)
    assert probe.calls == [config.month]
    assert len(probe.session.calls) == 1
    assert factory_calls == []
    assert (month_root / "state" / "official_local_month_total.json").is_file()
    assert not (month_root / "timeseries").exists()
    assert not (month_root / "manifests" / "timeseries").exists()
    assert not (month_root / "state" / "progress.json").exists()


def test_ts_factory_exception_is_reduced_to_static_reason_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = jpl_month_config("2019-02")
    scope = _verified_scope(tmp_path / "metadata", monkeypatch, month=config.month)
    root = tmp_path / config.month
    probe = _LiveProbe(root / "state" / "official_local_month_total.json", 3)

    def fail_factory() -> Any:
        raise RuntimeError("https://private.invalid/?token=never-echo")

    result = acquire_jpl_month(
        authorized=True,
        config=config,
        scope=scope,
        official_probe=probe,
        raw_root=root,
        ts_client_factory=fail_factory,
    )

    assert result.status == "INCOMPLETE"
    assert result.reason_codes == ("UNEXPECTED_ERROR",)
    assert "private.invalid" not in repr(result)


def test_scope_mutated_during_live_probe_is_rejected_before_ts_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = jpl_month_config("2019-02")
    scope = _verified_scope(tmp_path / "metadata", monkeypatch, month=config.month)
    root = tmp_path / config.month
    live = _LiveProbe(root / "state" / "official.json", 3)
    factory_calls: list[str] = []

    def mutate_after_probe(month_config: Any) -> Any:
        result = live(month_config)
        scope.local_month_records[0]["sessionID"] = "tampered-after-gate"
        return result

    def factory() -> Any:
        factory_calls.append("factory")
        return _CarryClient(scope)

    result = acquire_jpl_month(
        authorized=True,
        config=config,
        scope=scope,
        official_probe=mutate_after_probe,
        raw_root=root,
        ts_client_factory=factory,
    )

    assert result.status == "METADATA_GATE_FAIL"
    assert result.reason_codes == ("SCOPE_NOT_VERIFIED",)
    assert factory_calls == []


def test_offline_manual_replaced_wrong_month_and_naked_probe_results_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = jpl_month_config("2019-02")
    scope = _verified_scope(tmp_path / "metadata", monkeypatch, month=config.month)
    live_path = tmp_path / "references" / "live-feb.json"
    live = _LiveProbe(live_path, 3)(config)
    offline = load_verified_official_local_month_total(live_path, month=config)
    wrong_month = _LiveProbe(tmp_path / "references" / "live-aug.json", 3)(
        jpl_month_config("2019-08")
    )
    manual = OfficialLocalMonthTotalResult(
        total=3,
        reference_path=live_path,
        month=config.month,
        local_start_inclusive=config.local_start.isoformat(),
        local_end_exclusive=config.local_end.isoformat(),
        utc_start_inclusive=config.utc_start.isoformat(),
        utc_end_exclusive=config.utc_end.isoformat(),
        request_count=0,  # type: ignore[arg-type]
    )
    candidates: tuple[object, ...] = (offline, replace(live), wrong_month, manual, 3)
    factory_calls: list[str] = []

    def factory() -> Any:
        factory_calls.append("factory")
        raise AssertionError("untrusted official evidence must stop")

    for index, candidate in enumerate(candidates):
        calls = 0

        def probe(month_config: Any, value: object = candidate) -> object:
            nonlocal calls
            calls += 1
            assert month_config is config
            return value

        result = acquire_jpl_month(
            authorized=True,
            config=config,
            scope=scope,
            official_probe=probe,  # type: ignore[arg-type]
            raw_root=tmp_path / f"raw-{index}",
            ts_client_factory=factory,
        )
        assert result.status == "METADATA_GATE_FAIL"
        assert result.reason_codes == ("OFFICIAL_PROBE_NOT_LIVE",)
        assert calls == 1

    assert factory_calls == []


@pytest.mark.parametrize("month", SEASONAL_MONTHS)
@pytest.mark.parametrize("carry_count", [0, 1, 2])
def test_dynamic_day_windows_and_zero_one_many_carry_use_stable_ordinals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    month: str,
    carry_count: int,
) -> None:
    config = jpl_month_config(month)
    scope = _verified_scope(
        tmp_path / "metadata",
        monkeypatch,
        month=month,
        carry_count=carry_count,
    )
    root = tmp_path / month
    probe = _LiveProbe(root / "state" / "official_local_month_total.json", 3)
    observed: dict[str, Any] = {}
    client = _CarryClient(scope)

    result = acquire_jpl_month(
        authorized=True,
        config=config,
        scope=scope,
        official_probe=probe,
        raw_root=root,
        ts_client_factory=lambda: client,
        daily_runner=_daily_runner(scope, observed),
        downloaded_at_utc=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )

    assert result.status == "COMPLETE"
    assert result.valid_daily_chunks == config.day_count
    assert result.local_session_count == 3
    assert result.daily_record_count == 3
    assert result.carry_in_count == carry_count
    assert result.carry_in_completed == carry_count
    assert result.combined_record_count == 3 + carry_count
    assert tuple(observed["windows"]) == config.day_windows
    assert len(client.queries) == carry_count
    carry_data = sorted((root / "timeseries" / "carry_in").glob("*.jsonl.gz"))
    carry_manifests = sorted((root / "manifests" / "carry_in").glob("*.manifest.json"))
    assert [path.name for path in carry_data] == [
        f"carry-{index:04d}.jsonl.gz" for index in range(1, carry_count + 1)
    ]
    assert [path.name for path in carry_manifests] == [
        f"carry-{index:04d}.manifest.json" for index in range(1, carry_count + 1)
    ]
    assert result.raw_inventory_sha256 is not None
    assert "private" not in repr(result).lower()


def test_default_daily_chunks_and_carry_resume_without_network_or_byte_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = jpl_month_config("2019-02")
    scope = _verified_scope(
        tmp_path / "metadata",
        monkeypatch,
        month=config.month,
        carry_count=2,
    )
    root = tmp_path / config.month
    first_client = _FullClient(scope)
    first = acquire_jpl_month(
        authorized=True,
        config=config,
        scope=scope,
        official_probe=_LiveProbe(root / "state" / "official-first.json", 3),
        raw_root=root,
        ts_client_factory=lambda: first_client,
        downloaded_at_utc=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    tracked = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and (
            path.name.endswith(".jsonl.gz")
            or path.name.endswith(".manifest.json")
            or path.name == "progress.json"
        )
    )
    before = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tracked
    }

    second_client = _FullClient(scope)
    second = acquire_jpl_month(
        authorized=True,
        config=config,
        scope=scope,
        official_probe=_LiveProbe(root / "state" / "official-second.json", 3),
        raw_root=root,
        ts_client_factory=lambda: second_client,
        downloaded_at_utc=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )
    after = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tracked
    }

    assert first.status == second.status == "COMPLETE"
    assert len(first_client.queries) == config.day_count + 2
    assert second_client.queries == []
    assert before == after
    assert first.raw_inventory_sha256 == second.raw_inventory_sha256
    assert len(list((root / "timeseries").glob("*.jsonl.gz"))) == config.day_count
    assert len(list((root / "manifests" / "timeseries").glob("*.manifest.json"))) == (
        config.day_count
    )
    assert not list(root.rglob("*.partial"))


def test_unexpected_carry_ordinal_cannot_be_ignored_as_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = jpl_month_config("2019-02")
    scope = _verified_scope(
        tmp_path / "metadata",
        monkeypatch,
        month=config.month,
        carry_count=1,
    )
    root = tmp_path / config.month
    first = acquire_jpl_month(
        authorized=True,
        config=config,
        scope=scope,
        official_probe=_LiveProbe(root / "state" / "official-first.json", 3),
        raw_root=root,
        ts_client_factory=lambda: _FullClient(scope),
        downloaded_at_utc=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    assert first.status == "COMPLETE"

    source_data = root / "timeseries" / "carry_in" / "carry-0001.jsonl.gz"
    source_manifest = root / "manifests" / "carry_in" / "carry-0001.manifest.json"
    orphan_data = source_data.with_name("carry-0002.jsonl.gz")
    orphan_manifest = source_manifest.with_name("carry-0002.manifest.json")
    orphan_data.write_bytes(source_data.read_bytes())
    payload = json.loads(source_manifest.read_text(encoding="utf-8"))
    payload["ordinal"] = 2
    payload["output_file"] = orphan_data.name
    orphan_manifest.write_text(json.dumps(payload), encoding="utf-8")

    second = acquire_jpl_month(
        authorized=True,
        config=config,
        scope=scope,
        official_probe=_LiveProbe(root / "state" / "official-second.json", 3),
        raw_root=root,
        ts_client_factory=lambda: _FullClient(scope),
    )

    assert second.status == "INCOMPLETE"
    assert second.reason_codes == ("CARRY_INCOMPLETE",)


def test_fixed_order_runner_isolates_failure_and_continues_later_months() -> None:
    observed: list[str] = []

    def runner(config: Any) -> Any:
        observed.append(config.month)
        if config.month == "2019-08":
            raise RuntimeError("https://secret.invalid/?token=do-not-echo")
        return {"month": config.month, "status": "COMPLETE", "reason_codes": ()}

    result = run_seasonal_acquisition(authorized=True, month_runner=runner)

    assert observed == list(SEASONAL_MONTHS)
    assert [item["month"] for item in result["months"]] == list(SEASONAL_MONTHS)
    assert [item["status"] for item in result["months"]] == [
        "COMPLETE",
        "FAILED",
        "COMPLETE",
    ]
    assert result["months"][1]["reason_codes"] == ["UNEXPECTED_ERROR"]
    assert "secret.invalid" not in repr(result)


@pytest.mark.parametrize("concurrency", [0, 3, True])
def test_invalid_concurrency_stops_before_month_runner(concurrency: object) -> None:
    calls: list[str] = []

    with pytest.raises(ValueError, match="1 or 2"):
        run_seasonal_acquisition(
            authorized=True,
            concurrency=concurrency,  # type: ignore[arg-type]
            month_runner=lambda config: calls.append(config.month),
        )

    assert calls == []


@pytest.mark.parametrize(
    "months",
    [
        (jpl_month_config("2019-08"), jpl_month_config("2019-02")),
        (jpl_month_config("2019-02"), jpl_month_config("2019-02")),
    ],
)
def test_fixed_order_runner_rejects_reordering_and_duplicates(months: tuple[Any, ...]) -> None:
    with pytest.raises(ValueError, match="fixed seasonal order"):
        run_seasonal_acquisition(
            authorized=True,
            months=months,
            month_runner=lambda config: {},
        )
