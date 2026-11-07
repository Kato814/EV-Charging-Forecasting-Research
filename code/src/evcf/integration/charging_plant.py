"""Artificial charging with exact overlap accounting, not battery or grid physics.

Evaluation targets never constrain delivery. Efficiency is one and commands are
constant throughout a step, with no tapering, losses or within-step redistribution.
"""

from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from math import fsum

from .charging_types import ChargeAction, DeliveredEnergy, EnergySnapshot, step_end, utc_datetime
from .controller_common import AdmissionError, identifier, number


@dataclass(frozen=True)
class TruthSession:
    session_id: str
    device_id: str
    arrival_utc: datetime
    departure_utc: datetime
    required_energy_kwh: float
    max_power_kw: float


@dataclass(frozen=True)
class StepResult:
    start_utc: datetime
    end_utc: datetime
    commanded_kw: float
    delivered_kwh: float
    increments: tuple[DeliveredEnergy, ...]


@dataclass(frozen=True)
class SessionEvaluation:
    session_id: str
    departed: bool
    required_kwh: float
    delivered_kwh: float
    shortfall_kwh: float
    overdelivery_kwh: float


@dataclass(frozen=True)
class Evaluation:
    complete: bool
    delivered_kwh: float
    shortfall_kwh: float
    overdelivery_kwh: float
    sessions: tuple[SessionEvaluation, ...]


def _finite_sum(values, label):
    try:
        total = fsum(values)
    except OverflowError as exc:
        raise AdmissionError('INVALID_NUMBER', f'{label} must remain finite') from exc
    return number(total, label)


class SyntheticPlant:
    """Own artificial truth; expose only already-realized energy through feedback."""

    def __init__(self, sessions: tuple[TruthSession, ...], *, start_utc, capacity_kw):
        start = utc_datetime(start_utc, 'start_utc')
        capacity = number(capacity_kw, 'capacity_kw')
        if type(sessions) is not tuple:
            raise AdmissionError('INVALID_SCHEMA', 'sessions must be a tuple of TruthSession')
        admitted = {}
        devices = {}
        for session in sessions:
            if type(session) is not TruthSession:
                raise AdmissionError('INVALID_SCHEMA', 'sessions must contain TruthSession records')
            session_id = identifier(session.session_id, 'session_id')
            device_id = identifier(session.device_id, 'device_id')
            arrival = utc_datetime(session.arrival_utc, 'arrival_utc')
            departure = utc_datetime(session.departure_utc, 'departure_utc')
            required = number(session.required_energy_kwh, 'required_energy_kwh')
            limit = number(session.max_power_kw, 'max_power_kw')
            if session_id in admitted:
                raise AdmissionError('DUPLICATE_SESSION', 'truth session IDs must be unique')
            if arrival < start or departure <= arrival:
                raise AdmissionError('INVALID_INTERVAL', 'sessions require start <= arrival < departure')
            admitted[session_id] = TruthSession(
                session_id, device_id, arrival, departure, required, limit
            )
            devices.setdefault(device_id, []).append((arrival, departure))
        for intervals in devices.values():
            ordered = sorted(intervals)
            if any(current[0] < previous[1] for previous, current in pairwise(ordered)):
                raise AdmissionError('OVERLAPPING_DEVICE', 'device connection intervals cannot overlap')
        _finite_sum((session.required_energy_kwh for session in admitted.values()),
                    'aggregate required energy')
        self._sessions = admitted
        self._cursor = start
        self._capacity_kw = capacity
        self._delivered = {session_id: 0.0 for session_id in self._sessions}

    def _issue(self, issue_time_utc):
        issue = utc_datetime(issue_time_utc, 'issue_time_utc')
        if issue != self._cursor:
            raise AdmissionError('INVALID_CURSOR', 'issue_time_utc must equal the current cursor')
        return issue

    def feedback(self, session_ids: tuple[str, ...], *, issue_time_utc) -> EnergySnapshot:
        """Return requested cumulative kWh, without departure times or evaluation targets."""
        issue = self._issue(issue_time_utc)
        if type(session_ids) is not tuple:
            raise AdmissionError('INVALID_SCHEMA', 'session_ids must be a tuple')
        seen = set()
        for session_id in session_ids:
            identifier(session_id, 'session_id')
            if session_id in seen:
                raise AdmissionError('DUPLICATE_SESSION', 'feedback IDs must be unique')
            seen.add(session_id)
            if session_id not in self._sessions:
                raise AdmissionError('UNKNOWN_SESSION', 'feedback requires an existing session')
            if self._sessions[session_id].arrival_utc > issue:
                raise AdmissionError('NOT_ARRIVED', 'feedback requires an already-arrived session')
        return EnergySnapshot(issue, tuple(
            DeliveredEnergy(session_id, self._sessions[session_id].device_id,
                            self._delivered[session_id])
            for session_id in session_ids
        ))

    def execute(self, actions: tuple[ChargeAction, ...], *, issue_time_utc,
                step_seconds=900) -> StepResult:
        """Validate the entire batch, then atomically advance exactly one interval.

        A command to a departed session remains admissible but delivers no energy.
        Required energy is intentionally absent from every execution calculation.
        """
        issue = self._issue(issue_time_utc)
        end = step_end(issue, step_seconds)
        if type(actions) is not tuple:
            raise AdmissionError('INVALID_SCHEMA', 'actions must be a tuple of ChargeAction')
        admitted = []
        seen_sessions = set()
        seen_devices = set()
        for action in actions:
            if type(action) is not ChargeAction:
                raise AdmissionError('INVALID_SCHEMA', 'actions must contain ChargeAction records')
            session_id = identifier(action.session_id, 'action.session_id')
            device_id = identifier(action.device_id, 'action.device_id')
            action_start = utc_datetime(action.start_utc, 'action.start_utc')
            action_end = utc_datetime(action.end_utc, 'action.end_utc')
            power = number(action.power_kw, 'action.power_kw')
            if action_start != issue or action_end != end:
                raise AdmissionError('INVALID_INTERVAL', 'each action must span exactly this step')
            if session_id not in self._sessions:
                raise AdmissionError('UNKNOWN_SESSION', 'actions require existing sessions')
            session = self._sessions[session_id]
            if device_id != session.device_id:
                raise AdmissionError('DEVICE_MISMATCH', 'action device must match the session')
            if session_id in seen_sessions or device_id in seen_devices:
                raise AdmissionError('DUPLICATE_ACTION', 'one action per session and device is allowed')
            if power > session.max_power_kw:
                raise AdmissionError('DEVICE_LIMIT', 'action exceeds the session device power limit')
            seen_sessions.add(session_id)
            seen_devices.add(device_id)
            admitted.append((session, power))
        commanded = _finite_sum((power for _, power in admitted), 'aggregate commanded power')
        if commanded > self._capacity_kw:
            raise AdmissionError('CAPACITY_LIMIT', 'commands exceed aggregate power capacity')
        increments = []
        delivered = self._delivered.copy()
        for session, power in admitted:
            connected_seconds = max(0.0, (
                min(end, session.departure_utc) - max(issue, session.arrival_utc)
            ).total_seconds())
            energy = number(power * (connected_seconds / 3600), 'delivered increment')
            delivered[session.session_id] = number(
                delivered[session.session_id] + energy, 'session cumulative energy'
            )
            increments.append(DeliveredEnergy(session.session_id, session.device_id, energy))
        step_energy = _finite_sum((entry.energy_kwh for entry in increments), 'step energy')
        _finite_sum(delivered.values(), 'aggregate cumulative energy')
        result = StepResult(issue, end, commanded, step_energy, tuple(increments))
        self._delivered = delivered
        self._cursor = end
        return result

    def evaluate(self) -> Evaluation:
        """Current deficits are final only once every artificial session has departed."""
        sessions = tuple(
            SessionEvaluation(
                session.session_id, session.departure_utc <= self._cursor,
                session.required_energy_kwh, self._delivered[session.session_id],
                max(session.required_energy_kwh - self._delivered[session.session_id], 0.0),
                max(self._delivered[session.session_id] - session.required_energy_kwh, 0.0),
            )
            for session in self._sessions.values()
        )
        return Evaluation(all(session.departed for session in sessions),
                          _finite_sum((session.delivered_kwh for session in sessions), 'delivery'),
                          _finite_sum((session.shortfall_kwh for session in sessions), 'shortfall'),
                          _finite_sum((session.overdelivery_kwh for session in sessions), 'overdelivery'),
                          sessions)
