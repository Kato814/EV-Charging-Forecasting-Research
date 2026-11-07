"""Service-preserving early charging on hand-authored sessions."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from evcf.integration import charging_loop as loop
from evcf.integration import charging_optimizer
from evcf.integration.controller_common import AdmissionError


class EarlyChargingTests(unittest.TestCase):
    def run_early(self, rows, capacity, steps, notices=None):
        policy = getattr(charging_optimizer, 'dispatch_early', None)
        self.assertIsNotNone(policy, 'Missing early charging policy')
        env, plant, options = loop._fixture(rows, capacity, steps, notices)
        return loop.run_loop(env, plant, **options, policy=policy)

    def test_first_delivered_energy_reaches_the_ten_minute_physical_maximum(self):
        result = self.run_early([('A', 6, 3, 45, 10, 3)], 6, 3, {'A': 30})
        self.assertEqual(result.decisions[0].actions[0].power_kw, 6)
        self.assertEqual(result.evaluation.delivered_kwh, 1)
        self.assertEqual(result.evaluation.shortfall_kwh, 2)

    def test_slow_car_gets_every_required_slot_while_fast_car_leaves_early(self):
        rows = [('A', 6, 1.5, 45, 10, 1.5), ('B', 4, 3, 45, 45, 3)]
        result = self.run_early(rows, 8, 3, {'A': 30})
        self.assertEqual({a.session_id: a.power_kw for a in result.decisions[0].actions},
                         {'A': 4, 'B': 4})
        sessions = {s.session_id: s for s in result.evaluation.sessions}
        self.assertAlmostEqual(sessions['A'].delivered_kwh, 4 / 6)
        self.assertEqual(sessions['B'].delivered_kwh, 3)

    def test_shortage_retains_original_allocation_without_second_stage(self):
        from scipy.optimize import linprog

        rows = [('A', 4, 2, 30, 30, 2), ('B', 4, 2, 30, 30, 2)]
        env, plant, options = loop._fixture(rows, 4, 2)
        original = loop.run_loop(env, plant, **options, policy=charging_optimizer.dispatch_optimized)
        with patch('scipy.optimize.linprog', wraps=linprog) as solve:
            result = self.run_early(rows, 4, 2)
        self.assertEqual(result.decisions, original.decisions)
        self.assertEqual(result.evaluation.shortfall_kwh, 2)
        self.assertEqual(solve.call_count, 2)

    def test_no_positive_request_issues_no_command(self):
        result = self.run_early([('A', 8, 0, 30, 30, 0)], 8, 2)
        self.assertEqual(result.evaluation.delivered_kwh, 0)
        self.assertTrue(all(not d.actions for d in result.decisions))

    def test_rejects_failed_secondary_or_solution_losing_primary_service(self):
        rows = [('A', 4, 1, 30, 30, 1)]
        primary = SimpleNamespace(success=True, status=0, x=[0., 4.], fun=-4.)
        cases = [
            (SimpleNamespace(success=False, status=2), 'OPTIMIZER_FAILED'),
            (RuntimeError('secondary unavailable'), 'OPTIMIZER_FAILED'),
            (SimpleNamespace(success=True, status=0, x=[3., 0.], fun=0.), 'INVALID_OPTIMIZER_SOLUTION'),
            (SimpleNamespace(success=True, status=0, x=[4., 0.], fun=-4.), 'INVALID_OPTIMIZER_SOLUTION'),
        ]
        for secondary, reason in cases:
            with self.subTest(secondary=secondary), patch('scipy.optimize.linprog',
                    side_effect=[primary, secondary]), self.assertRaisesRegex(AdmissionError, reason):
                self.run_early(rows, 4, 1)

    def test_rejects_declared_optimum_with_worse_timing_than_known_witness(self):
        primary = SimpleNamespace(success=True, status=0, x=[4., 0.], fun=-4.)
        later = SimpleNamespace(success=True, status=0, x=[0., 4.], fun=4.)
        with patch('scipy.optimize.linprog', side_effect=[primary, later]), \
                self.assertRaisesRegex(AdmissionError, 'INVALID_OPTIMIZER_SOLUTION'):
            self.run_early([('A', 4, 1, 30, 30, 1)], 4, 1)
