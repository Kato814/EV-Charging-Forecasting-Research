from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from evcf.data.acn_caltech_r11_g0 import (
    HORIZONS_MINUTES,
    OverlapQuery,
    _arrival_labels,
    load_protocol,
    month_config,
)
from evcf.data.acn_jpl_cleaning import IntegralContribution


def test_frozen_protocol_and_month_grid() -> None:
    protocol = load_protocol("code/configs/acn_caltech_r11_g0_prefit_2019.yaml")
    assert protocol.site_id == "caltech"
    assert protocol.months == ("2019-02", "2019-05", "2019-08", "2019-11")
    assert protocol.horizons_minutes == (15, 30, 60, 120, 240)
    assert protocol.maximum_quarantine_fraction == 0.001

    feb = month_config("2019-02")
    nov = month_config("2019-11")
    assert feb.expected_bins == 28 * 96
    assert feb.expected_scheduled_issue_times == 28 * 96 - 111
    assert nov.expected_bins == 30 * 96 + 4
    assert nov.expected_scheduled_issue_times == 30 * 96 + 4 - 111


def test_overlap_query_uses_connection_and_disconnect_bounds() -> None:
    config = month_config("2019-05")
    query = OverlapQuery(
        site="caltech",
        start=config.utc_start,
        end=config.utc_end,
        timeseries=True,
    )
    assert query.endpoint == "sessions/caltech/ts"
    assert "connectionTime <" in query.condition
    assert "disconnectTime >" in query.condition
    assert query.public_dict()["selection"] == (
        "connectionTime < month_end and disconnectTime > month_start"
    )


def test_component_label_split_reconstructs_target_bins() -> None:
    config = month_config("2019-02")
    start = int(config.utc_start.timestamp())
    issue = start + 96 * 15 * 60

    existing_contributions = []
    arrival_contributions = []
    labels = np.empty((1, len(HORIZONS_MINUTES)), dtype=np.float64)
    expected_arrival = np.empty_like(labels)
    for position, horizon in enumerate(HORIZONS_MINUTES):
        target_start = issue + (horizon - 15) * 60
        target_end = issue + horizon * 60
        existing_contributions.append(
            IntegralContribution(
                start_utc_s=target_start,
                end_utc_s=target_end,
                value=10.0,
                raw_ordinal=position,
            )
        )
        arrival_start = max(target_start, issue + 1)
        arrival_contributions.append(
            IntegralContribution(
                start_utc_s=arrival_start,
                end_utc_s=target_end,
                value=5.0,
                raw_ordinal=position,
            )
        )
        arrival_mean = 5.0 * (target_end - arrival_start) / (15 * 60)
        expected_arrival[0, position] = arrival_mean
        labels[0, position] = 10.0 + arrival_mean

    existing = SimpleNamespace(
        connection_utc_s=issue - 3600,
        current=SimpleNamespace(
            main_integral=SimpleNamespace(contributions=tuple(existing_contributions))
        ),
    )
    arrival = SimpleNamespace(
        connection_utc_s=issue + 1,
        current=SimpleNamespace(
            main_integral=SimpleNamespace(contributions=tuple(arrival_contributions))
        ),
    )
    values, error = _arrival_labels(
        sessions=(existing, arrival),
        config=config,
        issue=np.asarray([issue], dtype=np.int64),
        labels=labels,
        tolerance=1e-6,
    )
    np.testing.assert_allclose(values, expected_arrival, rtol=0.0, atol=1e-12)
    assert error <= 1e-12
