from __future__ import annotations

import json

import pytest
from evcf.data.acn_jpl_power_semantics import (
    CURRENT_PROXY_ONLY,
    KW_RECONSTRUCTION_CANDIDATE,
    PINNED_POWER_EVIDENCE,
    POWER_SEMANTICS_FAIL,
    PowerAuditSession,
    PowerDecisionInputs,
    ampere_hours_from_ampere_seconds,
    assert_online_feature_payload_safe,
    audit_power_semantics,
    classify_power_semantics,
    effective_voltage_v,
    energy_at_208v_kwh,
)


def test_offline_energy_formulas_use_fixed_208_v() -> None:
    ampere_hours = ampere_hours_from_ampere_seconds(7200.0)

    assert ampere_hours == pytest.approx(2.0)
    assert energy_at_208v_kwh(ampere_hours) == pytest.approx(0.416)
    assert effective_voltage_v(ampere_hours, 0.416) == pytest.approx(208.0)
    assert effective_voltage_v(0.0, 1.0) is None


def test_pinned_power_evidence_is_exact_and_static_mirror_is_not_used() -> None:
    evidence = PINNED_POWER_EVIDENCE.public_dict()

    assert evidence == {
        "repository": "https://github.com/zach401/acnportal",
        "commit": "14e723b11339e56ca3afd2bf4969f9e4bc8c2623",
        "source_path": "acnportal/acnsim/network/sites/jpl_acn.py",
        "source_url": (
            "https://raw.githubusercontent.com/zach401/acnportal/"
            "14e723b11339e56ca3afd2bf4969f9e4bc8c2623/"
            "acnportal/acnsim/network/sites/jpl_acn.py"
        ),
        "source_sha256": (
            "0a8c9de3c972995dd323e3c2a976bff8511b795553f3926b60251b5418d6140d"
        ),
        "source_retrieved_utc": "2026-09-01T06:31:52.7278373Z",
        "license": "BSD-3-Clause",
        "license_path": "LICENSE.txt",
        "license_url": (
            "https://raw.githubusercontent.com/zach401/acnportal/"
            "14e723b11339e56ca3afd2bf4969f9e4bc8c2623/LICENSE.txt"
        ),
        "license_sha256": (
            "34256c87b252573d30203b02ee12407bfbf2169684adfef3a3ea4f9bb9e0db5f"
        ),
        "license_retrieved_utc": "2026-09-01T06:31:55.3086889Z",
        "license_copyright": "Copyright 2019 California Institute of Technology",
        "default_evse_voltage_v": 208.0,
        "line_to_line_network": True,
        "line_to_line_definition": (
            "EVSEs are assigned to AB/BC/CA branches at 30/-90/150 degrees; "
            "phase currents are Ia=Iab-Ica, Ib=Ibc-Iab, Ic=Ica-Ibc."
        ),
        "pinned_evse_name_count": 52,
        "evse_naming_summary": (
            "52 AG-prefixed, floor-coded, two-digit EVSE/space names: "
            "14 first-floor, 19 third-floor, 19 fourth-floor."
        ),
        "topology_caveat": (
            "ACN-Sim network-model defaults are audit evidence, not proof of per-session "
            "measured voltage or active power."
        ),
        "static_mirror": "NOT_USED",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"kWhDelivered": 12.0},
        {"nested": {"Veff": 208.0}},
        {"nested": [{"effective_voltage_v": 208.0}]},
        {"E208_kWh": 1.2},
    ],
)
def test_offline_only_values_are_rejected_from_online_feature_payloads(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="offline-only"):
        assert_online_feature_payload_safe(payload)


def test_online_feature_guard_accepts_issue_time_current_state() -> None:
    assert_online_feature_payload_safe(
        {
            "elapsedConnectionSeconds": 900,
            "ampere_hours_observed_so_far": 1.5,
            "recent_current_a": [4.0, 5.0],
        }
    )


def _candidate_inputs(**changes: object) -> PowerDecisionInputs:
    values: dict[str, object] = {
        "mapping_rate": 1.0,
        "primary_audit_coverage": 0.90,
        "eligible_session_count": 10,
        "retained_session_count": 9,
        "median_absolute_percentage_error": 0.20,
        "p90_absolute_percentage_error": 0.40,
        "monthly_relative_energy_error": -0.10,
        "statistics_finite": True,
    }
    values.update(changes)
    return PowerDecisionInputs(**values)  # type: ignore[arg-type]


def test_candidate_status_includes_all_closed_rule_boundaries() -> None:
    assert classify_power_semantics(_candidate_inputs()) == KW_RECONSTRUCTION_CANDIDATE


@pytest.mark.parametrize(
    "changes",
    [
        {"mapping_rate": 0.999},
        {"primary_audit_coverage": 0.899},
        {"retained_session_count": 8},
        {"median_absolute_percentage_error": 0.201},
        {"p90_absolute_percentage_error": 0.401},
        {"monthly_relative_energy_error": 0.101},
    ],
)
def test_nonsevere_candidate_rule_miss_is_current_proxy_only(
    changes: dict[str, object],
) -> None:
    assert classify_power_semantics(_candidate_inputs(**changes)) == CURRENT_PROXY_ONLY


@pytest.mark.parametrize(
    "changes",
    [
        {"mapping_rate": 0.949},
        {"statistics_finite": False},
        {"monthly_relative_energy_error": 0.501},
    ],
)
def test_severe_contradictions_fail_power_semantics(changes: dict[str, object]) -> None:
    assert classify_power_semantics(_candidate_inputs(**changes)) == POWER_SEMANTICS_FAIL


def test_severe_thresholds_are_strict_not_inclusive() -> None:
    assert (
        classify_power_semantics(_candidate_inputs(mapping_rate=0.95))
        == CURRENT_PROXY_ONLY
    )
    assert (
        classify_power_semantics(_candidate_inputs(monthly_relative_energy_error=0.50))
        == CURRENT_PROXY_ONLY
    )


def _mapped_space(floor: int, number: int) -> str:
    return f"AG-{floor}F{number:02d}"


def _exact_session(
    *,
    space_id: str,
    is_weekend: bool = False,
    coverage: float = 0.95,
    delivered_kwh: float = 0.624,
    ampere_hours: float = 3.0,
    retained: bool = True,
) -> PowerAuditSession:
    return PowerAuditSession(
        space_id=space_id,
        ampere_hours=ampere_hours,
        kwh_delivered=delivered_kwh,
        current_coverage=coverage,
        is_weekend=is_weekend,
        retained=retained,
    )


def test_complete_mapping_and_exact_energy_can_be_a_candidate() -> None:
    report = audit_power_semantics(
        [
            _exact_session(space_id=_mapped_space(1, 1)),
            _exact_session(
                space_id=_mapped_space(3, 15),
                ampere_hours=3.0,
                delivered_kwh=0.624,
                is_weekend=True,
            ),
        ]
    )

    assert report["status"] == KW_RECONSTRUCTION_CANDIDATE
    assert report["mapping"] == {
        "raw_record_count": 2,
        "records_with_space": 2,
        "mapped_record_count": 2,
        "unmapped_record_count": 0,
        "mapping_rate": 1.0,
        "observed_unique_space_count": 2,
        "mapped_unique_space_count": 2,
        "unmapped_unique_space_count": 0,
        "pinned_source_space_count": 52,
        "complete_for_candidate": True,
    }
    primary = report["cohorts"]["primary"]
    assert primary["audit_coverage"] == 1.0
    assert primary["retained_rate"] == 1.0
    assert primary["effective_voltage_v"] == {
        "count": 2,
        "median": 208.0,
        "iqr": 0.0,
        "p05": 208.0,
        "p95": 208.0,
    }
    assert primary["e208_error"]["mae_kwh"] == pytest.approx(0.0)
    assert primary["e208_error"]["median_absolute_percentage_error"] == 0.0
    assert primary["e208_error"]["p90_absolute_percentage_error"] == 0.0


def test_primary_and_sensitivity_cohorts_have_deterministic_threshold_order() -> None:
    report = audit_power_semantics(
        [
            _exact_session(
                space_id=_mapped_space(1, 1), delivered_kwh=0.2, coverage=0.95
            ),
            _exact_session(
                space_id=_mapped_space(3, 15), delivered_kwh=0.6, coverage=0.85
            ),
            _exact_session(
                space_id=_mapped_space(4, 34), delivered_kwh=1.1, coverage=0.75
            ),
        ]
    )

    cohorts = [report["cohorts"]["primary"], *report["cohorts"]["sensitivity"]]
    assert [
        (
            cohort["thresholds"]["minimum_kwh_delivered"],
            cohort["thresholds"]["minimum_current_coverage"],
            cohort["eligible_session_count"],
            cohort["coverage_qualified_session_count"],
        )
        for cohort in cohorts
    ] == [
        (0.5, 0.9, 2, 0),
        (0.1, 0.8, 3, 2),
        (0.1, 0.9, 3, 1),
        (0.1, 0.95, 3, 1),
        (0.5, 0.8, 2, 1),
        (0.5, 0.95, 2, 0),
        (1.0, 0.8, 1, 0),
        (1.0, 0.9, 1, 0),
        (1.0, 0.95, 1, 0),
    ]


def test_e208_veff_and_group_errors_are_aggregate_statistics_only() -> None:
    private_space_a = _mapped_space(1, 1)
    private_space_b = _mapped_space(3, 15)
    report = audit_power_semantics(
        [
            _exact_session(
                space_id=private_space_a,
                delivered_kwh=1.04,
                ampere_hours=5.0,
            ),
            _exact_session(
                space_id=private_space_b,
                delivered_kwh=0.52,
                ampere_hours=5.0,
                is_weekend=True,
            ),
        ]
    )
    primary = report["cohorts"]["primary"]

    assert primary["effective_voltage_v"] == pytest.approx(
        {"count": 2, "median": 156.0, "iqr": 52.0, "p05": 109.2, "p95": 202.8}
    )
    assert primary["e208_error"] == pytest.approx(
        {
            "count": 2,
            "mae_kwh": 0.26,
            "median_absolute_percentage_error": 0.5,
            "p90_absolute_percentage_error": 0.9,
        }
    )
    assert primary["aggregate_energy"]["relative_error"] == pytest.approx(1 / 3)
    assert primary["aggregate_energy"]["absolute_relative_error"] == pytest.approx(1 / 3)
    assert primary["weekday_aggregate_energy"]["relative_error"] == 0.0
    assert primary["weekend_aggregate_energy"]["relative_error"] == pytest.approx(1.0)
    by_evse = primary["aggregate_by_evse_distribution"]
    assert by_evse["evse_count"] == 2
    assert len(by_evse["groups"]) == 2
    assert all("anonymous_evse_index" in group for group in by_evse["groups"])
    assert by_evse["relative_error"]["median"] == pytest.approx(0.5)
    assert by_evse["absolute_relative_error"]["median"] == pytest.approx(0.5)

    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert private_space_a not in serialized
    assert private_space_b not in serialized
    assert "space_id" not in serialized
    assert report["privacy"] == {
        "aggregate_only": True,
        "identifiers_emitted": False,
        "space_names_emitted": False,
        "token_emitted": False,
    }


def test_incomplete_but_nonsevere_mapping_is_current_only_without_names() -> None:
    private_unknown = "fixture-private-unmapped-space"
    sessions = [
        _exact_session(space_id=_mapped_space(1, 1)) for _ in range(99)
    ] + [_exact_session(space_id=private_unknown)]

    report = audit_power_semantics(sessions)

    assert report["status"] == CURRENT_PROXY_ONLY
    assert report["mapping"]["mapping_rate"] == 0.99
    assert report["mapping"]["unmapped_record_count"] == 1
    assert report["mapping"]["complete_for_candidate"] is False
    assert private_unknown not in json.dumps(report, sort_keys=True)
