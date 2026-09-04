from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts_pipeline import verify_cn_component_coverage as verify


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class LegacyComponentVerificationTests(unittest.TestCase):
    def test_rounds_one_to_four_certify_absence_only_without_markers(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            page = root / "data_raw/cn_official_legacy/round_01/raw/pages/root.html"
            page.parent.mkdir(parents=True)
            page.write_text("<html>static result</html>", encoding="utf-8")
            snapshot = verify.Snapshot(root)

            result = verify._probe_legacy_absence(snapshot, 1)
            self.assertEqual(result["status"], "official_not_offered")
            self.assertTrue(result["status_basis"].startswith("explicit_metadata"))

            page.write_text("object=votedate", encoding="utf-8")
            result = verify._probe_legacy_absence(snapshot, 1)
            self.assertEqual(result["status"], "pending")
            self.assertEqual(result["action"], "refetch_or_review_interface")

    def make_item_api_fixture(self, root: Path, *, bad: bool = False) -> list[dict]:
        item = root / "data_raw/cn_official_legacy/round_05/raw/api/items/chara/1"
        item.mkdir(parents=True)
        for endpoint in verify.ENDPOINTS:
            (item / f"{endpoint}.json").write_text(
                "{" if bad and endpoint == "votedate" else '{"ok": true}',
                encoding="utf-8",
            )
        return [
            {
                "round": 5,
                "category": "chara",
                "item_api_status": "available_crawled",
                "detail_pages_expected": 1,
            }
        ]

    def test_complete_legacy_item_apis_certify_trends(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = self.make_item_api_fixture(root)
            result = verify._probe_legacy_api(
                verify.Snapshot(root), 5, rows, {"errors": []}
            )
            self.assertEqual(result["status"], "available_crawled")
            self.assertEqual(result["observed_by_endpoint"], dict.fromkeys(verify.ENDPOINTS, 1))
            self.assertEqual(result["refetch_plan"], [])

    def test_missing_or_bad_legacy_json_stays_pending_with_refetch_plan(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = self.make_item_api_fixture(root, bad=True)
            missing = root / "data_raw/cn_official_legacy/round_05/raw/api/items/chara/1/votesex.json"
            missing.unlink()
            result = verify._probe_legacy_api(
                verify.Snapshot(root), 5, rows, {"errors": []}
            )
            self.assertEqual(result["status"], "pending")
            self.assertEqual(result["action"], "refetch")
            self.assertGreaterEqual(len(result["invalid_files"]), 1)
            self.assertTrue(
                any(item["endpoint"] == "votesex" for item in result["refetch_plan"])
            )

    def test_snapshot_change_never_certifies_complete(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = self.make_item_api_fixture(root)
            with mock.patch.object(
                verify.Snapshot,
                "read_raw_json",
                side_effect=verify.SnapshotChanged("changed"),
            ):
                with self.assertRaises(verify.SnapshotChanged):
                    verify._probe_legacy_api(
                        verify.Snapshot(root), 5, rows, {"errors": []}
                    )


class ModernComponentVerificationTests(unittest.TestCase):
    def make_fixture(self, root: Path, *, entity_marker_round: int | None = None) -> None:
        write_json(
            root / verify.MODERN_COVERAGE,
            {"rounds": [{"round": 10, "complete": True}, {"round": 11, "complete": True}]},
        )
        write_json(
            root / verify.MODERN_REPORT,
            {"rounds": [{"round": 10, "available": True}, {"round": 11, "available": True}]},
        )
        for round_no in (10, 11):
            asset = (
                root
                / f"data_raw/cn_official/round_{round_no}/static/assets/Questionnaire.js"
            )
            asset.parent.mkdir(parents=True, exist_ok=True)
            marker = " queryEntityQuestionnaire " if entity_marker_round == round_no else ""
            asset.write_text(f"queryQuestionnaire{marker}", encoding="utf-8")

    def test_modern_aggregate_interface_without_entity_snapshots_requests_refetch(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_fixture(root)
            rounds, plan = verify.verify_modern(verify.Snapshot(root))
            for round_no in (10, 11):
                item = rounds[str(round_no)]["entity_questionnaire_details"]
                self.assertEqual(item["status"], "pending")
                self.assertEqual(item["action"], "refetch")
            self.assertEqual(len(plan), 2)

    def test_valid_entity_questionnaire_snapshots_certify_component(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_fixture(root)
            rounds_payload = []
            for round_no in (10, 11):
                rel = f"data_raw/cn_official/round_{round_no}/entity_questionnaire/responses/character_any/source_0001.json"
                path = root / rel
                write_json(
                    path,
                    {
                        "provenance": {"status": 200, "operation": "EntityQuestionnaire"},
                        "context": {"query": 'chars: ["灵梦"]'},
                        "data": {
                            "queryGlobalStats": {"numVote": 1},
                            "queryQuestionnaire": {"entries": [{"questionId": "q11011", "totalAnswers": 1, "answersCat": []}]},
                            "queryCompletionRates": {"items": []},
                        },
                    },
                )
                rounds_payload.append(
                    {
                        "round": round_no,
                        "complete": True,
                        "expectedResponses": 1,
                        "availableCrawled": 1,
                        "fetchFailed": 0,
                        "responseRoot": f"data_raw/cn_official/round_{round_no}/entity_questionnaire/responses",
                        "records": [{"status": "available_crawled", "responsePath": rel, "query": 'chars: ["灵梦"]'}],
                    }
                )
            write_json(root / verify.MODERN_ENTITY_QUESTIONNAIRE, {"rounds": rounds_payload})
            rounds, plan = verify.verify_modern(verify.Snapshot(root))
            self.assertEqual(plan, [])
            for round_no in (10, 11):
                self.assertEqual(
                    rounds[str(round_no)]["entity_questionnaire_details"]["status"],
                    "available_crawled",
                )

    def test_modern_entity_operation_without_capture_requests_refetch(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_fixture(root, entity_marker_round=10)
            rounds, plan = verify.verify_modern(verify.Snapshot(root))
            item = rounds["10"]["entity_questionnaire_details"]
            self.assertEqual(item["status"], "pending")
            self.assertEqual(item["action"], "refetch")
            self.assertTrue(any(entry["round"] == 10 for entry in plan))


class QueueConfigurationTests(unittest.TestCase):
    def test_cn10_cn11_stages_are_scheduled_from_existing_checkpoints(self) -> None:
        workspace = Path(__file__).resolve().parents[1]
        config = json.loads(
            (workspace / "metadata/data_crawl_queue.json").read_text(encoding="utf-8")
        )
        stage_ids = [stage["id"] for stage in config["stages"]]
        for stage_id in (
            "cn_modern_advanced",
            "cn_modern_normalize",
            "cn_modern_validate",
            "cn_modern_entity_questionnaire",
            "cn_component_verification",
        ):
            self.assertIn(stage_id, stage_ids)
        self.assertLess(stage_ids.index("unified_coverage"), stage_ids.index("thwiki_arrangement_counts"))
        self.assertEqual(stage_ids[-1], "thwiki_arrangement_counts")
        self.assertIn("cn1-11", config["queue_name"])

        commands = {
            stage["id"]: " ".join(str(part) for part in stage.get("command", []))
            for stage in config["stages"]
        }
        self.assertIn("crawl_cn_modern_advanced.py", commands["cn_modern_advanced"])
        self.assertIn("--resume", commands["cn_modern_advanced"])
        self.assertIn("normalize_cn_official.py", commands["cn_modern_normalize"])
        self.assertIn("--validate-only", commands["cn_modern_validate"])
        self.assertIn(
            "crawl_cn_modern_entity_questionnaire.py",
            commands["cn_modern_entity_questionnaire"],
        )
        self.assertIn("verify_cn_component_coverage.py", commands["cn_component_verification"])

        entity_checks = {
            tuple(check["json_path"]): check["equals"]
            for check in next(
                stage
                for stage in config["stages"]
                if stage["id"] == "cn_modern_entity_questionnaire"
            )["success_checks"]
        }
        self.assertTrue(entity_checks[("allRequiredChecksPassed",)])
        verification_checks = {
            tuple(check["json_path"]): check["equals"]
            for check in next(
                stage
                for stage in config["stages"]
                if stage["id"] == "cn_component_verification"
            )["success_checks"]
        }
        self.assertTrue(verification_checks[("verification_complete",)])


if __name__ == "__main__":
    unittest.main()
