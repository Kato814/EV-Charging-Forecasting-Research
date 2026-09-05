from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from evcf.data import acn_jpl_seasonal_prep as prep_module
from evcf.data.acn_jpl_month_config import SEASONAL_MONTHS
from evcf.data.acn_jpl_preparation import canonical_seasonal_inventory
from evcf.data.acn_jpl_seasonal_acquisition import (
    ExistingMonthVerificationError,
    verified_existing_official_reference_sha256,
    verify_existing_jpl_month,
    verify_month_acquisition_result,
)
from evcf.data.acn_jpl_seasonal_prep import (
    MONTH_PAYLOAD_NAMES,
    MONTH_RELEASE_NAMES,
    ROOT_PAYLOAD_NAMES,
    ROOT_RELEASE_NAMES,
    SeasonalPreparationError,
    build_month_preparation_result,
    expected_seasonal_release_paths,
    publish_month_release,
    publish_seasonal_release,
    release_paths,
    verify_seasonal_release,
)

EXPECTED_MONTH_PAYLOAD_NAMES = (
    "acquisition_summary.json",
    "cleaning_qa.json",
    "cleaning_sensitivity.json",
    "boundary_current_audit.json",
    "power_semantics_audit.json",
    "station_15min_qa.json",
    "issue_snapshot_qa.json",
    "leakage_audit.json",
    "data_snapshot_manifest.json",
    "run_manifest.json",
)
EXPECTED_MONTH_RELEASE_NAMES = (*EXPECTED_MONTH_PAYLOAD_NAMES, "SHA256SUMS")
EXPECTED_ROOT_PAYLOAD_NAMES = (
    "seasonal_prep_summary.csv",
    "seasonal_snapshot_manifest.json",
    "seasonal_prep_report.md",
)
EXPECTED_ROOT_RELEASE_NAMES = (*EXPECTED_ROOT_PAYLOAD_NAMES, "SHA256SUMS")
EXPECTED_RELEASE_PATHS = (
    tuple(f"{month}/{name}" for month in SEASONAL_MONTHS for name in EXPECTED_MONTH_RELEASE_NAMES)
    + EXPECTED_ROOT_RELEASE_NAMES
)


def test_seasonal_public_allowlist_is_literal_unique_and_exactly_37() -> None:
    assert MONTH_PAYLOAD_NAMES == EXPECTED_MONTH_PAYLOAD_NAMES
    assert MONTH_RELEASE_NAMES == EXPECTED_MONTH_RELEASE_NAMES
    assert ROOT_PAYLOAD_NAMES == EXPECTED_ROOT_PAYLOAD_NAMES
    assert ROOT_RELEASE_NAMES == EXPECTED_ROOT_RELEASE_NAMES
    assert expected_seasonal_release_paths() == EXPECTED_RELEASE_PATHS
    assert len(EXPECTED_RELEASE_PATHS) == len(set(EXPECTED_RELEASE_PATHS)) == 37


def test_protocol_freezes_the_narrow_trajectory_quarantine_policy() -> None:
    protocol = prep_module.load_seasonal_preparation_protocol()

    assert protocol.trajectory_quarantine_month == "2019-11"
    assert protocol.trajectory_quarantine_expected_counts == (0, 0, 1)
    assert protocol.trajectory_quarantine_backward_seconds == 3596
    assert protocol.trajectory_quarantine_preserves_raw is True
    assert protocol.trajectory_quarantine_preserves_connected is True


def _month_documents(month: str, expected_bins: int, scheduled: int) -> dict[str, object]:
    valid_90 = (4 * expected_bins + 4) // 5
    day_count = {"2019-02": 28, "2019-08": 31, "2019-11": 30}[month]
    trajectory_quarantine_count = 1 if month == "2019-11" else 0
    month_status = (
        "PASS_WITH_TRAJECTORY_QUARANTINE"
        if trajectory_quarantine_count
        else "CONDITIONAL_PASS"
    )
    sha = {
        "config": "1" * 64,
        "metadata_source": "2" * 64,
        "metadata_record": "3" * 64,
        "raw": "4" * 64,
        "processed": "5" * 64,
        "snapshot": "6" * 64,
    }
    common_window = {
        "timezone": "America/Los_Angeles",
        "local_start_inclusive": f"{month}-01T00:00:00-08:00"
        if month == "2019-02"
        else f"{month}-01T00:00:00-07:00",
        "local_end_exclusive": {
            "2019-02": "2019-03-01T00:00:00-08:00",
            "2019-08": "2019-09-01T00:00:00-07:00",
            "2019-11": "2019-12-01T00:00:00-08:00",
        }[month],
        "utc_start_inclusive": {
            "2019-02": "2019-02-01T08:00:00+00:00",
            "2019-08": "2019-08-01T07:00:00+00:00",
            "2019-11": "2019-11-01T07:00:00+00:00",
        }[month],
        "utc_end_exclusive": {
            "2019-02": "2019-03-01T08:00:00+00:00",
            "2019-08": "2019-09-01T07:00:00+00:00",
            "2019-11": "2019-12-01T08:00:00+00:00",
        }[month],
    }
    integral = {
        "observed_seconds": 9,
        "eligible_seconds": 9,
        "coverage": 1.0,
        "value_hours": 0.0,
    }
    comparison_integral = {**integral, "relative_value_hours_change": None}
    return {
        "acquisition_summary.json": {
            "schema_version": "acn-jpl-seasonal-acquisition-summary/v1",
            "month": month,
            "status": "COMPLETE",
            "official_total": 9,
            "local_session_count": 9,
            "carry_in_count": 1,
            "combined_session_count": 10,
            "trajectory_quarantine_count": trajectory_quarantine_count,
            "trajectory_quarantine_rate": trajectory_quarantine_count / 10,
            "full_session_quarantine_count": 0,
            "metadata_scope": {
                "local_calendar_session_count": 9,
                "utc_calendar_session_count": 10,
                "left_boundary_count": 1,
                "right_boundary_count": 0,
                "carry_in_count": 1,
            },
            "official_probe": {
                "request_count": 1,
                "timeseries": False,
                "total_matches_local": True,
                "reference_valid": True,
            },
            "chunk_integrity": {
                "daily_expected": day_count,
                "daily_data_files_present": day_count,
                "daily_manifests_present": day_count,
                "daily_manifest_contracts_valid": day_count,
                "daily_sha256_verified": day_count,
                "daily_json_valid": day_count,
                "daily_record_manifest_matches": day_count,
                "daily_record_remote_matches": day_count,
                "daily_valid": day_count,
                "carry_expected": 1,
                "carry_completed": 1,
                "carry_manifest_sha_json_valid": True,
            },
            "linkage": {
                "daily_record_count": 9,
                "daily_unique_object_count": 9,
                "daily_unique_session_count": 9,
                "daily_unique_pair_count": 9,
                "combined_record_count": 10,
                "combined_unique_object_count": 10,
                "combined_unique_session_count": 10,
                "combined_unique_pair_count": 10,
                "matched_metadata_pairs": 10,
                "missing_metadata_pairs": 0,
                "orphan_timeseries_pairs": 0,
            },
            "valid_daily_chunks": day_count,
            "expected_daily_chunks": day_count,
            "metadata_source_inventory_sha256": sha["metadata_source"],
            "metadata_record_inventory_sha256": sha["metadata_record"],
            "official_reference_sha256": "7" * 64,
            "raw_file_count": 2 * (day_count + 1),
            "raw_inventory_sha256": sha["raw"],
            "raw_inventory_before_sha256": sha["raw"],
            "raw_inventory_after_sha256": sha["raw"],
            "partial_file_count": 0,
            "integrity": {
                "scope_verified": True,
                "official_reference_verified": True,
                "raw_snapshot_valid": True,
                "raw_unchanged": True,
                "linkage_exact": True,
                "partial_files_absent": True,
            },
        },
        "cleaning_qa.json": {
            "schema_version": "acn-jpl-seasonal-preparation-cleaning-qa/v1",
            "month": month,
            "status": "PASS",
            "sessions_processed": 10,
            "expected_sessions": 10,
            "cleaned_session_count": 9,
            "invalid_skipped_session_count": 1,
            "trajectory_quarantine": {
                "denominator_sessions": 10,
                "trajectory_quarantine_count": trajectory_quarantine_count,
                "trajectory_quarantine_rate": trajectory_quarantine_count / 10,
                "full_session_quarantine_count": 0,
                "full_session_quarantine_rate": 0.0,
                "synchronized_utc_nonmonotonic_sessions": trajectory_quarantine_count,
                "raw_trajectory_anomalies_retained": True,
                "raw_manifest_modified": False,
                "raw_timestamps_modified": False,
                "sort_repair_applied": False,
                "timestamp_shift_seconds": 0,
                "interpolation_applied": False,
                "whole_current_pilot_trajectory_unobservable": True,
                "coverage_denominator_includes_quarantined": True,
                "structural_metadata_retained_count": trajectory_quarantine_count,
                "connected_state_retained_count": trajectory_quarantine_count,
                "raw_field_coverage": {
                    "current": {"count": 9, "denominator": 10, "rate": 0.9},
                    "pilot": {"count": 10, "denominator": 10, "rate": 1.0},
                },
                "analysis_field_coverage": {
                    "current": {
                        "count": 9 - trajectory_quarantine_count,
                        "denominator": 10,
                        "rate": (9 - trajectory_quarantine_count) / 10,
                    },
                    "pilot": {
                        "count": 10 - trajectory_quarantine_count,
                        "denominator": 10,
                        "rate": (10 - trajectory_quarantine_count) / 10,
                    },
                },
            },
            "analysis_window": common_window,
            "sampling": {
                "derivation": "mode_of_positive_raw_timestamp_differences",
                "current_mode_seconds": 4,
                "pilot_mode_seconds": 4,
                "current_hold_seconds": 12,
                "pilot_hold_seconds": 12,
                "mode_multiplier": 3,
                "cap_seconds": 60,
            },
            "invalid_containers": {
                "denominator": 10,
                "charging_current": {"count": 1, "rate": 0.1, "limit": 0.1, "status": "PASS"},
                "pilot_signal": {"count": 0, "rate": 0.0, "limit": 0.1, "status": "PASS"},
            },
            "duplicate_conflict": {
                "exact_duplicate_policy": "retain_first_remove_extra",
                "conflict_main_policy": "mark_timestamp_missing",
                "conflict_sensitivity_policy": "last_write_wins",
                "current_conflicting_timestamps": 0,
                "pilot_conflicting_timestamps": 0,
            },
            "series": {
                name: {
                    "raw_samples": 9,
                    "usable_samples": 9,
                    "retained_samples": 9,
                    "retained_sample_rate": 1.0,
                    "invalid_timestamps": 0,
                    "invalid_values": 0,
                    "exact_duplicate_extras": 0,
                    "conflicting_timestamps": 0,
                    "conflict_affected_sessions": 0,
                    "nonmonotonic_pairs": trajectory_quarantine_count,
                    "nonmonotonic_sessions": trajectory_quarantine_count,
                    "bounded_observation_coverage": 1.0,
                    "bounded_value_hours": 0.0,
                }
                for name in ("current", "pilot")
            },
            "user_inputs": {
                "raw_revision_count": 0,
                "sanitized_revision_count": 0,
                "unparseable_modified_count": 0,
                "issue_time_truncation_ready": True,
            },
            "retrospective_done_time": {
                "present_count": 0,
                "parsed_count": 0,
                "unparseable_count": 0,
                "online_feature_allowed": False,
                "original_value_retained_locally": True,
            },
            "raw_modified": False,
        },
        "cleaning_sensitivity.json": {
            "schema_version": "acn-jpl-seasonal-preparation-cleaning-sensitivity/v1",
            "month": month,
            "status": "PASS",
            "main_hold_seconds": {"current": 12, "pilot": 12},
            "hold_thresholds_seconds": {"current": [4, 12, 60], "pilot": [4, 12, 60]},
            "hold_thresholds": {
                name: {str(hold): dict(integral) for hold in (4, 12, 60)}
                for name in ("current", "pilot")
            },
            "last_write_wins": {name: dict(comparison_integral) for name in ("current", "pilot")},
            "boundary_plus_minus_60_seconds": {
                name: dict(comparison_integral) for name in ("current", "pilot")
            },
            "boundary_sensitivity_seconds": 60,
            "last_write_wins_compared": True,
        },
        "boundary_current_audit.json": {
            "schema_version": "acn-jpl-seasonal-preparation-boundary-audit/v1",
            "month": month,
            "status": "PASS",
            "positive_points_excluded": 0,
            "sessions_affected": 0,
            "signed_distance_seconds": {
                "count": 0,
                "minimum": None,
                "p05": None,
                "median": None,
                "p95": None,
                "maximum": None,
            },
            "before_connection_count": 0,
            "at_or_after_disconnect_count": 0,
            "excluded_positive_ampere_seconds": 0.0,
            "raw_total_ampere_seconds": 0.0,
            "current_integral_share": 0.0,
            "sensitivity_window_seconds": 60,
            "main_result_excludes_boundary_points": True,
        },
        "power_semantics_audit.json": {
            "schema_version": "acn-jpl-seasonal-preparation-power-semantics/v1",
            "month": month,
            "status": "CURRENT_PROXY_ONLY",
            "legacy_classifier_status": "POWER_SEMANTICS_FAIL",
            "continue_current_pipeline": True,
            "e208_authorized": False,
            "reconstructed_kw_column_authorized": False,
            "current_proxy_available": True,
            "pinned_evidence": {
                "repository": "https://github.com/zach401/acnportal",
                "commit": "14e723b11339e56ca3afd2bf4969f9e4bc8c2623",
                "source_sha256": "0a8c9de3c972995dd323e3c2a976bff8511b795553f3926b60251b5418d6140d",
                "default_evse_voltage_v": 208.0,
                "line_to_line_network": True,
                "e208_formula": "E_208_kWh=208*ampere_hours/1000",
            },
            "mapping": {
                "raw_record_count": 9,
                "mapped_record_count": 9,
                "unmapped_record_count": 0,
                "mapping_rate": 1.0,
            },
            "primary_cohort": {
                "thresholds": {
                    "minimum_kwh_delivered": 0.5,
                    "minimum_current_coverage": 0.9,
                },
                "input_session_count": 9,
                "eligible_session_count": 0,
                "coverage_qualified_session_count": 0,
                "retained_session_count": 0,
                "audit_coverage": None,
                "retained_rate": None,
                "effective_voltage_v": {
                    "count": 0,
                    "q1": None,
                    "median": None,
                    "q3": None,
                    "iqr": None,
                },
                "e208_error": {
                    "count": 0,
                    "median_absolute_percentage_error": None,
                    "p90_absolute_percentage_error": None,
                },
                "aggregate_energy": {
                    "session_count": 0,
                    "observed_kwh": 0.0,
                    "e208_kwh": 0.0,
                    "error_kwh": 0.0,
                    "relative_error": None,
                    "absolute_relative_error": None,
                },
            },
            "statistics_finite": False,
            "privacy": {"aggregate_only": True, "identifiers_emitted": False},
        },
        "station_15min_qa.json": {
            "schema_version": "acn-jpl-seasonal-preparation-station-15min-qa/v1",
            "month": month,
            "status": "PASS",
            "grid_policy": "continuous_physical_utc",
            "station_columns": [
                "station_current_mean_a",
                "station_current_peak_a",
                "connected_session_count",
                "active_charging_session_count",
                "pilot_sum_a",
                "pilot_mean_a",
                "arrival_count",
                "disconnect_count",
                "observed_coverage_ratio",
                "valid_bin_80",
                "valid_bin_90",
                "valid_bin_95",
            ],
            "expected_bins": expected_bins,
            "generated_bins": expected_bins,
            "valid_bins_at_80": expected_bins,
            "valid_bins_at_90": valid_90,
            "valid_bins_at_95": valid_90,
            "pilot_valid_bins_at_80": expected_bins,
            "pilot_valid_bins_at_90": valid_90,
            "pilot_valid_bins_at_95": valid_90,
            "valid_bin_rate_at_80": 1.0,
            "valid_bin_rate_at_90": valid_90 / expected_bins,
            "valid_bin_rate_at_95": valid_90 / expected_bins,
            "missing_bin_rate_at_80": 0.0,
            "missing_bin_rate_at_90": 1 - valid_90 / expected_bins,
            "missing_bin_rate_at_95": 1 - valid_90 / expected_bins,
            "valid_bin_90_rate": valid_90 / expected_bins,
            "valid_bin_90_rate_min": 0.8,
            "valid_bin_90_gate": "PASS",
            "trajectory_quarantine_count": trajectory_quarantine_count,
            "coverage_denominator_includes_quarantined": True,
            "missing_bin_rate": 1 - valid_90 / expected_bins,
            "longest_missing_run": 0,
            "peak_current_proxy_a": 0.0,
            "max_absolute_ramp_a": 0.0,
            "weekday_distribution": {
                "bin_count": expected_bins,
                "valid_bin_count": valid_90,
                "mean_current_a": 0.0,
                "median_current_a": 0.0,
            },
            "weekend_distribution": {
                "bin_count": 0,
                "valid_bin_count": 0,
                "mean_current_a": None,
                "median_current_a": None,
            },
            "active_threshold_sensitivity": {
                "main_threshold_a": 0.1,
                "comparison_threshold_a": 1.0,
                "main_end_bin_count_sum": 0,
                "comparison_end_bin_count_sum": 0,
            },
            "aggregation_semantics": {
                "bin_rule": "left_closed_right_open",
                "missing_is_zero": False,
                "power_label_type": "none",
            },
            "dst_fold_extra_bins": 4 if month == "2019-11" else 0,
            "repeated_local_quarter_count": 4 if month == "2019-11" else 0,
            "time_weighted_integral_status": "PASS",
        },
        "issue_snapshot_qa.json": {
            "schema_version": "acn-jpl-seasonal-preparation-issue-snapshot-qa/v1",
            "month": month,
            "status": "PASS",
            "tiers": ["M1", "M2", "M3"],
            "lookback_minutes": 1440,
            "horizons_minutes": [15, 30, 60, 120, 240],
            "scheduled_issue_times": scheduled,
            "formal_issue_times": scheduled,
            "incomplete_label_issue_times": 0,
            "samples": {name: scheduled for name in ("M1", "M2", "M3")},
            "ragged_rows": {"M3": 9},
            "valid_labels_by_horizon": {
                str(horizon): scheduled for horizon in (15, 30, 60, 120, 240)
            },
            "shapes": {
                "M1_history": [scheduled, 96],
                "M2_dense": [scheduled, 6],
                "M3_ragged_rows": 9,
                "M3_session_feature_width": 11,
                "labels": [scheduled, 5],
            },
            "missing_rates": {
                name: 0.0
                for name in (
                    "M1_history",
                    "M2_station_current",
                    "M2_pilot_sum",
                    "M2_pilot_mean",
                    "M3_current_current",
                    "M3_elapsed_charging_time_proxy",
                    "M3_recent_current_mean",
                    "M3_recent_current_peak",
                    "M3_current_pilot",
                    "M3_cumulative_current_ah",
                    "M3_known_requested_departure",
                    "M3_known_requested_energy",
                )
            },
            "snapshot_sha256": sha["snapshot"],
            "m4_generated": False,
            "leakage_status": "PASS",
        },
        "leakage_audit.json": {
            "schema_version": "acn-jpl-seasonal-preparation-leakage-audit/v1",
            "month": month,
            "status": "PASS",
            "identifiers_emitted": False,
            "future_outcome_fields_emitted": False,
            "future_outcome_field_count": 0,
            "private_identifier_field_count": 0,
            "unexpected_feature_key_count": 0,
            "temporal_violation_count": 0,
            "late_user_input_rows": 0,
            "issue_time_user_input_status": "PASS",
            "connected_user_input_rows": 9,
            "known_user_input_rows": 0,
            "user_input_rule": "last modifiedAt at or before issue time",
            "feature_whitelist_status": "PASS",
        },
        "data_snapshot_manifest.json": {
            "schema_version": "acn-jpl-seasonal-preparation-data-snapshot/v1",
            "month": month,
            "status": "PASS",
            "config_sha256": sha["config"],
            "code_commit": "a" * 40,
            "metadata_source_inventory_sha256": sha["metadata_source"],
            "metadata_record_inventory_sha256": sha["metadata_record"],
            "raw_inventory_sha256": sha["raw"],
            "processed_snapshot_sha256": sha["processed"],
            "raw_dimensions": [195, 201, 311],
            "encoded_dimensions": [195, 204, 391],
            "local_artifact_count": 14,
            "trajectory_quarantine_count": trajectory_quarantine_count,
            "full_session_quarantine_count": 0,
            "anonymous_local_indexes_published": False,
            "large_arrays_published": False,
        },
        "run_manifest.json": {
            "schema_version": "acn-jpl-seasonal-preparation-run/v1",
            "month": month,
            "status": month_status,
            "raw_unchanged": True,
            "official_total": 9,
            "local_session_count": 9,
            "carry_in_count": 1,
            "sessions_processed": 10,
            "cleaned_session_count": 9,
            "invalid_skipped_session_count": 1,
            "trajectory_quarantine_count": trajectory_quarantine_count,
            "full_session_quarantine_count": 0,
            "station_bins": expected_bins,
            "valid_bin_90_count": valid_90,
            "scheduled_issue_times": scheduled,
            "formal_issue_times": scheduled,
            "power_semantics_status": "CURRENT_PROXY_ONLY",
            "ready_for_gate1_baseline": True,
            "scope": {"training": False, "network": False, "optimization": False},
            "privacy": {
                "aggregate_only": True,
                "private_values_emitted": False,
                "absolute_paths_emitted": False,
            },
        },
    }


def _month_result(month: str):
    from evcf.data.acn_jpl_month_config import jpl_month_config

    config = jpl_month_config(month)
    return build_month_preparation_result(
        config=config,
        documents=_month_documents(
            month, config.expected_bins, config.expected_scheduled_issue_times
        ),
    )


def _nonintegral_month_documents(month: str, *, rounded: bool) -> dict[str, object]:
    config = prep_module.jpl_month_config(month)
    documents = _month_documents(month, config.expected_bins, config.expected_scheduled_issue_times)
    combined, skipped, station_counts = {
        "2019-02": (1289, 2, (2646, 2640, 2638)),
        "2019-11": (1354, 6, (2775, 2769, 2762)),
    }[month]
    local = combined - 1
    acquisition = documents["acquisition_summary.json"]
    acquisition.update(
        official_total=local,
        local_session_count=local,
        combined_session_count=combined,
        trajectory_quarantine_rate=acquisition["trajectory_quarantine_count"] / combined,
    )
    acquisition["metadata_scope"].update(
        local_calendar_session_count=local,
        utc_calendar_session_count=local,
        left_boundary_count=0,
    )
    for name in acquisition["linkage"]:
        if name.startswith("daily_"):
            acquisition["linkage"][name] = local
        elif name.startswith("combined_") or name == "matched_metadata_pairs":
            acquisition["linkage"][name] = combined
    cleaning = documents["cleaning_qa.json"]
    cleaning.update(
        sessions_processed=combined,
        expected_sessions=combined,
        cleaned_session_count=combined - skipped,
        invalid_skipped_session_count=skipped,
    )
    quarantine = cleaning["trajectory_quarantine"]
    quarantine.update(
        denominator_sessions=combined,
        trajectory_quarantine_rate=quarantine["trajectory_quarantine_count"] / combined,
    )
    for coverage_name in ("raw_field_coverage", "analysis_field_coverage"):
        count = combined - skipped
        if coverage_name == "analysis_field_coverage":
            count -= quarantine["trajectory_quarantine_count"]
        for field_name in ("current", "pilot"):
            rate = count / combined
            quarantine[coverage_name][field_name] = {
                "count": count,
                "denominator": combined,
                "rate": round(rate, 8) if rounded else rate,
            }
    cleaning["invalid_containers"]["denominator"] = combined
    for field_name in ("charging_current", "pilot_signal"):
        cleaning["invalid_containers"][field_name].update(count=skipped, rate=skipped / combined)
    station = documents["station_15min_qa.json"]
    for threshold, count in zip((80, 90, 95), station_counts, strict=True):
        rate = count / config.expected_bins
        station[f"valid_bins_at_{threshold}"] = count
        station[f"pilot_valid_bins_at_{threshold}"] = count
        station[f"valid_bin_rate_at_{threshold}"] = round(rate, 8) if rounded else rate
        station[f"missing_bin_rate_at_{threshold}"] = (
            round(1 - rate, 8) if rounded else 1 - rate
        )
    station["valid_bin_90_rate"] = station_counts[1] / config.expected_bins
    station["missing_bin_rate"] = 1 - station["valid_bin_90_rate"]
    station["weekday_distribution"]["valid_bin_count"] = station_counts[1]
    documents["run_manifest.json"].update(
        official_total=local,
        local_session_count=local,
        sessions_processed=combined,
        cleaned_session_count=combined - skipped,
        invalid_skipped_session_count=skipped,
        valid_bin_90_count=station_counts[1],
    )
    return documents


@pytest.mark.parametrize("month", ("2019-02", "2019-11"))
@pytest.mark.parametrize("rounded", (False, True))
def test_compact_rates_preserve_counts_and_close_real_nonintegral_ratios(
    month: str, rounded: bool
) -> None:
    documents = _nonintegral_month_documents(month, rounded=rounded)
    original = copy.deepcopy(documents)
    config = prep_module.jpl_month_config(month)
    if rounded:
        with pytest.raises(SeasonalPreparationError, match="QUARANTINE_FIELD_COVERAGE_RATE_INVALID"):
            build_month_preparation_result(config=config, documents=documents)

    canonical = prep_module._canonicalize_compact_rates(documents)

    assert documents == original
    quarantine = canonical["cleaning_qa.json"]["trajectory_quarantine"]
    for coverage_name in ("raw_field_coverage", "analysis_field_coverage"):
        for field_name in ("current", "pilot"):
            coverage = quarantine[coverage_name][field_name]
            assert coverage["rate"] == coverage["count"] / coverage["denominator"]
    station = canonical["station_15min_qa.json"]
    for threshold in (80, 90, 95):
        rate = station[f"valid_bins_at_{threshold}"] / config.expected_bins
        assert station[f"valid_bin_rate_at_{threshold}"] == rate
        assert station[f"missing_bin_rate_at_{threshold}"] == 1 - rate
    result = build_month_preparation_result(config=config, documents=canonical)
    assert result.sessions_processed == (1289 if month == "2019-02" else 1354)
    assert result.trajectory_quarantine_count == (0 if month == "2019-02" else 1)


@pytest.mark.parametrize("coverage_name", ("raw_field_coverage", "analysis_field_coverage"))
@pytest.mark.parametrize("field_name", ("current", "pilot"))
@pytest.mark.parametrize("invalid_rate", (None, True, float("nan"), float("inf"), 0.5))
def test_compact_rates_reject_contradictory_coverage_rates(
    coverage_name: str, field_name: str, invalid_rate: object
) -> None:
    documents = _nonintegral_month_documents("2019-11", rounded=True)
    coverage = documents["cleaning_qa.json"]["trajectory_quarantine"][coverage_name][field_name]
    coverage["rate"] = invalid_rate

    with pytest.raises(SeasonalPreparationError):
        prep_module._canonicalize_compact_rates(documents)


@pytest.mark.parametrize("threshold", (80, 90, 95))
@pytest.mark.parametrize("rate_name", ("valid_bin_rate", "missing_bin_rate"))
def test_compact_rates_reject_contradictory_station_rates(threshold: int, rate_name: str) -> None:
    documents = _nonintegral_month_documents("2019-02", rounded=True)
    station = documents["station_15min_qa.json"]
    station[f"{rate_name}_at_{threshold}"] += 1e-7

    with pytest.raises(SeasonalPreparationError):
        prep_module._canonicalize_compact_rates(documents)


@pytest.mark.parametrize("invalid_count", (-1, True, 1.5, None, float("inf"), 9999))
@pytest.mark.parametrize("target", ("coverage_count", "coverage_denominator", "station_count"))
def test_compact_rates_reject_invalid_counts(target: str, invalid_count: object) -> None:
    documents = _nonintegral_month_documents("2019-02", rounded=True)
    if target == "station_count":
        documents["station_15min_qa.json"]["valid_bins_at_90"] = invalid_count
    else:
        coverage = documents["cleaning_qa.json"]["trajectory_quarantine"]["raw_field_coverage"]
        coverage["current"]["count" if target == "coverage_count" else "denominator"] = invalid_count

    with pytest.raises(SeasonalPreparationError):
        prep_module._canonicalize_compact_rates(documents)


def test_month_result_is_slots_frozen_and_enforces_both_main_gates() -> None:
    result = _month_result("2019-02")
    assert result.valid_bin_90_rate >= 0.8
    assert not hasattr(result, "__dict__")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        result.status = "FAIL"  # type: ignore[misc]

    documents = _month_documents("2019-02", 2688, 2577)
    documents["cleaning_qa.json"]["invalid_containers"]["charging_current"] = {  # type: ignore[index]
        "count": 2,
        "rate": 0.2,
        "limit": 0.1,
        "status": "PASS",
    }
    with pytest.raises(SeasonalPreparationError, match="INVALID_CONTAINER_RATE_EXCEEDED"):
        build_month_preparation_result(
            config=__import__("evcf.data.acn_jpl_month_config", fromlist=["FEB_2019"]).FEB_2019,
            documents=documents,
        )

    zero_invalid = _month_documents("2019-02", 2688, 2577)
    cleaning = zero_invalid["cleaning_qa.json"]
    run = zero_invalid["run_manifest.json"]
    cleaning["invalid_containers"]["charging_current"] = {  # type: ignore[index]
        "count": 0,
        "rate": 0.0,
        "limit": 0.1,
        "status": "PASS",
    }
    cleaning["cleaned_session_count"] = 10  # type: ignore[index]
    cleaning["invalid_skipped_session_count"] = 0  # type: ignore[index]
    cleaning["trajectory_quarantine"]["raw_field_coverage"]["current"] = {  # type: ignore[index]
        "count": 10,
        "denominator": 10,
        "rate": 1.0,
    }
    cleaning["trajectory_quarantine"]["analysis_field_coverage"]["current"] = {  # type: ignore[index]
        "count": 10,
        "denominator": 10,
        "rate": 1.0,
    }
    run["cleaned_session_count"] = 10  # type: ignore[index]
    run["invalid_skipped_session_count"] = 0  # type: ignore[index]
    assert (
        build_month_preparation_result(
            config=__import__("evcf.data.acn_jpl_month_config", fromlist=["FEB_2019"]).FEB_2019,
            documents=zero_invalid,
        ).cleaned_session_count
        == 10
    )


def test_release_is_exactly_37_files_deterministic_and_strictly_verified(
    tmp_path: Path,
) -> None:
    results = tuple(_month_result(month) for month in SEASONAL_MONTHS)
    publish_seasonal_release(results, tmp_path)
    first = {name: (tmp_path / name).read_bytes() for name in EXPECTED_RELEASE_PATHS}

    assert release_paths(tmp_path) == EXPECTED_RELEASE_PATHS
    assert verify_seasonal_release(tmp_path)
    publish_month_release(results[0], tmp_path)
    assert first == {name: (tmp_path / name).read_bytes() for name in EXPECTED_RELEASE_PATHS}
    publish_seasonal_release(results, tmp_path)
    assert first == {name: (tmp_path / name).read_bytes() for name in EXPECTED_RELEASE_PATHS}

    root_manifest = json.loads(
        (tmp_path / "seasonal_snapshot_manifest.json").read_text(encoding="utf-8")
    )
    november = root_manifest["month_snapshots"][2]
    assert november["status"] == "PASS_WITH_TRAJECTORY_QUARANTINE"
    assert november["trajectory_quarantine_count"] == 1
    assert november["full_session_quarantine_count"] == 0

    manifest = tmp_path / "2019-02" / "run_manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["privacy"]["token"] = "private"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert not verify_seasonal_release(tmp_path)


def _recursive_file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_full_publisher_restores_existing_release_when_install_and_cleanup_fail_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = tuple(_month_result(month) for month in SEASONAL_MONTHS)
    destination = tmp_path / "release"
    publish_month_release(results[0], destination)
    before = _recursive_file_bytes(destination)
    real_replace = prep_module.os.replace
    real_remove = prep_module._safe_remove_generated
    cleanup_failed = False

    def fail_install(source, target):  # type: ignore[no-untyped-def]
        if Path(source).name.startswith(".release.staging-") and Path(target) == destination:
            raise OSError("injected install failure")
        return real_replace(source, target)

    def fail_first_staging_cleanup(path, *, parent):  # type: ignore[no-untyped-def]
        nonlocal cleanup_failed
        if Path(path).name.startswith(".release.staging-") and not cleanup_failed:
            cleanup_failed = True
            raise OSError("injected cleanup failure")
        return real_remove(path, parent=parent)

    monkeypatch.setattr(prep_module.os, "replace", fail_install)
    monkeypatch.setattr(prep_module, "_safe_remove_generated", fail_first_staging_cleanup)

    with pytest.raises(OSError, match="injected install failure"):
        publish_seasonal_release(results, destination)

    assert destination.is_dir()
    assert _recursive_file_bytes(destination) == before
    assert not tuple(tmp_path.glob(".release.staging-*"))
    assert not tuple(tmp_path.glob(".release.backup-*"))


def test_full_publisher_restores_old_release_when_installed_tree_fails_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = tuple(_month_result(month) for month in SEASONAL_MONTHS)
    destination = tmp_path / "release"
    publish_month_release(results[0], destination)
    before = _recursive_file_bytes(destination)
    real_verify = prep_module.verify_seasonal_release
    rejected_installed_tree = False

    def reject_first_valid_destination(path):  # type: ignore[no-untyped-def]
        nonlocal rejected_installed_tree
        valid = real_verify(path)
        if Path(path) == destination and valid and not rejected_installed_tree:
            rejected_installed_tree = True
            return False
        return valid

    monkeypatch.setattr(
        prep_module,
        "verify_seasonal_release",
        reject_first_valid_destination,
    )

    with pytest.raises(SeasonalPreparationError, match="PUBLIC_INSTALL_INVALID"):
        publish_seasonal_release(results, destination)

    assert rejected_installed_tree
    assert destination.is_dir()
    assert _recursive_file_bytes(destination) == before
    assert not tuple(tmp_path.glob(".release.staging-*"))
    assert not tuple(tmp_path.glob(".release.backup-*"))


def test_full_publisher_commits_verified_new_tree_when_backup_cleanup_fails_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = tuple(_month_result(month) for month in SEASONAL_MONTHS)
    destination = tmp_path / "release"
    publish_month_release(results[0], destination)
    real_remove = prep_module._safe_remove_generated
    cleanup_failed = False

    def fail_first_backup_cleanup(path, *, parent):  # type: ignore[no-untyped-def]
        nonlocal cleanup_failed
        if (
            Path(path).name.startswith(".release.backup-")
            and Path(path).exists()
            and not cleanup_failed
        ):
            cleanup_failed = True
            raise OSError("injected backup cleanup failure")
        return real_remove(path, parent=parent)

    monkeypatch.setattr(prep_module, "_safe_remove_generated", fail_first_backup_cleanup)

    published = publish_seasonal_release(results, destination)

    assert published.months == results
    assert verify_seasonal_release(destination)
    assert release_paths(destination) == EXPECTED_RELEASE_PATHS
    assert not tuple(tmp_path.glob(".release.staging-*"))
    assert not tuple(tmp_path.glob(".release.backup-*"))


def test_full_publisher_never_restores_partially_deleted_backup_after_install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = tuple(_month_result(month) for month in SEASONAL_MONTHS)
    destination = tmp_path / "release"
    publish_month_release(results[0], destination)
    real_remove = prep_module._safe_remove_generated
    cleanup_failed = False

    def partially_delete_backup_then_fail(path, *, parent):  # type: ignore[no-untyped-def]
        nonlocal cleanup_failed
        candidate = Path(path)
        if (
            candidate.name.startswith(".release.backup-")
            and candidate.exists()
            and not cleanup_failed
        ):
            cleanup_failed = True
            (candidate / "2019-02" / "run_manifest.json").unlink()
            raise OSError("injected partial backup cleanup failure")
        return real_remove(candidate, parent=parent)

    monkeypatch.setattr(
        prep_module,
        "_safe_remove_generated",
        partially_delete_backup_then_fail,
    )

    published = publish_seasonal_release(results, destination)

    assert published.months == results
    assert verify_seasonal_release(destination)
    assert release_paths(destination) == EXPECTED_RELEASE_PATHS
    assert not tuple(tmp_path.glob(".release.staging-*"))
    assert not tuple(tmp_path.glob(".release.backup-*"))


def test_root_summary_and_report_cover_required_monthly_evidence_and_are_closed(
    tmp_path: Path,
) -> None:
    results = tuple(_month_result(month) for month in SEASONAL_MONTHS)
    publish_seasonal_release(results, tmp_path)
    summary = (tmp_path / "seasonal_prep_summary.csv").read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(summary))
    rows = list(reader)
    required_columns = {
        "month",
        "status",
        "local_session_count",
        "utc_calendar_session_count",
        "left_boundary_count",
        "right_boundary_count",
        "carry_in_count",
        "official_probe_request_count",
        "official_probe_timeseries",
        "daily_manifests_present",
        "daily_sha256_verified",
        "daily_json_valid",
        "carry_completed",
        "valid_daily_chunks",
        "expected_daily_chunks",
        "daily_unique_pair_count",
        "combined_unique_pair_count",
        "matched_metadata_pairs",
        "missing_metadata_pairs",
        "orphan_timeseries_pairs",
        "trajectory_quarantine_count",
        "trajectory_quarantine_rate",
        "full_session_quarantine_count",
        "full_session_quarantine_rate",
        "trajectory_current_raw_coverage_count",
        "trajectory_current_analysis_coverage_count",
        "trajectory_pilot_raw_coverage_count",
        "trajectory_pilot_analysis_coverage_count",
        "coverage_denominator_includes_quarantined",
        "whole_current_pilot_trajectory_unobservable",
        "raw_trajectory_anomalies_retained",
        "sort_repair_applied",
        "timestamp_shift_seconds",
        "interpolation_applied",
        "sessions_processed",
        "cleaned_session_count",
        "invalid_skipped_session_count",
        "charging_current_invalid_rate",
        "pilot_signal_invalid_rate",
        "current_raw_samples",
        "current_usable_samples",
        "current_retained_samples",
        "pilot_raw_samples",
        "pilot_usable_samples",
        "pilot_retained_samples",
        "current_retained_sample_rate",
        "pilot_retained_sample_rate",
        "current_exact_duplicate_extras",
        "pilot_exact_duplicate_extras",
        "current_conflicting_timestamps",
        "pilot_conflicting_timestamps",
        "boundary_positive_points_excluded",
        "boundary_excluded_positive_ampere_seconds",
        "boundary_raw_total_ampere_seconds",
        "boundary_current_integral_share",
        "current_boundary_60_relative_change",
        "pilot_boundary_60_relative_change",
        "current_mode_seconds",
        "pilot_mode_seconds",
        "retrospective_done_present_count",
        "retrospective_done_unparseable_count",
        "power_mapping_rate",
        "power_mapping_raw_record_count",
        "power_mapping_mapped_record_count",
        "power_minimum_kwh_delivered",
        "power_minimum_current_coverage",
        "power_eligible_session_count",
        "power_retained_session_count",
        "power_statistics_finite",
        "e208_authorized",
        "pinned_power_commit",
        "pinned_e208_formula",
        "effective_voltage_q1_v",
        "effective_voltage_median_v",
        "effective_voltage_q3_v",
        "effective_voltage_iqr_v",
        "median_absolute_percentage_error",
        "p90_absolute_percentage_error",
        "aggregate_relative_error",
        "station_bins",
        "valid_bin_80_count",
        "valid_bin_90_count",
        "valid_bin_95_count",
        "valid_bin_90_rate",
        "missing_bin_90_rate",
        "longest_missing_run",
        "peak_current_proxy_a",
        "max_absolute_ramp_a",
        "dst_fold_extra_bins",
        "grid_policy",
        "time_weighted_integral_status",
        "scheduled_issue_times",
        "formal_issue_times",
        "valid_labels_15_minutes",
        "valid_labels_240_minutes",
        "m1_sample_count",
        "m2_sample_count",
        "m3_sample_count",
        "raw_dimension_m1",
        "raw_dimension_m2",
        "raw_dimension_m3",
        "encoded_dimension_m1",
        "encoded_dimension_m2",
        "encoded_dimension_m3",
        "future_outcome_field_count",
        "private_identifier_field_count",
        "feature_whitelist_status",
        "snapshot_sha256",
        "metadata_source_inventory_sha256",
        "metadata_record_inventory_sha256",
        "official_reference_sha256",
        "raw_inventory_sha256",
        "raw_inventory_before_sha256",
        "raw_inventory_after_sha256",
        "processed_snapshot_sha256",
    }
    assert set(reader.fieldnames or ()) >= required_columns
    assert [row["month"] for row in rows] == list(SEASONAL_MONTHS)
    assert rows[0]["official_reference_sha256"] == "7" * 64
    assert rows[0]["raw_inventory_sha256"] == "4" * 64
    assert rows[0]["snapshot_sha256"] == "6" * 64
    assert rows[2]["trajectory_quarantine_count"] == "1"
    assert rows[2]["trajectory_current_raw_coverage_count"] == "9"
    assert rows[2]["trajectory_current_analysis_coverage_count"] == "8"

    report = (tmp_path / "seasonal_prep_report.md").read_text(encoding="utf-8")
    headings = [line for line in report.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Acquisition",
        "## Cleaning",
        "## Power semantics",
        "## 15-minute",
        "## M1-M3",
        "## Security",
        "## Decision",
    ]
    assert report.count("M4 generated: NO") == 1
    assert "PASS_WITH_TRAJECTORY_QUARANTINE" in report
    assert "Trajectory quarantine" in report
    for result in results:
        assert result.raw_inventory_sha256 in report
        assert result.processed_snapshot_sha256 in report

    tampered = summary.replace("2019-02", "2019-05", 1).encode("utf-8")
    (tmp_path / "seasonal_prep_summary.csv").write_bytes(tampered)
    checksums = (tmp_path / "SHA256SUMS").read_text(encoding="ascii")
    old_digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()
    new_digest = hashlib.sha256(tampered).hexdigest()
    (tmp_path / "SHA256SUMS").write_text(
        checksums.replace(old_digest, new_digest, 1),
        encoding="ascii",
        newline="",
    )
    assert not verify_seasonal_release(tmp_path)

    (tmp_path / "seasonal_prep_summary.csv").write_text(
        summary,
        encoding="utf-8",
        newline="",
    )
    report_bytes = report.encode("utf-8")
    tampered_report = report.replace("M4 generated: NO", "M4 generated: YES").encode("utf-8")
    (tmp_path / "seasonal_prep_report.md").write_bytes(tampered_report)
    (tmp_path / "SHA256SUMS").write_text(
        checksums.replace(
            hashlib.sha256(report_bytes).hexdigest(),
            hashlib.sha256(tampered_report).hexdigest(),
            1,
        ),
        encoding="ascii",
        newline="",
    )
    assert not verify_seasonal_release(tmp_path)


def test_implementation_binding_covers_dependencies_and_detects_each_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    required = {
        "environment-gate1-pilot.yml",
        "pyproject.toml",
        "code/src/evcf/__init__.py",
        "code/src/evcf/data/__init__.py",
        "code/src/evcf/data/acn_coverage.py",
        "code/src/evcf/data/acn_api.py",
        "code/src/evcf/data/acn_audit.py",
        "code/src/evcf/data/acn_jpl_gate0.py",
        "code/src/evcf/data/acn_jpl_preparation.py",
        "code/src/evcf/data/acn_jpl_official_reference.py",
        "code/src/evcf/data/acn_jpl_full_month_ts.py",
        "code/src/evcf/data/acn_jpl_trajectory_quarantine.py",
        "code/src/evcf/forecasting/__init__.py",
        "scripts/acquire_jpl_seasonal.py",
    }
    assert set(prep_module.IMPLEMENTATION_PATHS) >= required

    for drifted in prep_module.IMPLEMENTATION_PATHS:
        def fake_run(args, _drifted=drifted, **_kwargs):  # type: ignore[no-untyped-def]
            relative = args[2].split(":", 1)[1]
            content = (repo_root / relative).read_bytes()
            if relative == _drifted:
                content += b"\n# injected drift\n"
            return SimpleNamespace(returncode=0, stdout=content)

        monkeypatch.setattr(prep_module.subprocess, "run", fake_run)
        with pytest.raises(SeasonalPreparationError, match="IMPLEMENTATION_DRIFT"):
            prep_module.verify_implementation_commit("a" * 40, repo_root=repo_root)


def test_strict_loader_rejects_duplicate_keys_nan_and_extra_files(tmp_path: Path) -> None:
    results = tuple(_month_result(month) for month in SEASONAL_MONTHS)
    publish_seasonal_release(results, tmp_path)

    target = tmp_path / "2019-08" / "run_manifest.json"
    target.write_text('{"schema_version":"x","schema_version":"y"}', encoding="utf-8")
    assert not verify_seasonal_release(tmp_path)

    publish_root = tmp_path / "fresh"
    publish_seasonal_release(results, publish_root)
    (publish_root / "unexpected.json").write_text('{"x":NaN}', encoding="utf-8")
    assert not verify_seasonal_release(publish_root)


def test_existing_raw_is_reconstructed_and_current_process_sealed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_acn_jpl_seasonal_acquisition import _complete_february

    config, scope, raw_root, reference = _complete_february(tmp_path, monkeypatch)
    before = canonical_seasonal_inventory(raw_root)
    result = verify_existing_jpl_month(config=config, scope=scope, raw_root=raw_root)
    after = canonical_seasonal_inventory(raw_root)

    assert before == after
    assert result.status == "COMPLETE"
    assert verify_month_acquisition_result(
        result,
        config=config,
        scope=scope,
        inventory=after,
    )
    assert (
        verified_existing_official_reference_sha256(
            result,
            config=config,
            scope=scope,
            inventory=after,
            raw_root=raw_root,
        )
        == hashlib.sha256(reference.read_bytes()).hexdigest()
    )
    with pytest.raises(
        ExistingMonthVerificationError,
        match="EXISTING_MONTH_VERIFICATION_FAILED",
    ):
        verify_existing_jpl_month(
            config=config,
            scope=copy.copy(scope),
            raw_root=raw_root,
        )

    reference.write_text('{"schema_version":"changed"}', encoding="utf-8")
    with pytest.raises(ExistingMonthVerificationError):
        verified_existing_official_reference_sha256(
            result,
            config=config,
            scope=scope,
            inventory=after,
            raw_root=raw_root,
        )
    with pytest.raises(
        ExistingMonthVerificationError,
        match="EXISTING_MONTH_VERIFICATION_FAILED",
    ):
        verify_existing_jpl_month(config=config, scope=scope, raw_root=raw_root)


def test_prepare_month_runs_real_clean_station_snapshot_feature_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evcf.data import acn_jpl_15min as station_module
    from evcf.data import acn_jpl_cleaning as cleaning_module
    from evcf.data import acn_jpl_full_month_qa as full_qa_module
    from evcf.data.acn_jpl_15min import Station15MinResult
    from evcf.data.acn_jpl_cleaning import SamplingMode, SamplingModes
    from test_acn_jpl_seasonal_acquisition import _complete_february

    config, _scope, raw_root, _reference = _complete_february(tmp_path, monkeypatch)
    modes = SamplingModes(
        current=SamplingMode("chargingCurrent", 4, 1, ((4, 1),)),
        pilot=SamplingMode("pilotSignal", 4, 1, ((4, 1),)),
    )
    monkeypatch.setattr(cleaning_module, "derive_sampling_modes", lambda records: modes)
    real_aggregate = station_module.aggregate_station_15min

    def complete_station_rows(sessions, **kwargs):  # type: ignore[no-untyped-def]
        materialized = tuple(sessions)
        result = real_aggregate((), **kwargs)
        return Station15MinResult(
            rows=result.rows,
            qa={**result.qa, "session_count": len(materialized)},
        )

    monkeypatch.setattr(station_module, "aggregate_station_15min", complete_station_rows)
    monkeypatch.setattr(
        full_qa_module,
        "generate_month_timeseries_qa",
        lambda **kwargs: SimpleNamespace(
            gate_status="PASS",
            qa={
                "quality": {
                    "series": {
                            "chargingCurrent": {
                                "invalid_container_count": 0,
                                "usable_samples": 0,
                                "raw_field_coverage": {
                                    "count": 3,
                                    "denominator": 3,
                                    "rate": 1.0,
                                },
                                "analysis_field_coverage": {
                                    "count": 3,
                                    "denominator": 3,
                                    "rate": 1.0,
                                },
                                "nonmonotonic_pairs": 0,
                                "nonmonotonic_sessions": 0,
                            },
                            "pilotSignal": {
                                "invalid_container_count": 0,
                                "usable_samples": 0,
                                "raw_field_coverage": {
                                    "count": 3,
                                    "denominator": 3,
                                    "rate": 1.0,
                                },
                                "analysis_field_coverage": {
                                    "count": 3,
                                    "denominator": 3,
                                    "rate": 1.0,
                                },
                                "nonmonotonic_pairs": 0,
                                "nonmonotonic_sessions": 0,
                        },
                    }
                    },
                    "trajectory_quarantine": {
                        "denominator_sessions": 3,
                        "trajectory_quarantine_count": 0,
                        "trajectory_quarantine_rate": 0.0,
                        "full_session_quarantine_count": 0,
                        "full_session_quarantine_rate": 0.0,
                        "synchronized_utc_nonmonotonic_sessions": 0,
                        "raw_trajectory_anomalies_retained": True,
                        "raw_manifest_modified": False,
                        "raw_timestamps_modified": False,
                        "sort_repair_applied": False,
                        "timestamp_shift_seconds": 0,
                        "interpolation_applied": False,
                        "whole_current_pilot_trajectory_unobservable": True,
                        "coverage_denominator_includes_quarantined": True,
                        "structural_metadata_retained_count": 0,
                        "connected_state_retained_count": 0,
                    },
                    "integrity": {
                    "daily_chunks": {
                        "expected": 28,
                        "data_files_present": 28,
                        "manifests_present": 28,
                        "manifest_contracts_valid": 28,
                        "sha256_verified": 28,
                        "gzip_json_valid": 28,
                        "record_manifest_matches": 28,
                        "record_remote_matches": 28,
                        "valid": 28,
                    },
                    "combined": {
                        "matched_metadata_pairs": 3,
                        "missing_metadata_pairs": 0,
                        "orphan_timeseries_pairs": 0,
                    },
                },
            },
        ),
    )
    monkeypatch.setattr(prep_module, "verify_implementation_commit", lambda *a, **k: None)

    result = prep_module.prepare_jpl_seasonal_month(
        authorized=True,
        config=config,
        metadata_root=tmp_path / "metadata",
        raw_root=raw_root,
        interim_root=tmp_path / "interim",
        processed_root=tmp_path / "processed",
        code_commit="a" * 40,
    )

    assert result.month == "2019-02"
    assert result.sessions_processed == 3
    assert result.cleaned_session_count == 3
    assert result.invalid_skipped_session_count == 0
    assert result.station_bins == config.expected_bins
    assert result.grid_policy == config.grid_policy
    assert (tmp_path / "processed" / "m1.jsonl.gz").is_file()
    assert not any("m4" in path.name.lower() for path in tmp_path.rglob("*"))


def test_controller_uses_fixed_order_and_publishes_exact_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = tmp_path / "metadata"
    raw = tmp_path / "raw"
    metadata.mkdir()
    raw.mkdir()
    protocol = replace(
        prep_module.load_seasonal_preparation_protocol(),
        config_sha256="1" * 64,
    )
    calls: list[str] = []

    def fake_prepare(**kwargs):  # type: ignore[no-untyped-def]
        calls.append(kwargs["config"].month)
        return _month_result(kwargs["config"].month)

    monkeypatch.setattr(prep_module, "load_seasonal_preparation_protocol", lambda path: protocol)
    monkeypatch.setattr(prep_module, "verify_implementation_commit", lambda *a, **k: None)
    monkeypatch.setattr(prep_module, "_prepare_verified_month", fake_prepare)

    result = prep_module.prepare_jpl_seasonal_data(
        authorized=True,
        metadata_root=metadata,
        raw_root=raw,
        interim_root=tmp_path / "interim",
        processed_root=tmp_path / "processed",
        public_root=tmp_path / "public",
        code_commit="a" * 40,
    )

    assert calls == list(SEASONAL_MONTHS)
    assert result.status == "CONDITIONAL_PASS"
    assert release_paths(tmp_path / "public") == EXPECTED_RELEASE_PATHS


def test_controller_stops_unauthorized_before_path_or_loader_and_preserves_prior_month(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ForbiddenPath:
        def __fspath__(self) -> str:
            raise AssertionError("path conversion happened before authorization")

    with pytest.raises(SeasonalPreparationError, match="PREPARATION_NOT_AUTHORIZED"):
        prep_module.prepare_jpl_seasonal_data(
            authorized=False,
            metadata_root=ForbiddenPath(),  # type: ignore[arg-type]
            raw_root=ForbiddenPath(),  # type: ignore[arg-type]
            interim_root=ForbiddenPath(),  # type: ignore[arg-type]
            processed_root=ForbiddenPath(),  # type: ignore[arg-type]
            public_root=ForbiddenPath(),  # type: ignore[arg-type]
            code_commit="not-read",
            protocol_path=ForbiddenPath(),  # type: ignore[arg-type]
        )

    metadata = tmp_path / "metadata"
    raw = tmp_path / "raw"
    metadata.mkdir()
    raw.mkdir()
    protocol = replace(
        prep_module.load_seasonal_preparation_protocol(),
        config_sha256="1" * 64,
    )

    def fail_in_august(**kwargs):  # type: ignore[no-untyped-def]
        if kwargs["config"].month == "2019-08":
            raise SeasonalPreparationError("CLEANING_GATE_FAILED")
        return _month_result(kwargs["config"].month)

    monkeypatch.setattr(prep_module, "load_seasonal_preparation_protocol", lambda path: protocol)
    monkeypatch.setattr(prep_module, "verify_implementation_commit", lambda *a, **k: None)
    monkeypatch.setattr(prep_module, "_prepare_verified_month", fail_in_august)
    public = tmp_path / "public"
    with pytest.raises(SeasonalPreparationError, match="CLEANING_GATE_FAILED"):
        prep_module.prepare_jpl_seasonal_data(
            authorized=True,
            metadata_root=metadata,
            raw_root=raw,
            interim_root=tmp_path / "interim",
            processed_root=tmp_path / "processed",
            public_root=public,
            code_commit="a" * 40,
        )
    before = {
        path.relative_to(public).as_posix(): path.read_bytes()
        for path in (public / "2019-02").iterdir()
    }
    with pytest.raises(SeasonalPreparationError, match="CLEANING_GATE_FAILED"):
        prep_module.prepare_jpl_seasonal_data(
            authorized=True,
            metadata_root=metadata,
            raw_root=raw,
            interim_root=tmp_path / "interim",
            processed_root=tmp_path / "processed",
            public_root=public,
            code_commit="a" * 40,
        )
    assert before == {
        path.relative_to(public).as_posix(): path.read_bytes()
        for path in (public / "2019-02").iterdir()
    }


def test_controller_rejects_metadata_raw_output_overlap_without_mutation(
    tmp_path: Path,
) -> None:
    metadata = tmp_path / "metadata"
    raw = metadata / "raw"
    raw.mkdir(parents=True)
    marker = metadata / "must-remain.txt"
    marker.write_text("immutable", encoding="utf-8")

    with pytest.raises(SeasonalPreparationError, match="OUTPUT_TOPOLOGY_INVALID"):
        prep_module.prepare_jpl_seasonal_data(
            authorized=True,
            metadata_root=metadata,
            raw_root=raw,
            interim_root=tmp_path / "interim",
            processed_root=tmp_path / "processed",
            public_root=tmp_path / "public",
            code_commit="a" * 40,
        )
    assert marker.read_text(encoding="utf-8") == "immutable"
    assert not (tmp_path / "public").exists()
