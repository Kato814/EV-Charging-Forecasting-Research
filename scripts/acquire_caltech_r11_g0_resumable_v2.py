"""Disconnect-filter-free acquisition for frozen R11-G0 Caltech overlap scopes.

ACN-Data intermittently returns HTTP 502 for server-side predicates involving
``disconnectTime``. This acquisition-engineering repair preserves the exact frozen
scientific scope

    connectionTime < month_end and disconnectTime > month_start

without sending ``disconnectTime`` to the server. The exact same set is materialized
as the disjoint union of:

1. target-month sessions selected only by ``connectionTime``; and
2. carry-in sessions identified by downloading pre-month metadata selected only by
   ``connectionTime`` and applying ``disconnectTime > month_start`` locally.

Historical metadata is cached in resumable chunks. Only the small locally identified
carry-in set is subsequently fetched from ``/ts`` by session ID. No forecasting model
is imported or trained here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from evcf.data.acn_api import (
    ACNAuthenticationError,
    ACNClient,
    ACNQuery,
    DEFAULT_API_BASE_URL,
    DEFAULT_TOKEN_ENV,
    download_sessions,
    iter_jsonl,
)
from evcf.data.acn_jpl_cleaning import parse_timestamp_utc_s
from evcf.data.acn_caltech_r11_g0 import (
    CALTECH_MONTHS,
    AcquisitionMonthResult,
    OverlapQuery,
    R11G0Error,
    _atomic_json,
    _existing_acquisition,
    _raw_paths,
    _sha256_file,
    _validate_raw,
    load_protocol,
    month_config,
)

_SCRIPT_PATH = "scripts/acquire_caltech_r11_g0_resumable_v2.py"
_TIMEZONE = ZoneInfo("America/Los_Angeles")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_HISTORY_ANCHOR = datetime(2000, 1, 1, tzinfo=timezone.utc)
_ACTIVE_HISTORY_START = datetime(2018, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class CarryRecord:
    object_id: str
    session_id: str
    connection_utc_s: int
    disconnect_utc_s: int


def _verify_self(code_commit: str, repo_root: Path) -> None:
    if not isinstance(code_commit, str) or _COMMIT.fullmatch(code_commit) is None:
        raise R11G0Error("IMPLEMENTATION_DRIFT")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if head.returncode != 0 or head.stdout.strip() != code_commit:
        raise R11G0Error("IMPLEMENTATION_DRIFT")
    for command in (
        ["git", "cat-file", "-e", f"{code_commit}:{_SCRIPT_PATH}"],
        ["git", "diff", "--quiet", code_commit, "--", _SCRIPT_PATH],
        ["git", "diff", "--cached", "--quiet", code_commit, "--", _SCRIPT_PATH],
    ):
        if subprocess.run(
            command,
            cwd=repo_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode != 0:
            raise R11G0Error("IMPLEMENTATION_DRIFT")


def _safe_reason(exc: BaseException) -> str:
    value = getattr(exc, "reason_code", None)
    if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", value):
        return value
    return "UNEXPECTED_ERROR"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID") from exc
    if not isinstance(value, dict):
        raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID")
    return value


def _chunk_paths(root: Path, namespace: str, name: str) -> tuple[Path, Path]:
    data = root / namespace / f"{name}.jsonl"
    return data, data.with_suffix(data.suffix + ".manifest.json")


def _validate_completed_chunk(data: Path, manifest: Path, query: ACNQuery) -> int:
    present = (data.exists(), manifest.exists())
    if any(present) and not all(present):
        raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID")
    if not all(present):
        return -1
    document = _load_json(manifest)
    count = document.get("record_count")
    if (
        document.get("schema_version") != "acn-download-manifest/v1"
        or document.get("query") != query.public_dict()
        or document.get("complete_for_query") is not True
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        or document.get("remote_total_reported") != count
        or document.get("sha256") != _sha256_file(data)
    ):
        raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID")
    return count


def _download_or_reuse(
    client: ACNClient,
    query: ACNQuery,
    data: Path,
    manifest: Path,
) -> int:
    existing = _validate_completed_chunk(data, manifest, query)
    if existing >= 0:
        return existing
    try:
        result = download_sessions(client, query, data, overwrite=False)
    except ACNAuthenticationError as exc:
        raise R11G0Error("ACN_AUTHENTICATION_FAILED") from exc
    except Exception as exc:
        raise R11G0Error("ACN_ACQUISITION_FAILED") from exc
    if (
        result.complete is not True
        or result.remote_total_reported != result.record_count
        or result.sha256 != _sha256_file(data)
    ):
        raise R11G0Error("ACN_ACQUISITION_INTEGRITY_FAILED")
    return result.record_count


def _month_start(value: datetime) -> datetime:
    return datetime(value.year, value.month, 1, tzinfo=timezone.utc)


def _next_month(value: datetime) -> datetime:
    if value.month == 12:
        return datetime(value.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(value.year, value.month + 1, 1, tzinfo=timezone.utc)


def historical_metadata_intervals(boundary: datetime) -> tuple[tuple[str, datetime, datetime], ...]:
    """Return a deterministic exact cover of [2000-01-01 UTC, boundary)."""
    edge = boundary.astimezone(timezone.utc)
    if edge <= _ACTIVE_HISTORY_START:
        raise R11G0Error("MONTH_CONFIG_INVALID")
    output: list[tuple[str, datetime, datetime]] = []

    current = _HISTORY_ANCHOR
    while current < _ACTIVE_HISTORY_START:
        following = min(datetime(current.year + 1, 1, 1, tzinfo=timezone.utc), edge)
        output.append((f"year_{current.year:04d}", current, following))
        current = following
        if current >= edge:
            return tuple(output)

    current = _ACTIVE_HISTORY_START
    while current < edge:
        following = min(_next_month(current), edge)
        name = f"month_{current.year:04d}-{current.month:02d}"
        if following != _next_month(current):
            name += f"_to_{edge.strftime('%Y%m%dT%H%M%SZ')}"
        output.append((name, current, following))
        current = following
    return tuple(output)


def _local_day_queries(config: object) -> tuple[tuple[str, ACNQuery], ...]:
    start = config.local_start  # type: ignore[attr-defined]
    end = config.local_end  # type: ignore[attr-defined]
    output: list[tuple[str, ACNQuery]] = []
    current = start
    while current < end:
        provisional = current + timedelta(days=1)
        following = datetime(
            provisional.year,
            provisional.month,
            provisional.day,
            tzinfo=_TIMEZONE,
        )
        output.append(
            (
                current.date().isoformat(),
                ACNQuery(
                    site="caltech",
                    start=current.astimezone(timezone.utc),
                    end=min(following, end).astimezone(timezone.utc),
                    timeseries=True,
                ),
            )
        )
        current = following
    return tuple(output)


def _identity(record: Mapping[str, Any]) -> tuple[str, str]:
    object_id, session_id = record.get("_id"), record.get("sessionID")
    if (
        not isinstance(object_id, str)
        or not object_id
        or not isinstance(session_id, str)
        or not session_id
    ):
        raise R11G0Error("RAW_IDENTITY_INVALID")
    return object_id, session_id


def _collect_carry_records(metadata_files: Iterable[Path], boundary: datetime) -> tuple[CarryRecord, ...]:
    edge = int(boundary.astimezone(timezone.utc).timestamp())
    seen: set[tuple[str, str]] = set()
    carry: list[CarryRecord] = []
    for path in metadata_files:
        for record in iter_jsonl(path):
            identity = _identity(record)
            if identity in seen:
                raise R11G0Error("RAW_DUPLICATE_IDENTITY")
            seen.add(identity)
            try:
                connection = parse_timestamp_utc_s(record.get("connectionTime"))
                disconnect = parse_timestamp_utc_s(record.get("disconnectTime"))
            except (TypeError, ValueError) as exc:
                raise R11G0Error("METADATA_BOUNDS_INVALID") from exc
            if disconnect <= connection:
                raise R11G0Error("METADATA_BOUNDS_INVALID")
            if connection < edge < disconnect:
                carry.append(
                    CarryRecord(
                        object_id=identity[0],
                        session_id=identity[1],
                        connection_utc_s=connection,
                        disconnect_utc_s=disconnect,
                    )
                )
    carry.sort(key=lambda item: (item.connection_utc_s, item.object_id, item.session_id))
    return tuple(carry)


def _validate_carry_timeseries(path: Path, expected: CarryRecord) -> None:
    rows = list(iter_jsonl(path))
    if len(rows) != 1:
        raise R11G0Error("ACN_ACQUISITION_INTEGRITY_FAILED")
    record = rows[0]
    if _identity(record) != (expected.object_id, expected.session_id):
        raise R11G0Error("RAW_IDENTITY_INVALID")
    try:
        connection = parse_timestamp_utc_s(record.get("connectionTime"))
        disconnect = parse_timestamp_utc_s(record.get("disconnectTime"))
    except (TypeError, ValueError) as exc:
        raise R11G0Error("METADATA_BOUNDS_INVALID") from exc
    if connection != expected.connection_utc_s or disconnect != expected.disconnect_utc_s:
        raise R11G0Error("ACN_ACQUISITION_INTEGRITY_FAILED")


def _write_final_month(
    *,
    raw: Path,
    manifest_path: Path,
    records: tuple[Mapping[str, Any], ...],
    expected_total: int,
    overlap_query: OverlapQuery,
    target_connection_total: int,
    carry_count: int,
) -> str:
    raw.parent.mkdir(parents=True, exist_ok=True)
    partial = raw.with_suffix(raw.suffix + ".partial")
    manifest_partial = manifest_path.with_name(manifest_path.name + ".partial")
    if any(path.exists() for path in (raw, manifest_path, partial, manifest_partial)):
        raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID")

    ordered = sorted(
        records,
        key=lambda record: (
            parse_timestamp_utc_s(record.get("connectionTime")),
            *_identity(record),
        ),
    )
    identities: set[tuple[str, str]] = set()
    digest = hashlib.sha256()
    try:
        with partial.open("xb") as handle:
            for record in ordered:
                identity = _identity(record)
                if identity in identities:
                    raise R11G0Error("RAW_DUPLICATE_IDENTITY")
                identities.add(identity)
                encoded = (
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                ).encode("utf-8")
                handle.write(encoded)
                digest.update(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if len(identities) != expected_total or expected_total != target_connection_total + carry_count:
            raise R11G0Error("ACN_ACQUISITION_INTEGRITY_FAILED")
        os.replace(partial, raw)

        manifest = {
            "schema_version": "acn-download-manifest/v1",
            "dataset_id": "D0001",
            "source": "ACN-Data public REST API",
            "source_documentation": "https://ev.caltech.edu/dataset",
            "api_base_url": DEFAULT_API_BASE_URL,
            "query": overlap_query.public_dict(),
            "authentication": {
                "method": "HTTP Basic; token as username, blank password",
                "token_environment_variable": DEFAULT_TOKEN_ENV,
                "token_stored": False,
            },
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "output_file": raw.name,
            "record_count": expected_total,
            "remote_total_reported": expected_total,
            "complete_for_query": True,
            "sha256": digest.hexdigest(),
            "notes": [
                "Exact frozen overlap scope materialized without a server-side disconnectTime predicate.",
                "Expected overlap total equals connection-month metadata total plus locally filtered carry-in metadata count.",
                "Carry-in candidates were selected from the complete connection-time metadata history starting 2000-01-01 UTC.",
                "Raw timestamp strings are preserved exactly as returned by the API.",
            ],
        }
        with manifest_partial.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(manifest_partial, manifest_path)
        return digest.hexdigest()
    except BaseException:
        partial.unlink(missing_ok=True)
        manifest_partial.unlink(missing_ok=True)
        raise


def acquire_resumable_v2(
    *,
    raw_root: Path,
    code_commit: str,
    repo_root: Path,
    protocol_path: Path,
) -> tuple[object, tuple[AcquisitionMonthResult, ...]]:
    _verify_self(code_commit, repo_root)
    protocol = load_protocol(protocol_path)
    root = raw_root
    if root.exists() and (not root.is_dir() or root.is_symlink()):
        raise R11G0Error("OUTPUT_TOPOLOGY_INVALID")
    root.mkdir(parents=True, exist_ok=True)
    try:
        client = ACNClient.from_env(DEFAULT_TOKEN_ENV)
    except ACNAuthenticationError as exc:
        raise R11G0Error("ACN_AUTHENTICATION_FAILED") from exc

    results: list[AcquisitionMonthResult] = []
    for month in CALTECH_MONTHS:
        config = month_config(month)
        raw, manifest_path, summary_path = _raw_paths(root, month)
        existing = tuple(path.exists() for path in (raw, manifest_path, summary_path))
        if any(existing):
            if not all(existing):
                raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID")
            results.append(
                _existing_acquisition(protocol, config, raw, manifest_path, summary_path)
            )
            continue

        # 1) Exact pre-boundary metadata universe, selected only by connectionTime.
        metadata_files: list[Path] = []
        for name, start, end in historical_metadata_intervals(config.utc_start):
            query = ACNQuery(site="caltech", start=start, end=end, timeseries=False)
            data, manifest = _chunk_paths(root, "metadata_history", name)
            _download_or_reuse(client, query, data, manifest)
            metadata_files.append(data)
        carry = _collect_carry_records(metadata_files, config.utc_start)

        # 2) Target-month total selected only by connectionTime.
        target_metadata = ACNQuery(
            site="caltech",
            start=config.utc_start,
            end=config.utc_end,
            timeseries=False,
        )
        try:
            target_total = client.fetch_total_once(target_metadata)
        except ACNAuthenticationError as exc:
            raise R11G0Error("ACN_AUTHENTICATION_FAILED") from exc
        except Exception as exc:
            raise R11G0Error("ACN_ACQUISITION_FAILED") from exc
        if target_total <= 0:
            raise R11G0Error("ACN_ACQUISITION_INTEGRITY_FAILED")

        # 3) Fetch the small carry-in set by session ID; no disconnectTime predicate.
        month_records: list[Mapping[str, Any]] = []
        for ordinal, expected in enumerate(carry):
            query = ACNQuery(
                site="caltech",
                start=_HISTORY_ANCHOR,
                end=config.utc_start,
                timeseries=True,
                session_id=expected.session_id,
            )
            data, manifest = _chunk_paths(root / month, "carry_ts", f"carry_{ordinal:04d}")
            count = _download_or_reuse(client, query, data, manifest)
            if count != 1:
                raise R11G0Error("ACN_ACQUISITION_INTEGRITY_FAILED")
            _validate_carry_timeseries(data, expected)
            month_records.extend(iter_jsonl(data))

        # 4) Fetch target-month /ts in local-day connection-time chunks.
        target_seen: set[tuple[str, str]] = set()
        target_count = 0
        for day_name, query in _local_day_queries(config):
            data, manifest = _chunk_paths(root / month, "day_ts", f"day_{day_name}")
            _download_or_reuse(client, query, data, manifest)
            for record in iter_jsonl(data):
                identity = _identity(record)
                if identity in target_seen:
                    raise R11G0Error("RAW_DUPLICATE_IDENTITY")
                target_seen.add(identity)
                target_count += 1
                month_records.append(record)
        if target_count != target_total:
            raise R11G0Error("ACN_ACQUISITION_INTEGRITY_FAILED")

        expected_total = target_total + len(carry)
        overlap_query = OverlapQuery("caltech", config.utc_start, config.utc_end, True)
        raw_sha = _write_final_month(
            raw=raw,
            manifest_path=manifest_path,
            records=tuple(month_records),
            expected_total=expected_total,
            overlap_query=overlap_query,
            target_connection_total=target_total,
            carry_count=len(carry),
        )
        _validate_raw(raw, config, expected_total)
        _atomic_json(
            summary_path,
            {
                "schema_version": "evcf-r11-g0-caltech-acquisition-month/v1",
                "status": "COMPLETE",
                "month": month,
                "site_id": "caltech",
                "protocol_sha256": protocol.protocol_sha256,
                "session_count": expected_total,
                "metadata_total": expected_total,
                "raw_sha256": raw_sha,
                "partial_file_count": 0,
                "timeseries": True,
                "overlap_selection": True,
                "disconnect_filter_sent_to_server": False,
                "target_connection_total": target_total,
                "carry_in_count": len(carry),
                "history_anchor_utc": _HISTORY_ANCHOR.isoformat(),
                "resumable_materialization": True,
                "identifiers_public": False,
                "token_stored": False,
            },
        )
        results.append(AcquisitionMonthResult(month, expected_total, raw_sha, False))
    return protocol, tuple(results)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Disconnect-filter-free resumable Caltech R11-G0 acquisition"
    )
    parser.add_argument("--authorize-r11-g0-acquisition", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument(
        "--protocol-path",
        type=Path,
        default=Path("code/configs/acn_caltech_r11_g0_prefit_2019.yaml"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not args.authorize_r11_g0_acquisition:
        payload: dict[str, Any] = {
            "schema_version": "evcf-r11-g0-caltech-acquisition/v1",
            "status": "FAIL",
            "reason_code": "ACQUISITION_NOT_AUTHORIZED",
            "models_trained": False,
            "model_fit_count": 0,
            "jpl_final_holdout_accessed": False,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 2
    try:
        protocol, months = acquire_resumable_v2(
            raw_root=args.raw_root,
            code_commit=args.code_commit,
            repo_root=args.repo_root.resolve(),
            protocol_path=args.protocol_path,
        )
        payload = {
            "schema_version": "evcf-r11-g0-caltech-acquisition/v1",
            "status": "COMPLETE",
            "site_id": protocol.site_id,
            "protocol_sha256": protocol.protocol_sha256,
            "code_commit": args.code_commit,
            "months": [item.public_dict() for item in months],
            "models_trained": False,
            "model_fit_count": 0,
            "jpl_final_holdout_accessed": False,
            "session_predictors_used": False,
            "disconnect_filter_sent_to_server": False,
            "resumable_materialization": True,
        }
        code = 0
    except Exception as exc:  # noqa: BLE001
        payload = {
            "schema_version": "evcf-r11-g0-caltech-acquisition/v1",
            "status": "FAIL",
            "reason_code": _safe_reason(exc),
            "models_trained": False,
            "model_fit_count": 0,
            "jpl_final_holdout_accessed": False,
        }
        code = 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
