"""Fail-closed temporary month contracts for the 2019 JPL method-development set.

The production month registry intentionally remains unchanged. Development
months are installed only inside an explicit context used by dedicated local
acquisition/preparation entrypoints. Final holdout months are never installed.

Several reviewed seasonal modules imported ``SEASONAL_MONTHS`` by value before
this extension existed. The context therefore installs one narrow compatibility
policy in those modules for its lifetime only, then restores every module-level
binding exactly. This avoids permanently broadening the production registry or
silently authorizing the final holdout months.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from types import ModuleType
from typing import Any

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


def _seasonal_compatibility_modules() -> tuple[ModuleType, ...]:
    # Delayed imports avoid expanding the import surface for callers that only
    # need the partition constants or a dry month-contract inspection.
    import evcf.data.acn_jpl_full_month_qa as full_month_qa
    import evcf.data.acn_jpl_preparation as preparation
    import evcf.data.acn_jpl_seasonal_acquisition as acquisition

    return acquisition, full_month_qa, preparation


def _development_quarantine_wrapper(original: Any) -> Any:
    import evcf.data.acn_jpl_trajectory_quarantine as quarantine

    def build(
        config: object,
        decisions: tuple[Any, ...],
        *,
        denominator_sessions: int,
    ) -> Any:
        month = getattr(config, "month", None)
        if month not in DEVELOPMENT_MONTHS:
            return original(
                config,
                decisions,
                denominator_sessions=denominator_sessions,
            )
        trajectory = tuple(
            decision
            for decision in decisions
            if getattr(decision, "action", None) == quarantine.TRAJECTORY_QUARANTINE
        )
        full = tuple(
            decision
            for decision in decisions
            if getattr(decision, "action", None) == quarantine.FULL_SESSION_QUARANTINE
        )
        # No quarantine signature has been scientifically approved for the new
        # development months. Any synchronized reversal therefore fails the QA
        # gate instead of inheriting November's unique 3,596-second exception.
        approved = bool(
            isinstance(denominator_sessions, int)
            and not isinstance(denominator_sessions, bool)
            and denominator_sessions > 0
            and not trajectory
            and not full
        )
        return quarantine.TrajectoryQuarantineAudit(
            approved=approved,
            denominator_sessions=denominator_sessions,
            trajectory_quarantine_count=len(trajectory),
            full_session_quarantine_count=len(full),
            quarantined_current_nonmonotonic_pairs=sum(
                int(getattr(decision, "current_nonmonotonic_pairs", 0))
                for decision in (*trajectory, *full)
            ),
            quarantined_pilot_nonmonotonic_pairs=sum(
                int(getattr(decision, "pilot_nonmonotonic_pairs", 0))
                for decision in (*trajectory, *full)
            ),
        )

    return build


@contextmanager
def installed_development_month_contracts() -> Iterator[Mapping[str, JPLMonthConfig]]:
    """Temporarily extend only the reviewed path needed for development months.

    The canonical registry, imported seasonal allowlists, and quarantine policy
    are restored exactly on exit, including when acquisition fails. Holdout
    months never become canonical through this context.
    """

    contracts = dict(development_month_contracts())
    compatibility_modules = _seasonal_compatibility_modules()
    for module in compatibility_modules:
        if tuple(module.SEASONAL_MONTHS) != _EXPECTED_SEASONAL_MONTHS:  # type: ignore[attr-defined]
            raise DevelopmentMonthContractError("imported seasonal allowlist drifted")

    import evcf.data.acn_jpl_full_month_qa as full_month_qa

    old_approved = month_config._APPROVED_MONTHS
    old_configs = month_config._MONTH_CONFIGS
    old_module_months = tuple(
        (module, module.SEASONAL_MONTHS)  # type: ignore[attr-defined]
        for module in compatibility_modules
    )
    old_quarantine_builder = full_month_qa.build_trajectory_quarantine_audit

    month_config._APPROVED_MONTHS = (*old_approved, *DEVELOPMENT_MONTHS)
    month_config._MONTH_CONFIGS = {**old_configs, **contracts}
    extended_seasonal = (*_EXPECTED_SEASONAL_MONTHS, *DEVELOPMENT_MONTHS)
    for module in compatibility_modules:
        module.SEASONAL_MONTHS = extended_seasonal  # type: ignore[attr-defined]
    full_month_qa.build_trajectory_quarantine_audit = _development_quarantine_wrapper(
        old_quarantine_builder
    )

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
        full_month_qa.build_trajectory_quarantine_audit = old_quarantine_builder
        for module, old_months in old_module_months:
            module.SEASONAL_MONTHS = old_months  # type: ignore[attr-defined]
        month_config._APPROVED_MONTHS = old_approved
        month_config._MONTH_CONFIGS = old_configs
