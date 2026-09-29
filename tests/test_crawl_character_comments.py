from __future__ import annotations

import unittest

from scripts_pipeline.crawl_character_comments import (
    parse_cn_legacy_reasons,
    parse_jp_aggregate_comments,
    parse_jp_detail_comments,
)


class CharacterCommentParserTests(unittest.TestCase):
    def test_japanese_aggregate_sections_keep_primary_marker_and_author(self) -> None:
        payload = """
        <table><tr><td class="title_com">1位 博麗 霊夢 10ポイント コメント数:2</td>
        <td><div>* 好き（甲）<br>主人公</div></td></tr></table>
        <table><tr><td class="title_com">2位 霧雨 魔理沙 9ポイント コメント数:1</td>
        <td><div>魔法使い（乙）</div></td></tr></table>
        """.encode()

        entities = parse_jp_aggregate_comments(payload, round_no=4, url="fixture")

        self.assertEqual([entity["entity_name"] for entity in entities], ["博麗 霊夢", "霧雨 魔理沙"])
        self.assertEqual(entities[0]["rank"], 1)
        self.assertEqual(entities[0]["comments"][0]["text"], "好き")
        self.assertTrue(entities[0]["comments"][0]["is_primary"])
        self.assertEqual(entities[0]["comments"][0]["author"], "甲")
        self.assertEqual(entities[1]["comments"][0]["text"], "魔法使い")

    def test_japanese_detail_page_extracts_each_comment_paragraph(self) -> None:
        payload = """
        <article><h2>博麗 霊夢（2位）</h2>
        <h3>投票コメント</h3><div class="result_comment">
        <p>* 主人公（匿名）</p><p>\nかわいい\n</p>
        </div></article>
        """.encode()

        name, rank, comments = parse_jp_detail_comments(payload)

        self.assertEqual((name, rank), ("博麗 霊夢", 2))
        self.assertEqual([comment["text"] for comment in comments], ["主人公", "かわいい"])
        self.assertEqual(comments[0]["author"], "匿名")

    def test_chinese_early_reason_table_is_read_as_text(self) -> None:
        payload = """
        <p class="step1p">该页面是 <b>博丽灵梦</b> 的投票理由</p>
        <table id="stable2"><tr><td>主角</td></tr><tr><td>本命</td></tr></table>
        """.encode()

        name, comments = parse_cn_legacy_reasons(payload, 3)

        self.assertEqual(name, "博丽灵梦")
        self.assertEqual(comments, ["主角", "本命"])

    def test_chinese_later_reason_json_is_read_without_executing_script(self) -> None:
        payload = '''<h1>投票理由</h1><script>var data={"rows":[{"reason":"主角"},{"reason":"本命"}]};</script>'''.encode()

        name, comments = parse_cn_legacy_reasons(payload, 9)

        self.assertIsNone(name)
        self.assertEqual(comments, ["主角", "本命"])


if __name__ == "__main__":
    unittest.main()
