from __future__ import annotations

import csv
import gzip
import itertools
import json
from collections import defaultdict
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts_pipeline"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import build_vote_explorer_analysis_data as analysis  # noqa: E402


class CovoteScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        path = ROOT / "vote_explorer" / "data" / "analysis_covote_pairs_all.csv"
        with path.open(encoding="utf-8-sig", newline="") as handle:
            cls.rows = list(csv.DictReader(handle))

    @staticmethod
    def _key(round_no: int, category: str, name_a: str, name_b: str) -> tuple[int, str, str, str]:
        return (round_no, category, *sorted((analysis.normalize_name(name_a), analysis.normalize_name(name_b))))

    def test_scope_fields_and_states_are_explicit(self) -> None:
        required = {"pair_category", "data_completeness", "censoring_status", "complete_pair_matrix", "metric_status"}
        self.assertTrue(required.issubset(self.rows[0]))
        self.assertEqual({row["pair_category"] for row in self.rows}, {"character", "music"})
        self.assertEqual(
            {
                (row["data_completeness"], row["censoring_status"])
                for row in self.rows
            },
            {
                ("complete_matrix", "not_censored"),
                ("official_published_leading_list", "right_censored_by_official_list"),
            },
        )

    def test_cn_complete_matrix_row_counts_and_explicit_zeros(self) -> None:
        for round_no in (10, 11):
            for category, filename in (("character", "character_reconstruction_validation.json"), ("music", "music_reconstruction_validation.json")):
                validation_path = ROOT / "data_raw" / "cn_official" / f"round_{round_no:02d}" / "covote" / filename
                validation = json.loads(validation_path.read_text(encoding="utf-8"))
                rows = [
                    row for row in self.rows
                    if row["region"] == "cn"
                    and int(row["round"]) == round_no
                    and row["pair_category"] == category
                ]
                self.assertEqual(len(rows), validation["expectedPairs"], (round_no, category))
                self.assertTrue(all(row["data_completeness"] == "complete_matrix" for row in rows))
                self.assertTrue(all(row["censoring_status"] == "not_censored" for row in rows))
                self.assertTrue(all(row["complete_pair_matrix"] == "True" for row in rows))
                self.assertTrue(all(row["metric_status"] == "exact_complete_2x2" for row in rows))
                self.assertGreater(sum(row["intersection_count"] == "0" for row in rows), 0)

    def test_jp_rows_are_exactly_the_published_same_department_pairs(self) -> None:
        source_pairs: dict[tuple[int, str], set[tuple[int, str, str, str]]] = defaultdict(set)
        source_path = ROOT / "data_processed" / "jp_unified" / "entity_association_long.csv.gz"
        with gzip.open(source_path, "rt", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                category = row.get("source_category", "")
                if category not in {"character", "music"} or row.get("target_category") != category:
                    continue
                if analysis.normalize_name(row["source_name"]) == analysis.normalize_name(row["target_name"]):
                    continue
                round_no = int(row["round"])
                source_pairs[(round_no, category)].add(
                    self._key(round_no, category, row["source_name"], row["target_name"])
                )

        output_pairs: dict[tuple[int, str], set[tuple[int, str, str, str]]] = defaultdict(set)
        for row in self.rows:
            if row["region"] != "jp":
                continue
            round_no = int(row["round"])
            category = row["pair_category"]
            output_pairs[(round_no, category)].add(
                self._key(round_no, category, row["name_a"], row["name_b"])
            )
            self.assertEqual(row["data_completeness"], "official_published_leading_list")
            self.assertEqual(row["censoring_status"], "right_censored_by_official_list")
            self.assertEqual(row["complete_pair_matrix"], "False")

        self.assertEqual(dict(source_pairs), dict(output_pairs))
        self.assertTrue(any(category == "music" for _, category in output_pairs))

    def test_unavailable_rounds_have_no_placeholder_pairs(self) -> None:
        self.assertFalse(any(row["region"] == "cn" and int(row["round"]) <= 9 for row in self.rows))
        self.assertFalse(any(row["region"] == "jp" and int(row["round"]) <= 10 for row in self.rows))

    def test_unlisted_jp_pair_is_not_materialized_as_zero(self) -> None:
        round_no, category = 22, "character"
        source_path = ROOT / "data_processed" / "jp_unified" / "entity_association_long.csv.gz"
        entities: set[str] = set()
        published: set[tuple[int, str, str, str]] = set()
        with gzip.open(source_path, "rt", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if int(row["round"]) != round_no or row.get("source_category") != category or row.get("target_category") != category:
                    continue
                entities.update((row["source_name"], row["target_name"]))
                published.add(self._key(round_no, category, row["source_name"], row["target_name"]))
        output = {
            self._key(round_no, category, row["name_a"], row["name_b"])
            for row in self.rows
            if row["region"] == "jp" and int(row["round"]) == round_no and row["pair_category"] == category
        }
        missing = next(
            pair for pair in itertools.combinations(sorted(entities), 2)
            if self._key(round_no, category, *pair) not in published
        )
        missing_key = self._key(round_no, category, *missing)
        self.assertNotIn(missing_key, output)
        self.assertFalse(any(
            self._key(round_no, category, row["name_a"], row["name_b"]) == missing_key
            and row["intersection_count"] == "0"
            for row in self.rows
        ))

    def test_music_rows_are_not_cp_fallback_candidates(self) -> None:
        self.assertTrue(analysis._is_music_covote_row({"pair_category": "music"}))
        self.assertFalse(analysis._is_music_covote_row({"pair_category": "character"}))
        self.assertTrue(analysis._is_music_covote_row({"source_type": "cn10_11_official_music_covote_matrix"}))


if __name__ == "__main__":
    unittest.main()
