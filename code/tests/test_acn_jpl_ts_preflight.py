from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import yaml
from evcf.data.acn_api import ACNQuery
from evcf.data.acn_jpl_ts_preflight import (
    PREFLIGHT_INVALID_CHARGING_CURRENT_RATE_LIMIT,
    PREFLIGHT_INVALID_PILOT_SIGNAL_RATE_LIMIT,
    PREFLIGHT_RANDOM_SEED,
    PREFLIGHT_SAMPLE_SIZE,
    PREFLIGHT_UNMATCHED_METADATA_RATE_LIMIT,
    audit_ts_preflight,
    run_ts_preflight,
    select_preflight_sessions,
)

ZONE = ZoneInfo("America/Los_Angeles")


def test_frozen_preflight_protocol_matches_repository_config() -> None:
    config_path = Path(__file__).parents[1] / "configs" / "acn_gate0.yaml"
    policy = yaml.safe_load(config_path.read_text(encoding="utf-8"))[
        "jpl_2019_05_preflight"
    ]

    assert policy == {
        "timezone": "America/Los_Angeles",
        "analysis_start": "2019-05-01T00:00:00-07:00",
        "analysis_end_exclusive": "2019-06-01T00:00:00-07:00",
        "random_seed": PREFLIGHT_RANDOM_SEED,
        "sample_size": PREFLIGHT_SAMPLE_SIZE,
        "invalid_charging_current_rate_limit": (
            PREFLIGHT_INVALID_CHARGING_CURRENT_RATE_LIMIT
        ),
        "invalid_pilot_signal_rate_limit": PREFLIGHT_INVALID_PILOT_SIGNAL_RATE_LIMIT,
        "unmatched_metadata_rate_limit": PREFLIGHT_UNMATCHED_METADATA_RATE_LIMIT,
        "full_month_timeseries_authorized": False,
    }


def _stamp(value: datetime) -> str:
    return format_datetime(value.astimezone(timezone.utc), usegmt=True)


def _metadata(index: int, *, connected: datetime | None = None) -> dict[str, Any]:
    connection = connected or datetime(2019, 5, 2, 8, 0, tzinfo=ZONE)
    return {
        "_id": f"private-object-{index}",
        "sessionID": f"private-session-{index:04d}",
        "connectionTime": _stamp(connection),
        "disconnectTime": _stamp(connection + timedelta(hours=1)),
    }


def _timeseries(metadata: dict[str, Any], *, valid: bool = True) -> dict[str, Any]:
    connection = datetime(2019, 5, 2, 15, 0, tzinfo=timezone.utc)
    result = dict(metadata)
    result["userInputs"] = [{"kWhRequested": 8.0}]
    if valid:
        result["chargingCurrent"] = {
            "timestamps": [
                _stamp(connection - timedelta(seconds=1)),
                _stamp(connection),
                _stamp(connection),
                _stamp(connection + timedelta(seconds=4)),
            ],
            "current": [1.0, 16.0, 16.0, 15.0],
        }
        result["pilotSignal"] = {
            "timestamps": [
                _stamp(connection),
                _stamp(connection + timedelta(seconds=4)),
            ],
            "pilot": [32.0, 32.0],
        }
    else:
        result["chargingCurrent"] = {"timestamps": [_stamp(connection)]}
        result["pilotSignal"] = None
    return result


class FakeClient:
    def __init__(self, records: dict[str, dict[str, Any]], token: str) -> None:
        self.records = records
        self.token = token
        self.queries: list[ACNQuery] = []

    def iter_pages(self, query: ACNQuery):  # type: ignore[no-untyped-def]
        self.queries.append(query)
        assert query.session_id is not None
        record = self.records[query.session_id]
        yield {
            "_items": [record],
            "_links": {},
            "_meta": {"total": 1},
        }


class NoNetworkClient:
    def iter_pages(self, query: ACNQuery):  # type: ignore[no-untyped-def]
        raise AssertionError(f"resume unexpectedly queried {query.endpoint}")


def test_fixed_seed_selects_100_unique_may_sessions_independent_of_input_order() -> None:
    records = [_metadata(index) for index in range(120)]
    records.extend(
        [
            _metadata(200, connected=datetime(2019, 4, 30, 23, 59, tzinfo=ZONE)),
            _metadata(201, connected=datetime(2019, 6, 1, 0, 0, tzinfo=ZONE)),
            dict(records[0]),
        ]
    )
    shuffled = list(records)
    random.Random(7).shuffle(shuffled)

    first = select_preflight_sessions(records)
    second = select_preflight_sessions(shuffled)

    assert PREFLIGHT_RANDOM_SEED == 201905
    assert len(first) == 100
    assert len({item.session_id for item in first}) == 100
    assert [item.session_id for item in first] == [item.session_id for item in second]


def test_exact_session_query_uses_json_escaping_and_ts_endpoint() -> None:
    query = ACNQuery(
        site="jpl",
        start=datetime(2019, 5, 1, 7, tzinfo=timezone.utc),
        end=datetime(2019, 6, 1, 7, tzinfo=timezone.utc),
        timeseries=True,
        session_id='private" or connectionTime >= "escape-attempt',
    )

    assert query.endpoint == "sessions/jpl/ts"
    assert query.condition.endswith(
        'sessionID == "private\\" or connectionTime >= \\"escape-attempt"'
    )
    assert query.public_dict()["session_id"] == query.session_id
    with pytest.raises(ValueError, match="session_id"):
        ACNQuery(
            site="jpl",
            start=query.start,
            end=query.end,
            timeseries=True,
            session_id=" ",
        )
    with pytest.raises(ValueError, match="session_id"):
        ACNQuery(
            site="jpl",
            start=query.start,
            end=query.end,
            timeseries=True,
            session_id=7,  # type: ignore[arg-type]
        )


def test_serial_preflight_is_atomic_secret_free_and_resumes_valid_sessions(
    tmp_path: Path,
) -> None:
    metadata = [_metadata(1), _metadata(2)]
    records = {item["sessionID"]: _timeseries(item) for item in metadata}
    token = "fixture-secret-token"
    client = FakeClient(records, token)

    first = run_ts_preflight(
        client,  # type: ignore[arg-type]
        metadata,
        tmp_path,
        sample_size=2,
        downloaded_at_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert len(client.queries) == 2
    assert first.downloaded_sessions == 2
    assert first.skipped_sessions == 0
    assert first.failed_sessions == 0
    assert not list(tmp_path.rglob("*.partial"))
    manifests = sorted((tmp_path / "manifests" / "preflight").glob("*.json"))
    assert len(manifests) == 2
    for path in manifests:
        text = path.read_text(encoding="utf-8")
        assert token not in text
        assert json.loads(text)["token_stored"] is False

    second = run_ts_preflight(
        NoNetworkClient(),  # type: ignore[arg-type]
        list(reversed(metadata)),
        tmp_path,
        sample_size=2,
    )

    assert second.downloaded_sessions == 0
    assert second.skipped_sessions == 2
    assert second.failed_sessions == 0
    assert second.qa["matching"]["match_rate"] == 1.0
    serialized = json.dumps(second.qa, ensure_ascii=False)
    for item in metadata:
        assert item["sessionID"] not in serialized
        assert item["_id"] not in serialized
    qa_path = tmp_path / "state" / "preflight_qa.json"
    assert json.loads(qa_path.read_text(encoding="utf-8")) == second.qa
    qa_text = qa_path.read_text(encoding="utf-8")
    assert token not in qa_text
    for item in metadata:
        assert item["sessionID"] not in qa_text
        assert item["_id"] not in qa_text


def test_aggregate_qa_supports_official_containers_and_declared_metrics() -> None:
    metadata = [_metadata(1), _metadata(2)]
    records = [_timeseries(metadata[0]), _timeseries(metadata[1], valid=False)]

    report = audit_ts_preflight(metadata, records, requested_sample_size=2)

    assert report["field_coverage"]["chargingCurrent"] == {
        "count": 2,
        "denominator": 2,
        "rate": 1.0,
    }
    assert report["field_coverage"]["pilotSignal"]["rate"] == 0.5
    assert report["field_coverage"]["userInputs"]["rate"] == 1.0
    assert report["matching"] == {
        "metadata_sessions": 2,
        "timeseries_records": 2,
        "matched_sessions": 2,
        "missing_sessions": 0,
        "orphan_sessions": 0,
        "match_rate": 1.0,
    }
    current = report["series"]["chargingCurrent"]
    pilot = report["series"]["pilotSignal"]
    assert current["invalid_container_sessions"] == 1
    assert pilot["invalid_container_sessions"] == 1
    assert current["duplicate_extra_timestamps"] == 1
    assert current["nonmonotonic_pairs"] == 0
    assert current["raw_samples"] == 4
    assert current["usable_samples"] == 2
    assert current["retained_sample_rate"] == 0.5
    assert current["boundary_positive_current_points"] == 1
    assert current["expected_complete_active_minutes"] == 120
    assert current["sparse_minutes_under_10_points"] == 120
    assert current["sparse_minute_rate"] == 1.0
    assert report["gate"]["status"] == "FAIL"
    assert report["privacy"] == {
        "aggregate_only": True,
        "identifiers_emitted": False,
        "token_emitted": False,
    }


def test_mismatched_vectors_are_not_retained_and_unknown_bounds_are_not_outside() -> None:
    metadata = [_metadata(1), _metadata(2)]
    mismatch = _timeseries(metadata[0])
    mismatch["chargingCurrent"] = {
        "timestamps": mismatch["chargingCurrent"]["timestamps"][:2],
        "current": [1.0, 16.0, 17.0],
    }
    unknown_bounds = _timeseries(metadata[1])
    unknown_bounds["disconnectTime"] = None

    report = audit_ts_preflight(
        metadata,
        [mismatch, unknown_bounds],
        requested_sample_size=2,
    )
    current = report["series"]["chargingCurrent"]

    assert current["length_mismatch_sessions"] == 1
    assert current["raw_samples"] == 7
    assert current["usable_samples"] == 0
    assert current["boundary_positive_current_points"] == 0
    assert current["boundary_unverifiable_sessions"] == 1


def test_vector_tails_and_raw_values_are_fully_audited_when_alignment_is_invalid() -> None:
    metadata = [_metadata(1), _metadata(2), _metadata(3)]
    timestamp_tail = _timeseries(metadata[0])
    timestamp_tail["chargingCurrent"] = {
        "timestamps": [
            timestamp_tail["chargingCurrent"]["timestamps"][1],
            "not-a-timestamp",
        ],
        "current": [16.0],
    }
    value_tail = _timeseries(metadata[1])
    value_tail["chargingCurrent"] = {
        "timestamps": [value_tail["chargingCurrent"]["timestamps"][1]],
        "current": [16.0, "bad", -1.0],
    }
    missing_timestamps = _timeseries(metadata[2])
    missing_timestamps["chargingCurrent"] = {
        "timestamps": None,
        "current": [16.0, "bad"],
    }

    report = audit_ts_preflight(
        metadata,
        [timestamp_tail, value_tail, missing_timestamps],
        requested_sample_size=3,
    )
    current = report["series"]["chargingCurrent"]

    assert current["invalid_container_sessions"] == 3
    assert current["length_mismatch_sessions"] == 2
    assert current["timestamp_parse_errors"] == 1
    assert current["invalid_numeric_values"] == 2
    assert current["negative_values"] == 1
    assert current["raw_samples"] == 6
    assert current["usable_samples"] == 0
    assert current["expected_complete_active_minutes"] == 180
    assert current["sparse_minutes_under_10_points"] == 180


@pytest.mark.parametrize(
    ("invalid_sessions", "expected_status"),
    [(10, "PASS"), (11, "FAIL")],
)
def test_invalid_container_threshold_is_inclusive_at_ten_percent(
    invalid_sessions: int,
    expected_status: str,
) -> None:
    metadata = [_metadata(index) for index in range(100)]
    records = [
        _timeseries(item, valid=index >= invalid_sessions)
        for index, item in enumerate(metadata)
    ]

    report = audit_ts_preflight(metadata, records)

    assert report["series"]["chargingCurrent"]["invalid_container_sessions"] == (
        invalid_sessions
    )
    assert report["series"]["pilotSignal"]["invalid_container_sessions"] == invalid_sessions
    assert report["gate"]["status"] == expected_status
