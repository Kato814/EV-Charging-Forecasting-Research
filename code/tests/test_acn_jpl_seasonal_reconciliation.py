from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from evcf.data.acn_jpl_month_config import jpl_month_config
from evcf.data.acn_jpl_seasonal_prep import (
    MONTH_PAYLOAD_NAMES,
    MONTH_RELEASE_NAMES,
    ROOT_PAYLOAD_NAMES,
    build_month_preparation_result,
    publish_seasonal_release,
)
from test_acn_jpl_seasonal_prep import _month_documents

MONTHS = ("2019-02", "2019-08", "2019-11")
BASELINE_COMMIT = "a" * 40


def _module() -> Any:
    name = "evcf.data.acn_jpl_seasonal_reconciliation"
    assert importlib.util.find_spec(name) is not None, "reconciliation is not implemented"
    return importlib.import_module(name)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checksums(root: Path, names: tuple[str, ...]) -> None:
    (root / "SHA256SUMS").write_text(
        "".join(f"{_hash(root / name)}  {name}\n" for name in names), encoding="ascii", newline="\n"
    )


def _may_verification() -> dict[str, Any]:
    return {
        "status": "PASS", "checks": 62, "mismatch_count": 0, "mismatch_categories": [],
        "baseline_manifest_sha256": "f" * 64, "replay_manifest_sha256": "0" * 64,
        "numerical_values_unchanged": True, "raw_unchanged": True,
        "raw_before_sha256": "1" * 64, "raw_after_sha256": "1" * 64,
        "frozen_public_unchanged": True,
        "local_artifact_comparison": {
            "synthetic.npz": {"arrays": {
                f"array_{index}": {"exact_equal": True, "within_tolerance": True}
                for index in range(15)
            }},
        },
        "public_byte_comparison": {f"public_{index}.json": index < 10 for index in range(13)},
        "public_byte_matches": 10, "public_file_count": 13,
        "numeric_details": {"exact_difference_count": 1138,
                            "max_absolute_difference": 4.3655745685100555e-11,
                            "tolerance_failure_count": 0},
        "numerical_equality_definition": {
            "relative_tolerance": 1e-12, "absolute_tolerance": 1e-8,
            "artifact_provenance_hash_fields_excluded": True,
            "runtime_environment_python_field_excluded": True,
        },
        "python": "3.11.16", "source_snapshot_sha256": "8" * 64,
        "working_tree_base_commit": BASELINE_COMMIT,
        "source_representation": (
            "copied tracked working-tree bytes, including uncommitted changes; not a claimed commit"
        ),
    }


def _closed_may_evidence() -> dict[str, Any]:
    verification = _may_verification()
    return {
        "status": "PASS", "checks": 62, "mismatch_count": 0,
        "baseline_manifest_sha256": "f" * 64, "replay_manifest_sha256": "0" * 64,
        "numerical_equivalence_within_tolerance": True, "raw_unchanged": True,
        "frozen_public_unchanged": True,
        "arrays": {"compared_count": 15, "exact_equal_count": 15},
        "public_files": {"compared_count": 13, "byte_equal_count": 10},
        "numeric_comparison": {
            **verification["numeric_details"], **verification["numerical_equality_definition"],
        },
        "runtime_python": "3.11.16",
        "source": {"representation": "working_tree_snapshot", "snapshot_sha256": "8" * 64,
                   "working_tree_base_commit": BASELINE_COMMIT},
        "verification_content_sha256": hashlib.sha256((
            json.dumps(verification, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
            + "\n"
        ).encode("utf-8")).hexdigest(),
    }


@pytest.fixture
def evidence(tmp_path: Path) -> dict[str, Any]:
    after = tmp_path / "after"
    before = tmp_path / "before"
    results = []
    for month in MONTHS:
        config = jpl_month_config(month)
        docs = _month_documents(month, config.expected_bins, config.expected_scheduled_issue_times)
        cleaning = docs["cleaning_qa.json"]
        if month == "2019-08":
            cleaning["invalid_containers"]["charging_current"].update(count=0, rate=0.0)
            cleaning["session_accounting"].update(
                current_analyzable_session_count=10, invalid_container_placeholder_count=0,
                current_only_invalid_count=0, metadata_checked_session_count=0,
                metadata_match_session_count=0, whole_current_unobservable_session_count=0,
            )
            for name in ("raw_field_coverage", "analysis_field_coverage"):
                cleaning["trajectory_quarantine"][name]["current"].update(count=10, rate=1.0)
        else:
            docs["station_15min_qa.json"]["known_incomplete_current_bins"] = 5
            docs["station_15min_qa.json"]["known_incomplete_pilot_bins"] = (
                1 if month == "2019-11" else 0
            )
            docs["station_15min_qa.json"].update(
                valid_bins_at_80=config.expected_bins - 5,
                valid_bin_rate_at_80=(config.expected_bins - 5) / config.expected_bins,
                missing_bin_rate_at_80=5 / config.expected_bins,
                known_incomplete_current_excluded_bins_at_80=5,
            )
        results.append(build_month_preparation_result(config=config, documents=docs))
    publish_seasonal_release(tuple(results), after)
    for path in after.rglob("*"):
        if path.is_file():
            destination = before / path.relative_to(after)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(path.read_bytes())
    manifest = _json(before / "seasonal_snapshot_manifest.json")
    manifest.update(code_commit="b" * 40, config_sha256="c" * 64)
    comparison_months = []
    metadata_months = []
    for month in MONTHS:
        cleaning = _json(before / month / "cleaning_qa.json")
        count = cleaning.pop("session_accounting")["invalid_container_placeholder_count"]
        cleaning["schema_version"] = "acn-jpl-seasonal-preparation-cleaning-qa/v1"
        cleaning["cleaned_session_count"] -= count
        cleaning["invalid_skipped_session_count"] = count
        _write(before / month / "cleaning_qa.json", cleaning)
        run = _json(before / month / "run_manifest.json")
        run["cleaned_session_count"] -= count
        run["invalid_skipped_session_count"] = count
        _write(before / month / "run_manifest.json", run)
        station = _json(before / month / "station_15min_qa.json")
        station["valid_bins_at_90"] += 2 * count
        _write(before / month / "station_15min_qa.json", station)
        old_data = _json(before / month / "data_snapshot_manifest.json")
        old_data.update(code_commit=manifest["code_commit"], config_sha256=manifest["config_sha256"])
        old_data["processed_snapshot_sha256"] = "d" * 64
        _write(before / month / "data_snapshot_manifest.json", old_data)
        old_issue = _json(before / month / "issue_snapshot_qa.json")
        old_issue["snapshot_sha256"] = "e" * 64
        _write(before / month / "issue_snapshot_qa.json", old_issue)
        _checksums(before / month, MONTH_PAYLOAD_NAMES)
        declared = next(item for item in manifest["month_snapshots"] if item["month"] == month)
        declared["month_public_sha256"] = _hash(before / month / "SHA256SUMS")
        declared["processed_snapshot_sha256"] = old_data["processed_snapshot_sha256"]
        new_station = _json(after / month / "station_15min_qa.json")
        comparison_months.append({
            "month": month, "status": "PASS", "checks": 100, "mismatch_count": 0,
            "mismatch_categories": {}, "old_cleaned_count": 10 - count,
            "new_cleaned_count": 10, "invalid_structures_retained": count,
            "original_trajectory_quarantine_count": int(month == "2019-11"),
            "old_connected_session_seconds": 10000,
            "new_connected_session_seconds": 10000 + 4500 * count,
            "added_connected_session_seconds": 4500 * count,
            "affected_interval_bins": 5 * count,
            "changed_connected_bins": 5 * count,
            "known_incomplete_current_bins": new_station["known_incomplete_current_bins"],
            "known_incomplete_pilot_bins": new_station["known_incomplete_pilot_bins"],
            "old_valid90": station["valid_bins_at_90"],
            "new_valid90": new_station["valid_bins_at_90"],
            "old_valid_now_excluded_bins_at_90": 2 * count,
            "coverage_only_valid90": new_station["coverage_only_valid_bins_at_90"],
            "old_formal_issue_times": old_issue["formal_issue_times"],
            "formal_issue_times": old_issue["formal_issue_times"],
            "temporal_violations": 0,
            "august_numpy_comparisons": ({f"{tier}.{name}.npy": True
                                          for tier in ("M1", "M2", "M3")
                                          for name in ("issue_times", "nullable_mask", "values")}
                                         if month == "2019-08" else {}),
        })
        metadata_months.append({
            "month": month, "raw_session_count": 10, "invalid_container_union_count": count,
            "current_invalid_count": count, "pilot_invalid_count": 0,
            "current_only_invalid_count": count, "pilot_only_invalid_count": 0,
            "both_invalid_count": 0, "metadata_bad_count": 0,
            "metadata_normal_count": count, "official_metadata_matched_count": count,
            "official_metadata_missing_count": 0,
            "all_metadata_fields_exact_match_count": count,
            "all_metadata_fields_mismatch_count": 0,
            "connection_exact_official_match_count": count,
            "disconnect_exact_official_match_count": count,
            "unparseable_metadata_bounds_count": 0, "nonpositive_metadata_interval_count": 0,
            "invalid_metadata_timezone_count": 0,
            "unique_15min_bins_overlapping_invalid_sessions": 5 * count,
            "connected_seconds_inside_local_month": 4500 * count,
        })
    _write(before / "seasonal_snapshot_manifest.json", manifest)
    _checksums(before, (*ROOT_PAYLOAD_NAMES, *(f"{month}/{name}" for month in MONTHS
                                             for name in MONTH_RELEASE_NAMES)))
    entries = [{"relative_path": path.relative_to(before).as_posix(),
                "size_bytes": path.stat().st_size, "sha256": _hash(path)}
               for path in sorted(before.rglob("*")) if path.is_file()]
    public_digest = hashlib.sha256("".join(
        f"{item['relative_path']}\t{item['size_bytes']}\t{item['sha256']}\n" for item in entries
    ).encode()).hexdigest()
    return {
        "before_public_root": before, "after_public_root": after,
        "baseline_commit": BASELINE_COMMIT,
        "baseline_inventory": {
            "baseline_commit": BASELINE_COMMIT, "copy_only": True,
            "source_files_unchanged_during_copy": True,
            "sources": {"public": {"copy_all_hashes_match": True, "entries": entries,
                                   "file_count": len(entries), "inventory_sha256": public_digest},
                        "raw": {"file_count": 12}},
        },
        "comparison": {"status": "PASS", "baseline_commit": BASELINE_COMMIT,
                       "raw_files_unchanged": 12, "months": comparison_months,
                       "identifiers_emitted": False, "timestamp_fingerprints_emitted": False},
        "metadata_audit": {"status": "PASS", "baseline_commit": BASELINE_COMMIT,
                           "raw_modified": False, "models_run": False, "downloads": 0,
                           "identifiers_emitted": False, "timestamp_fingerprints_emitted": False,
                           "official_metadata_duplicate_pair_count": 0, "months": metadata_months},
        "may_regression": _closed_may_evidence(),
    }


def test_builder_binds_old_and_new_counts_without_hardcoded_prior_results(evidence) -> None:
    module = _module()
    result = module.build_reconciliation(**evidence)

    module.validate_reconciliation(result)
    assert result["baseline_commit"] == BASELINE_COMMIT
    assert result["before_provenance"]["code_commit"] == "b" * 40
    assert result["before_provenance"]["code_commit"] != result["baseline_commit"]
    first = result["months"][0]
    assert first["before"]["structural_session_count"] == 9
    assert first["after"]["structural_session_count"] == 10
    assert first["changes"]["connected_session_seconds"] == 4500
    assert first["changes"]["valid_bins_at_90"] == -2
    assert first["changes"]["old_valid_now_excluded_bins_at_90"] == 2
    assert first["before"]["issue_snapshot_sha256"] == "e" * 64
    assert first["after"]["issue_snapshot_sha256"] == "6" * 64
    assert result["regressions"]["august"]["checked_array_count"] == 9
    assert result["publication"]["total_public_file_count"] == 39
    assert result == module.build_reconciliation(**evidence)


@pytest.mark.parametrize("source", ["comparison", "metadata_audit", "may_regression"])
def test_failed_audit_cannot_publish_a_successful_correction(evidence, source) -> None:
    module = _module()
    evidence[source]["status"] = "FAIL"
    with pytest.raises(module.ReconciliationError):
        module.build_reconciliation(**evidence)


@pytest.mark.parametrize("mutation", ["metadata", "connected", "valid", "august", "raw"])
def test_independent_audit_must_agree_with_public_artifacts(evidence, mutation) -> None:
    module = _module()
    if mutation == "metadata":
        evidence["metadata_audit"]["months"][0]["metadata_bad_count"] = 1
    elif mutation == "connected":
        evidence["comparison"]["months"][0]["added_connected_session_seconds"] += 1
    elif mutation == "valid":
        evidence["comparison"]["months"][0]["new_valid90"] -= 1
    elif mutation == "august":
        evidence["comparison"]["months"][1]["august_numpy_comparisons"]["M1.values.npy"] = False
    else:
        evidence["comparison"]["raw_files_unchanged"] -= 1
    with pytest.raises(module.ReconciliationError):
        module.build_reconciliation(**evidence)


def test_before_inventory_and_after_release_are_verified_from_bytes(evidence) -> None:
    module = _module()
    path = evidence["before_public_root"] / "2019-02" / "issue_snapshot_qa.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(module.ReconciliationError):
        module.build_reconciliation(**evidence)


def test_august_requires_exact_named_arrays_not_arbitrary_nine_successes(evidence) -> None:
    module = _module()
    evidence["comparison"]["months"][1]["august_numpy_comparisons"] = {
        f"unrelated_{index}.npy": True for index in range(9)
    }
    with pytest.raises(module.ReconciliationError):
        module.build_reconciliation(**evidence)


def test_current_release_must_pass_the_existing_closed_verifier(evidence) -> None:
    module = _module()
    (evidence["after_public_root"] / "extra.json").write_text("{}", encoding="utf-8")
    with pytest.raises(module.ReconciliationError):
        module.build_reconciliation(**evidence)


@pytest.mark.parametrize("mutation", ["extra", "delta", "digest", "bool", "missing"])
def test_closed_document_validator_rejects_privacy_and_consistency_drift(evidence, mutation) -> None:
    module = _module()
    result = module.build_reconciliation(**evidence)
    if mutation == "extra":
        result["months"][0]["sessionID"] = "not-permitted"
    elif mutation == "delta":
        result["months"][0]["changes"]["formal_issue_times"] += 1
    elif mutation == "digest":
        result["before_provenance"]["code_commit"] = "C:\\private\\source"
    elif mutation == "bool":
        result["months"][0]["after"]["structural_session_count"] = True
    else:
        del result["regressions"]["may"]["raw_unchanged"]
    with pytest.raises(module.ReconciliationError):
        module.validate_reconciliation(result)


def test_publisher_creates_only_correction_pair_and_is_idempotent(evidence, tmp_path) -> None:
    module = _module()
    result = module.build_reconciliation(**evidence)
    destination = tmp_path / "correction"
    module.publish_reconciliation(result, destination)
    first = {path.name: path.read_bytes() for path in destination.iterdir()}
    assert set(first) == {"reconciliation.json", "SHA256SUMS"}
    assert first["SHA256SUMS"] == (
        hashlib.sha256(first["reconciliation.json"]).hexdigest() + "  reconciliation.json\n"
    ).encode()
    module.publish_reconciliation(result, destination)
    assert first == {path.name: path.read_bytes() for path in destination.iterdir()}
    changed = copy.deepcopy(result)
    changed["baseline_commit"] = "9" * 40
    with pytest.raises(module.ReconciliationError):
        module.publish_reconciliation(changed, destination)
    assert first == {path.name: path.read_bytes() for path in destination.iterdir()}


def test_may_extractor_distinguishes_exact_arrays_bytes_and_numeric_tolerance() -> None:
    module = _module()
    result = module.extract_may_regression(_may_verification())

    assert result == _closed_may_evidence()
    assert "numerical_values_unchanged" not in result
    assert result["arrays"] == {"compared_count": 15, "exact_equal_count": 15}
    assert result["public_files"] == {"compared_count": 13, "byte_equal_count": 10}
    assert result["numeric_comparison"]["exact_difference_count"] == 1138
    assert result["source"]["representation"] == "working_tree_snapshot"
    assert "code_commit" not in result["source"]


@pytest.mark.parametrize("mutation", ["array", "bytes", "raw", "status", "base_commit"])
def test_may_extractor_rejects_contradictory_original_verification(mutation) -> None:
    module = _module()
    verification = _may_verification()
    if mutation == "array":
        verification["local_artifact_comparison"]["synthetic.npz"]["arrays"]["array_0"][
            "exact_equal"] = False
    elif mutation == "bytes":
        verification["public_byte_matches"] = 13
    elif mutation == "raw":
        verification["raw_after_sha256"] = "2" * 64
    elif mutation == "status":
        verification["status"] = "FAIL"
    else:
        verification["working_tree_base_commit"] = "not-a-commit"
    with pytest.raises(module.ReconciliationError):
        module.extract_may_regression(verification)


@pytest.mark.parametrize(
    ("section", "key", "invalid"),
    [
        ("arrays", "exact_equal_count", 14),
        ("public_files", "byte_equal_count", 14),
        ("numeric_comparison", "max_absolute_difference", float("nan")),
        ("numeric_comparison", "max_absolute_difference", -1.0),
        ("numeric_comparison", "max_absolute_difference", 0.0),
        ("numeric_comparison", "exact_difference_count", 0),
        ("numeric_comparison", "tolerance_failure_count", 1),
        ("numeric_comparison", "absolute_tolerance", 0.1),
        ("numeric_comparison", "relative_tolerance", True),
        ("source", "representation", "committed_source"),
        ("source", "snapshot_sha256", "C:\\private\\source"),
    ],
)
def test_may_closed_validator_rejects_precision_or_provenance_overclaims(
    evidence, section, key, invalid
) -> None:
    module = _module()
    evidence["may_regression"][section][key] = invalid
    with pytest.raises(module.ReconciliationError):
        module.build_reconciliation(**evidence)
