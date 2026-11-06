"""The public adapter accepts an artificial envelope and returns an immutable view."""
import copy
import importlib
import unittest
from dataclasses import FrozenInstanceError

try:
    adapter = importlib.import_module('evcf.integration.controller_adapter')
except ModuleNotFoundError as exc:
    if not exc.name.startswith('evcf.integration.controller_'):
        raise
    adapter = None


def payload():
    identity = {'site_id': 'SYN-SITE', 'cluster_id': 'SYN-CLUSTER',
                'station_id': 'SYN-DEVICE', 'space_id': 'SYN-SPACE'}
    common = {'session_id': 'SYN-SESSION', 'device_id': 'SYN-DEVICE',
              'event_time_utc': '2026-11-06T00:00:00Z',
              'available_at_utc': '2026-11-06T00:00:00Z',
              'availability_basis': 'recorded_reception', 'evidence_id': 'synthetic-receipt',
              'revision': 0}
    return {
        'schema_version': 'synthetic-controller/v1', 'data_origin': 'hand_authored',
        'issue_time_utc': '2026-11-06T00:15:00Z', 'availability_mode': 'recorded_reception',
        'stale_after_seconds': 900,
        'events': [{**common, 'event_id': 'connect-1', 'kind': 'connect', 'payload': {}},
                   {**common, 'event_id': 'current-1', 'kind': 'current',
                    'payload': {'value': 3.0, 'unit': 'A'}}],
        'device_keys': {'SYN-DEVICE': identity},
        'device_mappings': [{**identity, 'topology_label': 'SYN-TOPOLOGY', 'node_id': 'SYN-NODE',
                             'valid_from_utc': '2026-11-06T00:00:00Z', 'valid_to_utc': None,
                             'available_at_utc': '2026-11-06T00:00:00Z',
                             'evidence_id': 'synthetic-map', 'mapping_basis': 'synthetic_assumption'}],
    }


class ControllerAdapterTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(adapter, 'Synthetic controller adapter is not implemented')

    def test_maps_only_visible_sessions_and_cannot_authorize_live_dispatch(self):
        result = adapter.build_synthetic_controller_view(payload())
        self.assertTrue(result.synthetic_only)
        self.assertFalse(result.real_dispatch_authorized)
        self.assertEqual(len(result.sessions), 1)
        self.assertEqual(result.sessions[0].state.current_a, 3.0)
        self.assertEqual(result.sessions[0].mapping.node_id, 'SYN-NODE')

    def test_rejects_real_origin_or_whole_truth_container(self):
        for change in ({'data_origin': 'acn_dataset'}, {'evaluation_truth': {'final_kwh': 99}},
                       {'schema_version': 'controller/live'}):
            with self.subTest(change=change), self.assertRaises(adapter.AdmissionError):
                adapter.build_synthetic_controller_view({**payload(), **change})

    def test_unknown_mapping_fails_without_guessing_identifier_equality(self):
        value = payload()
        value['device_mappings'] = []
        with self.assertRaises(adapter.AdmissionError) as exc:
            adapter.build_synthetic_controller_view(value)
        self.assertEqual(exc.exception.code, 'UNKNOWN_DEVICE_MAPPING')

    def test_mismatched_physical_key_is_rejected(self):
        value = payload()
        value['device_keys']['SYN-DEVICE']['station_id'] = 'ANOTHER-DEVICE'
        with self.assertRaises(adapter.AdmissionError) as exc:
            adapter.build_synthetic_controller_view(value)
        self.assertEqual(exc.exception.code, 'UNKNOWN_DEVICE_MAPPING')

    def test_output_is_frozen_and_independent_of_input_mutation(self):
        value = payload()
        original = copy.deepcopy(value)
        result = adapter.build_synthetic_controller_view(value)
        self.assertEqual(value, original)
        value['events'][1]['payload']['value'] = 999
        value['device_mappings'][0]['node_id'] = 'CHANGED'
        self.assertEqual(result.sessions[0].state.current_a, 3)
        self.assertEqual(result.sessions[0].mapping.node_id, 'SYN-NODE')
        with self.assertRaises(FrozenInstanceError):
            result.sessions = ()

    def test_late_and_future_values_cannot_change_integrated_view(self):
        baseline = payload()
        future = copy.deepcopy(baseline['events'][1])
        future.update(event_id='future-current', event_time_utc='2026-11-06T01:00:00Z',
                      available_at_utc='2026-11-06T01:00:00Z')
        baseline['events'].append(future)
        first = adapter.build_synthetic_controller_view(baseline)
        future['payload'] = {'final_kwh': 9000, 'value': None}
        second = adapter.build_synthetic_controller_view(baseline)
        self.assertEqual(first, second)

    def test_expired_or_ambiguous_declarations_are_explicitly_flagged(self):
        cases = [('total', '2026-11-06T00:05:00Z', None, 'EXPIRED_DEPARTURE'),
                 ('unknown', '2026-11-06T01:00:00Z', None, 'UNKNOWN_REQUEST_BASIS'),
                 ('additional', '2026-11-06T01:00:00Z', None, 'UNKNOWN_REQUEST_BASELINE')]
        for basis, departure, baseline, expected in cases:
            with self.subTest(expected=expected):
                value = payload()
                request = {**value['events'][0], 'event_id': 'request-1', 'kind': 'request',
                           'payload': {'energy_kwh': 10, 'request_basis': basis,
                                       'departure_time_utc': departure,
                                       'delivered_at_revision_kwh': baseline}}
                value['events'].append(request)
                result = adapter.build_synthetic_controller_view(value)
                self.assertTrue(hasattr(result.sessions[0], 'declaration_status'),
                                'Declaration status guard is not implemented')
                self.assertEqual(result.sessions[0].declaration_status, expected)

    def test_unavailable_mapping_content_cannot_change_integrated_view(self):
        value = payload()
        expected = adapter.build_synthetic_controller_view(value)
        for clock in ('available_at_utc', 'valid_from_utc'):
            with self.subTest(clock=clock):
                changed = copy.deepcopy(value)
                future = copy.deepcopy(changed['device_mappings'][0])
                future[clock] = '2026-11-06T01:00:00Z'
                future.update(node_id='', mapping_basis='unavailable-content', future_truth=999)
                changed['device_mappings'].append(future)
                self.assertEqual(adapter.build_synthetic_controller_view(changed), expected)


if __name__ == '__main__':
    unittest.main()
