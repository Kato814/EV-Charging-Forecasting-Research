from __future__ import annotations

"""Fetch DOI metadata from Crossref without overwriting the curated evidence fields.

Usage:
    python scripts/sync_crossref.py

Network access is required. Results are written to literature/crossref_cache.json.
Review changes manually before updating BibTeX or CSV author/title fields.
"""

import csv
import json
import time
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = "EV-Charging-Forecasting-Research/0.1 (mailto:replace-with-project-email@example.com)"


def doi_records() -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for name in ("core_library.csv", "frontier_watchlist.csv"):
        with (ROOT / "literature" / name).open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                identifier = row["identifier"].strip()
                if identifier.lower().startswith("doi:"):
                    records.append((row["paper_id"], identifier[4:]))
    return records


def main() -> None:
    output: dict[str, dict] = {}
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    for paper_id, doi in doi_records():
        url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
        response = session.get(url, timeout=30)
        response.raise_for_status()
        output[paper_id] = response.json()["message"]
        print(f"fetched {paper_id} {doi}")
        time.sleep(0.2)
    target = ROOT / "literature/crossref_cache.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
