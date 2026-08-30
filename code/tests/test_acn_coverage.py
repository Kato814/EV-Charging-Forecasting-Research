from __future__ import annotations

from datetime import timezone
from typing import Any

import pytest

from evcf.data.acn_coverage import (
    collect_monthly_coverage,
    iter_months,
    local_month_bounds,
    summarize_monthly_coverage,
)


class FakeClient:
    def __init__(self, totals: list[int]) -> None:
        self.totals = totals
        self.queries: list[Any] = []

    def iter_pages(self, query: Any):
        self.queries.append(query)
        total = self.totals.pop(0)
        yield {
            "_meta": {"total": total},
            "_items": [{}] * min(total, 25),
            "_links": {},
        }


def test_iter_months_is_inclusive_and_validates_order() -> None:
    assert list(iter_months("2019-11", "2020-02")) == [
        (2019, 11),
        (2019, 12),
        (2020, 1),
        (2020, 2),
    ]
    with pytest.raises(ValueError, match="start_month"):
        list(iter_months("2020-02", "2019-11"))


def test_local_month_bounds_respect_daylight_saving() -> None:
    start, end = local_month_bounds(2019, 3, "America/Los_Angeles")
    assert start.utcoffset() != end.utcoffset()
    assert start.astimezone(timezone.utc).isoformat() == "2019-03-01T08:00:00+00:00"
    assert end.astimezone(timezone.utc).isoformat() == "2019-04-01T07:00:00+00:00"


def test_collect_and_summarize_monthly_coverage() -> None:
    client = FakeClient([0, 12, 25, 0, 9])
    records = collect_monthly_coverage(
        client,  # type: ignore[arg-type]
        site="caltech",
        start_month="2019-01",
        end_month="2019-05",
        timezone_name="America/Los_Angeles",
    )
    assert [record.session_count for record in records] == [0, 12, 25, 0, 9]
    assert records[1].start_local.startswith("2019-02-01T00:00:00")
    assert all(query.site == "caltech" for query in client.queries)

    summary = summarize_monthly_coverage(records)
    assert summary["months_queried"] == 5
    assert summary["months_with_sessions"] == 3
    assert summary["total_sessions_reported"] == 46
    assert summary["earliest_nonzero_month"] == "2019-02"
    assert summary["latest_nonzero_month"] == "2019-05"
    assert summary["maximum_month"] == "2019-03"
    assert summary["longest_nonzero_run_start"] == "2019-02"
    assert summary["longest_nonzero_run_end"] == "2019-03"
    assert summary["longest_nonzero_run_months"] == 2
