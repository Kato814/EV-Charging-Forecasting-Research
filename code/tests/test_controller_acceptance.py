"""Acceptance evidence must come from executed cases and retain case failures."""
import importlib
import unittest
from unittest import mock

try:
    acceptance = importlib.import_module('evcf.integration.controller_acceptance')
except ModuleNotFoundError as exc:
    if not exc.name.startswith('evcf.integration.controller_'):
        raise
    acceptance = None


class ControllerAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(acceptance, 'Controller acceptance cases are not implemented')

    def test_all_fifteen_cases_execute_and_have_observed_evidence(self):
        progress = []
        results = acceptance.run_acceptance(progress=progress.append)
        self.assertEqual([row['case_id'] for row in results], [f'C{i:02}' for i in range(1, 16)])
        self.assertEqual(len(progress), 15)
        self.assertTrue(all(row['status'] == 'PASS' and row['observed'] for row in results), results)

    def test_failed_case_is_preserved_and_remaining_cases_continue(self):
        def fail():
            raise AssertionError('injected acceptance failure')

        with mock.patch.object(acceptance, 'CASES', (('C01', fail), ('C02', lambda: {'ran': True}))):
            results = acceptance.run_acceptance()
        self.assertEqual(results[0]['status'], 'FAIL')
        self.assertEqual(results[0]['error']['type'], 'AssertionError')
        self.assertEqual(results[1]['status'], 'PASS')


if __name__ == '__main__':
    unittest.main()
