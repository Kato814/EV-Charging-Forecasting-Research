import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / 'scripts/check_charging_loop.py'


class ChargingCommandTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CLI.is_file(), 'Artificial charging command is not implemented')

    def test_output_is_required(self):
        result = subprocess.run([sys.executable, str(CLI)], capture_output=True, check=False, timeout=30)
        self.assertNotEqual(result.returncode, 0)

    def test_stdlib_network_blocked_command_and_no_overwrite(self):
        guard = ('import runpy,socket,sys\n'
                 'def blocked(*a,**kw):\n raise RuntimeError("Network forbidden")\n'
                 'socket.socket.connect=blocked\nsocket.socket.connect_ex=blocked\n'
                 'socket.create_connection=blocked\nsocket.getaddrinfo=blocked\n'
                 'sys.argv=sys.argv[1:]\nrunpy.run_path(sys.argv[0],run_name="__main__")\n')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            result = subprocess.run([sys.executable, '-S', '-c', guard, str(CLI), '--output', str(output)],
                                    capture_output=True, check=False, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual((report['status'], report['passed'], report['failed']), ('PASS',8,0))
            self.assertFalse(report['real_dispatch_authorized'])
            self.assertFalse(report['network_constraints_evaluated'])
            self.assertEqual(len(report['source_sha256']), 10)
            before = output.read_bytes()
            repeated = subprocess.run([sys.executable, str(CLI), '--output', str(output)],
                                      capture_output=True, check=False, timeout=30)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(output.read_bytes(), before)

    def test_injected_failure_is_saved_and_fails_process(self):
        guard = ('import sys,runpy,pathlib\n'
                 'sys.path.insert(0,str(pathlib.Path(sys.argv[1]).parents[1]/"code/src"))\n'
                 'import evcf.integration.charging_loop as loop\n'
                 'def fail():\n raise RuntimeError("injected failure")\n'
                 'loop.CASES=(("L01",fail),)+loop.CASES[1:]\n'
                 'sys.argv=sys.argv[1:]\nrunpy.run_path(sys.argv[0],run_name="__main__")\n')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            result = subprocess.run([sys.executable, '-S', '-c', guard, str(CLI), '--output', str(output)],
                                    capture_output=True, check=False, text=True, timeout=30)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual((report['status'], report['passed'], report['failed']), ('FAIL',7,1))
            self.assertEqual(report['cases'][0]['error']['type'], 'RuntimeError')

    def test_optimized_python_keeps_acceptance_checks_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            result = subprocess.run([sys.executable, '-S', '-O', str(CLI), '--output', str(output)],
                                    capture_output=True, check=False, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['passed'], 8)
