"""Closed aggregate correction evidence beside the unchanged seasonal release.

The baseline is bound to its preserved inventory and original checksum tree;
the corrected release passes the current 37-file verifier. Independent audits
are supplied after their separate runs. No telemetry, identifiers, filenames
from private audits, or timestamp fingerprints are copied into the result.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .acn_jpl_seasonal_prep import (
    MONTH_PAYLOAD_NAMES,
    MONTH_RELEASE_NAMES,
    ROOT_PAYLOAD_NAMES,
    SeasonalPreparationError,
    _parse_checksums,
    expected_seasonal_release_paths,
    load_verified_seasonal_release,
    release_paths,
)

MONTHS = ("2019-02", "2019-08", "2019-11")
RECONCILIATION_FILES = ("reconciliation.json", "SHA256SUMS")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_AUGUST_ARRAY_NAMES = tuple(
    f"{tier}.{name}.npy" for tier in ("M1", "M2", "M3")
    for name in ("issue_times", "nullable_mask", "values")
)
_BEFORE_COUNTS = (
    "structural_session_count", "valid_bins_at_90", "formal_issue_times",
    "connected_session_seconds",
)
_ACCOUNTING = (
    "current_analyzable_session_count", "pilot_analyzable_session_count",
    "invalid_container_placeholder_count", "current_only_invalid_count",
    "pilot_only_invalid_count", "both_invalid_count", "trajectory_quarantine_count",
    "metadata_checked_session_count", "metadata_match_session_count", "metadata_anomaly_count",
    "coverage_denominator_session_count", "whole_current_unobservable_session_count",
    "whole_pilot_unobservable_session_count",
)
_AFTER_COUNTS = (*_BEFORE_COUNTS, *_ACCOUNTING, "known_incomplete_current_bins",
                 "known_incomplete_pilot_bins", "coverage_only_valid_bins_at_90",
                 "known_incomplete_current_excluded_bins_at_90")
_CHANGES = (*_BEFORE_COUNTS, "affected_interval_bins", "changed_connected_bins",
            "old_valid_now_excluded_bins_at_90")
_SNAPSHOT_HASHES = ("issue_snapshot_sha256", "processed_snapshot_sha256")
_PROVENANCE_HASHES = (
    "raw_inventory_before_sha256", "raw_inventory_after_sha256",
    "metadata_source_inventory_sha256", "metadata_record_inventory_sha256",
    "official_reference_sha256", "before_month_public_sha256", "after_month_public_sha256",
)
_MAY_KEYS = (
    "status", "checks", "mismatch_count", "baseline_manifest_sha256", "replay_manifest_sha256",
    "numerical_equivalence_within_tolerance", "raw_unchanged", "frozen_public_unchanged",
    "arrays", "public_files", "numeric_comparison", "runtime_python", "source",
    "verification_content_sha256",
)
_MAY_NUMERIC_DETAILS = (
    "exact_difference_count", "max_absolute_difference", "tolerance_failure_count",
)
_MAY_NUMERIC_DEFINITION = (
    "relative_tolerance", "absolute_tolerance", "artifact_provenance_hash_fields_excluded",
    "runtime_environment_python_field_excluded",
)


class ReconciliationError(ValueError):
    """One safe diagnostic for unverified or inconsistent correction evidence."""

    def __init__(self) -> None:
        super().__init__("SEASONAL_RECONCILIATION_INVALID")


def _require(condition: bool) -> None:
    if not condition:
        raise ReconciliationError


def _mapping(value: object) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping))
    return value  # type: ignore[return-value]


def _exact(value: object, keys: tuple[str, ...]) -> Mapping[str, Any]:
    result = _mapping(value)
    _require(set(result) == set(keys))
    return result


def _integer(value: object, *, signed: bool = False) -> int:
    _require(type(value) is int and (signed or value >= 0))
    return value  # type: ignore[return-value]


def _digest(value: object, *, commit: bool = False) -> str:
    pattern = _COMMIT if commit else _SHA256
    _require(isinstance(value, str) and pattern.fullmatch(value) is not None)
    return value  # type: ignore[return-value]


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
            + "\n").encode("utf-8")


def _content_digest(value: object) -> str:
    """Hash canonical aggregate input content, independently of file formatting."""

    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _validate_may_regression(value: object) -> Mapping[str, Any]:
    may = _exact(value, _MAY_KEYS)
    _require(may["status"] == "PASS" and _integer(may["checks"]) > 0)
    _require(_integer(may["mismatch_count"]) == 0)
    for name in ("numerical_equivalence_within_tolerance", "raw_unchanged",
                 "frozen_public_unchanged"):
        _require(may[name] is True)
    for name in ("baseline_manifest_sha256", "replay_manifest_sha256",
                 "verification_content_sha256"):
        _digest(may[name])
    arrays = _exact(may["arrays"], ("compared_count", "exact_equal_count"))
    _require(_integer(arrays["compared_count"]) == _integer(arrays["exact_equal_count"]) == 15)
    public = _exact(may["public_files"], ("compared_count", "byte_equal_count"))
    _require(_integer(public["compared_count"]) == 13)
    _require(_integer(public["byte_equal_count"]) <= public["compared_count"])
    numeric = _exact(may["numeric_comparison"], (*_MAY_NUMERIC_DETAILS, *_MAY_NUMERIC_DEFINITION))
    for name in ("relative_tolerance", "absolute_tolerance", "max_absolute_difference"):
        number = numeric[name]
        _require(type(number) in (int, float) and math.isfinite(number) and number >= 0)
    _require(numeric["relative_tolerance"] == 1e-12 and numeric["absolute_tolerance"] == 1e-8)
    count = _integer(numeric["exact_difference_count"])
    _require((count == 0) == (numeric["max_absolute_difference"] == 0))
    _require(_integer(numeric["tolerance_failure_count"]) == 0)
    for name in ("artifact_provenance_hash_fields_excluded",
                 "runtime_environment_python_field_excluded"):
        _require(numeric[name] is True)
    runtime = may["runtime_python"]
    _require(isinstance(runtime, str) and re.fullmatch(r"3\.11\.\d+", runtime) is not None)
    source = _exact(may["source"], ("representation", "snapshot_sha256", "working_tree_base_commit"))
    _require(source["representation"] == "working_tree_snapshot")
    _digest(source["snapshot_sha256"])
    _digest(source["working_tree_base_commit"], commit=True)
    return may


def extract_may_regression(verification: Mapping[str, Any]) -> dict[str, Any]:
    """Extract checked aggregate semantics from the original independent May audit.

    Exact array equality, public-file byte equality, and tolerance-based numeric
    equivalence are different claims. The copied working-tree snapshot is never
    represented as an artifact producer commit.
    """

    try:
        original = _mapping(verification)
        _require(original["mismatch_categories"] == [])
        _require(original["numerical_values_unchanged"] is True)
        _require(_digest(original["raw_before_sha256"]) == _digest(original["raw_after_sha256"]))
        _require(original["source_representation"] == (
            "copied tracked working-tree bytes, including uncommitted changes; not a claimed commit"
        ))
        array_results = []
        for artifact in _mapping(original["local_artifact_comparison"]).values():
            row = _mapping(artifact)
            if "arrays" in row:
                for observation in _mapping(row["arrays"]).values():
                    observed = _mapping(observation)
                    _require(observed["within_tolerance"] is True)
                    _require(type(observed["exact_equal"]) is bool)
                    array_results.append(observed["exact_equal"])
        public_results = tuple(_mapping(original["public_byte_comparison"]).values())
        _require(all(type(item) is bool for item in public_results))
        _require(_integer(original["public_file_count"]) == len(public_results))
        _require(_integer(original["public_byte_matches"]) == sum(public_results))
        numeric = {
            **_exact(original["numeric_details"], _MAY_NUMERIC_DETAILS),
            **_exact(original["numerical_equality_definition"], _MAY_NUMERIC_DEFINITION),
        }
        result = {
            **{key: original[key] for key in ("status", "checks", "mismatch_count",
               "baseline_manifest_sha256", "replay_manifest_sha256", "raw_unchanged",
               "frozen_public_unchanged")},
            "numerical_equivalence_within_tolerance": True,
            "arrays": {"compared_count": len(array_results), "exact_equal_count": sum(array_results)},
            "public_files": {"compared_count": len(public_results),
                             "byte_equal_count": sum(public_results)},
            "numeric_comparison": numeric,
            "runtime_python": original["python"],
            "source": {"representation": "working_tree_snapshot",
                       "snapshot_sha256": original["source_snapshot_sha256"],
                       "working_tree_base_commit": original["working_tree_base_commit"]},
            "verification_content_sha256": _content_digest(original),
        }
        _validate_may_regression(result)
        return result
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ReconciliationError from None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> Mapping[str, Any]:
    def closed_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        _require(len(pairs) == len({key for key, _value in pairs}))
        return dict(pairs)

    return _mapping(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=closed_pairs))


def _audit_months(value: object) -> dict[str, Mapping[str, Any]]:
    _require(isinstance(value, list))
    rows = tuple(_mapping(item) for item in value)  # type: ignore[union-attr]
    _require(tuple(item.get("month") for item in rows) == MONTHS)
    return {item["month"]: item for item in rows}


def _verify_baseline(
    root: Path, inventory: Mapping[str, Any], baseline_commit: str
) -> Mapping[str, Any]:
    """Verify old bytes without asking a new schema validator to approve v1 data."""

    _require(inventory["baseline_commit"] == baseline_commit)
    _require(inventory["copy_only"] is True and inventory["source_files_unchanged_during_copy"] is True)
    public = _mapping(_mapping(inventory["sources"])["public"])
    _require(public["copy_all_hashes_match"] is True)
    _require(release_paths(root) == expected_seasonal_release_paths())
    _require(not root.is_symlink() and not any(path.is_symlink() for path in root.rglob("*")))
    entries = public["entries"]
    _require(isinstance(entries, list) and public["file_count"] == len(entries) == 37)
    known_names = set(expected_seasonal_release_paths())
    names = []
    for entry in entries:
        item = _exact(entry, ("relative_path", "size_bytes", "sha256"))
        name = item["relative_path"]
        _require(name in known_names)
        names.append(name)
        path = root / name
        _require(path.stat().st_size == _integer(item["size_bytes"]))
        _require(_sha(path) == _digest(item["sha256"]))
    _require(len(set(names)) == 37)
    canonical = "".join(
        f"{item['relative_path']}\t{item['size_bytes']}\t{item['sha256']}\n" for item in entries
    ).encode("utf-8")
    _require(hashlib.sha256(canonical).hexdigest() == _digest(public["inventory_sha256"]))
    for month in MONTHS:
        declared = _parse_checksums((root / month / "SHA256SUMS").read_bytes(),
                                    expected_names=MONTH_PAYLOAD_NAMES)
        _require(all(_sha(root / month / name) == digest for name, digest in declared.items()))
    declared = _parse_checksums(
        (root / "SHA256SUMS").read_bytes(),
        expected_names=(*ROOT_PAYLOAD_NAMES, *(f"{month}/{name}" for month in MONTHS
                                              for name in MONTH_RELEASE_NAMES)),
    )
    _require(all(_sha(root / name) == digest for name, digest in declared.items()))
    manifest = _read_json(root / "seasonal_snapshot_manifest.json")
    _require(manifest["months"] == list(MONTHS) and manifest["public_file_count"] == 37)
    _require(manifest["aggregate_only"] is True)
    _digest(manifest["code_commit"], commit=True)
    _digest(manifest["config_sha256"])
    declared_months = _audit_months(manifest["month_snapshots"])
    for month in MONTHS:
        declared_month = declared_months[month]
        data = _read_json(root / month / "data_snapshot_manifest.json")
        _require(data["code_commit"] == manifest["code_commit"])
        _require(data["config_sha256"] == manifest["config_sha256"])
        _require(declared_month["month_public_sha256"] == _sha(root / month / "SHA256SUMS"))
        for name in ("processed_snapshot_sha256", "raw_inventory_sha256",
                     "metadata_source_inventory_sha256", "metadata_record_inventory_sha256"):
            _require(_digest(data[name]) == declared_month[name])
    return manifest


def _check_pass_audit(audit: Mapping[str, Any], baseline_commit: str) -> None:
    _require(audit["status"] == "PASS" and audit["baseline_commit"] == baseline_commit)
    _require(audit["identifiers_emitted"] is False and audit["timestamp_fingerprints_emitted"] is False)


def _month_reconciliation(
    before_root: Path, after_root: Path, month: str,
    independent: Mapping[str, Any], metadata: Mapping[str, Any],
) -> dict[str, Any]:
    old = {name: _read_json(before_root / month / name) for name in MONTH_PAYLOAD_NAMES}
    new = {name: _read_json(after_root / month / name) for name in MONTH_PAYLOAD_NAMES}
    old_clean = old["cleaning_qa.json"]
    new_clean = new["cleaning_qa.json"]
    accounting = _mapping(new_clean["session_accounting"])
    old_station, new_station = old["station_15min_qa.json"], new["station_15min_qa.json"]
    old_issue, new_issue = old["issue_snapshot_qa.json"], new["issue_snapshot_qa.json"]
    old_acq, new_acq = old["acquisition_summary.json"], new["acquisition_summary.json"]
    acquisition = _integer(new_acq["combined_session_count"])
    _require(acquisition > 0 and acquisition == old_acq["combined_session_count"])
    for field in ("official_total", "local_session_count", "carry_in_count", "raw_inventory_sha256",
                  "metadata_source_inventory_sha256", "metadata_record_inventory_sha256",
                  "official_reference_sha256"):
        _require(old_acq[field] == new_acq[field])
    _require(independent["status"] == "PASS" and _integer(independent["checks"]) > 0)
    _require(_integer(independent["mismatch_count"]) == 0 and independent["mismatch_categories"] == {})
    _require(_integer(independent["temporal_violations"]) == 0)
    count = _integer(accounting["invalid_container_placeholder_count"])
    _require(old_clean["invalid_skipped_session_count"] == count)
    _require(_integer(metadata["invalid_container_union_count"]) == count)
    _require(_integer(metadata["raw_session_count"]) == acquisition)
    for name in ("metadata_bad_count", "official_metadata_missing_count",
                 "all_metadata_fields_mismatch_count", "unparseable_metadata_bounds_count",
                 "nonpositive_metadata_interval_count", "invalid_metadata_timezone_count"):
        _require(_integer(metadata[name]) == 0)
    for name in ("metadata_normal_count", "official_metadata_matched_count",
                 "all_metadata_fields_exact_match_count", "connection_exact_official_match_count",
                 "disconnect_exact_official_match_count"):
        _require(_integer(metadata[name]) == count)
    for name in ("current_only_invalid_count", "pilot_only_invalid_count", "both_invalid_count"):
        _require(_integer(metadata[name]) == accounting[name])
    _require(_integer(metadata["current_invalid_count"]) == (
        accounting["current_only_invalid_count"] + accounting["both_invalid_count"]))
    _require(_integer(metadata["pilot_invalid_count"]) == (
        accounting["pilot_only_invalid_count"] + accounting["both_invalid_count"]))
    before = {
        "structural_session_count": old_clean["cleaned_session_count"],
        "valid_bins_at_90": old_station["valid_bins_at_90"],
        "formal_issue_times": old_issue["formal_issue_times"],
        "connected_session_seconds": independent["old_connected_session_seconds"],
        "issue_snapshot_sha256": old_issue["snapshot_sha256"],
        "processed_snapshot_sha256": old["data_snapshot_manifest.json"]["processed_snapshot_sha256"],
    }
    after = {
        "structural_session_count": new_clean["cleaned_session_count"],
        "valid_bins_at_90": new_station["valid_bins_at_90"],
        "formal_issue_times": new_issue["formal_issue_times"],
        "connected_session_seconds": independent["new_connected_session_seconds"],
        **{key: accounting[key] for key in _ACCOUNTING},
        **{key: new_station[key] for key in ("known_incomplete_current_bins",
                                           "known_incomplete_pilot_bins",
                                           "coverage_only_valid_bins_at_90",
                                           "known_incomplete_current_excluded_bins_at_90")},
        "issue_snapshot_sha256": new_issue["snapshot_sha256"],
        "processed_snapshot_sha256": new["data_snapshot_manifest.json"]["processed_snapshot_sha256"],
    }
    expected_independent = {
        "old_cleaned_count": before["structural_session_count"],
        "new_cleaned_count": after["structural_session_count"],
        "invalid_structures_retained": count,
        "original_trajectory_quarantine_count": accounting["trajectory_quarantine_count"],
        "old_valid90": before["valid_bins_at_90"], "new_valid90": after["valid_bins_at_90"],
        "old_formal_issue_times": before["formal_issue_times"],
        "formal_issue_times": after["formal_issue_times"],
        "coverage_only_valid90": after["coverage_only_valid_bins_at_90"],
        "known_incomplete_current_bins": after["known_incomplete_current_bins"],
        "known_incomplete_pilot_bins": after["known_incomplete_pilot_bins"],
        "affected_interval_bins": metadata["unique_15min_bins_overlapping_invalid_sessions"],
        "added_connected_session_seconds": metadata["connected_seconds_inside_local_month"],
    }
    for key, expected in expected_independent.items():
        _require(_integer(independent[key]) == expected)
    changes = {key: _integer(after[key]) - _integer(before[key]) for key in _BEFORE_COUNTS}
    changes.update({key: independent[key] for key in (
        "affected_interval_bins", "changed_connected_bins", "old_valid_now_excluded_bins_at_90")})
    _require(changes["connected_session_seconds"] == independent["added_connected_session_seconds"])
    return {
        "month": month, "acquisition_session_count": acquisition,
        "station_bin_count": new_station["generated_bins"],
        "before": before, "after": after, "changes": changes,
        "provenance": {
            "raw_inventory_before_sha256": old_acq["raw_inventory_sha256"],
            "raw_inventory_after_sha256": new_acq["raw_inventory_sha256"],
            "raw_unchanged": True,
            "metadata_source_inventory_sha256": new_acq["metadata_source_inventory_sha256"],
            "metadata_record_inventory_sha256": new_acq["metadata_record_inventory_sha256"],
            "official_reference_sha256": new_acq["official_reference_sha256"],
            "before_month_public_sha256": _sha(before_root / month / "SHA256SUMS"),
            "after_month_public_sha256": _sha(after_root / month / "SHA256SUMS"),
        },
        "independent_comparison": {"status": "PASS", "checks": independent["checks"],
                                   "mismatch_count": 0},
    }


def build_reconciliation(
    *, before_public_root: str | Path, after_public_root: str | Path,
    baseline_commit: str, baseline_inventory: Mapping[str, Any],
    comparison: Mapping[str, Any], metadata_audit: Mapping[str, Any],
    may_regression: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind preserved baseline, verified corrected release, and independent audits.

    ``baseline_inventory``, ``comparison`` and ``metadata_audit`` accept the
    original aggregate audit mappings. Only the fixed fields selected here are
    published; their canonical-content digests bind the full supplied evidence.
    ``may_regression`` is the closed result of ``extract_may_regression``. Baseline
    capture commit and the older artifact producer commit remain distinct.
    """

    try:
        _digest(baseline_commit, commit=True)
        before_root, after_root = Path(before_public_root), Path(after_public_root)
        _require(before_root.resolve() != after_root.resolve())
        old_manifest = _verify_baseline(before_root, baseline_inventory, baseline_commit)
        new_release = load_verified_seasonal_release(after_root)
        for audit in (comparison, metadata_audit):
            _check_pass_audit(audit, baseline_commit)
        _require(metadata_audit["raw_modified"] is False and metadata_audit["models_run"] is False)
        _require(_integer(metadata_audit["downloads"]) == 0)
        _require(_integer(metadata_audit["official_metadata_duplicate_pair_count"]) == 0)
        raw_count = _integer(comparison["raw_files_unchanged"])
        _require(raw_count > 0 and raw_count == baseline_inventory["sources"]["raw"]["file_count"])
        independent = _audit_months(comparison["months"])
        metadata = _audit_months(metadata_audit["months"])
        months = [_month_reconciliation(before_root, after_root, month,
                                        independent[month], metadata[month]) for month in MONTHS]
        august_arrays = _exact(independent["2019-08"]["august_numpy_comparisons"], _AUGUST_ARRAY_NAMES)
        _require(all(value is True for value in august_arrays.values()))
        document = {
            "schema_version": "acn-jpl-seasonal-invalid-container-reconciliation/v1",
            "status": "PASS", "baseline_commit": baseline_commit,
            "before_provenance": {
                "code_commit": old_manifest["code_commit"],
                "config_sha256": old_manifest["config_sha256"],
                "public_root_sha256": _sha(before_root / "SHA256SUMS"),
                "preserved_public_inventory_sha256": baseline_inventory["sources"]["public"][
                    "inventory_sha256"],
            },
            "after_provenance": {
                "code_commit": new_release.code_commit,
                "config_sha256": new_release.config_sha256,
                "public_root_sha256": _sha(after_root / "SHA256SUMS"),
            },
            "evidence": {
                "baseline_inventory_content_sha256": _content_digest(baseline_inventory),
                "comparison_audit_content_sha256": _content_digest(comparison),
                "metadata_audit_content_sha256": _content_digest(metadata_audit),
                "may_audit_content_sha256": _content_digest(may_regression),
                "reconciliation_source_sha256": _sha(Path(__file__)),
                "raw_files_verified_unchanged": raw_count,
            },
            "months": months,
            "regressions": {
                "august": {"status": "PASS", "checked_array_count": len(august_arrays),
                           "numerical_values_unchanged": True},
                "may": dict(_exact(may_regression, _MAY_KEYS)),
            },
            "publication": {"seasonal_core_file_count": 37, "correction_file_count": 2,
                            "total_public_file_count": 39, "aggregate_only": True,
                            "identifiers_emitted": False, "timestamp_fingerprints_emitted": False,
                            "new_kw_authorization": False},
        }
        validate_reconciliation(document)
        # Re-read both inventories at the final evidence boundary.
        _verify_baseline(before_root, baseline_inventory, baseline_commit)
        refreshed = load_verified_seasonal_release(after_root)
        _require(refreshed == new_release)
        _require(_sha(after_root / "SHA256SUMS") == document["after_provenance"]["public_root_sha256"])
        return document
    except (KeyError, TypeError, OSError, ValueError, SeasonalPreparationError):
        raise ReconciliationError from None


def _validate_month(value: object, month: str) -> None:
    row = _exact(value, ("month", "acquisition_session_count", "station_bin_count", "before",
                         "after", "changes", "provenance", "independent_comparison"))
    _require(row["month"] == month)
    acquisition = _integer(row["acquisition_session_count"])
    bins = _integer(row["station_bin_count"])
    _require(acquisition > 0 and bins > 0)
    before = _exact(row["before"], (*_BEFORE_COUNTS, *_SNAPSHOT_HASHES))
    after = _exact(row["after"], (*_AFTER_COUNTS, *_SNAPSHOT_HASHES))
    changes = _exact(row["changes"], _CHANGES)
    for group, count_keys in ((before, _BEFORE_COUNTS), (after, _AFTER_COUNTS)):
        for key in count_keys:
            _integer(group[key])
        for key in _SNAPSHOT_HASHES:
            _digest(group[key])
        _require(group["valid_bins_at_90"] <= bins and group["formal_issue_times"] <= bins)
    for key in _CHANGES:
        _integer(changes[key], signed=key in _BEFORE_COUNTS)
    for key in _BEFORE_COUNTS:
        _require(changes[key] == after[key] - before[key])
    placeholders = after["invalid_container_placeholder_count"]
    _require(after["structural_session_count"] == after["coverage_denominator_session_count"]
             == acquisition)
    _require(changes["structural_session_count"] == placeholders)
    _require(after["current_only_invalid_count"] + after["pilot_only_invalid_count"]
             + after["both_invalid_count"] == placeholders)
    _require(placeholders == after["metadata_checked_session_count"]
             == after["metadata_match_session_count"] and after["metadata_anomaly_count"] == 0)
    trajectory = after["trajectory_quarantine_count"]
    _require(trajectory == (1 if month == "2019-11" else 0))
    _require(placeholders + trajectory <= acquisition)
    for branch in ("current", "pilot"):
        observable = after[f"{branch}_analyzable_session_count"]
        missing = after[f"whole_{branch}_unobservable_session_count"]
        invalid = after[f"{branch}_only_invalid_count"] + after["both_invalid_count"]
        _require(observable + missing == acquisition and missing >= invalid + trajectory)
        _require(after[f"known_incomplete_{branch}_bins"] <= bins)
    known = after["known_incomplete_current_bins"]
    coverage = after["coverage_only_valid_bins_at_90"]
    excluded = after["known_incomplete_current_excluded_bins_at_90"]
    _require(coverage <= bins and excluded <= known)
    _require(coverage - excluded == after["valid_bins_at_90"])
    _require(after["valid_bins_at_90"] + known <= bins)
    _require(changes["connected_session_seconds"] >= 0)
    _require(changes["changed_connected_bins"] <= changes["affected_interval_bins"] <= bins)
    _require(changes["affected_interval_bins"] <= (
        after["known_incomplete_current_bins"] + after["known_incomplete_pilot_bins"]))
    lost = changes["old_valid_now_excluded_bins_at_90"]
    _require(max(0, -changes["valid_bins_at_90"]) <= lost <= before["valid_bins_at_90"])
    _require(lost <= bins - after["valid_bins_at_90"])
    provenance = _exact(row["provenance"], (*_PROVENANCE_HASHES, "raw_unchanged"))
    for key in _PROVENANCE_HASHES:
        _digest(provenance[key])
    _require(provenance["raw_unchanged"] is True)
    _require(provenance["raw_inventory_before_sha256"] == provenance["raw_inventory_after_sha256"])
    independent = _exact(row["independent_comparison"], ("status", "checks", "mismatch_count"))
    _require(independent["status"] == "PASS" and _integer(independent["checks"]) > 0)
    _require(_integer(independent["mismatch_count"]) == 0)


def validate_reconciliation(document: Mapping[str, Any]) -> None:
    """Check every output key/type and every reported count relationship."""

    try:
        root = _exact(document, ("schema_version", "status", "baseline_commit", "before_provenance",
                                 "after_provenance", "evidence", "months", "regressions", "publication"))
        _require(root["schema_version"] == "acn-jpl-seasonal-invalid-container-reconciliation/v1")
        _require(root["status"] == "PASS")
        _digest(root["baseline_commit"], commit=True)
        for name in ("before_provenance", "after_provenance"):
            extra = ("preserved_public_inventory_sha256",) if name == "before_provenance" else ()
            provenance = _exact(root[name], ("code_commit", "config_sha256", "public_root_sha256", *extra))
            _digest(provenance["code_commit"], commit=True)
            for key in ("config_sha256", "public_root_sha256", *extra):
                _digest(provenance[key])
        evidence = _exact(root["evidence"], ("baseline_inventory_content_sha256",
                          "comparison_audit_content_sha256", "metadata_audit_content_sha256",
                          "may_audit_content_sha256", "reconciliation_source_sha256",
                          "raw_files_verified_unchanged"))
        for key, value in evidence.items():
            if key == "raw_files_verified_unchanged":
                _require(_integer(value) > 0)
            else:
                _digest(value)
        months = _audit_months(root["months"])
        for month in MONTHS:
            _validate_month(months[month], month)
        regressions = _exact(root["regressions"], ("august", "may"))
        august = _exact(regressions["august"], ("status", "checked_array_count", "numerical_values_unchanged"))
        _require(august["status"] == "PASS" and _integer(august["checked_array_count"]) == 9)
        _require(august["numerical_values_unchanged"] is True)
        _require(all(value == 0 for value in months["2019-08"]["changes"].values()))
        may = _validate_may_regression(regressions["may"])
        _require(evidence["may_audit_content_sha256"] == _content_digest(may))
        publication = _exact(root["publication"], ("seasonal_core_file_count", "correction_file_count",
                              "total_public_file_count", "aggregate_only", "identifiers_emitted",
                              "timestamp_fingerprints_emitted", "new_kw_authorization"))
        for key, expected in (("seasonal_core_file_count", 37), ("correction_file_count", 2),
                              ("total_public_file_count", 39)):
            _require(_integer(publication[key]) == expected)
        _require(publication["aggregate_only"] is True)
        for key in ("identifiers_emitted", "timestamp_fingerprints_emitted", "new_kw_authorization"):
            _require(publication[key] is False)
    except (KeyError, TypeError, ValueError):
        raise ReconciliationError from None


def publish_reconciliation(document: Mapping[str, Any], output_root: str | Path) -> None:
    """Atomically publish exactly two files, accepting an identical rerun only."""

    validate_reconciliation(document)
    content = _json_bytes(document)
    payloads = {
        "reconciliation.json": content,
        "SHA256SUMS": (hashlib.sha256(content).hexdigest() + "  reconciliation.json\n").encode("ascii"),
    }
    root = Path(output_root)
    _require(not root.is_symlink())
    if root.exists():
        _require(root.is_dir() and {path.name for path in root.iterdir()} == set(RECONCILIATION_FILES))
        _require(all(not (root / name).is_symlink() and (root / name).read_bytes() == data
                     for name, data in payloads.items()))
        return
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".reconciliation-staging-", dir=root.parent) as directory:
        staging = Path(directory)
        for name, data in payloads.items():
            with (staging / name).open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        _require(not root.exists())
        os.replace(staging, root)
