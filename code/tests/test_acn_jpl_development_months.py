from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
import evcf.data.acn_jpl_full_month_qa as full_month_qa
import evcf.data.acn_jpl_preparation as preparation
import evcf.data.acn_jpl_seasonal_acquisition as acquisition
from evcf.data.acn_jpl_development_months import (
    DEVELOPMENT_MONTHS,
    FINAL_HOLDOUT_MONTHS,
    DevelopmentMonthContractError,
    development_month_contracts,
    installed_development_month_contracts,
)
from evcf.data.acn_jpl_month_config import jpl_month_config, summarize_complete_metadata
from evcf.data.acn_jpl_preparation import (
    InventorySnapshot,
    SEASONAL_INVENTORY_DIGEST_ALGORITHM,
    SEASONAL_INVENTORY_SCHEMA_VERSION,
)
from evcf.data.acn_jpl_trajectory_quarantine import (
    TRAJECTORY_QUARANTINE,
    TrajectoryQuarantineDecision,
)


def test_development_and_holdout_partitions_are_fixed_and_disjoint() -> None:
    assert DEVELOPMENT_MONTHS == ("2019-01", "2019-04", "2019-07", "2019-10")
    assert FINAL_HOLDOUT_MONTHS == ("2019-03", "2019-06", "2019-09", "2019-12")
    assert set(DEVELOPMENT_MONTHS).isdisjoint(FINAL_HOLDOUT_MONTHS)


def test_development_contracts_build_without_persistently_approving_months() -> None:
    contracts = development_month_contracts()
    assert tuple(contracts) == DEVELOPMENT_MONTHS
    for month in DEVELOPMENT_MONTHS:
        assert contracts[month].month == month
        with pytest.raises(ValueError, match="approved JPL month"):
            jpl_month_config(month)


def test_installed_context_approves_development_only_and_restores_registry() -> None:
    original_guards = (
        acquisition.SEASONAL_MONTHS,
        full_month_qa.SEASONAL_MONTHS,
        preparation.SEASONAL_MONTHS,
        full_month_qa.build_trajectory_quarantine_audit,
    )
    with installed_development_month_contracts() as contracts:
        assert tuple(contracts) == DEVELOPMENT_MONTHS
        expected_extended = ("2019-02", "2019-08", "2019-11", *DEVELOPMENT_MONTHS)
        assert acquisition.SEASONAL_MONTHS == expected_extended
        assert full_month_qa.SEASONAL_MONTHS == expected_extended
        assert preparation.SEASONAL_MONTHS == expected_extended
        for month in DEVELOPMENT_MONTHS:
            assert jpl_month_config(month) is contracts[month]
        for month in FINAL_HOLDOUT_MONTHS:
            with pytest.raises(ValueError, match="approved JPL month"):
                jpl_month_config(month)

    assert (
        acquisition.SEASONAL_MONTHS,
        full_month_qa.SEASONAL_MONTHS,
        preparation.SEASONAL_MONTHS,
        full_month_qa.build_trajectory_quarantine_audit,
    ) == original_guards
    for month in (*DEVELOPMENT_MONTHS, *FINAL_HOLDOUT_MONTHS):
        with pytest.raises(ValueError, match="approved JPL month"):
            jpl_month_config(month)


def test_development_context_reaches_reviewed_raw_and_qa_guards_without_unlocking_holdout() -> None:
    digest = hashlib.sha256(b"").hexdigest()
    inventory = InventorySnapshot(
        entries=(),
        digest=digest,
        total_bytes=0,
        algorithm=SEASONAL_INVENTORY_DIGEST_ALGORITHM,
        schema_version=SEASONAL_INVENTORY_SCHEMA_VERSION,
    )
    with installed_development_month_contracts():
        config = jpl_month_config("2019-01")
        contract = preparation.RawSnapshotContract.for_month(
            config,
            local_record_count=0,
            carry_in_record_count=0,
            inventory=inventory,
        )
        assert contract.month_config is config

        unverified_scope = summarize_complete_metadata([], config)
        acquisition_result = acquisition.acquire_jpl_month(
            authorized=True,
            config=config,
            scope=unverified_scope,
            official_probe=lambda _config: (_ for _ in ()).throw(
                AssertionError("scope failure must precede official probe")
            ),
            raw_root="unused",
            ts_client_factory=lambda: (_ for _ in ()).throw(
                AssertionError("scope failure must precede client")
            ),
        )
        assert acquisition_result.status == "METADATA_GATE_FAIL"
        assert acquisition_result.reason_codes == ("SCOPE_NOT_VERIFIED",)

        qa_result = full_month_qa.generate_month_timeseries_qa(
            config=config,
            scope=unverified_scope,
            raw_root="unused",
            acquisition_result=None,
        )
        assert qa_result.gate_status == "FAIL"
        assert qa_result.qa["gate"]["reason_codes"] == ["SCOPE_NOT_VERIFIED"]

    for month in FINAL_HOLDOUT_MONTHS:
        with pytest.raises(ValueError, match="approved JPL month"):
            jpl_month_config(month)


def test_development_quarantine_policy_accepts_no_anomaly_and_rejects_any_new_signature() -> None:
    with installed_development_month_contracts():
        config = jpl_month_config("2019-04")
        clean = full_month_qa.build_trajectory_quarantine_audit(
            config,
            (),
            denominator_sessions=10,
        )
        assert clean.approved is True
        assert clean.trajectory_quarantine_count == 0

        unexpected = TrajectoryQuarantineDecision(
            action=TRAJECTORY_QUARANTINE,
            current_nonmonotonic_pairs=1,
            pilot_nonmonotonic_pairs=1,
            synchronized_transition_count=1,
            synchronized_backward_seconds=(3596.0,),
            synchronized_raw_ordinals=(3,),
            metadata_bounds_valid=True,
        )
        blocked = full_month_qa.build_trajectory_quarantine_audit(
            config,
            (unexpected,),
            denominator_sessions=10,
        )
        assert blocked.approved is False
        assert blocked.trajectory_quarantine_count == 1


def test_development_months_have_expected_physical_utc_grids() -> None:
    with installed_development_month_contracts():
        jan = jpl_month_config("2019-01")
        apr = jpl_month_config("2019-04")
        jul = jpl_month_config("2019-07")
        oct_ = jpl_month_config("2019-10")

        assert (jan.day_count, jan.expected_bins, jan.expected_scheduled_issue_times) == (
            31,
            2976,
            2865,
        )
        assert jan.local_start.utcoffset() == timedelta(hours=-8)
        assert jan.local_end.utcoffset() == timedelta(hours=-8)

        assert (apr.day_count, apr.expected_bins, apr.expected_scheduled_issue_times) == (
            30,
            2880,
            2769,
        )
        assert apr.local_start.utcoffset() == timedelta(hours=-7)
        assert apr.local_end.utcoffset() == timedelta(hours=-7)

        for config in (jul, oct_):
            assert (config.day_count, config.expected_bins, config.expected_scheduled_issue_times) == (
                31,
                2976,
                2865,
            )
            assert config.local_start.utcoffset() == timedelta(hours=-7)
            assert config.local_end.utcoffset() == timedelta(hours=-7)


def test_registry_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import evcf.data.acn_jpl_month_config as month_config

    monkeypatch.setattr(month_config, "_APPROVED_MONTHS", ("2019-05",))
    with pytest.raises(DevelopmentMonthContractError, match="registry drifted"):
        development_month_contracts()
