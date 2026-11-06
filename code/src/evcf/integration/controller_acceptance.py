"""Executed artificial C01-C15 checks; never read a dataset or model."""
import copy
import json
from datetime import datetime, timedelta, timezone

from .controller_adapter import build_synthetic_controller_view
from .controller_common import AdmissionError
from .controller_quantities import (
    current_to_power_proxy,
    energy_increment,
    interval_current_means,
    remaining_energy_kwh,
    require_same_power_boundary,
    validate_interval_support,
)


def _time(minutes):
    return (datetime(2026, 11, 6, tzinfo=timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _event(kind, minute=0, *, received=None, revision=0, payload=None, name=None):
    return {
        'event_id': name or f'{kind}-{minute}-{revision}',
        'session_id': 'SYN-SESSION', 'device_id': 'SYN-DEVICE', 'kind': kind,
        'event_time_utc': _time(minute),
        'available_at_utc': _time(minute if received is None else received),
        'availability_basis': 'recorded_reception', 'evidence_id': 'hand-authored-receipt',
        'revision': revision, 'payload': {} if payload is None else payload,
    }


def _envelope():
    identity = {'site_id': 'SYN-SITE', 'cluster_id': 'SYN-CLUSTER',
                'station_id': 'SYN-DEVICE', 'space_id': 'SYN-SPACE'}
    return {
        'schema_version': 'synthetic-controller/v1', 'data_origin': 'hand_authored',
        'issue_time_utc': _time(15), 'availability_mode': 'recorded_reception',
        'stale_after_seconds': 900,
        'events': [_event('connect'), _event('current', 5, payload={'value': 3, 'unit': 'A'})],
        'device_keys': {'SYN-DEVICE': identity},
        'device_mappings': [{**identity, 'topology_label': 'SYN-TOPOLOGY', 'node_id': 'SYN-NODE',
                             'valid_from_utc': _time(0), 'valid_to_utc': None,
                             'available_at_utc': _time(0), 'evidence_id': 'hand-authored-map',
                             'mapping_basis': 'synthetic_assumption'}],
    }


def _require(condition, message):
    # Explicit checks remain active under python -O.
    if not condition:
        raise AssertionError(message)


def _reject(operation, code):
    try:
        operation()
    except AdmissionError as exc:
        _require(exc.code == code, f'Expected {code}, got {exc.code}')
        return exc.code
    raise AssertionError(f'Expected rejection {code}')


def _assumptions():
    return {'voltage_v': 208, 'power_factor': 1, 'pf_basis': 'explicit_assumption',
            'connection': 'single_phase_line_to_line', 'evidence_id': 'hand-authored-power'}


def _proxy(assumptions, profile='assumed_power_simulation', requested_basis='assumed_proxy'):
    return current_to_power_proxy(4, profile=profile, requested_basis=requested_basis,
                                  assumptions=assumptions)


def _c01():
    value = _envelope()
    value['events'].append(_event('current', 10, received=20, payload={'value': 9, 'unit': 'A'}))
    before = build_synthetic_controller_view(value).sessions[0].state.current_a
    value['issue_time_utc'] = _time(25)
    after = build_synthetic_controller_view(value).sessions[0].state.current_a
    _require((before, after) == (3, 9), 'Late sample was not gated by actual availability')
    return {'before_receipt_a': before, 'after_receipt_a': after}


def _c02():
    value = _envelope()
    value['events'][1]['available_at_utc'] = None
    code = _reject(lambda: build_synthetic_controller_view(value), 'UNKNOWN_AVAILABILITY')
    value = _envelope()
    value['availability_mode'] = 'assumed_replay'
    for event in value['events']:
        event['availability_basis'] = 'assumed_replay'
    result = build_synthetic_controller_view(value)
    _require(result.availability_mode == 'assumed_replay'
             and result.sessions[0].state.availability_basis == 'assumed_replay',
             'Replay assumption was upgraded to recorded reception')
    return {'unknown_rejected': code, 'replay_basis': result.availability_mode}


def _c03():
    value = _envelope()
    request = {'energy_kwh': 10, 'request_basis': 'total', 'departure_time_utc': _time(120),
               'delivered_at_revision_kwh': None}
    value['events'] += [_event('request', 8, revision=0, payload=request),
                        _event('request', 8, revision=1, payload={**request, 'energy_kwh': 12})]
    first = build_synthetic_controller_view(value)
    value['events'].reverse()
    _require(first == build_synthetic_controller_view(value), 'Revision depended on list order')
    _require(first.sessions[0].state.declaration.energy_kwh == 12, 'Latest revision not selected')
    value['events'].append(_event('request', 8, revision=1, name='conflict',
                                  payload={**request, 'energy_kwh': 99}))
    code = _reject(lambda: build_synthetic_controller_view(value), 'CONFLICTING_REVISION')
    return {'selected_request_kwh': 12, 'conflict_rejected': code, 'permutation_invariant': True}


def _c04():
    value = _envelope()
    value['events'] = [_event('connect'), _event('current', payload={'value': 3, 'unit': 'A'}),
                       _event('disconnect', 10, received=25)]
    value['issue_time_utc'] = _time(20)
    before = build_synthetic_controller_view(value)
    _require(len(before.sessions) == 1 and before.sessions[0].state.stale,
             'Unreceived disconnect changed visible connection state')
    value['issue_time_utc'] = _time(30)
    after = build_synthetic_controller_view(value)
    _require(not after.sessions, 'Received disconnect did not close the session')
    return {'connected_before_receipt': 1, 'connected_after_receipt': 0,
            'visible_event_age_seconds': before.sessions[0].state.state_age_seconds}


def _c05():
    value = _envelope()
    value['events'].append(_event('pilot', 4, payload={'value': 8, 'unit': 'A'}))
    state = build_synthetic_controller_view(value).sessions[0].state
    _require(state.current_a == 3 and state.pilot_a == 8, 'Pilot minimum corrupted measured current')
    return {'current_a': state.current_a, 'pilot_a': state.pilot_a}


def _c06():
    full = [{'start_utc': _time(15 + 15*i), 'end_utc': _time(30 + 15*i)} for i in range(16)]
    sparse = [full[i] for i in (0, 1, 3, 7, 15)]
    code = _reject(lambda: validate_interval_support(sparse, _time(15)),
                   'INSUFFICIENT_FORECAST_SUPPORT')
    accepted = validate_interval_support(full, _time(15))
    _require(len(accepted) == 16, 'Dense interval support rejected')
    return {'sparse_rejected': code, 'dense_intervals': len(accepted),
            'probabilistic_forecast_validated': False}


def _c07():
    world = {'controller': _envelope(), 'evaluator_truth': {'final_kwh': 50, 'departure': _time(60)}}
    future = _event('current', 30, payload={'value': 9, 'unit': 'A'})
    world['controller']['events'].append(future)
    before = build_synthetic_controller_view(world['controller'])
    world['evaluator_truth'] = {'final_kwh': 9000, 'departure': _time(600), 'done': _time(500)}
    future['payload'] = {'actual_departure': _time(600), 'final_kwh': 9000}
    after = build_synthetic_controller_view(world['controller'])
    _require(before == after, 'Future values affected controller-visible output')
    future_mapping = copy.deepcopy(world['controller']['device_mappings'][0])
    future_mapping.update(available_at_utc=_time(30), node_id='', future_truth=999)
    world['controller']['device_mappings'].append(future_mapping)
    _require(before == build_synthetic_controller_view(world['controller']),
             'Unavailable mapping content affected controller-visible output')
    bad = copy.deepcopy(world['controller'])
    bad['evaluation_truth'] = world['evaluator_truth']
    code = _reject(lambda: build_synthetic_controller_view(bad), 'INVALID_SCHEMA')
    return {'future_mutation_invariant': True, 'future_mapping_invariant': True,
            'whole_truth_container_rejected': code}


def _c08():
    wrong_pf = {**_assumptions(), 'pf_basis': 'topology_phase_angle', 'power_factor': 0.866}
    extra_multiplier = {**_assumptions(), 'line_multiplier': 3**0.5}
    first = _reject(lambda: _proxy(wrong_pf), 'INVALID_POWER_ASSUMPTION')
    second = _reject(lambda: _proxy(extra_multiplier), 'INVALID_POWER_ASSUMPTION')
    return {'phase_angle_pf_rejected': first, 'extra_line_multiplier_rejected': second}


def _c09():
    value = _envelope()
    value['device_keys']['SYN-DEVICE']['space_id'] = 'SYN-DEVICE'
    value['device_mappings'] = []
    code = _reject(lambda: build_synthetic_controller_view(value), 'UNKNOWN_DEVICE_MAPPING')
    return {'equal_strings_not_a_mapping': code}


def _c10():
    partial = interval_current_means(900, 300, 900)
    complete = interval_current_means(900, 900, 900)
    _require((partial.fixed_window_mean_a, partial.covered_time_mean_a) == (1, 3)
             and (complete.fixed_window_mean_a, complete.covered_time_mean_a) == (1, 1)
             and not partial.complete and complete.complete, 'Coverage denominators conflated')
    return {'partial_fixed_mean_a': partial.fixed_window_mean_a,
            'partial_covered_mean_a': partial.covered_time_mean_a,
            'complete_fixed_mean_a': complete.fixed_window_mean_a,
            'partial_coverage': partial.coverage}


def _c11():
    reset = _reject(lambda: energy_increment(5, 1, previous_epoch='A', current_epoch='A'),
                    'ENERGY_COUNTER_RESET')
    boundary = _reject(lambda: energy_increment(5, 6, previous_epoch='A', current_epoch='B'),
                       'ENERGY_COUNTER_BOUNDARY')
    delta = energy_increment(5, 6, previous_epoch='A', current_epoch='A')
    _require(delta == 1, 'Valid energy increment incorrect')
    return {'reset_rejected': reset, 'epoch_change_rejected': boundary, 'valid_increment_kwh': delta}


def _c12():
    unknown = _reject(lambda: remaining_energy_kwh(10, 3, request_basis='unknown'),
                      'UNKNOWN_REQUEST_BASIS')
    wrong_unit = _reject(lambda: remaining_energy_kwh(10, 3, request_basis='total', unit='Ah'),
                         'UNIT_MISMATCH')
    total = remaining_energy_kwh(10, 3, request_basis='total')
    additional = remaining_energy_kwh(5, 3, request_basis='additional', delivered_at_revision=2)
    _require((total, additional) == (7, 4), 'Remaining request arithmetic incorrect')
    return {'unknown_basis_rejected': unknown, 'wrong_unit_rejected': wrong_unit,
            'total_remaining_kwh': total, 'additional_remaining_kwh': additional}


def _c13():
    archive = _reject(lambda: _proxy(_assumptions(), profile='archive_current',
                                     requested_basis='measured'), 'POWER_BASIS_MISMATCH')
    relabel = _reject(lambda: _proxy(_assumptions(), requested_basis='measured'),
                      'POWER_BASIS_MISMATCH')
    return {'archive_to_measured_rejected': archive, 'proxy_relabel_rejected': relabel}


def _c14():
    result = _proxy(_assumptions())
    _require(abs(result.value - 0.832) < 1e-12 and result.power_basis == 'assumed_proxy'
             and result.unit == 'kW', 'Nominal proxy identity or label incorrect')
    return {'power_kw': result.value, 'power_basis': result.power_basis,
            'measured_power_admitted': False}


def _c15():
    evse = {'boundary_id': 'synthetic-evse', 'components': ['ev_charging']}
    meter = {'boundary_id': 'synthetic-cluster', 'components': ['ev_charging', 'standby', 'loss']}
    code = _reject(lambda: require_same_power_boundary(evse, meter),
                   'MEASUREMENT_BOUNDARY_MISMATCH')
    require_same_power_boundary(evse, copy.deepcopy(evse))
    return {'unequal_scope_rejected': code, 'same_scope_accepted': True,
            'meter_calibration_validated': False}


CASES = tuple((f'C{i:02}', case) for i, case in enumerate(
    (_c01, _c02, _c03, _c04, _c05, _c06, _c07, _c08, _c09, _c10, _c11, _c12, _c13, _c14, _c15), 1))


def run_acceptance(progress=None):
    results = []
    for case_id, operation in CASES:
        if progress is not None:
            progress(case_id)
        try:
            observed = operation()
            json.dumps(observed, allow_nan=False)
            row = {'case_id': case_id, 'status': 'PASS', 'observed': observed}
        except Exception as exc:  # noqa: BLE001 -- case boundary preserves failures for nonzero exit
            row = {'case_id': case_id, 'status': 'FAIL',
                   'error': {'type': type(exc).__name__, 'message': str(exc)}}
        results.append(row)
    return results
