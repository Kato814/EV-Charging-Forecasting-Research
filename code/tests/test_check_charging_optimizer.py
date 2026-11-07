import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / 'scripts/check_charging_optimizer.py'


class OptimizerComparisonTests(unittest.TestCase):
    def test_offline_paired_report_and_exclusive_output(self):
        guard = (
            'import runpy,socket,sys\n'
            'def blocked(*a, **kw):\n raise RuntimeError("Network forbidden")\n'
            'socket.socket.connect=socket.socket.connect_ex=blocked\n'
            'socket.create_connection=socket.getaddrinfo=blocked\n'
            'sys.argv=sys.argv[1:]\n'
            'runpy.run_path(sys.argv[0],run_name="__main__")'
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'pair.json'
            args = [str(CLI), '--output', str(output)]
            run = subprocess.run([sys.executable, '-O', '-c', guard, *args],
                                 check=False, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            report = json.loads(output.read_bytes())
            self.assertEqual((report['status'], report['passed'], report['failed']), ('PASS', 7, 0))
            cases = {row['case_id']: row['variants'] for row in report['cases']}
            self.assertEqual(set(cases), {'L01', 'L02', 'L03', 'L04', 'L05', 'L06', 'L08'})
            for variants in cases.values():
                for pair in variants.values():
                    self.assertEqual(set(pair['policies']), {'edf', 'lp'})
                    self.assertEqual(len(pair['paired_input_sha256']), 64)
                    for actual in pair['policies'].values():
                        self.assertTrue(actual['evaluation_complete'])
                        self.assertAlmostEqual(actual['delivered_kwh'],
                                               sum(s['delivered_kwh'] for s in actual['steps']))
            l03 = cases['L03']['base']['policies']
            self.assertAlmostEqual(l03['edf']['shortfall_kwh'], 1.0)
            self.assertFalse(l03['edf']['service_met'])
            self.assertTrue(l03['lp']['service_met'])
            for actual in cases['L08']['base']['policies'].values():
                self.assertAlmostEqual(actual['steps'][0]['delivered_kwh'], 2)
                self.assertAlmostEqual(actual['delivered_kwh'], 7)
            before = output.read_bytes()
            again = subprocess.run([sys.executable, *args], check=False, capture_output=True, timeout=30)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(output.read_bytes(), before)

    def test_edf_substitution_fails_counterexample_and_preserves_observations(self):
        guard = (
            'import pathlib,runpy,sys\n'
            'sys.path.insert(0,str(pathlib.Path(sys.argv[1]).parents[1]/"code/src"))\n'
            'from evcf.integration import charging_optimizer,charging_policy\n'
            'charging_optimizer.dispatch_optimized=charging_policy.dispatch_edf\n'
            'sys.argv=sys.argv[1:]\n'
            'runpy.run_path(sys.argv[0],run_name="__main__")'
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'fail.json'
            run = subprocess.run([sys.executable, '-O', '-c', guard, str(CLI), '--output',
                                  str(output)], check=False, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 1, run.stderr + run.stdout)
            report = json.loads(output.read_bytes())
            failed = [r for r in report['cases'] if r['status'] == 'FAIL']
            self.assertEqual([r['case_id'] for r in failed], ['L03'])
            self.assertEqual(report['status'], 'FAIL')
            self.assertEqual(failed[0]['variants']['base']['policies']['lp']['shortfall_kwh'], 1)
