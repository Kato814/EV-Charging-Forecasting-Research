"""Synthetic-only examples for controller visibility and session state."""
import copy
import importlib
import itertools
import math
import unittest
from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone

from evcf.integration.controller_common import AdmissionError

try:
    visibility = importlib.import_module('evcf.integration.controller_visibility')
except ModuleNotFoundError as exc:
    if exc.name != 'evcf.integration.controller_visibility':
        raise
    visibility = None


ISSUE = '2026-11-06T00:20:00Z'


def event(event_id, kind, time='00:00:00', *, available=None,
          session='synthetic-session', device='synthetic-device', revision=0,
          basis='recorded_reception', payload=None):
    return {
        'event_id': event_id,
        'session_id': session,
        'device_id': device,
        'kind': kind,
        'event_time_utc': f'2026-11-06T{time}Z',
        'available_at_utc': f'2026-11-06T{available or time}Z',
        'availability_basis': basis,
        'evidence_id': 'synthetic-receipt',
        'revision': revision,
        'payload': {} if payload is None else payload,
    }


def request(energy=10, basis='total', departure='2026-11-06T01:00:00Z',
            delivered=None):
    return {'energy_kwh': energy, 'request_basis': basis,
            'departure_time_utc': departure,
            'delivered_at_revision_kwh': delivered}


class ControllerVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(visibility, 'Controller visibility is not implemented')

    def build(self, events, **kwargs):
        return visibility.build_visible_snapshot(events, ISSUE, **kwargs)

    def assert_rejected(self, events, code, **kwargs):
        with self.assertRaises(AdmissionError) as exc:
            self.build(events, **kwargs)
        self.assertEqual(exc.exception.code, code)

    def test_empty_snapshot_has_explicit_issue_time_and_mode(self):
        snapshot = self.build([])
        self.assertEqual(snapshot.sessions, ())
        self.assertEqual(snapshot.issue_time_utc,
                         datetime(2026, 11, 6, 0, 20, tzinfo=timezone.utc))
        self.assertEqual(snapshot.availability_mode, 'recorded_reception')

    def test_connect_keeps_absent_current_pilot_and_declaration_unknown(self):
        state, = self.build([event('c', 'connect')]).sessions
        self.assertEqual((state.session_id, state.device_id),
                         ('synthetic-session', 'synthetic-device'))
        self.assertIsNone(state.current_a)
        self.assertIsNone(state.pilot_a)
        self.assertIsNone(state.declaration)
        self.assertEqual(state.state_age_seconds, 1200)
        self.assertTrue(state.stale)
        self.assertEqual(state.availability_basis, 'recorded_reception')

    def test_future_event_is_skipped_without_reading_any_other_fields(self):
        connected = event('c', 'connect')
        baseline = self.build([connected])
        future = {'event_time_utc': '2026-11-06T00:21:00Z',
                  'payload': {'final_energy_kwh': math.nan}, 'unknown': object()}
        self.assertEqual(self.build([future, connected]), baseline)
        future['payload'] = None
        future['available_at_utc'] = None
        self.assertEqual(self.build([connected, future]), baseline)

    def test_unreceived_past_event_skips_payload_and_other_metadata(self):
        connected = event('c', 'connect')
        unavailable = {'event_time_utc': '2026-11-06T00:15:00Z',
                       'available_at_utc': '2026-11-06T00:21:00Z',
                       'payload': {'actual_departure': object()}}
        self.assertEqual(self.build([connected, unavailable]), self.build([connected]))

    def test_late_record_becomes_visible_only_after_reception(self):
        events = [event('c', 'connect'), event('a', 'current', '00:10:00',
                  available='00:20:01', payload={'value': 3, 'unit': 'A'})]
        self.assertIsNone(self.build(events).sessions[0].current_a)
        snapshot = visibility.build_visible_snapshot(events, '2026-11-06T00:20:01Z')
        self.assertEqual(snapshot.sessions[0].current_a, 3)
        self.assertEqual(snapshot.sessions[0].state_age_seconds, 601)

    def test_unknown_past_availability_fails_closed(self):
        for value in (None, 'unknown'):
            record = event('c', 'connect')
            record['available_at_utc'] = value
            self.assert_rejected([record], 'UNKNOWN_AVAILABILITY')
        record = event('c', 'connect')
        del record['available_at_utc']
        self.assert_rejected([record], 'UNKNOWN_AVAILABILITY')

    def test_available_before_event_is_invalid(self):
        self.assert_rejected([event('c', 'connect', '00:10:00',
                                   available='00:09:59')], 'INVALID_TIME')

    def test_replay_requires_explicit_mode_and_keeps_worst_provenance(self):
        events = [event('c', 'connect', basis='assumed_replay'),
                  event('a', 'current', '00:10:00', payload={'value': 3, 'unit': 'A'})]
        self.assert_rejected(events, 'UNKNOWN_AVAILABILITY')
        snapshot = self.build(events, availability_mode='assumed_replay')
        self.assertEqual(snapshot.availability_mode, 'assumed_replay')
        self.assertEqual(snapshot.sessions[0].availability_basis, 'assumed_replay')
        self.assertEqual(snapshot.sessions[0].current_a, 3)

    def test_replay_mode_remains_labeled_when_all_receipts_are_recorded(self):
        snapshot = self.build([event('c', 'connect')], availability_mode='assumed_replay')
        self.assertEqual(snapshot.availability_mode, 'assumed_replay')
        self.assertEqual(snapshot.sessions[0].availability_basis, 'recorded_reception')

    def test_unknown_availability_basis_is_not_promoted_to_recorded(self):
        for value in (None, '', 'unknown', True):
            self.assert_rejected([event('c', 'connect', basis=value)],
                                 'UNKNOWN_AVAILABILITY')

    def test_current_and_pilot_are_separate_and_low_current_is_valid(self):
        events = [event('c', 'connect'),
                  event('a', 'current', '00:15:00', payload={'value': 3, 'unit': 'A'}),
                  event('p', 'pilot', '00:16:00', payload={'value': 6, 'unit': 'A'})]
        state, = self.build(events).sessions
        self.assertEqual((state.current_a, state.pilot_a), (3.0, 6.0))
        self.assertEqual(state.state_age_seconds, 240)
        self.assertFalse(state.stale)

    def test_latest_event_time_then_revision_wins_independent_of_input_order(self):
        events = [event('c', 'connect'),
                  event('early', 'current', '00:10:00', revision=9,
                        payload={'value': 32, 'unit': 'A'}),
                  event('old', 'current', '00:15:00', revision=0,
                        payload={'value': 16, 'unit': 'A'}),
                  event('new', 'current', '00:15:00', revision=1,
                        payload={'value': 3, 'unit': 'A'})]
        expected = self.build(events)
        self.assertEqual(expected.sessions[0].current_a, 3)
        for ordered in itertools.permutations(events):
            self.assertEqual(self.build(list(ordered)), expected)

    def test_exact_duplicate_events_are_idempotent(self):
        connected = event('c', 'connect')
        current = event('a', 'current', '00:10:00', payload={'value': 3, 'unit': 'A'})
        self.assertEqual(self.build([connected, current, copy.deepcopy(current)]),
                         self.build([connected, current]))

    def test_conflicting_event_id_rejected_in_either_order(self):
        a = event('a', 'current', '00:10:00', payload={'value': 3, 'unit': 'A'})
        b = copy.deepcopy(a)
        b['payload']['value'] = 4
        for pair in ((a, b), (b, a)):
            self.assert_rejected([event('c', 'connect'), *pair], 'CONFLICTING_REVISION')

    def test_conflicting_revision_payload_rejected_with_different_event_ids(self):
        a = event('a', 'current', '00:10:00', payload={'value': 3, 'unit': 'A'})
        b = event('b', 'current', '00:10:00', payload={'value': 4, 'unit': 'A'})
        for pair in ((a, b), (b, a)):
            self.assert_rejected([event('c', 'connect'), *pair], 'CONFLICTING_REVISION')

    def test_conflicting_future_duplicate_does_not_change_visible_state(self):
        events = [event('c', 'connect'),
                  event('a', 'current', '00:10:00', payload={'value': 3, 'unit': 'A'})]
        future = event('a', 'current', '00:21:00', payload={'value': 99, 'unit': 'A'})
        self.assertEqual(self.build([*events, future]), self.build(events))

    def test_received_disconnect_closes_but_late_disconnect_cannot_be_known(self):
        events = [event('c', 'connect'),
                  event('d', 'disconnect', '00:15:00', available='00:21:00')]
        self.assertEqual(len(self.build(events).sessions), 1)
        self.assertEqual(visibility.build_visible_snapshot(
            events, '2026-11-06T00:21:00Z').sessions, ())

    def test_reconnect_requires_new_session_id_instead_of_reusing_old_observations(self):
        events = [event('c', 'connect'),
                  event('a', 'current', '00:01:00', payload={'value': 3, 'unit': 'A'}),
                  event('p', 'pilot', '00:02:00', payload={'value': 6, 'unit': 'A'}),
                  event('r', 'request', '00:03:00', payload=request()),
                  event('d', 'disconnect', '00:10:00'),
                  event('reconnect', 'connect', '00:15:00')]
        for ordered in (events, list(reversed(events))):
            self.assert_rejected(ordered, 'INVALID_EVENT_SEQUENCE')

    def test_overlapping_sessions_cannot_share_one_device(self):
        events = [event('c1', 'connect', session='first'),
                  event('c2', 'connect', '00:01:00', session='second'),
                  event('d1', 'disconnect', '00:10:00', session='first')]
        for ordered in itertools.permutations(events):
            self.assert_rejected(list(ordered), 'INVALID_EVENT_SEQUENCE')

    def test_connect_notifications_for_open_session_preserve_observations(self):
        connected = event('c', 'connect')
        events = [connected, copy.deepcopy(connected),
                  event('a', 'current', '00:01:00', payload={'value': 3, 'unit': 'A'}),
                  event('p', 'pilot', '00:02:00', payload={'value': 6, 'unit': 'A'}),
                  event('r', 'request', '00:03:00', payload=request()),
                  event('notification', 'connect', '00:15:00', revision=1)]
        state, = self.build(events).sessions
        self.assertEqual(state.current_a, 3)
        self.assertEqual(state.pilot_a, 6)
        self.assertEqual(state.declaration.energy_kwh, 10)

    def test_new_session_can_use_released_device_without_inheriting_observations(self):
        events = [event('c1', 'connect', session='first'),
                  event('a1', 'current', '00:01:00', session='first',
                        payload={'value': 3, 'unit': 'A'}),
                  event('d1', 'disconnect', '00:10:00', session='first'),
                  event('c2', 'connect', '00:15:00', session='second')]
        state, = self.build(events).sessions
        self.assertEqual(state.session_id, 'second')
        self.assertIsNone(state.current_a)
        self.assertIsNone(state.pilot_a)
        self.assertIsNone(state.declaration)

    def test_disconnect_without_known_connect_still_closes_session_identity(self):
        self.assert_rejected([event('d', 'disconnect'),
                              event('c', 'connect', '00:15:00')],
                             'INVALID_EVENT_SEQUENCE')

    def test_repeated_old_disconnect_cannot_release_another_sessions_device(self):
        events = [event('c1', 'connect', session='first'),
                  event('d1', 'disconnect', '00:05:00', session='first'),
                  event('c2', 'connect', '00:10:00', session='second'),
                  event('d1-repeat', 'disconnect', '00:15:00', session='first'),
                  event('c3', 'connect', '00:16:00', session='third')]
        self.assert_rejected(events, 'INVALID_EVENT_SEQUENCE')

    def test_telemetry_before_connect_and_after_disconnect_is_rejected(self):
        for kind in ('current', 'pilot'):
            before = event('a', kind, '00:00:00', payload={'value': 3, 'unit': 'A'})
            self.assert_rejected([before, event('c', 'connect', '00:01:00')],
                                 'INVALID_EVENT_SEQUENCE')
            after = event('a', kind, '00:11:00', payload={'value': 3, 'unit': 'A'})
            self.assert_rejected([event('c', 'connect'),
                                  event('d', 'disconnect', '00:10:00'), after],
                                 'INVALID_EVENT_SEQUENCE')

    def test_request_before_connect_is_retained_without_inventing_connection(self):
        declaration = event('r', 'request', payload=request())
        self.assertEqual(self.build([declaration]).sessions, ())
        state, = self.build([declaration, event('c', 'connect', '00:01:00')]).sessions
        self.assertEqual(state.declaration.energy_kwh, 10)
        self.assertEqual(state.declaration.request_basis, 'total')
        self.assertEqual(state.declaration.departure_time_utc,
                         datetime(2026, 11, 6, 1, tzinfo=timezone.utc))
        self.assertIsNone(state.declaration.delivered_at_revision_kwh)

    def test_declaration_selection_and_availability_metadata(self):
        events = [event('c', 'connect'),
                  event('r0', 'request', '00:10:00', payload=request()),
                  event('r1', 'request', '00:10:00', available='00:19:00', revision=1,
                        basis='assumed_replay', payload=request(5, 'additional', None, 2))]
        expected = self.build(events, availability_mode='assumed_replay')
        for ordered in itertools.permutations(events):
            self.assertEqual(self.build(list(ordered), availability_mode='assumed_replay'),
                             expected)
        declaration = expected.sessions[0].declaration
        self.assertEqual(declaration.energy_kwh, 5)
        self.assertEqual(declaration.request_basis, 'additional')
        self.assertIsNone(declaration.departure_time_utc)
        self.assertEqual(declaration.delivered_at_revision_kwh, 2)
        self.assertEqual(declaration.revision, 1)
        self.assertEqual(declaration.event_time_utc,
                         datetime(2026, 11, 6, 0, 10, tzinfo=timezone.utc))
        self.assertEqual(declaration.available_at_utc,
                         datetime(2026, 11, 6, 0, 19, tzinfo=timezone.utc))
        self.assertEqual(declaration.availability_basis, 'assumed_replay')

    def test_unknown_request_basis_is_explicit_and_not_assumed_total(self):
        state, = self.build([event('c', 'connect'), event('r', 'request',
            '00:10:00', payload=request(5, 'unknown', None))]).sessions
        self.assertEqual(state.declaration.request_basis, 'unknown')

    def test_last_event_and_latest_receipt_track_distinct_clocks(self):
        events = [event('c', 'connect'),
                  event('r', 'request', '00:01:00', available='00:19:00', payload=request()),
                  event('a', 'current', '00:10:00', payload={'value': 3, 'unit': 'A'})]
        state, = self.build(events).sessions
        self.assertEqual(state.last_event_time_utc,
                         datetime(2026, 11, 6, 0, 10, tzinfo=timezone.utc))
        self.assertEqual(state.last_available_at_utc,
                         datetime(2026, 11, 6, 0, 19, tzinfo=timezone.utc))
        self.assertEqual(state.state_age_seconds, 600)

    def test_staleness_is_strictly_older_than_configured_threshold(self):
        events = [event('c', 'connect', '00:05:00')]
        self.assertFalse(self.build(events).sessions[0].stale)
        self.assertTrue(self.build(events, stale_after_seconds=899).sessions[0].stale)
        self.assertFalse(self.build(events, stale_after_seconds=901).sessions[0].stale)

    def test_session_device_binding_cannot_change(self):
        self.assert_rejected([event('r', 'request', payload=request()),
                              event('c', 'connect', '00:01:00', device='other-device')],
                             'INVALID_EVENT_SEQUENCE')

    def test_sessions_are_sorted_and_same_time_connect_opens_for_telemetry(self):
        events = [event('b', 'connect', session='b', device='b-device'),
                  event('a', 'connect', session='a', device='a-device'),
                  event('current', 'current', session='a', device='a-device',
                        payload={'value': 3, 'unit': 'A'})]
        for ordered in itertools.permutations(events):
            snapshot = self.build(list(ordered))
            self.assertEqual(tuple(s.session_id for s in snapshot.sessions), ('a', 'b'))
            self.assertEqual(snapshot.sessions[0].current_a, 3)

    def test_output_is_frozen_and_does_not_alias_input(self):
        events = [event('c', 'connect'), event('r', 'request', '00:10:00', payload=request())]
        snapshot = self.build(events)
        state, = snapshot.sessions
        declaration = state.declaration
        with self.assertRaises(FrozenInstanceError):
            snapshot.availability_mode = 'assumed_replay'
        with self.assertRaises(FrozenInstanceError):
            state.current_a = 99
        with self.assertRaises(FrozenInstanceError):
            declaration.energy_kwh = 99
        events[1]['payload']['energy_kwh'] = 99
        events.clear()
        self.assertEqual(declaration.energy_kwh, 10)
        self.assertEqual({field.name for field in fields(snapshot)},
                         {'issue_time_utc', 'availability_mode', 'sessions'})
        self.assertNotIn('actual_departure', {field.name for field in fields(state)})
        self.assertNotIn('final_energy_kwh', {field.name for field in fields(state)})

    def test_eligible_unknown_or_oracle_keys_are_rejected(self):
        for kind, payload in (('connect', {'final_energy_kwh': 10}),
                              ('disconnect', {'actual_departure': ISSUE}),
                              ('current', {'value': 3, 'unit': 'A', 'oracle': 1}),
                              ('request', {**request(), 'final_energy_kwh': 10})):
            self.assert_rejected([event('c', 'connect'),
                                  event('x', kind, '00:10:00', payload=payload)],
                                 'INVALID_SCHEMA')
        record = event('c', 'connect')
        record['actual_departure'] = ISSUE
        self.assert_rejected([record], 'INVALID_SCHEMA')

    def test_invalid_times_are_rejected_before_future_or_payload_handling(self):
        for invalid in (None, True, 'bad', '2026-11-06T00:00:00',
                        '2026-11-06T08:00:00+08:00'):
            record = event('c', 'connect')
            record['event_time_utc'] = invalid
            self.assert_rejected([record], 'INVALID_TIME')
            with self.assertRaises(AdmissionError) as exc:
                visibility.build_visible_snapshot([], invalid)
            self.assertEqual(exc.exception.code, 'INVALID_TIME')
        record = event('c', 'connect')
        record['available_at_utc'] = 'not-a-time'
        self.assert_rejected([record], 'INVALID_TIME')

    def test_telemetry_and_declaration_quantities_reject_invalid_numbers(self):
        for value in (True, None, '3', -1, math.nan, math.inf, 10**400):
            for kind in ('current', 'pilot'):
                self.assert_rejected([event('c', 'connect'), event('x', kind, '00:10:00',
                    payload={'value': value, 'unit': 'A'})], 'INVALID_NUMBER')
            self.assert_rejected([event('r', 'request', payload=request(value))],
                                 'INVALID_NUMBER')
            if value is not None:
                self.assert_rejected([event('r', 'request', payload=request(delivered=value))],
                                     'INVALID_NUMBER')

    def test_strict_revisions_evidence_identifiers_and_payload_units(self):
        for value in (True, 1.0, -1, '1', None):
            self.assert_rejected([event('c', 'connect', revision=value)], 'INVALID_REVISION')
        for key in ('event_id', 'session_id', 'device_id', 'evidence_id'):
            record = event('c', 'connect')
            record[key] = ''
            self.assert_rejected([record], 'INVALID_IDENTIFIER')
        self.assert_rejected([event('c', 'connect'), event('a', 'current', '00:10:00',
            payload={'value': 3, 'unit': 'kW'})], 'INVALID_UNIT')
        self.assert_rejected([event('r', 'request', payload=request(basis='inferred'))],
                             'INVALID_REQUEST_BASIS')

    def test_invalid_top_level_types_mode_and_staleness(self):
        for events in (None, {}, (), 'events'):
            self.assert_rejected(events, 'INVALID_SCHEMA')
        for mode in (None, True, 'online', 'replay'):
            self.assert_rejected([], 'UNKNOWN_AVAILABILITY', availability_mode=mode)
        for value in (True, None, -1, math.nan, math.inf, '900'):
            self.assert_rejected([], 'INVALID_NUMBER', stale_after_seconds=value)


if __name__ == '__main__':
    unittest.main()
