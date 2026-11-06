"""Unit and identity admission checks using hand-authored artificial inputs."""

import importlib
import math
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from evcf.integration.controller_common import AdmissionError

try:
    quantities = importlib.import_module("evcf.integration.controller_quantities")
except ModuleNotFoundError as exc:
    if exc.name != "evcf.integration.controller_quantities":
        raise
    quantities = None


ISSUE = "2026-11-06T01:00:00Z"
KEY = {
    "site_id": "site-a",
    "cluster_id": "cluster-a",
    "station_id": "station-a",
    "space_id": "space-a",
}


def mapping(**changes):
    value = dict(
        **KEY,
        topology_label="synthetic-topology",
        node_id="synthetic-node",
        valid_from_utc="2026-11-06T00:00:00Z",
        valid_to_utc=None,
        available_at_utc="2026-11-06T00:00:00Z",
        evidence_id="mapping-assumption-1",
        mapping_basis="synthetic_assumption",
    )
    value.update(changes)
    return value


def assumptions(**changes):
    value = {
        "voltage_v": 208,
        "power_factor": 0.9,
        "pf_basis": "explicit_assumption",
        "connection": "single_phase_line_to_line",
        "evidence_id": "power-assumption-1",
    }
    value.update(changes)
    return value


def support(count=16):
    issue = datetime(2026, 11, 6, 1, tzinfo=timezone.utc)
    return [
        {
            "start_utc": (issue + timedelta(seconds=900 * i)).isoformat(),
            "end_utc": (issue + timedelta(seconds=900 * (i + 1))).isoformat(),
        }
        for i in range(count)
    ]


class QuantityGuardsTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(quantities, "Controller quantity guards are not implemented")

    def assert_rejected(self, code, function, *args, **kwargs):
        with self.assertRaises(AdmissionError) as exc:
            function(*args, **kwargs)
        self.assertEqual(exc.exception.code, code)

    def resolve(self, values, **kwargs):
        options = dict(**KEY, issue_time_utc=ISSUE)
        options.update(kwargs)
        return quantities.resolve_device_mapping(values, **options)

    def proxy(self, current=10, **kwargs):
        options = {
            "profile": "assumed_power_simulation",
            "requested_basis": "assumed_proxy",
            "assumptions": assumptions(),
        }
        options.update(kwargs)
        return quantities.current_to_power_proxy(current, **options)

    def test_mapping_selects_all_four_keys_and_preserves_evidence(self):
        wrong = [mapping(**{key: "another"}) for key in KEY]
        result = self.resolve([*wrong, mapping()])
        for key, expected in KEY.items():
            self.assertEqual(getattr(result, key), expected)
        self.assertEqual(result.node_id, "synthetic-node")
        self.assertEqual(result.evidence_id, "mapping-assumption-1")
        self.assertEqual(result.mapping_basis, "synthetic_assumption")
        self.assertEqual(result.valid_from_utc, datetime(2026, 11, 6, tzinfo=timezone.utc))
        self.assertIsNone(result.valid_to_utc)
        with self.assertRaises(FrozenInstanceError):
            result.node_id = "changed"

    def test_missing_mapping_never_guesses_from_joined_labels(self):
        self.assert_rejected("UNKNOWN_DEVICE_MAPPING", self.resolve, [])
        for key in KEY:
            with self.subTest(key=key):
                self.assert_rejected(
                    "UNKNOWN_DEVICE_MAPPING", self.resolve, [mapping(**{key: "another"})]
                )

    def test_mapping_effective_interval_is_half_open_and_availability_is_causal(self):
        self.assertEqual(
            self.resolve([mapping(valid_from_utc=ISSUE, available_at_utc=ISSUE)]).node_id,
            "synthetic-node",
        )
        for change in (
            {"valid_to_utc": ISSUE},
            {"valid_from_utc": "2026-11-06T01:00:01Z"},
            {"available_at_utc": "2026-11-06T01:00:01Z"},
        ):
            with self.subTest(change=change):
                self.assert_rejected("UNKNOWN_DEVICE_MAPPING", self.resolve, [mapping(**change)])
        result = self.resolve(
            [mapping(), mapping(node_id="future-node", available_at_utc="2026-11-06T02:00:00Z")]
        )
        self.assertEqual(result.node_id, "synthetic-node")

    def test_mapping_overlap_is_ambiguous_even_if_entries_are_identical(self):
        self.assert_rejected("AMBIGUOUS_DEVICE_MAPPING", self.resolve, [mapping(), mapping()])

    def test_future_mapping_content_cannot_change_current_mapping(self):
        expected = self.resolve([mapping()])
        for clock in ("available_at_utc", "valid_from_utc"):
            for mutation in (
                {"node_id": ""},
                {"mapping_basis": "measured"},
                {"future_truth": 123},
            ):
                with self.subTest(clock=clock, mutation=mutation):
                    future = mapping(**{clock: "2026-11-06T02:00:00Z"}, **mutation)
                    self.assertEqual(self.resolve([mapping(), future]), expected)

    def test_future_mapping_still_requires_complete_valid_clocks(self):
        for clock in ("available_at_utc", "valid_from_utc", "valid_to_utc"):
            for invalid in ("not-a-time", "2026-11-06T02:00:00", True):
                with self.subTest(clock=clock, invalid=invalid):
                    future = mapping(available_at_utc="2026-11-06T02:00:00Z")
                    future[clock] = invalid
                    self.assert_rejected("INVALID_TIME", self.resolve, [mapping(), future])
            with self.subTest(missing_clock=clock), self.assertRaises(AdmissionError):
                future = mapping(available_at_utc="2026-11-06T02:00:00Z")
                del future[clock]
                self.resolve([mapping(), future])
        for clock in ("available_at_utc", "valid_from_utc"):
            with self.subTest(null_clock=clock):
                future = mapping(available_at_utc="2026-11-06T02:00:00Z")
                future[clock] = None
                self.assert_rejected("INVALID_TIME", self.resolve, [mapping(), future])
        self.assert_rejected(
            "INVALID_DEVICE_MAPPING",
            self.resolve,
            [
                mapping(),
                mapping(
                    available_at_utc="2026-11-06T02:00:00Z", valid_to_utc="2026-11-05T23:00:00Z"
                ),
            ],
        )

    def test_mapping_rejects_incomplete_or_unproved_metadata(self):
        missing = mapping()
        del missing["cluster_id"]
        invalid = [
            missing,
            mapping(extra="guessed"),
            mapping(mapping_basis="measured"),
            mapping(valid_to_utc="2026-11-05T23:00:00Z"),
            mapping(valid_from_utc="2026-11-06T00:00:00"),
            mapping(evidence_id=""),
        ]
        invalid += [mapping(**{field: ""}) for field in (*KEY, "topology_label", "node_id")]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(AdmissionError):
                self.resolve([value])
        with self.assertRaises(AdmissionError):
            self.resolve([mapping()], station_id="")

    def test_proxy_uses_only_explicit_single_phase_assumptions(self):
        result = self.proxy()
        self.assertAlmostEqual(result.value, 1.872)
        self.assertEqual(result.unit, "kW")
        self.assertEqual(result.power_basis, "assumed_proxy")
        self.assertEqual(result.evidence_id, "power-assumption-1")
        self.assertEqual(self.proxy(0).value, 0)
        self.assertEqual(self.proxy(assumptions=assumptions(power_factor=0)).value, 0)
        self.assertEqual(self.proxy(assumptions=assumptions(power_factor=1)).value, 2.08)
        with self.assertRaises(FrozenInstanceError):
            result.power_basis = "measured"

    def test_proxy_cannot_admit_archived_current_or_measured_power(self):
        for options in (
            {"profile": "archive_current"},
            {"profile": "unknown"},
            {"requested_basis": "measured"},
            {"requested_basis": "actual_power"},
        ):
            with self.subTest(options=options):
                self.assert_rejected("POWER_BASIS_MISMATCH", self.proxy, **options)

    def test_proxy_rejects_angle_as_pf_three_phase_and_hidden_multipliers(self):
        for options in (
            {"pf_basis": "topology_angle"},
            {"connection": "three_phase"},
            {"phase_multiplier": math.sqrt(3)},
            {"topology_angle_deg": 30},
            {"voltage_v": 0},
            {"voltage_v": -208},
            {"voltage_v": True},
            {"power_factor": -0.1},
            {"power_factor": 1.1},
            {"power_factor": math.nan},
            {"evidence_id": ""},
        ):
            with self.subTest(options=options):
                self.assert_rejected(
                    "INVALID_POWER_ASSUMPTION", self.proxy, assumptions=assumptions(**options)
                )
        self.assert_rejected("INVALID_POWER_ASSUMPTION", self.proxy, assumptions={})

    def test_proxy_rejects_invalid_current_and_nonfinite_result(self):
        for value in (True, -1, math.nan, math.inf, "10"):
            with self.subTest(value=value), self.assertRaises(AdmissionError):
                self.proxy(value)
        self.assert_rejected(
            "INVALID_POWER_ASSUMPTION", self.proxy, 1e308, assumptions=assumptions(voltage_v=1e308)
        )

    def test_partial_interval_keeps_fixed_and_covered_means_distinct(self):
        result = quantities.interval_current_means(900, 300)
        self.assertEqual(result.fixed_window_mean_a, 1)
        self.assertEqual(result.covered_time_mean_a, 3)
        self.assertEqual(result.coverage, 1 / 3)
        self.assertFalse(result.complete)
        with self.assertRaises(FrozenInstanceError):
            result.coverage = 1

    def test_zero_coverage_is_unknown_not_observed_zero(self):
        missing = quantities.interval_current_means(0, 0)
        observed = quantities.interval_current_means(0, 900)
        self.assertIsNone(missing.covered_time_mean_a)
        self.assertEqual(missing.fixed_window_mean_a, 0)
        self.assertFalse(missing.complete)
        self.assertEqual(observed.covered_time_mean_a, 0)
        self.assertTrue(observed.complete)
        self.assertEqual(observed.coverage, 1)

    def test_invalid_interval_rejects_nonfinite_or_impossible_coverage(self):
        for args in (
            (1, 0),
            (-1, 300),
            (1, -1),
            (1, 901),
            (1, 1, 0),
            (1, 1, -1),
            (True, 1),
            (1, True),
            (1, 1, True),
            (math.inf, 1),
            (1, math.nan),
            (1, 1, math.inf),
            (1e308, 1e-308, 900),
        ):
            with self.subTest(args=args):
                self.assert_rejected("INVALID_INTERVAL", quantities.interval_current_means, *args)

    def test_energy_increment_requires_same_epoch_and_monotone_kwh(self):
        self.assertEqual(
            quantities.energy_increment(3, 5, previous_epoch="epoch-a", current_epoch="epoch-a"), 2
        )
        self.assertEqual(
            quantities.energy_increment(3, 3, previous_epoch="epoch-a", current_epoch="epoch-a"), 0
        )
        self.assert_rejected(
            "ENERGY_COUNTER_RESET",
            quantities.energy_increment,
            5,
            1,
            previous_epoch="epoch-a",
            current_epoch="epoch-a",
        )
        self.assert_rejected(
            "ENERGY_COUNTER_BOUNDARY",
            quantities.energy_increment,
            3,
            5,
            previous_epoch="epoch-a",
            current_epoch="epoch-b",
        )

    def test_energy_increment_rejects_undefined_epochs_wrong_units_and_invalid_values(self):
        for previous, current in (("", ""), (None, None), ("epoch-a", 1)):
            with self.subTest(previous=previous, current=current):
                self.assert_rejected(
                    "ENERGY_COUNTER_BOUNDARY",
                    quantities.energy_increment,
                    3,
                    5,
                    previous_epoch=previous,
                    current_epoch=current,
                )
        self.assert_rejected(
            "UNIT_MISMATCH",
            quantities.energy_increment,
            3,
            5,
            previous_epoch="a",
            current_epoch="a",
            unit="Ah",
        )
        for value in (-1, True, math.inf, math.nan, "5"):
            with self.subTest(value=value), self.assertRaises(AdmissionError):
                quantities.energy_increment(0, value, previous_epoch="a", current_epoch="a")

    def test_remaining_energy_total_and_additional_have_explicit_distinct_bases(self):
        self.assertEqual(quantities.remaining_energy_kwh(10, 3, request_basis="total"), 7)
        self.assertEqual(
            quantities.remaining_energy_kwh(
                5, 3, request_basis="additional", delivered_at_revision=2
            ),
            4,
        )
        self.assertEqual(quantities.remaining_energy_kwh(1, 3, request_basis="total"), 0)
        self.assertEqual(
            quantities.remaining_energy_kwh(
                1, 5, request_basis="additional", delivered_at_revision=2
            ),
            0,
        )

    def test_remaining_energy_rejects_unknown_basis_and_missing_revision_baseline(self):
        for basis in ("unknown", "", None):
            with self.subTest(basis=basis):
                self.assert_rejected(
                    "UNKNOWN_REQUEST_BASIS",
                    quantities.remaining_energy_kwh,
                    10,
                    3,
                    request_basis=basis,
                )
        self.assert_rejected(
            "UNKNOWN_REQUEST_BASIS",
            quantities.remaining_energy_kwh,
            5,
            3,
            request_basis="additional",
        )
        for baseline in (-1, 4, True, math.inf, math.nan):
            with self.subTest(baseline=baseline), self.assertRaises(AdmissionError):
                quantities.remaining_energy_kwh(
                    5, 3, request_basis="additional", delivered_at_revision=baseline
                )

    def test_remaining_energy_rejects_wrong_units_invalid_values_and_overflow(self):
        self.assert_rejected(
            "UNIT_MISMATCH",
            quantities.remaining_energy_kwh,
            10,
            3,
            request_basis="total",
            unit="Ah",
        )
        for value in (-1, True, math.inf, math.nan, "10"):
            with self.subTest(value=value), self.assertRaises(AdmissionError):
                quantities.remaining_energy_kwh(value, 3, request_basis="total")
        # Avoid constructing baseline + requested before subtracting delivered.
        self.assertEqual(
            quantities.remaining_energy_kwh(
                1e308, 1e308, request_basis="additional", delivered_at_revision=1e308
            ),
            1e308,
        )

    def test_interval_support_returns_dense_immutable_temporal_support(self):
        values = support()
        result = quantities.validate_interval_support(values, ISSUE)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 16)
        self.assertTrue(all(isinstance(pair, tuple) for pair in result))
        self.assertEqual(result[0][0], datetime(2026, 11, 6, 1, tzinfo=timezone.utc))
        self.assertEqual(result[-1][1], datetime(2026, 11, 6, 5, tzinfo=timezone.utc))
        values[0]["start_utc"] = "changed"
        self.assertEqual(result[0][0], datetime(2026, 11, 6, 1, tzinfo=timezone.utc))

    def test_interval_support_rejects_sparse_gapped_overlapping_and_oracle_records(self):
        gap = support()
        gap[1]["start_utc"] = "2026-11-06T01:15:01Z"
        overlap = support()
        overlap[1]["start_utc"] = "2026-11-06T01:14:59Z"
        bad_end = support()
        bad_end[-1]["end_utc"] = "2026-11-06T05:00:01Z"
        extra = support()
        extra[0]["future_truth"] = 0
        naive = support()
        naive[0]["start_utc"] = "2026-11-06T01:00:00"
        for values in (support(15), support(17), gap, overlap, bad_end, extra, naive, None):
            with self.subTest(values=values):
                self.assert_rejected(
                    "INSUFFICIENT_FORECAST_SUPPORT",
                    quantities.validate_interval_support,
                    values,
                    ISSUE,
                )

    def test_interval_support_validates_positive_integer_configuration_and_time_range(self):
        for config in (
            {"horizon_steps": True},
            {"horizon_steps": 0},
            {"horizon_steps": 1.0},
            {"step_seconds": True},
            {"step_seconds": 0},
            {"step_seconds": 900.0},
            {"step_seconds": 10**100},
        ):
            with self.subTest(config=config):
                self.assert_rejected(
                    "INSUFFICIENT_FORECAST_SUPPORT",
                    quantities.validate_interval_support,
                    support(),
                    ISSUE,
                    **config,
                )
        self.assert_rejected(
            "INSUFFICIENT_FORECAST_SUPPORT",
            quantities.validate_interval_support,
            support(),
            "9999-12-31T23:59:59Z",
        )

    def test_matching_boundary_allows_component_order_only(self):
        left = {"boundary_id": "meter-a", "components": ["charger", "auxiliary"]}
        right = {"boundary_id": "meter-a", "components": ["auxiliary", "charger"]}
        self.assertIsNone(quantities.require_same_power_boundary(left, right))
        self.assertEqual(left["components"], ["charger", "auxiliary"])

    def test_boundary_mismatch_and_invalid_components_fail_closed(self):
        left = {"boundary_id": "meter-a", "components": ["charger", "auxiliary"]}
        for right in (
            {"boundary_id": "meter-b", "components": ["charger", "auxiliary"]},
            {"boundary_id": "meter-a", "components": ["charger"]},
            {"boundary_id": "meter-a", "components": ["charger", "charger"]},
            {"boundary_id": "meter-a", "components": []},
            {"boundary_id": "meter-a", "components": [""]},
            {"boundary_id": "meter-a", "components": "charger"},
            {"boundary_id": "", "components": ["charger"]},
            {"boundary_id": "meter-a", "components": ["charger"], "losses": 0},
            None,
        ):
            with self.subTest(right=right):
                self.assert_rejected(
                    "MEASUREMENT_BOUNDARY_MISMATCH",
                    quantities.require_same_power_boundary,
                    left,
                    right,
                )


if __name__ == "__main__":
    unittest.main()
