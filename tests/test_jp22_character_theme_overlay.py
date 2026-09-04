from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
import unittest

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts_pipeline"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import build_music_canonical as canonical  # noqa: E402


class JP22CharacterThemeOverlayTests(unittest.TestCase):
    def test_wave_dash_subtitles_are_removed_from_canonical_display_titles(self) -> None:
        self.assertEqual(
            canonical.normalize_exact_title("最後の一人は慣れてるから　〜 Stone Goddess"),
            "最後の一人は慣れてるから",
        )
        self.assertEqual(
            canonical.normalize_exact_title("早已习惯最终孑然一身～ Stone Goddess"),
            "早已习惯最终孑然一身",
        )
        self.assertEqual(
            canonical.normalize_for_match("最後の一人は慣れてるから ~ Stone Goddess"),
            "最後の一人は慣れてるから",
        )

    def test_verified_rows_are_written_to_user_workbook(self) -> None:
        workbook = openpyxl.load_workbook(
            ROOT / "TouhouMusicInfo.xlsx", read_only=True, data_only=False
        )
        rows = {
            row[3]: row
            for row in workbook.active.iter_rows(min_row=2, values_only=True)
            if row[3]
        }
        expected = {
            "鹿狩りのレミニセンス": (100, "猎鹿旧忆回潮", 1004, 60, 151, "维缦·浅间"),
            "最後の一人は慣れてるから　〜 Stone Goddess": (
                42,
                "早已习惯最终孑然一身～ Stone Goddess",
                2637,
                256,
                389,
                "磐永阿梨夜",
            ),
            "二枚貝の上のハルシネーション": (97, "双壳贝上的幻觉", 1058, 75, 147, "渡里贝子"),
        }
        for title, values in expected.items():
            self.assertIn(title, rows)
            row = rows[title]
            self.assertEqual((row[0], row[4], row[5], row[6], row[7], row[8]), values)

    def test_overlay_has_only_verified_new_character_themes(self) -> None:
        by_title, by_music_id = canonical.load_jp22_theme_overlay()
        self.assertEqual(set(by_music_id), {"837", "841", "843"})
        self.assertEqual(len(by_title), 3)
        self.assertEqual(
            {
                (row["music_id"], row["character_id"], row["character_name_cn"])
                for row in by_music_id.values()
            },
            {
                ("837", "223", "维缦·浅间"),
                ("841", "224", "磐永阿梨夜"),
                ("843", "225", "渡里贝子"),
            },
        )
        self.assertNotIn("226", {row["character_id"] for row in by_music_id.values()})

    def test_generated_jp22_rows_keep_overlay_owner_and_provenance(self) -> None:
        source_path = ROOT / "data_processed" / "music_canonical" / "local_music_source_rows.csv"
        merged_path = ROOT / "data_processed" / "music_canonical" / "local_music_merged.csv"
        report_path = ROOT / "metadata" / "music_canonical_validation.json"
        with source_path.open(encoding="utf-8-sig", newline="") as handle:
            source_rows = list(csv.DictReader(handle))
        with merged_path.open(encoding="utf-8-sig", newline="") as handle:
            merged_rows = list(csv.DictReader(handle))
        report = json.loads(report_path.read_text(encoding="utf-8"))

        expected = {
            "837": ("鹿狩りのレミニセンス", "维缦·浅间"),
            "841": ("最後の一人は慣れてるから 〜 Stone Goddess", "磐永阿梨夜"),
            "843": ("二枚貝の上のハルシネーション", "渡里贝子"),
        }
        for music_id, (title, owner) in expected.items():
            source = [
                row
                for row in source_rows
                if row["round"] == "22" and row["source_record_id"] == music_id
            ]
            self.assertEqual(len(source), 1, music_id)
            self.assertEqual(source[0]["raw_title_jp"], title)
            self.assertEqual(source[0]["mapped_character"], owner)
            # Once the verified rows are written to the user's workbook, the
            # workbook mapping is authoritative; the overlay remains a
            # traceable fallback for a fresh checkout without those rows.
            self.assertEqual(source[0]["merge_basis"], "official_jp_user_repaired_exact")

            merged = [
                row
                for row in merged_rows
                if row["round"] == "22"
                and json.loads(row["source_ranks_json"])
                == [int(float(source[0]["source_rank"]))]
            ]
            self.assertEqual(len(merged), 1, music_id)
            self.assertEqual(json.loads(merged[0]["mapped_characters_json"]), [owner])

        self.assertEqual(report["round_coverage"]["jp"][-1], 22)
        self.assertEqual(report["jp22_character_theme_overlay"]["rows"], 3)
        self.assertEqual(report["jp22_character_theme_overlay"]["mapped_source_rows"], 0)
        self.assertEqual(report["jp22_character_theme_overlay"]["workbook_authoritative_rows"], 3)


if __name__ == "__main__":
    unittest.main()
