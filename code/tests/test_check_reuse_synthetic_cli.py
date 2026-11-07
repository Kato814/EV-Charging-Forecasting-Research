"""Exercise the opt-in synthetic command; no research files are used."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / 'scripts' / 'check_reuse_synthetic.py'
NUMERICAL_AVAILABLE = all(importlib.util.find_spec(name) for name in ('cvxpy', 'pandapower'))


class SyntheticCommandTests(unittest.TestCase):
    def test_command_exists(self):
        self.assertTrue(CLI.is_file(), 'Synthetic command has not been implemented')

    @unittest.skipUnless(NUMERICAL_AVAILABLE, 'Optional synthetic numerical environment required')
    def test_real_command_with_network_connections_blocked(self):
        self.assertTrue(CLI.is_file(), 'Synthetic command has not been implemented')
        guard = (
            'import runpy,socket,sys\n'
            'def blocked(*args,**kwargs):\n'
            ' raise RuntimeError("Network access forbidden in synthetic validation")\n'
            'socket.socket.connect=blocked\n'
            'socket.socket.connect_ex=blocked\n'
            'socket.create_connection=blocked\n'
            'socket.getaddrinfo=blocked\n'
            'sys.argv=sys.argv[1:]\n'
            'runpy.run_path(sys.argv[0],run_name="__main__")\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            result = subprocess.run(
                [sys.executable, '-c', guard, str(CLI), '--output', str(output)],
                check=False, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['status'], 'PASS')
            self.assertEqual(report['scope'], 'synthetic-engineering-only')
            self.assertFalse(report['research_data_accessed'])
            self.assertEqual(report['checks']['contracts']['integrated_energy_kwh'], 16.0)
            self.assertIn('soc', report['checks'])
            self.assertIn('powerflow', report['checks'])
            original = output.read_bytes()
            repeat = subprocess.run(
                [sys.executable, str(CLI), '--output', str(output)],
                check=False, capture_output=True, text=True, timeout=30,
            )
            self.assertNotEqual(repeat.returncode, 0)
            self.assertEqual(output.read_bytes(), original)

    def test_output_argument_is_required(self):
        self.assertTrue(CLI.is_file(), 'Synthetic command has not been implemented')
        result = subprocess.run([sys.executable, str(CLI)], check=False,
                                capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)

    def test_failed_probe_returns_failure_and_preserves_report(self):
        self.assertTrue(CLI.is_file(), 'Synthetic command has not been implemented')
        guard = (
            'import runpy,sys\n'
            'namespace=runpy.run_path(sys.argv[1],run_name="synthetic_cli_under_test")\n'
            'def fail(report):\n'
            ' raise RuntimeError("probe failed")\n'
            'namespace["main"].__globals__["execute_checks"]=fail\n'
            'raise SystemExit(namespace["main"](sys.argv[2:]))\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'failed.json'
            result = subprocess.run(
                [sys.executable, '-c', guard, str(CLI), '--output', str(output)],
                check=False, capture_output=True, text=True, timeout=30,
            )
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(report['status'], 'FAIL')
            self.assertEqual(report['error']['type'], 'RuntimeError')
            self.assertEqual(report['checks'], {})


if __name__ == '__main__':
    unittest.main()
