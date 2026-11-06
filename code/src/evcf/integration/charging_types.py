"""Immutable carriers for artificial charging only; boundaries validate their values."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from .controller_common import AdmissionError


@dataclass(frozen=True)
class ChargeAction:
    session_id: str
    device_id: str
    start_utc: datetime
    end_utc: datetime
    power_kw: float


@dataclass(frozen=True)
class DeliveredEnergy:
    session_id: str
    device_id: str
    energy_kwh: float


@dataclass(frozen=True)
class EnergySnapshot:
    as_of_utc: datetime
    entries: tuple[DeliveredEnergy, ...]


def utc_datetime(value, label):
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise AdmissionError('INVALID_TIME', f'{label} requires an aware UTC datetime')
    return value


def step_end(issue, step_seconds):
    issue = utc_datetime(issue, 'issue')
    if type(step_seconds) is not int or step_seconds <= 0:
        raise AdmissionError('INVALID_STEP', 'step_seconds must be a positive integer')
    try:
        return issue + timedelta(seconds=step_seconds)
    except OverflowError as exc:
        raise AdmissionError('INVALID_STEP', 'step is outside datetime range') from exc
