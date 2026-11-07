"""Contract primitives tested using artificial values only."""
import importlib
import math
import unittest
from datetime import datetime, timezone

try:
    common = importlib.import_module('evcf.integration.controller_common')
except ModuleNotFoundError as exc:
    if exc.name != 'evcf.integration.controller_common':
        raise
    common = None


class ControllerCommonTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(common, 'Controller common contract is not implemented')

    def test_utc_is_explicit_and_valid(self):
        self.assertEqual(common.utc('2026-11-06T00:00:00Z', 'issue'),
                         datetime(2026, 11, 6, tzinfo=timezone.utc))
        for value in ('2026-11-06T00:00:00', '2026-11-06T08:00:00+08:00', None, True):
            with self.subTest(value=value), self.assertRaises(common.AdmissionError) as exc:
                common.utc(value, 'issue')
            self.assertEqual(exc.exception.code, 'INVALID_TIME')

    def test_numbers_exclude_bool_nonfinite_and_negative(self):
        self.assertEqual(common.number(0, 'current'), 0.0)
        self.assertEqual(common.number(3, 'current'), 3.0)
        for value in (True, None, '3', -1, math.nan, math.inf, 10**400):
            with self.subTest(value=str(value)), self.assertRaises(common.AdmissionError) as exc:
                common.number(value, 'current')
            self.assertEqual(exc.exception.code, 'INVALID_NUMBER')

    def test_exact_keys_reject_missing_and_unknown_fields(self):
        self.assertEqual(common.exact_keys({'a': 1}, ('a',), 'record'), {'a': 1})
        for value in ({}, {'a': 1, 'final_kwh': 2}, None):
            with self.subTest(value=value), self.assertRaises(common.AdmissionError) as exc:
                common.exact_keys(value, ('a',), 'record')
            self.assertEqual(exc.exception.code, 'INVALID_SCHEMA')

    def test_identifiers_are_explicit_not_coerced(self):
        self.assertEqual(common.identifier('synthetic-device', 'device'), 'synthetic-device')
        for value in ('', ' ', ' DEV', 42, None, True):
            with self.subTest(value=value), self.assertRaises(common.AdmissionError) as exc:
                common.identifier(value, 'device')
            self.assertEqual(exc.exception.code, 'INVALID_IDENTIFIER')


if __name__ == '__main__':
    unittest.main()
