"""Monthly coverage diagnostics for ACN-Data metadata.

The functions in this module query only the first metadata page for each local-calendar
month and read the API-reported total. They do not request charging time series and do
not store authentication credentials.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .acn_api import ACNClient, ACNQuery, ACNSchemaError


@dataclass(frozen=True)
class MonthlyCoverageRecord:
    month: str
    start_local: str
    end_local_exclusive: str
    start_utc: str
    end_utc_exclusive: str
    session_count: int
    first_page_records: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_month(value: str) -> tuple[int, int]:
    """Parse ``YYYY-MM`` and return ``(year, month)``."""

    try:
        year_text, month_text = value.split("-", maxsplit=1)
        year = int(year_text)
        month = int(month_text)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid month {value!r}; expected YYYY-MM") from exc
    if year < 1900 or not 1 <= month <= 12:
        raise ValueError(f"Invalid month {value!r}; expected YYYY-MM")
    return year, month


def next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def iter_months(start_month: str, end_month: str) -> Iterable[tuple[int, int]]:
    """Yield inclusive calendar months from ``start_month`` through ``end_month``."""

    start = parse_month(start_month)
    end = parse_month(end_month)
    if start > end:
        raise ValueError("start_month must not be later than end_month")
    current = start
    while current <= end:
        yield current
        current = next_month(*current)


def local_month_bounds(year: int, month: int, timezone_name: str) -> tuple[datetime, datetime]:
    timezone = ZoneInfo(timezone_name)
    start = datetime(year, month, 1, tzinfo=timezone)
    end_year, end_month = next_month(year, month)
    end = datetime(end_year, end_month, 1, tzinfo=timezone)
    return start, end


def collect_monthly_coverage(
    client: ACNClient,
    *,
    site: str,
    start_month: str,
    end_month: str,
    timezone_name: str,
) -> list[MonthlyCoverageRecord]:
    """Collect API-reported session totals for local-calendar months."""

    records: list[MonthlyCoverageRecord] = []
    for year, month in iter_months(start_month, end_month):
        start_local, end_local = local_month_bounds(year, month, timezone_name)
        query = ACNQuery(site=site, start=start_local, end=end_local)
        page = next(client.iter_pages(query))
        meta = page.get("_meta")
        items = page.get("_items")
        if not isinstance(meta, dict) or not isinstance(meta.get("total"), int):
            raise ACNSchemaError("ACN-Data monthly coverage page lacks integer _meta.total")
        if not isinstance(items, list):
            raise ACNSchemaError("ACN-Data monthly coverage page lacks list _items")
        records.append(
            MonthlyCoverageRecord(
                month=f"{year:04d}-{month:02d}",
                start_local=start_local.isoformat(),
                end_local_exclusive=end_local.isoformat(),
                start_utc=query.start_utc.isoformat(),
                end_utc_exclusive=query.end_utc.isoformat(),
                session_count=int(meta["total"]),
                first_page_records=len(items),
            )
        )
    return records


def summarize_monthly_coverage(records: Iterable[MonthlyCoverageRecord]) -> dict[str, Any]:
    rows = list(records)
    nonzero = [row for row in rows if row.session_count > 0]

    longest_start: str | None = None
    longest_end: str | None = None
    longest_length = 0
    current_start: str | None = None
    current_end: str | None = None
    current_length = 0

    for row in rows:
        if row.session_count > 0:
            if current_length == 0:
                current_start = row.month
            current_end = row.month
            current_length += 1
            if current_length > longest_length:
                longest_start = current_start
                longest_end = current_end
                longest_length = current_length
        else:
            current_start = None
            current_end = None
            current_length = 0

    return {
        "months_queried": len(rows),
        "months_with_sessions": len(nonzero),
        "total_sessions_reported": sum(row.session_count for row in rows),
        "earliest_nonzero_month": nonzero[0].month if nonzero else None,
        "latest_nonzero_month": nonzero[-1].month if nonzero else None,
        "maximum_month": (
            max(nonzero, key=lambda row: row.session_count).month if nonzero else None
        ),
        "maximum_month_sessions": (
            max(row.session_count for row in nonzero) if nonzero else 0
        ),
        "longest_nonzero_run_start": longest_start,
        "longest_nonzero_run_end": longest_end,
        "longest_nonzero_run_months": longest_length,
    }
