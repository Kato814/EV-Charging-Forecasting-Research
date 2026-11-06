"""Artificial feedback loop and hand-checkable cases; never a scientific protocol."""
import copy
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .charging_plant import Evaluation, StepResult, SyntheticPlant, TruthSession
from .charging_policy import DispatchDecision, dispatch_edf
from .charging_types import ChargeAction, step_end
from .controller_adapter import build_synthetic_controller_view
from .controller_common import AdmissionError, utc


@dataclass(frozen=True)
class LoopResult:
    decisions: tuple[DispatchDecision, ...]
    executions: tuple[StepResult, ...]
    evaluation: Evaluation


def run_loop(envelope, plant, *, site_id, cluster_id, device_limits_kw,
             capacity_kw, steps, step_seconds=900):
    """Only realized feedback reaches policy; evaluation happens after execution."""
    if type(steps) is not int or steps <= 0 or not isinstance(envelope, dict):
        raise AdmissionError('INVALID_LOOP_CONFIG', 'Positive integer steps and envelope required')
    if type(plant) is not SyntheticPlant:
        raise AdmissionError('SYNTHETIC_ONLY', 'Only the artificial execution environment is allowed')
    issue = utc(envelope.get('issue_time_utc'), 'issue_time_utc')
    step_end(issue, step_seconds)
    step_end(issue, steps * step_seconds)  # Check the requested time range before mutation.
    template = copy.deepcopy(envelope)
    decisions, executions = [], []
    for _ in range(steps):
        template['issue_time_utc'] = issue.isoformat()
        view = build_synthetic_controller_view(template)
        feedback = plant.feedback(tuple(s.state.session_id for s in view.sessions),
                                  issue_time_utc=issue)
        decision = dispatch_edf(view, feedback, site_id=site_id, cluster_id=cluster_id,
                                device_limits_kw=device_limits_kw, capacity_kw=capacity_kw,
                                step_seconds=step_seconds)
        execution = plant.execute(decision.actions, issue_time_utc=issue, step_seconds=step_seconds)
        decisions.append(decision)
        executions.append(execution)
        issue = execution.end_utc
    return LoopResult(tuple(decisions), tuple(executions), plant.evaluate())


def _time(minutes):
    return datetime(2026, 11, 6, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _event(session, kind, minute, payload, *, received=None, revision=0):
    return {'event_id': f'SYN-{session}-{kind}-{minute}-{revision}', 'session_id': session,
            'device_id': 'SYN-D-' + session, 'kind': kind,
            'event_time_utc': _time(minute).isoformat(),
            'available_at_utc': _time(minute if received is None else received).isoformat(),
            'availability_basis': 'assumed_replay', 'evidence_id': 'hand-authored-event',
            'revision': revision, 'payload': payload}


def _request(goal, departure, basis='total', baseline=None):
    return {'energy_kwh': goal, 'request_basis': basis,
            'departure_time_utc': _time(departure).isoformat(),
            'delivered_at_revision_kwh': baseline}


def _fixture(specs, capacity, steps, notices=None):
    """Fixed artificial scenarios, not a dataset importer or real-data schema."""
    events, keys, mappings, truth, limits = [], {}, [], [], {}
    for sid, limit, declaration, departure, actual_departure, goal in specs:
        device = 'SYN-D-' + sid
        identity = {'site_id': 'SYN-SITE', 'cluster_id': 'SYN-GROUP',
                    'station_id': device, 'space_id': 'SYN-SPACE-' + sid}
        keys[device] = identity
        mappings.append({**identity, 'topology_label': 'SYN-TOPOLOGY', 'node_id': 'SYN-NODE-' + sid,
                         'valid_from_utc': _time(0).isoformat(), 'valid_to_utc': None,
                         'available_at_utc': _time(0).isoformat(),
                         'evidence_id': 'hand-authored-map', 'mapping_basis': 'synthetic_assumption'})
        events.extend((_event(sid, 'connect', 0, {}),
                       _event(sid, 'request', 0, _request(declaration, departure)),
                       _event(sid, 'disconnect', actual_departure, {},
                              received=(notices or {}).get(sid, actual_departure))))
        truth.append(TruthSession(sid, device, _time(0), _time(actual_departure), goal, limit))
        limits[device] = limit
    envelope = {'schema_version': 'synthetic-controller/v1', 'data_origin': 'hand_authored',
                'issue_time_utc': _time(0).isoformat(), 'availability_mode': 'assumed_replay',
                'stale_after_seconds': 900, 'events': events,
                'device_keys': keys, 'device_mappings': mappings}
    plant = SyntheticPlant(tuple(truth), start_utc=_time(0), capacity_kw=capacity)
    options = {'site_id': 'SYN-SITE', 'cluster_id': 'SYN-GROUP', 'device_limits_kw': limits,
               'capacity_kw': capacity, 'steps': steps}
    return envelope, plant, options


def _run(specs, capacity, steps, notices=None):
    envelope, plant, options = _fixture(specs, capacity, steps, notices)
    return run_loop(envelope, plant, **options)


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _reject(operation):
    try:
        operation()
    except AdmissionError as exc:
        return exc.code
    raise AssertionError('Invalid operation was accepted')


def _l01():
    result = _run([('A',4,0.5,15,15,0.5), ('B',4,1.5,30,30,1.5)], 4, 2)
    powers = [[a.power_kw for a in d.actions] for d in result.decisions]
    _require(powers == [[2,2],[4]] and result.evaluation.complete
             and result.evaluation.delivered_kwh == 2 and result.evaluation.shortfall_kwh == 0,
             'Feasible hand calculation did not match execution')
    return {'powers_kw': powers, 'delivered_kwh': result.evaluation.delivered_kwh,
            'shortfall_kwh': result.evaluation.shortfall_kwh}


def _l02():
    result = _run([('A',4,2,30,30,2), ('B',4,2,30,30,2)], 4, 2)
    _require(result.evaluation.complete and result.evaluation.delivered_kwh == 2
             and result.evaluation.shortfall_kwh == 2, 'Capacity deficit was hidden')
    return {'delivered_kwh': result.evaluation.delivered_kwh,
            'shortfall_kwh': result.evaluation.shortfall_kwh, 'general_infeasibility_proved': False}


def _l03():
    specs = [('A',8,2,30,30,2), ('B',4,3,45,45,3)]
    result = _run(specs, 8, 3)
    _, witness, _ = _fixture(specs, 8, 3)
    for index, allocation in enumerate(((('A',4),('B',4)), (('A',4),('B',4)), (('B',4),))):
        start, end = _time(15 * index), _time(15 * (index + 1))
        actions = tuple(ChargeAction(sid, 'SYN-D-' + sid, start, end, power)
                        for sid, power in allocation)
        witness.execute(actions, issue_time_utc=start)
    evaluated = witness.evaluate()
    _require(result.evaluation.complete and result.evaluation.shortfall_kwh == 1
             and evaluated.complete and evaluated.shortfall_kwh == 0
             and evaluated.delivered_kwh == 5, 'Counterexample did not establish rule limitation')
    return {'edf_shortfall_kwh': result.evaluation.shortfall_kwh,
            'witness_shortfall_kwh': evaluated.shortfall_kwh,
            'witness_delivered_kwh': evaluated.delivered_kwh, 'optimizer_used': False}


def _l04():
    result = _run([('A',6,3,45,10,3)], 6, 3, {'A':30})
    commands = [s.commanded_kw for s in result.executions]
    energy = [s.delivered_kwh for s in result.executions]
    _require(commands == [6,6,0] and energy == [1,0,0]
             and result.evaluation.shortfall_kwh == 2, 'Late notice or partial energy was mishandled')
    return {'commanded_kw': commands, 'delivered_per_step_kwh': energy,
            'shortfall_kwh': result.evaluation.shortfall_kwh}


def _l05():
    envelope, plant, options = _fixture([('A',4,1,15,15,1)], 4, 1)
    envelope['events'][1]['payload']['request_basis'] = 'unknown'
    result = run_loop(envelope, plant, **options)
    _require(not result.decisions[0].actions and bool(result.decisions[0].blocked)
             and result.evaluation.delivered_kwh == 0 and result.evaluation.shortfall_kwh == 1,
             'Unknown declaration was treated as a dispatchable demand')
    return {'blocked': result.decisions[0].blocked, 'delivered_kwh': result.evaluation.delivered_kwh,
            'shortfall_kwh': result.evaluation.shortfall_kwh}


def _l06():
    baseline = _run([('A',4,4,60,60,4)], 4, 4)
    changed_goal = _run([('A',4,4,60,60,2)], 4, 4)
    changed_departure = _run([('A',4,4,60,45,4)], 4, 4)
    actions_equal = baseline.decisions == changed_goal.decisions
    delivery_equal = baseline.executions == changed_goal.executions
    prefix_equal = baseline.decisions[:3] == changed_departure.decisions[:3]
    _require(actions_equal and delivery_equal and prefix_equal
             and changed_goal.evaluation.overdelivery_kwh == 2,
             'Hidden truth leaked into actions or clipped environment delivery')
    return {'target_change_actions_equal': actions_equal, 'target_change_delivery_equal': delivery_equal,
            'changed_target_overdelivery_kwh': changed_goal.evaluation.overdelivery_kwh,
            'future_departure_prefix_equal': prefix_equal,
            'later_feedback_may_differ': True}


def _l07():
    _, plant, _ = _fixture([('A',4,1,15,15,1)], 4, 1)
    before = plant.feedback(('A',), issue_time_utc=_time(0))
    code = _reject(lambda: plant.execute((ChargeAction('A','SYN-D-A',_time(0),_time(15),5),),
                                        issue_time_utc=_time(0)))
    _require(before == plant.feedback(('A',), issue_time_utc=_time(0)), 'Rejection mutated state')
    good = (ChargeAction('A','SYN-D-A',_time(0),_time(15),4),)
    step = plant.execute(good, issue_time_utc=_time(0))
    repeat = _reject(lambda: plant.execute(good, issue_time_utc=_time(0)))
    _require(step.delivered_kwh == 1 and plant.evaluate().delivered_kwh == 1,
             'Rejected batch or repeated interval altered accounting')
    return {'invalid_action_rejected': code, 'repeat_rejected': repeat,
            'state_preserved_on_rejection': True, 'valid_delivered_kwh': step.delivered_kwh}


def _l08():
    envelope, plant, options = _fixture([('A',8,2,60,60,7)], 8, 4)
    envelope['events'].append(_event('A','request',15,_request(5,60,'additional',2),revision=1))
    result = run_loop(envelope, plant, **options)
    commands = [s.commanded_kw for s in result.executions]
    _require(commands == [8,8,8,4] and result.evaluation.delivered_kwh == 7
             and result.evaluation.shortfall_kwh == 0, 'Additional revision double-counted energy')
    return {'commanded_kw': commands, 'delivered_kwh': result.evaluation.delivered_kwh,
            'shortfall_kwh': result.evaluation.shortfall_kwh}


CASES = tuple((f'L{i:02}', case) for i, case in enumerate(
    (_l01, _l02, _l03, _l04, _l05, _l06, _l07, _l08), 1))


def run_acceptance(progress=None):
    results = []
    for case_id, operation in CASES:
        if progress is not None:
            progress(case_id)
        try:
            observed = operation()
            json.dumps(observed, allow_nan=False)
            row = {'case_id': case_id, 'status': 'PASS', 'observed': observed}
        except Exception as exc:  # noqa: BLE001 -- preserve each failure and continue the other cases
            row = {'case_id': case_id, 'status': 'FAIL',
                   'error': {'type': type(exc).__name__, 'message': str(exc)}}
        results.append(row)
    return results
