"""Declared-departure greedy charging for hand-authored, visible inputs only.

This rule makes no optimality or service-feasibility claim. Commands hold for a
whole interval, using assumed limits, unit efficiency and synchronous cumulative
energy. State age does not establish a disconnect or per-channel freshness.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from math import nextafter

from .charging_types import ChargeAction, DeliveredEnergy, EnergySnapshot, step_end, utc_datetime
from .controller_adapter import ControllerInput, MappedSession
from .controller_common import AdmissionError, identifier, number
from .controller_quantities import DeviceMapping, remaining_energy_kwh
from .controller_visibility import Declaration, SessionState

_BASES = ('recorded_reception', 'assumed_replay')


@dataclass(frozen=True)
class DispatchDecision:
    issue_time_utc: datetime
    actions: tuple[ChargeAction, ...]
    blocked: tuple[tuple[str, str], ...]
    remaining_kwh: tuple[tuple[str, float], ...]
    stale_sessions: tuple[str, ...]


def _exact(value, expected, label):
    if type(value) is not expected:
        raise AdmissionError('INVALID_POLICY_INPUT', f'{label} requires exact {expected.__name__}')


def _basis(value, mode):
    if value not in _BASES or (mode == 'recorded_reception' and value != mode):
        raise AdmissionError('UNKNOWN_AVAILABILITY', 'availability basis conflicts with view mode')


def _validate_mapping(mapping, state, issue, site_id, cluster_id):
    _exact(mapping, DeviceMapping, 'mapping')
    for name in ('site_id', 'cluster_id', 'station_id', 'space_id',
                 'topology_label', 'node_id', 'evidence_id'):
        identifier(getattr(mapping, name), name)
    if (mapping.site_id, mapping.cluster_id) != (site_id, cluster_id):
        raise AdmissionError('BUDGET_MISMATCH', 'visible device is outside the site/cluster budget')
    if mapping.station_id != state.device_id:
        raise AdmissionError('DEVICE_MISMATCH', 'visible mapping does not identify this device')
    if mapping.mapping_basis != 'synthetic_assumption':
        raise AdmissionError('INVALID_DEVICE_MAPPING', 'mapping must be an explicit assumption')
    start = utc_datetime(mapping.valid_from_utc, 'mapping.valid_from_utc')
    available = utc_datetime(mapping.available_at_utc, 'mapping.available_at_utc')
    end = (None if mapping.valid_to_utc is None
           else utc_datetime(mapping.valid_to_utc, 'mapping.valid_to_utc'))
    if start > issue or available > issue or (end is not None and (end <= start or issue >= end)):
        raise AdmissionError('INVALID_DEVICE_MAPPING', 'mapping is not effective and visible at issue')


def _validate_view(view, issue, site_id, cluster_id):
    _exact(view.sessions, tuple, 'view.sessions')
    if view.synthetic_only is not True or view.real_dispatch_authorized is not False:
        raise AdmissionError('SYNTHETIC_ONLY', 'only artificial views without live authority are allowed')
    if view.availability_mode not in _BASES:
        raise AdmissionError('UNKNOWN_AVAILABILITY', 'an explicit availability mode is required')
    sessions = {}
    devices = set()
    for item in view.sessions:
        _exact(item, MappedSession, 'mapped session')
        state = item.state
        _exact(state, SessionState, 'session state')
        sid = identifier(state.session_id, 'session_id')
        device = identifier(state.device_id, 'device_id')
        identifier(item.declaration_status, 'declaration_status')
        if sid in sessions or device in devices:
            raise AdmissionError('DUPLICATE_SESSION', 'visible session and device IDs must be unique')
        last_event = utc_datetime(state.last_event_time_utc, 'state.last_event_time_utc')
        last_available = utc_datetime(state.last_available_at_utc, 'state.last_available_at_utc')
        if not last_event <= last_available <= issue:
            raise AdmissionError('INVALID_TIME', 'visible state clocks must precede issue')
        age = number(state.state_age_seconds, 'state_age_seconds')
        if age != (issue - last_event).total_seconds():
            raise AdmissionError('INVALID_TIME', 'state age disagrees with the latest event clock')
        _exact(state.stale, bool, 'state.stale')
        _basis(state.availability_basis, view.availability_mode)
        for label in ('current_a', 'pilot_a'):
            value = getattr(state, label)
            if value is not None:
                number(value, label)
        _validate_mapping(item.mapping, state, issue, site_id, cluster_id)
        sessions[sid] = state
        devices.add(device)
    return sessions


def _validate_feedback(feedback, issue, sessions):
    _exact(feedback, EnergySnapshot, 'feedback')
    if utc_datetime(feedback.as_of_utc, 'feedback.as_of_utc') != issue:
        raise AdmissionError('UNSYNCHRONIZED_ENERGY', 'cumulative feedback must be exactly at issue')
    _exact(feedback.entries, tuple, 'feedback.entries')
    delivered = {}
    for entry in feedback.entries:
        _exact(entry, DeliveredEnergy, 'feedback entry')
        sid = identifier(entry.session_id, 'feedback.session_id')
        device = identifier(entry.device_id, 'feedback.device_id')
        if sid in delivered:
            raise AdmissionError('DUPLICATE_FEEDBACK', 'one energy entry per visible session is required')
        if sid not in sessions:
            raise AdmissionError('EXTRA_FEEDBACK', 'energy feedback includes a session outside the view')
        if device != sessions[sid].device_id:
            raise AdmissionError('DEVICE_MISMATCH', 'feedback device does not match visible session')
        delivered[sid] = number(entry.energy_kwh, 'feedback.energy_kwh')
    return delivered


def _declaration(state, issue, mode, delivered, step_seconds):
    """Return remaining energy, departure and an explicit per-session blocker.

    Revalidate declaration content; the adapter's diagnostic string cannot grant
    permission to act on a malformed or unknown request.
    """
    request = state.declaration
    if request is None:
        return None, None, 'MISSING_DECLARATION'
    try:
        _exact(request, Declaration, 'declaration')
        number(request.energy_kwh, 'declaration.energy_kwh')
        if type(request.revision) is not int or request.revision < 0:
            raise AdmissionError('INVALID_REVISION', 'nonnegative integer revision required')
        _basis(request.availability_basis, mode)
        if request.availability_basis == 'assumed_replay' and state.availability_basis != 'assumed_replay':
            raise AdmissionError('UNKNOWN_AVAILABILITY', 'declaration and state bases disagree')
        event = utc_datetime(request.event_time_utc, 'declaration.event_time_utc')
        available = utc_datetime(request.available_at_utc, 'declaration.available_at_utc')
        if (not event <= available <= issue or event > state.last_event_time_utc
                or available > state.last_available_at_utc):
            raise AdmissionError('INVALID_TIME', 'declaration was not visible at the state boundary')
        if request.delivered_at_revision_kwh is not None:
            number(request.delivered_at_revision_kwh, 'declaration.delivered_at_revision_kwh')
        if request.request_basis not in ('total', 'additional', 'unknown'):
            raise AdmissionError('INVALID_REQUEST_BASIS', 'request basis is invalid')
        departure = (None if request.departure_time_utc is None
                     else utc_datetime(request.departure_time_utc, 'declaration.departure_time_utc'))
        if departure is not None and departure <= issue:
            return None, None, 'EXPIRED_DEPARTURE'
        if request.request_basis == 'unknown':
            return None, None, 'UNKNOWN_REQUEST_BASIS'
        if request.request_basis == 'additional' and request.delivered_at_revision_kwh is None:
            return None, None, 'UNKNOWN_REQUEST_BASELINE'
        if departure is None:
            return None, None, 'MISSING_DEPARTURE'
        if (departure - issue) % timedelta(seconds=step_seconds) != timedelta(0):
            return None, None, 'UNALIGNED_DEPARTURE'
        remaining = remaining_energy_kwh(
            request.energy_kwh, delivered, request_basis=request.request_basis,
            delivered_at_revision=request.delivered_at_revision_kwh,
        )
        return remaining, departure, None
    except AdmissionError:
        return None, None, 'INVALID_DECLARATION'


def dispatch_edf(view, feedback, *, site_id, cluster_id, device_limits_kw,
                 capacity_kw, step_seconds=900) -> DispatchDecision:
    """Allocate one explicit site/cluster budget by declared departure then ID.

    Input-contract violations reject the entire call. Unknown per-session
    feedback, limits or declarations are blocked individually. Remaining energy
    is reported before this decision's actions and only for eligible sessions.
    Blocked, remaining and stale diagnostics are sorted by session ID. Feedback
    metadata is checked for consistency; it cannot establish physical provenance.
    """
    _exact(view, ControllerInput, 'view')
    issue = utc_datetime(view.issue_time_utc, 'view.issue_time_utc')
    end = step_end(issue, step_seconds)
    site_id = identifier(site_id, 'site_id')
    cluster_id = identifier(cluster_id, 'cluster_id')
    budget = Fraction.from_float(number(capacity_kw, 'capacity_kw'))
    _exact(device_limits_kw, dict, 'device_limits_kw')
    limits = {identifier(key, 'device limit ID'): number(value, 'device limit kW')
              for key, value in device_limits_kw.items()}
    sessions = _validate_view(view, issue, site_id, cluster_id)
    delivered = _validate_feedback(feedback, issue, sessions)
    blocked = []
    remaining_values = []
    eligible = []
    for sid, state in sorted(sessions.items()):
        if sid not in delivered:
            blocked.append((sid, 'UNKNOWN_DELIVERED_ENERGY'))
            continue
        if state.device_id not in limits:
            blocked.append((sid, 'UNKNOWN_DEVICE_LIMIT'))
            continue
        remaining, departure, reason = _declaration(
            state, issue, view.availability_mode, delivered[sid], step_seconds,
        )
        if reason is not None:
            blocked.append((sid, reason))
            continue
        remaining_values.append((sid, remaining))
        eligible.append((departure, sid, state.device_id, remaining))
    actions = []
    hours = step_seconds / 3600.0
    for _, sid, device, remaining in sorted(eligible):
        # Keep the exact sum of the binary floats within the capacity. Repeated
        # float subtraction can invent headroom (e.g. six 0.1 kW actions at
        # 0.6 kW). Round headroom downward with at most one adjacent-float step.
        available = float(budget)
        if Fraction.from_float(available) > budget:
            available = nextafter(available, 0.0)
        # A huge finite request may yield infinite requested power. The two
        # finite power limits still bound the action; no infinity is returned.
        power = min(limits[device], remaining / hours, available)
        if power > 0:
            actions.append(ChargeAction(sid, device, issue, end, power))
            budget -= Fraction.from_float(power)
    return DispatchDecision(issue, tuple(actions), tuple(blocked), tuple(remaining_values),
                            tuple(sid for sid, state in sorted(sessions.items()) if state.stale))
