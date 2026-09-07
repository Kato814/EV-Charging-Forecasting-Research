from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import pytest
from evcf.data import acn_jpl_month_config as month_config_module
from evcf.data.acn_api import ACNQuery
from evcf.data.acn_jpl_month_config import SEASONAL_MONTHS, jpl_month_config

from scripts import acquire_jpl_seasonal as seasonal_cli_module
from scripts.acquire_jpl_seasonal import (
    SEASONAL_AUTHORIZATION_MESSAGE,
    SEASONAL_MISSING_TOKEN_MESSAGE,
    build_parser,
    run_seasonal_cli,
)


class _ForbiddenEnvironment(dict[str, str]):
    def get(self, key: str, default: Any = None) -> Any:
        raise AssertionError(f"environment must not be read: {key} {default}")


def test_unauthorized_stops_before_environment_executor_or_directories(tmp_path: Path) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    metadata_root = tmp_path / "metadata-must-not-exist"
    raw_root = tmp_path / "raw-must-not-exist"

    def forbidden(**kwargs: Any) -> Any:
        raise AssertionError("unauthorized CLI must stop immediately")

    status = run_seasonal_cli(
        authorized=False,
        metadata_root=metadata_root,
        raw_root=raw_root,
        environ=_ForbiddenEnvironment(),
        month_executor=forbidden,
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 2
    assert stdout.getvalue() == SEASONAL_AUTHORIZATION_MESSAGE + "\n"
    assert stderr.getvalue() == ""
    assert not metadata_root.exists()
    assert not raw_root.exists()


def test_production_main_has_no_stdout_side_effect_before_literal_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    class _ForbiddenReconfigure:
        def reconfigure(self, **kwargs: Any) -> None:
            raise AssertionError(f"stdout must not be reconfigured: {kwargs}")

    def fake_run(**kwargs: Any) -> int:
        calls.append(kwargs["authorized"])
        return 2

    monkeypatch.setattr(seasonal_cli_module.sys, "stdout", _ForbiddenReconfigure())
    monkeypatch.setattr(seasonal_cli_module, "run_seasonal_cli", fake_run)
    metadata_root = tmp_path / "metadata-must-not-be-read"
    raw_root = tmp_path / "raw-must-not-be-created"

    status = seasonal_cli_module.main(
        [
            "--metadata-root",
            str(metadata_root),
            "--raw-root",
            str(raw_root),
        ]
    )

    assert status == 2
    assert calls == [False]
    assert not metadata_root.exists()
    assert not raw_root.exists()


def test_missing_token_is_static_and_stops_before_executor_or_files(tmp_path: Path) -> None:
    stdout = io.StringIO()
    calls: list[str] = []

    def forbidden(**kwargs: Any) -> Any:
        calls.append("executor")
        raise AssertionError("missing token must stop")

    status = run_seasonal_cli(
        authorized=True,
        metadata_root=tmp_path / "metadata",
        raw_root=tmp_path / "raw",
        environ={},
        month_executor=forbidden,
        stdout=stdout,
    )

    assert status == 2
    assert stdout.getvalue() == SEASONAL_MISSING_TOKEN_MESSAGE + "\n"
    assert calls == []
    assert not (tmp_path / "raw").exists()


def test_authorized_cli_uses_fixed_order_continues_after_failure_and_redacts(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    stderr = io.StringIO()
    sentinel = "fixture-seasonal-token"
    auth_url = "https://auth-secret.invalid/?token=fixture-seasonal-token"
    calls: list[str] = []

    def executor(**kwargs: Any) -> dict[str, Any]:
        month = kwargs["config"].month
        calls.append(month)
        assert kwargs["token"] == sentinel
        month_root = kwargs["raw_root"]
        for relative, content in (
            ("state/progress.json", '{"token_stored": false}\n'),
            ("manifests/timeseries/example.manifest.json", '{"token_stored": false}\n'),
            ("state/run.log", "static reason code only\n"),
            ("state/example.partial", "static incomplete marker\n"),
        ):
            path = month_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        if month == "2019-08":
            raise RuntimeError(auth_url)
        day_count = kwargs["config"].day_count
        trajectory_count = 1 if month == "2019-11" else 0
        return {
            "month": month,
            "acquisition_status": "COMPLETE",
            "qa_status": "PASS",
            "valid_daily_chunks": day_count,
            "local_records": 3,
            "carry_records": 1,
            "combined_records": 4,
            "trajectory_quarantine_count": trajectory_count,
            "trajectory_quarantine_rate": trajectory_count / 4,
            "full_session_quarantine_count": 0,
            "reason_codes": [],
        }

    status = run_seasonal_cli(
        authorized=True,
        metadata_root=tmp_path / "metadata",
        raw_root=tmp_path / "raw",
        environ={"ACN_API_TOKEN": sentinel},
        month_executor=executor,
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())
    assert status == 1
    assert calls == list(SEASONAL_MONTHS)
    assert [item["month"] for item in payload["months"]] == list(SEASONAL_MONTHS)
    assert [item["status"] for item in payload["months"]] == [
        "PASS",
        "FAIL",
        "PASS",
    ]
    assert payload["months"][1]["reason_codes"] == ["UNEXPECTED_ERROR"]
    assert payload["status"] == "INCOMPLETE"
    assert stderr.getvalue() == ""
    rendered = stdout.getvalue()
    assert sentinel not in rendered
    assert auth_url not in rendered
    assert str(tmp_path) not in rendered
    assert "sessionID" not in rendered
    assert "query_condition" not in rendered
    persisted = "\n".join(
        path.read_text(encoding="utf-8") for path in (tmp_path / "raw").rglob("*") if path.is_file()
    )
    scanned = rendered + stderr.getvalue() + persisted
    assert sentinel not in scanned
    assert auth_url not in scanned


def test_parser_has_literal_authorization_and_no_month_or_order_override() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "--authorize-seasonal",
            "--metadata-root",
            "metadata",
            "--raw-root",
            "raw",
        ]
    )
    assert args.authorize_seasonal is True
    assert args.metadata_root == Path("metadata")
    assert args.raw_root == Path("raw")
    assert args.concurrency == 1
    assert not hasattr(args, "month")
    assert not hasattr(args, "months")
    assert not hasattr(args, "order")

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "--authorize-seasonal",
                "--metadata-root",
                "metadata",
                "--month",
                "2019-08",
            ]
        )


def test_parser_uses_the_frozen_seasonal_raw_root_default() -> None:
    args = build_parser().parse_args(
        [
            "--authorize-seasonal",
            "--metadata-root",
            "metadata",
        ]
    )

    assert args.raw_root == Path("data/raw/acn/jpl/seasonal")


def test_november_safe_result_keeps_acquisition_status_pass() -> None:
    config = jpl_month_config("2019-11")

    result = seasonal_cli_module._safe_month_result(
        config,
        {
            "month": config.month,
            "acquisition_status": "COMPLETE",
            "qa_status": "PASS",
            "valid_daily_chunks": config.day_count,
            "local_records": 1353,
            "carry_records": 1,
            "combined_records": 1354,
            "trajectory_quarantine_count": 1,
            "trajectory_quarantine_rate": 1 / 1354,
            "full_session_quarantine_count": 0,
            "reason_codes": [],
        },
    )

    assert result["status"] == "PASS"
    assert result["qa_status"] == "PASS"
    assert result["trajectory_quarantine_count"] == 1
    assert result["trajectory_quarantine_rate"] == 1 / 1354
    assert result["full_session_quarantine_count"] == 0


_MISSING = object()


@pytest.mark.parametrize(
    "field",
    (
        "trajectory_quarantine_count",
        "trajectory_quarantine_rate",
        "full_session_quarantine_count",
    ),
)
@pytest.mark.parametrize(
    "bad_value",
    (_MISSING, "1", True, -1, float("nan"), float("inf"), float("-inf")),
    ids=("missing", "string", "bool", "negative", "nan", "positive_inf", "negative_inf"),
)
def test_safe_month_result_fails_closed_on_malformed_quarantine_fields(
    field: str,
    bad_value: object,
) -> None:
    config = jpl_month_config("2019-02")
    payload: dict[str, object] = {
        "month": config.month,
        "acquisition_status": "COMPLETE",
        "qa_status": "PASS",
        "valid_daily_chunks": config.day_count,
        "local_records": 3,
        "carry_records": 0,
        "combined_records": 3,
        "trajectory_quarantine_count": 0,
        "trajectory_quarantine_rate": 0.0,
        "full_session_quarantine_count": 0,
        "reason_codes": [],
    }
    if bad_value is _MISSING:
        payload.pop(field)
    else:
        payload[field] = bad_value

    result = seasonal_cli_module._safe_month_result(config, payload)

    assert result["status"] == "FAIL"
    assert result["qa_status"] == "FAIL"
    assert result["reason_codes"] == ["UNEXPECTED_ERROR"]
    assert math.isfinite(float(result["trajectory_quarantine_rate"]))


@pytest.mark.parametrize("concurrency", [0, 3, True])
def test_cli_rejects_invalid_concurrency_before_environment(
    tmp_path: Path,
    concurrency: object,
) -> None:
    with pytest.raises(ValueError, match="1 or 2"):
        run_seasonal_cli(
            authorized=True,
            metadata_root=tmp_path / "metadata",
            raw_root=tmp_path / "raw",
            concurrency=concurrency,  # type: ignore[arg-type]
            environ=_ForbiddenEnvironment(),
            month_executor=lambda **kwargs: {},
            stdout=io.StringIO(),
        )


def test_executor_malformed_reason_values_and_inconsistent_counts_fail_statically(
    tmp_path: Path,
) -> None:
    stdout = io.StringIO()
    private_url = "https://private.invalid/?token=fixture-seasonal-token"

    def malformed(**kwargs: Any) -> dict[str, Any]:
        return {
            "month": kwargs["config"].month,
            "acquisition_status": "COMPLETE",
            "qa_status": "PASS",
            "valid_daily_chunks": 0,
            "local_records": 3,
            "carry_records": 1,
            "combined_records": 99,
            "reason_codes": [{"error": private_url}],
        }

    status = run_seasonal_cli(
        authorized=True,
        metadata_root=tmp_path / "metadata",
        raw_root=tmp_path / "raw",
        environ={"ACN_API_TOKEN": "fixture-seasonal-token"},
        month_executor=malformed,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert status == 1
    assert payload["status"] == "INCOMPLETE"
    assert all(item["status"] == "FAIL" for item in payload["months"])
    assert all(item["reason_codes"] == ["UNEXPECTED_ERROR"] for item in payload["months"])
    assert private_url not in stdout.getvalue()


def _cli_record(
    index: int,
    connection: datetime,
    disconnect: datetime,
    *,
    trajectory_anomaly: bool = False,
) -> dict[str, Any]:
    record = {
        "_id": f"private-object-{index}",
        "sessionID": f"private-session-{index}",
        "connectionTime": format_datetime(connection.astimezone(timezone.utc), usegmt=True),
        "disconnectTime": format_datetime(disconnect.astimezone(timezone.utc), usegmt=True),
        "chargingCurrent": {"timestamps": [], "current": []},
        "pilotSignal": {"timestamps": [], "pilot": []},
    }
    if trajectory_anomaly:
        timestamps = [
            connection,
            connection + timedelta(hours=1),
            connection + timedelta(seconds=4),
        ]
        record["chargingCurrent"] = {
            "timestamps": [format_datetime(value, usegmt=True) for value in timestamps],
            "current": [16.0, 16.0, 16.0],
        }
        record["pilotSignal"] = {
            "timestamps": [format_datetime(value, usegmt=True) for value in timestamps],
            "pilot": [16.0, 16.0, 16.0],
        }
    return record


class _OfflineSeasonalClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = tuple(records)
        self.official_calls = 0
        self.iter_calls = 0

    @staticmethod
    def _connection(record: dict[str, Any]) -> datetime:
        return datetime.strptime(record["connectionTime"], "%a, %d %b %Y %H:%M:%S GMT").replace(
            tzinfo=timezone.utc
        )

    def _items(self, query: ACNQuery) -> list[dict[str, Any]]:
        if query.session_id is not None:
            return [record for record in self.records if record["sessionID"] == query.session_id]
        return [
            record
            for record in self.records
            if query.start_utc <= self._connection(record) < query.end_utc
        ]

    def fetch_total_once(self, query: ACNQuery) -> int:
        self.official_calls += 1
        return len(self._items(query))

    def iter_pages(self, query: ACNQuery):  # type: ignore[no-untyped-def]
        self.iter_calls += 1
        items = self._items(query)
        yield {"_meta": {"total": len(items)}, "_items": items, "_links": {}}


def test_default_cli_pipeline_is_fully_offline_and_never_persists_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "fixture-default-pipeline-token"
    records: list[dict[str, Any]] = []
    index = 100
    for month, carry_count in zip(SEASONAL_MONTHS, (0, 1, 2)):
        config = jpl_month_config(month)
        for day in range(2):
            connection = config.utc_start + timedelta(days=day, minutes=1)
            anomaly = month == "2019-11" and day == 0
            records.append(
                _cli_record(
                    index,
                    connection,
                    connection + timedelta(hours=2 if anomaly else 0, minutes=2),
                    trajectory_anomaly=anomaly,
                )
            )
            index += 1
        for carry_index in range(carry_count):
            connection = config.utc_start - timedelta(hours=carry_index + 1)
            records.append(
                _cli_record(
                    index,
                    connection,
                    config.utc_start + timedelta(minutes=carry_index + 1),
                )
            )
            index += 1

    metadata_root = tmp_path / "metadata"
    metadata_root.mkdir()
    data_path = metadata_root / "complete.jsonl.gz"
    with gzip.open(data_path, "wt", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    digest = hashlib.sha256(data_path.read_bytes()).hexdigest()
    data_path.with_name(data_path.name + ".manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "endpoint": "sessions/jpl",
                "site": "jpl",
                "mode": "metadata",
                "record_count": len(records),
                "source_total": len(records),
                "sha256": digest,
            }
        ),
        encoding="utf-8",
    )
    inventory = hashlib.sha256(f"{data_path.name}\0{digest}\0{len(records)}\n".encode()).hexdigest()
    monkeypatch.setattr(month_config_module, "EXPECTED_COMPLETE_METADATA_FILE_COUNT", 1)
    monkeypatch.setattr(
        month_config_module,
        "EXPECTED_COMPLETE_METADATA_RECORD_COUNT",
        len(records),
    )
    monkeypatch.setattr(
        month_config_module,
        "EXPECTED_COMPLETE_METADATA_INVENTORY_SHA256",
        inventory,
    )
    client = _OfflineSeasonalClient(records)

    def client_factory(token: str) -> _OfflineSeasonalClient:
        assert token == sentinel
        return client

    monkeypatch.setattr(seasonal_cli_module, "ACNClient", client_factory)
    stdout = io.StringIO()
    stderr = io.StringIO()
    raw_root = tmp_path / "raw"

    status = run_seasonal_cli(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=raw_root,
        environ={"ACN_API_TOKEN": sentinel},
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())
    assert status == 0
    assert payload["status"] == "COMPLETE"
    assert [item["month"] for item in payload["months"]] == list(SEASONAL_MONTHS)
    assert [item["status"] for item in payload["months"]] == [
        "PASS",
        "PASS",
        "PASS",
    ]
    assert client.official_calls == 3
    immutable_paths = tuple(
        path
        for path in raw_root.rglob("*")
        if path.is_file()
        and (path.name.endswith(".jsonl.gz") or path.name.endswith(".manifest.json"))
    )
    before = {
        path.relative_to(raw_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in immutable_paths
    }
    first_iter_calls = client.iter_calls

    resumed_stdout = io.StringIO()
    resumed_status = run_seasonal_cli(
        authorized=True,
        metadata_root=metadata_root,
        raw_root=raw_root,
        environ={"ACN_API_TOKEN": sentinel},
        stdout=resumed_stdout,
        stderr=stderr,
    )
    after = {
        path.relative_to(raw_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in immutable_paths
    }
    assert resumed_status == 0
    assert json.loads(resumed_stdout.getvalue())["status"] == "COMPLETE"
    assert client.official_calls == 6
    assert client.iter_calls == first_iter_calls
    assert before == after
    scanned = stdout.getvalue().encode() + stderr.getvalue().encode()
    scanned += resumed_stdout.getvalue().encode()
    scanned += b"".join(path.read_bytes() for path in raw_root.rglob("*") if path.is_file())
    assert sentinel.encode() not in scanned
    assert b"https://" not in scanned
    assert not list(raw_root.rglob("*.partial"))
