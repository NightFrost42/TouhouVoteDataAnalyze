from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts_pipeline.crawl_thwiki_arrangement_counts import (
    aggregate_jp_vote_windows,
    build_count_wikitext,
    build_content_items,
    load_checkpoint_originals,
    originals_fingerprint,
    parse_count_batch,
    parse_original_results,
    save_checkpoint,
)


class ThwikiArrangementCountTests(unittest.TestCase):
    def test_original_metadata_includes_release_date(self) -> None:
        payload = {
            "query": {
                "results": {
                    "蓬莱传说": {
                        "fullurl": "https://thwiki.cc/example",
                        "printouts": {
                            "原曲名称": ["蓬莱伝説"],
                            "原曲译名": ["蓬莱传说"],
                            "原曲首发作品": ["蓬莱人形"],
                            "原曲首发日期": [
                                {"timestamp": "1029024000", "raw": "1/2002/8/11"}
                            ],
                        },
                    }
                }
            }
        }
        row = parse_original_results(payload)[0]
        self.assertEqual(row["original_name_jp"], "蓬莱伝説")
        self.assertEqual(row["first_release_date"], "2002-08-11")
        self.assertEqual(row["first_release_date_raw"], "1/2002/8/11")

    def test_batch_query_requests_aggregates_not_track_details(self) -> None:
        text = build_count_wikitext([{"original_page": "蓬莱传说"}])
        self.assertIn("[[曲目原曲::蓬莱传说]]", text)
        self.assertIn("format=count", text)
        self.assertIn("?发售日期#-F[Y-m-d]", text)
        self.assertIn("charttitle=THWIKI_RELEASE_DAY_0", text)
        self.assertNotIn("?曲目名称", text)
        self.assertNotIn("?曲目专辑", text)

    def test_count_and_half_year_chart_are_parsed(self) -> None:
        config = {
            "numbers": [["2005-01-01", 3], ["2005-07-01", 4]],
            "total": 8,
            "parameters": {"charttitle": "THWIKI_RELEASE_DAY_0"},
        }
        encoded = json.dumps(json.dumps(config, ensure_ascii=False))
        payload = {
            "parse": {
                "text": {"*": "<p>THWIKI_TOTAL_0=8\nTHWIKI_VOCAL_0=2</p>"},
                "headhtml": {
                    "*": f'<script>mw.config.set({{"jqplot-line-1":{encoded}}});</script>'
                },
            }
        }
        row = parse_count_batch(payload, 1)[0]
        self.assertEqual(row["arrangement_count"], 8)
        self.assertEqual(row["vocal_count"], 2)
        self.assertEqual(row["arrange_count"], 6)
        self.assertEqual(row["dated_arrangement_count"], 7)
        self.assertEqual(row["undated_arrangement_count"], 1)
        self.assertEqual(
            row["periods"],
            [
                {"half_year": "2005H1", "arrangement_count": 3},
                {"half_year": "2005H2", "arrangement_count": 4},
            ],
        )

    def test_vote_windows_are_end_to_end_and_non_overlapping(self) -> None:
        release_days = [
            {"release_date": "2004-10-23", "arrangement_count": 2},
            {"release_date": "2004-10-24", "arrangement_count": 3},
            {"release_date": "2005-12-24", "arrangement_count": 4},
            {"release_date": "2026-08-29", "arrangement_count": 5},
        ]
        rows = aggregate_jp_vote_windows(release_days, 1)
        round3 = next(row for row in rows if row["jp_vote_round"] == 3)
        round4 = next(row for row in rows if row["jp_vote_round"] == 4)
        waiting = next(row for row in rows if row["vote_window_status"] == "waiting_next_vote")
        self.assertEqual(round3["arrangement_count"], 2)
        self.assertEqual(round3["arrangement_cumulative_count"], 2)
        self.assertEqual(round3["vote_window_status"], "before_first_vote_end")
        self.assertEqual(round4["arrangement_count"], 7)
        self.assertEqual(round4["arrangement_cumulative_count"], 9)
        self.assertFalse(round4["release_window_start_inclusive"])
        self.assertEqual(waiting["arrangement_count"], 5)

    def test_zero_count_can_have_no_chart(self) -> None:
        payload = {
            "parse": {
                "text": {"*": "THWIKI_TOTAL_0=0 THWIKI_VOCAL_0=0"},
                "headhtml": {"*": ""},
            }
        }
        row = parse_count_batch(payload, 1)[0]
        self.assertTrue(row["timeline_available"])
        self.assertEqual(row["periods"], [])

    def test_content_items_keep_stable_completed_current_pending_batches(self) -> None:
        originals = [{"original_page": f"原曲{i}"} for i in range(1, 6)]
        records = {"原曲1": {}, "原曲2": {}}

        items = build_content_items(
            originals,
            records,
            2,
            current_batch_index=2,
        )

        self.assertEqual(
            [item["status"] for item in items],
            ["completed", "completed", "current", "pending"],
        )
        self.assertTrue(items[2]["current"])
        self.assertFalse(items[1]["current"])

    def test_checkpoint_reuses_original_catalog(self) -> None:
        originals = [
            {
                "original_page": "蓬莱传说",
                "original_name_jp": "蓬莱伝説",
                "original_name_cn": "蓬莱传说",
                "first_release_work": "蓬莱人形",
                "first_release_date": "2002-08-11",
                "first_release_date_raw": "1/2002/8/11",
                "source_page_url": "https://thwiki.cc/蓬莱传说",
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            fingerprint = originals_fingerprint(originals)
            save_checkpoint(
                path,
                fingerprint,
                {},
                complete=False,
                originals=originals,
            )
            self.assertEqual(load_checkpoint_originals(path), originals)


if __name__ == "__main__":
    unittest.main()
