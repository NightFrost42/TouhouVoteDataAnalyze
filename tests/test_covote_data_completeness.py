from __future__ import annotations

import csv
import gzip
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts_pipeline"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from scripts_pipeline import audit_covote_metrics as audit
from scripts_pipeline import build_vote_explorer_analysis_data as analysis
from scripts_pipeline.covote_metrics import empty_exact_metrics, source_scope_label


class CovoteDataCompletenessTests(unittest.TestCase):
    def test_pair_keys_are_symmetric_without_collapsing_blank_names(self) -> None:
        self.assertEqual(audit.pair_key("Ｂeta", "alpha"), audit.pair_key("alpha", "Ｂeta"))
        self.assertEqual(analysis.canonical_pair_key("Beta", "alpha"), "alpha|beta")
        self.assertEqual(analysis.canonical_pair_key("same", "same"), "")
        self.assertEqual(analysis.canonical_pair_key("", "alpha"), "")

    def test_scope_and_empty_metrics_make_incompleteness_explicit(self) -> None:
        self.assertEqual(source_scope_label(True), "complete_pair_matrix")
        self.assertEqual(source_scope_label(False), "published_leading_list")
        values = empty_exact_metrics("official_published_leading_list")
        self.assertFalse(values["complete_pair_matrix"])
        self.assertEqual(values["metric_status"], "official_published_leading_list")
        for field in ("m00_both_selected", "m01_b_only", "m10_a_only", "m11_neither_selected", "phi"):
            self.assertIsNone(values[field])
        self.assertNotIn("lift", values)  # JP published rate-ratio lift is not an exact 2x2 lift.

    @staticmethod
    def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_jp_leading_list_preserves_blank_reverse_direction_and_no_zero_fill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "vote_explorer" / "data"
            self._write_csv(
                output / "rankings.csv",
                ["region", "round", "category", "entity_name", "entity_name_localized", "rank", "vote_count", "ballots"],
                [
                    {"region": "jp", "round": "22", "category": "character", "entity_name": "A", "entity_name_localized": "甲", "rank": "1", "vote_count": "80", "ballots": "100"},
                    {"region": "jp", "round": "22", "category": "character", "entity_name": "B", "entity_name_localized": "乙", "rank": "2", "vote_count": "10", "ballots": "100"},
                ],
            )
            association = root / "data_processed" / "jp_unified" / "entity_association_long.csv.gz"
            association.parent.mkdir(parents=True)
            fields = ["round", "source_category", "target_category", "source_name", "target_name", "intersection_count", "conditional_rate", "lift"]
            with gzip.open(association, "wt", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"round": "22", "source_category": "character", "target_category": "character", "source_name": "A", "target_name": "B", "intersection_count": "4", "conditional_rate": "0.05", "lift": "0.5"})

            with patch.object(analysis, "ROOT", root), patch.object(analysis, "OUT", output):
                rows = analysis.build_covote_pairs([], {}, [])

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["data_completeness"], "official_published_leading_list")
        self.assertEqual(row["censoring_status"], "right_censored_by_official_list")
        self.assertEqual(row["complete_pair_matrix"], False)
        self.assertEqual(row["raw_count_a_to_b"], 4)
        self.assertEqual(row["raw_count_b_to_a"], "")
        self.assertEqual(row["conditional_rate_a_to_b"], 0.05)
        self.assertEqual(row["conditional_rate_b_to_a"], "")
        self.assertEqual(row["intersection_count"], 4)
        self.assertEqual(row["m00_both_selected"], None)
        self.assertEqual(row["lift"], 0.5)
        self.assertEqual(row["phi"], None)

    def test_conflicting_published_directions_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "vote_explorer" / "data"
            self._write_csv(
                output / "rankings.csv",
                ["region", "round", "category", "entity_name", "entity_name_localized", "rank", "vote_count", "ballots"],
                [
                    {"region": "jp", "round": "22", "category": "character", "entity_name": "A", "entity_name_localized": "甲", "rank": "1", "vote_count": "80", "ballots": "100"},
                    {"region": "jp", "round": "22", "category": "character", "entity_name": "B", "entity_name_localized": "乙", "rank": "2", "vote_count": "10", "ballots": "100"},
                ],
            )
            association = root / "data_processed" / "jp_unified" / "entity_association_long.csv.gz"
            association.parent.mkdir(parents=True)
            fields = ["round", "source_category", "target_category", "source_name", "target_name", "intersection_count", "conditional_rate", "lift"]
            with gzip.open(association, "wt", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for source, target, count in (("A", "B", "4"), ("B", "A", "5")):
                    writer.writerow({"round": "22", "source_category": "character", "target_category": "character", "source_name": source, "target_name": target, "intersection_count": count, "conditional_rate": "0.05", "lift": "0.5"})
            with patch.object(analysis, "ROOT", root), patch.object(analysis, "OUT", output):
                rows = analysis.build_covote_pairs([], {}, [])

        row = rows[0]
        self.assertEqual(row["metric_status"], "conflicting_published_directions")
        self.assertEqual(row["intersection_count"], "")
        self.assertEqual(row["raw_count"], "")
        self.assertEqual(row["anomaly"], "true")
        self.assertIsNone(row["phi"])


if __name__ == "__main__":
    unittest.main()
