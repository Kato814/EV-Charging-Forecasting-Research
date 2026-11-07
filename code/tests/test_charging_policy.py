"""Hand-authored policy cases, independent of plant truth and integration fixtures."""
import importlib
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from math import fsum, nextafter

from evcf.integration.charging_types import DeliveredEnergy, EnergySnapshot
from evcf.integration.controller_adapter import ControllerInput, MappedSession
from evcf.integration.controller_common import AdmissionError
from evcf.integration.controller_quantities import DeviceMapping
from evcf.integration.controller_visibility import Declaration, SessionState

try:
    policy = importlib.import_module('evcf.integration.charging_policy')
except ModuleNotFoundError as exc:
    if exc.name != 'evcf.integration.charging_policy':
        raise
    policy = None

START = datetime(2026, 11, 6, tzinfo=timezone.utc)


def session(sid='A', *, requested=2.0, due_minutes=30, basis='total', baseline=None):
    """A completely explicit artificial visible record, with no hidden truth."""
    device = f'device-{sid}'
    declaration = Declaration(requested, basis, START + timedelta(minutes=due_minutes),
                              baseline, 0, START, START, 'recorded_reception')
    state = SessionState(sid, device, None, None, declaration, START, START,
                         0.0, False, 'recorded_reception')
    mapping = DeviceMapping('site', 'cluster', device, f'space-{sid}', 'topology',
                            'node', START, None, START, 'synthetic-map',
                            'synthetic_assumption')
    return MappedSession(state, mapping, 'DECLARED_ONLY')


def view(*sessions, issue=START):
    return ControllerInput(issue, 'recorded_reception', tuple(sessions))


def feedback(*entries, issue=START):
    return EnergySnapshot(issue, tuple(DeliveredEnergy(sid, f'device-{sid}', energy)
                                       for sid, energy in entries))


def with_declaration(item, **changes):
    return replace(item, state=replace(item.state,
                                      declaration=replace(item.state.declaration, **changes)))


class ChargingPolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(policy, 'Artificial EDF charging policy is not implemented')

    def dispatch(self, visible=None, measured=None, **changes):
        visible = view(session()) if visible is None else visible
        measured = feedback(('A', 0)) if measured is None else measured
        options = {'site_id': 'site', 'cluster_id': 'cluster',
                       'device_limits_kw': {'device-A': 4, 'device-B': 4}, 'capacity_kw': 4}
        options.update(changes)
        return policy.dispatch_edf(visible, measured, **options)

    def test_two_step_hand_calculation_recomputes_from_actual_feedback(self):
        a = session('A', requested=0.5, due_minutes=15)
        b = session('B', requested=1.5, due_minutes=30)
        first = self.dispatch(view(b, a), feedback(('B', 0), ('A', 0)))
        self.assertEqual([(a.session_id, a.power_kw) for a in first.actions],
                         [('A', 2), ('B', 2)])
        self.assertEqual(first.remaining_kwh, (('A', 0.5), ('B', 1.5)))
        issue = START + timedelta(minutes=15)
        later = tuple(replace(s, state=replace(s.state, state_age_seconds=900)) for s in (a, b))
        second = self.dispatch(view(*later, issue=issue),
                               feedback(('A', 0.5), ('B', 0.5), issue=issue))
        self.assertEqual([(a.session_id, a.power_kw) for a in second.actions], [('B', 4)])
        self.assertEqual(second.remaining_kwh, (('B', 1.0),))

    def test_equal_departure_uses_session_id_not_input_order(self):
        result = self.dispatch(view(session('B'), session('A')), feedback(('B', 0), ('A', 0)))
        self.assertEqual([(a.session_id, a.power_kw) for a in result.actions], [('A', 4)])
        self.assertEqual(result.remaining_kwh, (('A', 2.0), ('B', 2.0)))

    def test_actions_span_full_step_and_results_are_frozen(self):
        result = self.dispatch()
        self.assertEqual(result.issue_time_utc, START)
        action = result.actions[0]
        self.assertEqual((action.start_utc, action.end_utc),
                         (START, START + timedelta(seconds=900)))
        with self.assertRaises(FrozenInstanceError):
            result.actions = ()
        with self.assertRaises(FrozenInstanceError):
            action.power_kw = 900

    def test_total_and_additional_requests_keep_distinct_semantics(self):
        cases = [('total', None, 0.0), ('additional', 2.0, 0.5)]
        for basis, baseline, expected in cases:
            with self.subTest(basis=basis):
                result = self.dispatch(view(session(requested=2, basis=basis, baseline=baseline)),
                                       feedback(('A', 3.5)))
                self.assertEqual(result.remaining_kwh, (('A', expected),))
                self.assertEqual(sum(a.power_kw for a in result.actions), expected * 4)

    def test_missing_feedback_blocks_only_that_session(self):
        result = self.dispatch(view(session('A'), session('B')), feedback(('B', 0)))
        self.assertEqual(result.blocked, (('A', 'UNKNOWN_DELIVERED_ENERGY'),))
        self.assertEqual([a.session_id for a in result.actions], ['B'])
        self.assertEqual(result.remaining_kwh, (('B', 2.0),))

    def test_missing_device_limit_is_explicitly_blocked(self):
        result = self.dispatch(device_limits_kw={})
        self.assertEqual(result.actions, ())
        self.assertEqual(result.blocked, (('A', 'UNKNOWN_DEVICE_LIMIT'),))

    def test_unknown_missing_expired_and_unaligned_declarations_are_blocked(self):
        cases = [(None, 'MISSING_DECLARATION'),
                 ({'request_basis': 'unknown'}, 'UNKNOWN_REQUEST_BASIS'),
                 ({'request_basis': 'additional'}, 'UNKNOWN_REQUEST_BASELINE'),
                 ({'departure_time_utc': None}, 'MISSING_DEPARTURE'),
                 ({'departure_time_utc': START}, 'EXPIRED_DEPARTURE'),
                 ({'departure_time_utc': START + timedelta(minutes=29)}, 'UNALIGNED_DEPARTURE')]
        for changes, expected in cases:
            with self.subTest(expected=expected):
                s = session()
                s = (replace(s, state=replace(s.state, declaration=None)) if changes is None
                     else with_declaration(s, **changes))
                result = self.dispatch(view(s))
                self.assertEqual(result.blocked, (('A', expected),))
                self.assertEqual(result.actions, ())

    def test_invalid_declaration_cannot_rely_on_claimed_declared_status(self):
        invalid = [{'energy_kwh': -1}, {'energy_kwh': float('inf')},
                   {'energy_kwh': float('nan')}, {'energy_kwh': True},
                   {'request_basis': 'guess'}, {'revision': True},
                   {'revision': -1}, {'availability_basis': 'unknown'},
                   {'departure_time_utc': START.replace(tzinfo=None)},
                   {'event_time_utc': START + timedelta(seconds=1)},
                   {'available_at_utc': START + timedelta(seconds=1)},
                   {'request_basis': 'additional', 'delivered_at_revision_kwh': 1},
                   {'delivered_at_revision_kwh': True}]
        for changes in invalid:
            with self.subTest(changes=changes):
                result = self.dispatch(view(with_declaration(session(), **changes)))
                self.assertEqual(result.blocked, (('A', 'INVALID_DECLARATION'),))
                self.assertEqual(result.actions, ())
        malformed = replace(session(), state=replace(session().state, declaration={}))
        self.assertEqual(self.dispatch(view(malformed)).blocked,
                         (('A', 'INVALID_DECLARATION'),))

    def test_stale_state_still_dispatches_and_is_reported(self):
        issue = START + timedelta(minutes=15)
        s = session(due_minutes=45)
        s = replace(s, state=replace(s.state, state_age_seconds=900, stale=True))
        result = self.dispatch(view(s, issue=issue), feedback(('A', 0), issue=issue))
        self.assertEqual(result.stale_sessions, ('A',))
        self.assertEqual(result.actions[0].power_kw, 4)

    def test_no_telemetry_is_inferred_as_a_device_power_limit(self):
        s = session()
        s = replace(s, state=replace(s.state, current_a=0.0, pilot_a=0.0))
        self.assertEqual(self.dispatch(view(s)).actions[0].power_kw, 4)

    def test_zero_energy_capacity_and_device_limits_make_no_zero_actions(self):
        for visible, changes in [(view(session(requested=0)), {}),
                                 (view(session()), {'capacity_kw': 0}),
                                 (view(session()), {'device_limits_kw': {'device-A': 0}})]:
            with self.subTest(changes=changes):
                result = self.dispatch(visible, **changes)
                self.assertEqual(result.actions, ())
                self.assertEqual(result.blocked, ())

    def test_nondefault_step_uses_duration_and_relative_departure_grid(self):
        result = self.dispatch(view(session(requested=0.25, due_minutes=30)), step_seconds=300)
        self.assertEqual(result.actions[0].power_kw, 3)
        self.assertEqual(result.actions[0].end_utc, START + timedelta(seconds=300))
        shifted = START + timedelta(seconds=1)
        s = session()
        declaration = replace(s.state.declaration, departure_time_utc=shifted + timedelta(minutes=30))
        s = replace(s, state=replace(s.state, state_age_seconds=1, declaration=declaration))
        self.assertEqual(len(self.dispatch(view(s, issue=shifted),
                                           feedback(('A', 0), issue=shifted)).actions), 1)

    def test_huge_finite_request_does_not_create_infinite_action(self):
        result = self.dispatch(view(session(requested=1e308)), capacity_kw=1e308,
                               device_limits_kw={'device-A': 7}, step_seconds=1)
        self.assertEqual(result.actions[0].power_kw, 7)
        self.assertEqual(result.remaining_kwh, (('A', 1e308),))

    def test_six_decimal_device_limits_fit_accurately_summed_capacity(self):
        names = tuple(f'S{i}' for i in range(6))
        result = self.dispatch(
            view(*(session(name) for name in names)),
            feedback(*((name, 0) for name in names)), capacity_kw=0.6,
            device_limits_kw={f'device-{name}': 0.1 for name in names},
        )
        powers = [action.power_kw for action in result.actions]
        self.assertLessEqual(fsum(powers), 0.6)
        self.assertEqual(powers[:5], [0.1] * 5)
        self.assertEqual(powers[-1], 0.09999999999999995)

    def test_many_decimal_actions_cannot_spend_rounding_residue(self):
        names = tuple(f'S{i:04d}' for i in range(2000))
        result = self.dispatch(
            view(*(session(name) for name in names)),
            feedback(*((name, 0) for name in names)), capacity_kw=1.0,
            device_limits_kw={f'device-{name}': 0.1 if i < 10 else 1e-20
                              for i, name in enumerate(names)},
        )
        powers = [action.power_kw for action in result.actions]
        self.assertLessEqual(sum(map(Fraction.from_float, powers)), Fraction(1))
        self.assertEqual(len(powers), 10)
        self.assertEqual(powers[:9], [0.1] * 9)
        self.assertLessEqual(fsum(powers), 1.0)

    def test_fractional_capacity_handles_large_and_subnormal_finite_values(self):
        for capacity, limits in [(1e308, [1e307] * 12),
                                 (1.0, [0.1, 0.2, 0.7, 1e-30]),
                                 (1.0, [nextafter(1.0, 0.0), 1.0]),
                                 (nextafter(0.0, 1.0), [1.0, 1.0]),
                                 (0.0, [0.1, 0.1])]:
            with self.subTest(capacity=capacity, limits=limits):
                names = tuple(f'S{i:04d}' for i in range(len(limits)))
                result = self.dispatch(
                    view(*(session(name, requested=1e308) for name in names)),
                    feedback(*((name, 0) for name in names)), capacity_kw=capacity,
                    device_limits_kw={f'device-{name}': limit
                                      for name, limit in zip(names, limits)},
                )
                powers = [action.power_kw for action in result.actions]
                self.assertLessEqual(fsum(powers), capacity)
                self.assertLessEqual(sum(map(Fraction.from_float, powers)),
                                     Fraction.from_float(capacity))
                for action in result.actions:
                    self.assertGreater(action.power_kw, 0)

    def test_empty_view_requires_empty_feedback(self):
        result = self.dispatch(view(), feedback())
        self.assertEqual((result.actions, result.blocked, result.remaining_kwh), ((), (), ()))
        with self.assertRaises(AdmissionError):
            self.dispatch(view(), feedback(('A', 0)))

    def test_feedback_requires_exact_issue_including_no_delayed_energy(self):
        for issue in [START - timedelta(seconds=1), START + timedelta(seconds=1),
                      START.replace(tzinfo=None), START.isoformat()]:
            with self.subTest(issue=issue), self.assertRaises(AdmissionError):
                self.dispatch(measured=feedback(('A', 0), issue=issue))

    def test_feedback_rejects_duplicate_extra_and_wrong_device(self):
        invalid = [feedback(('A', 0), ('A', 0)), feedback(('A', 0), ('hidden', 0)),
                   EnergySnapshot(START, (DeliveredEnergy('A', 'wrong-device', 0),))]
        for snapshot in invalid:
            with self.subTest(snapshot=snapshot), self.assertRaises(AdmissionError):
                self.dispatch(measured=snapshot)

    def test_nonfinite_negative_and_boolean_feedback_are_rejected(self):
        for energy in [-1, True, float('nan'), float('inf'), '0', 10**400]:
            with self.subTest(energy=energy), self.assertRaises(AdmissionError):
                self.dispatch(measured=feedback(('A', energy)))

    def test_budget_requires_finite_nonnegative_numbers_and_clean_ids(self):
        invalid = [-1, True, float('nan'), float('inf'), '4', 10**400]
        for value in invalid:
            for field in ['capacity_kw', 'device_limits_kw']:
                changes = {field: value if field == 'capacity_kw' else {'device-A': value}}
                with self.subTest(changes=changes), self.assertRaises(AdmissionError):
                    self.dispatch(**changes)
        for changes in [{'site_id': ''}, {'cluster_id': ' cluster'},
                        {'device_limits_kw': {'': 4}}, {'device_limits_kw': [4]}]:
            with self.subTest(changes=changes), self.assertRaises(AdmissionError):
                self.dispatch(**changes)

    def test_every_device_limit_is_validated_even_if_device_is_not_visible(self):
        with self.assertRaises(AdmissionError):
            self.dispatch(device_limits_kw={'device-A': 4, 'unused': float('nan')})

    def test_visible_sessions_cannot_cross_site_or_cluster_budget(self):
        for changes in [{'site_id': 'other'}, {'cluster_id': 'other'}]:
            s = replace(session(), mapping=replace(session().mapping, **changes))
            with self.subTest(changes=changes), self.assertRaises(AdmissionError):
                self.dispatch(view(s))

    def test_visible_duplicate_session_or_device_is_rejected(self):
        a = session()
        b = session('B')
        b = replace(b, state=replace(b.state, device_id=a.state.device_id),
                    mapping=replace(b.mapping, station_id=a.state.device_id))
        for visible in [view(a, a), view(a, b)]:
            with self.subTest(visible=visible), self.assertRaises(AdmissionError):
                self.dispatch(visible)

    def test_visible_mapping_identity_validity_and_evidence_are_validated(self):
        for changes in [{'station_id': 'wrong'}, {'space_id': ''}, {'node_id': ''},
                        {'evidence_id': ''}, {'mapping_basis': 'measured'},
                        {'valid_from_utc': START + timedelta(seconds=1)},
                        {'valid_to_utc': START},
                        {'available_at_utc': START + timedelta(seconds=1)},
                        {'valid_from_utc': START.replace(tzinfo=None)}]:
            s = replace(session(), mapping=replace(session().mapping, **changes))
            with self.subTest(changes=changes), self.assertRaises(AdmissionError):
                self.dispatch(view(s))

    def test_visible_state_clocks_ids_age_and_optional_telemetry_are_validated(self):
        for changes in [{'session_id': ''}, {'device_id': ' '}, {'current_a': True},
                        {'pilot_a': -1}, {'state_age_seconds': 1}, {'stale': 'yes'},
                        {'availability_basis': 'unknown'},
                        {'last_event_time_utc': START + timedelta(seconds=1)},
                        {'last_available_at_utc': START + timedelta(seconds=1)},
                        {'last_available_at_utc': START - timedelta(seconds=1)},
                        {'last_event_time_utc': START.replace(tzinfo=None)}]:
            s = replace(session(), state=replace(session().state, **changes))
            with self.subTest(changes=changes), self.assertRaises(AdmissionError):
                self.dispatch(view(s))

    def test_exact_container_types_are_required(self):
        class DerivedInput(ControllerInput):
            pass

        invalid_views = [{}, DerivedInput(START, 'recorded_reception', (session(),)),
                         replace(view(session()), sessions=[session()]),
                         replace(view(session()), availability_mode='unknown'),
                         view({}), view(replace(session(), state={})),
                         view(replace(session(), mapping={}))]
        for visible in invalid_views:
            with self.subTest(visible=visible), self.assertRaises(AdmissionError):
                self.dispatch(visible)
        for measured in [{}, EnergySnapshot(START, []), EnergySnapshot(START, ({},))]:
            with self.subTest(measured=measured), self.assertRaises(AdmissionError):
                self.dispatch(measured=measured)

    def test_synthetic_flags_cannot_be_tampered_into_real_dispatch(self):
        for field, value in [('synthetic_only', False), ('real_dispatch_authorized', True)]:
            visible = view(session())
            object.__setattr__(visible, field, value)
            with self.subTest(field=field), self.assertRaises(AdmissionError):
                self.dispatch(visible)

    def test_strict_issue_time_and_step_are_checked(self):
        for issue in [START.replace(tzinfo=None), START.isoformat(),
                      START.astimezone(timezone(timedelta(hours=8)))]:
            with self.subTest(issue=issue), self.assertRaises(AdmissionError):
                self.dispatch(view(session(), issue=issue))
        for step in [0, -1, True, 900.0, 10**400]:
            with self.subTest(step=step), self.assertRaises(AdmissionError):
                self.dispatch(step_seconds=step)
        with self.assertRaises(AdmissionError):
            self.dispatch(view(issue=datetime.max.replace(tzinfo=timezone.utc)), feedback())


if __name__ == '__main__':
    unittest.main()
