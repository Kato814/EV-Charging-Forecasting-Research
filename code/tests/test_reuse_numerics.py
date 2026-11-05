"""Numerical smoke checks use only explicit toy constants and no datasets."""

import importlib
import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    numerics = importlib.import_module("evcf.integration.reuse_numerics")
except ModuleNotFoundError as exc:
    if not exc.name.startswith("evcf.integration"):
        raise
    numerics = None


class _NumericalTestCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(numerics, "Numerical probe module is not implemented")


class NumericalApiTests(_NumericalTestCase):
    def test_public_probes_exist(self):
        self.assertTrue(callable(numerics.run_soc_parameter_probe))
        self.assertTrue(callable(numerics.run_two_bus_powerflow_probe))
        self.assertTrue(issubclass(numerics.NumericalCheckError, RuntimeError))

    def test_only_exact_optimal_status_can_yield_an_action(self):
        for status in ("infeasible", "infeasible_inaccurate", "optimal_inaccurate",
                       "unbounded", "user_limit", "unknown", None):
            with self.subTest(status=status):
                self.assertIsNone(numerics._soc_action(status, 5.0))
        self.assertEqual(numerics._soc_action("optimal", 5.0), {"t": 5.0})

    def test_nonfinite_or_missing_optimal_values_cannot_yield_actions(self):
        for value in (None, math.nan, math.inf, -math.inf, True):
            with self.subTest(value=value), self.assertRaises(numerics.NumericalCheckError):
                numerics._soc_action("optimal", value)


@unittest.skipUnless(importlib.util.find_spec("cvxpy"), "optional cvxpy is absent")
class SocTests(_NumericalTestCase):
    def test_parameter_update_solves_known_norms_and_infeasible_case(self):
        result = numerics.run_soc_parameter_probe()
        self.assertTrue(result["synthetic_only"])
        self.assertTrue(result["is_dcp"])
        self.assertTrue(result["is_dpp"])
        self.assertEqual(result["solver"], "CLARABEL")
        self.assertEqual(len(result["cases"]), 2)
        for case, vector in zip(result["cases"], ([3.0, 4.0], [6.0, 8.0])):
            self.assertEqual(case["a"], vector)
            self.assertEqual(case["status"], "optimal")
            expected = math.hypot(*vector)
            self.assertAlmostEqual(case["objective"], expected, delta=1e-6)
            self.assertAlmostEqual(case["action"]["t"], expected, delta=1e-6)
            self.assertLessEqual(max(0.0, expected - case["action"]["t"]), 1e-6)
            self.assertLessEqual(case["primal_residual"], 1e-6)
        self.assertEqual(result["infeasible_case"]["status"], "infeasible")
        self.assertIsNone(result["infeasible_case"]["action"])
        json.dumps(result, allow_nan=False)

    def test_solver_failure_is_reported(self):
        with self.assertRaisesRegex(numerics.NumericalCheckError, "solver"):
            numerics.run_soc_parameter_probe(solver="__MISSING_SOLVER__")


@unittest.skipUnless(importlib.util.find_spec("pandapower"), "optional pandapower is absent")
class PowerflowTests(_NumericalTestCase):
    def test_handbuilt_feeder_conserves_power_and_load_update_increases_drop(self):
        result = numerics.run_two_bus_powerflow_probe()
        self.assertTrue(result["synthetic_only"])
        assumptions = result["assumed_parameters"]
        self.assertEqual(assumptions["bus_voltage_kv"], 0.4)
        self.assertEqual(assumptions["line_length_km"], 0.1)
        self.assertEqual(assumptions["line_r_ohm_per_km"], 0.4)
        self.assertEqual(assumptions["line_x_ohm_per_km"], 0.08)
        self.assertEqual(assumptions["line_c_nf_per_km"], 0.0)
        self.assertEqual(assumptions["line_max_i_ka"], 0.2)
        self.assertEqual(len(result["cases"]), 2)
        for case, load_kw, load_kvar in zip(result["cases"], (5.0, 10.0), (1.0, 2.0)):
            self.assertTrue(case["converged"])
            self.assertEqual(case["load_kw"], load_kw)
            self.assertEqual(case["load_kvar"], load_kvar)
            self.assertAlmostEqual(case["load_p_mw"], load_kw / 1000)
            self.assertAlmostEqual(case["load_q_mvar"], load_kvar / 1000)
            self.assertGreater(case["line_loss_mw"], 0.0)
            self.assertGreater(case["slack_p_mw"], case["load_p_mw"])
            self.assertGreater(case["receiving_voltage_pu"], 0.9)
            self.assertLess(case["receiving_voltage_pu"], 1.0)
            self.assertAlmostEqual(case["slack_p_mw"],
                                   case["load_p_mw"] + case["line_loss_mw"], delta=1e-8)
        low, high = result["cases"]
        self.assertGreater(high["voltage_drop_pu"], low["voltage_drop_pu"])
        self.assertGreater(high["line_loss_mw"], low["line_loss_mw"])
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
