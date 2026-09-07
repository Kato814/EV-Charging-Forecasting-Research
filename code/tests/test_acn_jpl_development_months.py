from __future__ import annotations

from datetime import timedelta

import pytest
from evcf.data.acn_jpl_development_months import (
    DEVELOPMENT_MONTHS,
    FINAL_HOLDOUT_MONTHS,
    DevelopmentMonthContractError,
    development_month_contracts,
    installed_development_month_contracts,
)
from evcf.data.acn_jpl_month_config import jpl_month_config


def test_development_and_holdout_partitions_are_fixed_and_disjoint() -> None:
    assert DEVELOPMENT_MONTHS == ("2019-01", "2019-04", "2019-07", "2019-10")
    assert FINAL_HOLDOUT_MONTHS == ("2019-03", "2019-06", "2019-09", "2019-12")
    assert set(DEVELOPMENT_MONTHS).isdisjoint(FINAL_HOLDOUT_MONTHS)


def test_development_contracts_build_without_persistently_approving_months() -> None:
    contracts = development_month_contracts()
    assert tuple(contracts) == DEVELOPMENT_MONTHS
    for month in DEVELOPMENT_MONTHS:
        assert contracts[month].month == month
        with pytest.raises(ValueError, match="approved JPL month"):
            jpl_month_config(month)


def test_installed_context_approves_development_only_and_restores_registry() -> None:
    with installed_development_month_contracts() as contracts:
        assert tuple(contracts) == DEVELOPMENT_MONTHS
        for month in DEVELOPMENT_MONTHS:
            assert jpl_month_config(month) is contracts[month]
        for month in FINAL_HOLDOUT_MONTHS:
            with pytest.raises(ValueError, match="approved JPL month"):
                jpl_month_config(month)

    for month in (*DEVELOPMENT_MONTHS, *FINAL_HOLDOUT_MONTHS):
        with pytest.raises(ValueError, match="approved JPL month"):
            jpl_month_config(month)


def test_development_months_have_expected_physical_utc_grids() -> None:
    with installed_development_month_contracts():
        jan = jpl_month_config("2019-01")
        apr = jpl_month_config("2019-04")
        jul = jpl_month_config("2019-07")
        oct_ = jpl_month_config("2019-10")

        assert (jan.day_count, jan.expected_bins, jan.expected_scheduled_issue_times) == (
            31,
            2976,
            2865,
        )
        assert jan.local_start.utcoffset() == timedelta(hours=-8)
        assert jan.local_end.utcoffset() == timedelta(hours=-8)

        assert (apr.day_count, apr.expected_bins, apr.expected_scheduled_issue_times) == (
            30,
            2880,
            2769,
        )
        assert apr.local_start.utcoffset() == timedelta(hours=-7)
        assert apr.local_end.utcoffset() == timedelta(hours=-7)

        for config in (jul, oct_):
            assert (config.day_count, config.expected_bins, config.expected_scheduled_issue_times) == (
                31,
                2976,
                2865,
            )
            assert config.local_start.utcoffset() == timedelta(hours=-7)
            assert config.local_end.utcoffset() == timedelta(hours=-7)


def test_registry_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import evcf.data.acn_jpl_month_config as month_config

    monkeypatch.setattr(month_config, "_APPROVED_MONTHS", ("2019-05",))
    with pytest.raises(DevelopmentMonthContractError, match="registry drifted"):
        development_month_contracts()
