"""Artificial input checks; no datasets, model files, or external services."""

import importlib
import unittest
from dataclasses import FrozenInstanceError, is_dataclass
from datetime import datetime, timezone

try:
    contracts = importlib.import_module("evcf.integration.reuse_contracts")
except ModuleNotFoundError as exc:
    if exc.name not in {"evcf.integration", "evcf.integration.reuse_contracts"}:
        raise
    contracts = None


def synthetic_payload():
    return {
        "schema_version": "synthetic-dispatch/v1",
        "issue_time_utc": "2026-11-05T00:00:00Z",
        "step_seconds": 900,
        "observations": {
            "station_power": {
                "value": 0,
                "unit": "kW",
                "available_at_utc": "2026-11-05T00:00:00+00:00",
            }
        },
        "forecast": {
            "kind": "synthetic_forecast",
            "generated_at_utc": "2026-11-04T23:59:59Z",
            "unit": "kW",
            "values": [[4] * 16, [8] * 16],
            "weights": [0.25, 0.75],
        },
    }


class SyntheticContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(contracts, "synthetic contract API is not implemented")
        self.validate = contracts.validate_synthetic_dispatch_input
        self.error = contracts.ContractError

    def reject_change(self, path, value):
        payload = synthetic_payload()
        target = payload
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value
        with self.assertRaises(self.error, msg=str(path)):
            self.validate(payload)

    def test_valid_zero_and_normalized_records(self):
        result = self.validate(synthetic_payload())
        self.assertTrue(issubclass(self.error, ValueError))
        self.assertTrue(is_dataclass(result))
        self.assertEqual(result.schema_version, "synthetic-dispatch/v1")
        self.assertEqual(result.issue_time_utc, datetime(2026, 11, 5, tzinfo=timezone.utc))
        self.assertEqual(result.step_seconds, 900)
        self.assertEqual(result.station_power.value, 0.0)
        self.assertEqual(result.station_power.unit, "kW")
        self.assertEqual(result.station_power.available_at_utc, result.issue_time_utc)
        self.assertEqual(result.forecast.kind, "synthetic_forecast")
        self.assertEqual(result.forecast.unit, "kW")
        self.assertEqual(result.forecast.weights, (0.25, 0.75))
        self.assertEqual(result.forecast.values, ((4.0,) * 16, (8.0,) * 16))

    def test_missing_empty_null_observation_is_not_zero(self):
        for value in (None, {}, [], 0):
            with self.subTest(value=value):
                self.reject_change(("observations",), value)
                self.reject_change(("observations", "station_power"), value)
        self.reject_change(("observations", "station_power", "value"), None)
        payload = synthetic_payload()
        del payload["observations"]["station_power"]["value"]
        with self.assertRaises(self.error):
            self.validate(payload)

    def test_unknown_and_oracle_fields_rejected_at_every_mapping_level(self):
        for path in ((), ("observations",), ("observations", "station_power"), ("forecast",)):
            for key in ("actual_departure", "final_kwh", "unknown", "future_arrivals"):
                with self.subTest(path=path, key=key):
                    self.reject_change((*path, key), {"truth": 1})

    def test_truth_oracle_and_unlabelled_forecasts_rejected(self):
        for value in ("truth", "oracle", "forecast", None, 1):
            with self.subTest(value=value):
                self.reject_change(("forecast", "kind"), value)

    def test_bad_metadata_and_missing_top_level_fields_rejected(self):
        for value in (None, "dispatch/v1", 1):
            self.reject_change(("schema_version",), value)
        for value in (None, True, 900.0, "900", 0, 60):
            self.reject_change(("step_seconds",), value)
        for key in synthetic_payload():
            payload = synthetic_payload()
            del payload[key]
            with self.subTest(missing=key), self.assertRaises(self.error):
                self.validate(payload)
        for payload in (None, [], "synthetic", 0):
            with self.subTest(payload=payload), self.assertRaises(self.error):
                self.validate(payload)

    def test_future_observation_and_forecast_rejected(self):
        for path in (("observations", "station_power", "available_at_utc"),
                     ("forecast", "generated_at_utc")):
            self.reject_change(path, "2026-11-05T00:00:01Z")

    def test_malformed_naive_non_utc_times_rejected(self):
        for path in (("issue_time_utc",), ("observations", "station_power", "available_at_utc"),
                     ("forecast", "generated_at_utc")):
            for value in (None, 1, "", "bad", "2026-11-05", "2026-11-05T00:00:00",
                          "2026-11-05T08:00:00+08:00", "2026-02-30T00:00:00Z"):
                with self.subTest(path=path, value=value):
                    self.reject_change(path, value)

    def test_invalid_demand_numbers_rejected(self):
        for value in (True, False, None, "4", -1, float("nan"), float("inf"), -float("inf")):
            for path in (("observations", "station_power", "value"), ("forecast", "values", 0, 0)):
                with self.subTest(path=path, value=value):
                    self.reject_change(path, value)

    def test_units_must_be_explicit_kw(self):
        for value in ("A", "Ah", "MW", "kWh", "kw", None):
            self.reject_change(("observations", "station_power", "unit"), value)
            self.reject_change(("forecast", "unit"), value)

    def test_scenario_shape_rejected(self):
        for value in (None, [], [4] * 16, [[4] * 15, [8] * 16], [[4] * 17, [8] * 16],
                      ((4,) * 16, (8,) * 16), [[4] * 16, None], [[4] * 16, {"truth": 8}]):
            with self.subTest(value=value):
                self.reject_change(("forecast", "values"), value)

    def test_weights_shape_and_unit_sum_rejected(self):
        for value in (None, [], [1], [0, 0], [0.2, 0.2], [-0.1, 1.1], [True, 0],
                      [float("nan"), 0], [float("inf"), 0], ["0.25", 0.75], (0.25, 0.75)):
            with self.subTest(value=value):
                self.reject_change(("forecast", "weights"), value)

    def test_zero_weight_and_zero_demand_scenario_accepted(self):
        payload = synthetic_payload()
        payload["forecast"]["weights"] = [0, 1]
        payload["forecast"]["values"][0] = [0] * 16
        self.assertEqual(self.validate(payload).forecast.weights, (0.0, 1.0))

    def test_explicit_positive_horizon_controls_shape(self):
        payload = synthetic_payload()
        payload["forecast"]["values"] = [[4], [8]]
        self.assertEqual(len(self.validate(payload, horizon_steps=1).forecast.values[0]), 1)
        for horizon in (True, 0, -1, 1.0, None):
            with self.subTest(horizon=horizon), self.assertRaises(self.error):
                self.validate(payload, horizon_steps=horizon)

    def test_input_mutation_independence_and_frozen_nested_output(self):
        payload = synthetic_payload()
        result = self.validate(payload)
        payload["observations"]["station_power"]["value"] = 99
        payload["forecast"]["values"][0][0] = 99
        payload["forecast"]["weights"][0] = 99
        self.assertEqual(result.station_power.value, 0)
        self.assertEqual(result.forecast.values[0][0], 4)
        self.assertEqual(result.forecast.weights[0], 0.25)
        for record, field in ((result, "step_seconds"), (result.station_power, "value"),
                              (result.forecast, "kind")):
            with self.assertRaises(FrozenInstanceError):
                setattr(record, field, 99)
        with self.assertRaises(TypeError):
            result.forecast.values[0][0] = 99

    def test_explicit_kw_conversions(self):
        self.assertEqual(contracts.kw_to_mw(1000), 1)
        self.assertEqual(contracts.kw_to_mw(0, unit="kW"), 0)
        self.assertEqual(contracts.interval_energy_kwh([4] * 16), 16)
        self.assertEqual(contracts.interval_energy_kwh([4, 4], step_seconds=1800), 4)

    def test_conversion_rejects_unsupported_units_and_invalid_numbers(self):
        for unit in ("A", "Ah", "MW", "kWh", None):
            with self.subTest(unit=unit), self.assertRaises(self.error):
                contracts.kw_to_mw(1000, unit=unit)
            with self.assertRaises(self.error):
                contracts.interval_energy_kwh([4], unit=unit)
        for value in (True, False, None, "4", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(self.error):
                contracts.kw_to_mw(value)
            with self.assertRaises(self.error):
                contracts.interval_energy_kwh([value])
        for seconds in (True, 0, -1, "900", None, float("nan"), float("inf")):
            with self.subTest(seconds=seconds), self.assertRaises(self.error):
                contracts.interval_energy_kwh([4], step_seconds=seconds)
        for values in (None, [], "4", {"truth": 4}):
            with self.subTest(values=values), self.assertRaises(self.error):
                contracts.interval_energy_kwh(values)


if __name__ == "__main__":
    unittest.main()
