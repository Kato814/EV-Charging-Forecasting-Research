"""Opt-in engineering checks with hand-authored inputs only; not a research launcher."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code' / 'src'))


def synthetic_payload() -> dict:
    """Construct a test fixture; do not accept datasets or observed research values."""
    return {
        'schema_version': 'synthetic-dispatch/v1',
        'issue_time_utc': '2026-01-01T00:00:00Z',
        'step_seconds': 900,
        'observations': {
            'station_power': {
                'value': 4.0, 'unit': 'kW', 'available_at_utc': '2026-01-01T00:00:00Z',
            },
        },
        'forecast': {
            'kind': 'synthetic_forecast',
            'generated_at_utc': '2026-01-01T00:00:00Z',
            'unit': 'kW',
            'values': [[4.0] * 16, [6.0] * 16],
            'weights': [0.5, 0.5],
        },
    }


def package_versions() -> dict:
    names = ('numpy', 'pandas', 'scipy', 'cvxpy', 'pandapower', 'clarabel', 'scs', 'osqp')
    versions = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return {'python': sys.version.split()[0], 'packages': versions}


def source_hashes() -> dict:
    paths = (
        'scripts/check_reuse_synthetic.py',
        'code/src/evcf/integration/reuse_contracts.py',
        'code/src/evcf/integration/reuse_numerics.py',
    )
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}


def execute_checks(report: dict) -> None:
    from evcf.integration.reuse_contracts import (
        ContractError,
        interval_energy_kwh,
        kw_to_mw,
        validate_synthetic_dispatch_input,
    )
    from evcf.integration.reuse_numerics import (
        run_soc_parameter_probe,
        run_two_bus_powerflow_probe,
    )

    print('[1/3] synthetic information and unit contract', file=sys.stderr, flush=True)
    payload = synthetic_payload()
    normalized = validate_synthetic_dispatch_input(payload)
    rejected = []
    for name in ('actual_departure', 'final_kwh'):
        bad = synthetic_payload()
        bad['observations']['station_power'][name] = 999
        try:
            validate_synthetic_dispatch_input(bad)
        except ContractError:
            rejected.append(name)
        else:
            raise RuntimeError(f'Forbidden field accepted: {name}')
    energy = interval_energy_kwh([4.0] * 16, 900)
    converted = kw_to_mw(1000.0)
    if abs(energy - 16.0) > 1e-12 or abs(converted - 1.0) > 1e-12:
        raise RuntimeError('Known unit conversion identity failed')
    report['checks']['contracts'] = {
        'status': 'PASS', 'scenario_count': len(normalized.forecast.values),
        'horizon_steps': len(normalized.forecast.values[0]),
        'step_seconds': normalized.step_seconds, 'rejected_fields': rejected,
        'integrated_energy_kwh': energy, 'one_thousand_kw_in_mw': converted,
        'limitation': 'Checks declared metadata; does not prove caller provenance or truthful times.',
    }
    print('[2/3] parameterized SOC and infeasible case', file=sys.stderr, flush=True)
    report['checks']['soc'] = run_soc_parameter_probe()
    print('[3/3] manual two-bus AC power flow', file=sys.stderr, flush=True)
    report['checks']['powerflow'] = run_two_bus_powerflow_probe()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='New aggregate JSON report path')
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('Output already exists; preserve it and choose a new path.')
    if not args.output.parent.is_dir():
        parser.error('Output parent directory must already exist.')
    start = perf_counter()
    report = {
        'schema_version': 'reuse-engineering-report/v1',
        'scope': 'synthetic-engineering-only',
        'status': 'INCOMPLETE',
        'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'research_data_accessed': False,
        'forecast_models_fitted': 0,
        'services_contacted': False,
        'environment': package_versions(),
        'checks': {},
    }
    exit_code = 1
    try:
        report['source_sha256'] = source_hashes()
        execute_checks(report)
        report['status'] = 'PASS'
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 -- command boundary records failure and exits nonzero
        report['status'] = 'FAIL'
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        print(f'Engineering check failed: {type(exc).__name__}: {exc}', file=sys.stderr)
    report['elapsed_seconds'] = perf_counter() - start
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': report['status'], 'scope': report['scope']}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
