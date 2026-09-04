from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import urllib.parse
import unittest
from unittest import mock

from scripts_pipeline import crawl_cn_legacy as legacy


class LocalWorkbookSubstitutionTests(unittest.TestCase):
    def test_current_workbooks_are_structurally_valid(self) -> None:
        evidence = legacy.validate_local_workbooks()
        self.assertTrue(evidence["valid"])
        for source in evidence["sources"].values():
            self.assertEqual(source["valid_rounds"], list(range(1, 10)))

    def make_crawler(self, *, reuse: bool = True) -> legacy.Crawler:
        crawler = object.__new__(legacy.Crawler)
        crawler.reuse_local_workbooks = reuse
        crawler.refresh = False
        crawler.local_source_validation = legacy.validate_local_workbooks()
        crawler.local_substitution_records = {}
        crawler.local_substituted = 0
        crawler._write_local_source_manifest = lambda: None
        return crawler

    def job(self, url: str, *, target: Path | None = None) -> legacy.FetchJob:
        return legacy.FetchJob(
            round_no=1,
            url=url,
            target=target or Path("missing.html"),
            expect="html",
            label="result variant",
        )

    def test_only_round_one_redundant_views_are_substitutable(self) -> None:
        crawler = self.make_crawler()
        self.assertIsNotNone(
            crawler._local_substitution_info(
                self.job("https://touhou.vote/v1/index.php?mod=chara&step=2")
            )
        )
        self.assertIsNotNone(
            crawler._local_substitution_info(
                self.job("https://touhou.vote/v1/index.php?mod=music&step=4&w=2")
            )
        )
        # The canonical page is needed for ids; other views carry unique data.
        for url in (
            "https://touhou.vote/v1/index.php?mod=chara&step=1",
            "https://touhou.vote/v1/index.php?mod=chara&step=5",
            "https://touhou.vote/v1/index.php?mod=chara&step=4&w=3",
            "https://touhou.vote/v2/?m=1&s=2",
            "https://touhou.vote/v4/?m=chara&t=full",
            "https://touhou.vote/v5/?m=chara&type=contrast",
            "https://touhou.vote/v5/?m=info&type=chara&id=1",
        ):
            with self.subTest(url=url):
                self.assertIsNone(crawler._local_substitution_info(self.job(url)))

    def test_local_result_does_not_enter_http_manifest_or_call_network(self) -> None:
        crawler = self.make_crawler()
        crawler.workers = 1
        crawler.batch_size = 5
        crawler.batch_pause = 0.0
        crawler.delay = 0.0
        crawler.transient_failure_threshold = 2
        crawler.circuit_open = False
        crawler.circuit_reason = ""
        crawler.rebuild_only = False
        crawler.records = {}
        crawler.skipped = 0
        crawler.failed = 0
        crawler.downloaded = 0
        crawler._lock = threading.RLock()
        crawler._register_source = lambda job: self.fail("local substitute registered as HTTP")
        crawler._existing_is_valid = lambda job, record: False
        crawler._persist_adaptive_profile = lambda: None

        local_job = self.job(
            "https://touhou.vote/v1/index.php?mod=chara&step=2",
            target=(
                legacy.WORKSPACE
                / "data_raw/cn_official_legacy/round_01/raw/pages/chara/omitted.html"
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            run_state = Path(directory) / "run_state.json"
            with (
                mock.patch.object(legacy, "RUN_STATE_JSON", run_state),
                mock.patch.object(legacy, "write_json_atomic"),
                mock.patch.object(
                    crawler,
                    "fetch_one",
                    side_effect=AssertionError("network request should not be made"),
                ),
            ):
                result = crawler.fetch_many([local_job], "v1 result variants")

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].ok)
        self.assertTrue(result[0].local_substitute)
        self.assertEqual(crawler.local_substituted, 1)
        self.assertEqual(crawler.records, {})

    def test_invalid_evidence_disables_substitution(self) -> None:
        crawler = self.make_crawler()
        crawler.local_source_validation["valid"] = False
        self.assertIsNone(
            crawler._local_substitution_info(
                self.job("https://touhou.vote/v1/index.php?mod=chara&step=2")
            )
        )

    def _history_record(self, target: Path) -> dict[str, object]:
        return {
            "record_key": "history-key",
            "round": 1,
            "category": "chara",
            "url": "https://touhou.vote/v1/index.php?mod=chara&step=2",
            "target": str(target),
            "source_kind": "local_xlsx",
            "status": "available_local_substitute",
            "workbook_sha256": "hash-chara",
        }

    def _history_crawler(self, *, rebuild_only: bool) -> legacy.Crawler:
        crawler = object.__new__(legacy.Crawler)
        crawler.reuse_local_workbooks = True
        crawler.rebuild_only = rebuild_only
        crawler.local_source_validation = {
            "valid": True,
            "sources": {
                "chara": {
                    "valid": True,
                    "sha256": "hash-chara",
                    "sheets": {"1": {"valid": True}},
                }
            },
        }
        crawler.local_substitution_records = {}
        crawler.local_substitution_history = {}
        return crawler

    def test_history_does_not_affect_normal_run_but_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "local.json"
            target = root / "missing.html"
            manifest.write_text(
                json.dumps({"substitutions": [self._history_record(target)]}),
                encoding="utf-8",
            )
            crawler = self._history_crawler(rebuild_only=False)
            with mock.patch.object(legacy, "LOCAL_SOURCE_MANIFEST_PATH", manifest):
                crawler._load_local_source_manifest()
                self.assertEqual(len(crawler.local_substitution_history), 1)
                self.assertEqual(crawler.local_substitution_records, {})
                crawler._write_local_source_manifest()
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["substitutions"]), 1)
            self.assertEqual(payload["active_substitutions"], [])

    def test_rebuild_only_reuses_missing_historical_omission(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "local.json"
            target = root / "missing.html"
            manifest.write_text(
                json.dumps({"substitutions": [self._history_record(target)]}),
                encoding="utf-8",
            )
            crawler = self._history_crawler(rebuild_only=True)
            with mock.patch.object(legacy, "LOCAL_SOURCE_MANIFEST_PATH", manifest):
                crawler._load_local_source_manifest()
            self.assertEqual(len(crawler.local_substitution_records), 1)

    def test_existing_official_target_supersedes_history_on_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "already-fetched.html"
            target.write_text("official", encoding="utf-8")
            manifest = root / "local.json"
            manifest.write_text(
                json.dumps({"substitutions": [self._history_record(target)]}),
                encoding="utf-8",
            )
            crawler = self._history_crawler(rebuild_only=True)
            with mock.patch.object(legacy, "LOCAL_SOURCE_MANIFEST_PATH", manifest):
                crawler._load_local_source_manifest()
            self.assertEqual(crawler.local_substitution_records, {})

    def make_coverage_crawler(self, root: Path) -> legacy.Crawler:
        """Create the smallest crawler state needed by ``coverage_rows``."""

        crawler = object.__new__(legacy.Crawler)
        crawler.states = {
            round_no: legacy.RoundState(round_no)
            for round_no in range(1, 10)
        }
        crawler.records = {}
        crawler.local_substitution_records = {}
        crawler.local_source_validation = {"valid": True, "sources": {}}
        crawler._lock = threading.RLock()
        return crawler

    def test_missing_step_one_cannot_be_called_complete_by_local_workbook(self) -> None:
        """A workbook supplies values, never the canonical ID-discovery page."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            crawler = self.make_coverage_crawler(root)
            crawler.local_substitution_records = {
                "v1-chara-step2": {
                    "record_key": "v1-chara-step2",
                    "round": 1,
                    "category": "chara",
                    "url": "https://touhou.vote/v1/index.php?mod=chara&step=2",
                    "status": "available_local_substitute",
                    "workbook": "TouhouVote_cn.xlsx",
                }
            }
            with mock.patch.object(legacy, "DATA_ROOT", root):
                rows = crawler.coverage_rows()

        row = next(
            item for item in rows
            if item["round"] == 1 and item["category"] == "chara"
        )
        self.assertEqual(row["local_source_status"], "available_local_substitute")
        self.assertEqual(row["summary_pages_omitted_by_policy"], 1)
        self.assertEqual(row["summary_status"], "fetch_failed")
        self.assertEqual(row["overall_status"], "fetch_failed")

    def test_missing_detail_and_item_api_stay_fetch_failed(self) -> None:
        """A complete-looking ranking page does not waive detail/API coverage."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            simple = (
                root / "round_05" / "raw" / "pages" / "chara"
                / "m_chara__type_simple.html"
            )
            simple.parent.mkdir(parents=True)
            simple.write_text("<html><body>ranking</body></html>", encoding="utf-8")
            crawler = self.make_coverage_crawler(root)
            state = crawler.states[5]
            state.add_summary("chara", simple)
            state.add_detail(
                "chara",
                "1",
                root / "round_05" / "raw" / "details" / "chara" / "1.html",
            )
            with mock.patch.object(legacy, "DATA_ROOT", root):
                rows = crawler.coverage_rows()

        row = next(
            item for item in rows
            if item["round"] == 5 and item["category"] == "chara"
        )
        self.assertEqual(row["summary_status"], "available_crawled")
        self.assertEqual(row["detail_status"], "fetch_failed")
        self.assertEqual(row["item_api_status"], "fetch_failed")
        self.assertEqual(row["overall_status"], "fetch_failed")

    def test_local_substitution_is_written_only_to_separate_evidence(self) -> None:
        """The official HTTP manifest must remain free of workbook rows."""

        crawler = self.make_crawler()
        crawler.records = {}
        crawler._write_local_source_manifest = legacy.Crawler._write_local_source_manifest.__get__(crawler)
        info = crawler._local_substitution_info(
            self.job("https://touhou.vote/v1/index.php?mod=chara&step=2")
        )
        self.assertIsNotNone(info)
        with tempfile.TemporaryDirectory() as directory:
            local_manifest = Path(directory) / "local-source.json"
            http_manifest = Path(directory) / "http-manifest.jsonl"
            with (
                mock.patch.object(legacy, "LOCAL_SOURCE_MANIFEST_PATH", local_manifest),
                mock.patch.object(legacy, "MANIFEST_PATH", http_manifest),
            ):
                crawler._record_local_substitution(self.job(
                    "https://touhou.vote/v1/index.php?mod=chara&step=2"
                ), info or {})
                self.assertTrue(local_manifest.exists())
                self.assertFalse(http_manifest.exists())
                payload = json.loads(local_manifest.read_text(encoding="utf-8"))

        self.assertEqual(len(payload["substitutions"]), 1)
        self.assertEqual(payload["substitutions"][0]["source_kind"], "local_xlsx")

    def test_round_one_integration_keeps_step_one_detail_discovery(self) -> None:
        """Omitting local variants must not remove the detail-ID frontier."""

        with tempfile.TemporaryDirectory(dir=legacy.WORKSPACE) as directory:
            root = Path(directory)
            data_root = root / "data_raw" / "cn_official_legacy"
            metadata_root = root / "metadata"
            metadata_root.mkdir(parents=True)
            patched_paths = {
                "DATA_ROOT": data_root,
                "METADATA_ROOT": metadata_root,
                "MANIFEST_PATH": metadata_root / "manifest.jsonl",
                "JOURNAL_PATH": metadata_root / "journal.jsonl",
                "LOCAL_SOURCE_MANIFEST_PATH": metadata_root / "local.json",
                "RUN_STATE_JSON": metadata_root / "run-state.json",
                "ADAPTIVE_PROFILE_JSON": metadata_root / "profiles.json",
            }

            def fake_fetch_one(job: legacy.FetchJob) -> legacy.FetchResult:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(job.url).query)
                category = query.get("mod", [""])[0]
                step = query.get("step", [""])[0]
                if category in {"chara", "music"} and not step:
                    links = "".join(
                        f'<a href="./index.php?mod={category}&step={item}">x</a>'
                        for item in ("1", "2", "3", "4", "5")
                    )
                    body = f"<html><body>{links}</body></html>"
                elif category == "work" and not step:
                    links = "".join(
                        f'<a href="./index.php?mod=work&step={item}">x</a>'
                        for item in ("1", "2", "3")
                    )
                    body = f"<html><body>{links}</body></html>"
                elif category == "chara" and step == "1":
                    body = (
                        "<html>"
                        "index.php?mod=json&type=chara&id=1"
                        "</html>"
                    )
                elif category == "music" and step == "1":
                    body = (
                        "<html>"
                        "index.php?mod=json&type=music&id=2"
                        "</html>"
                    )
                elif "mod=json" in job.url:
                    body = "<html><body><table><tr><td>detail</td></tr></table></body></html>"
                else:
                    body = "<html><body>result</body></html>"
                encoded = body.encode("utf-8")
                job.target.parent.mkdir(parents=True, exist_ok=True)
                job.target.write_bytes(encoded)
                return legacy.FetchResult(
                    job=job,
                    ok=True,
                    status=200,
                    bytes_count=len(encoded),
                )

            with mock.patch.multiple(legacy, **patched_paths):
                crawler = legacy.Crawler(
                    rounds=[1],
                    workers=1,
                    refresh=False,
                    no_item_apis=False,
                    max_items=None,
                    retries=1,
                    timeout=1,
                    delay=0.0,
                    batch_size=20,
                    batch_pause=0.0,
                    transient_failure_threshold=3,
                    import_existing_temp=False,
                    supplemental_only=False,
                    advanced_only=False,
                    advanced_stage="all",
                    rebuild_only=False,
                    reuse_local_workbooks=True,
                    adaptive_tuning=False,
                )
                with mock.patch.object(crawler, "fetch_one", side_effect=fake_fetch_one):
                    crawler.crawl_round_1(1)

            state = crawler.states[1]
            local_records = list(crawler.local_substitution_records.values())
            self.assertEqual(len(local_records), 6)
            self.assertEqual(
                {(item["category"], item["variant"]) for item in local_records},
                {
                    ("chara", "step=2"),
                    ("chara", "step=3"),
                    ("chara", "step=4&w=2"),
                    ("music", "step=2"),
                    ("music", "step=3"),
                    ("music", "step=4&w=2"),
                },
            )
            self.assertEqual(state.detail_ids["chara"], {"1"})
            self.assertEqual(state.detail_ids["music"], {"2"})
            self.assertTrue(
                (data_root / "round_01" / "raw" / "details" / "chara" / "1.html").exists()
            )
            self.assertTrue(
                (data_root / "round_01" / "raw" / "details" / "music" / "2.html").exists()
            )
            self.assertFalse(
                any("step_2" in path.name for path in state.summary_files["chara"])
            )
            self.assertFalse(
                any("step_3" in path.name for path in state.summary_files["music"])
            )


if __name__ == "__main__":
    unittest.main()
