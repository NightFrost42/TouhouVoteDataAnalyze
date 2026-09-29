from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = ROOT / "scripts_pipeline"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import build_vote_explorer_analysis_data as analysis  # noqa: E402


class CharacterMusicLinkTests(unittest.TestCase):
    def test_character_name_normalization_handles_full_width_punctuation(self) -> None:
        self.assertEqual(
            analysis._character_key("因幡天为(因幡帝)"),
            analysis._character_key("因幡天为（因幡帝）"),
        )


    def test_local_music_short_aliases_resolve_to_canonical_character(self) -> None:
        jp_to_cn, _ = analysis.load_name_maps()
        rows = [
            {
                "name_cn": "",
                "name_jp": "道神 馴子",
                "canonical_name": "道神馴子",
            },
            {
                "name_cn": "博丽灵梦",
                "name_jp": "博麗 霊夢",
                "canonical_name": "博丽灵梦",
            },
            {
                "name_cn": "雾雨魔理沙",
                "name_jp": "霧雨 魔理沙",
                "canonical_name": "雾雨魔理沙",
            },
            {
                "name_cn": "莉莉霍瓦特（莉莉白）",
                "name_jp": "リリーホワイト",
                "canonical_name": "莉莉霍瓦特（莉莉白）",
            },
        ]

        self.assertEqual(
            analysis._find_character_row(rows, "灵梦", jp_to_cn, "jp")["canonical_name"],
            "博丽灵梦",
        )
        self.assertEqual(
            analysis._find_character_row(rows, "灵梦", jp_to_cn, "cn")["canonical_name"],
            "博丽灵梦",
        )
        self.assertEqual(
            analysis._find_character_row(rows, "魔理沙", jp_to_cn, "jp")["canonical_name"],
            "雾雨魔理沙",
        )
        self.assertEqual(
            analysis._find_character_row(rows, "莉莉白", jp_to_cn, "jp")["canonical_name"],
            "莉莉霍瓦特（莉莉白）",
        )


    def test_untranslated_label_never_falls_back_to_blank_chinese_name(self) -> None:
        rows = [
            {"name_cn": "", "name_jp": "道神 馴子", "canonical_name": "道神馴子"},
            {"name_cn": "博丽灵梦", "name_jp": "博麗 霊夢", "canonical_name": "博丽灵梦"},
        ]
        self.assertIsNone(analysis._find_character_row(rows, "未收录角色", {}, "jp"))


if __name__ == "__main__":
    unittest.main()
