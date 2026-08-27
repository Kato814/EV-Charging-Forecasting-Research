from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DOI_RE = re.compile(r"^doi:10\.\d{4,9}/\S+$", re.IGNORECASE)
ARXIV_RE = re.compile(r"^arXiv:\d{4}\.\d{4,5}$", re.IGNORECASE)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def valid_url(value: str) -> bool:
    if not value:
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def unique_ids(
    path: Path,
    id_column: str,
    errors: list[str],
    *,
    require_rows: bool = True,
) -> tuple[list[dict[str, str]], set[str]]:
    rows = read_csv(path)
    if require_rows and not rows:
        errors.append(f"{path}: no rows")
        return rows, set()
    if rows and id_column not in rows[0]:
        errors.append(f"{path}: missing id column {id_column}")
        return rows, set()
    identifiers = [row.get(id_column, "").strip() for row in rows]
    for line, value in enumerate(identifiers, start=2):
        if not value:
            errors.append(f"{path}:{line}: missing {id_column}")
    duplicates = sorted({value for value in identifiers if value and identifiers.count(value) > 1})
    for value in duplicates:
        errors.append(f"{path}: duplicate {id_column} {value}")
    return rows, set(identifiers) - {""}


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    literature_files = [
        ROOT / "literature/core_library.csv",
        ROOT / "literature/frontier_watchlist.csv",
    ]
    literature_ids: set[str] = set()
    required_literature = {
        "paper_id",
        "title",
        "year",
        "publication_status",
        "identifier",
        "official_url",
        "review_depth",
        "verified_on",
    }
    literature_counts: dict[str, int] = {}

    for path in literature_files:
        rows, ids = unique_ids(path, "paper_id", errors)
        literature_counts[path.name] = len(rows)
        overlap = literature_ids & ids
        for value in sorted(overlap):
            errors.append(f"duplicate paper_id across libraries: {value}")
        literature_ids |= ids

        if rows:
            missing_cols = required_literature - set(rows[0])
            if missing_cols:
                errors.append(f"{path}: missing columns {sorted(missing_cols)}")
        for line, row in enumerate(rows, start=2):
            if not row.get("title", "").strip():
                errors.append(f"{path}:{line}: missing title")
            identifier = row.get("identifier", "").strip()
            if identifier.lower().startswith("doi:") and not DOI_RE.match(identifier):
                errors.append(f"{path}:{line}: malformed DOI identifier {identifier}")
            if identifier.lower().startswith("arxiv:") and not ARXIV_RE.match(identifier):
                errors.append(f"{path}:{line}: malformed arXiv identifier {identifier}")
            if not valid_url(row.get("official_url", "").strip()):
                errors.append(f"{path}:{line}: malformed official_url")
            if path.name == "frontier_watchlist.csv" and row.get("publication_status") == "peer-reviewed":
                warnings.append(f"{path}:{line}: peer-reviewed item may belong in core library")
            if row.get("review_depth") == "reviewed-full" and row.get("status") in {
                "watchlist",
                "metadata-check",
            }:
                errors.append(f"{path}:{line}: inconsistent review status")

    method_rows, method_ids = unique_ids(
        ROOT / "literature/method_foundations.csv", "method_id", errors
    )
    for line, row in enumerate(method_rows, start=2):
        if not valid_url(row.get("official_url", "").strip()):
            errors.append(f"method_foundations.csv:{line}: malformed official_url")

    dataset_rows, dataset_ids = unique_ids(
        ROOT / "datasets/dataset_catalog.csv", "dataset_id", errors
    )
    code_rows, _ = unique_ids(
        ROOT / "related_code/repositories.csv", "repo_id", errors
    )
    evidence_rows, _ = unique_ids(
        ROOT / "literature/round2_evidence_matrix.csv", "evidence_id", errors
    )
    direction_rows, _ = unique_ids(
        ROOT / "research/round2_direction_scorecard.csv", "direction_id", errors
    )

    known_records = literature_ids | method_ids
    for line, row in enumerate(evidence_rows, start=2):
        record_id = row.get("record_id", "").strip()
        if record_id not in known_records:
            errors.append(
                f"round2_evidence_matrix.csv:{line}: unknown record_id {record_id}"
            )
        if not valid_url(row.get("primary_source", "").strip()):
            errors.append(
                f"round2_evidence_matrix.csv:{line}: malformed primary_source"
            )

    field_rows = read_csv(ROOT / "datasets/field_audit.csv")
    for line, row in enumerate(field_rows, start=2):
        dataset_id = row.get("dataset_id", "").strip()
        if dataset_id not in dataset_ids:
            errors.append(f"field_audit.csv:{line}: unknown dataset_id {dataset_id}")

    required_files = [
        "literature/search_protocol.md",
        "literature/round2_search_log.csv",
        "literature/round2_evidence_matrix.csv",
        "datasets/dataset_catalog.csv",
        "datasets/field_audit.csv",
        "research/evidence_synthesis_v0.3.md",
        "research/decision_recommendation_v0.3.md",
        "research/novelty_red_lines.md",
        "research/round2_direction_scorecard.csv",
        "docs/ROUND2_REVIEW_PROTOCOL.md",
        "code/configs/base.yaml",
    ]
    for relative in required_files:
        if not (ROOT / relative).exists():
            errors.append(f"missing required file: {relative}")

    manifest_path = ROOT / "MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"MANIFEST.json: {exc}")
        manifest = {}

    expected_counts = {
        "core_peer_reviewed_records": literature_counts.get("core_library.csv", 0),
        "frontier_records": literature_counts.get("frontier_watchlist.csv", 0),
        "method_foundation_records": len(method_rows),
        "round2_evidence_records": len(evidence_rows),
        "candidate_direction_records": len(direction_rows),
        "dataset_records": len(dataset_rows),
        "related_code_records": len(code_rows),
    }
    for key, expected in expected_counts.items():
        if manifest.get(key) != expected:
            errors.append(
                f"MANIFEST.json: {key}={manifest.get(key)!r}, expected {expected}"
            )

    if errors:
        print("VALIDATION FAILED")
        for item in errors:
            print(f"ERROR: {item}")
        for item in warnings:
            print(f"WARNING: {item}")
        return 1

    print(
        "VALIDATION PASS: "
        f"{len(literature_ids)} EV literature records, "
        f"{len(method_rows)} method records, "
        f"{len(dataset_rows)} datasets, "
        f"{len(evidence_rows)} round-2 evidence records, "
        f"{len(direction_rows)} candidate directions"
    )
    for item in warnings:
        print(f"WARNING: {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
