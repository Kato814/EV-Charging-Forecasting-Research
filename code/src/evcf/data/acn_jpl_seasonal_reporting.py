"""Deterministic aggregate-only root reporting for seasonal JPL preparation."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from typing import Any

SEASONAL_MONTHS = ("2019-02", "2019-08", "2019-11")

SUMMARY_COLUMNS = (
    "month",
    "status",
    "official_total",
    "local_session_count",
    "utc_calendar_session_count",
    "left_boundary_count",
    "right_boundary_count",
    "carry_in_count",
    "combined_session_count",
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
    "official_probe_request_count",
    "official_probe_timeseries",
    "official_probe_total_matches_local",
    "official_probe_reference_valid",
    "daily_data_files_present",
    "daily_manifests_present",
    "daily_manifest_contracts_valid",
    "daily_sha256_verified",
    "daily_json_valid",
    "daily_record_manifest_matches",
    "daily_record_remote_matches",
    "carry_expected",
    "carry_completed",
    "carry_manifest_sha_json_valid",
    "valid_daily_chunks",
    "expected_daily_chunks",
    "daily_record_count",
    "daily_unique_object_count",
    "daily_unique_session_count",
    "daily_unique_pair_count",
    "combined_record_count",
    "combined_unique_object_count",
    "combined_unique_session_count",
    "combined_unique_pair_count",
    "matched_metadata_pairs",
    "missing_metadata_pairs",
    "orphan_timeseries_pairs",
    "raw_file_count",
    "partial_file_count",
    "raw_inventory_before_sha256",
    "raw_inventory_after_sha256",
    "scope_verified",
    "official_reference_verified",
    "raw_snapshot_valid",
    "raw_unchanged",
    "linkage_exact",
    "partial_files_absent",
    "sessions_processed",
    "cleaned_session_count",
    "invalid_skipped_session_count",
    "charging_current_invalid_count",
    "charging_current_invalid_rate",
    "pilot_signal_invalid_count",
    "pilot_signal_invalid_rate",
    "current_raw_samples",
    "current_usable_samples",
    "current_retained_samples",
    "current_retained_sample_rate",
    "current_invalid_timestamps",
    "current_invalid_values",
    "pilot_raw_samples",
    "pilot_usable_samples",
    "pilot_retained_samples",
    "pilot_retained_sample_rate",
    "pilot_invalid_timestamps",
    "pilot_invalid_values",
    "current_exact_duplicate_extras",
    "pilot_exact_duplicate_extras",
    "current_conflicting_timestamps",
    "pilot_conflicting_timestamps",
    "current_nonmonotonic_pairs",
    "current_nonmonotonic_sessions",
    "pilot_nonmonotonic_pairs",
    "pilot_nonmonotonic_sessions",
    "current_bounded_observation_coverage",
    "pilot_bounded_observation_coverage",
    "current_mode_seconds",
    "pilot_mode_seconds",
    "current_hold_seconds",
    "pilot_hold_seconds",
    "boundary_positive_points_excluded",
    "boundary_sessions_affected",
    "boundary_excluded_positive_ampere_seconds",
    "boundary_raw_total_ampere_seconds",
    "boundary_current_integral_share",
    "current_boundary_60_relative_change",
    "pilot_boundary_60_relative_change",
    "current_last_write_wins_relative_change",
    "pilot_last_write_wins_relative_change",
    "user_input_raw_revision_count",
    "user_input_sanitized_revision_count",
    "user_input_unparseable_modified_count",
    "issue_time_truncation_ready",
    "retrospective_done_present_count",
    "retrospective_done_parsed_count",
    "retrospective_done_unparseable_count",
    "retrospective_done_online_feature_allowed",
    "raw_modified",
    "power_semantics_status",
    "e208_authorized",
    "power_statistics_finite",
    "pinned_power_repository",
    "pinned_power_commit",
    "pinned_power_source_sha256",
    "pinned_default_evse_voltage_v",
    "pinned_line_to_line_network",
    "pinned_e208_formula",
    "power_mapping_raw_record_count",
    "power_mapping_mapped_record_count",
    "power_mapping_unmapped_record_count",
    "power_mapping_rate",
    "power_minimum_kwh_delivered",
    "power_minimum_current_coverage",
    "power_eligible_session_count",
    "power_coverage_qualified_session_count",
    "power_retained_session_count",
    "power_audit_coverage",
    "power_retained_rate",
    "effective_voltage_q1_v",
    "effective_voltage_median_v",
    "effective_voltage_q3_v",
    "effective_voltage_iqr_v",
    "median_absolute_percentage_error",
    "p90_absolute_percentage_error",
    "aggregate_observed_kwh",
    "aggregate_e208_kwh",
    "aggregate_error_kwh",
    "aggregate_relative_error",
    "aggregate_absolute_relative_error",
    "grid_policy",
    "station_column_count",
    "station_bins",
    "valid_bin_80_count",
    "valid_bin_90_count",
    "valid_bin_95_count",
    "pilot_valid_bin_80_count",
    "pilot_valid_bin_90_count",
    "pilot_valid_bin_95_count",
    "valid_bin_80_rate",
    "valid_bin_90_rate",
    "valid_bin_95_rate",
    "missing_bin_80_rate",
    "missing_bin_90_rate",
    "missing_bin_95_rate",
    "longest_missing_run",
    "peak_current_proxy_a",
    "max_absolute_ramp_a",
    "weekday_bin_count",
    "weekday_valid_bin_count",
    "weekday_mean_current_a",
    "weekday_median_current_a",
    "weekend_bin_count",
    "weekend_valid_bin_count",
    "weekend_mean_current_a",
    "weekend_median_current_a",
    "dst_fold_extra_bins",
    "repeated_local_quarter_count",
    "time_weighted_integral_status",
    "scheduled_issue_times",
    "formal_issue_times",
    "incomplete_label_issue_times",
    "valid_labels_15_minutes",
    "valid_labels_30_minutes",
    "valid_labels_60_minutes",
    "valid_labels_120_minutes",
    "valid_labels_240_minutes",
    "m1_sample_count",
    "m2_sample_count",
    "m3_sample_count",
    "m1_history_rows",
    "m1_history_width",
    "m2_dense_rows",
    "m2_dense_width",
    "m3_ragged_rows",
    "m3_session_feature_width",
    "label_rows",
    "label_width",
    "m1_history_missing_rate",
    "m2_station_current_missing_rate",
    "m2_pilot_sum_missing_rate",
    "m2_pilot_mean_missing_rate",
    "m3_current_current_missing_rate",
    "m3_recent_current_mean_missing_rate",
    "m3_recent_current_peak_missing_rate",
    "m3_current_pilot_missing_rate",
    "m3_known_requested_departure_missing_rate",
    "m3_known_requested_energy_missing_rate",
    "leakage_status",
    "late_user_input_rows",
    "temporal_violation_count",
    "future_outcome_field_count",
    "private_identifier_field_count",
    "unexpected_feature_key_count",
    "issue_time_user_input_status",
    "feature_whitelist_status",
    "raw_dimension_m1",
    "raw_dimension_m2",
    "raw_dimension_m3",
    "encoded_dimension_m1",
    "encoded_dimension_m2",
    "encoded_dimension_m3",
    "snapshot_sha256",
    "metadata_source_inventory_sha256",
    "metadata_record_inventory_sha256",
    "official_reference_sha256",
    "raw_inventory_sha256",
    "processed_snapshot_sha256",
    "config_sha256",
    "code_commit",
)


class SeasonalReportingError(ValueError):
    """Raised when a root report is not the one closed deterministic report."""

    def __init__(self) -> None:
        super().__init__("SEASONAL_REPORT_INVALID")


def _document(
    documents: Mapping[str, Mapping[str, Any]],
    name: str,
) -> Mapping[str, Any]:
    value = documents.get(name)
    if not isinstance(value, Mapping):
        raise SeasonalReportingError
    return value


def build_month_summary_row(
    documents: Mapping[str, Mapping[str, Any]],
) -> dict[str, object]:
    """Project one already-validated month document set into the closed root row."""

    try:
        acquisition = _document(documents, "acquisition_summary.json")
        cleaning = _document(documents, "cleaning_qa.json")
        sensitivity = _document(documents, "cleaning_sensitivity.json")
        boundary = _document(documents, "boundary_current_audit.json")
        power = _document(documents, "power_semantics_audit.json")
        station = _document(documents, "station_15min_qa.json")
        issue = _document(documents, "issue_snapshot_qa.json")
        leakage = _document(documents, "leakage_audit.json")
        snapshot = _document(documents, "data_snapshot_manifest.json")
        run = _document(documents, "run_manifest.json")
        scope = acquisition["metadata_scope"]
        official_probe = acquisition["official_probe"]
        chunks = acquisition["chunk_integrity"]
        linkage = acquisition["linkage"]
        integrity = acquisition["integrity"]
        quarantine = cleaning["trajectory_quarantine"]
        raw_coverage = quarantine["raw_field_coverage"]
        analysis_coverage = quarantine["analysis_field_coverage"]
        invalid = cleaning["invalid_containers"]
        series = cleaning["series"]
        sampling = cleaning["sampling"]
        user_inputs = cleaning["user_inputs"]
        retrospective = cleaning["retrospective_done_time"]
        plus_minus = sensitivity["boundary_plus_minus_60_seconds"]
        last_write = sensitivity["last_write_wins"]
        primary = power["primary_cohort"]
        power_evidence = power["pinned_evidence"]
        power_thresholds = primary["thresholds"]
        voltage = primary["effective_voltage_v"]
        error = primary["e208_error"]
        energy = primary["aggregate_energy"]
        weekday = station["weekday_distribution"]
        weekend = station["weekend_distribution"]
        labels = issue["valid_labels_by_horizon"]
        samples = issue["samples"]
        shapes = issue["shapes"]
        missing = issue["missing_rates"]
        row: dict[str, object] = {
            "month": run["month"],
            "status": run["status"],
            "official_total": acquisition["official_total"],
            "local_session_count": acquisition["local_session_count"],
            "utc_calendar_session_count": scope["utc_calendar_session_count"],
            "left_boundary_count": scope["left_boundary_count"],
            "right_boundary_count": scope["right_boundary_count"],
            "carry_in_count": acquisition["carry_in_count"],
            "combined_session_count": acquisition["combined_session_count"],
            "trajectory_quarantine_count": quarantine[
                "trajectory_quarantine_count"
            ],
            "trajectory_quarantine_rate": quarantine["trajectory_quarantine_rate"],
            "full_session_quarantine_count": quarantine[
                "full_session_quarantine_count"
            ],
            "full_session_quarantine_rate": quarantine[
                "full_session_quarantine_rate"
            ],
            "trajectory_current_raw_coverage_count": raw_coverage["current"]["count"],
            "trajectory_current_analysis_coverage_count": analysis_coverage["current"][
                "count"
            ],
            "trajectory_pilot_raw_coverage_count": raw_coverage["pilot"]["count"],
            "trajectory_pilot_analysis_coverage_count": analysis_coverage["pilot"][
                "count"
            ],
            "coverage_denominator_includes_quarantined": quarantine[
                "coverage_denominator_includes_quarantined"
            ],
            "whole_current_pilot_trajectory_unobservable": quarantine[
                "whole_current_pilot_trajectory_unobservable"
            ],
            "raw_trajectory_anomalies_retained": quarantine[
                "raw_trajectory_anomalies_retained"
            ],
            "sort_repair_applied": quarantine["sort_repair_applied"],
            "timestamp_shift_seconds": quarantine["timestamp_shift_seconds"],
            "interpolation_applied": quarantine["interpolation_applied"],
            "official_probe_request_count": official_probe["request_count"],
            "official_probe_timeseries": official_probe["timeseries"],
            "official_probe_total_matches_local": official_probe["total_matches_local"],
            "official_probe_reference_valid": official_probe["reference_valid"],
            "daily_data_files_present": chunks["daily_data_files_present"],
            "daily_manifests_present": chunks["daily_manifests_present"],
            "daily_manifest_contracts_valid": chunks["daily_manifest_contracts_valid"],
            "daily_sha256_verified": chunks["daily_sha256_verified"],
            "daily_json_valid": chunks["daily_json_valid"],
            "daily_record_manifest_matches": chunks["daily_record_manifest_matches"],
            "daily_record_remote_matches": chunks["daily_record_remote_matches"],
            "carry_expected": chunks["carry_expected"],
            "carry_completed": chunks["carry_completed"],
            "carry_manifest_sha_json_valid": chunks["carry_manifest_sha_json_valid"],
            "valid_daily_chunks": acquisition["valid_daily_chunks"],
            "expected_daily_chunks": acquisition["expected_daily_chunks"],
            "daily_record_count": linkage["daily_record_count"],
            "daily_unique_object_count": linkage["daily_unique_object_count"],
            "daily_unique_session_count": linkage["daily_unique_session_count"],
            "daily_unique_pair_count": linkage["daily_unique_pair_count"],
            "combined_record_count": linkage["combined_record_count"],
            "combined_unique_object_count": linkage["combined_unique_object_count"],
            "combined_unique_session_count": linkage["combined_unique_session_count"],
            "combined_unique_pair_count": linkage["combined_unique_pair_count"],
            "matched_metadata_pairs": linkage["matched_metadata_pairs"],
            "missing_metadata_pairs": linkage["missing_metadata_pairs"],
            "orphan_timeseries_pairs": linkage["orphan_timeseries_pairs"],
            "raw_file_count": acquisition["raw_file_count"],
            "partial_file_count": acquisition["partial_file_count"],
            "raw_inventory_before_sha256": acquisition["raw_inventory_before_sha256"],
            "raw_inventory_after_sha256": acquisition["raw_inventory_after_sha256"],
            "scope_verified": integrity["scope_verified"],
            "official_reference_verified": integrity["official_reference_verified"],
            "raw_snapshot_valid": integrity["raw_snapshot_valid"],
            "raw_unchanged": integrity["raw_unchanged"],
            "linkage_exact": integrity["linkage_exact"],
            "partial_files_absent": integrity["partial_files_absent"],
            "sessions_processed": cleaning["sessions_processed"],
            "cleaned_session_count": cleaning["cleaned_session_count"],
            "invalid_skipped_session_count": cleaning["invalid_skipped_session_count"],
            "charging_current_invalid_count": invalid["charging_current"]["count"],
            "charging_current_invalid_rate": invalid["charging_current"]["rate"],
            "pilot_signal_invalid_count": invalid["pilot_signal"]["count"],
            "pilot_signal_invalid_rate": invalid["pilot_signal"]["rate"],
            "current_raw_samples": series["current"]["raw_samples"],
            "current_usable_samples": series["current"]["usable_samples"],
            "current_retained_samples": series["current"]["retained_samples"],
            "current_retained_sample_rate": series["current"]["retained_sample_rate"],
            "current_invalid_timestamps": series["current"]["invalid_timestamps"],
            "current_invalid_values": series["current"]["invalid_values"],
            "pilot_raw_samples": series["pilot"]["raw_samples"],
            "pilot_usable_samples": series["pilot"]["usable_samples"],
            "pilot_retained_samples": series["pilot"]["retained_samples"],
            "pilot_retained_sample_rate": series["pilot"]["retained_sample_rate"],
            "pilot_invalid_timestamps": series["pilot"]["invalid_timestamps"],
            "pilot_invalid_values": series["pilot"]["invalid_values"],
            "current_exact_duplicate_extras": series["current"]["exact_duplicate_extras"],
            "pilot_exact_duplicate_extras": series["pilot"]["exact_duplicate_extras"],
            "current_conflicting_timestamps": series["current"]["conflicting_timestamps"],
            "pilot_conflicting_timestamps": series["pilot"]["conflicting_timestamps"],
            "current_nonmonotonic_pairs": series["current"]["nonmonotonic_pairs"],
            "current_nonmonotonic_sessions": series["current"]["nonmonotonic_sessions"],
            "pilot_nonmonotonic_pairs": series["pilot"]["nonmonotonic_pairs"],
            "pilot_nonmonotonic_sessions": series["pilot"]["nonmonotonic_sessions"],
            "current_bounded_observation_coverage": series["current"][
                "bounded_observation_coverage"
            ],
            "pilot_bounded_observation_coverage": series["pilot"][
                "bounded_observation_coverage"
            ],
            "current_mode_seconds": sampling["current_mode_seconds"],
            "pilot_mode_seconds": sampling["pilot_mode_seconds"],
            "current_hold_seconds": sampling["current_hold_seconds"],
            "pilot_hold_seconds": sampling["pilot_hold_seconds"],
            "boundary_positive_points_excluded": boundary["positive_points_excluded"],
            "boundary_sessions_affected": boundary["sessions_affected"],
            "boundary_excluded_positive_ampere_seconds": boundary[
                "excluded_positive_ampere_seconds"
            ],
            "boundary_raw_total_ampere_seconds": boundary["raw_total_ampere_seconds"],
            "boundary_current_integral_share": boundary["current_integral_share"],
            "current_boundary_60_relative_change": plus_minus["current"][
                "relative_value_hours_change"
            ],
            "pilot_boundary_60_relative_change": plus_minus["pilot"][
                "relative_value_hours_change"
            ],
            "current_last_write_wins_relative_change": last_write["current"][
                "relative_value_hours_change"
            ],
            "pilot_last_write_wins_relative_change": last_write["pilot"][
                "relative_value_hours_change"
            ],
            "user_input_raw_revision_count": user_inputs["raw_revision_count"],
            "user_input_sanitized_revision_count": user_inputs["sanitized_revision_count"],
            "user_input_unparseable_modified_count": user_inputs[
                "unparseable_modified_count"
            ],
            "issue_time_truncation_ready": user_inputs["issue_time_truncation_ready"],
            "retrospective_done_present_count": retrospective["present_count"],
            "retrospective_done_parsed_count": retrospective["parsed_count"],
            "retrospective_done_unparseable_count": retrospective["unparseable_count"],
            "retrospective_done_online_feature_allowed": retrospective[
                "online_feature_allowed"
            ],
            "raw_modified": cleaning["raw_modified"],
            "power_semantics_status": power["status"],
            "e208_authorized": power["e208_authorized"],
            "power_statistics_finite": power["statistics_finite"],
            "pinned_power_repository": power_evidence["repository"],
            "pinned_power_commit": power_evidence["commit"],
            "pinned_power_source_sha256": power_evidence["source_sha256"],
            "pinned_default_evse_voltage_v": power_evidence["default_evse_voltage_v"],
            "pinned_line_to_line_network": power_evidence["line_to_line_network"],
            "pinned_e208_formula": power_evidence["e208_formula"],
            "power_mapping_raw_record_count": power["mapping"]["raw_record_count"],
            "power_mapping_mapped_record_count": power["mapping"]["mapped_record_count"],
            "power_mapping_unmapped_record_count": power["mapping"][
                "unmapped_record_count"
            ],
            "power_mapping_rate": power["mapping"]["mapping_rate"],
            "power_minimum_kwh_delivered": power_thresholds["minimum_kwh_delivered"],
            "power_minimum_current_coverage": power_thresholds[
                "minimum_current_coverage"
            ],
            "power_eligible_session_count": primary["eligible_session_count"],
            "power_coverage_qualified_session_count": primary[
                "coverage_qualified_session_count"
            ],
            "power_retained_session_count": primary["retained_session_count"],
            "power_audit_coverage": primary["audit_coverage"],
            "power_retained_rate": primary["retained_rate"],
            "effective_voltage_q1_v": voltage["q1"],
            "effective_voltage_median_v": voltage["median"],
            "effective_voltage_q3_v": voltage["q3"],
            "effective_voltage_iqr_v": voltage["iqr"],
            "median_absolute_percentage_error": error[
                "median_absolute_percentage_error"
            ],
            "p90_absolute_percentage_error": error["p90_absolute_percentage_error"],
            "aggregate_observed_kwh": energy["observed_kwh"],
            "aggregate_e208_kwh": energy["e208_kwh"],
            "aggregate_error_kwh": energy["error_kwh"],
            "aggregate_relative_error": energy["relative_error"],
            "aggregate_absolute_relative_error": energy["absolute_relative_error"],
            "grid_policy": station["grid_policy"],
            "station_column_count": len(station["station_columns"]),
            "station_bins": station["generated_bins"],
            "valid_bin_80_count": station["valid_bins_at_80"],
            "valid_bin_90_count": station["valid_bins_at_90"],
            "valid_bin_95_count": station["valid_bins_at_95"],
            "pilot_valid_bin_80_count": station["pilot_valid_bins_at_80"],
            "pilot_valid_bin_90_count": station["pilot_valid_bins_at_90"],
            "pilot_valid_bin_95_count": station["pilot_valid_bins_at_95"],
            "valid_bin_80_rate": station["valid_bin_rate_at_80"],
            "valid_bin_90_rate": station["valid_bin_rate_at_90"],
            "valid_bin_95_rate": station["valid_bin_rate_at_95"],
            "missing_bin_80_rate": station["missing_bin_rate_at_80"],
            "missing_bin_90_rate": station["missing_bin_rate_at_90"],
            "missing_bin_95_rate": station["missing_bin_rate_at_95"],
            "longest_missing_run": station["longest_missing_run"],
            "peak_current_proxy_a": station["peak_current_proxy_a"],
            "max_absolute_ramp_a": station["max_absolute_ramp_a"],
            "weekday_bin_count": weekday["bin_count"],
            "weekday_valid_bin_count": weekday["valid_bin_count"],
            "weekday_mean_current_a": weekday["mean_current_a"],
            "weekday_median_current_a": weekday["median_current_a"],
            "weekend_bin_count": weekend["bin_count"],
            "weekend_valid_bin_count": weekend["valid_bin_count"],
            "weekend_mean_current_a": weekend["mean_current_a"],
            "weekend_median_current_a": weekend["median_current_a"],
            "dst_fold_extra_bins": station["dst_fold_extra_bins"],
            "repeated_local_quarter_count": station["repeated_local_quarter_count"],
            "time_weighted_integral_status": station["time_weighted_integral_status"],
            "scheduled_issue_times": issue["scheduled_issue_times"],
            "formal_issue_times": issue["formal_issue_times"],
            "incomplete_label_issue_times": issue["incomplete_label_issue_times"],
            "valid_labels_15_minutes": labels["15"],
            "valid_labels_30_minutes": labels["30"],
            "valid_labels_60_minutes": labels["60"],
            "valid_labels_120_minutes": labels["120"],
            "valid_labels_240_minutes": labels["240"],
            "m1_sample_count": samples["M1"],
            "m2_sample_count": samples["M2"],
            "m3_sample_count": samples["M3"],
            "m1_history_rows": shapes["M1_history"][0],
            "m1_history_width": shapes["M1_history"][1],
            "m2_dense_rows": shapes["M2_dense"][0],
            "m2_dense_width": shapes["M2_dense"][1],
            "m3_ragged_rows": shapes["M3_ragged_rows"],
            "m3_session_feature_width": shapes["M3_session_feature_width"],
            "label_rows": shapes["labels"][0],
            "label_width": shapes["labels"][1],
            "m1_history_missing_rate": missing["M1_history"],
            "m2_station_current_missing_rate": missing["M2_station_current"],
            "m2_pilot_sum_missing_rate": missing["M2_pilot_sum"],
            "m2_pilot_mean_missing_rate": missing["M2_pilot_mean"],
            "m3_current_current_missing_rate": missing["M3_current_current"],
            "m3_recent_current_mean_missing_rate": missing["M3_recent_current_mean"],
            "m3_recent_current_peak_missing_rate": missing["M3_recent_current_peak"],
            "m3_current_pilot_missing_rate": missing["M3_current_pilot"],
            "m3_known_requested_departure_missing_rate": missing[
                "M3_known_requested_departure"
            ],
            "m3_known_requested_energy_missing_rate": missing[
                "M3_known_requested_energy"
            ],
            "leakage_status": leakage["status"],
            "late_user_input_rows": leakage["late_user_input_rows"],
            "temporal_violation_count": leakage["temporal_violation_count"],
            "future_outcome_field_count": leakage["future_outcome_field_count"],
            "private_identifier_field_count": leakage["private_identifier_field_count"],
            "unexpected_feature_key_count": leakage["unexpected_feature_key_count"],
            "issue_time_user_input_status": leakage["issue_time_user_input_status"],
            "feature_whitelist_status": leakage["feature_whitelist_status"],
            "raw_dimension_m1": snapshot["raw_dimensions"][0],
            "raw_dimension_m2": snapshot["raw_dimensions"][1],
            "raw_dimension_m3": snapshot["raw_dimensions"][2],
            "encoded_dimension_m1": snapshot["encoded_dimensions"][0],
            "encoded_dimension_m2": snapshot["encoded_dimensions"][1],
            "encoded_dimension_m3": snapshot["encoded_dimensions"][2],
            "snapshot_sha256": issue["snapshot_sha256"],
            "metadata_source_inventory_sha256": acquisition[
                "metadata_source_inventory_sha256"
            ],
            "metadata_record_inventory_sha256": acquisition[
                "metadata_record_inventory_sha256"
            ],
            "official_reference_sha256": acquisition["official_reference_sha256"],
            "raw_inventory_sha256": acquisition["raw_inventory_sha256"],
            "processed_snapshot_sha256": snapshot["processed_snapshot_sha256"],
            "config_sha256": snapshot["config_sha256"],
            "code_commit": snapshot["code_commit"],
        }
    except (KeyError, IndexError, TypeError) as exc:
        raise SeasonalReportingError from exc
    if tuple(row) != SUMMARY_COLUMNS:
        raise AssertionError("seasonal summary column drift")
    return row


def _csv_value(value: object) -> str:
    if value is None:
        return ""
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in (int, float):
        return json.dumps(value, allow_nan=False, separators=(",", ":"))
    if isinstance(value, str):
        return value
    raise SeasonalReportingError


def render_summary_csv(rows: Sequence[Mapping[str, object]]) -> bytes:
    """Render three closed month rows with stable columns and scalar encoding."""

    materialized = tuple(rows)
    if (
        tuple(row.get("month") for row in materialized) != SEASONAL_MONTHS
        or any(tuple(row) != SUMMARY_COLUMNS for row in materialized)
    ):
        raise SeasonalReportingError
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(SUMMARY_COLUMNS)
    for row in materialized:
        writer.writerow(tuple(_csv_value(row[name]) for name in SUMMARY_COLUMNS))
    return stream.getvalue().encode("utf-8")


def validate_summary_csv(
    content: bytes,
    expected_rows: Sequence[Mapping[str, object]],
) -> None:
    """Parse the CSV as a closed table and bind it to the month documents."""

    try:
        text = content.decode("utf-8")
        parsed = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except (UnicodeError, csv.Error) as exc:
        raise SeasonalReportingError from exc
    if (
        len(parsed) != 4
        or tuple(parsed[0]) != SUMMARY_COLUMNS
        or any(len(row) != len(SUMMARY_COLUMNS) for row in parsed[1:])
        or content != render_summary_csv(expected_rows)
    ):
        raise SeasonalReportingError


def _display(value: object) -> str:
    rendered = _csv_value(value)
    return rendered if rendered else "NA"


def _table(
    rows: Sequence[Mapping[str, object]],
    columns: Sequence[tuple[str, str]],
) -> list[str]:
    lines = [
        "| " + " | ".join(label for _name, label in columns) + " |",
        "| " + " | ".join("---" for _name, _label in columns) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_display(row[name]) for name, _label in columns) + " |"
        for row in rows
    )
    return lines


def render_report_markdown(
    rows: Sequence[Mapping[str, object]],
    *,
    status: str,
    config_sha256: str,
    code_commit: str,
) -> bytes:
    """Render the fixed seven-section human-readable aggregate report."""

    materialized = tuple(rows)
    render_summary_csv(materialized)
    lines = [
        "# JPL seasonal preparation report",
        "",
        f"Status: {status}",
        "Months: 2019-02, 2019-08, 2019-11",
        "",
        "## Acquisition",
        "",
        *_table(
            materialized,
            (
                ("month", "Month"),
                ("official_total", "Official"),
                ("official_probe_request_count", "Probe requests"),
                ("local_session_count", "Local"),
                ("utc_calendar_session_count", "UTC"),
                ("left_boundary_count", "Left"),
                ("right_boundary_count", "Right"),
                ("carry_in_count", "Carry"),
                ("carry_completed", "Carry complete"),
                ("valid_daily_chunks", "Valid chunks"),
                ("expected_daily_chunks", "Expected chunks"),
                ("matched_metadata_pairs", "Matched"),
                ("missing_metadata_pairs", "Missing"),
                ("orphan_timeseries_pairs", "Orphan"),
            ),
        ),
        "",
        "## Cleaning",
        "",
        *_table(
            materialized,
            (
                ("month", "Month"),
                ("sessions_processed", "Attempted"),
                ("cleaned_session_count", "Cleaned"),
                ("invalid_skipped_session_count", "Skipped"),
                ("charging_current_invalid_rate", "Current invalid rate"),
                ("pilot_signal_invalid_rate", "Pilot invalid rate"),
                ("current_raw_samples", "Current raw"),
                ("current_usable_samples", "Current usable"),
                ("current_retained_samples", "Current retained"),
                ("current_retained_sample_rate", "Current retained rate"),
                ("pilot_raw_samples", "Pilot raw"),
                ("pilot_usable_samples", "Pilot usable"),
                ("pilot_retained_samples", "Pilot retained"),
                ("pilot_retained_sample_rate", "Pilot retained rate"),
            ),
        ),
        "",
        "### Trajectory quarantine",
        "",
        *_table(
            materialized,
            (
                ("month", "Month"),
                ("trajectory_quarantine_count", "Trajectory quarantine"),
                ("full_session_quarantine_count", "Full-session quarantine"),
                ("trajectory_current_raw_coverage_count", "Current raw coverage"),
                (
                    "trajectory_current_analysis_coverage_count",
                    "Current analysis coverage",
                ),
                ("trajectory_pilot_raw_coverage_count", "Pilot raw coverage"),
                (
                    "trajectory_pilot_analysis_coverage_count",
                    "Pilot analysis coverage",
                ),
                (
                    "coverage_denominator_includes_quarantined",
                    "Quarantine in denominator",
                ),
                ("raw_trajectory_anomalies_retained", "Raw retained"),
                ("sort_repair_applied", "Sort repair"),
                ("timestamp_shift_seconds", "Timestamp shift s"),
                ("interpolation_applied", "Interpolation"),
            ),
        ),
        "",
        *_table(
            materialized,
            (
                ("month", "Month"),
                ("current_exact_duplicate_extras", "Current duplicate extras"),
                ("pilot_exact_duplicate_extras", "Pilot duplicate extras"),
                ("current_conflicting_timestamps", "Current conflicts"),
                ("pilot_conflicting_timestamps", "Pilot conflicts"),
                ("boundary_positive_points_excluded", "Boundary points"),
                ("boundary_sessions_affected", "Boundary sessions"),
                ("boundary_current_integral_share", "Boundary integral share"),
                ("current_boundary_60_relative_change", "Current boundary +/-60"),
                ("pilot_boundary_60_relative_change", "Pilot boundary +/-60"),
                ("current_mode_seconds", "Current mode s"),
                ("pilot_mode_seconds", "Pilot mode s"),
                ("current_hold_seconds", "Current hold s"),
                ("pilot_hold_seconds", "Pilot hold s"),
                ("issue_time_truncation_ready", "User-input truncation"),
            ),
        ),
        "",
        "## Power semantics",
        "",
        *_table(
            materialized,
            (
                ("month", "Month"),
                ("power_semantics_status", "Status"),
                ("e208_authorized", "E208 authorized"),
                ("pinned_power_commit", "Pinned commit"),
                ("pinned_e208_formula", "Pinned formula"),
                ("power_mapping_rate", "Mapping rate"),
                ("power_minimum_kwh_delivered", "Minimum kWh"),
                ("power_minimum_current_coverage", "Minimum coverage"),
                ("power_eligible_session_count", "Eligible"),
                ("power_retained_session_count", "Retained"),
                ("power_retained_rate", "Retained rate"),
                ("effective_voltage_q1_v", "Voltage Q1"),
                ("effective_voltage_median_v", "Voltage median"),
                ("effective_voltage_q3_v", "Voltage Q3"),
                ("effective_voltage_iqr_v", "Voltage IQR"),
                ("median_absolute_percentage_error", "MdAPE"),
                ("p90_absolute_percentage_error", "P90 APE"),
                ("aggregate_relative_error", "Aggregate relative error"),
            ),
        ),
        "",
        "## 15-minute",
        "",
        *_table(
            materialized,
            (
                ("month", "Month"),
                ("station_bins", "Bins"),
                ("valid_bin_80_count", "Valid 80"),
                ("valid_bin_90_count", "Valid 90"),
                ("valid_bin_95_count", "Valid 95"),
                ("valid_bin_80_rate", "Valid 80 rate"),
                ("valid_bin_90_rate", "Valid 90 rate"),
                ("valid_bin_95_rate", "Valid 95 rate"),
                ("missing_bin_80_rate", "Missing 80 rate"),
                ("missing_bin_90_rate", "Missing 90 rate"),
                ("missing_bin_95_rate", "Missing 95 rate"),
                ("longest_missing_run", "Longest missing"),
                ("peak_current_proxy_a", "Peak current"),
                ("max_absolute_ramp_a", "Max ramp"),
                ("dst_fold_extra_bins", "DST extra bins"),
                ("time_weighted_integral_status", "Integral status"),
            ),
        ),
        "",
        *_table(
            materialized,
            (
                ("month", "Month"),
                ("weekday_bin_count", "Weekday bins"),
                ("weekday_valid_bin_count", "Weekday valid"),
                ("weekday_mean_current_a", "Weekday mean"),
                ("weekday_median_current_a", "Weekday median"),
                ("weekend_bin_count", "Weekend bins"),
                ("weekend_valid_bin_count", "Weekend valid"),
                ("weekend_mean_current_a", "Weekend mean"),
                ("weekend_median_current_a", "Weekend median"),
            ),
        ),
        "",
        "## M1-M3",
        "",
        *_table(
            materialized,
            (
                ("month", "Month"),
                ("scheduled_issue_times", "Scheduled"),
                ("formal_issue_times", "Formal"),
                ("valid_labels_15_minutes", "Labels 15"),
                ("valid_labels_240_minutes", "Labels 240"),
                ("m1_sample_count", "M1"),
                ("m2_sample_count", "M2"),
                ("m3_sample_count", "M3"),
                ("m1_history_width", "M1 width"),
                ("m2_dense_width", "M2 width"),
                ("m3_session_feature_width", "M3 width"),
                ("encoded_dimension_m1", "M1 encoded"),
                ("encoded_dimension_m2", "M2 encoded"),
                ("encoded_dimension_m3", "M3 encoded"),
                ("temporal_violation_count", "Leakage violations"),
            ),
        ),
        "",
        *_table(
            materialized,
            (
                ("month", "Month"),
                ("m1_history_missing_rate", "M1 history missing"),
                ("m2_station_current_missing_rate", "M2 current missing"),
                ("m2_pilot_sum_missing_rate", "M2 pilot sum missing"),
                ("m2_pilot_mean_missing_rate", "M2 pilot mean missing"),
                ("m3_current_current_missing_rate", "M3 current missing"),
                ("m3_recent_current_mean_missing_rate", "M3 recent mean missing"),
                ("m3_recent_current_peak_missing_rate", "M3 recent peak missing"),
                ("m3_current_pilot_missing_rate", "M3 pilot missing"),
                (
                    "m3_known_requested_departure_missing_rate",
                    "M3 departure missing",
                ),
                ("m3_known_requested_energy_missing_rate", "M3 energy missing"),
                ("feature_whitelist_status", "Feature whitelist"),
            ),
        ),
        "",
        "## Security",
        "",
        "Aggregate-only evidence: YES",
        "Raw inventories unchanged: YES",
        "Network access: NO",
        "Training executed: NO",
        "M4 generated: NO",
        f"Config SHA256: {config_sha256}",
        f"Code commit: {code_commit}",
    ]
    for row in materialized:
        lines.extend(
            (
                f"{row['month']} metadata source SHA256: {row['metadata_source_inventory_sha256']}",
                f"{row['month']} metadata record SHA256: {row['metadata_record_inventory_sha256']}",
                f"{row['month']} official reference SHA256: {row['official_reference_sha256']}",
                f"{row['month']} raw SHA256: {row['raw_inventory_sha256']}",
                f"{row['month']} processed SHA256: {row['processed_snapshot_sha256']}",
                f"{row['month']} snapshot SHA256: {row['snapshot_sha256']}",
            )
        )
    lines.extend(
        (
            "",
            "## Decision",
            "",
            *_table(
                materialized,
                (
                    ("month", "Month"),
                    ("status", "Preparation status"),
                    ("power_semantics_status", "Power status"),
                    ("leakage_status", "Leakage status"),
                    ("issue_time_truncation_ready", "User-input truncation ready"),
                ),
            ),
            "",
        )
    )
    return "\n".join(lines).encode("utf-8")


def validate_report_markdown(
    content: bytes,
    expected_rows: Sequence[Mapping[str, object]],
    *,
    status: str,
    config_sha256: str,
    code_commit: str,
) -> None:
    """Bind the fixed report bytes to the same closed monthly rows as the CSV."""

    expected = render_report_markdown(
        expected_rows,
        status=status,
        config_sha256=config_sha256,
        code_commit=code_commit,
    )
    if content != expected:
        raise SeasonalReportingError


__all__ = [
    "SUMMARY_COLUMNS",
    "SeasonalReportingError",
    "build_month_summary_row",
    "render_report_markdown",
    "render_summary_csv",
    "validate_report_markdown",
    "validate_summary_csv",
]
