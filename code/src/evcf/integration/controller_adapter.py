"""Opt-in artificial controller view; no ACN data parser or live dispatch authority."""
from dataclasses import dataclass, field
from datetime import datetime

from .controller_common import AdmissionError, exact_keys
from .controller_quantities import DeviceMapping, resolve_device_mapping
from .controller_visibility import SessionState, build_visible_snapshot


@dataclass(frozen=True)
class MappedSession:
    state: SessionState
    mapping: DeviceMapping
    declaration_status: str


@dataclass(frozen=True)
class ControllerInput:
    issue_time_utc: datetime
    availability_mode: str
    sessions: tuple[MappedSession, ...]
    synthetic_only: bool = field(default=True, init=False)
    real_dispatch_authorized: bool = field(default=False, init=False)


def _declaration_status(state, issue):
    declaration = state.declaration
    if declaration is None:
        return 'MISSING_DECLARATION'
    if declaration.departure_time_utc is not None and declaration.departure_time_utc <= issue:
        return 'EXPIRED_DEPARTURE'
    if declaration.request_basis == 'unknown':
        return 'UNKNOWN_REQUEST_BASIS'
    if declaration.request_basis == 'additional' and declaration.delivered_at_revision_kwh is None:
        return 'UNKNOWN_REQUEST_BASELINE'
    if declaration.departure_time_utc is None:
        return 'MISSING_DEPARTURE'
    return 'DECLARED_ONLY'  # No service feasibility or delivered-energy proof is implied.


def build_synthetic_controller_view(payload) -> ControllerInput:
    """Filter declared events and resolve explicit identities; never accept evaluator truth.

    The hand_authored marker and evidence labels are caller declarations, not proof
    of provenance. Real data acquisition, calibration and control are outside this API.
    """
    exact_keys(payload, ('schema_version', 'data_origin', 'issue_time_utc',
                         'availability_mode', 'stale_after_seconds', 'events',
                         'device_keys', 'device_mappings'), 'controller envelope')
    if (payload['schema_version'] != 'synthetic-controller/v1'
            or payload['data_origin'] != 'hand_authored'):
        raise AdmissionError('SYNTHETIC_ONLY', 'Only the hand-authored synthetic schema is accepted')
    if not isinstance(payload['device_keys'], dict):
        raise AdmissionError('UNKNOWN_DEVICE_MAPPING', 'Explicit device keys are required')
    snapshot = build_visible_snapshot(
        payload['events'], payload['issue_time_utc'],
        availability_mode=payload['availability_mode'],
        stale_after_seconds=payload['stale_after_seconds'],
    )
    mapped = []
    for state in snapshot.sessions:
        identity = payload['device_keys'].get(state.device_id)
        if identity is None:
            raise AdmissionError('UNKNOWN_DEVICE_MAPPING', 'No identity for a visible device')
        exact_keys(identity, ('site_id', 'cluster_id', 'station_id', 'space_id'), 'device identity')
        if identity['station_id'] != state.device_id:
            raise AdmissionError('UNKNOWN_DEVICE_MAPPING', 'Physical device key does not match event')
        mapping = resolve_device_mapping(payload['device_mappings'], **identity,
                                         issue_time_utc=payload['issue_time_utc'])
        mapped.append(MappedSession(state, mapping, _declaration_status(state, snapshot.issue_time_utc)))
    return ControllerInput(snapshot.issue_time_utc, snapshot.availability_mode, tuple(mapped))
