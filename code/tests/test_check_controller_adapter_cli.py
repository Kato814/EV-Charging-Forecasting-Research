"""Run the artificial acceptance command without numerical packages or network."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / 'scripts/check_controller_adapter.py'


class ControllerCommandTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CLI.is_file(), 'Controller acceptance command is not implemented')

    def test_requires_explicit_new_output(self):
        result = subprocess.run([sys.executable, str(CLI)], check=False,
                                capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)

    def test_stdlib_network_blocked_run_and_no_overwrite(self):
        guard = ('import runpy,socket,sys\n'
                 'def blocked(*args,**kwargs):\n'
                 ' raise RuntimeError("Network forbidden")\n'
                 'socket.socket.connect=blocked\n'
                 'socket.socket.connect_ex=blocked\n'
                 'socket.create_connection=blocked\n'
                 'socket.getaddrinfo=blocked\n'
                 'sys.argv=sys.argv[1:]\n'
                 'runpy.run_path(sys.argv[0],run_name="__main__")\n')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'success.json'
            result = subprocess.run([sys.executable, '-S', '-c', guard, str(CLI),
                                     '--output', str(output)], check=False,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual((report['status'], report['passed'], report['failed']), ('PASS', 15, 0))
            self.assertEqual([c['case_id'] for c in report['cases']], [f'C{i:02}' for i in range(1,16)])
            self.assertFalse(report['real_dispatch_authorized'])
            original = output.read_bytes()
            repeat = subprocess.run([sys.executable, str(CLI), '--output', str(output)],
                                    check=False, capture_output=True, timeout=30)
            self.assertNotEqual(repeat.returncode, 0)
            self.assertEqual(output.read_bytes(), original)

    def test_injected_case_failure_causes_nonzero_exit_and_saved_failure(self):
        guard = ('import runpy,sys,pathlib\n'
                 'sys.path.insert(0,str(pathlib.Path(sys.argv[1]).parents[1]/"code"/"src"))\n'
                 'import evcf.integration.controller_acceptance as cases\n'
                 'def fail():\n'
                 ' raise RuntimeError("injected case failure")\n'
                 'cases.CASES=(("C01",fail),)+cases.CASES[1:]\n'
                 'sys.argv=sys.argv[1:]\n'
                 'runpy.run_path(sys.argv[0],run_name="__main__")\n')
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'failure.json'
            result = subprocess.run([sys.executable, '-S', '-c', guard, str(CLI),
                                     '--output', str(output)], check=False,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual((report['status'], report['passed'], report['failed']), ('FAIL', 14, 1))
            self.assertEqual(report['cases'][0]['error']['type'], 'RuntimeError')

    def test_optimized_python_does_not_disable_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'optimized.json'
            result = subprocess.run([sys.executable, '-S', '-O', str(CLI), '--output', str(output)],
                                    check=False, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['passed'], 15)


if __name__ == '__main__':
    unittest.main()
