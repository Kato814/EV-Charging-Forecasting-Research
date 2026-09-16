"""Resumable acquisition for the frozen R11-G0 Caltech overlap scope.

This is an acquisition-engineering repair only. The frozen scientific scope remains
`connectionTime < month_end and disconnectTime > month_start`. To avoid losing a
whole month when ACN-Data intermittently fails after hundreds of `/ts` pages, the
same overlap set is materialized as the disjoint union of:

1. carry-in sessions: connected before month start and disconnected after it; and
2. local-day connection-time chunks within the target month.

Completed chunk files are hash-validated and reused on retry. The final month file
is accepted only when its unique-session count exactly equals an independent
metadata-only overlap query total. No model is imported or trained here.
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
from typing import Any
from zoneinfo import ZoneInfo

from evcf.data.acn_api import (
    ACNAuthenticationError,
    ACNClient,
    ACNQuery,
    DEFAULT_API_BASE_URL,
    DEFAULT_TOKEN_ENV,
    download_sessions,
    format_http_date,
    iter_jsonl,
)
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

_SCRIPT_PATH = "scripts/acquire_caltech_r11_g0_resumable.py"
_TIMEZONE = ZoneInfo("America/Los_Angeles")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True, slots=True)
class CarryQuery:
    """ACN query adapter for sessions already connected at month start."""

    site: str
    boundary: datetime
    timeseries: bool
    max_sessions: int | None = None
    sort: str = "-connectionTime"

    @property
    def condition(self) -> str:
        edge = format_http_date(self.boundary.astimezone(timezone.utc))
        return f'connectionTime < "{edge}" and disconnectTime > "{edge}"'

    @property
    def endpoint(self) -> str:
        return f"sessions/{self.site}" + ("/ts" if self.timeseries else "")

    def public_dict(self) -> dict[str, Any]:
        edge = self.boundary.astimezone(timezone.utc).isoformat()
        return {
            "site": self.site,
            "boundary_utc": edge,
            "timeseries": self.timeseries,
            "max_sessions": self.max_sessions,
            "sort": self.sort,
            "where": self.condition,
            "endpoint": self.endpoint,
            "selection": "connectionTime < month_start and disconnectTime > month_start",
        }


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


def _chunk_paths(month_root: Path, name: str) -> tuple[Path, Path]:
    data = month_root / "chunks" / f"{name}.jsonl"
    return data, data.with_suffix(data.suffix + ".manifest.json")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID") from exc
    if not isinstance(value, dict):
        raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID")
    return value


def _validate_completed_chunk(data: Path, manifest: Path, query: object) -> int:
    present = (data.exists(), manifest.exists())
    if any(present) and not all(present):
        raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID")
    if not all(present):
        return -1
    document = _load_json(manifest)
    count = document.get("record_count")
    if (
        document.get("schema_version") != "acn-download-manifest/v1"
        or document.get("query") != query.public_dict()  # type: ignore[attr-defined]
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
    query: object,
    data: Path,
    manifest: Path,
) -> int:
    existing = _validate_completed_chunk(data, manifest, query)
    if existing >= 0:
        return existing
    try:
        result = download_sessions(client, query, data, overwrite=False)  # type: ignore[arg-type]
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


def _local_day_queries(config: object) -> tuple[tuple[str, ACNQuery], ...]:
    start = config.local_start  # type: ignore[attr-defined]
    end = config.local_end  # type: ignore[attr-defined]
    output: list[tuple[str, ACNQuery]] = []
    current = start
    while current < end:
        following = current + timedelta(days=1)
        # Reconstruct at local midnight so DST transitions produce the correct UTC span.
        following = datetime(
            following.year,
            following.month,
            following.day,
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


def _write_final_month(
    *,
    raw: Path,
    manifest_path: Path,
    chunk_paths: tuple[Path, ...],
    total: int,
    overlap_query: OverlapQuery,
) -> str:
    raw.parent.mkdir(parents=True, exist_ok=True)
    partial = raw.with_suffix(raw.suffix + ".partial")
    manifest_partial = manifest_path.with_name(manifest_path.name + ".partial")
    if any(path.exists() for path in (raw, manifest_path, partial, manifest_partial)):
        raise R11G0Error("EXISTING_RAW_IDENTITY_INVALID")

    digest = hashlib.sha256()
    count = 0
    identities: set[tuple[str, str]] = set()
    try:
        with partial.open("xb") as handle:
            for chunk in chunk_paths:
                for record in iter_jsonl(chunk):
                    object_id, session_id = record.get("_id"), record.get("sessionID")
                    if (
                        not isinstance(object_id, str)
                        or not object_id
                        or not isinstance(session_id, str)
                        or not session_id
                    ):
                        raise R11G0Error("RAW_IDENTITY_INVALID")
                    identity = (object_id, session_id)
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
                    count += 1
            handle.flush()
            os.fsync(handle.fileno())
        if count != total or total <= 0:
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
            "record_count": count,
            "remote_total_reported": total,
            "complete_for_query": True,
            "sha256": digest.hexdigest(),
            "notes": [
                "Frozen overlap scope materialized resumably from carry-in plus local-day connection chunks.",
                "Final unique-session count equals an independent metadata-only overlap total.",
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
        # Preserve a completed final raw file if an unlikely manifest-write failure occurs;
        # the next run will fail closed instead of silently deleting evidence.
        raise


def acquire_resumable(
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

        overlap_metadata = OverlapQuery("caltech", config.utc_start, config.utc_end, False)
        overlap_timeseries = OverlapQuery("caltech", config.utc_start, config.utc_end, True)
        try:
            total = client.fetch_total_once(overlap_metadata)  # type: ignore[arg-type]
        except ACNAuthenticationError as exc:
            raise R11G0Error("ACN_AUTHENTICATION_FAILED") from exc
        except Exception as exc:
            raise R11G0Error("ACN_ACQUISITION_FAILED") from exc
        if total <= 0:
            raise R11G0Error("ACN_ACQUISITION_INTEGRITY_FAILED")

        month_root = root / month
        chunk_files: list[Path] = []

        carry_ts = CarryQuery("caltech", config.utc_start, True)
        carry_data, carry_manifest = _chunk_paths(month_root, "carry_in")
        _download_or_reuse(client, carry_ts, carry_data, carry_manifest)
        chunk_files.append(carry_data)

        for day_name, query in _local_day_queries(config):
            data, manifest = _chunk_paths(month_root, f"day_{day_name}")
            _download_or_reuse(client, query, data, manifest)
            chunk_files.append(data)

        raw_sha = _write_final_month(
            raw=raw,
            manifest_path=manifest_path,
            chunk_paths=tuple(chunk_files),
            total=total,
            overlap_query=overlap_timeseries,
        )
        _validate_raw(raw, config, total)
        _atomic_json(
            summary_path,
            {
                "schema_version": "evcf-r11-g0-caltech-acquisition-month/v1",
                "status": "COMPLETE",
                "month": month,
                "site_id": "caltech",
                "protocol_sha256": protocol.protocol_sha256,
                "session_count": total,
                "metadata_total": total,
                "raw_sha256": raw_sha,
                "partial_file_count": 0,
                "timeseries": True,
                "overlap_selection": True,
                "resumable_materialization": True,
                "identifiers_public": False,
                "token_stored": False,
            },
        )
        results.append(AcquisitionMonthResult(month, total, raw_sha, False))
    return protocol, tuple(results)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resumable Caltech R11-G0 acquisition")
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
        protocol, months = acquire_resumable(
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
