"""Semantic and structural audits for raw ACN-Data session records."""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from .acn_api import iter_jsonl

CORE_FIELDS = (
    "_id",
    "sessionID",
    "siteID",
    "stationID",
    "spaceID",
    "clusterID",
    "timezone",
    "connectionTime",
    "disconnectTime",
    "doneChargingTime",
    "kWhDelivered",
    "chargingCurrent",
    "pilotSignal",
    "userID",
    "userInputs",
)

RETROSPECTIVE_LABEL_FIELDS = frozenset(
    {"disconnectTime", "doneChargingTime", "kWhDelivered"}
)

ISSUE_TIME_BASE_FIELDS = (
    "_id",
    "sessionID",
    "siteID",
    "stationID",
    "spaceID",
    "clusterID",
    "timezone",
    "connectionTime",
    "userID",
)


@dataclass
class ACNAuditReport:
    schema_version: str = "acn-gate0-audit/v1"
    record_count: int = 0
    unique_session_ids: int = 0
    duplicate_session_ids: list[str] = field(default_factory=list)
    sites: dict[str, int] = field(default_factory=dict)
    stations: int = 0
    spaces: int = 0
    timezones: dict[str, int] = field(default_factory=dict)
    field_presence_count: dict[str, int] = field(default_factory=dict)
    field_presence_rate: dict[str, float] = field(default_factory=dict)
    sessions_with_user_inputs: int = 0
    sessions_with_requested_departure: int = 0
    sessions_with_requested_energy: int = 0
    sessions_with_charging_current: int = 0
    sessions_with_pilot_signal: int = 0
    current_length_mismatch: int = 0
    pilot_length_mismatch: int = 0
    unknown_timeseries_value_key: int = 0
    nonmonotonic_timeseries: int = 0
    negative_current_values: int = 0
    invalid_connection_disconnect_order: int = 0
    done_before_connection: int = 0
    done_after_disconnect: int = 0
    negative_delivered_energy: int = 0
    missing_session_identifier: int = 0
    unknown_fields: dict[str, int] = field(default_factory=dict)
    semantic_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_acn_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ACN datetime must be timezone-aware")
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise TypeError(f"Expected datetime string, got {type(value).__name__}")
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid RFC 1123 datetime: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"ACN datetime has no timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def _series_values(series: Mapping[str, Any]) -> Sequence[Any] | None:
    for key in ("values", "current", "pilot", "value"):
        candidate = series.get(key)
        if isinstance(candidate, list):
            return candidate
    list_fields = [
        value
        for key, value in series.items()
        if key != "timestamps" and isinstance(value, list)
    ]
    if len(list_fields) == 1:
        return list_fields[0]
    return None


def _inspect_timeseries(series: Any) -> dict[str, int | bool]:
    result: dict[str, int | bool] = {
        "present": False,
        "length_mismatch": False,
        "unknown_value_key": False,
        "nonmonotonic": False,
        "negative_values": 0,
    }
    if not isinstance(series, Mapping):
        return result
    timestamps = series.get("timestamps")
    values = _series_values(series)
    if not isinstance(timestamps, list):
        return result
    result["present"] = True
    if values is None:
        result["unknown_value_key"] = True
        return result
    result["length_mismatch"] = len(timestamps) != len(values)

    parsed: list[datetime] = []
    for stamp in timestamps:
        try:
            dt = parse_acn_datetime(stamp)
        except (TypeError, ValueError):
            result["nonmonotonic"] = True
            parsed = []
            break
        if dt is not None:
            parsed.append(dt)
    if parsed and any(current <= previous for previous, current in pairwise(parsed)):
        result["nonmonotonic"] = True

    negatives = 0
    for value in values:
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) < 0
        ):
            negatives += 1
    result["negative_values"] = negatives
    return result


def audit_sessions(records: Iterable[Mapping[str, Any]]) -> ACNAuditReport:
    report = ACNAuditReport()
    presence: Counter[str] = Counter()
    site_counts: Counter[str] = Counter()
    timezone_counts: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    session_ids: Counter[str] = Counter()
    stations: set[str] = set()
    spaces: set[str] = set()

    for record in records:
        report.record_count += 1
        for key in record:
            if key not in CORE_FIELDS:
                unknown[key] += 1
        for field_name in CORE_FIELDS:
            if field_name in record and record[field_name] not in (None, "", []):
                presence[field_name] += 1

        session_id = record.get("sessionID") or record.get("_id")
        if session_id in (None, ""):
            report.missing_session_identifier += 1
        else:
            session_ids[str(session_id)] += 1
        if record.get("siteID") not in (None, ""):
            site_counts[str(record["siteID"])] += 1
        if record.get("stationID") not in (None, ""):
            stations.add(str(record["stationID"]))
        if record.get("spaceID") not in (None, ""):
            spaces.add(str(record["spaceID"]))
        if record.get("timezone") not in (None, ""):
            timezone_counts[str(record["timezone"])] += 1

        try:
            connection = parse_acn_datetime(record.get("connectionTime"))
            disconnect = parse_acn_datetime(record.get("disconnectTime"))
            done = parse_acn_datetime(record.get("doneChargingTime"))
        except (TypeError, ValueError):
            report.invalid_connection_disconnect_order += 1
            connection = disconnect = done = None
        if connection is not None and disconnect is not None and disconnect < connection:
            report.invalid_connection_disconnect_order += 1
        if connection is not None and done is not None and done < connection:
            report.done_before_connection += 1
        if disconnect is not None and done is not None and done > disconnect:
            report.done_after_disconnect += 1

        energy = record.get("kWhDelivered")
        if isinstance(energy, (int, float)) and not isinstance(energy, bool) and energy < 0:
            report.negative_delivered_energy += 1

        user_inputs = record.get("userInputs")
        if isinstance(user_inputs, list) and user_inputs:
            report.sessions_with_user_inputs += 1
            if any(
                isinstance(entry, Mapping) and entry.get("requestedDeparture") not in (None, "")
                for entry in user_inputs
            ):
                report.sessions_with_requested_departure += 1
            if any(
                isinstance(entry, Mapping) and entry.get("kWhRequested") not in (None, "")
                for entry in user_inputs
            ):
                report.sessions_with_requested_energy += 1

        current = _inspect_timeseries(record.get("chargingCurrent"))
        if current["present"]:
            report.sessions_with_charging_current += 1
        report.current_length_mismatch += int(bool(current["length_mismatch"]))
        report.unknown_timeseries_value_key += int(bool(current["unknown_value_key"]))
        report.nonmonotonic_timeseries += int(bool(current["nonmonotonic"]))
        report.negative_current_values += int(current["negative_values"])

        pilot = _inspect_timeseries(record.get("pilotSignal"))
        if pilot["present"]:
            report.sessions_with_pilot_signal += 1
        report.pilot_length_mismatch += int(bool(pilot["length_mismatch"]))
        report.unknown_timeseries_value_key += int(bool(pilot["unknown_value_key"]))
        report.nonmonotonic_timeseries += int(bool(pilot["nonmonotonic"]))

    report.unique_session_ids = len(session_ids)
    report.duplicate_session_ids = sorted(
        session_id for session_id, count in session_ids.items() if count > 1
    )
    report.sites = dict(sorted(site_counts.items()))
    report.stations = len(stations)
    report.spaces = len(spaces)
    report.timezones = dict(sorted(timezone_counts.items()))
    report.field_presence_count = {field_name: presence[field_name] for field_name in CORE_FIELDS}
    denominator = max(report.record_count, 1)
    report.field_presence_rate = {
        field_name: round(presence[field_name] / denominator, 6) for field_name in CORE_FIELDS
    }
    report.unknown_fields = dict(sorted(unknown.items()))
    report.semantic_warnings = [
        (
            "chargingCurrent is measured current in amperes, not a direct active-power series; "
            "kW reconstruction requires EVSE voltage/phase/network metadata."
        ),
        (
            "disconnectTime, doneChargingTime and final kWhDelivered are retrospective labels and "
            "must not enter an earlier rolling-forecast input unchanged."
        ),
        (
            "userInputs may be revised; only entries with modifiedAt at or before the issue time "
            "are legal online inputs."
        ),
        "pilotSignal is a control command/limit and must be distinguished from measured current.",
    ]
    return report


def _truncate_timeseries(series: Any, issue_time: datetime) -> Any:
    if not isinstance(series, Mapping):
        return None
    timestamps = series.get("timestamps")
    values = _series_values(series)
    if not isinstance(timestamps, list) or values is None or len(timestamps) != len(values):
        return None

    keep: list[int] = []
    for index, stamp in enumerate(timestamps):
        parsed = parse_acn_datetime(stamp)
        if parsed is not None and parsed <= issue_time:
            keep.append(index)
    if not keep:
        return {"timestamps": [], "values": []}
    return {
        "timestamps": [timestamps[index] for index in keep],
        "values": [values[index] for index in keep],
    }


def online_session_snapshot(
    record: Mapping[str, Any], issue_time: datetime
) -> dict[str, Any] | None:
    """Create a leakage-safe session snapshot at one forecast issue time.

    The function deliberately omits final disconnect/done times and final delivered
    energy. It keeps only user inputs whose ``modifiedAt`` timestamp was available by
    the issue time and truncates current/pilot trajectories.
    """

    if issue_time.tzinfo is None or issue_time.utcoffset() is None:
        raise ValueError("issue_time must be timezone-aware")
    issue_utc = issue_time.astimezone(timezone.utc)
    connection = parse_acn_datetime(record.get("connectionTime"))
    disconnect = parse_acn_datetime(record.get("disconnectTime"))
    if connection is None or connection > issue_utc:
        return None
    # Retrospective disconnect is used only to reconstruct whether the session was
    # active at the issue time; its exact value is never returned as a predictor.
    if disconnect is not None and disconnect <= issue_utc:
        return None

    snapshot = {
        field_name: record[field_name]
        for field_name in ISSUE_TIME_BASE_FIELDS
        if field_name in record
    }
    snapshot["issueTimeUtc"] = issue_utc.isoformat()
    snapshot["elapsedConnectionSeconds"] = (issue_utc - connection).total_seconds()

    for field_name in ("chargingCurrent", "pilotSignal"):
        truncated = _truncate_timeseries(record.get(field_name), issue_utc)
        if truncated is not None:
            snapshot[field_name] = truncated

    legal_inputs: list[Mapping[str, Any]] = []
    for entry in record.get("userInputs") or []:
        if not isinstance(entry, Mapping):
            continue
        modified = parse_acn_datetime(entry.get("modifiedAt"))
        if modified is not None and modified <= issue_utc:
            legal_inputs.append(dict(entry))
    if legal_inputs:
        snapshot["userInputs"] = legal_inputs
    return snapshot


def write_audit_report(report: ACNAuditReport, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def audit_jsonl(input_path: str | Path, output_path: str | Path) -> ACNAuditReport:
    report = audit_sessions(iter_jsonl(input_path))
    write_audit_report(report, output_path)
    return report
