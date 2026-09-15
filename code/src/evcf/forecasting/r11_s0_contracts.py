"""Frozen contracts for R11-S0 station-level deep-backbone screening.

This module is intentionally lightweight and contains no real-data fitting.  It
centralizes the aggregate-only feature contract, chronology, parameter band and
formal fit budget frozen by the R11-S0 protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np

DEVELOPMENT_MONTHS: Final[tuple[str, ...]] = (
    "2019-01",
    "2019-04",
    "2019-07",
    "2019-10",
)
FINAL_HOLDOUT_MONTHS: Final[tuple[str, ...]] = (
    "2019-03",
    "2019-06",
    "2019-09",
    "2019-12",
)
HORIZONS_MINUTES: Final[tuple[int, ...]] = (15, 30, 60, 120, 240)
CONTEXT_LENGTH: Final[int] = 96
HISTORY_CHANNELS: Final[int] = 2
ISSUE_CONTEXT_WIDTH: Final[int] = 5
TARGET_CONTEXT_WIDTH: Final[int] = 6
EXPECTED_TEST_ORIGINS: Final[dict[str, int]] = {
    "2019-01": 1305,
    "2019-04": 1180,
    "2019-07": 1294,
    "2019-10": 1296,
}
DEEP_SEEDS: Final[tuple[int, ...]] = (2026091401, 2026091402, 2026091403)
PARAMETER_BAND: Final[tuple[int, int]] = (50_000, 250_000)
EXPECTED_DEEP_FITS: Final[int] = 48
EXPECTED_HGB_FITS: Final[int] = 20
EXPECTED_TOTAL_FITS: Final[int] = 68


class R11S0ContractError(RuntimeError):
    """Static fail-closed error for a frozen R11-S0 contract violation."""


@dataclass(frozen=True, slots=True)
class StationSample:
    """One aggregate-only five-horizon sample."""

    history: np.ndarray
    issue_context: np.ndarray
    target_context: np.ndarray
    target: np.ndarray

    def validate(self) -> None:
        if self.history.shape != (CONTEXT_LENGTH, HISTORY_CHANNELS):
            raise R11S0ContractError("INVALID_HISTORY_SHAPE")
        if self.issue_context.shape != (ISSUE_CONTEXT_WIDTH,):
            raise R11S0ContractError("INVALID_ISSUE_CONTEXT_SHAPE")
        if self.target_context.shape != (len(HORIZONS_MINUTES), TARGET_CONTEXT_WIDTH):
            raise R11S0ContractError("INVALID_TARGET_CONTEXT_SHAPE")
        if self.target.shape != (len(HORIZONS_MINUTES),):
            raise R11S0ContractError("INVALID_TARGET_SHAPE")
        for value, reason in (
            (self.history, "NONFINITE_HISTORY"),
            (self.issue_context, "NONFINITE_ISSUE_CONTEXT"),
            (self.target_context, "NONFINITE_TARGET_CONTEXT"),
            (self.target, "NONFINITE_TARGET"),
        ):
            if not np.isfinite(value).all():
                raise R11S0ContractError(reason)


def assert_authorized_month(month: str) -> None:
    if month in FINAL_HOLDOUT_MONTHS:
        raise R11S0ContractError("FINAL_HOLDOUT_ACCESS_PROHIBITED")
    if month not in DEVELOPMENT_MONTHS:
        raise R11S0ContractError("UNAUTHORIZED_MONTH")


def assert_test_origin_counts(counts: dict[str, int]) -> None:
    if counts != EXPECTED_TEST_ORIGINS:
        raise R11S0ContractError("FROZEN_TEST_ORIGIN_IDENTITY_MISMATCH")


def validate_parameter_count(count: int) -> None:
    low, high = PARAMETER_BAND
    if not low <= int(count) <= high:
        raise R11S0ContractError("PARAMETER_COUNT_OUTSIDE_FROZEN_BAND")
