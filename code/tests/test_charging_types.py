import importlib
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

try:
    types = importlib.import_module('evcf.integration.charging_types')
except ModuleNotFoundError:
    types = None


class ChargingTypesTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(types, 'Charging types are not implemented')
        self.issue = datetime(2026, 11, 6, tzinfo=timezone.utc)

    def test_records_are_frozen(self):
        action = types.ChargeAction('A', 'D', self.issue, self.issue + timedelta(minutes=15), 4)
        energy = types.DeliveredEnergy('A', 'D', 1)
        snapshot = types.EnergySnapshot(self.issue, (energy,))
        for record, key, value in ((action, 'power_kw', 9), (energy, 'energy_kwh', 9),
                                   (snapshot, 'entries', ())):
            with self.subTest(key=key), self.assertRaises(FrozenInstanceError):
                setattr(record, key, value)

    def test_utc_datetime_requires_aware_utc(self):
        self.assertEqual(types.utc_datetime(self.issue, 'issue'), self.issue)
        for value in (self.issue.replace(tzinfo=None), '2026-11-06T00:00:00Z', True,
                      self.issue.astimezone(timezone(timedelta(hours=1)))):
            with self.subTest(value=value), self.assertRaises(types.AdmissionError):
                types.utc_datetime(value, 'issue')

    def test_step_has_finite_positive_integer_duration(self):
        self.assertEqual(types.step_end(self.issue, 900), self.issue + timedelta(minutes=15))
        for value in (True, 0, -1, 900.0, 10**100):
            with self.subTest(value=value), self.assertRaises(types.AdmissionError):
                types.step_end(self.issue, value)
        with self.assertRaises(types.AdmissionError):
            types.step_end(datetime.max.replace(tzinfo=timezone.utc), 1)
