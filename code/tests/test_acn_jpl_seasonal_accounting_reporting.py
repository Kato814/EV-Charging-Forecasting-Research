from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from typing import Any

import pytest
from evcf.data.acn_jpl_month_config import jpl_month_config
from evcf.data.acn_jpl_seasonal_reporting import (
    SUMMARY_COLUMNS,
    SeasonalReportingError,
    build_month_summary_row,
    render_report_markdown,
    render_summary_csv,
    validate_report_markdown,
    validate_summary_csv,
)
from test_acn_jpl_seasonal_prep import _month_documents, _month_result

ACCOUNTING_KEYS = (
    "acquisition_session_count",
    "structural_retained_session_count",
    "current_analyzable_session_count",
    "pilot_analyzable_session_count",
    "invalid_container_placeholder_count",
    "current_only_invalid_count",
    "pilot_only_invalid_count",
    "both_invalid_count",
    "trajectory_quarantine_count",
    "metadata_checked_session_count",
    "metadata_match_session_count",
    "metadata_anomaly_count",
    "coverage_denominator_session_count",
    "whole_current_unobservable_session_count",
    "whole_pilot_unobservable_session_count",
)
STATION_GATE_KEYS = (
    "coverage_only_valid_bins_at_80",
    "coverage_only_valid_bins_at_90",
    "coverage_only_valid_bins_at_95",
    "known_incomplete_current_bins",
    "known_incomplete_pilot_bins",
    "known_incomplete_current_excluded_bins_at_80",
    "known_incomplete_current_excluded_bins_at_90",
    "known_incomplete_current_excluded_bins_at_95",
)


def _documents(month: str = "2019-02") -> dict[str, Any]:
    config = jpl_month_config(month)
    documents = _month_documents(
        month, config.expected_bins, config.expected_scheduled_issue_times
    )
    station = documents["station_15min_qa.json"]
    station.update({
        "coverage_only_valid_bins_at_80": station["valid_bins_at_80"],
        "coverage_only_valid_bins_at_90": station["valid_bins_at_90"],
        "coverage_only_valid_bins_at_95": station["valid_bins_at_95"],
        "known_incomplete_current_bins": 3,
        "known_incomplete_pilot_bins": 5,
        "known_incomplete_current_excluded_bins_at_80": 3,
        "known_incomplete_current_excluded_bins_at_90": 2,
        "known_incomplete_current_excluded_bins_at_95": 1,
    })
    for threshold in (80, 90, 95):
        station[f"valid_bins_at_{threshold}"] -= station[
            f"known_incomplete_current_excluded_bins_at_{threshold}"
        ]
    # A valid container may still leave no usable observed cleaned trajectory.
    # Preserve distinct evidence rather than deriving either count from the other.
    accounting = documents["cleaning_qa.json"]["session_accounting"]
    accounting["current_analyzable_session_count"] -= 1
    accounting["whole_current_unobservable_session_count"] += 1
    return documents


def _rows() -> tuple[dict[str, object], ...]:
    return tuple(build_month_summary_row(_documents(month)) for month in (
        "2019-02", "2019-08", "2019-11"
    ))


def _markdown(rows: tuple[Mapping[str, object], ...]) -> bytes:
    return render_report_markdown(
        rows, status="READY_WITH_LIMITATIONS", config_sha256="a" * 64, code_commit="b" * 40
    )


def test_summary_projects_all_accounting_and_gate_counts_without_duplicate_columns() -> None:
    documents = _documents()
    row = build_month_summary_row(documents)
    accounting = documents["cleaning_qa.json"]["session_accounting"]
    station = documents["station_15min_qa.json"]

    assert len(SUMMARY_COLUMNS) == len(set(SUMMARY_COLUMNS))
    assert SUMMARY_COLUMNS.count("trajectory_quarantine_count") == 1
    for key in ACCOUNTING_KEYS:
        assert key in row
        assert row[key] == accounting[key]
    for key in STATION_GATE_KEYS:
        assert key in row
        assert row[key] == station[key]
    assert row["invalid_skipped_session_count"] == 0
    assert row["current_analyzable_session_count"] != row[
        "trajectory_current_analysis_coverage_count"
    ]
    for threshold in (80, 90, 95):
        assert row[f"coverage_only_valid_bins_at_{threshold}"] == (
            row[f"valid_bin_{threshold}_count"]
            + row[f"known_incomplete_current_excluded_bins_at_{threshold}"]
        )


@pytest.mark.parametrize("key", tuple(key for key in ACCOUNTING_KEYS
                                      if key != "trajectory_quarantine_count"))
def test_reporting_does_not_silently_default_missing_session_accounting(key: str) -> None:
    documents = _documents()
    del documents["cleaning_qa.json"]["session_accounting"][key]

    with pytest.raises(SeasonalReportingError):
        build_month_summary_row(documents)


@pytest.mark.parametrize("key", STATION_GATE_KEYS)
def test_reporting_does_not_silently_default_missing_target_gate_evidence(key: str) -> None:
    documents = _documents()
    del documents["station_15min_qa.json"][key]

    with pytest.raises(SeasonalReportingError):
        build_month_summary_row(documents)


def test_csv_binds_corrected_counts_and_rejects_tampering() -> None:
    rows = _rows()
    content = render_summary_csv(rows)
    parsed = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))

    for row, encoded in zip(rows, parsed, strict=True):
        for key in (*ACCOUNTING_KEYS, *STATION_GATE_KEYS):
            assert key in encoded
            assert encoded[key] == str(row[key])
    validate_summary_csv(content, rows)
    altered = [dict(row) for row in rows]
    altered[0]["structural_retained_session_count"] = 1
    with pytest.raises(SeasonalReportingError):
        validate_summary_csv(render_summary_csv(altered), rows)


def test_markdown_explains_structure_raw_containers_observations_and_target_gate() -> None:
    report = _markdown(_rows()).decode("utf-8")

    for phrase in (
        "Structural retained",
        "Current analyzable",
        "Pilot analyzable",
        "Invalid placeholders",
        "Current-only invalid",
        "Pilot-only invalid",
        "Both invalid",
        "Metadata checked",
        "Metadata matched",
        "Metadata anomalies",
        "Coverage denominator",
        "Whole current unavailable",
        "Whole pilot unavailable",
        "Coverage-only 90",
        "Excluded despite coverage 90",
        "Final valid 90",
    ):
        assert phrase in report
    assert "| Skipped |" not in report
    assert "Sessions omitted" in report
    assert "positive observed duration" in report
    assert "raw container validity" in report
    assert "even when coverage is at least 90%" in report
    assert "observed lower bounds" in report
    assert "unknown current is not evidence" in report
    assert "no new kW-label authorization" in report


def test_markdown_validator_binds_the_target_gate_explanation() -> None:
    rows = _rows()
    content = _markdown(rows)
    altered = content.replace(b"Final valid 90", b"Coverage-only labels", 1)

    assert altered != content
    with pytest.raises(SeasonalReportingError):
        validate_report_markdown(
            altered,
            rows,
            status="READY_WITH_LIMITATIONS",
            config_sha256="a" * 64,
            code_commit="b" * 40,
        )


def test_corrected_root_report_passes_the_unchanged_public_privacy_gate() -> None:
    from evcf.data.acn_jpl_seasonal_prep import _root_payloads, _seasonal_result

    result = _seasonal_result(tuple(_month_result(month) for month in (
        "2019-02", "2019-08", "2019-11"
    )))
    payloads = _root_payloads(result)
    report = payloads["seasonal_prep_report.md"].decode("utf-8")

    assert "prediction" not in report.casefold()
    assert "offline anomaly reasons do not enter online features" in report
    assert "Final valid 90" in report
