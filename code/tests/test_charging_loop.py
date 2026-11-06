import copy
import importlib
import unittest
from unittest import mock

try:
    loop = importlib.import_module('evcf.integration.charging_loop')
except ModuleNotFoundError as exc:
    if not exc.name.startswith('evcf.integration.charging_'):
        raise
    loop = None


class ChargingLoopTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(loop, 'Artificial charging loop is not implemented')

    def test_all_eight_cases_have_executed_observations(self):
        progress = []
        results = loop.run_acceptance(progress=progress.append)
        self.assertEqual([r['case_id'] for r in results], [f'L{i:02}' for i in range(1,9)])
        self.assertTrue(all(r['status'] == 'PASS' and r['observed'] for r in results), results)
        self.assertEqual(progress, [f'L{i:02}' for i in range(1,9)])

    def test_feasible_hand_calculation_and_input_immutability(self):
        envelope, plant, options = loop._fixture(
            [('A', 4, 0.5, 15, 15, 0.5), ('B', 4, 1.5, 30, 30, 1.5)], 4, 2)
        before = copy.deepcopy(envelope)
        result = loop.run_loop(envelope, plant, **options)
        self.assertEqual(envelope, before)
        self.assertEqual([[a.power_kw for a in d.actions] for d in result.decisions], [[2, 2], [4]])
        self.assertEqual([s.delivered_kwh for s in result.executions], [1, 1])
        self.assertEqual(result.evaluation.delivered_kwh, 2)
        self.assertEqual(result.evaluation.shortfall_kwh, 0)
        self.assertTrue(result.evaluation.complete)

    def test_capacity_shortfall_is_retained(self):
        result = loop._l02()
        self.assertEqual(result['delivered_kwh'], 2)
        self.assertEqual(result['shortfall_kwh'], 2)
        self.assertFalse(result['general_infeasibility_proved'])

    def test_decimal_capacity_dispatch_is_accepted_by_strict_plant(self):
        specs = [(f'S{i}', 0.1, 1, 15, 15, 1) for i in range(6)]
        envelope, plant, options = loop._fixture(specs, 0.6, 1)
        result = loop.run_loop(envelope, plant, **options)
        self.assertLessEqual(result.executions[0].commanded_kw, 0.6)
        self.assertAlmostEqual(result.evaluation.delivered_kwh, 0.15)

    def test_rule_counterexample_has_a_successful_executed_witness(self):
        result = loop._l03()
        self.assertEqual(result['edf_shortfall_kwh'], 1)
        self.assertEqual(result['witness_shortfall_kwh'], 0)
        self.assertEqual(result['witness_delivered_kwh'], 5)

    def test_late_notice_does_not_create_fictitious_energy(self):
        result = loop._l04()
        self.assertEqual(result['commanded_kw'], [6, 6, 0])
        self.assertEqual(result['delivered_per_step_kwh'], [1, 0, 0])
        self.assertEqual(result['shortfall_kwh'], 2)

    def test_hidden_target_only_changes_evaluation(self):
        result = loop._l06()
        self.assertTrue(result['target_change_actions_equal'])
        self.assertTrue(result['target_change_delivery_equal'])
        self.assertEqual(result['changed_target_overdelivery_kwh'], 2)
        self.assertTrue(result['future_departure_prefix_equal'])

    def test_additional_revision_consumes_real_feedback(self):
        result = loop._l08()
        self.assertEqual(result['commanded_kw'], [8, 8, 8, 4])
        self.assertEqual(result['delivered_kwh'], 7)
        self.assertEqual(result['shortfall_kwh'], 0)

    def test_invalid_step_count_does_not_advance_plant(self):
        envelope, plant, options = loop._fixture([('A',4,1,15,15,1)],4,1)
        before = plant.feedback(('A',), issue_time_utc=loop._time(0))
        for value in (True, 0, -1, 1.5):
            with self.subTest(value=value), self.assertRaises(loop.AdmissionError):
                loop.run_loop(envelope, plant, **{**options, 'steps': value})
            self.assertEqual(before, plant.feedback(('A',), issue_time_utc=loop._time(0)))

    def test_case_failure_is_preserved_and_later_case_executes(self):
        def fail():
            raise RuntimeError('injected failure')
        with mock.patch.object(loop, 'CASES', (('L01', fail), ('L02', lambda: {'ran': True}))):
            result = loop.run_acceptance()
        self.assertEqual([r['status'] for r in result], ['FAIL', 'PASS'])
        self.assertEqual(result[0]['error']['type'], 'RuntimeError')
