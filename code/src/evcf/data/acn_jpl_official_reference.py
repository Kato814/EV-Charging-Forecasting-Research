"""One-request official count reference for the JPL May 2019 local month."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path

from .acn_api import ACNClient, ACNQuery
from .acn_jpl_gate0 import (
    JPL_ANALYSIS_END,
    JPL_ANALYSIS_START,
    JPL_TIMEZONE,
)


@dataclass(frozen=True)
class OfficialLocalMonthTotalResult:
    """Validated aggregate total and its secret-free local evidence path."""

    total: int
    reference_path: Path


def _atomic_write_reference(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def probe_official_local_month_total(
    client: ACNClient,
    destination: str | Path,
) -> OfficialLocalMonthTotalResult:
    """Query the complete LA-local May window exactly once and persist only total."""

    reference_path = Path(destination)
    if reference_path.exists() or reference_path.with_suffix(
        reference_path.suffix + ".partial"
    ).exists():
        raise FileExistsError(
            f"Refusing to overwrite existing official count reference: {reference_path}"
        )

    query = ACNQuery(
        site="jpl",
        start=JPL_ANALYSIS_START,
        end=JPL_ANALYSIS_END,
        timeseries=False,
    )
    total = client.fetch_total_once(query)
    payload: dict[str, object] = {
        "schema_version": "acn-jpl-official-local-month-total/v1",
        "source": "ACN-Data official REST API",
        "endpoint": query.endpoint,
        "site": "jpl",
        "timezone": JPL_TIMEZONE,
        "interval_semantics": "[start,end)",
        "local_start_inclusive": JPL_ANALYSIS_START.isoformat(),
        "local_end_exclusive": JPL_ANALYSIS_END.isoformat(),
        "utc_start_inclusive": JPL_ANALYSIS_START.astimezone(timezone.utc).isoformat(),
        "utc_end_exclusive": JPL_ANALYSIS_END.astimezone(timezone.utc).isoformat(),
        "query_condition": query.condition,
        "official_meta_total": total,
        "request_count": 1,
        "response_fields_consumed": ["_meta.total"],
        "token_stored": False,
    }
    _atomic_write_reference(reference_path, payload)
    return OfficialLocalMonthTotalResult(total=total, reference_path=reference_path)
