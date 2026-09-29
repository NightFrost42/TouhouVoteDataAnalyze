from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts_pipeline"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import audit_covote_metrics as audit  # noqa: E402


class CoVoteDataAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = audit.load_generated_pairs()
        cls.character_rows = audit.read_csv(audit.CHARACTER_PATH)
        cls.music_rows = audit.read_csv(audit.MUSIC_PATH)
        cls.association_rows = audit.read_gzip_csv(audit.JP_ASSOCIATION_PATH)

    def test_cn_complete_matrix_pair_counts_and_cells(self) -> None:
        expected = {
            (10, "character"): 28_441,
            (10, "music"): 176_715,
            (11, "character"): 29_646,
            (11, "music"): 186_966,
        }
        for (round_number, category), pair_count in expected.items():
            item = audit.audit_cn_matrix(round_number, category, self.generated)
            self.assertEqual(item["expected_pairs"], pair_count)
            self.assertEqual(item["raw_unique_pairs"], pair_count)
            self.assertEqual(item["generated_unique_pairs"], pair_count)
            self.assertEqual(item["missing_generated_pairs"], 0)
            self.assertEqual(item["extra_generated_pairs"], 0)
            self.assertEqual(item["mismatch_count"], 0)
            self.assertEqual(item["zero_preservation_failures"], 0)
            self.assertEqual(item["exact_metric_rows"], pair_count)

    def test_jp_leading_lists_have_no_complete_2x2_metrics(self) -> None:
        result = audit.audit_jp(
            self.generated, self.character_rows, self.music_rows, self.association_rows
        )
        self.assertFalse(result["hard_failures"])
        self.assertTrue(result["by_round_category"])
        for item in result["by_round_category"]:
            self.assertLess(item["coverage"], 1)
            self.assertEqual(item["complete_2x2_nonblank_cells"], 0)

    def test_cross_department_rows_do_not_claim_a_common_universe(self) -> None:
        result = audit.audit_cross_department(self.generated)
        self.assertEqual(result["exact_2x2_nonblank_rows"], 0)
        self.assertEqual(result["complete_pair_matrix_true_rows"], 0)


if __name__ == "__main__":
    unittest.main()
