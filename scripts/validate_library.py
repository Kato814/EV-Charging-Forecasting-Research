from __future__ import annotations

import csv
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


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    files = [
        ROOT / "literature/core_library.csv",
        ROOT / "literature/frontier_watchlist.csv",
    ]
    seen: set[str] = set()
    required = {"paper_id", "title", "year", "publication_status", "identifier", "official_url", "review_depth", "verified_on"}
    for path in files:
        rows = read_csv(path)
        if not rows:
            errors.append(f"{path}: no rows")
            continue
        missing_cols = required - set(rows[0])
        if missing_cols:
            errors.append(f"{path}: missing columns {sorted(missing_cols)}")
        for i, row in enumerate(rows, start=2):
            rid = row.get("paper_id", "").strip()
            if not rid:
                errors.append(f"{path}:{i}: missing paper_id")
            elif rid in seen:
                errors.append(f"duplicate paper_id: {rid}")
            seen.add(rid)
            if not row.get("title", "").strip():
                errors.append(f"{path}:{i}: missing title")
            identifier = row.get("identifier", "").strip()
            if identifier.lower().startswith("doi:") and not DOI_RE.match(identifier):
                errors.append(f"{path}:{i}: malformed DOI identifier {identifier}")
            if identifier.lower().startswith("arxiv:") and not ARXIV_RE.match(identifier):
                errors.append(f"{path}:{i}: malformed arXiv identifier {identifier}")
            if not valid_url(row.get("official_url", "").strip()):
                errors.append(f"{path}:{i}: malformed official_url")
            if path.name == "frontier_watchlist.csv" and row.get("publication_status") == "peer-reviewed":
                warnings.append(f"{path}:{i}: peer-reviewed item may belong in core library")
            if row.get("review_depth") == "reviewed-full" and row.get("status") in {"watchlist", "metadata-check"}:
                errors.append(f"{path}:{i}: inconsistent review status")

    dataset_path = ROOT / "datasets/dataset_catalog.csv"
    dataset_rows = read_csv(dataset_path)
    d_ids = [r["dataset_id"] for r in dataset_rows]
    if len(d_ids) != len(set(d_ids)):
        errors.append("duplicate dataset_id")

    if errors:
        print("VALIDATION FAILED")
        for item in errors:
            print(f"ERROR: {item}")
        for item in warnings:
            print(f"WARNING: {item}")
        return 1

    print(f"VALIDATION PASS: {len(seen)} literature records, {len(dataset_rows)} datasets")
    for item in warnings:
        print(f"WARNING: {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
