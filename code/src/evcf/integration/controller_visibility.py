"""Build an immutable, issue-time view from declared synthetic event metadata.

This module does not establish that supplied reception metadata is truthful.
It has no data access, evaluator outcomes, physical-power admission or I/O.
"""
from dataclasses import dataclass
from datetime import datetime

from .controller_common import AdmissionError, exact_keys, identifier, number, utc

_EVENT_KEYS = (
    'event_id', 'session_id', 'device_id', 'kind', 'event_time_utc',
    'available_at_utc', 'availability_basis', 'evidence_id', 'revision', 'payload',
)
_BASES = ('recorded_reception', 'assumed_replay')
_KIND_ORDER = {'connect': 0, 'request': 1, 'current': 2, 'pilot': 3, 'disconnect': 4}


@dataclass(frozen=True)
class Declaration:
    energy_kwh: float
    request_basis: str
    departure_time_utc: datetime | None
    delivered_at_revision_kwh: float | None
    revision: int
    event_time_utc: datetime
    available_at_utc: datetime
    availability_basis: str


@dataclass(frozen=True)
class SessionState:
    session_id: str
    device_id: str
    current_a: float | None
    pilot_a: float | None
    declaration: Declaration | None
    last_event_time_utc: datetime
    last_available_at_utc: datetime
    state_age_seconds: float
    stale: bool
    availability_basis: str


@dataclass(frozen=True)
class VisibleSnapshot:
    issue_time_utc: datetime
    availability_mode: str
    sessions: tuple[SessionState, ...]


@dataclass(frozen=True)
class _Event:
    event_id: str
    session_id: str
    device_id: str
    kind: str
    event_time: datetime
    available_at: datetime
    availability_basis: str
    evidence_id: str
    revision: int
    payload: tuple


@dataclass
class _Session:
    device_id: str
    last_event: datetime
    last_available: datetime
    connected: bool = False
    closed: bool = False
    current: float | None = None
    pilot: float | None = None
    declaration: Declaration | None = None
    basis: str = 'recorded_reception'


def _payload(kind, payload):
    """Copy only admitted scalar values; never keep a mutable input reference."""
    if kind in ('connect', 'disconnect'):
        exact_keys(payload, (), f'{kind}.payload')
        return ()
    if kind in ('current', 'pilot'):
        exact_keys(payload, ('value', 'unit'), f'{kind}.payload')
        if payload['unit'] != 'A':
            raise AdmissionError('INVALID_UNIT', 'current and pilot require explicit A units')
        return (number(payload['value'], f'{kind}.value'),)
    exact_keys(payload, ('energy_kwh', 'request_basis', 'departure_time_utc',
                         'delivered_at_revision_kwh'), 'request.payload')
    basis = payload['request_basis']
    if basis not in ('total', 'additional', 'unknown'):
        raise AdmissionError('INVALID_REQUEST_BASIS', 'request basis must be explicit')
    departure = payload['departure_time_utc']
    delivered = payload['delivered_at_revision_kwh']
    return (number(payload['energy_kwh'], 'request.energy_kwh'), basis,
            None if departure is None else utc(departure, 'request.departure_time_utc'),
            None if delivered is None else number(delivered, 'request.delivered_at_revision_kwh'))


def _eligible_event(raw, issue, availability_mode):
    # Only clocks are inspected until eligibility is established. A future row
    # cannot disclose values, identities, validation errors or diagnostic counts.
    if not isinstance(raw, dict):
        raise AdmissionError('INVALID_SCHEMA', 'each event must be a dictionary')
    event_time = utc(raw.get('event_time_utc'), 'event.event_time_utc')
    if event_time > issue:
        return None
    available_raw = raw.get('available_at_utc')
    if available_raw is None or available_raw == 'unknown':
        raise AdmissionError('UNKNOWN_AVAILABILITY', 'past event has no known reception time')
    available_at = utc(available_raw, 'event.available_at_utc')
    if available_at < event_time:
        raise AdmissionError('INVALID_TIME', 'reception cannot precede event time')
    if available_at > issue:
        return None

    exact_keys(raw, _EVENT_KEYS, 'event')
    basis = raw['availability_basis']
    if basis not in _BASES or (availability_mode == 'recorded_reception'
                              and basis != 'recorded_reception'):
        raise AdmissionError('UNKNOWN_AVAILABILITY',
                             'event availability evidence is not admitted in this mode')
    kind = raw['kind']
    if not isinstance(kind, str) or kind not in _KIND_ORDER:
        raise AdmissionError('INVALID_SCHEMA', 'unsupported event kind')
    revision = raw['revision']
    if type(revision) is not int or revision < 0:
        raise AdmissionError('INVALID_REVISION', 'revision must be a nonnegative integer')
    return _Event(
        identifier(raw['event_id'], 'event_id'),
        identifier(raw['session_id'], 'session_id'),
        identifier(raw['device_id'], 'device_id'), kind, event_time, available_at,
        basis, identifier(raw['evidence_id'], 'evidence_id'), revision,
        _payload(kind, raw['payload']),
    )


def _admitted_events(events, issue, availability_mode):
    identities = {}
    revisions = {}
    for raw in events:
        event = _eligible_event(raw, issue, availability_mode)
        if event is None:
            continue
        previous = identities.get(event.event_id)
        if previous is not None:
            if previous != event:
                raise AdmissionError('CONFLICTING_REVISION', 'event ID has conflicting content')
            continue
        key = (event.session_id, event.device_id, event.kind, event.event_time, event.revision)
        if key in revisions and revisions[key] != event.payload:
            raise AdmissionError('CONFLICTING_REVISION', 'event revision has conflicting payload')
        identities[event.event_id] = event
        revisions[key] = event.payload
    # At equal time/revision, a received connection opens before observations;
    # a received disconnection closes after them. Event IDs only break exact ties.
    return sorted(identities.values(), key=lambda e: (
        e.event_time, e.revision, _KIND_ORDER[e.kind], e.event_id))


def build_visible_snapshot(events: list[dict], issue_time_utc: str,
                           availability_mode: str = 'recorded_reception',
                           stale_after_seconds: float = 900) -> VisibleSnapshot:
    """Select received events and reconstruct the currently connected sessions.

    Requests can precede connection. Current and pilot require a visible active
    connection at their event time. Age measures time since the latest eligible
    event, not its receipt; receipt lag is preserved separately. Age strictly
    greater than ``stale_after_seconds`` is stale. No absent disconnection is
    inferred. The replay mode always stays labeled ``assumed_replay``.

    A received disconnect permanently closes that session identity; a later
    physical connection needs a new session ID. Repeated connect notifications
    while the session is still open preserve its observations. A device may
    belong to at most one connected session at any point in the visible history.
    """
    issue = utc(issue_time_utc, 'issue_time_utc')
    if not isinstance(events, list):
        raise AdmissionError('INVALID_SCHEMA', 'events must be an explicit list')
    if availability_mode not in _BASES:
        raise AdmissionError('UNKNOWN_AVAILABILITY', 'availability mode must be explicit')
    stale_after = number(stale_after_seconds, 'stale_after_seconds')
    sessions = {}
    connected_devices = {}
    for event in _admitted_events(events, issue, availability_mode):
        state = sessions.get(event.session_id)
        if state is None:
            state = _Session(event.device_id, event.event_time, event.available_at)
            sessions[event.session_id] = state
        if state.device_id != event.device_id:
            raise AdmissionError('INVALID_EVENT_SEQUENCE', 'session device binding changed')
        if event.kind == 'connect':
            if state.closed:
                raise AdmissionError('INVALID_EVENT_SEQUENCE',
                                     'a closed session ID cannot be reconnected')
            owner = connected_devices.get(event.device_id)
            if owner is not None and owner != event.session_id:
                raise AdmissionError('INVALID_EVENT_SEQUENCE',
                                     'device already belongs to a connected session')
            state.connected = True
            connected_devices[event.device_id] = event.session_id
        elif event.kind == 'disconnect':
            state.connected = False
            state.closed = True
            if connected_devices.get(event.device_id) == event.session_id:
                del connected_devices[event.device_id]
        elif event.kind in ('current', 'pilot'):
            if not state.connected:
                raise AdmissionError('INVALID_EVENT_SEQUENCE',
                                     'telemetry is outside a visible connected session')
            if event.kind == 'current':
                state.current = event.payload[0]
            else:
                state.pilot = event.payload[0]
        else:
            state.declaration = Declaration(
                *event.payload, event.revision, event.event_time,
                event.available_at, event.availability_basis)
        state.last_event = max(state.last_event, event.event_time)
        state.last_available = max(state.last_available, event.available_at)
        if event.availability_basis == 'assumed_replay':
            state.basis = 'assumed_replay'

    visible = []
    for session_id, state in sorted(sessions.items()):
        if state.connected:
            age = (issue - state.last_event).total_seconds()
            visible.append(SessionState(
                session_id, state.device_id, state.current, state.pilot, state.declaration,
                state.last_event, state.last_available, age, age > stale_after, state.basis))
    return VisibleSnapshot(issue, availability_mode, tuple(visible))
