"""Hand-calculated checks for a deliberately artificial execution environment."""

import importlib
import unittest
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone

from evcf.integration.charging_types import ChargeAction, DeliveredEnergy, EnergySnapshot
from evcf.integration.controller_common import AdmissionError

try:
    plant_module = importlib.import_module('evcf.integration.charging_plant')
except ModuleNotFoundError:
    plant_module = None


ISSUE = datetime(2026, 11, 6, tzinfo=timezone.utc)


def at(minutes):
    return ISSUE + timedelta(minutes=minutes)


class ChargingPlantTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(plant_module, 'Synthetic charging plant is not implemented')

    def session(self, session_id='A', device_id='D1', arrival=0, departure=30,
                required=1, limit=6):
        return plant_module.TruthSession(
            session_id, device_id, at(arrival), at(departure), required, limit
        )

    def plant(self, sessions=None, capacity=6):
        return plant_module.SyntheticPlant(
            (self.session(),) if sessions is None else sessions,
            start_utc=ISSUE, capacity_kw=capacity
        )

    def action(self, session_id='A', device_id='D1', start=0, end=15, power=6):
        return ChargeAction(session_id, device_id, at(start), at(end), power)

    def test_delivery_is_actual_connection_overlap_in_kwh(self):
        plant = self.plant((self.session(arrival=5, departure=10, required=10),))
        result = plant.execute((self.action(),), issue_time_utc=ISSUE)
        self.assertEqual((result.start_utc, result.end_utc), (ISSUE, at(15)))
        self.assertEqual(result.commanded_kw, 6)
        self.assertEqual(result.delivered_kwh, 0.5)
        self.assertEqual(result.increments, (DeliveredEnergy('A', 'D1', 0.5),))
        self.assertEqual(plant.feedback(('A',), issue_time_utc=at(15)),
                         EnergySnapshot(at(15), result.increments))

    def test_required_target_does_not_cap_delivery(self):
        results = []
        for required in (0, 0.1, 10):
            plant = self.plant((self.session(required=required, departure=15),))
            results.append(plant.execute((self.action(),), issue_time_utc=ISSUE))
            evaluation = plant.evaluate()
            self.assertTrue(evaluation.complete)
            self.assertEqual(evaluation.delivered_kwh, 1.5)
            self.assertEqual(evaluation.shortfall_kwh, max(required - 1.5, 0))
            self.assertEqual(evaluation.overdelivery_kwh, max(1.5 - required, 0))
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])

    def test_stale_command_after_departure_delivers_zero(self):
        plant = self.plant((self.session(departure=10, required=3),))
        first = plant.execute((self.action(),), issue_time_utc=ISSUE)
        second = plant.execute((self.action(start=15, end=30),), issue_time_utc=at(15))
        self.assertEqual((first.delivered_kwh, second.delivered_kwh), (1, 0))
        self.assertEqual(second.commanded_kw, 6)
        self.assertEqual(second.increments, (DeliveredEnergy('A', 'D1', 0),))
        self.assertEqual(plant.evaluate().shortfall_kwh, 2)

    def test_feedback_reveals_only_requested_realized_cumulative_energy(self):
        plant = self.plant((self.session(), self.session('B', 'D2', required=20)))
        self.assertEqual(plant.feedback(('A',), issue_time_utc=ISSUE),
                         EnergySnapshot(ISSUE, (DeliveredEnergy('A', 'D1', 0),)))
        self.assertEqual(plant.feedback((), issue_time_utc=ISSUE).entries, ())
        plant.execute((self.action(),), issue_time_utc=ISSUE)
        plant.execute((self.action(start=15, end=30, power=2),), issue_time_utc=at(15))
        snapshot = plant.feedback(('B', 'A'), issue_time_utc=at(30))
        self.assertEqual(snapshot.entries,
                         (DeliveredEnergy('B', 'D2', 0), DeliveredEnergy('A', 'D1', 2)))
        self.assertEqual(tuple(field.name for field in fields(snapshot)),
                         ('as_of_utc', 'entries'))
        self.assertEqual(tuple(field.name for field in fields(snapshot.entries[0])),
                         ('session_id', 'device_id', 'energy_kwh'))

    def test_pending_evaluation_is_current_deficit_not_final_failure(self):
        plant = self.plant((self.session(required=2, departure=30),))
        initial = plant.evaluate()
        self.assertFalse(initial.complete)
        self.assertFalse(initial.sessions[0].departed)
        self.assertEqual(initial.shortfall_kwh, 2)
        plant.execute((self.action(power=4),), issue_time_utc=ISSUE)
        midway = plant.evaluate()
        self.assertFalse(midway.complete)
        self.assertEqual(midway.sessions[0],
                         plant_module.SessionEvaluation('A', False, 2, 1, 1, 0))
        plant.execute((self.action(start=15, end=30, power=4),), issue_time_utc=at(15))
        final = plant.evaluate()
        self.assertTrue(final.complete)
        self.assertTrue(final.sessions[0].departed)
        self.assertEqual((final.delivered_kwh, final.shortfall_kwh), (2, 0))
        self.assertEqual(initial.delivered_kwh, 0)

    def test_evaluation_aggregates_shortfalls_without_canceling_overdelivery(self):
        plant = self.plant((self.session(required=0.5, departure=15),
                            self.session('B', 'D2', required=2, departure=15)))
        plant.execute((self.action(),), issue_time_utc=ISSUE)
        evaluation = plant.evaluate()
        self.assertEqual((evaluation.delivered_kwh, evaluation.shortfall_kwh,
                          evaluation.overdelivery_kwh), (1.5, 2, 1))

    def test_empty_batch_advances_once_and_empty_plant_is_complete(self):
        plant = self.plant(())
        self.assertTrue(plant.evaluate().complete)
        result = plant.execute((), issue_time_utc=ISSUE)
        self.assertEqual((result.commanded_kw, result.delivered_kwh, result.increments),
                         (0, 0, ()))
        self.assertEqual(plant.feedback((), issue_time_utc=at(15)), EnergySnapshot(at(15), ()))
        with self.assertRaises(AdmissionError):
            plant.execute((), issue_time_utc=ISSUE)

    def test_truth_and_result_records_are_frozen(self):
        plant = self.plant()
        step = plant.execute((self.action(),), issue_time_utc=ISSUE)
        evaluation = plant.evaluate()
        for record, attribute in ((self.session(), 'required_energy_kwh'),
                                  (step, 'delivered_kwh'), (evaluation, 'complete'),
                                  (evaluation.sessions[0], 'required_kwh')):
            with self.subTest(record=type(record).__name__), self.assertRaises(FrozenInstanceError):
                setattr(record, attribute, None)

    def test_constructor_requires_tuple_of_exact_truth_records(self):
        for sessions in ([self.session()], (object(),), ('A',)):
            with self.subTest(sessions=sessions), self.assertRaises(AdmissionError):
                self.plant(sessions)

    def test_constructor_rejects_invalid_numbers(self):
        for invalid in (True, -1, float('nan'), float('inf'), -float('inf'), '6', 10**1000):
            for attribute in ('required_energy_kwh', 'max_power_kw'):
                with (self.subTest(value=repr(invalid), attribute=attribute),
                      self.assertRaises(AdmissionError)):
                    self.plant((replace(self.session(), **{attribute: invalid}),))
            with self.subTest(capacity=repr(invalid)), self.assertRaises(AdmissionError):
                self.plant(capacity=invalid)

    def test_constructor_rejects_invalid_identity_and_duplicate_session(self):
        for attribute in ('session_id', 'device_id'):
            for invalid in ('', ' A', 'A ', None, 1, True):
                with (self.subTest(attribute=attribute, invalid=invalid),
                      self.assertRaises(AdmissionError)):
                    self.plant((replace(self.session(), **{attribute: invalid}),))
        with self.assertRaises(AdmissionError):
            self.plant((self.session(), self.session(device_id='D2')))

    def test_constructor_rejects_non_utc_and_invalid_connection_ranges(self):
        for invalid in (ISSUE.replace(tzinfo=None), '2026-11-06T00:00:00Z',
                        ISSUE.astimezone(timezone(timedelta(hours=1)))):
            for attribute in ('arrival_utc', 'departure_utc'):
                with (self.subTest(attribute=attribute, invalid=invalid),
                      self.assertRaises(AdmissionError)):
                    self.plant((replace(self.session(), **{attribute: invalid}),))
            with self.subTest(start=invalid), self.assertRaises(AdmissionError):
                plant_module.SyntheticPlant((), start_utc=invalid, capacity_kw=1)
        for arrival, departure in ((-1, 10), (10, 10), (10, 5)):
            with (self.subTest(arrival=arrival, departure=departure),
                  self.assertRaises(AdmissionError)):
                self.plant((self.session(arrival=arrival, departure=departure),))

    def test_constructor_rejects_overlapping_device_use_but_accepts_adjacency(self):
        first = self.session(arrival=0, departure=15)
        for arrival in (0, 5, 14):
            with self.subTest(arrival=arrival), self.assertRaises(AdmissionError):
                self.plant((self.session('B', arrival=arrival, departure=30), first))
        plant = self.plant((self.session('B', arrival=15), first))
        plant.execute((self.action(),), issue_time_utc=ISSUE)
        step = plant.execute((self.action('B', start=15, end=30),), issue_time_utc=at(15))
        self.assertEqual(step.delivered_kwh, 1.5)

    def test_constructor_copies_truth_into_private_records(self):
        original = self.session()
        plant = self.plant((original,))
        # Frozen dataclasses resist ordinary changes. Even bypassing the original
        # carrier's protection must not alter the admitted private plant state.
        object.__setattr__(original, 'departure_utc', at(1))
        object.__setattr__(original, 'required_energy_kwh', 99)
        self.assertEqual(plant.execute((self.action(),), issue_time_utc=ISSUE).delivered_kwh,
                         1.5)
        self.assertEqual(plant.evaluate().sessions[0].required_kwh, 1)

    def test_feedback_rejects_unknown_future_duplicate_or_invalid_ids(self):
        plant = self.plant((self.session(), self.session('B', 'D2', arrival=15)))
        for ids in (('B',), ('missing',), ('A', 'A'), ('',), (True,), ['A'], 'A'):
            with self.subTest(ids=ids), self.assertRaises(AdmissionError):
                plant.feedback(ids, issue_time_utc=ISSUE)
        self.assertEqual(plant.feedback(('A',), issue_time_utc=ISSUE).entries[0].energy_kwh, 0)
        plant.execute((), issue_time_utc=ISSUE)
        self.assertEqual(plant.feedback(('B',), issue_time_utc=at(15)).entries[0].energy_kwh, 0)

    def test_feedback_and_execution_require_exact_cursor(self):
        plant = self.plant()
        for wrong_issue in (at(-15), at(15), ISSUE.replace(tzinfo=None), 'now'):
            for method, argument in ((plant.feedback, ('A',)), (plant.execute, ())):
                with (self.subTest(issue=wrong_issue, method=method.__name__),
                      self.assertRaises(AdmissionError)):
                    method(argument, issue_time_utc=wrong_issue)
        plant.execute((), issue_time_utc=ISSUE)
        with self.assertRaises(AdmissionError):
            plant.feedback(('A',), issue_time_utc=ISSUE)

    def test_rejected_action_batches_are_atomic_and_valid_retry_executes_once(self):
        sessions = (self.session(), self.session('B', 'D2'))
        good = self.action(power=2)
        b = self.action('B', 'D2', power=2)
        invalid_batches = (
            (good, replace(b, power_kw=7)),
            (good, replace(b, power_kw=5)),
            (good, replace(b, device_id='D1')),
            (good, replace(b, session_id='unknown')),
            (good, replace(good, power_kw=1)),
            (good, replace(b, start_utc=at(1))),
            (good, replace(b, end_utc=at(30))),
            (good, replace(b, end_utc=ISSUE)),
            (good, replace(b, start_utc=ISSUE.replace(tzinfo=None))),
            (good, object()),
            [good, b],
        )
        for batch in invalid_batches:
            with self.subTest(batch=batch):
                plant = self.plant(sessions)
                before = plant.feedback(('A', 'B'), issue_time_utc=ISSUE)
                with self.assertRaises(AdmissionError):
                    plant.execute(batch, issue_time_utc=ISSUE)
                self.assertEqual(plant.feedback(('A', 'B'), issue_time_utc=ISSUE), before)
                result = plant.execute((good, b), issue_time_utc=ISSUE)
                self.assertEqual(result.delivered_kwh, 1)
                with self.assertRaises(AdmissionError):
                    plant.execute((good, b), issue_time_utc=ISSUE)

    def test_execute_rejects_invalid_power_and_accepts_explicit_zero(self):
        plant = self.plant()
        for power in (True, -1, float('nan'), float('inf'), '6', 10**1000):
            with self.subTest(power=repr(power)), self.assertRaises(AdmissionError):
                plant.execute((self.action(power=power),), issue_time_utc=ISSUE)
            self.assertEqual(plant.feedback(('A',), issue_time_utc=ISSUE).entries[0].energy_kwh,
                             0)
        result = plant.execute((self.action(power=0),), issue_time_utc=ISSUE)
        self.assertEqual((result.commanded_kw, result.delivered_kwh), (0, 0))

    def test_same_device_cannot_receive_two_commands_even_for_adjoining_sessions(self):
        plant = self.plant((self.session(departure=5), self.session('B', arrival=5)))
        with self.assertRaises(AdmissionError):
            plant.execute((self.action(power=2), self.action('B', power=2)),
                          issue_time_utc=ISSUE)

    def test_invalid_step_leaves_cursor_unchanged(self):
        plant = self.plant()
        for step in (True, 0, -1, 1.5, 10**1000):
            with self.subTest(step=repr(step)), self.assertRaises(AdmissionError):
                plant.execute((), issue_time_utc=ISSUE, step_seconds=step)
        self.assertEqual(plant.feedback(('A',), issue_time_utc=ISSUE).entries[0].energy_kwh, 0)

    def test_nonfinite_increment_is_rejected_before_any_mutation(self):
        plant = self.plant((self.session(departure=180, limit=1e308),), capacity=1e308)
        with self.assertRaises(AdmissionError):
            plant.execute((self.action(end=120, power=1e308),),
                          issue_time_utc=ISSUE, step_seconds=7200)
        self.assertEqual(plant.feedback(('A',), issue_time_utc=ISSUE).entries[0].energy_kwh, 0)
        result = plant.execute((self.action(power=1e308),), issue_time_utc=ISSUE)
        self.assertEqual(result.delivered_kwh, 2.5e307)

    def test_nonfinite_cumulative_total_is_rejected_transactionally(self):
        plant = self.plant((self.session(departure=180, limit=1e308),), capacity=1e308)
        plant.execute((self.action(end=60, power=1e308),),
                      issue_time_utc=ISSUE, step_seconds=3600)
        before = plant.feedback(('A',), issue_time_utc=at(60))
        with self.assertRaises(AdmissionError):
            plant.execute((self.action(start=60, end=120, power=1e308),),
                          issue_time_utc=at(60), step_seconds=3600)
        self.assertEqual(plant.feedback(('A',), issue_time_utc=at(60)), before)

    def test_nonfinite_aggregate_energy_is_rejected_transactionally(self):
        sessions = (self.session(departure=180, limit=1e308),
                    self.session('B', 'D2', departure=180, limit=1e308))
        plant = self.plant(sessions, capacity=1e308)
        plant.execute((self.action(end=60, power=1e308),),
                      issue_time_utc=ISSUE, step_seconds=3600)
        before = plant.feedback(('A', 'B'), issue_time_utc=at(60))
        with self.assertRaises(AdmissionError):
            plant.execute((self.action('B', 'D2', start=60, end=120, power=1e308),),
                          issue_time_utc=at(60), step_seconds=3600)
        self.assertEqual(plant.feedback(('A', 'B'), issue_time_utc=at(60)), before)

    def test_nonfinite_aggregate_targets_cannot_create_nonfinite_evaluations(self):
        with self.assertRaises(AdmissionError):
            self.plant((self.session(required=1e308), self.session('B', 'D2', required=1e308)))


if __name__ == '__main__':
    unittest.main()
