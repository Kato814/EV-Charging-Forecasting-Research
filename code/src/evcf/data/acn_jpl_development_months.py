"""Fail-closed temporary month contracts for the 2019 JPL method-development set.

The production month registry intentionally remains unchanged.  Development
months are installed only inside an explicit context used by the dedicated
acquisition/preparation CLIs.  Final holdout months are never installed here.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import evcf.data.acn_jpl_month_config as month_config
from evcf.data.acn_jpl_month_config import JPLMonthConfig

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
_EXPECTED_BASE_APPROVED = ("2019-02", "2019-05", "2019-08", "2019-11")
_EXPECTED_SEASONAL_MONTHS = ("2019-02", "2019-08", "2019-11")


class DevelopmentMonthContractError(RuntimeError):
    """Raised when the frozen month registry no longer matches this extension."""


def _verify_base_registry() -> None:
    if tuple(month_config._APPROVED_MONTHS) != _EXPECTED_BASE_APPROVED:
        raise DevelopmentMonthContractError("base approved-month registry drifted")
    if tuple(month_config.SEASONAL_MONTHS) != _EXPECTED_SEASONAL_MONTHS:
        raise DevelopmentMonthContractError("seasonal month registry drifted")
    if any(month in month_config._MONTH_CONFIGS for month in DEVELOPMENT_MONTHS):
        raise DevelopmentMonthContractError("development month unexpectedly pre-approved")
    if any(month in month_config._MONTH_CONFIGS for month in FINAL_HOLDOUT_MONTHS):
        raise DevelopmentMonthContractError("final holdout month must remain unapproved")


def development_month_contracts() -> Mapping[str, JPLMonthConfig]:
    """Build the four frozen development configs without installing them."""

    _verify_base_registry()
    return {month: month_config._make_month_config(month) for month in DEVELOPMENT_MONTHS}


@contextmanager
def installed_development_month_contracts() -> Iterator[Mapping[str, JPLMonthConfig]]:
    """Temporarily extend the canonical registry with development months only.

    The registry is restored exactly on exit, including when acquisition fails.
    Holdout months never become canonical through this context.
    """

    contracts = dict(development_month_contracts())
    old_approved = month_config._APPROVED_MONTHS
    old_configs = month_config._MONTH_CONFIGS
    month_config._APPROVED_MONTHS = (*old_approved, *DEVELOPMENT_MONTHS)
    month_config._MONTH_CONFIGS = {**old_configs, **contracts}
    try:
        for month, config in contracts.items():
            canonical = month_config.jpl_month_config(month)
            if canonical is not config or not month_config.is_canonical_jpl_month_config(config):
                raise DevelopmentMonthContractError("development contract did not become canonical")
        for month in FINAL_HOLDOUT_MONTHS:
            try:
                month_config.jpl_month_config(month)
            except ValueError:
                continue
            raise DevelopmentMonthContractError("final holdout month became approved")
        yield contracts
    finally:
        month_config._APPROVED_MONTHS = old_approved
        month_config._MONTH_CONFIGS = old_configs
