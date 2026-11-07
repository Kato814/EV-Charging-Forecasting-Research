"""Rolling optimizer checks on small hand-authored charging opportunities."""
import unittest
from fractions import Fraction
from importlib.util import find_spec
from types import SimpleNamespace
from unittest.mock import patch

from evcf.integration import charging_loop as loop
from evcf.integration.charging_policy import dispatch_edf
from evcf.integration.controller_adapter import build_synthetic_controller_view
from evcf.integration.controller_common import AdmissionError

if find_spec('evcf.integration.charging_optimizer'):
    from evcf.integration.charging_optimizer import dispatch_optimized
else:
    dispatch_optimized = None


def first_issue(specs, capacity):
    envelope, plant, options = loop._fixture(specs, capacity, 1)
    view = build_synthetic_controller_view(envelope)
    feedback = plant.feedback(tuple(s.state.session_id for s in view.sessions),
                              issue_time_utc=view.issue_time_utc)
    options.pop('steps')
    return view, feedback, options


class ChargingOptimizerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(dispatch_optimized, 'Rolling charging optimizer is missing')

    def test_l03_recovers_service_by_charging_rate_limited_session_immediately(self):
        specs = [('A', 8, 2, 30, 30, 2), ('B', 4, 3, 45, 45, 3)]
        envelope, plant, options = loop._fixture(specs, 8, 3)
        run = loop.run_loop(envelope, plant, **options, policy=dispatch_optimized)
        self.assertEqual({a.session_id: a.power_kw for a in run.decisions[0].actions},
                         {'A': 4, 'B': 4})
        self.assertTrue(run.evaluation.complete)
        self.assertEqual(run.evaluation.delivered_kwh, 5)
        self.assertEqual(run.evaluation.shortfall_kwh, 0)

    def test_genuine_capacity_shortage_is_preserved(self):
        specs = [('A', 4, 2, 30, 30, 2), ('B', 4, 2, 30, 30, 2)]
        envelope, plant, options = loop._fixture(specs, 4, 2)
        run = loop.run_loop(envelope, plant, **options, policy=dispatch_optimized)
        self.assertEqual(run.evaluation.delivered_kwh, 2)
        self.assertEqual(run.evaluation.shortfall_kwh, 2)

    def test_exact_aggregate_cap_and_remaining_energy_at_nonbinary_step_length(self):
        specs = [(str(i), 0.1, 1, 7, 7, 1) for i in range(6)]
        view, feedback, options = first_issue(specs, 0.6)
        result = dispatch_optimized(view, feedback, **options, step_seconds=420)
        power = sum(Fraction(a.power_kw) for a in result.actions)
        self.assertLessEqual(power, Fraction(0.6))
        self.assertAlmostEqual(float(power), 0.6)
        view, feedback, options = first_issue([('A', 8, 0.1, 7, 7, 0.1)], 8)
        action, = dispatch_optimized(view, feedback, **options, step_seconds=420).actions
        self.assertLessEqual(Fraction(action.power_kw) * Fraction(420, 3600), Fraction(0.1))
        self.assertLessEqual(action.power_kw * (420 / 3600), 0.1)
        self.assertAlmostEqual(action.power_kw * (420 / 3600), 0.1)

    def test_blockers_and_visible_remaining_are_inherited(self):
        specs = [('A', 4, 1, 15, 15, 1), ('B', 4, 0.5, 15, 15, 0.5)]
        view, feedback, options = first_issue(specs, 4)
        del options['device_limits_kw']['SYN-D-A']
        edf = dispatch_edf(view, feedback, **options)
        result = dispatch_optimized(view, feedback, **options)
        self.assertEqual(result.blocked, (('A', 'UNKNOWN_DEVICE_LIMIT'),))
        self.assertEqual(result.remaining_kwh, edf.remaining_kwh)
        self.assertEqual(result.stale_sessions, edf.stale_sessions)
        self.assertEqual([a.session_id for a in result.actions], ['B'])

    def test_maximum_horizon_included_and_longer_eligible_deadline_rejected(self):
        for steps in (16, 17):
            departure = steps * 15
            view, feedback, options = first_issue([('A', 4, 16, departure, departure, 16)], 4)
            if steps == 16:
                self.assertEqual(dispatch_optimized(view, feedback, **options).actions[0].power_kw, 4)
            else:
                with self.assertRaisesRegex(AdmissionError, 'OPTIMIZER_HORIZON'):
                    dispatch_optimized(view, feedback, **options)

    def test_solver_failure_and_malformed_status_are_rejected(self):
        view, feedback, options = first_issue([('A', 4, 1, 15, 15, 1)], 4)
        for success, status in [(False, 1), (False, 0), (True, 2), (True, False), (1, 0)]:
            fake = SimpleNamespace(success=success, status=status, fun=-4., x=[4.])
            with self.subTest(success=success, status=status), patch('scipy.optimize.linprog',
                    return_value=fake), self.assertRaisesRegex(AdmissionError, 'OPTIMIZER_FAILED'):
                dispatch_optimized(view, feedback, **options)
        with patch('scipy.optimize.linprog', side_effect=RuntimeError('solver unavailable')), \
                self.assertRaisesRegex(AdmissionError, 'OPTIMIZER_FAILED'):
            dispatch_optimized(view, feedback, **options)

    def test_invalid_solution_including_infeasible_future_step_is_rejected(self):
        view, feedback, options = first_issue([('A', 4, 1, 30, 30, 1)], 4)
        for values, objective in [([4.], -4.), ([0., float('nan')], 0.),
                                  ([-1., 0.], 1.), ([0., 5.], -5.), ([4., 4.], -8.),
                                  ([4., 0.], float('inf')), ([4., 0.], 0.)]:
            fake = SimpleNamespace(success=True, status=0, x=values, fun=objective)
            with self.subTest(values=values, objective=objective), patch('scipy.optimize.linprog',
                    return_value=fake), self.assertRaisesRegex(AdmissionError, 'INVALID_OPTIMIZER_SOLUTION'):
                dispatch_optimized(view, feedback, **options)

    def test_future_time_slot_aggregate_cap_is_checked_before_returning_first_step(self):
        specs = [('A', 4, 2, 30, 30, 2), ('B', 4, 2, 30, 30, 2)]
        view, feedback, options = first_issue(specs, 4)
        # Both start at zero and plan 4 kW in the second interval.
        fake = SimpleNamespace(success=True, status=0, x=[0., 4., 0., 4.], fun=-8.)
        with patch('scipy.optimize.linprog', return_value=fake), \
                self.assertRaisesRegex(AdmissionError, 'INVALID_OPTIMIZER_SOLUTION'):
            dispatch_optimized(view, feedback, **options)
