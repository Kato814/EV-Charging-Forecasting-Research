"""One-request official count reference for an approved JPL local month."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .acn_api import ACNClient, ACNQuery
from .acn_jpl_month_config import MAY_2019, JPLMonthConfig


@dataclass(frozen=True)
class OfficialLocalMonthTotalResult:
    """Validated aggregate total and its secret-free local evidence path."""

    total: int
    reference_path: Path
    month: str
    local_start_inclusive: str
    local_end_exclusive: str
    utc_start_inclusive: str
    utc_end_exclusive: str
    request_count: Literal[1]


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
    *,
    month: JPLMonthConfig = MAY_2019,
) -> OfficialLocalMonthTotalResult:
    """Query one complete LA-local month exactly once and persist only total."""

    reference_path = Path(destination)
    if (
        reference_path.exists()
        or reference_path.with_suffix(reference_path.suffix + ".partial").exists()
    ):
        raise FileExistsError(
            f"Refusing to overwrite existing official count reference: {reference_path}"
        )

    query = ACNQuery(
        site="jpl",
        start=month.local_start,
        end=month.local_end,
        timeseries=False,
    )
    total = client.fetch_total_once(query)
    payload: dict[str, object] = {
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
    _atomic_write_reference(reference_path, payload)
    return OfficialLocalMonthTotalResult(
        total=total,
        reference_path=reference_path,
        month=month.month,
        local_start_inclusive=month.local_start.isoformat(),
        local_end_exclusive=month.local_end.isoformat(),
        utc_start_inclusive=month.utc_start.isoformat(),
        utc_end_exclusive=month.utc_end.isoformat(),
        request_count=1,
    )
