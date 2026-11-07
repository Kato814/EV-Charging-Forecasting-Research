import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / 'scripts/check_early_charging.py'


class EarlyChargingComparisonTests(unittest.TestCase):
    def test_matched_three_policy_report(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'report.json'
            cmd = [sys.executable, '-O', str(CLI), '--output', str(output)]
            run = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            data = output.read_bytes()
            report = json.loads(data)
            self.assertEqual(report['status'], 'PASS')
            for path, digest in report['source_sha256'].items():
                self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest)
            rows = {row['case_id']: row for row in report['cases']}
            self.assertEqual(set(rows), {'L02', 'L03', 'L04', 'joint_on_time', 'joint_early_1kwh',
                                         'joint_early_2kwh', 'joint_early_3kwh'})
            for row in rows.values():
                self.assertEqual(row['status'], 'PASS')
                self.assertEqual(len(row['paired_input_sha256']), 64)
                self.assertEqual(set(row['policies']), {'edf', 'lp', 'early'})
            early = rows['joint_early_2kwh']
            timely = rows['joint_on_time']
            self.assertEqual(early['first_policy_input_sha256'], timely['first_policy_input_sha256'])
            self.assertNotEqual(early['paired_input_sha256'], timely['paired_input_sha256'])
            for policy in early['policies']:
                self.assertEqual(early['policies'][policy]['steps'][0]['actions_kw'],
                                 timely['policies'][policy]['steps'][0]['actions_kw'])
            for need in (1, 2, 3):
                actual = rows[f'joint_early_{need}kwh']['policies']['early']
                by_car = {s['session_id']: s for s in actual['sessions']}
                self.assertAlmostEqual(by_car['A']['shortfall_kwh'], need - 4 * 10 / 60)
                self.assertAlmostEqual(by_car['B']['delivered_kwh'], 3)
            self.assertTrue(timely['policies']['early']['service_met'])
            self.assertAlmostEqual(rows['L04']['policies']['early']['shortfall_kwh'], 2)
            self.assertAlmostEqual(rows['L02']['policies']['early']['shortfall_kwh'], 2)
            repeat = subprocess.run(cmd, check=False, capture_output=True, timeout=60)
            self.assertNotEqual(repeat.returncode, 0)
            self.assertEqual(output.read_bytes(), data)

    def test_replacing_early_with_edf_is_detected_and_reported(self):
        wrapper = (
            'import pathlib,runpy,sys\n'
            'root=pathlib.Path(sys.argv[1]).resolve().parents[1]\n'
            'sys.path[:0]=[str(root/"scripts"),str(root/"code/src")]\n'
            'from evcf.integration import charging_optimizer,charging_policy\n'
            'charging_optimizer.dispatch_early=charging_policy.dispatch_edf\n'
            'sys.argv=sys.argv[1:]\n'
            'runpy.run_path(sys.argv[0],run_name="__main__")'
        )
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'fault.json'
            run = subprocess.run([sys.executable, '-O', '-c', wrapper, str(CLI), '--output',
                                  str(output)], check=False, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
            report = json.loads(output.read_bytes())
            self.assertEqual(report['status'], 'FAIL')
            row = next(r for r in report['cases'] if r['case_id'] == 'L03')
            self.assertEqual(row['status'], 'FAIL')
            self.assertAlmostEqual(row['policies']['early']['shortfall_kwh'], 1)
