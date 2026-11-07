"""Compare EDF with the receding-horizon LP on fixed artificial charging sessions."""
import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code/src'))
TOL_KWH = 1e-7

# _fixture expects (session, device kW, declaration kWh, declared departure minute,
# actual departure minute, required kWh), then site kW, steps and optional notice minutes.
CASES = {
    'L01': {'base': ([('A', 4, 0.5, 15, 15, 0.5), ('B', 4, 1.5, 30, 30, 1.5)], 4, 2)},
    'L02': {'base': ([('A', 4, 2, 30, 30, 2), ('B', 4, 2, 30, 30, 2)], 4, 2)},
    'L03': {'base': ([('A', 8, 2, 30, 30, 2), ('B', 4, 3, 45, 45, 3)], 8, 3)},
    'L04': {'base': ([('A', 6, 3, 45, 10, 3)], 6, 3, {'A': 30})},
    'L05': {'base': ([('A', 4, 1, 15, 15, 1)], 4, 1)},
    'L06': {'base': ([('A', 4, 4, 60, 60, 4)], 4, 4),
            'changed_goal': ([('A', 4, 4, 60, 60, 2)], 4, 4),
            'changed_departure': ([('A', 4, 4, 60, 45, 4)], 4, 4)},
    'L08': {'base': ([('A', 8, 2, 15, 60, 7)], 8, 4)},
}
CASE_DESCRIPTIONS = {
    'L01': 'Feasible visible requests totaling 2 kWh.',
    'L02': '4 kWh required; 4 kW for 30 minutes can deliver at most 2 kWh.',
    'L03': 'Device B needs every 15-minute slot at 4 kW to receive its 3 kWh.',
    'L04': 'Actual departure at minute 10, notice at minute 30, declared departure at minute 45.',
    'L05': 'Unknown request basis blocks dispatch.',
    'L06': 'Perturb only the hidden goal or shorten actual departure to minute 45.',
    'L08': 'Matched L08 variant: initial 2 kWh due at minute 15. At minute 15 the declaration '
           'adds 5 kWh, with a 2 kWh baseline and revised deadline at minute 60.',
}


def _fresh_fixture(case_id, spec):
    from evcf.integration.charging_loop import _event, _fixture, _request

    envelope, plant, options = _fixture(*spec)
    if case_id == 'L05':
        envelope['events'][1]['payload']['request_basis'] = 'unknown'
    elif case_id == 'L08':
        revision = _request(5, 60, 'additional', 2)
        envelope['events'].append(_event('A', 'request', 15, revision, revision=1))
    inputs = {'envelope': envelope, 'options': options, 'fixture_spec_including_truth': spec}
    encoded = json.dumps(inputs, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return envelope, plant, options, hashlib.sha256(encoded).hexdigest()


def _observed(result):
    evaluation = result.evaluation
    steps = []
    for decision, execution in zip(result.decisions, result.executions, strict=True):
        steps.append({
            'issue_time_utc': decision.issue_time_utc.isoformat(),
            'actions_kw': {a.session_id: a.power_kw for a in decision.actions},
            'remaining_kwh': dict(decision.remaining_kwh), 'blocked': dict(decision.blocked),
            'commanded_kw': execution.commanded_kw, 'delivered_kwh': execution.delivered_kwh,
            'executed_kwh': {e.session_id: e.energy_kwh for e in execution.increments},
        })
    return {
        'evaluation_complete': evaluation.complete,
        'service_met': evaluation.complete and all(s.shortfall_kwh <= TOL_KWH
                                                   for s in evaluation.sessions),
        'delivered_kwh': evaluation.delivered_kwh, 'shortfall_kwh': evaluation.shortfall_kwh,
        'overdelivery_kwh': evaluation.overdelivery_kwh,
        'sessions': [asdict(s) for s in evaluation.sessions], 'steps': steps,
    }


def _paired(case_id, spec, policies):
    from evcf.integration.charging_loop import run_loop

    runs, digests = {}, []
    for name, policy in policies.items():
        envelope, plant, options, digest = _fresh_fixture(case_id, spec)
        digests.append(digest)
        runs[name] = _observed(run_loop(envelope, plant, policy=policy, **options))
    if len(set(digests)) != 1:
        raise ValueError('Paired policies received different artificial inputs')
    return {'paired_input_sha256': digests[0], 'policies': runs,
            'edf_minus_lp_shortfall_kwh': runs['edf']['shortfall_kwh'] - runs['lp']['shortfall_kwh']}


def _energy(actual, expected, label):
    if not math.isclose(actual, expected, rel_tol=0, abs_tol=TOL_KWH):
        raise ValueError(f'{label}: expected {expected} kWh, observed {actual} kWh')


def _validate(case_id, variants):
    for variant in variants.values():
        for actual in variant['policies'].values():
            if not actual['evaluation_complete']:
                raise ValueError('Artificial evaluation ended before all departures')
            _energy(sum(s['delivered_kwh'] for s in actual['steps']), actual['delivered_kwh'],
                    'step accounting')
    for name, actual in variants['base']['policies'].items():
        steps = actual['steps']
        if case_id in ('L01', 'L02', 'L03', 'L05', 'L08'):
            # (delivered, unserved) energy at actual departure.
            expected = {'L01': (2, 0), 'L02': (2, 2),
                        'L03': (4, 1) if name == 'edf' else (5, 0),
                        'L05': (0, 1), 'L08': (7, 0)}[case_id]
            _energy(actual['delivered_kwh'], expected[0], name + ' delivery')
            _energy(actual['shortfall_kwh'], expected[1], name + ' shortfall')
            _energy(actual['overdelivery_kwh'], 0, name + ' surplus')
        if case_id == 'L04':
            _energy(steps[0]['delivered_kwh'], steps[0]['commanded_kw'] * 10 / 60,
                    '10-minute connection overlap')
            _energy(sum(s['delivered_kwh'] for s in steps[1:]), 0, 'energy after departure')
            if steps[2]['actions_kw']:
                raise ValueError('Issued an action after the departure notice became visible')
            _energy(actual['shortfall_kwh'], 3 - steps[0]['delivered_kwh'], 'early departure')
            if name == 'edf':
                _energy(actual['shortfall_kwh'], 2, 'reference EDF shortfall')
        elif case_id == 'L05':
            if steps[0]['actions_kw'] or steps[0]['blocked'].get('A') != 'UNKNOWN_REQUEST_BASIS':
                raise ValueError('Unknown request basis must explicitly block the session')
        elif case_id == 'L06':
            goal = variants['changed_goal']['policies'][name]
            departure = variants['changed_departure']['policies'][name]
            if steps != goal['steps'] or steps[:3] != departure['steps'][:3]:
                raise ValueError('Hidden goal or future departure changed an earlier action or execution')
            _energy(actual['shortfall_kwh'], 0, 'original goal')
            _energy(goal['overdelivery_kwh'], 2, 'perturbed goal surplus')
            _energy(departure['shortfall_kwh'], 1, 'earlier departure shortfall')
        elif case_id == 'L08':
            _energy(steps[0]['executed_kwh'].get('A', 0), 2, 'delivered-at-revision baseline')
            _energy(steps[1]['remaining_kwh']['A'], 5, 'additional request at revision')


def _solver_info():
    import scipy
    from evcf.integration.charging_optimizer import MAX_HORIZON_STEPS, SOLVER_METHOD

    # The standalone highspy package can have a different version from SciPy's backend.
    try:
        from scipy.optimize._highspy import _core
        highs_version = '.'.join(str(getattr(_core, 'HIGHS_VERSION_' + part))
                                for part in ('MAJOR', 'MINOR', 'PATCH'))
    except (ImportError, AttributeError):
        highs_version = None
    return {'entrypoint': 'scipy.optimize.linprog', 'method': SOLVER_METHOD,
            'scipy_version': scipy.__version__, 'bundled_highs_version': highs_version,
            'max_horizon_steps': MAX_HORIZON_STEPS}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New artificial comparison JSON')
    args = parser.parse_args(argv)
    if args.output.exists() or not args.output.parent.is_dir():
        parser.error('Output must be new and its parent directory must exist.')
    start = perf_counter()
    report = {
        'schema_version': 'synthetic-charging-optimizer/v1', 'scope': 'hand-authored-engineering-only',
        'research_data_accessed': False, 'forecast_models_fitted': 0, 'real_dispatch_authorized': False,
        'network_constraints_evaluated': False, 'device': 'CPU', 'energy_tolerance_kwh': TOL_KWH,
        'service_definition': 'All sessions departed and each realized shortfall <= tolerance.',
        'assumptions': ['15-minute constant commands', 'unit efficiency',
                        'one aggregate site/cluster budget and fixed device limits',
                        'synchronous cumulative energy', 'assumed event reception times'],
        'started_at_utc': datetime.now(timezone.utc).isoformat(), 'python': sys.version.split()[0],
        'status': 'FAIL', 'cases': [],
    }
    print('[CPU] EDF and SciPy HiGHS on hand-authored fixtures', file=sys.stderr, flush=True)
    try:
        from evcf.integration.charging_optimizer import dispatch_optimized
        from evcf.integration.charging_policy import dispatch_edf

        report['solver'] = _solver_info()
        modules = ('reuse_contracts', 'controller_common', 'controller_quantities',
                   'controller_visibility', 'controller_adapter', 'charging_types', 'charging_policy',
                   'charging_loop', 'charging_plant', 'charging_optimizer')
        paths = tuple(f'code/src/evcf/integration/{m}.py' for m in modules) + (
            'scripts/check_charging_optimizer.py',)
        report['source_sha256'] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
        policies = {'edf': dispatch_edf, 'lp': dispatch_optimized}
        for index, (case_id, definitions) in enumerate(CASES.items(), 1):
            row = {'case_id': case_id, 'description': CASE_DESCRIPTIONS[case_id], 'variants': {}}
            report['cases'].append(row)
            try:
                for variant, spec in definitions.items():
                    row['variants'][variant] = _paired(case_id, spec, policies)
                _validate(case_id, row['variants'])
                row['status'] = 'PASS'
            except Exception as exc:  # noqa: BLE001 -- record failures and continue later cases
                row.update(status='FAIL', error={'type': type(exc).__name__, 'message': str(exc)})
            print(f'[{index}/{len(CASES)}] {case_id} {row["status"]}', file=sys.stderr, flush=True)
        if all(row['status'] == 'PASS' for row in report['cases']):
            report['status'] = 'PASS'
    except Exception as exc:  # noqa: BLE001 -- record setup failures as a nonzero exit
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    report['passed'] = sum(row['status'] == 'PASS' for row in report['cases'])
    report['failed'] = sum(row['status'] == 'FAIL' for row in report['cases'])
    report['elapsed_seconds'] = perf_counter() - start
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    with args.output.open('x', encoding='utf-8', newline='\n') as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({key: report[key] for key in ('status', 'passed', 'failed')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
