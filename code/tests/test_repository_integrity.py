from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def rows(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class RepositoryIntegrityTest(unittest.TestCase):
    def test_core_library_has_unique_ids(self) -> None:
        records = rows("literature/core_library.csv")
        ids = [row["paper_id"] for row in records]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 46)

    def test_round2_evidence_references_known_records(self) -> None:
        paper_ids = {
            row["paper_id"]
            for file in [
                "literature/core_library.csv",
                "literature/frontier_watchlist.csv",
            ]
            for row in rows(file)
        }
        method_ids = {
            row["method_id"] for row in rows("literature/method_foundations.csv")
        }
        evidence_ids = {
            row["record_id"] for row in rows("literature/round2_evidence_matrix.csv")
        }
        self.assertTrue(evidence_ids <= paper_ids | method_ids)
        self.assertGreaterEqual(len(evidence_ids), 18)

    def test_direction_scorecard_has_unique_ids_and_decisions(self) -> None:
        records = rows("research/round2_direction_scorecard.csv")
        ids = [row["direction_id"] for row in records]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 8)
        self.assertTrue(all(row["current_decision"].strip() for row in records))

    def test_dataset_field_audit_references_catalog(self) -> None:
        dataset_ids = {row["dataset_id"] for row in rows("datasets/dataset_catalog.csv")}
        audit_ids = {row["dataset_id"] for row in rows("datasets/field_audit.csv")}
        self.assertTrue(audit_ids <= dataset_ids)

    def test_manifest_counts_match_tables(self) -> None:
        manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
        expected = {
            "core_peer_reviewed_records": len(rows("literature/core_library.csv")),
            "frontier_records": len(rows("literature/frontier_watchlist.csv")),
            "method_foundation_records": len(rows("literature/method_foundations.csv")),
            "round2_evidence_records": len(rows("literature/round2_evidence_matrix.csv")),
            "candidate_direction_records": len(rows("research/round2_direction_scorecard.csv")),
            "dataset_records": len(rows("datasets/dataset_catalog.csv")),
            "related_code_records": len(rows("related_code/repositories.csv")),
        }
        for key, value in expected.items():
            self.assertEqual(manifest[key], value, key)

    def test_required_round2_files_exist(self) -> None:
        required = [
            "literature/round2_search_log.csv",
            "literature/round2_evidence_matrix.csv",
            "datasets/field_audit.csv",
            "research/evidence_synthesis_v0.3.md",
            "research/decision_recommendation_v0.3.md",
            "research/novelty_red_lines.md",
            "research/round2_direction_scorecard.csv",
            "docs/ROUND2_REVIEW_PROTOCOL.md",
            "code/configs/base.yaml",
        ]
        for relative in required:
            self.assertTrue((ROOT / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
