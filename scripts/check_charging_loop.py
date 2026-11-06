"""Execute eight fixed artificial charging-loop checks; never load research data."""
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
    'code/src/evcf/integration/charging_types.py',
    'code/src/evcf/integration/charging_policy.py',
    'code/src/evcf/integration/charging_plant.py',
    'code/src/evcf/integration/charging_loop.py',
    'scripts/check_charging_loop.py',
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New aggregate JSON report')
    args = parser.parse_args(argv)
    if args.output.exists() or not args.output.parent.is_dir():
        parser.error('Output must be new and its parent directory must exist.')
    started = perf_counter()
    report = {'schema_version': 'synthetic-charging-loop/v1', 'status': 'INCOMPLETE',
              'scope': 'hand-authored-engineering-only', 'real_dispatch_authorized': False,
              'research_data_accessed': False, 'forecast_models_fitted': 0,
              'network_constraints_evaluated': False, 'optimizer_used': False,
              'device': 'CPU; standard-library rule and arithmetic, no GPU backend',
              'python': sys.version.split()[0], 'cases': [],
              'started_at_utc': datetime.now(timezone.utc).isoformat()}
    print('[CPU] artificial rule and energy accounting; no GPU backend', file=sys.stderr, flush=True)
    try:
        from evcf.integration.charging_loop import run_acceptance

        report['source_sha256'] = {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_PATHS}
        report['cases'] = run_acceptance(
            progress=lambda case: print(f'[{case}/L08] artificial charging case',
                                        file=sys.stderr, flush=True))
        if [row['case_id'] for row in report['cases']] != [f'L{i:02}' for i in range(1,9)]:
            raise RuntimeError('Acceptance case identities are incomplete or out of order')
        report['status'] = 'PASS' if all(row['status'] == 'PASS' for row in report['cases']) else 'FAIL'
    except Exception as exc:  # noqa: BLE001 -- preserve command failures with nonzero exit
        report['status'] = 'FAIL'
        report['error'] = {'type': type(exc).__name__, 'message': str(exc)}
    report['passed'] = sum(row['status'] == 'PASS' for row in report['cases'])
    report['failed'] = sum(row['status'] != 'PASS' for row in report['cases'])
    report['elapsed_seconds'] = perf_counter() - started
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(encoded)
    print(json.dumps({key: report[key] for key in ('status', 'passed', 'failed', 'scope')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
