"""Run hand-authored controller cases only; never acquire data or fit models."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code/src'))

SOURCE_PATHS = (
    'code/src/evcf/integration/reuse_contracts.py',
    'code/src/evcf/integration/controller_common.py',
    'code/src/evcf/integration/controller_visibility.py',
    'code/src/evcf/integration/controller_quantities.py',
    'code/src/evcf/integration/controller_adapter.py',
    'code/src/evcf/integration/controller_acceptance.py',
    'scripts/check_controller_adapter.py',
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New aggregate JSON report')
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error('Output exists; preserve it and choose a new path.')
    if not args.output.parent.is_dir():
        parser.error('Output parent directory must exist.')
    started = perf_counter()
    report = {
        'schema_version': 'controller-adapter-checks/v1', 'scope': 'hand-authored-engineering-only',
        'status': 'INCOMPLETE', 'synthetic_only': True, 'real_dispatch_authorized': False,
        'research_data_accessed': False, 'forecast_models_fitted': 0, 'services_contacted': False,
        'started_at_utc': datetime.now(timezone.utc).isoformat(), 'python': sys.version.split()[0],
        'cases': [],
    }
    try:
        from evcf.integration.controller_acceptance import run_acceptance

        report['source_sha256'] = {
            p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCE_PATHS
        }
        report['cases'] = run_acceptance(
            progress=lambda case: print(f'[{case}/C15] synthetic controller check',
                                        file=sys.stderr, flush=True))
        expected = [f'C{i:02}' for i in range(1, 16)]
        if [c['case_id'] for c in report['cases']] != expected:
            raise RuntimeError('Acceptance case identity set is incomplete or out of order')
        report['status'] = 'PASS' if all(c['status'] == 'PASS' for c in report['cases']) else 'FAIL'
    except Exception as exc:  # noqa: BLE001 -- command boundary records failure and exits nonzero
        report['status'] = 'FAIL'
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    report['passed'] = sum(c['status'] == 'PASS' for c in report['cases'])
    report['failed'] = sum(c['status'] != 'PASS' for c in report['cases'])
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    report['elapsed_seconds'] = perf_counter() - started
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(encoded)
    print(json.dumps({k: report[k] for k in ('status', 'passed', 'failed', 'scope')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
