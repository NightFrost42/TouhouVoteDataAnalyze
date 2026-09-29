from __future__ import annotations

import csv
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scripts_pipeline.process_character_comments import process


class ProcessCharacterCommentsTests(unittest.TestCase):
    def test_process_preserves_text_and_marks_shape_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            entity_path = root / "entity.json"
            entity_path.write_text(json.dumps({
                "schema_version": 1, "region": "cn", "round": 1, "category": "character",
                "entity_id": "1", "entity_name": "测试", "rank": 1, "source_kind": "fixture",
                "source": {"url": "https://example.test", "sha256": "abc"},
                "comments": [{"text": "喜欢 https://example.test", "raw_text": "喜欢 https://example.test"},
                             {"text": "喜欢 https://example.test"}, {"text": ""}], "error": None,
            }, ensure_ascii=False), encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 1, "records": [{
                "region": "cn", "round": 1, "entity_id": "1", "entity_name": "测试", "status": "ok",
                "entity_path": entity_path.as_posix(), "source_kind": "fixture",
            }]}), encoding="utf-8")
            output, report = root / "processed", root / "report"
            summary = process(manifest, output, report)
            self.assertEqual(summary["comments_raw"], 3)
            self.assertEqual(summary["comments_nonempty"], 2)
            self.assertEqual(summary["exact_duplicates"], 1)
            self.assertEqual(summary["blank_comments"], 1)
            with gzip.open(output / "comments.csv.gz", "rt", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["text"], "喜欢 https://example.test")
            self.assertEqual(rows[0]["has_url"], "True")
            self.assertEqual(rows[1]["is_exact_duplicate"], "True")
            self.assertEqual(rows[2]["is_blank"], "True")
            self.assertTrue((report / "processing_summary.json").exists())


if __name__ == "__main__":
    unittest.main()
