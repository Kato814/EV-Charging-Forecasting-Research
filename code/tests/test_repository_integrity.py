from __future__ import annotations

import csv
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def rows(relative: str) -> list[dict[str, str]]:
    with (ROOT / relative).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class RepositoryIntegrityTest(unittest.TestCase):
    def test_literature_ids_and_identifiers_are_unique(self) -> None:
        records = rows("literature/core_library.csv") + rows(
            "literature/frontier_watchlist.csv"
        )
        ids = [row["paper_id"] for row in records]
        identifiers = [row["identifier"].casefold() for row in records if row["identifier"]]
        titles = [row["title"].casefold() for row in records if row["title"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(len(titles), len(set(titles)))
        self.assertGreaterEqual(len(rows("literature/core_library.csv")), 60)

    def test_evidence_references_known_records(self) -> None:
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
        dataset_ids = {row["dataset_id"] for row in rows("datasets/dataset_catalog.csv")}
        repo_ids = {row["repo_id"] for row in rows("related_code/repositories.csv")}
        round2_ids = {
            row["record_id"] for row in rows("literature/round2_evidence_matrix.csv")
        }
        round2b_ids = {
            row["record_id"] for row in rows("literature/round2b_evidence_matrix.csv")
        }
        round3_ids = {
            row["record_id"] for row in rows("literature/round3_evidence_matrix.csv")
        }
        self.assertTrue(round2_ids <= paper_ids | method_ids)
        self.assertTrue(round2b_ids <= paper_ids | method_ids | dataset_ids | repo_ids)
        self.assertTrue(round3_ids <= paper_ids | method_ids | dataset_ids | repo_ids)
        self.assertGreaterEqual(len(round2_ids), 30)
        self.assertGreaterEqual(len(round2b_ids), 20)
        self.assertGreaterEqual(len(round3_ids), 14)

    def test_direction_scorecards_have_unique_ids_and_decisions(self) -> None:
        for relative, minimum in [
            ("research/round2_direction_scorecard.csv", 13),
            ("research/round2b_direction_scorecard.csv", 8),
            ("research/round3_direction_scorecard.csv", 8),
        ]:
            records = rows(relative)
            ids = [row["direction_id"] for row in records]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertGreaterEqual(len(ids), minimum)
            self.assertTrue(all(row["current_decision"].strip() for row in records))

    def test_dataset_audits_reference_catalog(self) -> None:
        dataset_ids = {row["dataset_id"] for row in rows("datasets/dataset_catalog.csv")}
        audit_ids = {row["dataset_id"] for row in rows("datasets/field_audit.csv")}
        self.assertTrue(audit_ids <= dataset_ids)
        for path in (ROOT / "datasets/audits").glob("D*.md"):
            self.assertIn(path.stem.split("_", 1)[0], dataset_ids)

    def test_note_headers_match_record_ids(self) -> None:
        known_ids = {
            row["paper_id"]
            for file in [
                "literature/core_library.csv",
                "literature/frontier_watchlist.csv",
            ]
            for row in rows(file)
        } | {row["method_id"] for row in rows("literature/method_foundations.csv")}
        for path in (ROOT / "literature/notes").glob("*.md"):
            if path.name == "TEMPLATE.md":
                continue
            self.assertIn(path.stem, known_ids)
            match = re.search(r"^#\s+([PFM]\d{4})\b", path.read_text(encoding="utf-8"), re.MULTILINE)
            self.assertIsNotNone(match)
            self.assertEqual(match.group(1), path.stem)

    def test_manifest_counts_match_tables(self) -> None:
        manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
        expected = {
            "core_peer_reviewed_records": len(rows("literature/core_library.csv")),
            "frontier_records": len(rows("literature/frontier_watchlist.csv")),
            "method_foundation_records": len(rows("literature/method_foundations.csv")),
            "round2_evidence_records": len(rows("literature/round2_evidence_matrix.csv")),
            "round2_search_clusters": len(rows("literature/round2_search_log.csv")),
            "candidate_direction_records": len(rows("research/round2_direction_scorecard.csv")),
            "round2b_evidence_records": len(rows("literature/round2b_evidence_matrix.csv")),
            "round2b_search_clusters": len(rows("literature/round2b_search_log.csv")),
            "round2b_direction_records": len(rows("research/round2b_direction_scorecard.csv")),
            "round3_evidence_records": len(rows("literature/round3_evidence_matrix.csv")),
            "round3_search_clusters": len(rows("literature/round3_search_log.csv")),
            "round3_direction_records": len(rows("research/round3_direction_scorecard.csv")),
            "dataset_records": len(rows("datasets/dataset_catalog.csv")),
            "field_audit_records": len(rows("datasets/field_audit.csv")),
            "detailed_dataset_audit_notes": len(list((ROOT / "datasets/audits").glob("D*.md"))),
            "related_code_records": len(rows("related_code/repositories.csv")),
            "structured_note_files": len(
                [p for p in (ROOT / "literature/notes").glob("*.md") if p.name != "TEMPLATE.md"]
            ),
        }
        for key, value in expected.items():
            self.assertEqual(manifest[key], value, key)

    def test_required_review_files_exist(self) -> None:
        required = [
            "literature/round2_evidence_matrix.csv",
            "literature/round2b_evidence_matrix.csv",
            "literature/round2_search_log.csv",
            "literature/round2b_search_log.csv",
            "research/evidence_synthesis_v0.4.md",
            "research/decision_recommendation_v0.4.md",
            "research/extended_direction_landscape_v0.4.md",
            "research/expanded_candidate_directions_v0.4.md",
            "research/minimum_gate_plan_v0.4.md",
            "research/novelty_red_lines.md",
            "research/round2_direction_scorecard.csv",
            "research/round2b_direction_scorecard.csv",
            "docs/ROUND2_REVIEW_PROTOCOL.md",
            "docs/ROUND2_EXTENSION_PROTOCOL.md",
            "docs/ROUND2B_EXTENSION_PROTOCOL.md",
            "literature/round3_evidence_matrix.csv",
            "literature/round3_search_log.csv",
            "research/problem_gap_landscape_v0.5.md",
            "research/evidence_synthesis_v0.5.md",
            "research/decision_recommendation_v0.5.md",
            "research/minimum_gate_plan_v0.5.md",
            "research/round3_direction_scorecard.csv",
            "docs/ROUND3_PROBLEM_GAP_PROTOCOL.md",
        ]
        for relative in required:
            self.assertTrue((ROOT / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
