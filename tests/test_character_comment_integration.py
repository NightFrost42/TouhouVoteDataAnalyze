import sys
import csv
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts_pipeline"))
from scripts_pipeline.build_vote_explorer_analysis_data import attach_character_comment_metrics
from scripts_pipeline import build_vote_explorer_analysis_data as builder


class CharacterCommentIntegrationTests(unittest.TestCase):
    def test_duplicate_source_names_stay_ambiguous_but_exact_id_is_usable(self):
        sources = [
            {"region": "cn", "round": "3", "entity_id": "152", "entity_name": "阴阳玉", "status": "ok", "comments_nonempty": "5"},
            {"region": "cn", "round": "3", "entity_id": "159", "entity_name": "阴阳玉", "status": "ok", "comments_nonempty": "0"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'data_processed/character_comments/entity_summary.csv'
            path.parent.mkdir(parents=True)
            with path.open('w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(sources[0]))
                writer.writeheader()
                writer.writerows(sources)
            with patch.object(builder, 'ROOT', root):
                indexes = builder.load_character_comment_summaries({}, {})
        rows = [{"region": "cn", "round": 3, "entity_id": entity_id, "name_cn": "阴阳玉"} for entity_id in ('', '', '159')]
        attach_character_comment_metrics(rows, *indexes)
        self.assertEqual([r['comment_data_status'] for r in rows], ['ambiguous', 'ambiguous', 'ok'])
        self.assertEqual([r['comments_nonempty'] for r in rows], ['', '', 0])

    def test_one_source_cannot_attach_to_two_ranking_rows(self):
        source = {'status': 'ok', 'comments_nonempty': '5'}
        rows = [{'region': 'cn', 'round': 3, 'name_cn': '同名'} for _ in range(2)]
        attach_character_comment_metrics(rows, {}, {('cn', 3, '同名'): source})
        self.assertEqual([r['comment_data_status'] for r in rows], ['ambiguous', 'ambiguous'])
        self.assertTrue(all(r['comments_nonempty'] == '' for r in rows))

    def test_conflicting_aliases_and_failed_sources_do_not_supply_numbers(self):
        rows = [{'region': 'jp', 'round': 3, 'name_cn': '甲', 'name_jp': '乙'},
                {'region': 'jp', 'round': 3, 'name_cn': '丙'}]
        names = {('jp', 3, '甲'): {'status': 'ok'}, ('jp', 3, '乙'): {'status': 'ok'},
                 ('jp', 3, '丙'): {'status': 'error', 'comments_nonempty': '0'}}
        attach_character_comment_metrics(rows, {}, names)
        self.assertEqual([r['comment_data_status'] for r in rows], ['ambiguous', 'source_error'])
        self.assertTrue(all(r['comments_nonempty'] == '' for r in rows))

    def test_role_mean_explicitly_weights_entities_equally(self):
        rows = [dict(region='cn', round=1, comment_data_status='ok', comments_nonempty=100, comment_avg_chars=10),
                dict(region='cn', round=1, comment_data_status='ok', comments_nonempty=1, comment_avg_chars=30)]
        with tempfile.TemporaryDirectory() as tmp, patch.object(builder, 'ROOT', Path(tmp)):
            audit = builder.write_character_comment_role_audit(rows)
        self.assertEqual(audit['schema_version'], 2)
        self.assertEqual(audit['rounds'][0]['mean_entity_comment_chars'], 20)
        self.assertNotIn('mean_comment_chars', audit['rounds'][0])

    def test_audit_status_is_read_from_report_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(builder, 'ROOT', Path(tmp)):
            path = Path(tmp) / 'analysis_results/covote_metrics_audit.json'
            path.parent.mkdir()
            self.assertEqual(builder.covote_audit_manifest()['status'], 'UNAVAILABLE')
            for report, expected in [({'status': 'PASS', 'hard_failures': []}, 'PASS'),
                                     ({'status': 'FAIL'}, 'FAIL'),
                                     ({'status': 'PASS', 'hard_failures': ['bad cells']}, 'FAIL'),
                                     ({}, 'INVALID'), ([], 'INVALID'), ({'status': []}, 'INVALID')]:
                with self.subTest(report=report):
                    path.write_text(json.dumps(report), encoding='utf-8')
                    self.assertEqual(builder.covote_audit_manifest()['status'], expected)
            path.write_text('{broken', encoding='utf-8')
            self.assertEqual(builder.covote_audit_manifest()['status'], 'INVALID')

    def test_jp_name_alias_join_does_not_depend_on_source_id(self):
        rows = [{
            "region": "jp", "round": 17, "entity_id": "19",
            "name_cn": "魂魄妖梦", "name_jp": "魂魄 妖夢", "canonical_name": "魂魄妖梦",
            "selection_count": 100,
        }]
        by_id = {("jp", 17, "1"): {"status": "ok", "comments_raw": "12", "comments_nonempty": "10", "comments_unique": "8", "exact_duplicates": "2", "avg_char_count": "9.5", "median_char_count": "8"}}
        by_name = {("jp", 17, "魂魄妖夢"): {"status": "ok", "comments_raw": "12", "comments_nonempty": "10", "comments_unique": "8", "exact_duplicates": "2", "avg_char_count": "9.5", "median_char_count": "8"}}

        attach_character_comment_metrics(rows, by_id, by_name)

        self.assertEqual(rows[0]["comment_data_status"], "ok")
        self.assertEqual(rows[0]["comments_nonempty"], 10)
        self.assertEqual(rows[0]["comment_exact_duplicates"], 2)
        self.assertAlmostEqual(rows[0]["comment_to_selection_ratio"], 0.1)

    def test_unmatched_entity_stays_explicitly_blank(self):
        rows = [{
            "region": "jp", "round": 11, "entity_id": "missing",
            "name_cn": "未收录角色", "name_jp": "未収録", "canonical_name": "未收录角色",
            "selection_count": 10,
        }]

        attach_character_comment_metrics(rows, {}, {})

        self.assertEqual(rows[0]["comment_data_status"], "unmatched")
        self.assertEqual(rows[0]["comments_nonempty"], "")
        self.assertEqual(rows[0]["comment_to_selection_ratio"], "")


if __name__ == "__main__":
    unittest.main()
