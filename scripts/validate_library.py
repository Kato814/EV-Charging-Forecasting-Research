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
NOTE_ID_RE = re.compile(r"^#\s+([PFM]\d{4})\b", re.MULTILINE)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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
        errors.append(f"{path.relative_to(ROOT)}: no rows")
        return rows, set()
    if rows and id_column not in rows[0]:
        errors.append(f"{path.relative_to(ROOT)}: missing id column {id_column}")
        return rows, set()

    values = [row.get(id_column, "").strip() for row in rows]
    for line, value in enumerate(values, start=2):
        if not value:
            errors.append(f"{path.relative_to(ROOT)}:{line}: missing {id_column}")
    duplicates = sorted({value for value in values if value and values.count(value) > 1})
    for value in duplicates:
        errors.append(f"{path.relative_to(ROOT)}: duplicate {id_column} {value}")
    return rows, set(values) - {""}


def check_unique_field(
    rows: list[dict[str, str]],
    field: str,
    label: str,
    errors: list[str],
) -> None:
    seen: dict[str, list[str]] = {}
    for row in rows:
        value = row.get(field, "").strip().casefold()
        if value:
            seen.setdefault(value, []).append(row.get("paper_id") or row.get("method_id") or "?")
    for value, identifiers in seen.items():
        if len(identifiers) > 1:
            errors.append(f"{label}: duplicate {field} for {identifiers}: {value}")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    core_rows, core_ids = unique_ids(ROOT / "literature/core_library.csv", "paper_id", errors)
    frontier_rows, frontier_ids = unique_ids(
        ROOT / "literature/frontier_watchlist.csv", "paper_id", errors
    )
    overlap = core_ids & frontier_ids
    for value in sorted(overlap):
        errors.append(f"duplicate paper_id across core/frontier libraries: {value}")
    literature_rows = core_rows + frontier_rows
    literature_ids = core_ids | frontier_ids

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
    for relative, rows in [
        ("literature/core_library.csv", core_rows),
        ("literature/frontier_watchlist.csv", frontier_rows),
    ]:
        if rows:
            missing = required_literature - set(rows[0])
            if missing:
                errors.append(f"{relative}: missing columns {sorted(missing)}")
        for line, row in enumerate(rows, start=2):
            if not row.get("title", "").strip():
                errors.append(f"{relative}:{line}: missing title")
            identifier = row.get("identifier", "").strip()
            if identifier.lower().startswith("doi:") and not DOI_RE.match(identifier):
                errors.append(f"{relative}:{line}: malformed DOI identifier {identifier}")
            if identifier.lower().startswith("arxiv:") and not ARXIV_RE.match(identifier):
                errors.append(f"{relative}:{line}: malformed arXiv identifier {identifier}")
            if not valid_url(row.get("official_url", "").strip()):
                errors.append(f"{relative}:{line}: malformed official_url")
            if relative.endswith("frontier_watchlist.csv") and row.get("publication_status") == "peer-reviewed":
                warnings.append(f"{relative}:{line}: peer-reviewed item may belong in core library")
    check_unique_field(literature_rows, "identifier", "literature libraries", errors)
    check_unique_field(literature_rows, "title", "literature libraries", errors)

    method_rows, method_ids = unique_ids(
        ROOT / "literature/method_foundations.csv", "method_id", errors
    )
    check_unique_field(method_rows, "identifier", "method foundations", errors)
    check_unique_field(method_rows, "title", "method foundations", errors)
    for line, row in enumerate(method_rows, start=2):
        if not valid_url(row.get("official_url", "").strip()):
            errors.append(f"literature/method_foundations.csv:{line}: malformed official_url")

    dataset_rows, dataset_ids = unique_ids(
        ROOT / "datasets/dataset_catalog.csv", "dataset_id", errors
    )
    repo_rows, repo_ids = unique_ids(
        ROOT / "related_code/repositories.csv", "repo_id", errors
    )
    check_unique_field(repo_rows, "url", "related code repositories", errors)

    round2_rows, _ = unique_ids(
        ROOT / "literature/round2_evidence_matrix.csv", "evidence_id", errors
    )
    round2b_rows, _ = unique_ids(
        ROOT / "literature/round2b_evidence_matrix.csv", "evidence_id", errors
    )
    round2_search_rows, _ = unique_ids(
        ROOT / "literature/round2_search_log.csv", "search_id", errors
    )
    round2b_search_rows, _ = unique_ids(
        ROOT / "literature/round2b_search_log.csv", "search_id", errors
    )
    direction_rows, _ = unique_ids(
        ROOT / "research/round2_direction_scorecard.csv", "direction_id", errors
    )
    direction_b_rows, _ = unique_ids(
        ROOT / "research/round2b_direction_scorecard.csv", "direction_id", errors
    )
    round3_rows, _ = unique_ids(
        ROOT / "literature/round3_evidence_matrix.csv", "evidence_id", errors
    )
    round3_search_rows, _ = unique_ids(
        ROOT / "literature/round3_search_log.csv", "search_id", errors
    )
    round3_direction_rows, _ = unique_ids(
        ROOT / "research/round3_direction_scorecard.csv", "direction_id", errors
    )

    for relative, rows, known in [
        ("literature/round2_evidence_matrix.csv", round2_rows, literature_ids | method_ids),
        (
            "literature/round2b_evidence_matrix.csv",
            round2b_rows,
            literature_ids | method_ids | dataset_ids | repo_ids,
        ),
        (
            "literature/round3_evidence_matrix.csv",
            round3_rows,
            literature_ids | method_ids | dataset_ids | repo_ids,
        ),
    ]:
        for line, row in enumerate(rows, start=2):
            record_id = row.get("record_id", "").strip()
            if record_id not in known:
                errors.append(f"{relative}:{line}: unknown record_id {record_id}")
            if not valid_url(row.get("primary_source", "").strip()):
                errors.append(f"{relative}:{line}: malformed primary_source")

    field_rows, _field_ids = unique_ids(ROOT / "datasets/field_audit.csv", "dataset_id", errors)
    for line, row in enumerate(field_rows, start=2):
        if row.get("dataset_id", "").strip() not in dataset_ids:
            errors.append(
                f"datasets/field_audit.csv:{line}: unknown dataset_id {row.get('dataset_id', '')}"
            )

    note_files = sorted(
        path for path in (ROOT / "literature/notes").glob("*.md") if path.name != "TEMPLATE.md"
    )
    known_note_ids = literature_ids | method_ids
    for path in note_files:
        if path.stem not in known_note_ids:
            errors.append(f"{path.relative_to(ROOT)}: note has no matching literature/method record")
        match = NOTE_ID_RE.search(path.read_text(encoding="utf-8"))
        if not match or match.group(1) != path.stem:
            errors.append(f"{path.relative_to(ROOT)}: first heading ID does not match filename")

    audit_note_files = sorted(
        path for path in (ROOT / "datasets/audits").glob("D*.md")
    )
    for path in audit_note_files:
        dataset_id = path.stem.split("_", 1)[0]
        if dataset_id not in dataset_ids:
            errors.append(f"{path.relative_to(ROOT)}: audit note has no matching dataset record")

    required_files = [
        "literature/search_protocol.md",
        "literature/round2_search_log.csv",
        "literature/round2_evidence_matrix.csv",
        "literature/round2b_search_log.csv",
        "literature/round2b_evidence_matrix.csv",
        "literature/round3_search_log.csv",
        "literature/round3_evidence_matrix.csv",
        "datasets/dataset_catalog.csv",
        "datasets/field_audit.csv",
        "research/evidence_synthesis_v0.4.md",
        "research/decision_recommendation_v0.4.md",
        "research/extended_direction_landscape_v0.4.md",
        "research/expanded_candidate_directions_v0.4.md",
        "research/minimum_gate_plan_v0.4.md",
        "research/novelty_red_lines.md",
        "research/round2_direction_scorecard.csv",
        "research/round2b_direction_scorecard.csv",
        "research/problem_gap_landscape_v0.5.md",
        "research/evidence_synthesis_v0.5.md",
        "research/decision_recommendation_v0.5.md",
        "research/minimum_gate_plan_v0.5.md",
        "research/round3_direction_scorecard.csv",
        "docs/ROUND3_PROBLEM_GAP_PROTOCOL.md",
        "docs/ROUND2_REVIEW_PROTOCOL.md",
        "docs/ROUND2_EXTENSION_PROTOCOL.md",
        "docs/ROUND2B_EXTENSION_PROTOCOL.md",
        "code/configs/base.yaml",
    ]
    for relative in required_files:
        if not (ROOT / relative).exists():
            errors.append(f"missing required file: {relative}")

    redline_text = (ROOT / "research/novelty_red_lines.md").read_text(encoding="utf-8")
    redline_numbers = [int(value) for value in re.findall(r"^## R(\d+)\.", redline_text, re.MULTILINE)]
    if len(redline_numbers) != len(set(redline_numbers)):
        errors.append("research/novelty_red_lines.md: duplicate red-line numbers")
    if redline_numbers and redline_numbers != list(range(1, max(redline_numbers) + 1)):
        errors.append("research/novelty_red_lines.md: red-line numbers are not contiguous")

    manifest_path = ROOT / "MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"MANIFEST.json: {exc}")
        manifest = {}

    expected_counts = {
        "core_peer_reviewed_records": len(core_rows),
        "frontier_records": len(frontier_rows),
        "method_foundation_records": len(method_rows),
        "round2_evidence_records": len(round2_rows),
        "round2_search_clusters": len(round2_search_rows),
        "candidate_direction_records": len(direction_rows),
        "round2b_evidence_records": len(round2b_rows),
        "round2b_search_clusters": len(round2b_search_rows),
        "round2b_direction_records": len(direction_b_rows),
        "round3_evidence_records": len(round3_rows),
        "round3_search_clusters": len(round3_search_rows),
        "round3_direction_records": len(round3_direction_rows),
        "dataset_records": len(dataset_rows),
        "field_audit_records": len(field_rows),
        "detailed_dataset_audit_notes": len(audit_note_files),
        "related_code_records": len(repo_rows),
        "structured_note_files": len(note_files),
    }
    for key, expected in expected_counts.items():
        if manifest.get(key) != expected:
            errors.append(f"MANIFEST.json: {key}={manifest.get(key)!r}, expected {expected}")

    if errors:
        print("VALIDATION FAILED")
        for item in errors:
            print(f"ERROR: {item}")
        for item in warnings:
            print(f"WARNING: {item}")
        return 1

    print(
        "VALIDATION PASS: "
        f"{len(core_rows)} core + {len(frontier_rows)} frontier papers, "
        f"{len(method_rows)} methods, {len(dataset_rows)} datasets, "
        f"{len(round2_rows)} + {len(round2b_rows)} + {len(round3_rows)} evidence records, "
        f"{len(direction_rows)} + {len(direction_b_rows)} + {len(round3_direction_rows)} candidate directions"
    )
    for item in warnings:
        print(f"WARNING: {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
