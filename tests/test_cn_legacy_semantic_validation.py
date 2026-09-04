from __future__ import annotations

import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts_pipeline import crawl_cn_legacy as legacy


class LegacySemanticResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.crawler = object.__new__(legacy.Crawler)

    @staticmethod
    def job(*, expect: str, label: str, target: str = "fixture") -> legacy.FetchJob:
        return legacy.FetchJob(
            round_no=5,
            url="https://touhou.vote/v5/fixture",
            target=Path(target),
            expect=expect,
            label=label,
        )

    @staticmethod
    def pair_payload() -> dict[str, object]:
        return {
            "cross": False,
            "title1": "问题一",
            "title2": "问题二",
            "data": {
                "item1": ["甲", "乙"],
                "item2": ["丙"],
                "data": {"0": ["3", "4"]},
                "percent": {"0": [42.86, 57.14], "all": [50, 50]},
                "percentall": [[60, 40]],
                "quest1": {"value": ["甲", "乙"]},
                "quest2": {"value": ["丙"]},
            },
        }

    def validate_json(self, payload: object, label: str) -> tuple[bool, str]:
        return self.crawler._validate(
            self.job(expect="json", label=label),
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def test_condition_requires_embedded_rows_and_rejects_challenge(self) -> None:
        job = self.job(
            expect="html", label="advanced questionnaire condition q001 a001 target chara"
        )
        valid, _ = self.crawler._validate(
            job, b'<html><script>const table={"rows":[]};</script></html>', "text/html"
        )
        self.assertTrue(valid)

        missing, reason = self.crawler._validate(
            job, b"<html><body>temporary response</body></html>", "text/html"
        )
        self.assertFalse(missing)
        self.assertIn("rows", reason)

        challenged, reason = self.crawler._validate(
            job, b"<html><title>Just a moment</title></html>", "text/html"
        )
        self.assertFalse(challenged)
        self.assertIn("challenge", reason)

    def test_advice_requires_numeric_ids_and_nonempty_names(self) -> None:
        label = "advanced questionnaire advice q001"
        self.assertTrue(self.validate_json({"1": "男性"}, label)[0])
        for payload in ({}, {"error": "rate limited"}, {"1": ""}):
            with self.subTest(payload=payload):
                self.assertFalse(self.validate_json(payload, label)[0])

    def test_advanced_entry_pages_require_parseable_nonempty_catalogues(self) -> None:
        simple = self.job(expect="html", label="advanced entry chara simple")
        self.assertTrue(
            self.crawler._validate(
                simple,
                b'<html><script>const table={"rows":[{"id":1}]};</script></html>',
                "text/html",
            )[0]
        )
        paper = self.job(expect="html", label="advanced entry paper")
        self.assertTrue(
            self.crawler._validate(
                paper,
                (
                    '<html><script>var questlist = '
                    '[{"name":"Q","value":"token","group":1}];</script></html>'
                ).encode("utf-8"),
                "text/html",
            )[0]
        )

    def test_pair_requires_complete_numeric_matrix(self) -> None:
        label = "advanced questionnaire pair q001 q002"
        self.assertTrue(self.validate_json(self.pair_payload(), label)[0])
        self.assertTrue(self.validate_json({"cross": True}, label)[0])

        malformed = self.pair_payload()
        malformed["data"]["data"]["0"] = ["not-a-count", "4"]
        for payload in ({}, {"error": "busy"}, malformed):
            with self.subTest(payload=payload):
                self.assertFalse(self.validate_json(payload, label)[0])

    def test_identity_checkpoint_is_semantically_revalidated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "condition.html"
            body = b"<html><title>Verify you are human</title></html>"
            path.write_bytes(body)
            job = self.job(
                expect="html",
                label="advanced entity chara any source 0001 target music",
                target=str(path),
            )
            record = {
                "status": 200,
                "success": True,
                "error": "",
                "local_path": path.name,
                "bytes": len(body),
                "sha256": legacy.sha256_bytes(body),
                "storage_encoding": "identity",
                "response_bytes": len(body),
                "response_sha256": legacy.sha256_bytes(body),
                "content_type": "text/html",
            }
            self.crawler.refresh = False

            with mock.patch.object(legacy, "WORKSPACE", Path(directory)):
                self.assertFalse(self.crawler._existing_is_valid(job, record))


class LegacyStoredResponseValidationTests(unittest.TestCase):
    def make_crawler(self, record: dict[str, object]) -> legacy.Crawler:
        crawler = object.__new__(legacy.Crawler)
        crawler.records = {"fixture": record}
        crawler.workers = 1
        crawler.delay = 0.0
        crawler.downloaded = 0
        crawler.skipped = 0
        crawler.failed = 0
        return crawler

    def test_validate_accepts_gzip_json_and_checks_response_hash(self) -> None:
        payload = LegacySemanticResponseTests.pair_payload()
        response = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        stored = gzip.compress(response, mtime=0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "pair.json.gz"
            report = root / "validation.json"
            path.write_bytes(stored)
            record = {
                "round": 5,
                "url": "https://touhou.vote/v5/api.php",
                "method": "POST",
                "request_form": [["quest1", "a"], ["quest2", "b"]],
                "status": 200,
                "success": True,
                "error": "",
                "content_type": "application/json",
                "bytes": len(stored),
                "sha256": legacy.sha256_bytes(stored),
                "storage_encoding": "gzip",
                "response_bytes": len(response),
                "response_sha256": legacy.sha256_bytes(response),
                "local_path": path.name,
                "expect": "json",
                "label": "advanced questionnaire pair q001 q002",
            }
            crawler = self.make_crawler(record)
            with (
                mock.patch.object(legacy, "WORKSPACE", root),
                mock.patch.object(legacy, "VALIDATION_JSON", report),
                mock.patch.object(legacy.Crawler, "coverage_rows", return_value=[]),
            ):
                crawler.validate()

            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(result["manifest_integrity_ok"])
            self.assertEqual(result["valid_json_files"], 1)

            crawler.records["fixture"]["response_sha256"] = "0" * 64
            with (
                mock.patch.object(legacy, "WORKSPACE", root),
                mock.patch.object(legacy, "VALIDATION_JSON", report),
                mock.patch.object(legacy.Crawler, "coverage_rows", return_value=[]),
            ):
                crawler.validate()
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(result["manifest_integrity_ok"])
            self.assertIn(
                "response_sha256_mismatch",
                {error["type"] for error in result["errors"]},
            )


if __name__ == "__main__":
    unittest.main()
