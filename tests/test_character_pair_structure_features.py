from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts_pipeline import build_character_pair_structure_features as structure


class CharacterPairStructureFeatureTests(unittest.TestCase):
    def test_write_failure_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "features.csv"
            output.write_text("old result\n", encoding="utf-8")
            with mock.patch.object(structure.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    structure.write_csv(output, [{"name": "new"}], ["name"])
            self.assertEqual(output.read_text(encoding="utf-8"), "old result\n")
            self.assertEqual(list(output.parent.iterdir()), [output])

    def setUp(self) -> None:
        self.metadata = [
            {
                "canonical_name": "alpha",
                "canonical_name_cn": "Alpha",
                "crosswalk_key": "ALPHA",
                "character_jp": "Alpha",
                "character_jp_normalized": "Alpha",
                "reference_first_appearance_work": "Work A",
                "reference_identity_or_title": "title-a",
                "reference_character_type": "1",
                "reference_source_group": "正作游戏",
                "region": "Region A",
                "region_type": "geographic_region",
                "community": "Group A;Group B",
                "community_type": "formal_organization",
            },
            {
                "canonical_name": "beta",
                "canonical_name_cn": "Beta",
                "crosswalk_key": "BETA",
                "character_jp": "Beta",
                "character_jp_normalized": "Beta",
                "reference_first_appearance_work": "Work A",
                "reference_identity_or_title": "title-b",
                "reference_character_type": "2",
                "reference_source_group": "正作游戏",
                "region": "Region A",
                "region_type": "geographic_region",
                "community": "Group B",
                "community_type": "formal_organization",
            },
            {
                "canonical_name": "gamma",
                "canonical_name_cn": "Gamma",
                "crosswalk_key": "GAMMA",
                "character_jp": "Gamma",
                "character_jp_normalized": "Gamma",
                "reference_first_appearance_work": "Work B",
                "reference_identity_or_title": "title-c",
                "reference_character_type": "3",
                "reference_source_group": "出版物",
                "region": "Region B",
                "region_type": "geographic_region",
                "community": "",
                "community_type": "",
            },
        ]

    @staticmethod
    def pair(a: str, b: str, *, category: str = "character", source_type: str = "jp_official_entity_association") -> dict[str, str]:
        return {
            "region": "jp",
            "round": "22",
            "round_label": "JP22",
            "pair_category": category,
            "name_a": a,
            "name_b": b,
            "name_a_cn": a.title(),
            "name_b_cn": b.title(),
            "canonical_a": a,
            "canonical_b": b,
            "intersection_count": "10",
            "data_completeness": "official_published_leading_list",
            "censoring_status": "right_censored_by_official_list",
            "source_type": source_type,
            "source_path": "fixture.csv",
        }

    def test_pair_key_is_unordered_and_width_tolerant(self) -> None:
        self.assertEqual(
            structure.canonical_pair_key("Ｂeta", "alpha"),
            structure.canonical_pair_key("alpha", "beta"),
        )
        self.assertEqual(structure.canonical_pair_key("alpha", "alpha"), "")

    def test_features_are_computed_only_for_confirmed_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "features.csv"
            rows = structure.build_character_pair_structure_features(
                [
                    self.pair("beta", "alpha"),
                    self.pair("alpha", "beta"),
                    self.pair("alpha", "gamma"),
                    self.pair("beta", "unresolved"),
                ],
                self.metadata,
                output_path=output,
            )

        self.assertEqual(len(rows), 3)
        by_key = {row["canonical_pair_key"]: row for row in rows}
        same = by_key["alpha|beta"]
        self.assertEqual((same["canonical_a"], same["canonical_b"]), ("alpha", "beta"))
        self.assertEqual(same["same_reference_first_appearance_work"], "true")
        self.assertEqual(same["same_first_appearance_work"], "true")
        self.assertEqual(same["same_reference_character_type"], "false")
        self.assertEqual(same["same_reference_source_group"], "true")
        self.assertEqual(same["same_region"], "true")
        self.assertEqual(same["shared_community"], "true")
        self.assertEqual(same["common_community"], "Group B")

        partial = by_key["beta|unresolved"]
        self.assertEqual(partial["pair_metadata_status"], "partial")
        self.assertEqual(partial["same_region"], "unknown")
        self.assertEqual(partial["same_community"], "unknown")
        self.assertEqual(partial["shared_community"], "unknown")
        self.assertEqual(partial["same_reference_first_appearance_work"], "unknown")

        different = by_key["alpha|gamma"]
        self.assertEqual(different["same_region"], "false")
        self.assertEqual(different["same_reference_source_group"], "false")

    def test_music_rows_are_excluded_and_missing_metadata_is_not_false(self) -> None:
        rows = structure.build_character_pair_structure_features(
            [self.pair("alpha", "gamma", category="music", source_type="cn10_11_official_music_covote_matrix")],
            self.metadata,
            output_path=Path(tempfile.mkdtemp()) / "features.csv",
        )
        self.assertEqual(rows, [])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "features.csv"
            rows = structure.build_character_pair_structure_features(
                [self.pair("alpha", "unresolved")],
                self.metadata,
                output_path=output,
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pair_metadata_status"], "partial")
        self.assertEqual(rows[0]["same_region"], "unknown")
        self.assertEqual(rows[0]["same_reference_source_group"], "unknown")
        self.assertNotEqual(rows[0]["same_region"], "false")


if __name__ == "__main__":
    unittest.main()
