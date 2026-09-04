from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts_pipeline import data_crawl_control as control
from scripts_pipeline import stop_data_crawl_queue as stop_helper


def sample_config() -> dict:
    def stage(stage_id: str, workers: int, delay: float) -> dict:
        return {
            "id": stage_id,
            "description": stage_id,
            "command": [
                "{python}",
                "crawler.py",
                "--workers",
                str(workers),
                "--delay",
                str(delay),
                "--batch-size",
                "20",
                "--batch-pause",
                "5",
                "--retries",
                "5",
                "--timeout",
                "180",
                "--transient-failure-threshold",
                "3",
                "--resume",
            ],
            "success_checks": [],
        }

    return {
        "schema_version": 1,
        "queue_name": "test",
        "notifications": {"failed_attempt_threshold": 5},
        "stages": [
            stage("cn_legacy_advanced", 2, 1.0),
            stage("cn_legacy_remaining", 3, 0.5),
            {"id": "untouched", "command": ["do", "not", "change"]},
        ],
    }


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config_path = self.root / "metadata" / "data_crawl_queue.json"
        self.lock_path = self.root / "metadata" / ".control.lock"
        self.config_path.parent.mkdir(parents=True)
        self.config_path.write_text(
            json.dumps(sample_config(), ensure_ascii=False), encoding="utf-8"
        )
        self.patches = [
            mock.patch.object(control, "CONFIG_PATH", self.config_path),
            mock.patch.object(control, "CONTROL_LOCK_PATH", self.lock_path),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temporary.cleanup()

    def test_save_round_trip_is_persistent_and_preserves_other_arguments(self) -> None:
        settings = control.read_settings()
        settings["stages"]["cn_legacy_advanced"].update(
            {
                "workers": 6,
                "delay": 0.25,
                "batchSize": 144,
                "batchPause": 12.5,
                "retries": 8,
                "timeout": 240,
                "transientFailureThreshold": 7,
            }
        )
        settings["failurePolicy"]["maxConsecutiveStageFailures"] = 9

        saved = control.save_settings(settings)

        self.assertEqual(saved, control.read_settings())
        persisted = json.loads(self.config_path.read_text(encoding="utf-8"))
        advanced = next(
            stage
            for stage in persisted["stages"]
            if stage["id"] == "cn_legacy_advanced"
        )
        self.assertIn("--resume", advanced["command"])
        self.assertEqual(
            next(stage for stage in persisted["stages"] if stage["id"] == "untouched"),
            {"id": "untouched", "command": ["do", "not", "change"]},
        )
        self.assertEqual(
            persisted["failure_policy"],
            {"max_consecutive_stage_failures": 9, "stop_when_reached": True},
        )

    def test_read_settings_accepts_request_limit_commands_without_legacy_delay(self) -> None:
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        for stage in config["stages"][:2]:
            command = stage["command"]
            delay_index = command.index("--delay")
            del command[delay_index : delay_index + 2]
            batch_index = command.index("--batch-size")
            command[batch_index] = "--request-limit"
        self.config_path.write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
        )

        settings = control.read_settings()

        self.assertEqual(settings["stages"]["cn_legacy_advanced"]["delay"], 0.0)
        self.assertEqual(settings["stages"]["cn_legacy_remaining"]["requestLimit"], 20)

    def test_stage_metadata_guardrails_override_transitional_command_flags(self) -> None:
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        for stage in config["stages"][:2]:
            stage.update(
                {
                    "worker_ceiling": 7,
                    "request_limit_ceiling": 23,
                    "batch_pause_ceiling": 2.5,
                }
            )
            stage["command"].extend(
                [
                    "--worker-ceiling", "10",
                    "--request-limit-ceiling", "30",
                    "--batch-pause-ceiling", "3",
                ]
            )
            pause_index = stage["command"].index("--batch-pause")
            stage["command"][pause_index + 1] = "2"
        self.config_path.write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
        )

        settings = control.read_settings()

        for stage_id in ("cn_legacy_advanced", "cn_legacy_remaining"):
            self.assertEqual(settings["stages"][stage_id]["workerCeiling"], 7)
            self.assertEqual(settings["stages"][stage_id]["requestLimitCeiling"], 23)
            self.assertEqual(settings["stages"][stage_id]["batchPauseCeiling"], 2.5)

    def test_unknown_or_out_of_range_fields_are_rejected_without_writing(self) -> None:
        before = self.config_path.read_bytes()
        value = control.read_settings()
        value["stages"]["cn_legacy_advanced"]["workers"] = 999
        value["stages"]["cn_legacy_advanced"]["surprise"] = 1
        value["unexpected"] = True

        with self.assertRaises(control.SettingsValidationError) as caught:
            control.save_settings(value)

        self.assertIn("cn_legacy_advanced.workers", caught.exception.errors)
        self.assertIn("cn_legacy_advanced.surprise", caught.exception.errors)
        self.assertIn("unexpected", caught.exception.errors)
        self.assertEqual(before, self.config_path.read_bytes())

    def test_transient_failure_threshold_cannot_exceed_batch_size(self) -> None:
        before = self.config_path.read_bytes()
        value = control.read_settings()
        value["stages"]["cn_legacy_remaining"]["batchSize"] = 4
        value["stages"]["cn_legacy_remaining"][
            "transientFailureThreshold"
        ] = 5

        with self.assertRaises(control.SettingsValidationError) as caught:
            control.save_settings(value)

        self.assertIn(
            "cn_legacy_remaining.transientFailureThreshold",
            caught.exception.errors,
        )
        self.assertEqual(before, self.config_path.read_bytes())


class ProgressOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.legacy_state = self.root / "legacy.json"
        self.modern_state = self.root / "modern.json"
        self.entity_state = self.root / "entity.json"
        self.entity_coverage = self.root / "entity-coverage.json"
        self.thwiki_state = self.root / "thwiki.json"
        self.patches = [
            mock.patch.object(control, "WORKSPACE", self.root),
            mock.patch.object(control, "LEGACY_RUN_STATE", self.legacy_state),
            mock.patch.object(control, "MODERN_RUN_STATE", self.modern_state),
            mock.patch.object(
                control,
                "MODERN_ENTITY_QUESTIONNAIRE_RUN_STATE",
                self.entity_state,
            ),
            mock.patch.object(
                control,
                "MODERN_ENTITY_QUESTIONNAIRE_COVERAGE",
                self.entity_coverage,
            ),
            mock.patch.object(
                control,
                "THWIKI_ARRANGEMENT_COUNTS_RUN_STATE",
                self.thwiki_state,
            ),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temporary.cleanup()

    def write(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def legacy_payload(self, **updates: object) -> dict[str, object]:
        return {
            "updated_at": "2026-08-19T01:00:00+00:00",
            "phase": "v5 advanced questionnaire unordered pairs",
            "phase_completed_this_run": 100,
            "phase_total": 100,
            "phase_remaining": 0,
            **updates,
        }

    def test_safe_restart_rejects_previous_attempt_progress(self) -> None:
        self.write(self.legacy_state, self.legacy_payload())

        progress = control._progress_for_stage(
            "cn_legacy_advanced",
            stage_started_at="2026-08-19T01:00:00+00:00",
            child_pid=222,
        )

        self.assertEqual(progress["status"], "initializing")
        self.assertEqual(progress["ownership"], "previous_attempt")
        self.assertIsNone(progress["completed"])
        self.assertFalse(progress["phaseComplete"])

    def test_current_pid_accepts_same_second_progress_and_describes_work(self) -> None:
        self.write(
            self.legacy_state,
            self.legacy_payload(
                pid=222,
                queue_stage_id="cn_legacy_advanced",
            ),
        )

        progress = control._progress_for_stage(
            "cn_legacy_advanced",
            stage_started_at="2026-08-19T01:00:00+00:00",
            child_pid=222,
        )

        self.assertEqual(progress["status"], "phase_complete")
        self.assertEqual(progress["ownership"], "pid_match")
        self.assertEqual(progress["round"], 5)
        self.assertEqual(
            progress["activityLabel"], "国区第5届 · 问卷答案两两关联表"
        )

    def test_content_summary_parser_reads_round_phase_resource_rows(self) -> None:
        parsed = control._parse_content_summary_lines(
            """
[v5 advanced-search entry resources] 5 resources; cached=5, network=0, workers=5
[v5 advanced questionnaire-conditioned rankings] 628 resources; cached=12, network=616, workers=5
[v5 advanced questionnaire-conditioned rankings] 628 resources; cached=20, network=608, workers=4
[v6 aggregate questionnaire APIs] 8 resources; cached=8, network=0, workers=3
ordinary progress line
"""
        )
        self.assertEqual(
            [(row["round"], row["phase"]) for row in parsed],
            [
                (5, "advanced-search entry resources"),
                (5, "advanced questionnaire-conditioned rankings"),
                (6, "aggregate questionnaire APIs"),
            ],
        )
        self.assertEqual(parsed[1]["cached"], 20)
        self.assertEqual(parsed[1]["network"], 608)
        self.assertEqual(parsed[1]["workers"], 4)
        self.assertEqual(parsed[0]["label"], "国区第5届 · 高级搜索入口")

    def test_different_child_pid_never_reuses_old_progress(self) -> None:
        self.write(self.legacy_state, self.legacy_payload(pid=111))

        progress = control._progress_for_stage(
            "cn_legacy_remaining",
            stage_started_at="2026-08-19T00:00:00+00:00",
            child_pid=222,
        )

        self.assertEqual(progress["status"], "initializing")
        self.assertEqual(progress["ownership"], "previous_process")

    def test_modern_zero_progress_is_preserved_and_stage_is_the_phase(self) -> None:
        self.write(
            self.modern_state,
            {
                "pid": 333,
                "updatedAt": "2026-08-19T01:00:01+00:00",
                "state": "running",
                "stage": "advanced_conditions_start",
                "round": 10,
                "completed": 0,
                "total": 100,
                "adaptivePauseProbeBlockedSeconds": 245.5,
            },
        )

        progress = control._progress_for_stage(
            "cn_modern_advanced",
            stage_started_at="2026-08-19T01:00:00+00:00",
            child_pid=333,
        )

        self.assertEqual(progress["completed"], 0)
        self.assertEqual(progress["phase"], "advanced_conditions_start")
        self.assertEqual(progress["percent"], 0.0)
        self.assertEqual(progress["adaptivePauseProbeBlockedSeconds"], 245.5)

    def test_entity_questionnaire_progress_has_item_count_details_and_content(self) -> None:
        self.write(
            self.entity_state,
            {
                "pid": 444,
                "queue_stage_id": "cn_modern_entity_questionnaire",
                "updatedAt": "2026-08-19T01:00:01+00:00",
                "state": "running",
                "stage": "entity_questionnaire",
                "round": 10,
                "completed": 1,
                "total": 2,
                "remaining": 1,
                "recordedFailures": 0,
                "currentDimension": "character_any",
                "currentSourceIndex": 2,
                "currentSourceName": "魔理沙",
                "currentQuery": 'chars: ["魔理沙"]',
                "transientCircuitOpen": True,
                "stoppedReason": "HTTP 521 wave",
                "resumable": True,
            },
        )
        self.write(
            self.entity_coverage,
            {
                "rounds": [
                    {
                        "round": 10,
                        "records": [
                            {
                                "sourceCategory": "character",
                                "conditionKind": "any",
                                "sourceIndex": 1,
                                "sourceName": "灵梦",
                                "query": 'chars: ["灵梦"]',
                                "status": "available_crawled",
                            },
                            {
                                "sourceCategory": "character",
                                "conditionKind": "any",
                                "sourceIndex": 2,
                                "sourceName": "魔理沙",
                                "query": 'chars: ["魔理沙"]',
                                "status": "pending",
                            },
                        ],
                    }
                ]
            },
        )

        progress = control._progress_for_stage(
            "cn_modern_entity_questionnaire",
            stage_started_at="2026-08-19T01:00:00+00:00",
            child_pid=444,
        )

        self.assertEqual(progress["status"], "active")
        self.assertEqual((progress["completed"], progress["total"], progress["remaining"]), (1, 2, 1))
        self.assertEqual(progress["currentSourceName"], "魔理沙")
        self.assertEqual(progress["currentQuery"], 'chars: ["魔理沙"]')
        self.assertTrue(progress["transientCircuitOpen"])
        self.assertEqual(progress["stoppedReason"], "HTTP 521 wave")
        self.assertEqual([item["status"] for item in progress["contentItems"]], ["completed", "pending"])
        self.assertTrue(progress["contentItems"][1]["current"])

    def test_entity_questionnaire_old_pid_is_not_reused(self) -> None:
        self.write(
            self.entity_state,
            {
                "pid": 111,
                "queue_stage_id": "cn_modern_entity_questionnaire",
                "updatedAt": "2026-08-19T01:00:02+00:00",
                "stage": "entity_questionnaire",
                "completed": 1,
                "total": 2,
            },
        )
        progress = control._progress_for_stage(
            "cn_modern_entity_questionnaire",
            stage_started_at="2026-08-19T01:00:00+00:00",
            child_pid=222,
        )
        self.assertEqual(progress["status"], "initializing")
        self.assertEqual(progress["ownership"], "previous_process")

    def test_entity_questionnaire_coverage_recovers_count_when_status_file_is_missing(self) -> None:
        base_path = (
            self.root
            / "data_raw"
            / "cn_official"
            / "round_10"
            / "graphql"
            / "base.json"
        )
        base_path.parent.mkdir(parents=True)
        self.write(
            base_path,
            {
                "data": {
                    "queryCharacterRanking": {"entries": []},
                    "queryMusicRanking": {
                        "entries": [
                            {"name": "幽雅地绽放吧，墨染的樱花"},
                            {"name": "上海红茶馆"},
                            {"name": "亡灵的夜樱"},
                        ]
                    },
                }
            },
        )
        self.write(
            self.entity_coverage,
            {
                "generatedAt": "2026-08-19T01:00:02+00:00",
                "rounds": [
                    {
                        "round": 10,
                        "expectedResponses": 3,
                        "availableCrawled": 1,
                        "fetchFailed": 1,
                        "pending": 1,
                        "records": [
                            {
                                "sourceCategory": "music",
                                "conditionKind": "any",
                                "sourceIndex": 1,
                                "sourceName": "幽雅地绽放吧，墨染的樱花",
                                "query": 'musics: ["幽雅地绽放吧，墨染的樱花"]',
                                "status": "available_crawled",
                            }
                        ],
                    }
                ],
            },
        )
        progress = control._progress_for_stage(
            "cn_modern_entity_questionnaire",
            stage_started_at="2026-08-19T01:00:00+00:00",
            child_pid=222,
        )
        self.assertEqual((progress["completed"], progress["total"], progress["remaining"]), (1, 3, 2))
        self.assertEqual(progress["processed"], 2)
        self.assertEqual(progress["currentSourceName"], "上海红茶馆")
        self.assertEqual(len(progress["contentItems"]), 3)

    def test_offline_rebuild_does_not_reuse_network_crawl_progress(self) -> None:
        self.write(self.legacy_state, self.legacy_payload(pid=222))

        progress = control._progress_for_stage(
            "cn_legacy_rebuild_validate",
            stage_started_at="2026-08-19T01:00:00+00:00",
            child_pid=222,
        )

        self.assertEqual(progress["status"], "non_quantified")
        self.assertIsNone(progress["completed"])

    def test_thwiki_progress_preserves_explicit_content_item_states(self) -> None:
        self.write(
            self.thwiki_state,
            {
                "pid": 555,
                "queue_stage_id": "thwiki_arrangement_counts",
                "updated_at": "2026-08-19T01:00:01+00:00",
                "phase": "count_batches",
                "activityLabel": "统计原曲 3–4 的同人曲数量与半年分布",
                "completed": 2,
                "successful": 2,
                "processed": 2,
                "total": 10,
                "remaining": 8,
                "currentSourceIndex": 2,
                "currentSourceName": "原曲 3–4",
                "currentQuery": "曲目原曲计数、Vocal 计数、发售日期半年聚合",
                "interfaceFamily": "THBWiki Semantic MediaWiki 聚合计数接口",
                "contentItems": [
                    {"id": "catalog", "label": "目录", "status": "completed", "current": False},
                    {"id": "batch-1", "label": "原曲 1–2", "status": "completed", "current": False},
                    {"id": "batch-2", "label": "原曲 3–4", "status": "current", "current": True},
                    {"id": "batch-3", "label": "原曲 5–6", "status": "pending", "current": False},
                ],
            },
        )

        progress = control._progress_for_stage(
            "thwiki_arrangement_counts",
            stage_started_at="2026-08-19T01:00:00+00:00",
            child_pid=555,
        )

        self.assertEqual(progress["status"], "active")
        self.assertEqual(progress["percent"], 20.0)
        self.assertEqual(progress["currentSourceName"], "原曲 3–4")
        self.assertEqual(
            progress["interfaceFamily"],
            "THBWiki Semantic MediaWiki 聚合计数接口",
        )
        self.assertEqual(
            [item["status"] for item in progress["contentItems"]],
            ["completed", "completed", "current", "pending"],
        )
        self.assertTrue(progress["contentItems"][2]["current"])

    def test_queue_tasks_keep_order_and_distinguish_kind_and_status(self) -> None:
        stages = [
            {"id": "one", "label": "抓取", "kind": "crawl"},
            {"id": "two", "label": "整理", "kind": "transform"},
            {"id": "three", "label": "校验", "kind": "validation"},
        ]
        state = {
            "completed_stages": ["one"],
            "current_stage": {"id": "two", "status": "running", "attempt": 2},
            "stage_attempts": {"one": 1, "two": 2},
            "stage_failures": {"one": 3},
        }

        tasks = control._queue_tasks(
            stages,
            state,
            effective_status="running",
            runner_alive=True,
            progress={"status": "initializing"},
        )

        self.assertEqual([item["id"] for item in tasks], ["one", "two", "three"])
        self.assertEqual(
            [item["status"] for item in tasks],
            ["completed", "running", "pending"],
        )
        self.assertEqual([item["kind"] for item in tasks], ["crawl", "transform", "validation"])
        self.assertFalse(tasks[0]["isCurrent"])
        self.assertTrue(tasks[1]["isCurrent"])


class LogTailTests(unittest.TestCase):
    def test_stage_tail_excludes_errors_from_previous_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "stage.log"
            path.write_text(
                "\n".join(
                    (
                        "2026-08-19T00:00:00+00:00 START attempt=7 command=[]",
                        "ERROR stale WinError 10013",
                        "2026-08-19T00:01:00+00:00 END attempt=7 exit_code=143",
                        "2026-08-19T00:02:00+00:00 START attempt=8 command=[]",
                        "current progress",
                    )
                ),
                encoding="utf-8",
            )

            value = control.tail_stage_attempt(path, 8, max_lines=120)

        self.assertIn("START attempt=8", value)
        self.assertIn("current progress", value)
        self.assertNotIn("WinError 10013", value)
        self.assertNotIn("attempt=7", value)


class ControlActionTests(unittest.TestCase):
    def test_reopen_stale_completion_clears_invalid_stage_and_unknown_downstream(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata = root / "metadata"
            metadata.mkdir()
            config_path = metadata / "data_crawl_queue.json"
            state_path = metadata / "data_crawl_queue_state.json"
            artifact = metadata / "coverage.json"
            artifact.write_text(json.dumps({"complete": False}), encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "stages": [
                            {
                                "id": "first",
                                "success_checks": [],
                            },
                            {
                                "id": "second",
                                "success_checks": [
                                    {
                                        "type": "json_path_equals",
                                        "path": "metadata/coverage.json",
                                        "json_path": ["complete"],
                                        "equals": True,
                                    }
                                ],
                            },
                            {"id": "third", "success_checks": []},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "status": "complete",
                        "completed_stages": ["first", "second", "third", "unknown"],
                        "completed_at": "old",
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.object(control, "WORKSPACE", root),
                mock.patch.object(control, "CONFIG_PATH", config_path),
                mock.patch.object(control, "STATE_PATH", state_path),
            ):
                ok, reason = control._reopen_stale_completion()
            persisted = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertFalse(ok)
        self.assertIn("second", reason)
        self.assertEqual(persisted["status"], "queued")
        self.assertEqual(persisted["completed_stages"], ["first"])
        self.assertNotIn("completed_at", persisted)

    def test_rebenchmark_resets_only_target_speed_and_preserves_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "queue.json"
            lock_path = root / "control.lock"
            profile_path = root / "adaptive-profiles.json"
            run_state_path = root / "run-state.json"

            config = sample_config()
            advanced = next(
                stage
                for stage in config["stages"]
                if stage["id"] == "cn_legacy_advanced"
            )
            advanced.update(
                {
                    "worker_ceiling": 8,
                    "request_limit_ceiling": 30,
                    "batch_pause_ceiling": 3.0,
                }
            )
            pause_index = advanced["command"].index("--batch-pause")
            advanced["command"][pause_index + 1] = "2"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            config_before = config_path.read_bytes()

            other_profile = {
                "adaptive_workers": 6,
                "adaptive_safe_worker_ceiling": 6,
                "adaptive_batch_pause_seconds": 1.5,
            }
            profile_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "stages": {
                            "cn_legacy_advanced": {
                                "adaptive_workers": 1,
                                "adaptive_safe_worker_ceiling": 1,
                                "adaptive_batch_pause_seconds": 3.0,
                                "adaptive_safe_pause_floor_seconds": 15.0,
                            },
                            "cn_legacy_remaining": other_profile,
                        },
                    }
                ),
                encoding="utf-8",
            )
            checkpoint = {
                "queue_stage_id": "cn_legacy_advanced",
                "phase": "v8 advanced questionnaire unordered pairs",
                "phase_total": 8328,
                "phase_completed_this_run": 1917,
                "phase_remaining": 6411,
                "successful_or_skipped": 1917,
                "failed": 3,
                "resumable": True,
                "satisfied_by_local_source": 37,
                "workers": 1,
                "configured_workers": 2,
                "adaptive_tuning": True,
                "adaptive_worker_ceiling": 8,
                "adaptive_safe_worker_ceiling": 1,
                "adaptive_workers": 1,
                "request_limit_ceiling": 30,
                "adaptive_batch_pause_ceiling_seconds": 3.0,
                "adaptive_pause_floor_seconds": 0.25,
                "adaptive_safe_pause_floor_seconds": 15.0,
                "adaptive_batch_pause_seconds": 15.0,
                "adaptive_success_streak": 14,
                "adaptive_recovery_at": 40673.9,
                "adaptive_failure_wave_active": True,
                "minimum_seconds_between_request_starts": 15.0,
                "request_limit": 20,
                "batch_size": 20,
                "batch_pause_seconds": 2.0,
                "stopped_reason": "transient circuit breaker: HTTP 504",
            }
            run_state_path.write_text(json.dumps(checkpoint), encoding="utf-8")
            stopped = {"ok": True, "action": "stopped"}
            started = {"ok": True, "action": "started"}

            with (
                mock.patch.object(control, "CONFIG_PATH", config_path),
                mock.patch.object(control, "CONTROL_LOCK_PATH", lock_path),
                mock.patch.object(
                    control, "LEGACY_ADAPTIVE_PROFILE", profile_path
                ),
                mock.patch.object(control, "LEGACY_RUN_STATE", run_state_path),
                mock.patch.object(
                    control, "stop_queue", return_value=stopped
                ) as stop,
                mock.patch.object(
                    control, "start_queue", return_value=started
                ) as start,
            ):
                result = control.rebenchmark_stage(
                    "cn_legacy_advanced", timeout=17.5
                )

            stop.assert_called_once_with(timeout=17.5)
            start.assert_called_once_with()
            self.assertTrue(result["ok"])
            self.assertEqual(result["action"], "rebenchmarked")
            self.assertEqual(config_path.read_bytes(), config_before)
            profiles = json.loads(profile_path.read_text(encoding="utf-8"))
            target_profile = profiles["stages"].get("cn_legacy_advanced")
            if target_profile is not None:
                self.assertEqual(target_profile.get("adaptive_workers", 8), 8)
                self.assertEqual(
                    target_profile.get("adaptive_safe_worker_ceiling", 8), 8
                )
                self.assertEqual(
                    target_profile.get("adaptive_batch_pause_seconds", 2.0), 2.0
                )
                self.assertEqual(
                    target_profile.get("adaptive_safe_pause_floor_seconds", 0.25),
                    0.25,
                )
            self.assertEqual(
                profiles["stages"]["cn_legacy_remaining"], other_profile
            )

            reset = json.loads(run_state_path.read_text(encoding="utf-8"))
            for key in (
                "queue_stage_id",
                "phase",
                "phase_total",
                "phase_completed_this_run",
                "phase_remaining",
                "successful_or_skipped",
                "failed",
                "resumable",
                "satisfied_by_local_source",
            ):
                self.assertEqual(reset[key], checkpoint[key], key)
            # An implementation may remove learned fields or explicitly write
            # their fresh configured values.  Either way, the stale throttle
            # must be impossible for the crawler to restore.
            self.assertEqual(reset.get("workers", 8), 8)
            self.assertEqual(reset.get("adaptive_workers", 8), 8)
            self.assertEqual(reset.get("adaptive_safe_worker_ceiling", 8), 8)
            self.assertEqual(reset.get("adaptive_batch_pause_seconds", 2.0), 2.0)
            self.assertEqual(reset.get("adaptive_safe_pause_floor_seconds", 0.25), 0.25)
            self.assertEqual(reset.get("adaptive_success_streak", 0), 0)
            self.assertEqual(reset.get("adaptive_recovery_at", 0.0), 0.0)
            self.assertEqual(
                reset.get("minimum_seconds_between_request_starts", 0.0), 0.0
            )
            self.assertFalse(reset.get("adaptive_failure_wave_active", False))

    def test_rebenchmark_stop_failure_does_not_clear_or_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile_path = root / "adaptive-profiles.json"
            run_state_path = root / "run-state.json"
            lock_path = root / "control.lock"
            profile_before = b'{"schema_version":1,"stages":{"cn_legacy_advanced":{"adaptive_workers":1}}}\n'
            state_before = b'{"queue_stage_id":"cn_legacy_advanced","phase_remaining":9,"adaptive_workers":1}\n'
            profile_path.write_bytes(profile_before)
            run_state_path.write_bytes(state_before)
            stopped = {"ok": False, "action": "stop_timeout"}

            with (
                mock.patch.object(
                    control, "LEGACY_ADAPTIVE_PROFILE", profile_path
                ),
                mock.patch.object(control, "CONTROL_LOCK_PATH", lock_path),
                mock.patch.object(control, "LEGACY_RUN_STATE", run_state_path),
                mock.patch.object(control, "stop_queue", return_value=stopped),
                mock.patch.object(control, "start_queue") as start,
            ):
                result = control.rebenchmark_stage(
                    "cn_legacy_advanced", timeout=0.25
                )

            self.assertFalse(result["ok"])
            self.assertEqual(result["action"], "rebenchmark_stop_failed")
            self.assertEqual(profile_path.read_bytes(), profile_before)
            self.assertEqual(run_state_path.read_bytes(), state_before)
            start.assert_not_called()

    def test_rebenchmark_does_not_clear_run_state_owned_by_another_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = root / "queue.json"
            profile_path = root / "adaptive-profiles.json"
            run_state_path = root / "run-state.json"
            lock_path = root / "control.lock"
            config_path.write_text(json.dumps(sample_config()), encoding="utf-8")
            profile_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "stages": {
                            "cn_legacy_advanced": {
                                "adaptive_workers": 1,
                                "adaptive_batch_pause_seconds": 15.0,
                            },
                            "cn_legacy_remaining": {
                                "adaptive_workers": 2,
                                "adaptive_batch_pause_seconds": 1.0,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            state_before = {
                "queue_stage_id": "cn_legacy_remaining",
                "phase": "v6 item APIs",
                "phase_remaining": 23,
                "workers": 1,
                "adaptive_workers": 1,
                "adaptive_batch_pause_seconds": 15.0,
            }
            run_state_path.write_text(json.dumps(state_before), encoding="utf-8")

            with (
                mock.patch.object(control, "CONFIG_PATH", config_path),
                mock.patch.object(control, "CONTROL_LOCK_PATH", lock_path),
                mock.patch.object(
                    control, "LEGACY_ADAPTIVE_PROFILE", profile_path
                ),
                mock.patch.object(control, "LEGACY_RUN_STATE", run_state_path),
                mock.patch.object(
                    control, "stop_queue", return_value={"ok": True, "action": "stopped"}
                ),
                mock.patch.object(
                    control, "start_queue", return_value={"ok": True, "action": "started"}
                ),
            ):
                result = control.rebenchmark_stage(
                    "cn_legacy_advanced", timeout=2.0
                )

            self.assertTrue(result["ok"])
            self.assertEqual(
                json.loads(run_state_path.read_text(encoding="utf-8")),
                state_before,
            )
            profiles = json.loads(profile_path.read_text(encoding="utf-8"))
            self.assertNotIn("cn_legacy_advanced", profiles["stages"])
            self.assertEqual(
                profiles["stages"]["cn_legacy_remaining"]["adaptive_workers"],
                2,
            )

    def test_start_is_single_instance(self) -> None:
        snapshot = {
            "runnerAlive": True,
            "childAlive": True,
            "runnerLockHeld": True,
            "stopRequested": False,
        }
        with (
            mock.patch.object(control, "control_lock", return_value=nullcontext()),
            mock.patch.object(control, "process_snapshot", return_value=snapshot),
            mock.patch.object(control.subprocess, "Popen") as popen,
        ):
            result = control.start_queue()
        self.assertEqual(result["action"], "already_running")
        popen.assert_not_called()

    def test_start_reports_clean_noop_when_queue_is_already_complete(self) -> None:
        """A runner that exits 0 after finding no remaining stage is success."""

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            process = mock.Mock(pid=3516)
            process.poll.return_value = 0
            before = {
                "state": {"status": "complete"},
                "runnerAlive": False,
                "childAlive": False,
                "runnerLockHeld": False,
                "stopRequested": False,
            }
            after = dict(before)
            with (
                mock.patch.object(control, "STOP_PATH", root / "queue.stop"),
                mock.patch.object(control, "LOG_ROOT", root / "logs"),
                mock.patch.object(control, "RUNNER_STDOUT", root / "logs" / "out"),
                mock.patch.object(control, "RUNNER_STDERR", root / "logs" / "err"),
                mock.patch.object(control, "control_lock", return_value=nullcontext()),
                mock.patch.object(control, "process_snapshot", side_effect=[before, after]),
                mock.patch.object(control, "_prepare_resume_after_failure_stop"),
                mock.patch.object(control, "_reopen_stale_completion", return_value=(True, "ok")),
                mock.patch.object(control, "_queue_success_contract", return_value=(True, "ok")),
                mock.patch.object(control.subprocess, "Popen", return_value=process),
            ):
                result = control.start_queue(wait_seconds=0)

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "already_complete")
        self.assertEqual(result["spawnExitCode"], 0)

    def test_start_does_not_accept_zero_exit_when_success_contract_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            process = mock.Mock(pid=3517)
            process.poll.return_value = 0
            snapshot = {
                "state": {"status": "complete"},
                "runnerAlive": False,
                "childAlive": False,
                "runnerLockHeld": False,
                "stopRequested": False,
            }
            with (
                mock.patch.object(control, "STOP_PATH", root / "queue.stop"),
                mock.patch.object(control, "LOG_ROOT", root / "logs"),
                mock.patch.object(control, "RUNNER_STDOUT", root / "logs" / "out"),
                mock.patch.object(control, "RUNNER_STDERR", root / "logs" / "err"),
                mock.patch.object(control, "control_lock", return_value=nullcontext()),
                mock.patch.object(control, "process_snapshot", side_effect=[snapshot, snapshot]),
                mock.patch.object(control, "_prepare_resume_after_failure_stop"),
                mock.patch.object(control, "_reopen_stale_completion", return_value=(False, "stage cn_modern_advanced is missing legacyParityComplete")),
                mock.patch.object(
                    control,
                    "_queue_success_contract",
                    return_value=(False, "stage cn_modern_advanced is missing legacyParityComplete"),
                ),
                mock.patch.object(control.subprocess, "Popen", return_value=process),
            ):
                result = control.start_queue(wait_seconds=0)

        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "start_failed")
        self.assertIn("legacyParityComplete", result["error"])

    def test_start_refuses_recorded_child_identity_conflict(self) -> None:
        snapshot = {
            "state": {"status": control.IDENTITY_CONFLICT_STATUS},
            "runnerAlive": False,
            "childAlive": False,
            "runnerLockHeld": False,
            "stopRequested": False,
        }
        with (
            mock.patch.object(control, "control_lock", return_value=nullcontext()),
            mock.patch.object(control, "process_snapshot", return_value=snapshot),
            mock.patch.object(control.subprocess, "Popen") as popen,
        ):
            result = control.start_queue()
        self.assertFalse(result["ok"])
        self.assertEqual(result["action"], "child_identity_conflict")
        popen.assert_not_called()

    def test_identity_conflict_stop_is_idempotent_and_preserves_state(self) -> None:
        state = {"status": control.IDENTITY_CONFLICT_STATUS}
        snapshot = {
            "state": state,
            "runnerAlive": False,
            "childAlive": False,
            "runnerLockHeld": False,
            "stopRequested": False,
        }
        with (
            mock.patch.object(control, "control_lock", return_value=nullcontext()),
            mock.patch.object(control, "process_snapshot", return_value=snapshot),
            mock.patch.object(control, "atomic_write_text") as write_text,
            mock.patch.object(control, "atomic_write_json") as write_json,
        ):
            result = control.request_stop()
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "already_stopped")
        self.assertEqual(state["status"], control.IDENTITY_CONFLICT_STATUS)
        write_text.assert_not_called()
        write_json.assert_not_called()

    def test_failure_stop_is_idempotent_and_preserves_diagnostics(self) -> None:
        state = {
            "status": "stopped_after_failures",
            "last_error": {"message": "threshold reached"},
        }
        snapshot = {
            "state": state,
            "runnerAlive": False,
            "childAlive": False,
            "runnerLockHeld": False,
            "stopRequested": False,
        }
        with (
            mock.patch.object(control, "control_lock", return_value=nullcontext()),
            mock.patch.object(control, "process_snapshot", return_value=snapshot),
            mock.patch.object(control, "atomic_write_text") as write_text,
            mock.patch.object(control, "atomic_write_json") as write_json,
        ):
            result = control.request_stop()
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "already_stopped")
        self.assertEqual(state["status"], "stopped_after_failures")
        self.assertEqual(state["last_error"]["message"], "threshold reached")
        write_text.assert_not_called()
        write_json.assert_not_called()

    def test_start_removes_only_exact_stop_sentinel_and_uses_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stop_path = root / "queue.stop"
            neighbor = root / "queue.stop.keep"
            stop_path.write_text("stop\n", encoding="utf-8")
            neighbor.write_text("keep\n", encoding="utf-8")
            process = mock.Mock(pid=4321)
            process.poll.return_value = None
            before = {
                "runnerAlive": False,
                "childAlive": False,
                "runnerLockHeld": False,
                "stopRequested": True,
            }
            after = {**before, "stopRequested": False, "runnerAlive": True}
            with (
                mock.patch.object(control, "STOP_PATH", stop_path),
                mock.patch.object(control, "LOG_ROOT", root / "logs"),
                mock.patch.object(control, "RUNNER_STDOUT", root / "logs" / "out"),
                mock.patch.object(control, "RUNNER_STDERR", root / "logs" / "err"),
                mock.patch.object(control, "control_lock", return_value=nullcontext()),
                mock.patch.object(control, "process_snapshot", side_effect=[before, after]),
                mock.patch.object(control, "_prepare_resume_after_failure_stop"),
                mock.patch.object(control, "_reopen_stale_completion", return_value=(True, "ok")),
                mock.patch.object(control.subprocess, "Popen", return_value=process) as popen,
            ):
                result = control.start_queue(wait_seconds=0)
            self.assertTrue(result["ok"])
            self.assertFalse(stop_path.exists())
            self.assertTrue(neighbor.exists())
            command = popen.call_args.args[0]
            self.assertIn("--resume", command)

    def test_request_stop_passes_only_recorded_child_and_identity(self) -> None:
        executable = str(Path("python.exe").resolve())
        identity = {
            "pid": 2468,
            "creation_time_100ns": 123,
            "executable_path": executable,
        }
        state = {
            "current_stage": {
                "id": "legacy",
                "child_pid": 2468,
                "child_identity": identity,
            }
        }
        snapshot = {
            "state": state,
            "runnerAlive": True,
            "childAlive": True,
            "runnerLockHeld": True,
            "stopRequested": False,
            "childPid": 2468,
        }
        with tempfile.TemporaryDirectory() as temporary:
            stop_path = Path(temporary) / "queue.stop"
            with (
                mock.patch.object(control, "STOP_PATH", stop_path),
                mock.patch.object(control, "control_lock", return_value=nullcontext()),
                mock.patch.object(control, "process_snapshot", return_value=snapshot),
                mock.patch.object(
                    stop_helper,
                    "terminate_process",
                    return_value=(True, "identity_verified:sent"),
                ) as terminate,
            ):
                result = control.request_stop()
        terminate.assert_called_once_with(2468, expected_identity=identity)
        self.assertTrue(result["childTerminationOk"])

    def test_repeated_stop_is_idempotent_when_nothing_is_running(self) -> None:
        snapshot = {
            "runnerAlive": False,
            "childAlive": False,
            "runnerLockHeld": False,
            "stopRequested": True,
        }
        with (
            mock.patch.object(control, "control_lock", return_value=nullcontext()),
            mock.patch.object(control, "process_snapshot", return_value=snapshot),
            mock.patch.object(control, "atomic_write_text") as write,
            mock.patch.object(stop_helper, "terminate_process") as terminate,
        ):
            result = control.request_stop()
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "already_stopped")
        write.assert_not_called()
        terminate.assert_not_called()


class ProcessIdentityTests(unittest.TestCase):
    def test_current_process_identity_round_trip(self) -> None:
        identity = stop_helper.process_identity(os.getpid())
        self.assertIsNotNone(identity)
        matched, detail = stop_helper.identities_match(identity, identity)
        self.assertTrue(matched, detail)

    def test_creation_time_mismatch_is_rejected_before_signal(self) -> None:
        expected = {
            "pid": 123,
            "creation_time_100ns": 1,
            "executable_path": "/python",
        }
        actual = {**expected, "creation_time_100ns": 2}
        with (
            mock.patch.object(stop_helper, "process_alive", return_value=True),
            mock.patch.object(stop_helper, "process_identity", return_value=actual),
            mock.patch.object(stop_helper.sys, "platform", "linux"),
            mock.patch.object(stop_helper.os, "kill") as kill,
        ):
            ok, detail = stop_helper.terminate_process(
                123, expected_identity=expected
            )
        self.assertFalse(ok)
        self.assertIn("creation time mismatch", detail)
        kill.assert_not_called()

    def test_legacy_bare_pid_is_refused(self) -> None:
        with (
            mock.patch.object(stop_helper, "process_alive", return_value=True),
            mock.patch.object(stop_helper.sys, "platform", "linux"),
            mock.patch.object(stop_helper.os, "kill") as kill,
        ):
            ok, detail = stop_helper.terminate_process(123)
        self.assertFalse(ok)
        self.assertIn("identity_refused", detail)
        kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
