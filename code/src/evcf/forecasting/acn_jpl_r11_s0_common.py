"""Frozen constants and fail-closed errors for JPL R11-S0."""

from __future__ import annotations

from types import MappingProxyType

DEVELOPMENT_MONTHS = ("2019-01", "2019-04", "2019-07", "2019-10")
FINAL_HOLDOUT_MONTHS = ("2019-03", "2019-06", "2019-09", "2019-12")
HORIZONS_MINUTES = (15, 30, 60, 120, 240)
TIMEZONE_NAME = "America/Los_Angeles"
CONTEXT_LENGTH = 96
HISTORY_CHANNELS = 2
ISSUE_CONTEXT_WIDTH = 5
TARGET_CONTEXT_WIDTH = 6
DECODER_CONTEXT_WIDTH = ISSUE_CONTEXT_WIDTH + TARGET_CONTEXT_WIDTH
TEST_START_LOCAL_DAY = 18
TRAIN_LAST_LOCAL_DAY = 14
VALIDATION_FIRST_LOCAL_DAY = 15
VALIDATION_LAST_LOCAL_DAY = 17
MAX_HORIZON_MINUTES = 240
EXPECTED_TEST_ORIGINS = MappingProxyType(
    {"2019-01": 1305, "2019-04": 1180, "2019-07": 1294, "2019-10": 1296}
)
DEEP_ARCHITECTURES = ("gru", "tcn", "nhits", "patchtst")
DEEP_SEEDS = (2026091401, 2026091402, 2026091403)
BATCH_SIZE = 256
MAX_EPOCHS = 120
PATIENCE = 12
MIN_VALIDATION_IMPROVEMENT = 1e-4
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
GRADIENT_CLIP_NORM = 1.0
MIN_PARAMETER_COUNT = 50_000
MAX_PARAMETER_COUNT = 250_000
EXPECTED_DEEP_FITS = 48
EXPECTED_HGB_FITS = 20
EXPECTED_FIT_COUNT = 68


class R11S0Error(RuntimeError):
    """Identifier-free failure safe for public R11-S0 status output."""

    def __init__(self, reason_code: str) -> None:
        if not isinstance(reason_code, str) or not reason_code.replace("_", "").isalnum():
            reason_code = "UNEXPECTED_ERROR"
        self.reason_code = reason_code
        super().__init__(reason_code)
