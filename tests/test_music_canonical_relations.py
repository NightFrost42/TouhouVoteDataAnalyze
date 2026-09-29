from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MusicCanonicalRelationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with (ROOT / "data_processed/music_canonical/local_music_merged.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            cls.merged = list(csv.DictReader(handle))
        with (ROOT / "data_processed/music_canonical/music_associations.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            cls.associations = list(csv.DictReader(handle))
        with (ROOT / "data_processed/music_canonical/local_music_source_rows.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            cls.source = list(csv.DictReader(handle))

    def _merged(self, title: str) -> list[dict[str, str]]:
        return [row for row in self.merged if row["canonical_track"] == title]

    def test_scene_context_does_not_project_to_character_theme(self) -> None:
        for title in ("Desire Drive", "Last Remote", "碎月", "魔法少女们的百年祭", "Voyage1969"):
            rows = self._merged(title)
            self.assertTrue(rows, title)
            for row in rows:
                self.assertEqual(json.loads(row["mapped_characters_json"]), [], title)
                self.assertTrue(json.loads(row["scene_context_json"]), title)
        scene_titles = {row["canonical_track"] for row in self.associations if row["association_type"] == "scene_context"}
        self.assertTrue({"Desire Drive", "Last Remote", "碎月"}.issubset(scene_titles))

    def test_derivative_relation_does_not_project_source_characters(self) -> None:
        rows = self._merged("桑尼米尔克的红雾异变")
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(json.loads(row["mapped_characters_json"]), [])
            self.assertEqual(json.loads(row["scene_context_json"]), [])
            self.assertIn("Sunny Rutile Flection", json.loads(row["derivative_sources_json"]))
        derivative = [row for row in self.associations if row["association_type"] == "derivative_source"]
        self.assertTrue(any(row["entity_name"] == "Sunny Rutile Flection" for row in derivative))
        self.assertTrue(all(row["entity_type"] == "music" for row in derivative))

    def test_official_supplement_does_not_reuse_previous_translation(self) -> None:
        rows = [
            row for row in self.source
            if row["source_kind"] == "normalized_jp_official"
        ]
        self.assertTrue(rows)
        for row in rows:
            # A normalized official row may have an authoritative translation,
            # but it must never inherit the preceding iteration's title.
            if row["title_variant_key"] == "th17-fuujin-manjuka":
                self.assertEqual(row["raw_title_jp"], "不朽の曼珠沙華", row)

    def test_scene_override_matches_official_japanese_variant(self) -> None:
        rows = [
            row for row in self.source
            if row["source_kind"] == "normalized_jp_official"
            and row["raw_title_jp"] == "不朽の曼珠沙華"
        ]
        self.assertTrue(rows)
        self.assertTrue(all(row["relation_type"] == "scene_context" for row in rows))
        self.assertTrue(all(row["mapped_character"] == "" for row in rows))

        base = self._merged("妖妖跋扈")
        who = self._merged("妖妖跋扈 ~ Who done it!")
        speed = self._merged("妖妖跋扈 ~ Speed Fox!")
        self.assertTrue(base and who and speed)
        self.assertEqual({json.loads(row["mapped_characters_json"])[0] for row in who}, {"八云蓝"})
        self.assertEqual({json.loads(row["mapped_characters_json"])[0] for row in speed}, {"八云蓝"})
        self.assertTrue(all(json.loads(row["mapped_characters_json"]) == [] for row in base))
        ids = {row["music_track_id"] for row in base + who + speed}
        self.assertEqual(len(ids), 3)

    def test_old_new_short_labels_share_canonical_identity(self) -> None:
        labels = {row["mapped_character"] for row in self.source if row["mapped_character"]}
        self.assertIn("博丽灵梦", labels)
        self.assertIn("雾雨魔理沙", labels)
        self.assertIn("爱丽丝·玛格特洛依德", labels)
        self.assertNotIn("灵梦", labels)
        self.assertNotIn("魔理沙", labels)


if __name__ == "__main__":
    unittest.main()
