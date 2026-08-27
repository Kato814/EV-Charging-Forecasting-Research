from __future__ import annotations

import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RepositoryIntegrityTest(unittest.TestCase):
    def test_core_library_has_unique_ids(self) -> None:
        with (ROOT / "literature/core_library.csv").open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        ids = [row["paper_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 30)

    def test_required_research_files_exist(self) -> None:
        required = [
            "literature/search_protocol.md",
            "datasets/dataset_catalog.csv",
            "research/gap_map.md",
            "code/configs/base.yaml",
        ]
        for rel in required:
            self.assertTrue((ROOT / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
