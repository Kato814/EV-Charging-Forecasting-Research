"""Compare three rolling policies on matched hand-authored charging fixtures."""
import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from check_charging_optimizer import (
    CASES,
    ROOT,
    TOL_KWH,
    _energy,
    _fresh_fixture,
    _paired,
    _solver_info,
)


def _joint_case(need, actual_departure, notice):
    # The slow car B must use all three intervals to receive 3 kWh.
    return ([('A', 8, need, 45, actual_departure, need), ('B', 4, 3, 45, 45, 3)],
            8, 3, {'A': notice})


FIXTURES = {key: CASES[key]['base'] for key in ('L02', 'L03', 'L04')}
FIXTURES['joint_on_time'] = _joint_case(2, 45, 45)
FIXTURES.update({f'joint_early_{need}kwh': _joint_case(need, 10, 30) for need in (1, 2, 3)})


def _first_input_digest(case_id, spec):
    from evcf.integration.controller_adapter import build_synthetic_controller_view

    envelope, plant, options, _ = _fresh_fixture(case_id, spec)
    view = build_synthetic_controller_view(envelope)
    ids = tuple(s.state.session_id for s in view.sessions)
    feedback = plant.feedback(ids, issue_time_utc=view.issue_time_utc)
    options.pop('steps')  # The loop length is not passed to the policy.
    options.setdefault('step_seconds', 900)
    visible = {'view': asdict(view), 'feedback': asdict(feedback), 'options': options}
    encoded = json.dumps(visible, sort_keys=True, separators=(',', ':'), allow_nan=False,
                         default=datetime.isoformat).encode()
    return hashlib.sha256(encoded).hexdigest()


def _check(row):
    case = row['case_id']
    runs = row['policies']
    for name, actual in runs.items():
        if not actual['evaluation_complete']:
            raise ValueError(f'{name} ended before departure')
        _energy(actual['delivered_kwh'], sum(s['delivered_kwh'] for s in actual['steps']),
                'executed energy')
        _energy(actual['overdelivery_kwh'], 0, 'overdelivery')
    early = runs['early']
    if case == 'L02':
        _energy(early['shortfall_kwh'], 2, 'physical capacity shortage')
        if early != runs['lp']:
            raise ValueError('Early policy diverged from the primary policy in this shortage')
    elif case in ('L03', 'joint_on_time'):
        for name in ('lp', 'early'):
            _energy(runs[name]['shortfall_kwh'], 0, name + ' feasible shortfall')
            _energy(runs[name]['delivered_kwh'], 5, name + ' feasible delivery')
    elif case == 'L04':
        _energy(early['steps'][0]['executed_kwh']['A'], 6 * 10 / 60, 'first ten minutes')
        _energy(early['shortfall_kwh'], 2, 'early departure shortfall')
    elif case.startswith('joint_early_'):
        sessions = {s['session_id']: s for s in early['sessions']}
        _energy(sessions['A']['delivered_kwh'], 4 * 10 / 60, 'ten-minute fast car')
        _energy(sessions['B']['delivered_kwh'], 3, 'slow car')
        for step in early['steps']:
            _energy(step['executed_kwh']['B'], 1, 'slow car each interval')


def _check_counterfactual(on_time, early):
    if on_time['first_policy_input_sha256'] != early['first_policy_input_sha256']:
        raise ValueError('Visible first inputs differ across the two departure times')
    for name, actual in early['policies'].items():
        if actual['steps'][0]['actions_kw'] != on_time['policies'][name]['steps'][0]['actions_kw']:
            raise ValueError(f'{name} changed the first action before departure was visible')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New artificial comparison JSON')
    output = parser.parse_args(argv).output
    if output.exists() or not output.parent.is_dir():
        parser.error('Output must be new and its parent directory must exist.')
    report = {
        'schema_version': 'synthetic-early-charging/v1', 'scope': 'hand-authored-engineering-only',
        'python': sys.version.split()[0], 'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'energy_tolerance_kwh': TOL_KWH, 'research_data_accessed': False,
        'fixture_tuple_fields': ['session_id', 'device_kw', 'declared_kwh',
                                 'declared_departure_minute', 'actual_departure_minute', 'goal_kwh'],
        'fixture_spec_order': ['sessions', 'site_capacity_kw', 'steps', 'optional_notice_minutes'],
        'status': 'FAIL', 'cases': [],
    }
    try:
        from evcf.integration.charging_optimizer import dispatch_early, dispatch_optimized
        from evcf.integration.charging_policy import dispatch_edf

        policies = {'edf': dispatch_edf, 'lp': dispatch_optimized, 'early': dispatch_early}
        report['solver'] = _solver_info()
        modules = ('reuse_contracts', 'controller_common', 'controller_quantities',
                   'controller_visibility', 'controller_adapter', 'charging_types', 'charging_policy',
                   'charging_loop', 'charging_plant', 'charging_optimizer')
        paths = [f'code/src/evcf/integration/{module}.py' for module in modules]
        paths.extend(('scripts/check_charging_optimizer.py', 'scripts/check_early_charging.py'))
        report['source_sha256'] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
        rows = {}
        for case, spec in FIXTURES.items():
            row = {'case_id': case, 'fixture_spec': spec, 'status': 'FAIL'}
            rows[case] = row
            report['cases'].append(row)
            try:
                row.update(_paired(case, spec, policies))
                row['first_policy_input_sha256'] = _first_input_digest(case, spec)
                row['lp_minus_early_shortfall_kwh'] = (
                    row['policies']['lp']['shortfall_kwh'] - row['policies']['early']['shortfall_kwh'])
                _check(row)
                row['status'] = 'PASS'
            except Exception as exc:  # noqa: BLE001 -- preserve any observations before a failed check
                row['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        _check_counterfactual(rows['joint_on_time'], rows['joint_early_2kwh'])
        report['joint_first_inputs_and_actions_match'] = True
        if all(row['status'] == 'PASS' for row in rows.values()):
            report['status'] = 'PASS'
    except Exception as exc:  # noqa: BLE001 -- record setup or cross-scenario failures
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': report['status'], 'cases': len(report['cases'])}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
